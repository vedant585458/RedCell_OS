"""Application domain and orchestration services for RedCell_OS."""

from .intake import EngagementIntakeRequest, EngagementIntakeService
from .org_bootstrap import BootstrapResult, OrgBootstrapService
from .staffing import (
    DEFAULT_MAX_AGENTS_PER_DEPARTMENT,
    DepartmentCapacityStatus,
    DepartmentLoadState,
    DepartmentStaffingService,
    StaffingRecommendation,
)

__all__ = [
    "EngagementIntakeRequest",
    "EngagementIntakeService",
    "OrgBootstrapService",
    "BootstrapResult",
    "DepartmentStaffingService",
    "DepartmentCapacityStatus",
    "DepartmentLoadState",
    "StaffingRecommendation",
    "DEFAULT_MAX_AGENTS_PER_DEPARTMENT",
]
