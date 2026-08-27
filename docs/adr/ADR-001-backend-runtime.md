# ADR-001: Backend Runtime, Control Plane Framework, and Process Supervision Model

**Status:** Accepted  
**Date:** August 2026  
**Milestone Reference:** M005  
**Phase:** P02 — Architecture and Technology Decisions  
**Context Link:** [VISION.md](../../VISION.md), [SECURITY_CONSTRAINTS.md](../../SECURITY_CONSTRAINTS.md)  

---

## 1. Context & Problem Statement

RedCell_OS is a local-first, event-driven multi-agent penetration testing organization simulator. The backend must orchestrate multiple concurrent AI agents, stream sub-100ms real-time event updates over WebSockets to a React frontend, execute external security tools (e.g., `nmap`, `nuclei`, custom Python PoC runners), and maintain strict process isolation and deterministic emergency kill-switch control ($< 200\text{ ms}$ SLA).

The key architectural challenge is:
> **"Coordinating asynchronous, stateful, sandboxed agent execution with a real-time, event-driven frontend that never fabricates state independently of backend truth."**

We must choose the core backend language runtime, HTTP/WebSocket control-plane framework, asynchronous task execution model, and agent process supervision architecture.

---

## 2. Decision Drivers

1. **Native WebSocket Streaming & High I/O Concurrency:** Continuous bi-directional event streaming to the React office frontend and concurrent non-blocking LLM API calls.
2. **Strict Process & Workspace Isolation:** Malfunctioning tools, segfaults, memory leaks, or unhandled exceptions in agent tasks must never destabilize the central orchestrator.
3. **Instantaneous Kill Switch ($< 200\text{ ms}$):** Parent supervisor must have direct OS-level control to terminate child processes (`SIGKILL`/`SIGTERM` to process groups) immediately.
4. **Local-First & Zero-Friction Bootstrap:** The entire backend must boot with a single command without requiring external daemons (e.g., Redis, RabbitMQ, Celery brokers) on the operator's machine.
5. **Type Safety & Schema Validation:** High reliability for complex ROE manifests, agent state machines, and structured tool outputs.

---

## 3. Decision

We decide to adopt:

1. **Language & Runtime:** **Python 3.11+ with Native `asyncio`**
   - High-throughput asynchronous event loop managing non-blocking I/O (WebSockets, HTTP requests, file I/O, IPC).
2. **Control-Plane Framework:** **FastAPI + Uvicorn**
   - High-performance ASGI framework providing automatic OpenAPI docs, native WebSocket connection management, and Pydantic v2 data validation for ROE schemas and agent events.
3. **Process Supervision Model:** **Parent Orchestrator + Subprocess-per-Agent-Workspace**
   - The FastAPI/`asyncio` parent process supervises agent lifecycles and dispatches CLI tools / agent scripts inside dedicated OS subprocesses (`asyncio.create_subprocess_exec` / `asyncio.create_subprocess_shell`).
   - Every agent workspace executes in a distinct OS process group (`start_new_session=True` / `setpgrp`), enabling instantaneous, non-blocking termination via `os.killpg(pgid, signal.SIGKILL)`.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       BACKEND RUNTIME ARCHITECTURE                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                    FastAPI Control Plane (Uvicorn)                    │  │
│  │  • REST Endpoints (ROE Ingestion, Config, Report Export)              │  │
│  │  • WebSocket Hub (Real-time Event Stream -> React Frontend)           │  │
│  └───────────────────────────────────┬───────────────────────────────────┘  │
│                                      │                                      │
│  ┌───────────────────────────────────┴───────────────────────────────────┐  │
│  │             Asyncio Orchestrator & Task Supervisor Core               │  │
│  │  • DAG Dependency Engine & FSM Lifecycle Manager                      │  │
│  │  • Event Store (SQLite WAL + Merkle Chaining)                         │  │
│  │  • Human Approval Gate Dispatcher                                     │  │
│  │  • Global / Agent Process Registry & Kill-Switch Controller          │  │
│  └───────┬───────────────────────────┬───────────────────────────┬───────┘  │
│          │                           │                           │          │
│          ▼                           ▼                           ▼          │
│  ┌───────────────┐           ┌───────────────┐           ┌───────────────┐  │
│  │ Subprocess PG │           │ Subprocess PG │           │ Subprocess PG │  │
│  │ (Agent Recon) │           │ (Agent Vuln)  │           │(Agent Report) │  │
│  │ Workspace A   │           │ Workspace B   │           │ Workspace C   │  │
│  │ PGID: 10451   │           │ PGID: 10452   │           │ PGID: 10453   │  │
│  └───────────────┘           └───────────────┘           └───────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Evaluated Alternatives

| Dimension | Option A: FastAPI + asyncio + Subprocesses (CHOSEN) | Option B: Flask + Threading / Gevent | Option C: Celery + Redis / RabbitMQ | Option D: Rust / Go Native Sidecar |
|---|---|---|---|---|
| **Real-time WebSockets** | Native, high-concurrency async WS | Cumbersome (requires gevent/eventlet monkey-patching) | Requires separate WS server (e.g. Socket.IO) | Native, high performance |
| **Process Isolation** | Full OS process group isolation per agent | None (threads share address space; GIL locks) | Worker processes isolated, but overhead is high | Strong process isolation |
| **Kill-Switch Latency** | $< 10\text{ ms}$ (`os.killpg` SIGKILL) | Impossible to reliably kill running threads in Python | High ($> 1\text{ sec}$ queue revoke latency) | $< 10\text{ ms}$ OS signals |
| **Local Bootstrap Simplicity** | Single `uvicorn app:app` (Zero extra daemons) | Single command, but lacks async features | Requires running Redis/RabbitMQ daemons locally | Requires compiling dual-language toolchains |
| **Ecosystem & Tooling** | Rich Python security & LLM ecosystem (LangChain, LiteLLM, Scapy) | Rich Python ecosystem | Rich Python ecosystem | Weaker native Python security tool integration |

---

## 5. Detailed Rationale & Rejected Alternatives

### 5.1 Why Reject Flask + Threading?
1. **Thread Termination Limitations:** Python does not support forcefully killing a running native thread without corrupting interpreter state. If an agent executes an out-of-control scan or runs past a timeout, a threaded model cannot enforce the sub-200ms kill-switch requirement.
2. **Global Interpreter Lock (GIL):** CPU-bound tasks (hashing, log parsing, cryptography) in threads block the entire event loop, causing WebSocket stutter and dropped frames in the frontend visualization.
3. **Async / WebSocket Complexity:** Flask was historically built for synchronous request-response cycles. Modern ASGI FastAPI provides first-class asynchronous WebSocket handlers out of the box.

### 5.2 Why Reject Celery + Redis / RabbitMQ?
1. **Violates Local-First Lightweight Principle:** Requiring operators to install, configure, and supervise external message brokers (Redis or RabbitMQ) introduces friction and operational fragility on developer laptops or isolated air-gapped lab environments.
2. **Opaque Process Control:** Celery task revocation does not reliably terminate active native subprocesses spawned within worker tasks in sub-200ms.
3. **Over-Engineering for Single-Node Workflows:** For local MVP and multi-agent coordination, Python's native `asyncio.Queue` and process supervisors provide superior performance, lower latency, and zero dependency overhead.

### 5.3 Why Subprocess-per-Agent-Workspace is Superior:
1. **True Fault Containment:** If a security tool (e.g. `nuclei` or `nmap`) crashes, runs out of memory, or hangs on a network socket, only that specific subprocess group is affected. The FastAPI orchestrator detects the failure via return code / timeout and handles it gracefully.
2. **Strict Filesystem Sandboxing:** Each subprocess runs with `cwd` set to its dedicated workspace path (`/workspaces/{agent_id}/`) and a sanitized environment variables dictionary.
3. **Direct Process Group Kill:** By calling `os.setpgrp()` (or `start_new_session=True`), all child processes, forks, and pipes spawned by the agent belong to a distinct PGID, allowing instantaneous termination with `os.killpg(pgid, signal.SIGKILL)`.

---

## 6. Implementation Specifications & Patterns

### 6.1 Subprocess Launcher Pattern (Python `asyncio`)

```python
import asyncio
import os
import signal


class AgentProcessSupervisor:
    def __init__(self, agent_id: str, workspace_path: str):
        self.agent_id = agent_id
        self.workspace_path = workspace_path
        self.process: asyncio.subprocess.Process | None = None
        self.pgid: int | None = None

    async def launch_tool(
        self, cmd: list[str], env: dict[str, str], timeout_sec: float
    ) -> tuple[int, str, str]:
        # Launch in dedicated process session to establish new PGID
        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self.workspace_path,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # Creates new process group
        )
        self.pgid = os.getpgid(self.process.pid)

        try:
            stdout, stderr = await asyncio.wait_for(
                self.process.communicate(), timeout=timeout_sec
            )
            return (
                self.process.returncode or 0,
                stdout.decode(errors="replace"),
                stderr.decode(errors="replace"),
            )
        except asyncio.TimeoutError:
            await self.kill()
            raise TimeoutError(
                f"Agent {self.agent_id} process exceeded timeout of {timeout_sec}s"
            )

    async def kill(self) -> None:
        """Instantaneous sub-200ms kill switch using process group SIGKILL."""
        if self.process and self.process.returncode is None and self.pgid:
            try:
                os.killpg(self.pgid, signal.SIGKILL)
                await self.process.wait()
            except ProcessLookupError:
                pass  # Process already exited
```

---

## 7. Consequences & Trade-offs

### Positive Consequences
- **High Concurrency & Low Latency:** FastAPI + Uvicorn easily handles hundreds of real-time WebSocket clients and concurrent async agent events with sub-millisecond dispatch overhead.
- **Robust Failure Domain:** Unhandled exceptions and segfaults in agent tool executions are isolated to child processes.
- **Zero-Dependency Bootstrap:** Runs on any standard Python 3.11+ environment with `pip install -r requirements.txt`.
- **Deterministic Hard Kill:** Direct POSIX process group signal control satisfies the $< 200\text{ ms}$ kill-switch constraint.

### Negative Consequences & Mitigations
- **Subprocess Spawn Overhead:** Spawning fresh processes has a tiny OS overhead (~10-20ms per task).
  - *Mitigation:* Negligible in security workflows where network and LLM latencies are order of seconds.
- **Cross-Platform POSIX / Windows Differences:** `os.killpg` and `start_new_session` behave differently on Windows.
  - *Mitigation:* Implement a clean OS abstraction layer (`ProcessSupervisor`) supporting POSIX signal groups and Windows Job Objects.

---

## 8. Review & Acceptance

- **Accepted By:** RedCell_OS Architecture Review Board
- **Traceability:** Fulfills milestone **M005**, unlocking backend milestones across Phases P03–P20.
