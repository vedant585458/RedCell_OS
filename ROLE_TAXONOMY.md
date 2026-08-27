# Role Taxonomy & Agent Organization: RedCell_OS

**Document Version:** 1.0.0  
**Milestone:** M003 — Define agent taxonomy requirements  
**Phase:** P01 — Vision and Requirements  
**Status:** Approved & Canonical  
**Dependencies:** [VISION.md](VISION.md) (M001), [SECURITY_CONSTRAINTS.md](SECURITY_CONSTRAINTS.md) (M002)  

---

## 1. Architectural Philosophy: Roles as Data, Not Code

In RedCell_OS, **roles are defined declaratively as data manifests (JSON/YAML), never hardcoded Python classes**.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        ROLE DEFINITION PARADIGM                        │
├────────────────────────────────────────────────────────────────────────┤
│  ❌ Anti-Pattern:                                                      │
│     class WebScannerAgent(BaseAgent):                                  │
│         def scan_sqli(self): ...                                       │
│                                                                        │
│  ✅ RedCell_OS Data-Driven Pattern:                                    │
│     Unified Agent Runtime Engine + Role Manifest (YAML/JSON Schema)    │
│     ├── System Prompt Template & Persona                               │
│     ├── Allowed Tool Allowlist                                         │
│     ├── Triggered Approval Gate Categories                             │
│     ├── Required Capabilities & Output Schemas                         │
│     └── Resource & Execution Quotas                                    │
└────────────────────────────────────────────────────────────────────────┘
```

This design guarantees that adding, updating, or customizing specialist roles requires **zero changes to core engine code**—enabling dynamic extension via the Role & Capability Registry (milestone P11).

---

## 2. Organization Hierarchy & Department Structure

The virtual penetration testing firm is organized into 6 functional departments overseen by Executive Leadership and a dedicated Safety & Governance Sentinel.

```
                     ┌──────────────────────────────┐
                     │          CISO Agent          │
                     │    (Executive Leadership)    │
                     └──────────────┬───────────────┘
                                    │
                     ┌──────────────┴───────────────┐
                     │  Engagement Manager Agent    │
                     │     (Tactical Planning)      │
                     └──────────────┬───────────────┘
                                    │
    ┌────────────────┬──────────────┼───────────────┬────────────────┬──────────────┐
    │                │              │               │                │              │
    ▼                ▼              ▼               ▼                ▼              ▼
┌────────────┐ ┌────────────┐ ┌───────────┐ ┌───────────────┐ ┌────────────┐ ┌────────────┐
│ Recon Dept │ │ Vuln Dept  │ │ Exploit   │ │ Purple Team   │ │ Report     │ │ Safety     │
│            │ │            │ │ Dept      │ │ & Telemetry   │ │ Dept       │ │ Sentinel   │
└────────────┘ └────────────┘ └───────────┘ └───────────────┘ └────────────┘ └────────────┘
```

---

## 3. Specialist Role Enumeration & Responsibilities

### 3.1 Executive Leadership & Management

#### 1. Chief Information Security Officer (CISO) Agent (`role_ciso`)
The CISO Agent acts as the strategic director of the engagement. It ingests the client's high-level objectives and authorized Rules of Engagement (ROE), decomposes the mission into departmental phases and milestones, resolves inter-departmental roadblocks, enforces organizational safety policies, and performs the final executive review of engagement deliverables before client submission.

#### 2. Engagement Manager Agent (`role_engagement_manager`)
The Engagement Manager Agent is the tactical orchestrator responsible for compiling the CISO’s high-level mission into an executable Directed Acyclic Graph (DAG) of discrete tasks. It schedules tasks, provisions isolated agent workspaces, continuously monitors agent status transitions (FSM states), manages task dependency resolution, and escalates blocked tasks or approval requests to the human operator.

---

### 3.2 Reconnaissance & OSINT Department (`dept_recon`)

#### 3. Passive OSINT Specialist (`role_passive_osint`)
The Passive OSINT Specialist gathers external intelligence on the target organization without directly transmitting packets to the target’s network infrastructure. It searches public DNS records, Certificate Transparency logs, WHOIS registries, public code repositories, and leaked credential databases to map organizational domains, subdomains, external cloud assets, and employee email schemes.

#### 4. Active Network Recon Specialist (`role_active_network_recon`)
The Active Network Recon Specialist conducts direct, authorized probing of target IP ranges and host infrastructure strictly within allowlisted CIDRs. It executes host discovery, TCP/UDP port enumeration, service version identification, and operating system fingerprinting to establish an accurate network perimeter map while adhering strictly to configured packet rate limits.

#### 5. Web Asset Discovery Specialist (`role_web_discovery`)
The Web Asset Discovery Specialist maps web applications, REST/GraphQL API endpoints, and exposed web services. It crawls public sitemaps, analyzes JavaScript bundles for hidden routes and endpoints, profiles underlying web application frameworks and CMS platforms, and builds a comprehensive target attack surface inventory for downstream vulnerability analysis.

---

### 3.3 Vulnerability Assessment Department (`dept_vulnerability`)

#### 6. Network & Infrastructure Vulnerability Specialist (`role_infra_vuln_assessor`)
The Network & Infrastructure Vulnerability Specialist analyzes discovered open ports, network services, and server software versions against known vulnerability databases (CVE/NVD/EPSS). It inspects SSL/TLS cipher configurations, identifies outdated service daemons (e.g., OpenSSH, Apache, SMB), tests for default administrative credentials, and detects misconfigured network perimeter devices.

#### 7. Web Application Security Specialist (`role_web_vuln_assessor`)
The Web Application Security Specialist analyzes web applications and APIs for software security flaws aligned with the OWASP Top 10. It systematically constructs benign, non-destructive test inputs to identify vulnerabilities such as SQL Injection, Cross-Site Scripting (XSS), Server-Side Request Forgery (SSRF), Insecure Direct Object References (IDOR), and broken authentication logic.

#### 8. Cloud & Container Security Specialist (`role_cloud_container_assessor`)
The Cloud & Container Security Specialist investigates cloud infrastructure and containerized environments for architectural misconfigurations. It analyzes public cloud bucket permissions, evaluates exposed container runtime interfaces (Docker socket, Kubernetes API), tests IAM role trust policies for privilege escalation vulnerabilities, and probes cloud metadata endpoints (`169.254.169.254`).

---

### 3.4 Exploitation & Verification Department (`dept_exploitation`)

#### 9. Exploitation Verification Specialist (`role_exploit_verifier`)
The Exploitation Verification Specialist executes controlled, safe proof-of-concept (PoC) probes to definitively confirm the exploitability of high-risk vulnerabilities flagged by assessment agents. Operating under mandatory Human-in-the-Loop approval gates (GATE-01), it confirms whether a vulnerability is a true positive by demonstrating benign control (e.g., retrieving an echo token or `whoami` proof) without causing system instability or denial of service.

#### 10. Credential & Privilege Escalation Specialist (`role_privesc_credential_analyst`)
The Credential & Privilege Escalation Specialist evaluates post-access security posture by analyzing captured password hashes, authentication tokens, configuration secrets, and misconfigured local permissions. It models privilege escalation paths (e.g., sudo misconfigurations, SUID binaries, Active Directory Kerberoasting) and validates whether standard user permissions can lead to administrative access within authorized boundaries.

#### 11. Adversary Emulation / ATT&CK Specialist (`role_adversary_emulator`)
The Adversary Emulation Specialist translates specific cyber threat actor behaviors into deterministic simulation sequences mapped to the MITRE ATT&CK framework. It executes benign atomic test units (e.g., simulated discovery commands, mock persistence mechanisms) to produce the exact telemetry signatures required for defense detection verification.

---

### 3.5 Purple Team & Defense Analysis Department (`dept_purple_telemetry`)

#### 12. Detection & Telemetry Analyst (`role_detection_analyst`)
The Detection & Telemetry Analyst correlates simulated offensive operations against defensive logging infrastructure (SIEM, EDR, Syslog). It analyzes whether executed adversary techniques generated appropriate alerts, calculates the Time-to-Detect (TTD), identifies detection blind spots, and produces a quantified MITRE ATT&CK defensive coverage score.

#### 13. Remediation & Hardening Advisor (`role_remediation_advisor`)
The Remediation & Hardening Advisor translates technical vulnerability findings and detection gaps into prioritized, practical mitigation blueprints. It generates specific patch recommendations, configuration hardening snippets (e.g., Nginx configs, IAM policies, Sigma detection rules), and architectural guidance tailored to the target system's technology stack.

---

### 3.6 Reporting & Technical Writing Department (`dept_reporting`)

#### 14. Technical Report Writer (`role_technical_writer`)
The Technical Report Writer aggregates findings, vulnerability descriptions, step-by-step reproduction steps, raw tool outputs, and remediation strategies into a standardized, professional Markdown and PDF technical penetration testing report. It ensures all vulnerability descriptions follow standard CVSS v3.1/v4.0 scoring guidelines and include precise evidence artifacts.

#### 15. Executive Briefing Specialist (`role_executive_briefer`)
The Executive Briefing Specialist synthesizes complex technical vulnerabilities into clear, high-level business risk assessments for C-suite executives and board members. It visualizes risk posture through executive summaries, compliance impact matrices (SOC 2, ISO 27001, HIPAA), and strategic budget allocation recommendations.

---

### 3.7 Governance & Safety Sentinel (`dept_governance`)

#### 16. ROE Safety Sentinel Agent (`role_safety_sentinel`)
The ROE Safety Sentinel Agent is an independent, non-offensive supervisor running in parallel with all active tasks. It continuously monitors the execution event stream, validates task parameters against the machine-readable ROE allowlists, ensures rate limits are never exceeded, pauses operations if unexpected behavior occurs, and triggers emergency kill-switch routines upon detecting anomalies.

---

## 4. Shared Capabilities Across All Roles

Regardless of specialization, all agents share a standard core capability foundation implemented by the unified Agent Runtime Engine:

| Core Capability | Description | Architectural Implementation |
|---|---|---|
| **Event Emission & Tracing** | Emits structured, correlated lifecycle and telemetry events (`task_started`, `tool_invoked`, `finding_discovered`, `task_finished`). | Universal WebSocket/Event-Source logger with UUIDv4 correlation IDs. |
| **Workspace Isolation** | Executes within a private, dedicated scratchpad directory with no access to sibling agent workspaces. | Per-agent ephemeral directory mount (`/workspaces/{agent_id}/`). |
| **FSM State Management** | Transitions strictly through valid finite-state machine lifecycles. | Core FSM Engine (`IDLE` $\rightarrow$ `PLANNING` $\rightarrow$ `AWAITING_APPROVAL` $\rightarrow$ `EXECUTING` $\rightarrow$ `REPORTING` $\rightarrow$ `COMPLETED` / `FAILED`). |
| **Scope Self-Check** | Validates intended targets before submitting tool calls. | Pre-flight ROE verification client library. |
| **Artifact Stashing** | Hashes, timestamps, and persists raw scan outputs, evidence logs, and diagrams. | Content-Addressable Storage (CAS) client. |
| **Inter-Agent Communication** | Exchanges structured messages and task handoffs via standard message schemas. | Event bus / DAG dependency pipeline. |

---

## 5. Role-Specific Tool Requirements

Each role operates with a strictly constrained set of permitted tools declared in its manifest:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ROLE-SPECIFIC TOOL MATRIX                         │
├──────────────────────────┬──────────────────────────────────────────────────┤
│ Specialist Role          │ Permitted Tool Binaries & Capabilities           │
├──────────────────────────┼──────────────────────────────────────────────────┤
│ Passive OSINT            │ subfinder, amass, dnsx, whois, crtsh, shodan_api │
├──────────────────────────┼──────────────────────────────────────────────────┤
│ Active Network Recon     │ nmap (SYN/TCP), masscan (rate-capped), naabu     │
├──────────────────────────┼──────────────────────────────────────────────────┤
│ Web Asset Discovery      │ httpx, katana, ffuf (dir/param), gau, wappalyzer │
├──────────────────────────┼──────────────────────────────────────────────────┤
│ Infra Vuln Assessor      │ nmap-scripts (vuln), testssl.sh, snmpwalk        │
├──────────────────────────┼──────────────────────────────────────────────────┤
│ Web Vuln Assessor        │ nuclei (safe templates), dalfox, sqlmap (read)   │
├──────────────────────────┼──────────────────────────────────────────────────┤
│ Cloud/Container Assessor │ prowler, scoutsuite, trivy, cloudlist            │
├──────────────────────────┼──────────────────────────────────────────────────┤
│ Exploit Verifier         │ sandboxed-python-poc-runner, custom safe probes  │
├──────────────────────────┼──────────────────────────────────────────────────┤
│ PrivEsc / Credential     │ hashcat (offline benchmark), linpeas, winpeas    │
├──────────────────────────┼──────────────────────────────────────────────────┤
│ Adversary Emulator       │ atomic-red-team runner, custom TTP scripts       │
├──────────────────────────┼──────────────────────────────────────────────────┤
│ Detection Analyst        │ sigma-compiler, elasticsearch-client, splunk-sdk │
├──────────────────────────┼──────────────────────────────────────────────────┤
│ Technical Writer         │ pandoc, markdown-generator, cvss-calculator      │
├──────────────────────────┼──────────────────────────────────────────────────┤
│ Executive Briefer        │ chartjs-renderer, executive-summary-generator    │
├──────────────────────────┼──────────────────────────────────────────────────┤
│ Safety Sentinel          │ iptables-monitor, process-tree-auditor, kill-api │
└──────────────────────────┴──────────────────────────────────────────────────┘
```

---

## 6. Declarative Role Manifest Schema (Example)

Below is an example of the declarative schema used to register roles in the system without writing Python code:

```yaml
role_id: "role_web_vuln_assessor"
name: "Web Application Security Specialist"
department: "dept_vulnerability"
version: "1.0.0"

system_prompt_template: "prompts/roles/web_vuln_assessor.jinja2"

capabilities:
  - "web_crawling"
  - "owasp_top10_analysis"
  - "api_fuzzing"
  - "cvss_scoring"

allowed_tools:
  - "nuclei"
  - "httpx"
  - "ffuf"
  - "custom_http_probe"

approval_gates:
  trigger_on_actions:
    - "ACTIVE_EXPLOITATION_PROBE"
    - "HIGH_RATE_FUZZING"

quotas:
  max_execution_time_sec: 600
  max_memory_mb: 1024
  max_network_bandwidth_kbps: 2048
  max_concurrent_subprocesses: 2
```

---

## 7. Milestone Summary & Next Steps

This document establishes the canonical role taxonomy required for **M003**. It directly informs:
1. **P11 (Role and Capability Registries):** Implementation of dynamic role loaders and schemas.
2. **P12 (Agent FSM):** Finite-state machine mechanics across all agent lifecycles.
3. **P14 (Tool Sandboxing):** Enforcement of role-specific tool execution boundaries.
