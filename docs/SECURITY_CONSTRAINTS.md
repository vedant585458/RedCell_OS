# Security Constraints & Authorized-Use Architecture: RedCell_OS

**Document Version:** 1.0.0  
**Milestone:** M002 — Define authorized-use and legal constraints  
**Phase:** P01 — Vision and Requirements  
**Status:** Approved & Canonical  
**Dependencies:** [VISION.md](VISION.md) (M001)  

---

## 1. Executive Summary & Legal Mandate

RedCell_OS is an adversary emulation and automated penetration testing platform designed strictly for authorized, pre-approved security engagements. Under no circumstances should RedCell_OS operate without explicit authorization, nor can any agent execute actions against targets outside the designated boundary.

To ensure strict legal compliance, prevent unintentional disruption of production systems, and guarantee that simulated activities remain bounded, security constraints are enforced as **first-class architectural primitives** at the lowest execution boundary rather than mere high-level LLM guidance.

### Core Guarantees:
1. **Zero Out-of-Scope Execution:** All network, system, and tool calls are intercepted and mathematically validated against an immutable Scope of Work allowlist.
2. **Deterministic Kill Switch:** Universal and granular emergency-stop capabilities that terminate agent processes in $< 200\text{ ms}$.
3. **Mandatory Human-in-the-Loop Gates:** Dangerous, active, or privilege-escalating actions require cryptographically verifiable operator sign-off.
4. **Tamper-Evident Audit Trails:** Every command, network interaction, agent decision, and operator approval is persisted in an append-only, correlation-indexed event log.

---

## 2. Machine-Readable Rules of Engagement (ROE) Specification

Free-text scope descriptions introduce ambiguity that automated agents cannot reliably enforce. In RedCell_OS, all Rules of Engagement (ROE) must be provided as a **validated, structured JSON or YAML document** conforming to the strict schema below.

### 2.1 Complete ROE Schema (JSON Schema Definition)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "RedCell_OS_RulesOfEngagement",
  "type": "object",
  "required": [
    "engagement_id",
    "version",
    "authorization",
    "time_window",
    "target_scope",
    "capability_boundaries",
    "approval_gates"
  ],
  "properties": {
    "engagement_id": {
      "type": "string",
      "pattern": "^eng-[a-zA-Z0-9_-]{8,32}$"
    },
    "version": {
      "type": "string",
      "pattern": "^\\d+\\.\\d+\\.\\d+$"
    },
    "authorization": {
      "type": "object",
      "required": ["organization", "authorized_by", "operator_id", "authorization_reference"],
      "properties": {
        "organization": { "type": "string" },
        "authorized_by": { "type": "string" },
        "operator_id": { "type": "string" },
        "authorization_reference": { "type": "string" },
        "signature_hash": { "type": "string" }
      }
    },
    "time_window": {
      "type": "object",
      "required": ["valid_from_utc", "valid_until_utc", "timezone"],
      "properties": {
        "valid_from_utc": { "type": "string", "format": "date-time" },
        "valid_until_utc": { "type": "string", "format": "date-time" },
        "timezone": { "type": "string", "default": "UTC" },
        "allowed_hours_cron": { "type": "string", "description": "Optional cron or schedule window" },
        "emergency_freeze": { "type": "boolean", "default": false }
      }
    },
    "target_scope": {
      "type": "object",
      "required": ["allowed_targets", "excluded_targets"],
      "properties": {
        "allowed_targets": {
          "type": "object",
          "required": ["ipv4_cidrs", "ipv6_cidrs", "domains", "ports"],
          "properties": {
            "ipv4_cidrs": {
              "type": "array",
              "items": { "type": "string", "format": "ipv4-cidr" }
            },
            "ipv6_cidrs": {
              "type": "array",
              "items": { "type": "string", "format": "ipv6-cidr" }
            },
            "domains": {
              "type": "array",
              "items": { "type": "string", "pattern": "^(\\*\\.)?[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$" }
            },
            "ports": {
              "type": "array",
              "items": { "type": "string", "pattern": "^(\\d{1,5}|\\d{1,5}-\\d{1,5})$" }
            },
            "cloud_accounts": {
              "type": "array",
              "items": { "type": "string" }
            }
          }
        },
        "excluded_targets": {
          "type": "object",
          "required": ["ipv4_cidrs", "domains"],
          "properties": {
            "ipv4_cidrs": {
              "type": "array",
              "items": { "type": "string" }
            },
            "ipv6_cidrs": {
              "type": "array",
              "items": { "type": "string" }
            },
            "domains": {
              "type": "array",
              "items": { "type": "string" }
            },
            "sensitive_endpoints": {
              "type": "array",
              "items": { "type": "string" }
            }
          }
        }
      }
    },
    "capability_boundaries": {
      "type": "object",
      "required": ["max_intensity", "allowed_tactics", "prohibited_actions", "rate_limits"],
      "properties": {
        "max_intensity": {
          "type": "string",
          "enum": ["passive_recon", "active_recon", "vulnerability_verification", "safe_exploitation"]
        },
        "allowed_tactics": {
          "type": "array",
          "items": { "type": "string" }
        },
        "prohibited_actions": {
          "type": "array",
          "items": { "type": "string" }
        },
        "rate_limits": {
          "type": "object",
          "required": ["max_packets_per_sec", "max_concurrent_tasks"],
          "properties": {
            "max_packets_per_sec": { "type": "integer", "minimum": 1 },
            "max_concurrent_tasks": { "type": "integer", "minimum": 1 },
            "max_bandwidth_kbps": { "type": "integer", "minimum": 64 }
          }
        }
      }
    },
    "approval_gates": {
      "type": "object",
      "required": ["mandatory_categories", "default_timeout_seconds"],
      "properties": {
        "mandatory_categories": {
          "type": "array",
          "items": { "type": "string" }
        },
        "default_timeout_seconds": { "type": "integer", "default": 300 }
      }
    }
  }
}
```

### 2.2 Example ROE Instance (YAML Format)

```yaml
engagement_id: "eng-2026-q3-corp-audit"
version: "1.0.0"

authorization:
  organization: "Acme Financial Services"
  authorized_by: "Jane Doe, Chief Information Security Officer"
  operator_id: "op-sec-vedant"
  authorization_reference: "SOW-2026-ACME-0912"
  signature_hash: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

time_window:
  valid_from_utc: "2026-09-01T08:00:00Z"
  valid_until_utc: "2026-09-15T20:00:00Z"
  timezone: "UTC"
  emergency_freeze: false

target_scope:
  allowed_targets:
    ipv4_cidrs:
      - "10.100.20.0/24"
      - "192.168.10.0/28"
    ipv6_cidrs: []
    domains:
      - "*.staging.acme-corp.internal"
      - "lab.acme-corp.com"
    ports:
      - "80"
      - "443"
      - "8000-8080"
    cloud_accounts:
      - "aws:123456789012"
  excluded_targets:
    ipv4_cidrs:
      - "10.100.20.1/32"    # Primary Gateway
      - "10.100.20.10/32"   # Production DB Mirror
    domains:
      - "prod.acme-corp.internal"
      - "payment-gateway.acme-corp.internal"
    sensitive_endpoints:
      - "/api/v1/payments/execute"
      - "/admin/database/wipe"

capability_boundaries:
  max_intensity: "vulnerability_verification"
  allowed_tactics:
    - "TA0043" # Reconnaissance
    - "TA0042" # Resource Development
    - "TA0001" # Initial Access
    - "TA0007" # Discovery
    - "TA0008" # Lateral Movement
  prohibited_actions:
    - "DENIAL_OF_SERVICE"
    - "PERMANENT_DESTRUCTION"
    - "UNSAFE_CREDENTIAL_SPRAY_EXCEEDING_LOCKOUT"
    - "PERSISTENT_FIRMWARE_MODIFICATION"
  rate_limits:
    max_packets_per_sec: 500
    max_concurrent_tasks: 4
    max_bandwidth_kbps: 4096

approval_gates:
  mandatory_categories:
    - "ACTIVE_EXPLOITATION_PROBE"
    - "CREDENTIAL_REUSE_ATTEMPT"
    - "SUBNET_BOUNDARY_CROSSING"
    - "HIGH_RATE_FUZZING"
  default_timeout_seconds: 300
```

---

## 3. Boundary Enforcement Architecture

To guarantee that agent tasks cannot bypass scope rules, validation happens at the **execution boundary** (subprocess launcher and network interceptor), completely decoupled from LLM prompt compliance.

```
                    ┌──────────────────────────────────────────────┐
                    │            Agent LLM Output / Plan           │
                    └──────────────────────┬───────────────────────┘
                                           │ Request Command / Action
                                           ▼
                    ┌──────────────────────────────────────────────┐
                    │      Backend Command Dispatch Layer          │
                    │      (Extracts IP, Domain, Port, Flags)      │
                    └──────────────────────┬───────────────────────┘
                                           │
                                           ▼
                        ┌─────────────────────────────────────┐
                        │   Scope Validator (Fail-Closed)     │
                        ├─────────────────────────────────────┤
                        │ 1. Time Window Check (Valid Now?)   │
                        │ 2. Target IP in Excluded CIDR?      │
                        │ 3. DNS Resolved IP in Allowed CIDR? │
                        │ 4. Domain matches Regex Allowlist?  │
                        │ 5. Port in Allowed Ranges?          │
                        │ 6. Technique in Allowed Tactics?    │
                        │ 7. Rate Limits Respected?           │
                        └──────────────┬───────────────┬──────┘
                                       │               │
                                    [PASS]          [FAIL]
                                       │               │
                                       ▼               ▼
                        ┌─────────────────────┐   ┌─────────────────────────┐
                        │ Approval Gate Check │   │ REJECT & LOG VIOLATION  │
                        │ (Requires Operator  │   │ (SecurityAlert Event    │
                        │  Sign-off?)         │   │  Correlation Trace)     │
                        └──────────┬──────────┘   └─────────────────────────┘
                                   │
                                   ▼
                        ┌─────────────────────────────────────┐
                        │ Sandboxed Subprocess Execution Host │
                        └─────────────────────────────────────┘
```

### Dual-Layer Validation Mechanics
1. **Pre-Flight Planning Validator:** During CISO decomposition and agent planning, proposed tasks are evaluated against the ROE. If out of scope, the plan is rejected at the prompt/reasoning level.
2. **Deterministic Runtime Interceptor (Kernel/Subprocess Level):** Even if an LLM hallucinates an out-of-scope IP inside an arbitrary bash tool script (e.g. `curl -k https://192.168.1.100/`), the execution wrapper parses targets, performs pre-execution DNS resolution, and executes a hard block before spawning the process.
3. **Anti-DNS Rebinding Protection:** The runtime resolver pins the resolved IP before validation and injects the resolved IP directly into network calls to prevent Time-of-Check to Time-of-Use (TOCTOU) DNS rebinding attacks.

---

## 4. Emergency Kill-Switch Architecture & Protocol

A real-world simulator must have a zero-latency fail-safe mechanism. The kill-switch architecture in RedCell_OS operates at three granular levels:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       KILL-SWITCH HIERARCHY & TIMING                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Global Engagement Kill-Switch                                            │
│    • Target: Entire Engagement Runner.                                      │
│    • Mechanism: Broadcasts SIGKILL to all agent workspace process groups;   │
│      revokes IPC tokens; closes active sockets.                             │
│    • SLA: < 200ms from button click / API trigger to total process halt.    │
├─────────────────────────────────────────────────────────────────────────────┤
│ 2. Department / Agent-Level Kill-Switch                                     │
│    • Target: Specific misbehaving or stalled Agent (e.g., Recon Agent 02).  │
│    • Mechanism: Terminates agent's sandbox container/subprocess, freezes    │
│      its state machine into `EMERGENCY_HALTED`, notifies CISO orchestrator. │
├─────────────────────────────────────────────────────────────────────────────┤
│ 3. Target Host / Range Freeze                                               │
│    • Target: Specific IP or CIDR (e.g., target reporting unexpected load).  │
│    • Mechanism: Dynamically injects the target into `excluded_targets`,     │
│      canceling any active or queued task directed at that host.             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Fail-Safe Cleanup & Rollback Guarantee
- Every task requiring temporary file creation or artifact deployment registers an idempotent **rollback script**.
- When a kill switch is tripped, the backend spawns a dedicated cleanup worker that executes registered rollbacks sequentially, logging all artifact removals.

---

## 5. Mandatory Human-in-the-Loop Approval Gates

Approval gates are **first-class workflow nodes** in the state machine. When an agent determines that a proposed action falls into a gated category, it transitions to `AWAITING_APPROVAL` and emits an event to the frontend.

### 5.1 Mandatory Gate Categories

| Gate Category | Trigger Condition | Required Operator Prompt / Context |
|---|---|---|
| **GATE-01: Active Exploitation Probe** | Execution of vulnerability verification scripts, proof-of-concept exploits, or service manipulation tools. | Specific CVE/Vulnerability ID, exact command line, targeted host/port, potential service impact score. |
| **GATE-02: Credential & Token Reuse** | Utilizing captured credentials (hashes, API keys, Kerberos tickets) across service boundaries. | Source asset where credential was discovered, target asset for authentication, account privilege level. |
| **GATE-03: Subnet / Perimeter Crossing** | Pivoting or lateral movement from one authorized subnet into a newly discovered authorized segment. | Routing interface, source subnet, target subnet, justification. |
| **GATE-04: High-Rate Scan / Fuzzing** | Executing directory enumeration, port scanning, or fuzzing $> 100\text{ req/sec}$. | Tool name, thread count, target URL/IP, bandwidth estimation. |
| **GATE-05: Cloud Resource Modification** | Interacting with cloud management APIs, IAM policies, or container metadata services. | Cloud provider, Target ARN / Resource ID, API action (`AssumeRole`, `GetObject`, etc.). |

### 5.2 Approval Gate State Flow
```
[Agent Plans Gated Action]
            │
            ▼
[Transition Agent to 'AWAITING_APPROVAL']
            │
            ▼
[Emit 'approval_requested' Event to Frontend with Unique Gate ID]
            │
    ┌───────┴───────┐
    │               │
[Operator Grants] [Operator Rejects / Timeout]
    │               │
    ▼               ▼
[Execute Task]   [Mark Task 'REJECTED' & Provide Operator Reason to Agent]
```

---

## 6. Audit Logging, Storage, and Retention Requirements

To maintain non-repudiation and forensic auditability, every single action in RedCell_OS is recorded as an immutable event.

### 6.1 Audit Event Schema
Every recorded event contains:
- `event_id`: UUIDv4 unique identifier.
- `engagement_id`: Association with current engagement.
- `correlation_id`: Trace chain linking sub-actions to root CISO task.
- `timestamp_utc`: High-resolution ISO 8601 UTC timestamp.
- `agent_id` & `agent_role`: Generating entity.
- `department_id`: Department context.
- `task_id`: Specific task reference.
- `event_type`: Categorical event name (`command_executed`, `approval_granted`, `scope_blocked`, `artifact_created`, etc.).
- `payload`: Structured details (sanitized command, target IP/domain, raw output hash, execution duration, exit code).
- `integrity_hash`: SHA-256 hash chaining previous event hash + current event payload (`Merkle link`).

### 6.2 Audit Storage Architecture
- **Append-Only Relational Log:** SQLite database with WAL (Write-Ahead Logging) enabled.
- **Artifact Vault:** Raw stdout/stderr streams, PCAP captures, and scan results stored on the filesystem in content-addressable storage (`/engagements/{engagement_id}/artifacts/{sha256}`).
- **Retention & Export:**
  - Standard Local Retention: Defaults to retaining all engagement logs indefinitely until explicitly archived.
  - Cryptographic Export Bundle: At engagement conclusion, operators can export a sealed `.redcell.zip` bundle containing SQLite logs, artifacts, and a verification manifest signed with the operator's public key.

---

## 7. Requirement-to-Constraint Traceability Matrix

| Core Architectural Requirement | Enforcing Security Constraint | Verification Mechanism |
|---|---|---|
| **Scope Limitation** | Machine-readable ROE with CIDR/Domain allowlists | Execution boundary socket & subprocess interceptor |
| **Operator Control** | First-class Approval Gates | Blocking FSM state `AWAITING_APPROVAL` with UI prompt |
| **Immediate Containment** | Hierarchical Kill Switch ($< 200\text{ ms}$) | Process group `SIGKILL` + dynamic target exclusion table |
| **Safe Degradation** | Per-agent sandboxed workspaces & rollback scripts | Idempotent cleanup handlers on abnormal termination |
| **Forensic Non-Repudiation** | Event sourcing with SHA-256 hash chaining | Append-only SQLite audit log & verifiable bundle export |
| **No Fabricated State** | Frontend strictly driven by backend event stream | UI renders only validated WebSocket events with correlation IDs |
