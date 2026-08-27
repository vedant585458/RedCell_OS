#!/usr/bin/env node

/**
 * RedCell_OS — Local Process Supervisor & Unified Launcher
 *
 * Spawns, health-checks, supervises, and auto-restarts the Python backend
 * using the resilient BackendSupervisor class, while managing the React/Vite frontend.
 */

const { spawn, execSync } = require("child_process");
const path = require("path");
const { BackendSupervisor } = require("./supervisor");

// Configuration defaults
const ROOT_DIR = path.resolve(__dirname, "..");
const BACKEND_HOST = process.env.REDCELL_HOST || "0.0.0.0";
const BACKEND_PORT = parseInt(process.env.REDCELL_PORT || "8000", 10);
const FRONTEND_PORT = parseInt(process.env.FRONTEND_PORT || "5173", 10);

// ANSI color formatting
const COLORS = {
  reset: "\x1b[0m",
  bold: "\x1b[1m",
  blue: "\x1b[34m",
  green: "\x1b[32m",
  yellow: "\x1b[33m",
  red: "\x1b[31m",
  cyan: "\x1b[36m",
  gray: "\x1b[90m",
};

function logLauncher(msg, color = COLORS.cyan) {
  const timestamp = new Date().toISOString().substring(11, 19);
  console.log(`${COLORS.gray}[${timestamp}]${COLORS.reset} ${color}${COLORS.bold}[LAUNCHER]${COLORS.reset} ${msg}`);
}

function logBackend(text) {
  const lines = text.trim().split("\n");
  for (const line of lines) {
    if (line.trim()) {
      console.log(`${COLORS.blue}[BACKEND]${COLORS.reset} ${line}`);
    }
  }
}

function logFrontend(data) {
  const lines = data.toString().trim().split("\n");
  for (const line of lines) {
    if (line.trim()) {
      console.log(`${COLORS.green}[FRONTEND]${COLORS.reset} ${line}`);
    }
  }
}

let supervisor = null;
let frontendProc = null;
let isShuttingDown = false;

function killFrontend() {
  if (frontendProc && frontendProc.pid && !frontendProc.killed) {
    logLauncher(`Terminating Frontend (PID: ${frontendProc.pid})...`, COLORS.yellow);
    try {
      if (process.platform === "win32") {
        execSync(`taskkill /pid ${frontendProc.pid} /T /F 2>nul`);
      } else {
        process.kill(-frontendProc.pid, "SIGTERM");
        setTimeout(() => {
          try {
            process.kill(-frontendProc.pid, "SIGKILL");
          } catch (_) {}
        }, 300);
      }
    } catch (_) {}
  }
}

function shutdown(exitCode = 0) {
  if (isShuttingDown) return;
  isShuttingDown = true;

  console.log("");
  logLauncher("Initiating graceful shutdown of all supervised services...", COLORS.yellow);
  if (supervisor) {
    supervisor.stop();
  }
  killFrontend();

  setTimeout(() => {
    logLauncher("All services stopped. Exiting cleanly.", COLORS.green);
    process.exit(exitCode);
  }, 500);
}

// Signal handlers
process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));
process.on("SIGHUP", () => shutdown(0));
process.on("uncaughtException", (err) => {
  logLauncher(`Uncaught fatal exception: ${err.message}`, COLORS.red);
  console.error(err);
  shutdown(1);
});

async function start() {
  logLauncher("==================================================", COLORS.cyan);
  logLauncher("   RedCell_OS — AI Multi-Agent Simulator Launcher  ", COLORS.cyan);
  logLauncher("==================================================", COLORS.cyan);

  const isBackendOnly = process.argv.includes("--backend-only");
  const isFrontendOnly = process.argv.includes("--frontend-only");

  // 1. Initialize and Start Backend Supervisor
  if (!isFrontendOnly) {
    supervisor = new BackendSupervisor({
      maxRestartsInWindow: 5,
      windowMs: 60000,
      initialBackoffMs: 500,
    });

    supervisor.on("log", (event) => {
      const color = event.level === "error" ? COLORS.red : event.level === "warn" ? COLORS.yellow : COLORS.cyan;
      logLauncher(event.text, color);
    });

    supervisor.on("stdout", logBackend);
    supervisor.on("stderr", logBackend);

    supervisor.on("circuit_tripped", (data) => {
      logLauncher(`🚨 BACKEND CIRCUIT BREAKER TRIPPED: ${data.reason}`, COLORS.red);
      logLauncher("Frontend will reflect failure state. Manual inspection required.", COLORS.yellow);
    });

    supervisor.on("healthy", (info) => {
      logLauncher(`Backend is healthy on http://${BACKEND_HOST}:${info.port} (PID: ${info.pid})`, COLORS.green);
    });

    await supervisor.start();
  }

  // 2. Launch Frontend
  if (!isBackendOnly) {
    logLauncher(`Spawning Vite frontend on port ${FRONTEND_PORT}...`, COLORS.cyan);

    const frontendCwd = path.join(ROOT_DIR, "frontend");
    frontendProc = spawn(
      "npm",
      ["run", "dev", "--", "--host", "0.0.0.0", "--port", String(FRONTEND_PORT)],
      {
        cwd: frontendCwd,
        env: process.env,
        detached: process.platform !== "win32",
        stdio: ["ignore", "pipe", "pipe"],
      }
    );

    frontendProc.stdout.on("data", logFrontend);
    frontendProc.stderr.on("data", logFrontend);

    frontendProc.on("exit", (code) => {
      if (!isShuttingDown) {
        logLauncher(`Frontend exited with code ${code}`, COLORS.yellow);
        shutdown(code || 0);
      }
    });
  }

  logLauncher("🚀 RedCell_OS application services are live and supervised!", COLORS.green);
  logLauncher(`   Backend API:   http://${BACKEND_HOST}:${BACKEND_PORT}`, COLORS.blue);
  logLauncher(`   Frontend Web:  http://0.0.0.0:${FRONTEND_PORT}`, COLORS.green);
  logLauncher(`   Status File:   ${path.resolve(__dirname, "../data/supervisor_status.json")}`, COLORS.gray);
  logLauncher("   Press Ctrl+C at any time to gracefully terminate all services.", COLORS.gray);
}

start();
