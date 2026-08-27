"""API router package for RedCell_OS."""

from .departments import router as departments_router
from .engagements import router as engagements_router
from .events import router as events_router
from .health import router as health_router
from .organization import router as organization_router
from .processes import router as processes_router
from .ws import ConnectionManager, ws_manager
from .ws import router as ws_router

__all__ = [
    "health_router",
    "processes_router",
    "ws_router",
    "events_router",
    "organization_router",
    "engagements_router",
    "departments_router",
    "ws_manager",
    "ConnectionManager",
]
