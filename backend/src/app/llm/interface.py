"""Abstract AgentBrain interface protocol for provider-agnostic LLM reasoning."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TypeVar

from pydantic import BaseModel

from .models import BrainResponse, ChatMessage, StreamChunk

T = TypeVar("T", bound=BaseModel)


class AgentBrain(ABC):
    """Abstract provider-agnostic interface for agent reasoning."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        history: list[ChatMessage] | None = None,
        response_schema: type[T] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        timeout_sec: float = 45.0,
    ) -> BrainResponse:
        """Generate a complete text or structured response conforming to response_schema."""
        pass

    @abstractmethod
    def stream_generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        history: list[ChatMessage] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncIterator[StreamChunk]:
        """Stream response tokens in real-time for live frontend UI visualization."""
        pass
