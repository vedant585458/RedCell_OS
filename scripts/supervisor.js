/**
 * RedCell_OS — Backend Process Supervisor with Exponential Backoff and Circuit Breaker
 *
 * Wraps the Python backend in a resilient supervisory loop that:
 * 1. Automatically restarts on unexpected process exits with exponential backoff.
 * 2. Enforces a sliding-window circuit breaker (max N crashes in window T) to prevent infinite loops.
 * 3. Persists and exposes supervisor status for frontend and IPC consumption.
 * 4. Guarantees zero orphaned child processes via POSIX process groups.
 */

const { spawn, execSync } = require("child_process");
const http = require("http");
const fs = require("fs");
const path = require("path");
const EventEmitter = require("events");

// Default configuration
const DEFAULT_CONFIG = {
  maxRestartsInWindow: 5,
  windowMs: 60000, // 1 minute sliding window
  initialBackoffMs: 500,
  maxBackoffMs: 8000,
  backoffMultiplier: 2.0,
  healthCheckIntervalMs: 250,
  healthCheckMaxAttempts: 40,
  statusFilePath: path.resolve(__dirname, "../data/supervisor_status.json"),
};

class BackendSupervisor extends EventEmitter {
  constructor(options = {}) {
    super();
    this.config = { ...DEFAULT_CONFIG, ...options };
    this.rootDir = path.resolve(__dirname, "..");
    this.host = process.env.REDCELL_HOST || "0.0.0.0";
    this.port = parseInt(process.env.REDCELL_PORT || "8000", 10);
    this.healthUrl = `http://127.0.0.1:${this.port}/health`;

    this.process = null;
    this.pid = null;
    this.state = "STOPPED"; // STOPPED | STARTING | HEALTHY | RESTARTING | CIRCUIT_TRIPPED
    this.crashTimestamps = [];
    this.currentBackoffMs = this.config.initialBackoffMs;
    this.isIntentionalShutdown = false;
    this.lastCrashReason = null;
    this.lastCrashTime = null;
    this.errorMessage = null;

    // Ensure data directory exists for status file
    const dataDir = path.dirname(this.config.statusFilePath);
    if (!fs.existsSync(dataDir)) {
      fs.mkdirSync(dataDir, { recursive: true });
    }

    this._updateStatus();
  }

  getStatus() {
    this._pruneOldCrashes();
    return {
      status: this.state,
      pid: this.pid,
      host: this.host,
      port: this.port,
      restartsInWindow: this.crashTimestamps.length,
      maxRestarts: this.config.maxRestartsInWindow,
      windowSeconds: this.config.windowMs / 1000,
      currentBackoffMs: this.currentBackoffMs,
      lastCrashReason: this.lastCrashReason,
      lastCrashTime: this.lastCrashTime,
      circuitTripped: this.state === "CIRCUIT_TRIPPED",
      errorMessage: this.errorMessage,
      timestampUtc: new Date().toISOString(),
    };
  }

  _updateStatus() {
    try {
      const status = this.getStatus();
      fs.writeFileSync(this.config.statusFilePath, JSON.stringify(status, null, 2), "utf8");
      this.emit("status", status);
    } catch (_) {
      // Ignore file write errors during shutdown
    }
  }

  _pruneOldCrashes() {
    const now = Date.now();
    this.crashTimestamps = this.crashTimestamps.filter(
      (ts) => now - ts < this.config.windowMs
    );
  }

  async start() {
    this.isIntentionalShutdown = false;
    await this._spawnProcess();
  }

  async _spawnProcess() {
    if (this.isIntentionalShutdown) return;

    this.state = "STARTING";
    this._updateStatus();

    const pythonEnv = {
      ...process.env,
      PYTHONPATH: `${this.rootDir}/backend/src:${process.env.PYTHONPATH || ""}`,
      PYTHONUNBUFFERED: "1",
      REDCELL_HOST: this.host,
      REDCELL_PORT: String(this.port),
    };

    this.emit("log", { source: "supervisor", level: "info", text: `Spawning backend process on ${this.host}:${this.port}...` });

    this.process = spawn(
      "python3",
      ["-m", "app.main", "--host", this.host, "--port", String(this.port)],
      {
        cwd: this.rootDir,
        env: pythonEnv,
        detached: process.platform !== "win32",
        stdio: ["ignore", "pipe", "pipe"],
      }
    );

    this.pid = this.process.pid;
    this.emit("log", { source: "supervisor", level: "info", text: `Backend process active with PID: ${this.pid}` });

    this.process.stdout.on("data", (data) => {
      this.emit("stdout", data.toString());
    });

    this.process.stderr.on("data", (data) => {
      this.emit("stderr", data.toString());
    });

    this.process.on("exit", (code, signal) => {
      this._handleProcessExit(code, signal);
    });

    // Run health check verification
    try {
      await this._verifyHealth();
      this.state = "HEALTHY";
      this.currentBackoffMs = this.config.initialBackoffMs; // Reset backoff on healthy
      this.errorMessage = null;
      this._updateStatus();
      this.emit("healthy", { pid: this.pid, port: this.port });
    } catch (err) {
      if (!this.isIntentionalShutdown) {
        this.emit("log", { source: "supervisor", level: "error", text: `Health check failed during startup: ${err.message}` });
      }
    }
  }

  _handleProcessExit(code, signal) {
    const oldPid = this.pid;
    this.pid = null;
    this.process = null;

    if (this.isIntentionalShutdown) {
      this.state = "STOPPED";
      this._updateStatus();
      return;
    }

    const reason = signal ? `Killed by signal ${signal}` : `Exited with exit code ${code}`;
    this.lastCrashReason = reason;
    this.lastCrashTime = new Date().toISOString();
    this.crashTimestamps.push(Date.now());
    this._pruneOldCrashes();

    this.emit("log", {
      source: "supervisor",
      level: "warn",
      text: `Backend process (PID: ${oldPid}) died: ${reason}. Total crashes in 60s: ${this.crashTimestamps.length}`,
    });

    // Check Circuit Breaker
    if (this.crashTimestamps.length >= this.config.maxRestartsInWindow) {
      this.state = "CIRCUIT_TRIPPED";
      this.errorMessage = `Backend crashed ${this.crashTimestamps.length} times within ${this.config.windowMs / 1000}s. Circuit breaker tripped to prevent infinite restart loop.`;
      this._updateStatus();
      this.emit("circuit_tripped", {
        reason: this.errorMessage,
        crashCount: this.crashTimestamps.length,
      });
      this.emit("log", { source: "supervisor", level: "error", text: `🚨 ${this.errorMessage}` });
      return;
    }

    // Schedule exponential backoff restart
    this.state = "RESTARTING";
    const delay = this.currentBackoffMs;
    this.currentBackoffMs = Math.min(
      this.currentBackoffMs * this.config.backoffMultiplier,
      this.config.maxBackoffMs
    );
    this._updateStatus();

    this.emit("log", {
      source: "supervisor",
      level: "info",
      text: `Scheduling backend restart in ${delay}ms (attempt ${this.crashTimestamps.length}/${this.config.maxRestartsInWindow})...`,
    });

    setTimeout(() => {
      if (!this.isIntentionalShutdown && this.state !== "CIRCUIT_TRIPPED") {
        this._spawnProcess();
      }
    }, delay);
  }

  _verifyHealth() {
    return new Promise((resolve, reject) => {
      let attempts = 0;
      const interval = this.config.healthCheckIntervalMs;
      const maxAttempts = this.config.healthCheckMaxAttempts;

      const check = () => {
        if (this.isIntentionalShutdown || !this.process) {
          return reject(new Error("Supervisor stopped during health check"));
        }

        attempts++;
        const req = http.get(this.healthUrl, (res) => {
          if (res.statusCode === 200) {
            resolve(true);
          } else {
            retry();
          }
        });

        req.on("error", () => {
          retry();
        });

        req.setTimeout(200, () => {
          req.destroy();
          retry();
        });
      };

      const retry = () => {
        if (attempts >= maxAttempts) {
          reject(new Error(`Backend failed to respond at ${this.healthUrl} after ${maxAttempts * interval}ms`));
        } else {
          setTimeout(check, interval);
        }
      };

      check();
    });
  }

  stop() {
    this.isIntentionalShutdown = true;
    this.state = "STOPPED";
    this._updateStatus();

    if (this.process && this.process.pid && !this.process.killed) {
      try {
        if (process.platform === "win32") {
          execSync(`taskkill /pid ${this.process.pid} /T /F 2>nul`);
        } else {
          process.kill(-this.process.pid, "SIGTERM");
          setTimeout(() => {
            try {
              if (this.process && this.process.pid) {
                process.kill(-this.process.pid, "SIGKILL");
              }
            } catch (_) {}
          }, 300);
        }
      } catch (_) {}
    }
    this.pid = null;
    this.process = null;
  }
}

module.exports = { BackendSupervisor, DEFAULT_CONFIG };
