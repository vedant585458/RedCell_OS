# MVP Acceptance Scenario: End-to-End Test Specification

**Document Version:** 1.0.0  
**Milestone:** M004 — Define MVP acceptance scenario  
**Phase:** P01 — Vision and Requirements  
**Status:** Approved & Canonical  
**Dependencies:** [VISION.md](VISION.md) (M001), [SECURITY_CONSTRAINTS.md](SECURITY_CONSTRAINTS.md) (M002), [ROLE_TAXONOMY.md](ROLE_TAXONOMY.md) (M003)  

---

## 1. Purpose & MVP Definition

This document defines the **single canonical End-to-End (E2E) Acceptance Scenario** required to consider the RedCell_OS Minimum Viable Product (MVP) complete. 

Any build of RedCell_OS is classified as **"MVP Complete"** if and only if it can successfully execute this complete workflow autonomously—from operator input to final report generation—against a simulated, sandboxed target while adhering to all safety, event sourcing, and approval constraints.

This scenario is designed to serve directly as the primary acceptance test specification for milestone **P70 (End-to-End System Integration & Testing)**.

---

## 2. Minimal Architecture & Role Footprint

To prevent over-engineering while fully validating the multi-agent orchestration lifecycle, the MVP uses a minimal footprint of **3 specialist roles** plus the **CISO Supervisor**:

```
                              ┌─────────────────────────────┐
                              │     Operator (Human UI)     │
                              └──────────────┬──────────────┘
                                             │ Submit Engagement & ROE
                                             ▼
                              ┌─────────────────────────────┐
                              │         CISO Agent          │
                              │    (Decomposes Mission)     │
                              └──────────────┬──────────────┘
                                             │
                       ┌─────────────────────┼─────────────────────┐
                       │                     │                     │
                       ▼                     ▼                     ▼
              ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
              │ 1. Recon Agent  │──▶│  2. Vuln Agent  │──▶│ 3. Report Agent │
              │ (Web Discovery) │   │ (Web Assessor)  │   │(Technical Writer│
              └─────────────────┘   └─────────────────┘   └─────────────────┘
                       │                     │                     │
                       ▼                     ▼                     ▼
                Target Discovery      Finding Confirmed      Final Report
```

| Agent ID | Assigned Role | Department | Primary Objective in MVP Scenario |
|---|---|---|---|
| `agent-ciso-01` | `role_ciso` | Executive | Ingests ROE, generates 3-task execution DAG, monitors lifecycle, performs final sign-off. |
| `agent-recon-01` | `role_web_discovery` | `dept_recon` | Probes mock target server, discovers exposed `/api/v1/debug/config` endpoint. |
| `agent-vuln-01` | `role_web_vuln_assessor` | `dept_vulnerability` | Triggers approval gate, validates unauthenticated secret leakage, logs `FINDING-001`. |
| `agent-report-01` | `role_technical_writer` | `dept_reporting` | Collects finding evidence & logs, compiles final Markdown penetration test report. |

---

## 3. Simulated Target Environment

The MVP operates against an isolated local mock service to eliminate external network dependencies:

- **Target Identifier:** `mock-internal-portal`
- **Target URL:** `http://127.0.0.1:8088`
- **Simulated Vulnerability:** Unauthenticated Sensitive Information Exposure (CWE-200 / OWASP A01:2021-Broken Access Control).
- **Target Endpoint Behavior:**
  - `GET /` $\rightarrow$ `HTTP 200 OK` (Welcome to Staging Portal).
  - `GET /robots.txt` $\rightarrow$ `HTTP 200 OK` (`Disallow: /api/v1/debug/config`).
  - `GET /api/v1/debug/config` $\rightarrow$ `HTTP 200 OK` returns JSON containing mock production secrets:
    ```json
    {
      "environment": "staging",
      "jwt_secret": "mock_jwt_secret_key_prod_987654321",
      "database_url": "postgres://admin:SuperSecretPass123@10.0.0.5:5432/core_db",
      "debug_mode": true
    }
    ```

---

## 4. End-to-End Execution Sequence

```
Operator                 CISO Agent              Recon Agent             Vuln Agent             Report Agent
   │                         │                       │                       │                       │
   │── Submit ROE & Start ──▶│                       │                       │                       │
   │                         │── Decompose to DAG ──▶│                       │                       │
   │                         │                       │── Probe Port 8088 ───▶│                       │
   │                         │                       │   (Discovers Debug)   │                       │
   │                         │                       │── Emit Artifact ─────▶│                       │
   │                         │                                               │                       │
   │                         │◀── Request Approval (GATE-01) ────────────────│                       │
   │◀── Prompt Operator ─────│                                               │                       │
   │── Approve Gate-001 ────▶│                                               │                       │
   │                         │── Gate Approved ─────────────────────────────▶│                       │
   │                         │                                               │── Verify Secret Leak ─│
   │                         │                                               │── Record FINDING-001 ─│
   │                         │                                                                       │
   │                         │── Trigger Reporting ─────────────────────────────────────────────────▶│
   │                         │                                                                       │── Compile Markdown
   │                         │◀── Report Complete ───────────────────────────────────────────────────│
   │◀── Final Report Ready ──│
```

---

## 5. Detailed Step-by-Step Scenario Script

### Step 0: Initial State & Target Initialization
- The backend mock web target starts listening on `127.0.0.1:8088`.
- The operator uploads the valid ROE manifest:
  ```json
  {
    "engagement_id": "eng-mvp-001",
    "version": "1.0.0",
    "authorization": {
      "organization": "Localhost Security Lab",
      "authorized_by": "Security Lead",
      "operator_id": "operator-01",
      "authorization_reference": "LAB-AUTH-2026-MVP"
    },
    "time_window": {
      "valid_from_utc": "2026-08-01T00:00:00Z",
      "valid_until_utc": "2026-12-31T23:59:59Z",
      "timezone": "UTC",
      "emergency_freeze": false
    },
    "target_scope": {
      "allowed_targets": {
        "ipv4_cidrs": ["127.0.0.1/32"],
        "ipv6_cidrs": [],
        "domains": ["localhost"],
        "ports": ["8088"],
        "cloud_accounts": []
      },
      "excluded_targets": {
        "ipv4_cidrs": [],
        "domains": [],
        "sensitive_endpoints": []
      }
    },
    "capability_boundaries": {
      "max_intensity": "vulnerability_verification",
      "allowed_tactics": ["TA0043", "TA0007", "TA0001"],
      "prohibited_actions": ["DENIAL_OF_SERVICE"],
      "rate_limits": {
        "max_packets_per_sec": 100,
        "max_concurrent_tasks": 2,
        "max_bandwidth_kbps": 1024
      }
    },
    "approval_gates": {
      "mandatory_categories": ["ACTIVE_EXPLOITATION_PROBE"],
      "default_timeout_seconds": 120
    }
  }
  ```

---

### Step 1: Engagement Ingestion & CISO Decomposition
1. The operator sends command `START_ENGAGEMENT` with ROE payload.
2. The `agent-ciso-01` verifies ROE structure and validates scope parameters.
3. CISO creates execution DAG with 3 tasks:
   - `TASK-01` (`dept_recon`): Discover web routes and endpoints on `http://127.0.0.1:8088`.
   - `TASK-02` (`dept_vulnerability`): Assess discovered endpoints for information leakage and access control flaws (depends on `TASK-01`).
   - `TASK-03` (`dept_reporting`): Synthesize findings into final penetration test report (depends on `TASK-02`).
4. System emits `engagement_started` event.

---

### Step 2: Reconnaissance Phase (`agent-recon-01`)
1. Workspace `/workspaces/agent-recon-01/` is provisioned.
2. `agent-recon-01` transitions FSM to `EXECUTING`.
3. Agent executes HTTP crawl against `http://127.0.0.1:8088/robots.txt` and `http://127.0.0.1:8088/`.
4. Endpoint discovered: `/api/v1/debug/config`.
5. Agent writes discovery artifact `/workspaces/agent-recon-01/endpoints.json`.
6. Artifact is hashed (`SHA-256`) and saved to CAS.
7. Agent transitions FSM to `COMPLETED` and emits `task_completed` event with output reference.

---

### Step 3: Vulnerability Assessment & Approval Gate (`agent-vuln-01`)
1. Workspace `/workspaces/agent-vuln-01/` is provisioned.
2. `agent-vuln-01` ingests `endpoints.json` from Task 1.
3. Agent identifies potential unauthenticated debug endpoint `/api/v1/debug/config`.
4. Because querying and verifying sensitive configuration exposure is categorized under `ACTIVE_EXPLOITATION_PROBE`, the agent halts.
5. `agent-vuln-01` transitions FSM to `AWAITING_APPROVAL` and emits `approval_requested` event:
   ```json
   {
     "event_type": "approval_requested",
     "gate_id": "gate-req-001",
     "task_id": "TASK-02",
     "agent_id": "agent-vuln-01",
     "category": "ACTIVE_EXPLOITATION_PROBE",
     "target_uri": "http://127.0.0.1:8088/api/v1/debug/config",
     "risk_description": "Probe unauthenticated configuration endpoint to verify active secret leakage."
   }
   ```
6. The human operator reviews the prompt in the UI and submits an `approval_granted` event with `gate_id: "gate-req-001"`.
7. `agent-vuln-01` receives approval, transitions to `EXECUTING`, and sends a GET request to the target.
8. Response contains hardcoded credentials. Agent confirms exploitability.
9. Agent constructs standardized finding:
   ```json
   {
     "finding_id": "FINDING-001",
     "title": "Unauthenticated Sensitive Configuration and Credential Exposure",
     "severity": "HIGH",
     "cvss_v31_score": 7.5,
     "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
     "cwe_id": "CWE-200",
     "target_url": "http://127.0.0.1:8088/api/v1/debug/config",
     "description": "The debug configuration endpoint is exposed without authentication, leaking sensitive database credentials and JWT signing keys.",
     "evidence": "{\"jwt_secret\":\"mock_jwt_secret_key_prod_987654321\",\"database_url\":\"postgres://admin:SuperSecretPass123@...\"}",
     "remediation": "Restrict access to debug endpoints, enforce mandatory OAuth/API key authentication, and remove sensitive production secrets from configuration files."
   }
   ```
10. Finding is persisted in relational database and emitted via `finding_recorded` event.
11. `agent-vuln-01` completes `TASK-02`.

---

### Step 4: Report Generation (`agent-report-01`)
1. Workspace `/workspaces/agent-report-01/` is provisioned.
2. `agent-report-01` queries the engagement database for all findings, recon artifacts, and timing metadata.
3. Agent compiles `report_eng-mvp-001.md`:
   - Title: *Penetration Testing Assessment Report — Engagement eng-mvp-001*
   - Executive Summary
   - Scope Summary & Timeline
   - Discovered Findings Table (High: 1, Medium: 0, Low: 0, Info: 0)
   - Detailed Technical Breakdown for `FINDING-001` (CVSS, CWE, Proof-of-Concept Curl Command, Remediation)
4. Artifact saved to `/engagements/eng-mvp-001/deliverables/report_eng-mvp-001.md`.
5. Emits `report_generated` event.
6. `agent-report-01` completes `TASK-03`.

---

### Step 5: Engagement Wrap-Up & Sign-Off
1. `agent-ciso-01` validates that all DAG tasks are in state `COMPLETED`.
2. Emits `engagement_completed` event.
3. System triggers clean workspace teardown. Zero orphaned processes remain.

---

## 6. Verifiable Event Stream Sequence

The automated E2E test runner asserts that the following ordered event sequence occurs:

```
1.  [system]            engagement_created        (engagement_id: eng-mvp-001)
2.  [agent-ciso-01]     plan_decomposed           (task_count: 3)
3.  [agent-recon-01]    agent_state_changed       (state: PLANNING -> EXECUTING)
4.  [agent-recon-01]    command_executed          (target: 127.0.0.1:8088/robots.txt)
5.  [agent-recon-01]    artifact_generated        (artifact: endpoints.json)
6.  [agent-recon-01]    agent_state_changed       (state: EXECUTING -> COMPLETED)
7.  [agent-vuln-01]     agent_state_changed       (state: PLANNING -> AWAITING_APPROVAL)
8.  [agent-vuln-01]     approval_requested        (gate_id: gate-req-001)
9.  [operator]          approval_granted          (gate_id: gate-req-001)
10. [agent-vuln-01]     agent_state_changed       (state: AWAITING_APPROVAL -> EXECUTING)
11. [agent-vuln-01]     finding_recorded          (finding_id: FINDING-001, severity: HIGH)
12. [agent-vuln-01]     agent_state_changed       (state: EXECUTING -> COMPLETED)
13. [agent-report-01]   agent_state_changed       (state: PLANNING -> EXECUTING)
14. [agent-report-01]   report_generated          (path: report_eng-mvp-001.md)
15. [agent-report-01]   agent_state_changed       (state: EXECUTING -> COMPLETED)
16. [agent-ciso-01]     engagement_completed      (status: SUCCESS)
```

---

## 7. Acceptance Criteria for MVP Sign-off (Phase P70 Readiness)

To pass the MVP Acceptance Test:
- [x] **Zero Manual Code Interventions:** The full workflow runs from start to finish via backend API / WebSocket signals.
- [x] **Strict Scope Guardrails:** `0` network requests directed at any host other than `127.0.0.1:8088`.
- [x] **Mandatory Gate Verification:** `TASK-02` must strictly block and refuse execution until `approval_granted` event is received.
- [x] **Report Integrity:** Generated `report_eng-mvp-001.md` must contain valid CVSS 7.5 score, CWE-200 reference, target URL, and accurate reproduction proof.
- [x] **Clean Teardown:** After completion, all child agent subprocesses and temporary scratch files are cleaned up without memory leaks.
