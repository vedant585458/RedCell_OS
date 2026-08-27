"""Pydantic data models and schemas for LLM provider abstraction."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """Standardized chat message structure across all LLM providers."""

    role: Literal["system", "user", "assistant", "tool"] = Field(
        ..., description="Message author role"
    )
    content: str = Field(..., description="Message text content")
    name: str | None = Field(default=None, description="Optional author or tool name")


class BrainUsage(BaseModel):
    """Token consumption and cost tracking metadata."""

    prompt_tokens: int = Field(default=0, description="Tokens consumed in prompt")
    completion_tokens: int = Field(default=0, description="Tokens generated in output")
    total_tokens: int = Field(default=0, description="Total tokens consumed")
    estimated_cost_usd: float = Field(default=0.0, description="Estimated monetary cost in USD")


class BrainResponse(BaseModel):
    """Standardized response container returned by all AgentBrain implementations."""

    content: str = Field(..., description="Raw text response content")
    structured_data: Any | None = Field(
        default=None, description="Parsed Pydantic model instance if schema requested"
    )
    usage: BrainUsage = Field(default_factory=BrainUsage, description="Usage and token metadata")
    model: str = Field(..., description="Actual model name used for generation")
    finish_reason: str = Field(
        default="stop", description="Reason generation finished (e.g., stop, length)"
    )


class StreamChunk(BaseModel):
    """Token chunk emitted during streaming generation."""

    delta: str = Field(..., description="Incremental token text delta")
    is_finished: bool = Field(default=False, description="Whether stream has completed")
    finish_reason: str | None = Field(default=None, description="Completion reason if finished")
