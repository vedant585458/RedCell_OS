"""Unit tests for the pluggable, decoupled CapabilityRegistry and tool requirement resolution."""

from app.capabilities.base import CapabilityDefinition, RiskLevel
from app.capabilities.registry import CapabilityRegistry


def test_canonical_capabilities_registered():
    registry = CapabilityRegistry()

    assert registry.has_capability("port_scanning") is True
    assert registry.has_capability("owasp_top10_analysis") is True
    assert registry.has_capability("safe_poc_execution") is True
    assert registry.has_capability("markdown_compilation") is True

    port_scan = registry.get("port_scanning")
    assert port_scan is not None
    assert port_scan.risk_level == RiskLevel.LOW
    assert "nmap" in port_scan.required_tools

    poc_exec = registry.get("safe_poc_execution")
    assert poc_exec is not None
    assert poc_exec.risk_level == RiskLevel.CRITICAL
    assert poc_exec.requires_approval_gate == "ACTIVE_EXPLOITATION_PROBE"


def test_pluggable_extensibility_custom_capability():
    registry = CapabilityRegistry()

    assert registry.has_capability("graphql_introspection") is False

    # Dynamically register a new capability
    custom_cap = CapabilityDefinition(
        capability_id="graphql_introspection",
        name="GraphQL Schema Introspection Probe",
        category="vulnerability",
        risk_level=RiskLevel.MEDIUM,
        requires_approval_gate=None,
        required_tools=["clairvoyance", "inql"],
    )

    registry.register(custom_cap)

    assert registry.has_capability("graphql_introspection") is True
    fetched = registry.get("graphql_introspection")
    assert fetched is not None
    assert fetched.name == "GraphQL Schema Introspection Probe"
    assert "clairvoyance" in fetched.required_tools


def test_role_capability_validation():
    registry = CapabilityRegistry()

    # Valid list
    valid, missing = registry.validate_role_capabilities(
        ["port_scanning", "web_crawling"]
    )
    assert valid is True
    assert missing == []

    # List with unknown capability
    valid2, missing2 = registry.validate_role_capabilities(
        ["port_scanning", "quantum_decryption_magic"]
    )
    assert valid2 is False
    assert "quantum_decryption_magic" in missing2


def test_tool_requirement_aggregation():
    registry = CapabilityRegistry()

    tools = registry.get_required_tools_for_capabilities(
        ["dns_enumeration", "port_scanning", "web_crawling"]
    )

    assert "subfinder" in tools
    assert "nmap" in tools
    assert "httpx" in tools
    assert "katana" in tools


def test_approval_gate_aggregation():
    registry = CapabilityRegistry()

    gates = registry.get_approval_gates_for_capabilities(
        ["safe_poc_execution", "iam_policy_analysis", "dns_enumeration"]
    )

    assert len(gates) == 2
    assert "ACTIVE_EXPLOITATION_PROBE" in gates
    assert "CLOUD_RESOURCE_MODIFICATION" in gates
