"""Permissions package enforcing deny-by-default role permission boundaries."""

from .checker import CANONICAL_ROLE_PERMISSIONS, PermissionChecker
from .models import (
    PermissionCheckRequest,
    PermissionEvaluationResult,
    RolePermissionsSchema,
)

__all__ = [
    "PermissionChecker",
    "PermissionCheckRequest",
    "PermissionEvaluationResult",
    "RolePermissionsSchema",
    "CANONICAL_ROLE_PERMISSIONS",
]
