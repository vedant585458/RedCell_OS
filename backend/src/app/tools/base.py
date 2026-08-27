"""Tool definition interfaces, parameter schemas, and security risk levels."""

import re
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from app.process.worker import ProcessResult

ArgsT = TypeVar("ArgsT", bound=BaseModel)
ResultT = TypeVar("ResultT", bound=BaseModel)


class ToolRiskLevel(StrEnum):
    """Operational risk classification for tool binaries."""

    BENIGN = "BENIGN"  # Safe read-only / offline operations (pandoc, whois)
    INTRUSIVE = "INTRUSIVE"  # Network probing & scanning (nmap, httpx, subfinder)
    EXPLOITATIVE = "EXPLOITATIVE"  # Active vulnerability verification (nuclei, dalfox)
    DANGEROUS = "DANGEROUS"  # Controlled PoC execution (python_poc_runner)


class ToolParameter(BaseModel):
    """Specification for a structured tool invocation argument."""

    name: str = Field(..., description="Parameter argument name")
    param_type: str = Field(default="string", description="string | integer | boolean | list")
    description: str = Field(default="")
    required: bool = Field(default=False)
    default: Any | None = Field(default=None)
    pattern: str | None = Field(
        default=None, description="Optional regex pattern to validate argument format"
    )

    def validate_value(self, value: Any) -> Any:
        """Validate argument value against type and regex patterns."""
        if value is None:
            if self.required:
                raise ValueError(f"Missing required parameter '{self.name}'")
            return self.default

        # Sanitize against shell injection attempts
        if isinstance(value, str):
            dangerous_chars = [";", "&&", "||", "|", "`", "$(", ">", "<", "\n"]
            for char in dangerous_chars:
                if char in value:
                    raise ValueError(
                        f"Security Error: Parameter '{self.name}' contains illegal shell metacharacter '{char}'."
                    )

            if self.pattern and not re.match(self.pattern, value):
                raise ValueError(
                    f"Parameter '{self.name}' value '{value}' does not match required regex pattern '{self.pattern}'."
                )

        return value


class ToolDefinition(BaseModel):
    """Metadata and secure argument translation contract for an authorized tool."""

    tool_id: str = Field(..., description="Unique tool identifier (e.g. nmap, httpx)")
    name: str = Field(..., description="Human-readable tool title")
    binary_name: str = Field(
        ..., description="Underlying executable binary or interpreter (e.g. nmap, python3)"
    )
    description: str = Field(default="")
    risk_level: ToolRiskLevel = Field(default=ToolRiskLevel.INTRUSIVE)
    required_capability: str = Field(..., description="Capability ID required to invoke this tool")
    parameters: list[ToolParameter] = Field(default_factory=list)
    default_timeout_sec: float = Field(default=120.0, ge=1.0, le=1800.0)
    requires_approval: bool = Field(default=False)
    approval_gate_category: str | None = Field(default=None)

    def build_argv(self, args: dict[str, Any]) -> list[str]:
        """Construct a secure tokenized argv list without shell=True execution."""
        validated_args: dict[str, Any] = {}
        for param in self.parameters:
            raw_val = args.get(param.name, param.default)
            validated_args[param.name] = param.validate_value(raw_val)

        argv = [self.binary_name]

        # Standard tool command construction mapping
        if self.tool_id == "nmap":
            target = validated_args.get("target", "127.0.0.1")
            ports = validated_args.get("ports", "80,443")
            scan_type = validated_args.get("scan_type", "-sV")
            argv.extend([scan_type, "-p", str(ports), str(target)])

        elif self.tool_id == "httpx":
            target_url = validated_args.get("target_url", "http://127.0.0.1:8088")
            path = validated_args.get("path", "/")
            full_url = (
                f"{target_url.rstrip('/')}/{path.lstrip('/')}"
                if path and path != "/"
                else target_url
            )
            argv.extend(["-u", full_url, "-status-code", "-title", "-silent"])

        elif self.tool_id == "subfinder":
            domain = validated_args.get("domain", "localhost")
            argv.extend(["-d", str(domain), "-silent"])

        elif self.tool_id == "nuclei":
            target_url = validated_args.get("target_url", "http://127.0.0.1:8088")
            template = validated_args.get("template", "cves")
            argv.extend(["-u", str(target_url), "-t", str(template), "-silent", "-json"])

        elif self.tool_id in ("curl_probe", "http_probe"):
            url = validated_args.get(
                "target_url", validated_args.get("url", "http://127.0.0.1:8088")
            )
            path = validated_args.get("path", "")
            if path and path != "/":
                url = f"{url.rstrip('/')}/{path.lstrip('/')}"
            method = validated_args.get("method", "GET")
            argv.extend(["-i", "-s", "-S", "-L", "-X", str(method), str(url)])

        elif self.tool_id == "python_poc_runner":
            script_path = validated_args.get("script_path", "poc.py")
            target = validated_args.get("target", "127.0.0.1")
            argv.extend([str(script_path), "--target", str(target)])

        elif self.tool_id == "pandoc":
            input_file = validated_args.get("input_file", "report.md")
            output_file = validated_args.get("output_file", "report.pdf")
            argv.extend([str(input_file), "-o", str(output_file)])

        else:
            for k, v in validated_args.items():
                if v is not None:
                    argv.extend([f"--{k}", str(v)])

        return argv


class ToolInterface(ABC, Generic[ArgsT, ResultT]):
    """Standardized tool interface implementing arg validation, argv construction, and output parsing (Technical Decision)."""

    tool_id: str
    name: str
    required_capability: str
    risk_level: ToolRiskLevel

    @abstractmethod
    def validate_args(self, raw_args: dict[str, Any]) -> ArgsT:
        """Validate raw arguments into typed Pydantic model."""
        pass

    @abstractmethod
    def build_argv(self, args: ArgsT) -> list[str]:
        """Construct secure CLI argv tokens."""
        pass

    @abstractmethod
    def parse_output(self, process_result: ProcessResult) -> ResultT:
        """Parse raw process execution output into structured result."""
        pass
