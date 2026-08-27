"""Workspace package managing per-agent-task directory isolation, permissions, and lifecycle."""

from .service import (
    PathTraversalError,
    WorkspaceInitializedEventPayload,
    WorkspaceService,
    global_workspace_service,
    sanitize_path_segment,
)

__all__ = [
    "WorkspaceService",
    "global_workspace_service",
    "PathTraversalError",
    "sanitize_path_segment",
    "WorkspaceInitializedEventPayload",
]
