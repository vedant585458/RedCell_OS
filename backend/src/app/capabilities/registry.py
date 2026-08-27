"""Pluggable, decoupled Capability Registry mapping capability names to metadata, tools, and execution specifications."""

import asyncio

from app.capabilities.base import CapabilityDefinition, RiskLevel
from app.core.logging import get_logger

logger = get_logger("capabilities.registry")


class CapabilityRegistry:
    """Thread-safe registry managing modular capabilities and tool requirements independently of role models."""

    def __init__(self) -> None:
        self._capabilities: dict[str, CapabilityDefinition] = {}
        self._lock = asyncio.Lock()
        self._register_canonical_capabilities()

    def register(self, capability: CapabilityDefinition) -> None:
        """Register a new or custom pluggable capability."""
        self._capabilities[capability.capability_id] = capability
        logger.debug(
            "Registered capability in registry",
            capability_id=capability.capability_id,
            risk_level=capability.risk_level,
            tools=capability.required_tools,
        )

    def get(self, capability_id: str) -> CapabilityDefinition | None:
        """Fetch capability definition by its unique ID."""
        return self._capabilities.get(capability_id)

    def has_capability(self, capability_id: str) -> bool:
        """Check if capability ID exists in the registry."""
        return capability_id in self._capabilities

    def list_capabilities(
        self,
        category: str | None = None,
        max_risk_level: RiskLevel | None = None,
    ) -> list[CapabilityDefinition]:
        """List registered capabilities, optionally filtered by category or max risk level."""
        results = list(self._capabilities.values())
        if category:
            results = [c for c in results if c.category == category]
        return results

    def validate_role_capabilities(self, capabilities: list[str]) -> tuple[bool, list[str]]:
        """Validate that all capabilities requested by a role are registered."""
        missing = [cap for cap in capabilities if cap not in self._capabilities]
        return len(missing) == 0, missing

    def get_required_tools_for_capabilities(self, capabilities: list[str]) -> list[str]:
        """Resolve the deduplicated set of tool binaries required across a list of capabilities."""
        tools: set[str] = set()
        for cap_id in capabilities:
            cap = self.get(cap_id)
            if cap:
                tools.update(cap.required_tools)
        return sorted(tools)

    def get_approval_gates_for_capabilities(self, capabilities: list[str]) -> list[str]:
        """Resolve all human approval gate categories triggered by a list of capabilities."""
        gates: set[str] = set()
        for cap_id in capabilities:
            cap = self.get(cap_id)
            if cap and cap.requires_approval_gate:
                gates.add(cap.requires_approval_gate)
        return sorted(gates)

    def _register_canonical_capabilities(self) -> None:
        """Pre-register all canonical capabilities defined in ROLE_TAXONOMY.md (M003)."""
        canonical_caps = [
            # 1. Executive & Scoping
            CapabilityDefinition(
                capability_id="scope_ingestion",
                name="Scope & ROE Ingestion",
                category="executive",
                risk_level=RiskLevel.PASSIVE,
            ),
            CapabilityDefinition(
                capability_id="mission_decomposition",
                name="Mission DAG Decomposition",
                category="executive",
                risk_level=RiskLevel.PASSIVE,
            ),
            CapabilityDefinition(
                capability_id="task_scheduling",
                name="Task Scheduling & Dependency Resolution",
                category="executive",
                risk_level=RiskLevel.PASSIVE,
            ),
            # 2. Reconnaissance & OSINT
            CapabilityDefinition(
                capability_id="dns_enumeration",
                name="DNS Subdomain Enumeration",
                category="recon",
                risk_level=RiskLevel.PASSIVE,
                required_tools=["subfinder", "dnsx"],
            ),
            CapabilityDefinition(
                capability_id="whois_lookup",
                name="WHOIS & Registry Intelligence",
                category="recon",
                risk_level=RiskLevel.PASSIVE,
                required_tools=["whois"],
            ),
            CapabilityDefinition(
                capability_id="port_scanning",
                name="Active TCP/UDP Port Probing",
                category="recon",
                risk_level=RiskLevel.LOW,
                required_tools=["nmap", "naabu"],
            ),
            CapabilityDefinition(
                capability_id="service_enumeration",
                name="Service Version Fingerprinting",
                category="recon",
                risk_level=RiskLevel.LOW,
                required_tools=["nmap"],
            ),
            CapabilityDefinition(
                capability_id="web_crawling",
                name="Web Route & Endpoint Extraction",
                category="recon",
                risk_level=RiskLevel.LOW,
                required_tools=["httpx", "katana", "ffuf"],
            ),
            # 3. Vulnerability Assessment
            CapabilityDefinition(
                capability_id="cve_matching",
                name="CVE & Known Vulnerability Matching",
                category="vulnerability",
                risk_level=RiskLevel.MEDIUM,
                required_tools=["nmap_vuln"],
            ),
            CapabilityDefinition(
                capability_id="owasp_top10_analysis",
                name="OWASP Top 10 Security Flaw Analysis",
                category="vulnerability",
                risk_level=RiskLevel.HIGH,
                requires_approval_gate="ACTIVE_EXPLOITATION_PROBE",
                required_tools=["nuclei", "dalfox"],
            ),
            CapabilityDefinition(
                capability_id="ssl_tls_auditing",
                name="SSL/TLS Cipher Suite & Certificate Audit",
                category="vulnerability",
                risk_level=RiskLevel.LOW,
                required_tools=["testssl"],
            ),
            CapabilityDefinition(
                capability_id="iam_policy_analysis",
                name="Cloud IAM & Container Privilege Audit",
                category="vulnerability",
                risk_level=RiskLevel.HIGH,
                requires_approval_gate="CLOUD_RESOURCE_MODIFICATION",
                required_tools=["prowler", "trivy"],
            ),
            # 4. Exploitation & Verification
            CapabilityDefinition(
                capability_id="safe_poc_execution",
                name="Safe Proof-of-Concept Exploit Verification",
                category="exploitation",
                risk_level=RiskLevel.CRITICAL,
                requires_approval_gate="ACTIVE_EXPLOITATION_PROBE",
                required_tools=["python_poc_runner", "curl_probe"],
            ),
            CapabilityDefinition(
                capability_id="sudo_privesc_check",
                name="Local Privilege Escalation Path Audit",
                category="exploitation",
                risk_level=RiskLevel.HIGH,
                requires_approval_gate="CREDENTIAL_REUSE_ATTEMPT",
                required_tools=["linpeas"],
            ),
            CapabilityDefinition(
                capability_id="mitre_attack_mapping",
                name="Adversary TTP Emulation (MITRE ATT&CK)",
                category="exploitation",
                risk_level=RiskLevel.CRITICAL,
                requires_approval_gate="ACTIVE_EXPLOITATION_PROBE",
                required_tools=["atomic_red_team"],
            ),
            # 5. Purple Team & Reporting
            CapabilityDefinition(
                capability_id="detection_gap_analysis",
                name="Defensive Telemetry & Time-to-Detect Scoring",
                category="telemetry",
                risk_level=RiskLevel.PASSIVE,
                required_tools=["sigma_compiler"],
            ),
            CapabilityDefinition(
                capability_id="markdown_compilation",
                name="Technical Report & CVSS Deliverable Generation",
                category="reporting",
                risk_level=RiskLevel.PASSIVE,
                required_tools=["pandoc"],
            ),
            CapabilityDefinition(
                capability_id="scope_auditing",
                name="Kernel Scope & Kill-Switch Governance",
                category="governance",
                risk_level=RiskLevel.PASSIVE,
                required_tools=["iptables_monitor", "kill_api"],
            ),
        ]

        for cap in canonical_caps:
            self.register(cap)


# Global singleton capability registry
global_capability_registry = CapabilityRegistry()
