# ADR-003: Local IPC and Real-Time Transport: WebSocket Event Stream + REST Command Plane

**Status:** Accepted  
**Date:** August 2026  
**Milestone Reference:** M007  
**Phase:** P02 — Architecture and Technology Decisions  
**Context Link:** [VISION.md](../../VISION.md), [ADR-001-backend-runtime.md](ADR-001-backend-runtime.md), [ADR-002-frontend-stack.md](ADR-002-frontend-stack.md)  

---

## 1. Context & Problem Statement

RedCell_OS requires high-speed, reliable communication between the Python FastAPI backend orchestrator and the React / PixiJS office simulation frontend running on the operator's machine.

### Telemetry Profile & Workload Requirements:
1. **High-Frequency Downstream Telemetry (Backend $\rightarrow$ Frontend):**
   - Live agent FSM state transitions (`PLANNING`, `EXECUTING`, `AWAITING_APPROVAL`).
   - Terminal stdout/stderr streams and raw network packet counters.
   - Real-time 2D office movement coordinates and interaction events.
   - Discovered vulnerabilities, attack graph updates, and telemetry scores.
   - At peak enterprise scale (100+ concurrent agents), event rates can exceed **1,000 to 5,000 events/second**.
2. **Transactional Upstream Commands (Frontend $\rightarrow$ Backend):**
   - ROE manifest uploads and engagement initiation.
   - Operator human-in-the-loop (HITL) approval decisions (Grant / Deny).
   - Immediate Emergency Kill-Switch dispatch.
   - Report export requests and manual task re-prioritization.

We must define the local IPC transport protocol, the split between streaming and command channels, and a robust **reconnection, replay, and backpressure strategy**.

---

## 2. Decision Drivers

1. **Sub-20ms Event Latency:** Immediate visual feedback in the React/PixiJS simulation when backend agents transition states.
2. **Deterministic Sequence Ordering & Zero State Loss:** Reconnecting clients must never miss critical security events (approvals, findings, errors).
3. **Minimal Protocol Overhead:** Low framing overhead for high-frequency small JSON telemetry payloads.
4. **Idempotent, Transactional Command Handling:** Complex mutations (ROE uploads, approvals) must provide standard HTTP status codes, error payloads, and validation guarantees.
5. **Backpressure & Client Responsiveness:** Rapid bursts of tool stdout logs must not freeze the browser UI or overwhelm the WebSocket event loop.

---

## 3. Decision

We decide to adopt a **Hybrid Transport Architecture**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       HYBRID TRANSPORT ARCHITECTURE                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  React / PixiJS Frontend (Zustand + React Query)                            │
│  ┌─────────────────────────────────┐       ┌─────────────────────────────┐  │
│  │   Imperative Commands / Query   │       │   Real-Time Event Stream    │  │
│  │   (TanStack Query Client)       │       │   (Auto-Reconnecting WS)    │  │
│  └────────────────┬────────────────┘       └──────────────▲──────────────┘  │
│                   │ HTTP POST / GET                       │ Full-Duplex     │
│                   │ (REST + JSON Validation)              │ WebSocket Stream│
│                   ▼                                       │ (Seq-Ordered)   │
│  ┌─────────────────────────────────┐       ┌──────────────┴──────────────┐  │
│  │     FastAPI REST Endpoints      │       │    FastAPI WebSocket Hub    │  │
│  │  • POST /api/v1/engagements     │       │    • /ws/engagements/{id}   │  │
│  │  • POST /api/v1/approvals/{id}  │       │    • Ping/Pong Heartbeat    │  │
│  │  • POST /api/v1/kill-switch     │       │    • Sequence Catch-up Log  │  │
│  └─────────────────────────────────┘       └─────────────────────────────┘  │
│  Python FastAPI Orchestrator Backend                                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

1. **Real-Time Telemetry Stream (Downstream):** **Native WebSockets (`/ws/engagements/{id}`)**
   - Delivers sequenced, structured JSON event frames from the orchestrator event bus directly to the frontend Zustand store.
2. **Transactional Control Plane (Upstream):** **REST API (`/api/v1/...`)**
   - Handles engagement configuration, ROE manifest validation, approval decisions, and artifact downloads with explicit HTTP status codes (`200`, `202`, `400`, `403`, `422`).
3. **Sequence-Numbered Event Stream & Replay-on-Reconnect Protocol:**
   - Every event has a strictly monotonic `seq_num`. On reconnect, the client requests missed events starting from `last_seen_seq`.
4. **Tiered Backpressure & Batching Strategy:**
   - High-volume stdout streams are batched in 50ms windows; high-priority state events are dispatched with zero latency.

---

## 4. Evaluated Alternatives

| Transport Mechanism | Selected: WebSocket + REST | Alternative 1: Server-Sent Events (SSE) + REST | Alternative 2: Pure HTTP Polling | Alternative 3: gRPC-Web |
|---|---|---|---|---|
| **Downstream Latency** | $< 5\text{ ms}$ | $< 10\text{ ms}$ | $200 - 1000\text{ ms}$ (High jitter) | $< 5\text{ ms}$ |
| **Header / Framing Overhead** | 2–6 bytes per frame | Standard HTTP headers on connection | Full HTTP headers per poll request | Protobuf binary framing |
| **Bi-directional Heartbeats** | Native WS Ping/Pong frames | Requires simulated HTTP heartbeats | None | Complex HTTP/2 ping |
| **Connection Limits** | Single multiplexed socket | HTTP/1.1 max 6 connections limit | Exhausts local TCP ephemeral ports | Multiplexed HTTP/2 |
| **Simplicity & Tooling** | High (native in browser & FastAPI) | Medium | Very simple, but unacceptable performance | Low (requires Envoy proxy & proto build steps) |

### Why Not Pure SSE?
While SSE is clean for server-to-client streaming, WebSockets provide lower framing overhead, native sub-millisecond ping/pong connection health monitoring, and unified support for bidirectional binary data (e.g. streaming compressed PCAP files or raw terminal byte streams in future phases).

---

## 5. Reconnection & Replay Specification

To guarantee that temporary frontend network blips, browser backgrounding, or laptop sleep do not corrupt the simulation state:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      REPLAY-ON-RECONNECT SEQUENCE FLOW                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Frontend Client                             FastAPI WebSocket Hub          │
│         │                                              │                    │
│         │─── [1] WS Connect (/ws/engagements/eng-01) ──▶│                    │
│         │    ?last_seen_seq=142                        │                    │
│         │                                              │                    │
│         │                                    [2] Query SQLite Log:          │
│         │                                        SELECT * FROM events       │
│         │                                        WHERE eng_id = 'eng-01'    │
│         │                                        AND seq > 142 ORDER BY seq │
│         │                                              │                    │
│         │◀── [3] Replay Batch Frame (seq 143-160) ─────│                    │
│         │                                              │                    │
│         │   (Client applies missing events             │                    │
│         │    sequentially to Zustand store)            │                    │
│         │                                              │                    │
│         │◀── [4] Live Event Stream (seq 161+) ─────────│                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.1 Monotonic Event Envelope Schema
```json
{
  "seq_num": 143,
  "engagement_id": "eng-mvp-001",
  "correlation_id": "corr-task-02-recon",
  "timestamp_utc": "2026-08-26T14:30:15.120Z",
  "event_type": "agent_state_changed",
  "agent_id": "agent-vuln-01",
  "department_id": "dept_vulnerability",
  "task_id": "TASK-02",
  "priority": "HIGH",
  "payload": {
    "previous_state": "PLANNING",
    "current_state": "AWAITING_APPROVAL",
    "gate_id": "gate-req-001"
  }
}
```

### 5.2 Client-Side Reconnection Logic
- **Heartbeat:** Frontend sends WebSocket `PING` every 15 seconds; expects `PONG` within 5 seconds.
- **Exponential Backoff:** If connection drops, reconnect attempts trigger at $1\text{s}, 2\text{s}, 4\text{s}, 8\text{s}$ (capped at $10\text{s}$).
- **State Hydration:** Client provides `last_seen_seq` in the query parameter. If the server detects the client is too far behind (e.g. $> 5,000$ events missed), it sends a consolidated `state_snapshot` payload followed by sequential live events.

---

## 6. Backpressure & Event Prioritization

To prevent high-volume terminal output from saturating the browser event loop during large-scale simulations:

| Priority Level | Event Types | Delivery Guarantee | Throttle / Batching Policy |
|---|---|---|---|
| **Tier 1: CRITICAL** | `approval_requested`, `kill_switch_tripped`, `scope_violation`, `agent_state_changed`, `finding_recorded` | Zero Drop, Immediate Dispatch | Dispatched instantly with sub-millisecond priority queue. |
| **Tier 2: SIMULATION** | `agent_movement_tween`, `room_occupancy_changed`, `task_progress_update` | Zero Drop, In-Order | Dispatched every 16ms (synchronized with 60 FPS frame rate). |
| **Tier 3: TELEMETRY** | `stdout_chunk`, `stderr_chunk`, `packet_count_tick` | Batched Delivery | Batched into 50ms flush windows or max 100 log lines per frame. |

---

## 7. Consequences & Trade-offs

### Positive Consequences
- **Rock-Solid Event Determinism:** Monotonic sequence numbers and SQLite replay ensure the frontend and backend are always in 100% mathematical synchronization.
- **Clear Separation:** High-frequency events flow through the lightweight WebSocket pipeline, while heavy REST mutations benefit from standard HTTP caching, validation, and error semantics.
- **Resilient UI:** Tiered backpressure guarantees that spammy CLI tool outputs never freeze the 2D PixiJS canvas or lag operator approval buttons.

### Negative Consequences & Mitigations
- **Connection State Overhead:** Backend must track active WebSocket subscriber connections per engagement.
  - *Mitigation:* Implemented via a lightweight in-memory `ConnectionManager` class in FastAPI that cleans up dead sockets on disconnect.

---

## 8. Review & Acceptance

- **Accepted By:** RedCell_OS Architecture Review Board
- **Traceability:** Fulfills milestone **M007**, establishing the communication foundation for Phase P41 (Real-Time Synchronization) and Phase P02.
