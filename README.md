# RedCell_OS — AI-Agentic Penetration Testing Organization Simulator

**RedCell_OS** is a local-first, event-driven cybersecurity simulation platform pairing an interactive **React + PixiJS 2D virtual office simulation** with a high-throughput **Python FastAPI + `asyncio` multi-agent orchestration backend**.

A human operator submits an authorized security engagement and machine-readable Rules of Engagement (ROE) to a virtual **CISO Agent**, which decomposes the objectives into departments, tasks, and specialized AI employees (Reconnaissance, Vulnerability Assessment, Exploitation Verification, and Technical Reporting) executing inside isolated, guardrailed workspaces—all visually brought to life as an active virtual cybersecurity firm.

---

## 📁 Monorepo Layout

```
RedCell_OS/
├── backend/                        # Python 3.11+ Orchestrator & Control Plane
│   ├── src/app/                    # FastAPI Application, HTTP API & WebSocket Hub
│   │   ├── api/                    # Health checks, Engagements, Approvals, Reports
│   │   ├── core/                   # Config, Logging (structlog), and Contextvars
│   │   ├── agents/                 # Specialist Agent Roles & FSM Lifecycle Engine
│   │   ├── llm/                    # Provider-Agnostic AgentBrain & Pydantic Schemas
│   │   ├── storage/                # SQLModel Relational Models, Event Store & CAS
│   │   ├── roe/                    # Machine-Readable ROE Parser & Scope Interceptor
│   │   └── tools/                  # Sandboxed Subprocess Runners & Security Adapters
│   └── pyproject.toml              # Installable Python package configuration
│
├── frontend/                       # React 18 + PixiJS 2D Office Simulation
│   ├── src/
│   │   ├── components/             # Command Center, Approvals, Log Console, Reports
│   │   ├── office-world/           # PixiJS WebGL 2D Virtual Office Viewport
│   │   ├── state/                  # Zustand Stores & WebSocket Event Stream Client
│   │   ├── api/                    # TanStack Query Client for REST Mutations
│   │   ├── hooks/                  # Auto-reconnecting WebSocket hooks
│   │   └── types/                  # Canonical Event & Agent entity definitions
│   └── public/                     # Static assets, sprite sheets, and tilesets
│
├── docs/                           # Canonical Specifications & Architectural ADRs
│   ├── adr/                        # Architecture Decision Records (ADR-001 - ADR-008)
│   ├── VISION.md                   # Product Vision, Personas, and Explicit Non-Goals
│   ├── SECURITY_CONSTRAINTS.md     # Authorized-Use, ROE Schema & Kill Switch Specs
│   ├── ROLE_TAXONOMY.md            # Specialist Role Taxonomy & Capabilities
│   └── MVP_SCENARIO.md             # Canonical E2E Acceptance Scenario & Event Flow
│
├── data/                           # Local Runtime Storage (Database, Workspaces, Artifacts)
│   ├── engagements/                # Per-engagement databases, workspaces & evidence
│   └── .gitkeep
│
├── scripts/                        # Automation, Supervision & Developer Tooling
│   ├── launch.js                   # Node.js Child Process Supervisor (Zero-Orphan Launcher)
│   ├── ci.sh                       # Local unified CI pipeline runner
│   ├── setup.sh                    # Environment bootstrapper
│   └── dev.sh                      # Development environment launcher
│
├── tests/                          # Automated Pytest Suite
│   ├── test_health.py              # Health check endpoint unit tests
│   ├── test_llm_abstraction.py     # AgentBrain & MockBrain tests
│   └── test_logging.py             # Structured logging & contextvars tests
│
├── requirements.txt                # Python backend dependencies
├── package.json                    # Root npm scripts (start, dev, test, ci)
└── .gitignore                      # Git exclusion rules
```

---

## 🏛️ Key Architectural Pillars

1. **Backend as Single Source of Truth:** The 2D office simulation visualizes only derived backend state; it never fabricates fake animations or hallucinated actions.
2. **Process Supervision & Zero Orphans:** The Node.js launcher (`scripts/launch.js`) and Tauri sidecar architecture supervise backend child processes with POSIX process groups, guaranteeing instant cleanup on exit ([ADR-008](docs/adr/ADR-008-desktop-shell.md)).
3. **Provider-Agnostic LLM Layer (`AgentBrain`):** Modular reasoning interface supporting Claude 3.5 Sonnet, GPT-4o, local air-gapped models (Ollama/vLLM), and deterministic mock brains ([ADR-006](docs/adr/ADR-006-llm-abstraction.md)).
4. **Pluggable Sandboxing:** MVP uses Python native subprocesses with POSIX `resource` limits (RAM/CPU), CWD jails, scrubbed environments, and process group `SIGKILL` handlers; upgrades seamlessly to Docker in production ([ADR-005](docs/adr/ADR-005-sandboxing.md)).
5. **Sub-200ms Kill Switch:** Multi-tiered emergency stop protocol via `os.killpg(pgid, SIGKILL)` ensuring instant fail-safe containment ([SECURITY_CONSTRAINTS.md](docs/SECURITY_CONSTRAINTS.md)).
6. **Hybrid IPC Transport:** Real-time sequence-ordered WebSocket event stream with replay-on-reconnect catchup + REST command plane ([ADR-003](docs/adr/ADR-003-realtime-transport.md)).
7. **Tri-Store Persistence:** SQLite via SQLModel for relational current state, append-only SQLite event log for audit replay, and content-addressable filesystem for raw evidence ([ADR-004](docs/adr/ADR-004-persistence.md)).
8. **Universal Correlation & Observability:** `structlog` structured logging with automatic `correlation_id` and `engagement_id` propagation ([ADR-007](docs/adr/ADR-007-observability.md)).
9. **Roles as Data, Not Code:** Roles defined declaratively via YAML/JSON manifests registered dynamically ([ROLE_TAXONOMY.md](docs/ROLE_TAXONOMY.md)).

---

## 📜 Canonical Architecture Decision Records (ADRs)

- [ADR-001: Backend Runtime & Process Supervision Model](docs/adr/ADR-001-backend-runtime.md)
- [ADR-002: Frontend Framework, State Layer & 2D Office Renderer](docs/adr/ADR-002-frontend-stack.md)
- [ADR-003: Local IPC & Real-Time Transport Protocol](docs/adr/ADR-003-realtime-transport.md)
- [ADR-004: Persistence Architecture (Hybrid SQLite & Filesystem)](docs/adr/ADR-004-persistence.md)
- [ADR-005: Agent Execution Sandboxing Mechanism](docs/adr/ADR-005-sandboxing.md)
- [ADR-006: LLM Provider Abstraction & AgentBrain Interface](docs/adr/ADR-006-llm-abstraction.md)
- [ADR-007: Observability Stack (Structured Logging & Correlation IDs)](docs/adr/ADR-007-observability.md)
- [ADR-008: Desktop Shell Architecture & Process Launcher](docs/adr/ADR-008-desktop-shell.md)

---

## 🚀 Quick Start (Single-Command Launch)

```bash
# 1. Run automated setup script
./scripts/setup.sh

# 2. Run local CI suite (Ruff, Mypy, Pytest, ESLint, TypeScript Build)
./scripts/ci.sh

# 3. Start unified supervised environment (Backend + Frontend)
npm start
# or: node scripts/launch.js
```
