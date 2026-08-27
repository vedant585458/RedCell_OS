"""Health check endpoints for RedCell_OS control plane."""

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.config import settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Health check status payload."""

    status: str = Field(default="ok", description="Health status string")
    version: str = Field(description="Current application version")
    app_name: str = Field(description="Application name")
    timestamp_utc: str = Field(description="ISO 8601 UTC timestamp")
    environment: str = Field(description="Current running environment")


@router.get("/health", response_model=HealthResponse)
@router.get("/api/v1/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    """Return application health, version, and running environment."""
    return HealthResponse(
        status="ok",
        version=settings.version,
        app_name=settings.app_name,
        timestamp_utc=datetime.now(UTC).isoformat(),
        environment=settings.environment,
    )
