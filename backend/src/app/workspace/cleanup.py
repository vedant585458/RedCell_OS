"""Workspace cleanup and retention policy service distinguishing deletable tmp scratchpads from immutable evidence artifacts."""

import os
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.domain.audit import AuditEventCreateRequest
from app.domain.workspace import WorkspaceStatus
from app.orchestrator.core import global_orchestrator
from app.repositories.unit_of_work import UnitOfWork

logger = get_logger("workspace.cleanup")


class WorkspaceRetentionPolicy(BaseModel):
    """Retention configuration governing temporary file purging and immutable evidence preservation."""

    tmp_retention_seconds: float = Field(
        default=0.0,
        ge=0.0,
        description="Age in seconds after which files in tmp/ scratchpads are eligible for deletion (0.0 = immediate)",
    )
    artifacts_retention_seconds: float = Field(
        default=86400.0 * 7,  # 7 days
        ge=0.0,
        description="Retention duration for non-evidence generated artifacts",
    )
    evidence_never_delete: bool = Field(
        default=True,
        description="Strict invariant: Evidence artifacts must never be auto-deleted",
    )


class WorkspaceDiskUsage(BaseModel):
    """Disk consumption breakdown across workspace subdirectories."""

    workspace_path: str
    tmp_bytes: int = 0
    artifacts_bytes: int = 0
    evidence_bytes: int = 0
    total_bytes: int = 0


class WorkspaceCleanupReport(BaseModel):
    """Structured report detailing deleted temporary files and preserved evidence."""

    workspace_id: str
    task_id: str
    engagement_id: str
    deleted_tmp_files_count: int
    freed_bytes: int
    preserved_evidence_files_count: int
    preserved_artifacts_files_count: int
    evidence_preserved: bool = True
    status: str
    cleaned_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class BatchCleanupReport(BaseModel):
    """Summary of batch retention cleanup execution across multiple workspaces."""

    total_workspaces_processed: int = 0
    total_tmp_files_deleted: int = 0
    total_freed_bytes: int = 0
    total_evidence_files_preserved: int = 0
    reports: list[WorkspaceCleanupReport] = Field(default_factory=list)
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


def get_dir_size_and_count(dir_path: str) -> tuple[int, int]:
    """Calculate total byte size and file count of a directory recursively."""
    total_size = 0
    file_count = 0
    if not os.path.exists(dir_path):
        return 0, 0

    for root, _, files in os.walk(dir_path):
        for f in files:
            fp = os.path.join(root, f)
            if not os.path.islink(fp) and os.path.exists(fp):
                total_size += os.path.getsize(fp)
                file_count += 1
    return total_size, file_count


class WorkspaceCleanupService:
    """Service executing selective workspace retention cleanup, ensuring evidence immutability."""

    def __init__(
        self,
        session_factory: Any,
        policy: WorkspaceRetentionPolicy | None = None,
        permissions_mode: int = 0o700,
    ) -> None:
        self.session_factory = session_factory
        self.policy = policy or WorkspaceRetentionPolicy()
        self.permissions_mode = permissions_mode

    def calculate_disk_usage(
        self, tmp_path: str, artifacts_path: str, evidence_path: str, root_path: str
    ) -> WorkspaceDiskUsage:
        """Compute disk usage breakdown across workspace subfolders."""
        tmp_bytes, _ = get_dir_size_and_count(tmp_path)
        art_bytes, _ = get_dir_size_and_count(artifacts_path)
        evi_bytes, _ = get_dir_size_and_count(evidence_path)
        return WorkspaceDiskUsage(
            workspace_path=root_path,
            tmp_bytes=tmp_bytes,
            artifacts_bytes=art_bytes,
            evidence_bytes=evi_bytes,
            total_bytes=tmp_bytes + art_bytes + evi_bytes,
        )

    async def clean_task_workspace(
        self,
        task_id: str,
        force_immediate_tmp: bool = True,
        correlation_id: str = "",
    ) -> WorkspaceCleanupReport:
        """Selectively delete files in the tmp/ scratchpad while strictly preserving all artifacts and evidence.

        Technical Decision: Evidence is never auto-deleted; only tmp files are subject to cleanup.
        """
        corr_id = correlation_id or f"corr-clean-{task_id}-{uuid.uuid4().hex[:8]}"

        async with UnitOfWork(self.session_factory) as uow:
            ws = await uow.workspaces.get_by_task_id(task_id)
            if not ws:
                raise ValueError(f"No workspace found for task '{task_id}'.")

            tmp_path = ws.tmp_path
            artifacts_path = ws.artifacts_path
            evidence_path = ws.evidence_path

            # 1. Negative Safety Invariant Assertions: Evidence path must never be tmp path
            if os.path.abspath(evidence_path) == os.path.abspath(tmp_path) or not evidence_path:
                raise RuntimeError(
                    "Security invariant failure: Evidence path matches temporary scratchpad path. Aborting cleanup."
                )

            # 2. Count evidence and artifact files BEFORE cleanup to guarantee preservation
            _, initial_evidence_count = get_dir_size_and_count(evidence_path)
            _, initial_artifacts_count = get_dir_size_and_count(artifacts_path)

            deleted_tmp_files = 0
            freed_bytes = 0
            now = time.time()

            # 3. Selective Deletion: Purge files in tmp/ respecting retention threshold
            if os.path.exists(tmp_path):
                for root, dirs, files in os.walk(tmp_path, topdown=False):
                    for file_name in files:
                        file_path = os.path.join(root, file_name)
                        try:
                            file_stat = os.stat(file_path)
                            file_age = now - file_stat.st_mtime
                            # Check retention threshold
                            if force_immediate_tmp or file_age >= self.policy.tmp_retention_seconds:
                                file_size = file_stat.st_size
                                os.remove(file_path)
                                deleted_tmp_files += 1
                                freed_bytes += file_size
                        except OSError as e:
                            logger.warning(f"Error removing tmp file '{file_path}': {e}")

                    # Remove empty subdirectories in tmp/
                    for d in dirs:
                        dir_to_remove = os.path.join(root, d)
                        try:
                            os.rmdir(dir_to_remove)
                        except OSError:
                            pass

                # Re-create sanitized empty tmp directory with exact permission bits
                os.makedirs(tmp_path, exist_ok=True)
                try:
                    os.chmod(tmp_path, self.permissions_mode)
                except OSError:
                    pass

            # 4. Invariant Assertion: Verify evidence files are 100% intact after cleanup
            _, post_evidence_count = get_dir_size_and_count(evidence_path)
            _, post_artifacts_count = get_dir_size_and_count(artifacts_path)

            if post_evidence_count < initial_evidence_count:
                raise RuntimeError(
                    f"CRITICAL SAFETY VIOLATION: Evidence count dropped from {initial_evidence_count} "
                    f"to {post_evidence_count} during cleanup of task '{task_id}'!"
                )

            # 5. Update workspace status in relational database to ARCHIVED
            await uow.workspaces.update_status(ws.id, WorkspaceStatus.ARCHIVED)

            report = WorkspaceCleanupReport(
                workspace_id=ws.id,
                task_id=task_id,
                engagement_id=ws.engagement_id,
                deleted_tmp_files_count=deleted_tmp_files,
                freed_bytes=freed_bytes,
                preserved_evidence_files_count=post_evidence_count,
                preserved_artifacts_files_count=post_artifacts_count,
                evidence_preserved=True,
                status=WorkspaceStatus.ARCHIVED.value,
            )

            # 6. Record immutable audit event
            await uow.audit.append_audit_event(
                AuditEventCreateRequest(
                    event_id=f"aud-clean-{ws.id[:8]}-{uuid.uuid4().hex[:6]}",
                    engagement_id=ws.engagement_id,
                    correlation_id=corr_id,
                    event_type="workspace_tmp_cleaned",
                    actor_type="SYSTEM",
                    actor_id="workspace_cleanup_service",
                    payload=report.model_dump(),
                )
            )
            await uow.commit()

        # 7. Broadcast cleanup event
        await global_orchestrator.emit_event(
            event_type="workspace_cleaned",
            correlation_id=corr_id,
            engagement_id=report.engagement_id,
            task_id=task_id,
            payload=report.model_dump(),
        )

        logger.info(
            f"Cleaned workspace '{report.workspace_id}' for task '{task_id}': "
            f"Deleted {deleted_tmp_files} tmp files ({freed_bytes} bytes freed), "
            f"Preserved {post_evidence_count} evidence files.",
            task_id=task_id,
            freed_bytes=freed_bytes,
            evidence_count=post_evidence_count,
        )

        return report

    async def run_batch_retention_cleanup(
        self,
        engagement_id: str | None = None,
        force_immediate_tmp: bool = False,
    ) -> BatchCleanupReport:
        """Run batch retention cleanup across all provisioned or completed workspaces."""
        batch_report = BatchCleanupReport()

        async with UnitOfWork(self.session_factory) as uow:
            if engagement_id:
                tasks = await uow.tasks.list_by_engagement(engagement_id)
            else:
                tasks = await uow.tasks.list_tasks(limit=500)

        for t in tasks:
            try:
                report = await self.clean_task_workspace(
                    task_id=t.task_id,
                    force_immediate_tmp=force_immediate_tmp,
                )
                batch_report.total_workspaces_processed += 1
                batch_report.total_tmp_files_deleted += report.deleted_tmp_files_count
                batch_report.total_freed_bytes += report.freed_bytes
                batch_report.total_evidence_files_preserved += report.preserved_evidence_files_count
                batch_report.reports.append(report)
            except ValueError:
                # No workspace provisioned for this task
                continue
            except Exception as e:
                logger.error(f"Error during batch cleanup for task '{t.task_id}': {e}")

        return batch_report


# Global singleton instance of WorkspaceCleanupService
global_workspace_cleanup_service = WorkspaceCleanupService(None)
