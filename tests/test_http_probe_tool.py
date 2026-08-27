"""Unit and integration tests for HttpProbeTool, ToolInterface contract, HTTP response parser, and end-to-end mediated execution."""

import http.server
import socket
import threading

import pytest
from app.domain.engagement import (
    Base,
    EngagementCreateRequest,
    TargetScopeSchema,
)
from app.domain.task import TaskCreateRequest, TaskStatus
from app.execution.service import CommandExecutionService
from app.repositories.unit_of_work import UnitOfWork
from app.services.org_bootstrap import OrgBootstrapService
from app.tools.base import ToolInterface
from app.tools.http_probe import (
    HttpProbeArgs,
    HttpProbeTool,
    global_http_probe_tool,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


class MockHttpHandler(http.server.BaseHTTPRequestHandler):
    """Mock HTTP request handler serving varied status codes, headers, and HTML titles for parser testing."""

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            body = (
                b"<!DOCTYPE html><html><head><title>Secure Portal - Dashboard</title></head>"
                b"<body><h1>FastAPI Backend Gateway</h1><p>Welcome to RedCell_OS portal</p></body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Server", "Apache/2.4.52 (Ubuntu)")
            self.send_header("X-Powered-By", "Express")
            self.end_headers()
            self.wfile.write(body)

        elif self.path == "/api/auth":
            body = b'{"error": "Unauthorized: Missing Bearer token"}'
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Server", "Nginx/1.18.0")
            self.end_headers()
            self.wfile.write(body)

        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()

        elif self.path == "/server-error":
            body = b"Internal Server Error"
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        else:
            body = b"Not Found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, format, *args):
        # Suppress standard logging to keep test output clean
        pass


@pytest.fixture(scope="module")
def local_test_server():
    """Spin up a real background multithreaded HTTP server on an available localhost port."""
    # Find free port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), MockHttpHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    base_url = f"http://127.0.0.1:{port}"
    yield base_url, port

    server.shutdown()
    server.server_close()


def test_tool_interface_contract_compliance():
    """Technical Decision: Verify HttpProbeTool strictly implements the standard ToolInterface contract."""
    tool = HttpProbeTool()
    assert isinstance(tool, ToolInterface)
    assert tool.tool_id == "http_probe"
    assert tool.required_capability == "web_crawling"

    # Argument validation
    args = tool.validate_args({"url": "http://127.0.0.1:8000/api", "method": "GET"})
    assert isinstance(args, HttpProbeArgs)
    assert args.target_url == "http://127.0.0.1:8000/api"
    assert args.method == "GET"

    # Command token construction
    argv = tool.build_argv(args)
    assert argv[0] == "curl"
    assert "-i" in argv
    assert "http://127.0.0.1:8000/api" in argv


@pytest.mark.asyncio
async def test_http_probe_execution_and_parsing_against_local_server(local_test_server):
    """Acceptance Criteria: Probing a real test HTTP server produces structured, correct result via the wrapper."""
    base_url, _ = local_test_server
    tool = HttpProbeTool()

    # 1. Probe 200 OK root endpoint with title and server headers
    result_root = await tool.execute_probe(
        args=HttpProbeArgs(
            target_url=base_url,
            path="/index.html",
            method="GET",
        )
    )

    assert result_root.is_reachable is True
    assert result_root.status_code == 200
    assert result_root.title == "Secure Portal - Dashboard"
    assert "Apache" in (result_root.server_header or "")
    assert "text/html" in result_root.content_type
    assert result_root.response_time_ms > 0.0

    # Verify technology stack detection signatures
    assert "Apache" in result_root.tech_stack
    assert "FastAPI" in result_root.tech_stack
    assert "Express" in result_root.tech_stack

    # 2. Probe 401 Unauthorized API endpoint
    result_auth = await tool.execute_probe(
        args={"target_url": f"{base_url}/api/auth", "method": "GET"}
    )
    assert result_auth.is_reachable is True
    assert result_auth.status_code == 401
    assert "Nginx" in result_auth.tech_stack
    assert "application/json" in result_auth.content_type
    assert "Unauthorized" in result_auth.body_snippet

    # 3. Probe Redirect (302 followed to 200)
    result_redir = await tool.execute_probe(
        args={"target_url": f"{base_url}/redirect", "follow_redirects": True}
    )
    assert result_redir.status_code == 200
    assert result_redir.title == "Secure Portal - Dashboard"

    # 4. Probe 500 Server Error
    result_500 = await tool.execute_probe(
        args={"target_url": f"{base_url}/server-error"}
    )
    assert result_500.is_reachable is True
    assert result_500.status_code == 500


@pytest.mark.asyncio
async def test_http_probe_unreachable_endpoint_graceful_handling():
    """Risk Mitigation: Verify parser resilience when connection is refused on an inactive port."""
    tool = HttpProbeTool()

    # Unused local port (connection refused)
    result = await tool.execute_probe(
        args=HttpProbeArgs(
            target_url="http://127.0.0.1:59988",
            timeout_sec=2.0,
        )
    )

    assert result.is_reachable is False
    assert result.status_code == 0
    assert result.error_message is not None


@pytest.mark.asyncio
async def test_full_pipeline_mediated_command_execution(local_test_server):
    """End-to-End Integration: Execute HTTP probe through full CommandExecutionService pipeline."""
    base_url, port = local_test_server

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    bootstrap = OrgBootstrapService(session_factory)
    await bootstrap.bootstrap_organization()

    async with UnitOfWork(session_factory) as uow:
        await uow.engagements.create_engagement(
            EngagementCreateRequest(
                engagement_id="eng-probe-pipe-test",
                title="HTTP Probe Pipeline Test",
                organization="TargetOrg",
                authorized_by="CISO",
                target_scope=TargetScopeSchema(
                    allowed_ipv4_cidrs=["127.0.0.1/32"],
                    allowed_ports=[str(port), "80", "443"],
                ),
            )
        )
        await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_PROBE_LIVE",
                engagement_id="eng-probe-pipe-test",
                department_id="dept_recon",
                title="Live Port & HTTP Inspection",
                assigned_role="role_web_discovery",
                assigned_agent_id="agent-recon-01",
                input_context={"target": base_url},
            )
        )
        await uow.tasks.update_status("TASK_PROBE_LIVE", TaskStatus.RUNNING)
        await uow.commit()

    try:
        service = CommandExecutionService(session_factory)

        exec_res = await service.execute(
            agent_id="agent-recon-01",
            capability="web_crawling",
            args={"target_url": f"{base_url}/index.html", "path": "/"},
            task_id="TASK_PROBE_LIVE",
            engagement_id="eng-probe-pipe-test",
            tool_id_override="http_probe",
        )

        assert exec_res.exit_code == 0
        assert exec_res.task_id == "TASK_PROBE_LIVE"
        assert exec_res.tool_id == "http_probe"

        # Verify parsed output using tool wrapper
        parsed = global_http_probe_tool.parse_output(
            process_result=type(
                "FakeProc",
                (),
                {
                    "stdout": exec_res.stdout,
                    "stderr": exec_res.stderr,
                    "exit_code": exec_res.exit_code,
                    "duration_sec": exec_res.duration_sec,
                },
            )(),
            target_url=base_url,
        )

        assert parsed.status_code == 200
        assert parsed.title == "Secure Portal - Dashboard"
        assert "Apache" in (parsed.server_header or "")
    finally:
        await engine.dispose()
