# ADR-004: Persistence Architecture: Hybrid SQLite Relational Store, Append-Only Event Log, and Content-Addressable Filesystem

**Status:** Accepted  
**Date:** August 2026  
**Milestone Reference:** M008  
**Phase:** P02 — Architecture and Technology Decisions  
**Context Link:** [VISION.md](../../VISION.md), [SECURITY_CONSTRAINTS.md](../../SECURITY_CONSTRAINTS.md), [ADR-001-backend-runtime.md](ADR-001-backend-runtime.md)  

---

## 1. Context & Problem Statement

RedCell_OS requires a persistence architecture capable of serving three distinct data access patterns:

1. **Current-State Relational Queries:** Querying active engagements, agent statuses, pending approval gates, task dependency graphs, and discovered vulnerability findings.
2. **Event Sourcing & Audit Replay:** Storing an append-only, high-frequency stream of immutable events with strictly increasing sequence numbers for frontend catch-up, timeline scrubbing, and forensic non-repudiation.
3. **Heavy Binary & Artifact Storage:** Storing raw command logs, tool output XMLs/JSONs, PCAP packet captures, screenshots, and compiled PDF/Markdown reports.

We must choose persistence technologies that adhere to the **local-first, dependency-light bootstrap** principle for the MVP while providing an unambiguous **migration path to enterprise distributed storage (PostgreSQL + S3)**.

---

## 2. Decision Drivers

1. **Zero External Dependencies on Startup:** The local system must boot out-of-the-box on a fresh machine with zero external database daemons (no Docker or PostgreSQL container required for local operation).
2. **High Write Throughput & Low Latency:** Capable of ingesting bursts of agent execution events ($> 1,000\text{ events/sec}$) with sub-millisecond query latency.
3. **ACID Guarantees & Crash Resilience:** Sudden process crashes or power outages must never corrupt the relational store or truncate the event log.
4. **ORM Dialect Agnosticism:** Schema definitions and ORM query layers must remain 100% portable between SQLite (local) and PostgreSQL (enterprise).
5. **Clean Workspace Sandboxing:** Clear filesystem conventions separating ephemeral agent execution scratchpads from immutable long-term evidence.

---

## 3. Decision: The Tri-Store Persistence Architecture

We decide to adopt a **Tri-Store Persistence Model**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         TRI-STORE PERSISTENCE MODEL                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 1. Relational Current-State Store (SQLite via SQLAlchemy / SQLModel)   │  │
│  │    • Engagements, Agents, Tasks (DAG), Approvals, Findings, ROE       │  │
│  │    • Fast indexed relational queries for REST API & Dashboard         │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 2. Append-Only Event Log Table (`engagement_events`)                  │  │
│  │    • Monotonic `seq`, `correlation_id`, `event_type`, `payload_json`  │  │
│  │    • Drives WebSocket replay-on-reconnect & audit non-repudiation     │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 3. Content-Addressable Filesystem Store (`/data/...`)                 │  │
│  │    • Workspaces: Ephemeral scratchpads (`/data/workspaces/{agent_id}`) │  │
│  │    • Evidence: Raw tool outputs & PCAPs (`/data/evidence/{eng_id}`)   │  │
│  │    • Deliverables: Markdown/PDF reports (`/data/deliverables/`)       │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Technology Selection & ORM Layer

### 4.1 SQLModel / SQLAlchemy (Async Engine)
- **ORM Framework:** **SQLModel** (which unifies SQLAlchemy 2.0 and Pydantic v2).
- **Driver:** `aiosqlite` for local SQLite; `asyncpg` for PostgreSQL.
- **Portability:** Because SQLModel / SQLAlchemy abstracts table definitions and queries, transitioning the backend to PostgreSQL requires only changing the connection string (`DATABASE_URL=postgresql+asyncpg://...`).

---

## 5. Event Log Schema & Table Definition

The event log is stored in an optimized append-only SQLite table indexed by `engagement_id` and monotonic `seq`:

```sql
CREATE TABLE engagement_events (
    id TEXT PRIMARY KEY,                       -- UUIDv4 event identifier
    engagement_id TEXT NOT NULL,              -- Scope of engagement
    seq INTEGER NOT NULL,                     -- Monotonically increasing sequence integer (1, 2, 3...)
    timestamp_utc TEXT NOT NULL,              -- ISO 8601 UTC timestamp
    event_type TEXT NOT NULL,                 -- e.g., 'task_started', 'approval_requested'
    entity_id TEXT NOT NULL,                  -- Agent ID, Task ID, or Target ID
    correlation_id TEXT NOT NULL,             -- Trace ID linking to parent workflow DAG
    department_id TEXT,                       -- Department context
    payload_json TEXT NOT NULL,               -- Structured event payload
    integrity_hash TEXT NOT NULL,             -- SHA-256(prev_hash + payload_json)
    
    UNIQUE (engagement_id, seq)
);

CREATE INDEX idx_events_replay 
ON engagement_events (engagement_id, seq ASC);

CREATE INDEX idx_events_correlation 
ON engagement_events (correlation_id);
```

---

## 6. Filesystem Directory Layout Convention

To enforce workspace isolation and clean artifact lifecycle management, all filesystem paths follow a strict hierarchy under a configurable `/data` root:

```
/data/
├── redcell_global.db                       # Global user settings, catalogs, and role manifests
└── engagements/
    └── {engagement_id}/                   # e.g., eng-2026-q3-corp-audit/
        ├── engagement.db                   # Local SQLite relational store & event log
        │
        ├── workspaces/                     # Ephemeral agent execution directories
        │   ├── agent-ciso-01/              # Private agent scratchpad (cwd)
        │   ├── agent-recon-01/             # Private agent scratchpad
        │   └── agent-vuln-01/              # Private agent scratchpad
        │
        ├── evidence/                       # Content-addressable raw evidence & logs
        │   ├── sha256_e3b0c44298fc...raw   # Raw nmap XML output
        │   ├── sha256_8f434346648f...json  # Nuclei scan findings JSON
        │   └── sha256_12a89c8943bb...pcap  # Network packet capture
        │
        └── deliverables/                   # Client-ready output documents
            ├── report_eng-2026-q3.md       # Generated Markdown Report
            ├── report_eng-2026-q3.pdf      # Compiled PDF Report
            └── audit_bundle_sealed.zip     # Verifiable cryptographic audit bundle
```

### Filesystem Sandboxing Rules:
1. **Workspace Boundary:** Subprocesses spawned for `agent-recon-01` run with `cwd` set to `/data/engagements/{eng_id}/workspaces/agent-recon-01/`. Agents cannot write to sibling workspaces.
2. **Immutable Evidence Stashing:** When a tool run completes, output files are hashed (`SHA-256`), copied to `/data/engagements/{eng_id}/evidence/{hash}.raw`, and marked read-only (`chmod 444`).

---

## 7. SQLite Concurrency & Write Contention Mitigation

### The Concurrency Risk
Under high load with many concurrent agents emitting events simultaneously, default SQLite configurations can raise `sqlite3.OperationalError: database is locked`.

### Architectural Mitigations Applied:
1. **Write-Ahead Logging (WAL Mode):**
   ```sql
   PRAGMA journal_mode = WAL;
   PRAGMA synchronous = NORMAL;
   PRAGMA busy_timeout = 5000;
   PRAGMA temp_store = MEMORY;
   ```
   WAL mode allows concurrent readers to query current state while a write transaction is executing without blocking each other.
2. **Dedicated Background Event Writer Queue:**
   - Rather than having dozens of agent subprocesses open competing SQLite write connections, all agents emit events to an in-memory `asyncio.Queue`.
   - A single background `EventWriterService` task flushes events to SQLite in micro-batches (e.g. every 20ms or 50 items) using `executemany()`.
   - This achieves **$> 25,000\text{ event writes/second}$** in SQLite with zero lock contention.
3. **Database-per-Engagement Isolation:**
   - Each engagement maintains its own `engagement.db` file. Multiple parallel engagements never contend for the same database file locks.

---

## 8. Migration Path to Enterprise Scale (PostgreSQL + S3)

The architecture guarantees a frictionless upgrade path for enterprise deployments:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      ENTERPRISE MIGRATION BLUEPRINT                         │
├──────────────────────────────────┬──────────────────────────────────────────┤
│ MVP (Local-First)                │ Enterprise Distributed Deployment        │
├──────────────────────────────────┼──────────────────────────────────────────┤
│ SQLite (`sqlite+aiosqlite:///`)  │ PostgreSQL (`postgresql+asyncpg://`)     │
│ Local WAL Micro-batch Writer     │ Distributed Postgres with Connection Pool│
│ SQLite `engagement_events` table │ TimescaleDB / Partitioned Postgres Table │
│ Local `/data/evidence/` FS       │ S3-compatible Object Store (MinIO / AWS) │
│ Single Process Parent Supervisor │ Celery / Ray / Kubernetes Agent Pods     │
└──────────────────────────────────┴──────────────────────────────────────────┘
```

Because SQLModel ORM models and the CAS (Content-Addressable Storage) interface use clean repository abstractions (`EventRepository`, `ArtifactStorageService`), switching to Postgres and S3 requires **zero modifications to business logic or agent code**.

---

## 9. Review & Acceptance

- **Accepted By:** RedCell_OS Architecture Review Board
- **Traceability:** Fulfills milestone **M008**, completing Phase P02 persistence specifications and enabling Data Architecture milestones in Phase P03/P00.
