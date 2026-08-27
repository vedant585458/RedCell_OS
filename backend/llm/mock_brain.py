"""Deterministic MockAgentBrain implementation for offline testing and CI suites."""

import asyncio
from typing import Any, AsyncIterator, Type, TypeVar
from pydantic import BaseModel

from .interface import AgentBrain
from .models import BrainResponse, BrainUsage, ChatMessage, StreamChunk

T = TypeVar("T", bound=BaseModel)


class MockAgentBrain(AgentBrain):
    """Deterministic, offline AgentBrain for testing, CI/CD, and E2E validation."""

    def __init__(self, scripted_responses: dict[Any, Any] | None = None):
        """Initialize mock brain with optional pre-scripted schema responses."""
        self.scripted_responses = scripted_responses or {}
        self.call_history: list[dict[str, Any]] = []

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        history: list[ChatMessage] | None = None,
        response_schema: Type[T] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        timeout_sec: float = 45.0,
    ) -> BrainResponse:
        """Return scripted or deterministic mock response."""
        call_record = {
            "prompt": prompt,
            "system_prompt": system_prompt,
            "history": history,
            "response_schema": response_schema,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        self.call_history.append(call_record)

        if response_schema and response_schema in self.scripted_responses:
            mock_data = self.scripted_responses[response_schema]
            if isinstance(mock_data, BaseModel):
                return BrainResponse(
                    content=mock_data.model_dump_json(),
                    structured_data=mock_data,
                    usage=BrainUsage(prompt_tokens=20, completion_tokens=40, total_tokens=60, estimated_cost_usd=0.0),
                    model="mock-deterministic-v1",
                    finish_reason="stop",
                )

        content = "Mock Agent Brain deterministic text response."
        return BrainResponse(
            content=content,
            structured_data=None,
            usage=BrainUsage(prompt_tokens=10, completion_tokens=15, total_tokens=25, estimated_cost_usd=0.0),
            model="mock-deterministic-v1",
            finish_reason="stop",
        )

    async def stream_generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        history: list[ChatMessage] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncIterator[StreamChunk]:
        """Stream sample words for mock visualization."""
        words = ["Analyzing", " target", " scope", " and", " generating", " plan..."]
        for i, word in enumerate(words):
            await asyncio.sleep(0.01)
            is_last = i == len(words) - 1
            yield StreamChunk(
                delta=word,
                is_finished=is_last,
                finish_reason="stop" if is_last else None,
            )
