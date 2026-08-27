# ADR-008: Desktop Shell Architecture and Process Launcher Strategy

**Status:** Accepted  
**Date:** August 2026  
**Milestone Reference:** M017  
**Phase:** P04 — Local Application Bootstrap  
**Context Link:** [VISION.md](../../VISION.md), [ADR-001-backend-runtime.md](ADR-001-backend-runtime.md), [ADR-002-frontend-stack.md](ADR-002-frontend-stack.md)  

---

## 1. Context & Problem Statement

RedCell_OS is a local-first system pairing a React + PixiJS frontend office simulation with a Python FastAPI multi-agent orchestration backend.

A core operational requirement is:
> **"The application must automatically launch, health-check, supervise, and cleanly terminate the Python backend alongside the frontend, guaranteeing zero orphaned zombie processes upon exit."**

We must evaluate desktop shell and process supervision strategies for:
1. **Developer / CLI Workflow:** Running frontend and backend simultaneously with a single command.
2. **Packaged Standalone Desktop Distribution:** Bundling the entire system into a single executable binary for macOS, Linux, and Windows operators.

---

## 2. Decision Drivers

1. **Zero-Orphan Process Guarantee:** Terminating the frontend or launcher (via `Ctrl+C`, window close, crash, or `SIGTERM`) must instantly kill all child backend processes, agent scratchpad subprocesses, and network sockets.
2. **Lightweight Footprint & Fast Startup:** Minimal RAM consumption and disk bundle size (avoiding bloated multi-hundred-megabyte runtimes).
3. **Automated Health-Check Supervision:** Launcher must actively poll the backend `GET /health` endpoint and signal readiness to the frontend before routing requests.
4. **Unified Telemetry Stream:** Multiplexed console output with prefixed labels (`[BACKEND]`, `[FRONTEND]`) for real-time developer diagnostics.
5. **Cross-Platform Compatibility:** Seamless execution across Linux, macOS, and Windows workstations.

---

## 3. Decision: The Dual-Layer Launcher Strategy

We decide to adopt a **Dual-Layer Launcher Architecture**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       LAUNCHER & DESKTOP ARCHITECTURE                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Layer 1: Development & CLI Supervisor (`scripts/launch.js`)                │
│  • Node.js Child Process Supervisor utilizing POSIX Process Groups          │
│  • Spawns Python backend (`python3 -m app.main`) and Vite dev server        │
│  • Health-check polling (`/health`), stream multiplexing, graceful cleanup  │
│                                                                             │
│  Layer 2: Packaged Desktop Shell (Tauri v2 + Rust Sidecar — Phase P73)      │
│  • Lightweight Rust desktop shell leveraging OS-native WebViews (WebKit/WV2)│
│  • Bundles Python virtualenv runtime as a managed Tauri Sidecar process     │
│  • OS-level Parent-Death Signals (PR_SET_PDEATHSIG) preventing orphans      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Desktop Shell Evaluation Matrix

| Criterion | Selected: Tauri v2 + Rust Sidecar (Desktop) | Node.js Supervisor (Dev/CLI) | Alternative: Electron Desktop Shell |
|---|---|---|---|
| **Binary Bundle Size** | $\sim 15 - 25\text{ MB}$ (Lightweight) | Zero bundle (script) | $\sim 120 - 200\text{ MB}$ (Bloated) |
| **Idle Memory Overhead** | $\sim 40 - 60\text{ MB}$ RAM | $\sim 30\text{ MB}$ RAM | $\sim 350 - 500\text{ MB}$ RAM |
| **Sidecar Process Control** | Native Rust process lifecycle & `kill_on_drop` | POSIX Process Groups (`-pid`) | Node `child_process` in Electron main |
| **Startup Latency** | $< 300\text{ ms}$ | $< 500\text{ ms}$ | $2000 - 4000\text{ ms}$ (Chromium init) |
| **Security & Permissions** | Rust IPC allowlists, zero Node APIs in renderer | Developer-focused | Full Node.js integration risk in renderer |

### Why Electron Was Rejected:
Electron bundles a dedicated Chromium instance and Node runtime, adding over $150\text{ MB}$ to the binary and consuming $> 400\text{ MB}$ of baseline RAM before even launching the Python multi-agent backend. Tauri uses the operating system's native webview (WebKit on macOS/Linux, WebView2 on Windows), reducing bundle size by $85\%$ and idle RAM usage by $80\%$.

---

## 5. Development Supervisor (`scripts/launch.js`) Specification

The Node.js launcher `scripts/launch.js` implements comprehensive process supervision:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      PROCESS SUPERVISOR LIFECYCLE                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. Spawn Backend Process                                                   │
│     • Command: `python3 -m app.main --host 0.0.0.0 --port 8000`             │
│     • Process Group: `detached: true` creates distinct PGID                 │
│                                                                             │
│  2. Health-Check Polling Loop                                               │
│     • Poll `http://127.0.0.1:8000/health` every 100ms (max 10s timeout)     │
│     • On HTTP 200 OK: proceed to spawn frontend                             │
│                                                                             │
│  3. Spawn Frontend Dev Server                                               │
│     • Command: `npm run dev -- --host 0.0.0.0 --port 5173`                  │
│                                                                             │
│  4. Stream Multiplexing & Signal Trapping                                  │
│     • Prefix logs with `[BACKEND]` and `[FRONTEND]`                         │
│     • Trap `SIGINT`, `SIGTERM`, `SIGHUP`, `exit`, `uncaughtException`       │
│     • Broadcast `process.kill(-backendPid, 'SIGKILL')`                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.1 POSIX Process Group Termination
To avoid leaving zombie child processes (e.g., if the backend spawned an `nmap` or `nuclei` subprocess), the launcher spawns processes with `detached: true` and terminates the entire process group by negating the process ID (`-proc.pid`):

```javascript
function killProcessGroup(proc, name) {
  if (proc && proc.pid && !proc.killed) {
    try {
      if (process.platform === 'win32') {
        execSync(`taskkill /pid ${proc.pid} /T /F`);
      } else {
        process.kill(-proc.pid, 'SIGKILL');
      }
    } catch (err) {
      // Process already exited
    }
  }
}
```

---

## 6. Consequences & Trade-offs

### Positive Consequences
- **Single-Command Startup:** Running `npm start` or `node scripts/launch.js` starts the complete environment with unified logs.
- **Fail-Safe Cleanup:** Zero orphaned backend processes, even on unexpected terminal closure or unhandled exceptions.
- **Tauri Readiness:** The decoupled frontend/backend structure makes wrapping into Tauri v2 in Phase P73 completely frictionless.

### Negative Consequences & Mitigations
- **Windows vs POSIX Process Differences:** Process group signals differ on Windows.
  - *Mitigation:* `scripts/launch.js` detects `process.platform` and uses `taskkill /T /F` on Windows and `process.kill(-pid)` on POSIX systems.

---

## 7. Review & Acceptance

- **Accepted By:** RedCell_OS Architecture Review Board
- **Traceability:** Fulfills milestone **M017**, completing Phase P04 (Local Application Bootstrap).
