"""Unit tests for the structured logging framework."""

import structlog
from app.core.logging import configure_logging, get_logger


def test_structured_logging_binding():
    configure_logging(json_format=True, log_level="DEBUG")
    logger = get_logger("test.observability")

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        engagement_id="eng-test-001",
        correlation_id="corr-test-001",
        agent_id="agent-recon-01",
    )

    logger.info("Executing probe", target="127.0.0.1", port=8088)

    context = structlog.contextvars.get_contextvars()
    assert context["engagement_id"] == "eng-test-001"
    assert context["correlation_id"] == "corr-test-001"
    assert context["agent_id"] == "agent-recon-01"
