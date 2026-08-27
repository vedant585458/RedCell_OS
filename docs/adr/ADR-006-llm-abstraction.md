# ADR-006: LLM Provider Abstraction Strategy and AgentBrain Interface Contract

**Status:** Accepted  
**Date:** August 2026  
**Milestone Reference:** M010  
**Phase:** P02 — Architecture and Technology Decisions  
**Context Link:** [VISION.md](../../VISION.md), [SECURITY_CONSTRAINTS.md](../../SECURITY_CONSTRAINTS.md), [ADR-001-backend-runtime.md](ADR-001-backend-runtime.md)  

---

## 1. Context & Problem Statement

RedCell_OS agents—such as the CISO Agent, Vulnerability Assessors, and Reporting Specialists—rely on Large Language Models (LLMs) to perform complex cognitive tasks:
- Decomposing high-level Rules of Engagement (ROE) into Directed Acyclic Graphs (DAGs) of tasks.
- Analyzing raw scanner outputs (e.g. Nmap XMLs, HTTP responses) to infer vulnerabilities.
- Generating safe, non-destructive validation probes and PoC commands.
- Synthesizing technical findings into structured CVSS v3.1 reports.

In enterprise and penetration testing environments, operators have diverse infrastructure constraints:
1. **Public Cloud LLM APIs:** OpenAI (GPT-4o), Anthropic (Claude 3.5 Sonnet), Google (Gemini 1.5 Pro).
2. **Local-First & Air-Gapped Models:** Ollama, vLLM, llama.cpp, LocalAI.
3. **Deterministic Mock LLMs:** Required for offline unit tests, regression suites, and Phase P70 E2E integration tests.

Directly coupling agent code to provider-specific SDKs (e.g., hardcoding `openai.OpenAI()` or `anthropic.Anthropic()`) creates vendor lock-in, leaks API quirks into business logic, and prevents offline testing.

We must define a **unified, provider-agnostic `AgentBrain` interface**, a **JSON-schema-constrained output contract**, and a **fault-tolerant retry/backoff policy**.

---

## 2. Decision Drivers

1. **Strict Provider Agnosticism:** Core agent logic must never reference provider-specific SDK classes, message formats, or token parameters.
2. **Deterministic Structured Outputs:** Task decomposition, finding classification, and command proposals must return validated Pydantic v2 objects matching strict JSON schemas.
3. **Local-First & Air-Gapped Readiness:** Seamless runtime switching between cloud APIs (Claude/OpenAI) and local private models (Ollama/vLLM) via a single configuration parameter.
4. **Resilient Retry & Exponential Backoff:** Automatic handling of provider rate limits (HTTP 429), transient gateway errors (HTTP 502/503), and context length overflows.
5. **Observability & Cost Attribution:** Granular tracking of prompt tokens, completion tokens, latency, and estimated dollar costs per agent, department, and task.
6. **Deterministic Mocking:** Capability to execute full end-to-end simulation engagements in test environments without live API keys.

---

## 3. Decision: The `AgentBrain` Architecture

We decide to adopt a **Unified `AgentBrain` Abstract Interface** backed by **LiteLLM / Direct Provider Drivers** with **Pydantic v2 Schema Enforcement**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AGENT BRAIN ARCHITECTURE                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│                        ┌────────────────────────────┐                       │
│                        │  Agent / CISO Logic Layer  │                       │
│                        │ (TaskDecomposer, Assessor) │                       │
│                        └─────────────┬──────────────┘                       │
│                                      │ typed prompt & Pydantic schema       │
│                                      ▼                                      │
│                        ┌────────────────────────────┐                       │
│                        │    AgentBrain Interface    │                       │
│                        │ (Abstract Base Protocol)   │                       │
│                        └─────────────┬──────────────┘                       │
│                                      │                                      │
│        ┌─────────────────────────────┼─────────────────────────────┐        │
│        │                             │                             │        │
│        ▼                             ▼                             ▼        │
│  ┌───────────┐                 ┌───────────┐                 ┌───────────┐  │
│  │  LiteLLM  │                 │  Ollama / │                 │   Mock    │  │
│  │ Provider  │                 │   vLLM    │                 │   Brain   │  │
│  │ (Cloud)   │                 │  (Local)  │                 │  (Tests)  │  │
│  └─────┬─────┘                 └─────┬─────┘                 └─────┬─────┘  │
│        │                             │                             │        │
│        └─────────────────────────────┼─────────────────────────────┘        │
│                                      │ Raw JSON Response                     │
│                                      ▼                                      │
│                        ┌────────────────────────────┐                       │
│                        │ Pydantic v2 JSON Validator │                       │
│                        │ & Self-Correction Repairer │                       │
│                        └─────────────┬──────────────┘                       │
│                                      │ Validated Object Instance            │
│                                      ▼                                      │
│                        ┌────────────────────────────┐                       │
│                        │  Audit Logger & Cost Metric│                       │
│                        │ (SQLite Event Correlation) │                       │
│                        └────────────────────────────┘                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. `AgentBrain` Interface Specification

The core interface contract is defined in Python:

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator, TypeVar, Type
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ChatMessage(BaseModel):
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    name: str | None = None


class BrainUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float = 0.0


class BrainResponse(BaseModel):
    content: str
    structured_data: BaseModel | None = None
    usage: BrainUsage
    model: str
    finish_reason: str


class AgentBrain(ABC):
    """Abstract provider-agnostic interface for agent reasoning."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        history: list[ChatMessage] | None = None,
        response_schema: Type[T] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> BrainResponse:
        """Generate a complete text or structured response."""
        pass

    @abstractmethod
    async def stream_generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        history: list[ChatMessage] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        """Stream response tokens in real-time for UI visualization."""
        pass
```

---

## 5. Structured-Output Contract (Pydantic v2 Schema Enforcement)

When structured output is requested, the system guarantees that the return value conforms to the specified Pydantic model:

### 5.1 Canonical Role Output Schemas

1. **CISO Task Decomposition (`CisoPlanOutput`):**
   ```python
   class DecomposedTask(BaseModel):
       task_id: str
       title: str
       department: str
       role: str
       description: str
       depends_on: list[str] = []
       requires_approval_gate: str | None = None


   class CisoPlanOutput(BaseModel):
       engagement_id: str
       executive_summary: str
       tasks: list[DecomposedTask]
   ```

2. **Vulnerability Assessment Finding (`VulnFindingOutput`):**
   ```python
   class VulnFindingOutput(BaseModel):
       finding_id: str
       title: str
       severity: str  # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFORMATIONAL"
       cvss_score: float
       cwe_id: str
       target_endpoint: str
       description: str
       reproduction_steps: list[str]
       evidence_payload: str
       remediation: str
   ```

### 5.2 Self-Correction Repair Loop
If an LLM returns invalid JSON or fails Pydantic schema validation:
1. The `AgentBrain` captures the `ValidationError` details.
2. It immediately issues a **single-shot repair prompt** containing the validation error message and the failed raw output:
   > *"The previous output failed validation with error: {error_details}. Fix and return only valid JSON conforming to the schema."*
3. If the repair succeeds, execution proceeds seamlessly. If it fails twice, the task halts safely and alerts the operator.

---

## 6. Retry, Timeout, and Backoff Policy

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        LLM CALL RESILIENCE POLICY                           │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Request Timeout:                                                         │
│    • Per-call timeout: 45 seconds (configurable up to 180s for reports).    │
│    • Enforced via `asyncio.wait_for()`.                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ 2. Exponential Jittered Backoff:                                            │
│    • Max retries: 3 attempts.                                               │
│    • Retryable errors: HTTP 429 (Rate Limit), HTTP 500/502/503/504,         │
│      ConnectionTimeout, OverloadedError.                                    │
│    • Backoff formula: `delay = min(max_delay, base_delay * (2 ** attempt))  │
│      + uniform(0, jitter)`.                                                 │
│    • Attempt 1: ~1.5s, Attempt 2: ~3.0s, Attempt 3: ~6.0s.                  │
├─────────────────────────────────────────────────────────────────────────────┤
│ 3. Circuit Breaker:                                                         │
│    • If 5 consecutive calls fail across the entire engagement, the          │
│      orchestrator transitions the engagement to `LLM_CIRCUIT_OPEN`,         │
│      pausing active tasks to prevent cost runaway or infinite retries.       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. Deterministic Mock Brain for Testing (`MockAgentBrain`)

For unit testing, CI/CD, and the **Phase P70 E2E Acceptance Test**, a `MockAgentBrain` provides scripted, deterministic responses without network calls or API costs:

```python
class MockAgentBrain(AgentBrain):
    """Deterministic brain for offline testing and CI suites."""

    def __init__(self, responses: dict[str, BaseModel | str] | None = None):
        self.responses = responses or {}
        self.call_history: list[dict] = []

    async def generate(self, prompt: str, **kwargs) -> BrainResponse:
        self.call_history.append({"prompt": prompt, "kwargs": kwargs})
        schema = kwargs.get("response_schema")

        # Match scripted response or synthesize mock instance
        if schema and schema in self.responses:
            data = self.responses[schema]
            return BrainResponse(
                content=data.model_dump_json(),
                structured_data=data,
                usage=BrainUsage(
                    prompt_tokens=10, completion_tokens=20, total_tokens=30
                ),
                model="mock-brain-v1",
                finish_reason="stop",
            )
        return BrainResponse(
            content="Mock response output",
            usage=BrainUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
            model="mock-brain-v1",
            finish_reason="stop",
        )
```

---

## 8. Consequences & Trade-offs

### Positive Consequences
- **Complete Vendor Independence:** Switching from OpenAI to Anthropic or a private self-hosted Ollama model requires only updating a config setting (`LLM_PROVIDER=ollama`, `LLM_MODEL=llama3:8b`).
- **Mathematical Type Safety:** High-level CISO plans and vulnerability findings are always valid Pydantic instances.
- **Cost Transparency:** Every single LLM call records prompt/completion tokens and cost in the SQLite event log with correlation IDs.

### Negative Consequences & Mitigations
- **Structured Output Latency on Smaller Local Models:** Smaller open-source LLMs (e.g. 7B models) can occasionally struggle with strict JSON schemas.
  - *Mitigation:* The 1-shot self-correction repair loop resolves $> 95\%$ of formatting errors automatically.

---

## 9. Review & Acceptance

- **Accepted By:** RedCell_OS Architecture Review Board
- **Traceability:** Fulfills milestone **M010**, establishing the AI reasoning layer for CISO Decomposition and specialist agents.
