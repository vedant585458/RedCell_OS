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
        """Generate a complete text or structured response conforming to response_schema.

        Args:
            prompt: User/operator prompt or task instruction.
            system_prompt: Persona or role system prompt.
            history: Optional list of previous chat messages.
            response_schema: Optional Pydantic model class to constrain and parse output.
            temperature: Sampling temperature (0.0 - 1.0).
            max_tokens: Maximum completion tokens.
            timeout_sec: Maximum time allowed before raising TimeoutError.

        Returns:
            BrainResponse containing text, parsed structured_data, and usage stats.
        """
        pass

    @abstractmethod
    async def stream_generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        history: list[ChatMessage] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncIterator[StreamChunk]:
        """Stream response tokens in real-time for live frontend UI visualization.

        Args:
            prompt: User/operator prompt or task instruction.
            system_prompt: Persona or role system prompt.
            history: Optional list of previous chat messages.
            temperature: Sampling temperature.
            max_tokens: Maximum completion tokens.

        Yields:
            StreamChunk instances with token deltas.
        """
        pass
