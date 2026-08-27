"""In-memory thread-safe Process Registry for active subprocess tracking and kill-switch dispatch."""

import asyncio
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.process.worker import WorkerProcess

logger = get_logger("process.registry")


class ProcessRecord(BaseModel):
    """Metadata record for a supervised active subprocess."""

    process_id: str = Field(default_factory=lambda: f"proc-{uuid.uuid4().hex[:12]}")
    pid: int = Field(description="OS process ID")
    pgid: int | None = Field(default=None, description="OS process group ID")
    agent_id: str = Field(description="ID of the owner agent")
    department_id: str | None = Field(default=None, description="Department context")
    task_id: str | None = Field(default=None, description="Task context")
    engagement_id: str | None = Field(default=None, description="Engagement scope context")
    command: list[str] = Field(description="Command line arguments executed")
    workspace_path: str = Field(description="Working directory for the process")
    started_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    status: str = Field(
        default="RUNNING", description="Process state: RUNNING | COMPLETED | KILLED | TIMED_OUT"
    )


class ProcessRegistry:
    """Async thread-safe registry tracking active worker subprocesses with multi-level kill capabilities."""

    def __init__(self) -> None:
        self._processes: dict[str, ProcessRecord] = {}
        self._workers: dict[str, WorkerProcess] = {}
        self._agent_index: dict[str, set[str]] = {}
        self._engagement_index: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        worker: WorkerProcess,
        agent_id: str,
        command: list[str],
        workspace_path: str,
        engagement_id: str | None = None,
        task_id: str | None = None,
        department_id: str | None = None,
    ) -> ProcessRecord:
        """Register a freshly spawned worker subprocess into the active registry."""
        if worker.pid is None:
            raise ValueError("Cannot register a worker process without an active PID")

        async with self._lock:
            record = ProcessRecord(
                pid=worker.pid,
                pgid=worker.pgid,
                agent_id=agent_id,
                department_id=department_id,
                task_id=task_id,
                engagement_id=engagement_id,
                command=command,
                workspace_path=workspace_path,
                status="RUNNING",
            )

            proc_id = record.process_id
            self._processes[proc_id] = record
            self._workers[proc_id] = worker

            # Update indexing sets
            if agent_id not in self._agent_index:
                self._agent_index[agent_id] = set()
            self._agent_index[agent_id].add(proc_id)

            if engagement_id:
                if engagement_id not in self._engagement_index:
                    self._engagement_index[engagement_id] = set()
                self._engagement_index[engagement_id].add(proc_id)

            logger.debug(
                "Registered process in registry",
                process_id=proc_id,
                pid=worker.pid,
                agent_id=agent_id,
                engagement_id=engagement_id,
            )

            return record

    async def unregister(self, process_id: str, status: str = "COMPLETED") -> ProcessRecord | None:
        """Unregister a finished or terminated process from the active registry."""
        async with self._lock:
            record = self._processes.get(process_id)
            if not record:
                return None

            record.status = status
            del self._processes[process_id]
            self._workers.pop(process_id, None)

            # Cleanup agent index
            if record.agent_id in self._agent_index:
                self._agent_index[record.agent_id].discard(process_id)
                if not self._agent_index[record.agent_id]:
                    del self._agent_index[record.agent_id]

            # Cleanup engagement index
            if record.engagement_id and record.engagement_id in self._engagement_index:
                self._engagement_index[record.engagement_id].discard(process_id)
                if not self._engagement_index[record.engagement_id]:
                    del self._engagement_index[record.engagement_id]

            logger.debug(
                "Unregistered process from registry",
                process_id=process_id,
                status=status,
            )

            return record

    async def get(self, process_id: str) -> ProcessRecord | None:
        """Get a process record by ID."""
        async with self._lock:
            return self._processes.get(process_id)

    async def list_active(self) -> list[ProcessRecord]:
        """List all currently running active processes."""
        async with self._lock:
            return list(self._processes.values())

    async def list_by_agent(self, agent_id: str) -> list[ProcessRecord]:
        """List active processes owned by a specific agent."""
        async with self._lock:
            proc_ids = self._agent_index.get(agent_id, set())
            return [self._processes[pid] for pid in proc_ids if pid in self._processes]

    async def list_by_engagement(self, engagement_id: str) -> list[ProcessRecord]:
        """List active processes for an entire engagement."""
        async with self._lock:
            proc_ids = self._engagement_index.get(engagement_id, set())
            return [self._processes[pid] for pid in proc_ids if pid in self._processes]

    async def count(self) -> int:
        """Return count of active running processes."""
        async with self._lock:
            return len(self._processes)

    async def kill_process(self, process_id: str) -> bool:
        """Instantly kill a single registered process via its WorkerProcess reference."""
        worker = None
        async with self._lock:
            worker = self._workers.get(process_id)

        if worker:
            await worker.kill()
            await self.unregister(process_id, status="KILLED")
            logger.info("Killed registered process", process_id=process_id)
            return True
        return False

    async def kill_all_for_agent(self, agent_id: str) -> int:
        """Kill all active processes belonging to a specific agent."""
        target_ids: list[str] = []
        async with self._lock:
            target_ids = list(self._agent_index.get(agent_id, set()))

        killed_count = 0
        for proc_id in target_ids:
            if await self.kill_process(proc_id):
                killed_count += 1

        logger.info(
            "Executed agent-level kill switch",
            agent_id=agent_id,
            killed_count=killed_count,
        )
        return killed_count

    async def kill_all_for_engagement(self, engagement_id: str) -> int:
        """Kill all active processes belonging to an entire engagement."""
        target_ids: list[str] = []
        async with self._lock:
            target_ids = list(self._engagement_index.get(engagement_id, set()))

        killed_count = 0
        for proc_id in target_ids:
            if await self.kill_process(proc_id):
                killed_count += 1

        logger.info(
            "Executed engagement-level kill switch",
            engagement_id=engagement_id,
            killed_count=killed_count,
        )
        return killed_count

    async def kill_all_global(self) -> int:
        """Emergency global kill switch: terminates ALL active registered subprocesses across all engagements."""
        target_ids: list[str] = []
        async with self._lock:
            target_ids = list(self._processes.keys())

        killed_count = 0
        for proc_id in target_ids:
            if await self.kill_process(proc_id):
                killed_count += 1

        logger.warning(
            "Executed GLOBAL EMERGENCY KILL SWITCH",
            total_killed=killed_count,
        )
        return killed_count


# Global singleton process registry instance
global_process_registry = ProcessRegistry()
