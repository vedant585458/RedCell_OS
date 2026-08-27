# ADR-007: Observability Stack: Structured JSON Logging (structlog), Universal Correlation ID Propagation, and Local Event-Sourced Traces

**Status:** Accepted  
**Date:** August 2026  
**Milestone Reference:** M011  
**Phase:** P02 — Architecture and Technology Decisions  
**Context Link:** [VISION.md](../../VISION.md), [SECURITY_CONSTRAINTS.md](../../SECURITY_CONSTRAINTS.md), [ADR-001-backend-runtime.md](ADR-001-backend-runtime.md)  

---

## 1. Context & Problem Statement

RedCell_OS operates as a hierarchical multi-agent simulation system. A single user engagement triggers a cascade of asynchronous operations:
- CISO Agent decomposes mission into tasks.
- Engagement Manager schedules tasks across specialist agents.
- Agents spawn isolated subprocesses running external security CLI tools (`nmap`, `nuclei`, custom Python scripts).
- Approval gates pause execution and await operator input.
- Events stream in real time over WebSockets to the React/PixiJS frontend.

Debugging complex multi-agent failures, validating security boundaries, and generating forensic audit trails requires complete observability across all layers:
1. **Application Logging:** Fast, structured, contextual logging.
2. **Trace Correlation:** Ability to trace any low-level CLI log line or tool output back to its originating agent, task, and engagement.
3. **Local Metrics:** Real-time counters for task durations, active subprocesses, LLM token costs, and WebSocket client throughput.

We must select an observability stack that satisfies the **local-first zero-dependency bootstrap** for the MVP while allowing seamless export to **OpenTelemetry (OTel), Prometheus, and SIEMs** in enterprise production.

---

## 2. Decision Drivers

1. **Zero External Daemon Dependencies for MVP:** No mandatory Jaeger, Tempo, Elasticsearch, or OpenTelemetry Collector required on first boot.
2. **Universal Traceability:** Every log line, tool execution, and state event must carry a canonical `correlation_id` and `engagement_id`.
3. **Structured & Machine-Readable:** Standardized JSON formatting for automated ingestion and forensic replay, with colored development console output.
4. **Asynchronous Context Propagation:** Seamless propagation of contextual tags across `asyncio` task boundaries and subprocess spawns.
5. **Negligible Performance Overhead:** Structured log formatting must not block the asynchronous FastAPI event loop.

---

## 3. Decision: The Local-First Observability Architecture

We decide to adopt:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      LOCAL-FIRST OBSERVABILITY STACK                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 1. Structured Logging Engine: `structlog` (JSON + Console Formatter)  │  │
│  │    • Contextual key-value bindings via `structlog.contextvars`        │  │
│  │    • Async-safe, zero-allocation log pipeline                         │  │
│  └───────────────────────────────────┬───────────────────────────────────┘  │
│                                      │                                      │
│  ┌───────────────────────────────────┴───────────────────────────────────┐  │
│  │ 2. Universal Correlation ID Propagation Protocol                      │  │
│  │    • `engagement_id` + `correlation_id` + `task_id` + `agent_id`      │  │
│  │    • Automatic inheritance across async tasks and subprocess envs     │  │
│  └───────────────────────────────────┬───────────────────────────────────┘  │
│                                      │                                      │
│  ┌───────────────────────────────────┴───────────────────────────────────┐  │
│  │ 3. Event-Sourced Local Tracing (SQLite Events Table)                  │  │
│  │    • Queryable trace waterfall graphs without external tracing daemons│  │
│  │    • `SELECT * FROM events WHERE correlation_id = ? ORDER BY seq ASC` │  │
│  └───────────────────────────────────┬───────────────────────────────────┘  │
│                                      │                                      │
│  ┌───────────────────────────────────┴───────────────────────────────────┐  │
│  │ 4. Local In-Memory Metrics & Optional Prometheus Endpoint             │  │
│  │    • FastAPI `/metrics` endpoint (Prometheus format) for enterprise   │  │
│  │    • OpenTelemetry (OTel) Collector exporter as an optional post-MVP  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Evaluation Matrix

| Criterion | Selected: `structlog` + Correlation IDs | Alternative 1: Python stdlib `logging` | Alternative 2: Full OpenTelemetry + Jaeger |
|---|---|---|---|
| **Local Dependencies** | Zero (Embedded Python library) | Zero | Requires Jaeger / Tempo container |
| **Structured Output** | Native JSON dictionaries + Key-Value chaining | Requires custom JSON formatters & string interpolation | OTLP Protobuf format |
| **Async ContextVars** | Native `structlog.contextvars` support | Manual filter injection on every logger call | Context propagation via OTel Tracer |
| **Developer Console** | Beautiful colorized console formatter for CLI | Plain text string format | Requires opening external browser UI |
| **Audit Compliance** | Direct JSON output to immutable event files | Manual file handlers | Exports to central APM backend |
| **Trace Querying** | Fast local SQL queries in SQLite | Grep / awk text searching | Web UI waterfall trace view |

### Why Full OTel is Deferred to Post-MVP:
Full OpenTelemetry SDK with Jaeger requires running a Docker container or external OTLP collector on the developer's laptop, violating the local-first zero-dependency constraint. By embedding canonical `correlation_id` fields into every log line and SQLite event from Day 1, RedCell_OS achieves 100% trace queryability locally and can bridge to OTel with a single adapter in Phase P58.

---

## 5. Universal Correlation ID Propagation Specification

### 5.1 ID Formatting Standard
- `engagement_id`: Unique identifier for the engagement (e.g. `eng-2026-q3-corp-audit` or UUIDv4).
- `correlation_id`: Hierarchical trace ID linking sub-actions to root CISO plans:
  - Root Plan: `corr-{engagement_id}`
  - Task Execution: `corr-{engagement_id}-{task_id}`
  - Subprocess / Tool Call: `corr-{engagement_id}-{task_id}-{sub_id}`

### 5.2 Context Propagation Lifecycle
```
[HTTP Request / WS Message]
            │ (Extracts or generates 'X-Correlation-ID')
            ▼
[FastAPI Middleware: structlog.contextvars.bind_contextvars(correlation_id=...)]
            │
    ┌───────┴───────┐
    │               │
[Asyncio Task A]  [Asyncio Task B] (Contextvars automatically inherited)
    │
    ▼
[Agent Subprocess Launcher]
    │ (Injects `REDCELL_CORRELATION_ID` into subprocess environment)
    ▼
[Sandboxed CLI Tool / Script]
    │ (Output logs tagged with correlation ID)
    ▼
[SQLite Event Log + JSON Log File]
```

---

## 6. Canonical Implementation Blueprint

### 6.1 Logger Setup (`backend/core/logging.py`)

```python
import logging
import sys
import structlog


def configure_logging(json_format: bool = False, log_level: str = "INFO"):
    """Configure structured logging pipeline."""
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_format:
        # Production / Audit JSON formatter
        processors = shared_processors + [structlog.processors.JSONRenderer()]
    else:
        # Local interactive developer console formatter
        processors = shared_processors + [structlog.dev.ConsoleRenderer(colors=True)]

    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a bound structured logger instance."""
    return structlog.get_logger(name)
```

### 6.2 Usage Pattern in Agents & Tasks

```python
import structlog

logger = structlog.get_logger("agent.recon")


async def execute_recon_task(
    engagement_id: str, task_id: str, agent_id: str, target: str
):
    # Bind context to current async contextvars
    structlog.contextvars.bind_contextvars(
        engagement_id=engagement_id,
        correlation_id=f"corr-{engagement_id}-{task_id}",
        task_id=task_id,
        agent_id=agent_id,
    )

    logger.info("Starting target port probe", target=target, port_range="8000-8100")
    # Emits: {"event": "Starting target port probe", "target": "127.0.0.1", "port_range": "8000-8100",
    #         "engagement_id": "eng-01", "correlation_id": "corr-eng-01-t1", "level": "info", "timestamp": "..."}
```

---

## 7. Consequences & Trade-offs

### Positive Consequences
- **Bake-In from Day 1:** Standardizing `correlation_id` across all milestones from P02 onward eliminates costly future retrofitting.
- **Human & Machine Friendly:** Clean colorized console output for the operator during local runs; strict JSON logs for automated audit compliance and report generation.
- **Zero Daemon Overhead:** Trace graphs are reconstructed instantly via simple SQLite queries (`WHERE correlation_id = ?`) without running Jaeger or Elasticsearch.

### Negative Consequences & Mitigations
- **Contextvars Leaks in Custom Threadpools:** If manual OS threads are spawned outside `asyncio`, contextvars are not automatically copied.
  - *Mitigation:* We use pure `asyncio` and `asyncio.to_thread` which properly propagates contextvars.

---

## 8. Review & Acceptance

- **Accepted By:** RedCell_OS Architecture Review Board
- **Traceability:** Fulfills milestone **M011**, completing core architecture decisions for Phase P02.
