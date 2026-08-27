"""Unit tests for the thread-safe ProcessRegistry and kill switch mechanisms."""

import asyncio
import sys

import pytest
from app.main import create_app
from app.process.registry import ProcessRegistry
from app.process.worker import WorkerProcess
from fastapi.testclient import TestClient


@pytest.mark.asyncio
async def test_process_registry_concurrency_load():
    registry = ProcessRegistry()
    workers: list[WorkerProcess] = []
    registered_ids: list[str] = []

    # Spawn 20 sleeping workers concurrently
    async def spawn_and_register(idx: int):
        worker = WorkerProcess(
            cmd=[sys.executable, "-c", "import time; time.sleep(1.5)"]
        )
        # Launch subprocess
        task = asyncio.create_task(worker.execute())
        # Wait briefly for PID allocation
        for _ in range(50):
            if worker.pid:
                break
            await asyncio.sleep(0.01)

        record = await registry.register(
            worker=worker,
            agent_id=f"agent-recon-{idx % 4}",
            command=worker.cmd,
            workspace_path="/tmp/test_ws",
            engagement_id="eng-load-test-01",
            task_id=f"T{idx}",
        )
        workers.append(worker)
        registered_ids.append(record.process_id)
        return task

    tasks = [await spawn_and_register(i) for i in range(20)]

    # Assert 20 active processes in registry
    assert await registry.count() == 20
    active_records = await registry.list_active()
    assert len(active_records) == 20

    # Unregister / complete all
    for proc_id in registered_ids:
        await registry.unregister(proc_id, status="COMPLETED")

    assert await registry.count() == 0

    # Clean up worker child processes
    for w in workers:
        await w.kill()
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_process_registry_agent_targeted_kill():
    registry = ProcessRegistry()
    workers: list[WorkerProcess] = []
    tasks = []

    # Spawn 3 processes for agent-01 and 3 processes for agent-02
    for i in range(6):
        agent_id = "agent-target-01" if i < 3 else "agent-target-02"
        worker = WorkerProcess(cmd=[sys.executable, "-c", "import time; time.sleep(5)"])
        task = asyncio.create_task(worker.execute())
        tasks.append(task)

        for _ in range(50):
            if worker.pid:
                break
            await asyncio.sleep(0.01)

        await registry.register(
            worker=worker,
            agent_id=agent_id,
            command=worker.cmd,
            workspace_path="/tmp/test_ws",
            engagement_id="eng-targeted-kill",
        )
        workers.append(worker)

    assert await registry.count() == 6
    agent_01_procs = await registry.list_by_agent("agent-target-01")
    assert len(agent_01_procs) == 3

    # Execute targeted kill on agent-target-01 only
    killed_count = await registry.kill_all_for_agent("agent-target-01")
    assert killed_count == 3

    # Assert agent-01 has 0 remaining, agent-02 still has 3 running
    assert len(await registry.list_by_agent("agent-target-01")) == 0
    assert len(await registry.list_by_agent("agent-target-02")) == 3
    assert await registry.count() == 3

    # Clean up remaining
    await registry.kill_all_global()
    assert await registry.count() == 0
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_process_registry_global_emergency_kill():
    registry = ProcessRegistry()
    tasks = []
    workers = []

    for _ in range(5):
        worker = WorkerProcess(cmd=[sys.executable, "-c", "import time; time.sleep(5)"])
        task = asyncio.create_task(worker.execute())
        tasks.append(task)

        for _ in range(50):
            if worker.pid:
                break
            await asyncio.sleep(0.01)

        await registry.register(
            worker=worker,
            agent_id="agent-recon-01",
            command=worker.cmd,
            workspace_path="/tmp/test_ws",
        )
        workers.append(worker)

    assert await registry.count() == 5

    # Global kill
    killed = await registry.kill_all_global()
    assert killed == 5
    assert await registry.count() == 0
    await asyncio.gather(*tasks, return_exceptions=True)


def test_processes_api_endpoints():
    app = create_app()
    client = TestClient(app)

    # 1. List active processes
    res = client.get("/api/v1/processes")
    assert res.status_code == 200
    assert isinstance(res.json(), list)

    # 2. Trigger kill-switch endpoint
    kill_res = client.post("/api/v1/kill-switch", json={})
    assert kill_res.status_code == 200
    data = kill_res.json()
    assert data["success"] is True
    assert data["scope"] == "global"
    assert "Emergency kill switch executed" in data["message"]
