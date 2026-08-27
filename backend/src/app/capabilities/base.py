"""Base capability interfaces, definitions, and risk levels."""

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RiskLevel(StrEnum):
    """Operational risk level of an offensive/defensive capability."""

    PASSIVE = "PASSIVE"  # 1: No packets sent to target (OSINT, DNS, WHOIS)
    LOW = "LOW"  # 2: Benign network probing / port discovery
    MEDIUM = "MEDIUM"  # 3: Active service auditing / version banner grabbing
    HIGH = "HIGH"  # 4: Vulnerability scanning / PoC verification (Gate candidate)
    CRITICAL = "CRITICAL"  # 5: Active exploit validation / credential testing (Mandatory Gate)


CapabilityHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class CapabilityDefinition(BaseModel):
    """Metadata and execution specification for a modular agent capability."""

    capability_id: str = Field(..., description="Unique capability identifier (e.g. port_scanning)")
    name: str = Field(..., description="Human-readable title")
    description: str = Field(default="")
    category: str = Field(
        default="recon",
        description="Functional category: recon | vulnerability | exploitation | telemetry | reporting | governance",
    )
    risk_level: RiskLevel = Field(default=RiskLevel.LOW)
    requires_approval_gate: str | None = Field(
        default=None,
        description="Approval gate category if this capability requires human operator sign-off",
    )
    required_tools: list[str] = Field(
        default_factory=list,
        description="Allowlisted tool binaries or adapters required to execute this capability",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
