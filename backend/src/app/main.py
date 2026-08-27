"""Main entrypoint and FastAPI application factory for RedCell_OS."""

import argparse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.registry import global_agent_registry
from app.api import (
    departments_router,
    engagements_router,
    events_router,
    health_router,
    organization_router,
    processes_router,
    tasks_router,
    ws_router,
)
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.orchestrator import global_orchestrator
from app.services.org_bootstrap import OrgBootstrapService
from app.storage.database import dispose_engine, get_session_factory, init_db

logger = get_logger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan context manager for startup and shutdown events."""
    logger.info(
        "RedCell_OS backend control plane started",
        version=settings.version,
        environment=settings.environment,
        host=settings.host,
        port=settings.port,
    )
    # 1. Initialize relational database schema
    await init_db()

    # 2. Idempotently bootstrap organizational departments, roles, and baseline agents
    bootstrap_service = OrgBootstrapService(get_session_factory())
    await bootstrap_service.bootstrap_organization()

    # 3. Start the central orchestrator event loop
    await global_orchestrator.start()

    # 4. Reconcile runtime agent registry with database state (handling crash recovery)
    reconciliation_report = await global_agent_registry.reconcile_with_db(get_session_factory())
    logger.info(
        f"Agent reconciliation complete: {reconciliation_report.reconciled_count} active agents reconciled to RECOVERY",
        reconciled_count=reconciliation_report.reconciled_count,
        total_checked=reconciliation_report.total_checked,
    )

    yield
    # Gracefully cancel active agent tasks, stop orchestrator, and close DB
    logger.info("RedCell_OS backend control plane shutting down")
    await global_agent_registry.cancel_all()
    await global_orchestrator.stop()
    await dispose_engine()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    # Configure structured logging
    configure_logging(json_format=settings.json_logs, log_level=settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="AI-Agentic Penetration Testing Organization Simulator — Control Plane & Multi-Agent Orchestrator",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Enable CORS for local-first frontend & sandbox previews
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(health_router)
    app.include_router(processes_router)
    app.include_router(ws_router)
    app.include_router(events_router)
    app.include_router(organization_router)
    app.include_router(engagements_router)
    app.include_router(departments_router)
    app.include_router(tasks_router)

    return app


# ASGI instance for uvicorn
app = create_app()


def main() -> None:
    """CLI entrypoint for running backend with custom host/port arguments."""
    parser = argparse.ArgumentParser(description="Run RedCell_OS Backend Control Plane")
    parser.add_argument(
        "--host",
        type=str,
        default=settings.host,
        help=f"Host interface to bind (default: {settings.host})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=settings.port,
        help=f"Port to listen on (default: {settings.port})",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )

    args = parser.parse_args()

    print(f"Starting RedCell_OS on http://{args.host}:{args.port}")
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
