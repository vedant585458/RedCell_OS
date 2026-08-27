"""Tool Registry and Role-Tool Binding Mediator enforcing security controls over all CLI tool invocations."""

import asyncio
from typing import Any

from app.core.logging import get_logger
from app.tools.base import ToolDefinition, ToolParameter, ToolRiskLevel

logger = get_logger("tools.registry")


class UnauthorizedToolInvocationError(PermissionError):
    """Raised when an agent attempts to execute an unregistered or forbidden tool."""

    pass


class ToolRegistry:
    """Central authorized tool registry mediating all tool argv builds and role-to-tool permissions."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._lock = asyncio.Lock()
        self._register_canonical_tools()

    def register(self, tool: ToolDefinition) -> None:
        """Register an authorized tool definition in the registry."""
        self._tools[tool.tool_id] = tool
        logger.debug(
            "Registered tool in registry",
            tool_id=tool.tool_id,
            binary=tool.binary_name,
            risk_level=tool.risk_level,
        )

    def get(self, tool_id: str) -> ToolDefinition | None:
        """Get tool definition by ID."""
        return self._tools.get(tool_id)

    def has_tool(self, tool_id: str) -> bool:
        """Check if tool is registered."""
        return tool_id in self._tools

    def list_tools(self) -> list[ToolDefinition]:
        """List all authorized tools in the registry."""
        return list(self._tools.values())

    def resolve_tools_for_role(
        self,
        role_id: str,
        role_capabilities: list[str],
        allowed_tools: list[str],
    ) -> list[ToolDefinition]:
        """Resolve the set of authorized tools accessible to a specialist role based on capability and allowlist intersection."""
        resolved: list[ToolDefinition] = []
        allowed_set = set(allowed_tools)
        cap_set = set(role_capabilities)

        for tool in self._tools.values():
            # Tool must be explicitly in role's allowed_tools AND role must possess the required capability
            if tool.tool_id in allowed_set or tool.required_capability in cap_set:
                resolved.append(tool)

        return resolved

    def build_command(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        allowed_tool_ids: list[str] | None = None,
    ) -> list[str]:
        """Validate and construct tokenized argv list for an authorized tool invocation.

        SECURITY GUARANTEE:
        - Rejects unregistered tools.
        - Rejects tools outside the caller's allowed list.
        - Sanitizes all arguments against shell injection metacharacters.
        """
        tool = self.get(tool_id)
        if not tool:
            raise UnauthorizedToolInvocationError(
                f"Security Violation: Tool '{tool_id}' is not registered in the RedCell_OS tool registry."
            )

        if allowed_tool_ids is not None and tool_id not in allowed_tool_ids:
            raise UnauthorizedToolInvocationError(
                f"Permission Denied: Agent role is not authorized to invoke tool '{tool_id}'. "
                f"Allowed tools for this role: {allowed_tool_ids}"
            )

        return tool.build_argv(arguments)

    def _register_canonical_tools(self) -> None:
        """Pre-register all canonical security and simulation tools."""
        canonical_tools = [
            # 1. Nmap Network Scanner
            ToolDefinition(
                tool_id="nmap",
                name="Nmap Network & Port Scanner",
                binary_name="nmap",
                description="Port discovery and service fingerprinting",
                risk_level=ToolRiskLevel.INTRUSIVE,
                required_capability="port_scanning",
                default_timeout_sec=180.0,
                parameters=[
                    ToolParameter(
                        name="target",
                        param_type="string",
                        required=True,
                        description="Target IP or CIDR",
                    ),
                    ToolParameter(
                        name="ports",
                        param_type="string",
                        default="80,443,8088",
                        description="Target ports",
                    ),
                    ToolParameter(name="scan_type", param_type="string", default="-sV"),
                ],
            ),
            # 2. HTTPx Web Prober
            ToolDefinition(
                tool_id="httpx",
                name="HTTPx Web Route Prober",
                binary_name="httpx",
                description="Fast HTTP status and endpoint probing",
                risk_level=ToolRiskLevel.INTRUSIVE,
                required_capability="web_crawling",
                default_timeout_sec=60.0,
                parameters=[
                    ToolParameter(name="target_url", param_type="string", required=True),
                    ToolParameter(name="path", param_type="string", default="/"),
                ],
            ),
            # 3. Subfinder OSINT
            ToolDefinition(
                tool_id="subfinder",
                name="Subfinder Subdomain Discovery",
                binary_name="subfinder",
                description="Passive DNS enumeration",
                risk_level=ToolRiskLevel.BENIGN,
                required_capability="dns_enumeration",
                default_timeout_sec=120.0,
                parameters=[
                    ToolParameter(name="domain", param_type="string", required=True),
                ],
            ),
            # 4. Nuclei Vulnerability Scanner
            ToolDefinition(
                tool_id="nuclei",
                name="Nuclei Template Vulnerability Scanner",
                binary_name="nuclei",
                description="Template-based vulnerability assessment",
                risk_level=ToolRiskLevel.EXPLOITATIVE,
                required_capability="owasp_top10_analysis",
                requires_approval=True,
                approval_gate_category="ACTIVE_EXPLOITATION_PROBE",
                default_timeout_sec=300.0,
                parameters=[
                    ToolParameter(name="target_url", param_type="string", required=True),
                    ToolParameter(name="template", param_type="string", default="cves"),
                ],
            ),
            # 5. Safe Curl Probe
            ToolDefinition(
                tool_id="curl_probe",
                name="Safe Non-Destructive HTTP Probe",
                binary_name="curl",
                description="Direct HTTP REST request prober",
                risk_level=ToolRiskLevel.INTRUSIVE,
                required_capability="web_crawling",
                default_timeout_sec=30.0,
                parameters=[
                    ToolParameter(name="url", param_type="string", required=True),
                    ToolParameter(name="method", param_type="string", default="GET"),
                ],
            ),
            # 6. Sandboxed Python PoC Runner
            ToolDefinition(
                tool_id="python_poc_runner",
                name="Sandboxed Python PoC Exploit Verifier",
                binary_name="python3",
                description="Executes verified benign PoC scripts",
                risk_level=ToolRiskLevel.DANGEROUS,
                required_capability="safe_poc_execution",
                requires_approval=True,
                approval_gate_category="ACTIVE_EXPLOITATION_PROBE",
                default_timeout_sec=60.0,
                parameters=[
                    ToolParameter(name="script_path", param_type="string", required=True),
                    ToolParameter(name="target", param_type="string", required=True),
                ],
            ),
            # 7. Pandoc Report Generator
            ToolDefinition(
                tool_id="pandoc",
                name="Pandoc Document & Report Compiler",
                binary_name="pandoc",
                description="Compiles Markdown into PDF and HTML reports",
                risk_level=ToolRiskLevel.BENIGN,
                required_capability="markdown_compilation",
                default_timeout_sec=60.0,
                parameters=[
                    ToolParameter(name="input_file", param_type="string", required=True),
                    ToolParameter(name="output_file", param_type="string", default="report.pdf"),
                ],
            ),
        ]

        for tool in canonical_tools:
            self.register(tool)


# Global singleton tool registry
global_tool_registry = ToolRegistry()
