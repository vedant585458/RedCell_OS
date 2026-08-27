"""Unit tests for the AgentBrain interface and MockAgentBrain."""

import pytest
from app.llm import BrainResponse, MockAgentBrain, StreamChunk
from pydantic import BaseModel


class SampleTaskDecomposition(BaseModel):
    plan_id: str
    target_count: int


@pytest.mark.asyncio
async def test_mock_brain_text_generation():
    brain = MockAgentBrain()
    response = await brain.generate(
        prompt="Explain SQL injection",
        system_prompt="You are a security tutor.",
    )
    assert isinstance(response, BrainResponse)
    assert response.content == "Mock Agent Brain deterministic text response."
    assert response.usage.total_tokens == 25
    assert len(brain.call_history) == 1


@pytest.mark.asyncio
async def test_mock_brain_structured_generation():
    expected_data = SampleTaskDecomposition(plan_id="plan-001", target_count=3)
    brain = MockAgentBrain(scripted_responses={SampleTaskDecomposition: expected_data})

    response = await brain.generate(
        prompt="Decompose engagement scope",
        response_schema=SampleTaskDecomposition,
    )
    assert response.structured_data is not None
    assert response.structured_data.plan_id == "plan-001"
    assert response.structured_data.target_count == 3


@pytest.mark.asyncio
async def test_mock_brain_streaming():
    brain = MockAgentBrain()
    chunks: list[StreamChunk] = []
    async for chunk in brain.stream_generate(prompt="Stream sample"):
        chunks.append(chunk)

    assert len(chunks) > 0
    assert chunks[-1].is_finished is True
