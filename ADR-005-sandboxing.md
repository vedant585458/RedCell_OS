# ADR-005: Agent Execution Sandboxing: Layered Subprocess Jails (MVP) to Pluggable Container Isolation (Production)

**Status:** Accepted  
**Date:** August 2026  
**Milestone Reference:** M009  
**Phase:** P02 — Architecture and Technology Decisions  
**Context Link:** [VISION.md](../../VISION.md), [SECURITY_CONSTRAINTS.md](../../SECURITY_CONSTRAINTS.md), [ADR-001-backend-runtime.md](ADR-001-backend-runtime.md)  

---

## 1. Context & Problem Statement

RedCell_OS agents dynamically generate and execute CLI commands, network probes, and custom scripts (`nmap`, `nuclei`, `ffuf`, Python PoC scripts) during penetration testing engagements.

Executing arbitrary security tools and dynamic scripts introduces critical operational and safety hazards:
1. **Resource Exhaustion:** Runaway loops, memory leaks, fork-bombs, or CPU starvation crashing the host.
2. **Infinite Hanging:** Unresponsive network sockets or blocked processes stalling the entire orchestration pipeline.
3. **Filesystem Escape & State Corruption:** Accidental file writes, overwriting parent code, or mutating sibling agent scratchpads.
4. **Environment / Secret Leaks:** Child processes inheriting sensitive parent environment variables (e.g. LLM API keys, database credentials, operator secrets).

We must define an agent execution sandboxing architecture that satisfies the **local-first, zero-friction startup requirement for the MVP** while providing a seamless **upgrade path to containerized and multi-tenant isolation for enterprise deployments**.

---

## 2. Decision Drivers

1. **Local-First Zero-Dependency Startup (MVP):** Single-operator developer setup must run immediately without requiring Docker daemons, root privileges, or container engines.
2. **Deterministic Resource Limits:** Strict enforcement of CPU time, memory consumption, file descriptor limits, and execution timeouts.
3. **Immediate Containment ($< 200\text{ ms}$ Kill Switch):** Full parent ability to destroy any spawned process tree instantly.
4. **Filesystem & Environment Hygiene:** Execution confined to designated workspace scratchpads with scrubbed environment variables.
5. **Pluggable Architecture:** Identical tool invocation interface regardless of whether execution runs in an OS subprocess, a container, or a MicroVM.

---

## 3. Sandboxing Technology Evaluation Matrix

| Criterion | Option A: Subprocess + POSIX Limits + CWD Jail (CHOSEN MVP) | Option B: Linux Namespaces / Bubblewrap (`bwrap`) | Option C: Docker / Podman Containers (CHOSEN PROD) | Option D: MicroVMs (Firecracker / gVisor) |
|---|---|---|---|---|
| **Startup Latency** | $< 5\text{ ms}$ (Instantaneous) | $15 - 30\text{ ms}$ | $500 - 2000\text{ ms}$ (Container cold start) | $100 - 300\text{ ms}$ |
| **External Dependencies** | Zero (Pure Python 3.11 standard library) | Requires `bubblewrap` package & Linux kernel | Requires Docker / Podman daemon installed & running | Requires Linux KVM virtualization support |
| **Cross-Platform Support** | Linux & macOS native (Windows via Job Objects) | Linux only | Multi-platform (via Docker Desktop / VM) | Linux server only |
| **Filesystem Isolation** | CWD jailed; restricted paths | Mount namespace isolation (Read-only root) | Full container overlayfs filesystem isolation | Full guest filesystem isolation |
| **Process Isolation** | OS Process Group (`setpgrp` / `start_new_session`) | PID namespace isolation | Container cgroup / namespace isolation | Hardware-assisted hypervisor boundary |
| **Multi-Tenant Safety** | Low (Suitable for single operator) | Medium | High | Maximum |

---

## 4. Decision: The Pluggable Dual-Tier Sandbox Architecture

We decide to adopt a **Polymorphic Sandbox Provider Architecture**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PLUGGABLE SANDBOX ARCHITECTURE                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│                        ┌────────────────────────────┐                       │
│                        │    Tool Execution Layer    │                       │
│                        │ (ToolDispatcher / Agents)  │                       │
│                        └─────────────┬──────────────┘                       │
│                                      │                                      │
│                                      ▼                                      │
│                        ┌────────────────────────────┐                       │
│                        │   BaseSandboxProvider      │                       │
│                        │ (Abstract Interface Class) │                       │
│                        └─────────────┬──────────────┘                       │
│                                      │                                      │
│                ┌─────────────────────┴─────────────────────┐                │
│                │                                           │                │
│                ▼                                           ▼                │
│  ┌───────────────────────────┐               ┌───────────────────────────┐  │
│  │ SubprocessSandboxProvider │               │   DockerSandboxProvider   │  │
│  │ (MVP Default Engine)      │               │ (Enterprise / Multi-Tenant│  │
│  ├───────────────────────────┤               ├───────────────────────────┤  │
│  │ • CWD Jail: /workspaces/  │               │ • Docker Engine / Podman  │  │
│  │ • POSIX setrlimit (RAM/CPU│               │ • Read-Only RootFS        │  │
│  │ • Process Group SIGKILL   │               │ • Dedicated Docker Bridge │  │
│  │ • Scrubbed Environment    │               │ • Non-Root User Execution │  │
│  │ • Zero-Dependency Boot    │               │ • Multi-Tenant Compliant  │  │
│  └───────────────────────────┘               └───────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Tier 1: MVP Sandbox Specification (`SubprocessSandboxProvider`)

The MVP implementation runs natively using Python's `asyncio.subprocess` and POSIX `resource` limits with zero external software requirements.

### 5.1 Sandbox Execution Guarantees
1. **Working Directory Jail:** The child process `cwd` is strictly set to `/data/engagements/{id}/workspaces/{agent_id}/`.
2. **POSIX Resource Limits (`setrlimit` via `preexec_fn`):**
   - **`RLIMIT_AS` (Virtual Memory):** Capped per role (default: $1024\text{ MB}$). Exceeding allocations trigger immediate memory allocation errors instead of OOM killing the host.
   - **`RLIMIT_CPU` (CPU Time):** Capped per task (default: $60\text{ s}$ CPU time). Triggers `SIGXCPU` if a script enters an infinite loop.
   - **`RLIMIT_NOFILE` (Open Files):** Capped at 256 descriptors to prevent descriptor exhaustion.
   - **`RLIMIT_NPROC` (Process Count):** Capped at 32 sub-threads/processes to prevent fork-bombs.
3. **Process Group Isolation:** `start_new_session=True` ensures the child process becomes the leader of a new process group, enabling universal `os.killpg(pgid, signal.SIGKILL)`.
4. **Environment Variable Whitelist & Scrubbing:**
   - Child processes do **not** inherit `os.environ` wholesale.
   - Sensitive variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DATABASE_URL`, `AWS_SECRET_ACCESS_KEY`, `SSH_AUTH_SOCK`) are completely scrubbed.
   - Only safe environment variables (`PATH=/usr/bin:/bin`, `LANG=C.UTF-8`, `HOME={workspace_path}`, `TMPDIR={workspace_path}/tmp`) are injected.

### 5.2 Implementation Pattern (Python)

```python
import asyncio
import os
import resource
import signal

class ResourceLimits:
    def __init__(self, max_memory_mb: int = 1024, max_cpu_sec: int = 60, max_files: int = 256):
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self.max_cpu_sec = max_cpu_sec
        self.max_files = max_files

def _apply_rlimits(limits: ResourceLimits):
    """Executed in child process before exec."""
    resource.setrlimit(resource.RLIMIT_AS, (limits.max_memory_bytes, limits.max_memory_bytes))
    resource.setrlimit(resource.RLIMIT_CPU, (limits.max_cpu_sec, limits.max_cpu_sec))
    resource.setrlimit(resource.RLIMIT_NOFILE, (limits.max_files, limits.max_files))

class SubprocessSandboxProvider:
    async def run(
        self,
        cmd: list[str],
        workspace_path: str,
        limits: ResourceLimits,
        timeout_sec: float = 120.0
    ) -> tuple[int, str, str]:
        # Sanitized environment
        clean_env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME": workspace_path,
            "TMPDIR": os.path.join(workspace_path, "tmp"),
            "LANG": "C.UTF-8"
        }
        os.makedirs(clean_env["TMPDIR"], exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=workspace_path,
            env=clean_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            preexec_fn=lambda: _apply_rlimits(limits)
        )
        pgid = os.getpgid(proc.pid)

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
            return proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")
        except asyncio.TimeoutError:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            raise TimeoutError(f"Command '{' '.join(cmd)}' timed out after {timeout_sec}s")
```

---

## 6. Tier 2: Production / Enterprise Sandbox (`DockerSandboxProvider`)

In Phase P25+ (Security Hardening & Production Sandboxing), operators can switch the backend engine via configuration (`SANDBOX_PROVIDER=docker`):

```bash
docker run --rm \
  --name "redcell-sandbox-${agent_id}" \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --volume "/data/engagements/${id}/workspaces/${agent_id}:/workspace:rw" \
  --workdir /workspace \
  --memory 1024m \
  --cpus 1.0 \
  --cap-drop ALL \
  --user 1000:1000 \
  redcell-agent-sandbox:latest \
  nmap -sV -p 8088 127.0.0.1
```

---

## 7. Known Risks & Limitations (Explicit Disclosure)

| Risk Category | MVP Subprocess Sandbox Status | Mitigation / Upgrade Path |
|---|---|---|
| **Multi-Tenant Host Security** | **KNOWN LIMITATION:** Subprocess sandboxing does not prevent read access to world-readable system files (`/etc/passwd`, `/usr/bin`). | Documented explicitly: The MVP is designed for **single-operator local use**. Production multi-tenant deployments must use `DockerSandboxProvider` or MicroVMs. |
| **Fork Bombs / Kernel Exhaustion** | Mitigated via `RLIMIT_NPROC` and `RLIMIT_AS`. | Monitored by Parent Supervisor and ROE Safety Sentinel. |
| **Child Process Orphan Leaks** | Mitigated via POSIX Process Groups (`os.killpg`) on timeout/kill-switch. | Automated reaper checks for dead PGIDs during cleanup phase. |

---

## 8. Review & Acceptance

- **Accepted By:** RedCell_OS Architecture Review Board
- **Traceability:** Fulfills milestone **M009**, unlocking Phase P25 (Execution Sandboxing) and Phase P02.
