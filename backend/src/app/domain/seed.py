"""Idempotent seed utility initializing all departments and specialist roles from ROLE_TAXONOMY.md."""

from typing import Any

from app.core.logging import get_logger
from app.domain.department import DepartmentCreateRequest, DepartmentRepository
from app.domain.role import RoleCreateRequest, RoleQuotasSchema, RoleRepository

logger = get_logger("domain.seed")

# Canonical 7 Departments from ROLE_TAXONOMY.md
SEED_DEPARTMENTS: list[DepartmentCreateRequest] = [
    DepartmentCreateRequest(
        id="dept_executive",
        name="Executive Leadership & Strategy",
        description="Engagement scoping, mission decomposition, and high-level authorization governance.",
        color_theme="purple",
    ),
    DepartmentCreateRequest(
        id="dept_recon",
        name="Reconnaissance & OSINT Department",
        description="External intelligence gathering, asset discovery, and target perimeter mapping.",
        color_theme="blue",
    ),
    DepartmentCreateRequest(
        id="dept_vulnerability",
        name="Vulnerability Assessment Department",
        description="Network service auditing, web application security scanning, and cloud configuration assessment.",
        color_theme="cyan",
    ),
    DepartmentCreateRequest(
        id="dept_exploitation",
        name="Exploitation & Verification Department",
        description="Controlled proof-of-concept verification, credential analysis, and MITRE ATT&CK emulation under approval gates.",
        color_theme="red",
    ),
    DepartmentCreateRequest(
        id="dept_purple_telemetry",
        name="Purple Team & Defense Telemetry",
        description="Detection coverage scoring, SIEM/EDR log correlation, and remediation engineering.",
        color_theme="amber",
    ),
    DepartmentCreateRequest(
        id="dept_reporting",
        name="Technical Writing & Executive Reporting",
        description="Synthesizing assessment telemetry, CVSS calculation, and Markdown/PDF report compilation.",
        color_theme="emerald",
    ),
    DepartmentCreateRequest(
        id="dept_governance",
        name="Safety & Compliance Sentinel",
        description="Real-time ROE scope monitoring, rate-limit enforcement, and emergency kill-switch governance.",
        color_theme="rose",
    ),
]

# Canonical 16 Specialist Roles from ROLE_TAXONOMY.md
SEED_ROLES: list[RoleCreateRequest] = [
    # 1. Executive Leadership
    RoleCreateRequest(
        id="role_ciso",
        name="Chief Information Security Officer (CISO) Agent",
        department_id="dept_executive",
        description="Strategic director of the engagement; decomposes client ROE into department mission DAGs.",
        system_prompt_template="prompts/roles/ciso.jinja2",
        capabilities=[
            "scope_ingestion",
            "mission_decomposition",
            "policy_enforcement",
            "executive_review",
        ],
        allowed_tools=["plan_generator", "dag_builder"],
        approval_gates=[],
        quotas=RoleQuotasSchema(max_execution_time_sec=300, max_memory_mb=1024),
    ),
    RoleCreateRequest(
        id="role_engagement_manager",
        name="Engagement Manager Agent",
        department_id="dept_executive",
        description="Tactical orchestrator compiling high-level goals into executable DAG tasks and tracking SLAs.",
        system_prompt_template="prompts/roles/engagement_manager.jinja2",
        capabilities=["task_scheduling", "fsm_monitoring", "dependency_resolution"],
        allowed_tools=["task_scheduler"],
        approval_gates=[],
    ),
    # 2. Reconnaissance Department
    RoleCreateRequest(
        id="role_passive_osint",
        name="Passive OSINT Specialist",
        department_id="dept_recon",
        description="Gathers external intelligence without transmitting packets to target infrastructure.",
        system_prompt_template="prompts/roles/passive_osint.jinja2",
        capabilities=[
            "dns_enumeration",
            "whois_lookup",
            "certificate_transparency",
            "leaked_credential_search",
        ],
        allowed_tools=["subfinder", "amass", "dnsx", "whois", "crtsh"],
        approval_gates=[],
    ),
    RoleCreateRequest(
        id="role_active_network_recon",
        name="Active Network Recon Specialist",
        department_id="dept_recon",
        description="Probes allowlisted IP ranges for host discovery, port scanning, and OS fingerprinting.",
        system_prompt_template="prompts/roles/active_network_recon.jinja2",
        capabilities=["port_scanning", "service_enumeration", "banner_grabbing"],
        allowed_tools=["nmap", "masscan", "naabu"],
        approval_gates=["HIGH_RATE_FUZZING"],
    ),
    RoleCreateRequest(
        id="role_web_discovery",
        name="Web Asset Discovery Specialist",
        department_id="dept_recon",
        description="Maps web routes, crawls sitemaps, extracts JavaScript endpoints, and profiles CMS frameworks.",
        system_prompt_template="prompts/roles/web_discovery.jinja2",
        capabilities=["web_crawling", "endpoint_extraction", "tech_stack_fingerprinting"],
        allowed_tools=["httpx", "katana", "ffuf", "gau", "wappalyzer"],
        approval_gates=[],
    ),
    # 3. Vulnerability Department
    RoleCreateRequest(
        id="role_infra_vuln_assessor",
        name="Network & Infrastructure Vulnerability Specialist",
        department_id="dept_vulnerability",
        description="Assesses open services and software daemons against CVE/NVD vulnerability catalogs.",
        system_prompt_template="prompts/roles/infra_vuln_assessor.jinja2",
        capabilities=["cve_matching", "ssl_tls_auditing", "misconfiguration_detection"],
        allowed_tools=["nmap_vuln", "testssl", "snmpwalk"],
        approval_gates=[],
    ),
    RoleCreateRequest(
        id="role_web_vuln_assessor",
        name="Web Application Security Specialist",
        department_id="dept_vulnerability",
        description="Evaluates web endpoints against OWASP Top 10 with benign, non-destructive test probes.",
        system_prompt_template="prompts/roles/web_vuln_assessor.jinja2",
        capabilities=[
            "sqli_testing",
            "xss_testing",
            "ssrf_probing",
            "idor_analysis",
            "auth_bypass_check",
        ],
        allowed_tools=["nuclei", "httpx", "dalfox", "ffuf"],
        approval_gates=["ACTIVE_EXPLOITATION_PROBE"],
    ),
    RoleCreateRequest(
        id="role_cloud_container_assessor",
        name="Cloud & Container Security Specialist",
        department_id="dept_vulnerability",
        description="Audits cloud permissions, open buckets, container metadata, and IAM trust policies.",
        system_prompt_template="prompts/roles/cloud_container_assessor.jinja2",
        capabilities=[
            "iam_policy_analysis",
            "s3_bucket_check",
            "metadata_probing",
            "docker_k8s_audit",
        ],
        allowed_tools=["prowler", "scoutsuite", "trivy"],
        approval_gates=["CLOUD_RESOURCE_MODIFICATION"],
    ),
    # 4. Exploitation Department
    RoleCreateRequest(
        id="role_exploit_verifier",
        name="Exploitation Verification Specialist",
        department_id="dept_exploitation",
        description="Executes controlled, safe proof-of-concept probes to confirm exploitability under approval gates.",
        system_prompt_template="prompts/roles/exploit_verifier.jinja2",
        capabilities=["safe_poc_execution", "vulnerability_confirmation"],
        allowed_tools=["python_poc_runner", "curl_probe"],
        approval_gates=["ACTIVE_EXPLOITATION_PROBE"],
    ),
    RoleCreateRequest(
        id="role_privesc_credential_analyst",
        name="Credential & Privilege Escalation Specialist",
        department_id="dept_exploitation",
        description="Analyzes captured hashes, tokens, and permissions to model privilege escalation paths.",
        system_prompt_template="prompts/roles/privesc_credential_analyst.jinja2",
        capabilities=["hash_analysis", "sudo_privesc_check", "kerberoasting_analysis"],
        allowed_tools=["linpeas", "winpeas", "hashcat_bench"],
        approval_gates=["CREDENTIAL_REUSE_ATTEMPT"],
    ),
    RoleCreateRequest(
        id="role_adversary_emulator",
        name="Adversary Emulation / ATT&CK Specialist",
        department_id="dept_exploitation",
        description="Executes deterministic threat actor behavior playbooks mapped to MITRE ATT&CK techniques.",
        system_prompt_template="prompts/roles/adversary_emulator.jinja2",
        capabilities=["mitre_attack_mapping", "atomic_test_execution"],
        allowed_tools=["atomic_red_team", "ttp_runner"],
        approval_gates=["ACTIVE_EXPLOITATION_PROBE", "SUBNET_BOUNDARY_CROSSING"],
    ),
    # 5. Purple Team Department
    RoleCreateRequest(
        id="role_detection_analyst",
        name="Detection & Telemetry Analyst",
        department_id="dept_purple_telemetry",
        description="Correlates offensive operations with SIEM/EDR log events and computes Time-to-Detect (TTD).",
        system_prompt_template="prompts/roles/detection_analyst.jinja2",
        capabilities=["siem_querying", "edr_correlation", "detection_gap_analysis"],
        allowed_tools=["sigma_compiler", "elasticsearch_client"],
        approval_gates=[],
    ),
    RoleCreateRequest(
        id="role_remediation_advisor",
        name="Remediation & Hardening Advisor",
        department_id="dept_purple_telemetry",
        description="Generates actionable hardening snippets, patch priorities, and Sigma detection rules.",
        system_prompt_template="prompts/roles/remediation_advisor.jinja2",
        capabilities=["patch_prioritization", "config_hardening", "sigma_rule_generation"],
        allowed_tools=["remediation_builder"],
        approval_gates=[],
    ),
    # 6. Reporting Department
    RoleCreateRequest(
        id="role_technical_writer",
        name="Technical Report Writer Agent",
        department_id="dept_reporting",
        description="Compiles findings, reproduction steps, raw tool outputs, and CVSS scores into Markdown/PDF reports.",
        system_prompt_template="prompts/roles/technical_writer.jinja2",
        capabilities=["markdown_compilation", "cvss_calculation", "evidence_formatting"],
        allowed_tools=["pandoc", "report_engine"],
        approval_gates=[],
    ),
    RoleCreateRequest(
        id="role_executive_briefer",
        name="Executive Briefing Specialist",
        department_id="dept_reporting",
        description="Synthesizes business risk posture, compliance matrices, and high-level summaries for leadership.",
        system_prompt_template="prompts/roles/executive_briefer.jinja2",
        capabilities=[
            "business_impact_scoring",
            "executive_summary_generation",
            "compliance_mapping",
        ],
        allowed_tools=["executive_summary_builder"],
        approval_gates=[],
    ),
    # 7. Governance & Safety
    RoleCreateRequest(
        id="role_safety_sentinel",
        name="ROE Safety Sentinel Agent",
        department_id="dept_governance",
        description="Monitors task event streams against machine-readable ROE allowlists and triggers kill switches on anomaly.",
        system_prompt_template="prompts/roles/safety_sentinel.jinja2",
        capabilities=[
            "scope_auditing",
            "rate_limit_tracking",
            "anomaly_detection",
            "kill_switch_triggering",
        ],
        allowed_tools=["iptables_monitor", "process_auditor", "kill_api"],
        approval_gates=[],
    ),
]


async def seed_departments_and_roles(session_factory: Any) -> tuple[int, int]:
    """Idempotently seed all canonical departments and roles into the relational database."""
    dept_repo = DepartmentRepository(session_factory=session_factory)
    role_repo = RoleRepository(session_factory=session_factory)

    depts_seeded = 0
    for dept_req in SEED_DEPARTMENTS:
        await dept_repo.upsert(dept_req)
        depts_seeded += 1

    roles_seeded = 0
    for role_req in SEED_ROLES:
        await role_repo.upsert(role_req)
        roles_seeded += 1

    logger.info(
        "Seeded departments and specialist roles successfully",
        departments_count=depts_seeded,
        roles_count=roles_seeded,
    )
    return depts_seeded, roles_seeded
