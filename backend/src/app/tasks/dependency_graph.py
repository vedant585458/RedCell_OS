"""Task dependency Directed Acyclic Graph (DAG) engine with cycle detection and topological readiness computation."""

from collections import deque
from typing import Any

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.domain.audit import AuditEventCreateRequest
from app.domain.task import TaskDependencyModel, TaskStatus
from app.orchestrator.core import global_orchestrator
from app.repositories.unit_of_work import UnitOfWork

logger = get_logger("tasks.dependency_graph")


class DependencyGraphError(ValueError):
    """Base exception for dependency graph operations."""

    pass


class CyclicDependencyError(DependencyGraphError):
    """Raised when an edge creation would introduce a cycle into the task graph."""

    def __init__(self, from_task: str, to_task: str, cycle_path: list[str] | None = None) -> None:
        self.from_task = from_task
        self.to_task = to_task
        self.cycle_path = cycle_path or [from_task, to_task, from_task]
        path_str = " -> ".join(self.cycle_path)
        super().__init__(
            f"Cyclic dependency detected: Adding dependency '{from_task}' -> '{to_task}' "
            f"creates a closed cycle: [{path_str}]."
        )


class SelfDependencyError(DependencyGraphError):
    """Raised when a task attempts to depend on itself."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"Self-dependency detected: Task '{task_id}' cannot depend on itself.")


class TaskNodeNotFoundError(DependencyGraphError):
    """Raised when an operation references a nonexistent task node in the graph."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"Task node '{task_id}' does not exist in the dependency graph.")


class TaskDependencyGraph(BaseModel):
    """In-memory representation of an engagement's task Directed Acyclic Graph (DAG)."""

    nodes: set[str] = Field(default_factory=set, description="All registered task IDs")
    # depends_on[A] = {B, C} means task A depends on prerequisites B and C (must run after B and C)
    depends_on: dict[str, set[str]] = Field(
        default_factory=dict,
        description="Map of task_id to prerequisite task IDs",
    )
    # blocks[B] = {A} means task B blocks downstream dependent A
    blocks: dict[str, set[str]] = Field(
        default_factory=dict,
        description="Map of task_id to downstream blocked task IDs",
    )
    statuses: dict[str, TaskStatus] = Field(
        default_factory=dict,
        description="Map of task_id to current lifecycle status",
    )

    def add_node(self, task_id: str, status: TaskStatus | str | None = None) -> None:
        """Add a task node to the graph if not already present."""
        self.nodes.add(task_id)
        if task_id not in self.depends_on:
            self.depends_on[task_id] = set()
        if task_id not in self.blocks:
            self.blocks[task_id] = set()
        if status is not None:
            resolved_status = status if isinstance(status, TaskStatus) else TaskStatus(str(status))
            self.statuses[task_id] = resolved_status
        elif task_id not in self.statuses:
            self.statuses[task_id] = TaskStatus.PENDING

    def set_status(self, task_id: str, status: TaskStatus | str) -> None:
        """Update current status of a task node."""
        resolved_status = status if isinstance(status, TaskStatus) else TaskStatus(str(status))
        self.add_node(task_id, resolved_status)
        self.statuses[task_id] = resolved_status

    def would_create_cycle(self, task_id: str, depends_on_task_id: str) -> list[str] | None:
        """Incremental DFS Cycle Detection: Check if adding (task_id depends on depends_on_task_id)

        would create a directed cycle.

        Adding edge (depends_on_task_id -> task_id in execution flow) creates a cycle iff
        task_id can already reach depends_on_task_id in the downstream execution graph (blocks).
        Returns the cycle path list if a cycle is detected, else None.
        """
        if task_id == depends_on_task_id:
            return [task_id, task_id]

        # Targeted incremental DFS from task_id following existing downstream 'blocks' edges
        visited: set[str] = set()
        parent_map: dict[str, str] = {}
        stack: list[str] = [task_id]

        while stack:
            curr = stack.pop()
            if curr == depends_on_task_id:
                # Reconstruct cycle path
                path = [depends_on_task_id]
                step = curr
                while step != task_id and step in parent_map:
                    step = parent_map[step]
                    path.append(step)
                path.reverse()
                path.append(depends_on_task_id)
                return path

            if curr not in visited:
                visited.add(curr)
                for downstream in self.blocks.get(curr, set()):
                    if downstream not in visited:
                        parent_map[downstream] = curr
                        stack.append(downstream)

        return None

    def add_edge(self, task_id: str, depends_on_task_id: str) -> None:
        """Add a validated dependency edge: task_id depends on depends_on_task_id.

        Raises SelfDependencyError or CyclicDependencyError if invalid.
        """
        if task_id == depends_on_task_id:
            raise SelfDependencyError(task_id)

        cycle_path = self.would_create_cycle(task_id, depends_on_task_id)
        if cycle_path:
            raise CyclicDependencyError(task_id, depends_on_task_id, cycle_path)

        self.add_node(task_id)
        self.add_node(depends_on_task_id)

        self.depends_on[task_id].add(depends_on_task_id)
        self.blocks[depends_on_task_id].add(task_id)

    def is_task_ready(self, task_id: str) -> bool:
        """Technical Decision: Task is 'READY' iff all prerequisite dependencies have status == COMPLETED."""
        prereqs = self.depends_on.get(task_id, set())
        if not prereqs:
            return True
        return all(self.statuses.get(p) == TaskStatus.COMPLETED for p in prereqs)

    def compute_unblocked_tasks(self, completed_task_id: str) -> list[str]:
        """When a task completes, compute which downstream tasks now have all prerequisites satisfied."""
        self.set_status(completed_task_id, TaskStatus.COMPLETED)
        unblocked: list[str] = []

        # Check all tasks directly blocked by the completed task
        downstream_candidates = self.blocks.get(completed_task_id, set())
        for target_id in downstream_candidates:
            current_status = self.statuses.get(target_id, TaskStatus.PENDING)
            # Only pending tasks can transition to READY
            if current_status == TaskStatus.PENDING:
                if self.is_task_ready(target_id):
                    unblocked.append(target_id)

        return unblocked

    def get_topological_order(self) -> list[str]:
        """Compute topological sort ordering of the task DAG using Kahn's algorithm."""
        in_degree: dict[str, int] = {
            node: len(self.depends_on.get(node, set())) for node in self.nodes
        }
        queue: deque[str] = deque([node for node, deg in in_degree.items() if deg == 0])
        topo_order: list[str] = []

        while queue:
            node = queue.popleft()
            topo_order.append(node)

            for downstream in self.blocks.get(node, set()):
                in_degree[downstream] -= 1
                if in_degree[downstream] == 0:
                    queue.append(downstream)

        if len(topo_order) != len(self.nodes):
            remaining = set(self.nodes) - set(topo_order)
            raise CyclicDependencyError("graph_cycle", f"Unresolvable cycle in nodes: {remaining}")

        return topo_order

    def get_execution_waves(self) -> list[list[str]]:
        """Partition the task DAG into parallel execution layers/waves for concurrent dispatch."""
        in_degree: dict[str, int] = {
            node: len(self.depends_on.get(node, set())) for node in self.nodes
        }
        current_wave = [node for node, deg in in_degree.items() if deg == 0]
        waves: list[list[str]] = []
        processed_count = 0

        while current_wave:
            waves.append(sorted(current_wave))
            processed_count += len(current_wave)
            next_wave: list[str] = []

            for node in current_wave:
                for downstream in self.blocks.get(node, set()):
                    in_degree[downstream] -= 1
                    if in_degree[downstream] == 0:
                        next_wave.append(downstream)

            current_wave = next_wave

        if processed_count != len(self.nodes):
            raise CyclicDependencyError(
                "graph_cycle", "Cycle detected during execution wave computation"
            )

        return waves


class TaskDependencyGraphEngine:
    """Service managing graph construction from database records, cycle validation, and readiness unblocking."""

    def __init__(self, session_factory: Any) -> None:
        self.session_factory = session_factory

    async def load_engagement_graph(self, engagement_id: str) -> TaskDependencyGraph:
        """Construct an in-memory TaskDependencyGraph from relational database task and edge tables."""
        graph = TaskDependencyGraph()

        async with UnitOfWork(self.session_factory) as uow:
            tasks = await uow.tasks.list_by_engagement(engagement_id)
            for t in tasks:
                graph.add_node(t.task_id, t.status)

            for t in tasks:
                for dep_id in t.depends_on:
                    # Direct assignment without re-checking cycle on bulk load from verified DB
                    graph.add_node(dep_id)
                    graph.depends_on[t.task_id].add(dep_id)
                    graph.blocks[dep_id].add(t.task_id)

        return graph

    async def validate_and_add_dependency(
        self,
        task_id: str,
        depends_on_task_id: str,
        engagement_id: str,
        correlation_id: str = "",
    ) -> bool:
        """Validate acyclicity synchronously and persist a new dependency edge in the database.

        Technical Decision: Cycle check runs synchronously before edge commit, rejecting on violation.
        """
        if task_id == depends_on_task_id:
            raise SelfDependencyError(task_id)

        # 1. Load current graph and test hypothetical edge
        graph = await self.load_engagement_graph(engagement_id)
        cycle_path = graph.would_create_cycle(task_id, depends_on_task_id)
        if cycle_path:
            raise CyclicDependencyError(task_id, depends_on_task_id, cycle_path)

        # 2. Persist edge in database
        corr_id = correlation_id or f"corr-edge-{task_id}-{depends_on_task_id}"
        async with UnitOfWork(self.session_factory) as uow:
            assert uow.session is not None
            edge = TaskDependencyModel(task_id=task_id, depends_on_task_id=depends_on_task_id)
            uow.session.add(edge)

            # Record audit event
            await uow.audit.append_audit_event(
                AuditEventCreateRequest(
                    event_id=f"aud-edge-{task_id[:8]}-{depends_on_task_id[:8]}",
                    engagement_id=engagement_id,
                    correlation_id=corr_id,
                    event_type="dependency_edge_created",
                    actor_type="SYSTEM",
                    actor_id="dependency_graph_engine",
                    payload={"task_id": task_id, "depends_on_task_id": depends_on_task_id},
                )
            )
            await uow.commit()

        # 3. Broadcast graph edge event
        await global_orchestrator.emit_event(
            event_type="task_dependency_added",
            correlation_id=corr_id,
            engagement_id=engagement_id,
            task_id=task_id,
            payload={"task_id": task_id, "depends_on_task_id": depends_on_task_id},
        )

        return True

    async def validate_and_add_batch_dependencies(
        self,
        engagement_id: str,
        edges: list[tuple[str, str]],
        correlation_id: str = "",
    ) -> int:
        """Validate a batch of edges atomically against cycles before persisting any edge.

        Rejects the entire batch on any cycle violation.
        """
        if not edges:
            return 0

        # Load graph and simulate all edges
        graph = await self.load_engagement_graph(engagement_id)
        for from_task, to_task in edges:
            if from_task == to_task:
                raise SelfDependencyError(from_task)
            cycle = graph.would_create_cycle(from_task, to_task)
            if cycle:
                raise CyclicDependencyError(from_task, to_task, cycle)
            graph.add_edge(from_task, to_task)

        corr_id = correlation_id or f"corr-batch-edges-{engagement_id}"
        added_count = 0

        async with UnitOfWork(self.session_factory) as uow:
            assert uow.session is not None
            for from_task, to_task in edges:
                edge = TaskDependencyModel(task_id=from_task, depends_on_task_id=to_task)
                uow.session.add(edge)
                added_count += 1

            await uow.audit.append_audit_event(
                AuditEventCreateRequest(
                    event_id=f"aud-batch-edges-{engagement_id[:8]}",
                    engagement_id=engagement_id,
                    correlation_id=corr_id,
                    event_type="dependency_edges_batch_created",
                    actor_type="SYSTEM",
                    actor_id="dependency_graph_engine",
                    payload={"edge_count": added_count, "edges": edges},
                )
            )
            await uow.commit()

        return added_count

    async def on_task_completed(
        self,
        completed_task_id: str,
        engagement_id: str,
        correlation_id: str = "",
    ) -> list[str]:
        """Compute unblocked tasks on task completion, update their database status to READY,

        and broadcast state change events.
        """
        graph = await self.load_engagement_graph(engagement_id)
        unblocked_ids = graph.compute_unblocked_tasks(completed_task_id)

        if not unblocked_ids:
            return []

        corr_id = correlation_id or f"corr-unblock-{completed_task_id}"

        async with UnitOfWork(self.session_factory) as uow:
            for tid in unblocked_ids:
                await uow.tasks.update_status(tid, TaskStatus.READY)
                await uow.audit.append_audit_event(
                    AuditEventCreateRequest(
                        event_id=f"aud-unblock-{tid[:8]}",
                        engagement_id=engagement_id,
                        correlation_id=corr_id,
                        event_type="task_unblocked_to_ready",
                        actor_type="SYSTEM",
                        actor_id="dependency_graph_engine",
                        payload={"task_id": tid, "unblocked_by": completed_task_id},
                    )
                )
            await uow.commit()

        # Emit events for each unblocked task
        for tid in unblocked_ids:
            await global_orchestrator.emit_event(
                event_type="task_status_changed",
                correlation_id=corr_id,
                engagement_id=engagement_id,
                task_id=tid,
                payload={
                    "task_id": tid,
                    "prior_status": TaskStatus.PENDING.value,
                    "new_status": TaskStatus.READY.value,
                    "reason": f"Prerequisite task '{completed_task_id}' completed",
                },
            )

        logger.info(
            f"Task '{completed_task_id}' completion unblocked {len(unblocked_ids)} downstream tasks: {unblocked_ids}",
            completed_task_id=completed_task_id,
            unblocked_ids=unblocked_ids,
        )

        return unblocked_ids
