# RedCell_OS Backend

High-throughput multi-agent orchestration engine and control plane built with **Python 3.11+**, **FastAPI**, **`asyncio`**, **SQLModel/SQLite**, and **`structlog`**.

## Architecture Highlights
- **FastAPI Control Plane:** ASGI REST endpoints + WebSocket real-time event hub.
- **Asyncio Task Supervision:** Manages DAG task dependencies, FSM agent lifecycles, and event queues.
- **Subprocess Workspace Sandboxing:** Spawns isolated process groups (`start_new_session=True`) with POSIX `resource` limits (RAM/CPU), CWD jails, and instant `os.killpg` SIGKILL emergency stop (< 200ms).
- **Tri-Store Persistence:** SQLite for relational state, append-only SQLite table for event sourcing/replay, and content-addressable filesystem for evidence artifacts.
- **Provider-Agnostic LLM Layer (`AgentBrain`):** Insulates agent reasoning and planning from vendor SDKs, supporting Claude, GPT-4o, Ollama, and deterministic mock brains.

## Directory Structure
- `app/`: FastAPI application, HTTP routers, and WebSocket connection manager.
- `core/`: Global configuration, structured logging (`structlog`), and security interceptors.
- `agents/`: FSM state machines and specialist role logic (CISO, Recon, Vuln, Reporting).
- `llm/`: `AgentBrain` abstraction, Pydantic schemas, and mock/live LLM drivers.
- `storage/`: SQLModel relational models, append-only event store, and CAS file manager.
- `roe/`: Machine-readable ROE parser and execution-boundary scope validator.
- `tools/`: Sandboxed tool execution runners and security tool adapters.
