"""Orchestrator core loop, command queue, and task supervision engine."""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

import structlog

from app.core.logging import get_logger
from app.orchestrator.models import (
    OrchestratorCommand,
    OrchestratorEvent,
    OrchestratorState,
)

logger = get_logger("orchestrator.core")

CommandHandler = Callable[[OrchestratorCommand], Coroutine[Any, Any, None]]
EventSubscriber = Callable[[OrchestratorEvent], Coroutine[Any, Any, None]]


class Orchestrator:
    """Central asyncio orchestrator loop managing task scheduling, command dispatch, and event broadcasting."""

    def __init__(self) -> None:
        self.state: OrchestratorState = OrchestratorState.STOPPED
        self.command_queue: asyncio.Queue[OrchestratorCommand] = asyncio.Queue()
        self.event_queue: asyncio.Queue[OrchestratorEvent] = asyncio.Queue()

        self._command_handlers: dict[str, CommandHandler] = {}
        self._event_subscribers: list[EventSubscriber] = []

        self._tracked_tasks: set[asyncio.Task[Any]] = set()
        self._command_worker_task: asyncio.Task[None] | None = None
        self._event_worker_task: asyncio.Task[None] | None = None
        self._seq_counter: int = 0
        self._lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        return self.state == OrchestratorState.RUNNING

    async def start(self) -> None:
        """Start the orchestrator worker loops."""
        if self.state == OrchestratorState.RUNNING:
            logger.warning("Orchestrator is already running")
            return

        self.state = OrchestratorState.STARTING
        logger.info("Starting Orchestrator core loop...")

        # Spawn background queue processors
        self._command_worker_task = asyncio.create_task(
            self._process_command_queue(), name="orchestrator_command_worker"
        )
        self._event_worker_task = asyncio.create_task(
            self._process_event_queue(), name="orchestrator_event_worker"
        )

        self.state = OrchestratorState.RUNNING
        logger.info("Orchestrator core loop is active and running")

    async def stop(self, timeout_sec: float = 3.0) -> None:
        """Gracefully stop the orchestrator and cancel all running background tasks."""
        if self.state in (OrchestratorState.STOPPED, OrchestratorState.STOPPING):
            return

        self.state = OrchestratorState.STOPPING
        logger.info("Stopping Orchestrator and draining task queue...")

        # Cancel worker loops
        if self._command_worker_task and not self._command_worker_task.done():
            self._command_worker_task.cancel()
        if self._event_worker_task and not self._event_worker_task.done():
            self._event_worker_task.cancel()

        # Cancel all tracked running agent/dispatch tasks
        active_tasks = [t for t in self._tracked_tasks if not t.done()]
        for task in active_tasks:
            task.cancel()

        all_workers = [
            t
            for t in [self._command_worker_task, self._event_worker_task, *active_tasks]
            if t is not None and not t.done()
        ]

        if all_workers:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*all_workers, return_exceptions=True),
                    timeout=timeout_sec,
                )
            except (TimeoutError, asyncio.CancelledError, RuntimeError):
                pass

        self._tracked_tasks.clear()
        self._command_worker_task = None
        self._event_worker_task = None

        self.state = OrchestratorState.STOPPED
        logger.info("Orchestrator has cleanly stopped with zero remaining tasks")

    def register_command_handler(self, command_type: str, handler: CommandHandler) -> None:
        """Register an async handler for a specific command type."""
        self._command_handlers[command_type] = handler

    def register_event_subscriber(self, subscriber: EventSubscriber) -> None:
        """Register an async callback for emitted outbound events."""
        self._event_subscribers.append(subscriber)

    async def submit_command(self, cmd: OrchestratorCommand) -> None:
        """Submit a command to the internal queue for processing."""
        if not self.is_running and self.state != OrchestratorState.STARTING:
            raise RuntimeError(f"Cannot submit command while Orchestrator is in state {self.state}")
        await self.command_queue.put(cmd)

    async def emit_event(
        self,
        event_type: str,
        correlation_id: str,
        payload: dict[str, Any] | None = None,
        engagement_id: str | None = None,
        agent_id: str | None = None,
        department_id: str | None = None,
        task_id: str | None = None,
    ) -> OrchestratorEvent:
        """Construct, sequence, and queue an outbound event."""
        async with self._lock:
            self._seq_counter += 1
            seq = self._seq_counter

        event = OrchestratorEvent(
            seq=seq,
            event_type=event_type,
            correlation_id=correlation_id,
            engagement_id=engagement_id,
            agent_id=agent_id,
            department_id=department_id,
            task_id=task_id,
            payload=payload or {},
        )
        await self.event_queue.put(event)
        return event

    def track_task(
        self, coro: Coroutine[Any, Any, Any], name: str | None = None
    ) -> asyncio.Task[Any]:
        """Safely wrap and track a coroutine as an asyncio.Task with exception logging."""
        task = asyncio.create_task(coro, name=name)
        self._tracked_tasks.add(task)

        def _on_done(t: asyncio.Task[Any]) -> None:
            self._tracked_tasks.discard(t)
            if not t.cancelled():
                exc = t.exception()
                if exc:
                    logger.error(
                        f"Unhandled exception in tracked task '{t.get_name()}': {exc}",
                        exc_info=exc,
                    )

        task.add_done_callback(_on_done)
        return task

    async def _process_command_queue(self) -> None:
        """Background loop consuming and executing inbound commands."""
        while self.state in (OrchestratorState.RUNNING, OrchestratorState.STARTING):
            try:
                cmd = await self.command_queue.get()
                structlog.contextvars.bind_contextvars(
                    correlation_id=cmd.correlation_id,
                    command_id=cmd.command_id,
                )

                logger.info(
                    f"Processing inbound command: {cmd.command_type}",
                    command_type=cmd.command_type,
                    correlation_id=cmd.correlation_id,
                )

                handler = self._command_handlers.get(cmd.command_type)
                if handler:
                    self.track_task(
                        handler(cmd),
                        name=f"cmd_handler_{cmd.command_type}_{cmd.command_id[:8]}",
                    )
                else:
                    logger.warning(f"No handler registered for command type: {cmd.command_type}")

                self.command_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in command processing loop: {e}", exc_info=True)

    async def _process_event_queue(self) -> None:
        """Background loop dispatching outbound events to subscribers."""
        while self.state in (OrchestratorState.RUNNING, OrchestratorState.STARTING):
            try:
                event = await self.event_queue.get()

                # Broadcast to all registered event subscribers concurrently
                if self._event_subscribers:
                    coros = [sub(event) for sub in self._event_subscribers]
                    await asyncio.gather(*coros, return_exceptions=True)

                self.event_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in event dispatching loop: {e}", exc_info=True)


# Global singleton orchestrator instance for backend process
global_orchestrator = Orchestrator()
