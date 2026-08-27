"""Concrete HTTP Probe Tool Wrapper implementing ToolInterface with argument validation and structured output parsing."""

import re
from typing import Any

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.process.worker import ProcessResult, WorkerProcess
from app.tools.base import ToolInterface, ToolRiskLevel

logger = get_logger("tools.http_probe")

# Standard technology signature patterns
TECH_SIGNATURES: list[tuple[str, re.Pattern[str]]] = [
    ("FastAPI", re.compile(r"\bfastapi\b|openapi\.json|docs-url", re.IGNORECASE)),
    ("Uvicorn", re.compile(r"\buvicorn\b", re.IGNORECASE)),
    ("Nginx", re.compile(r"\bnginx(?:\/[\d\.]+)?\b", re.IGNORECASE)),
    ("Apache", re.compile(r"\bapache(?:\/[\d\.]+)?\b", re.IGNORECASE)),
    ("Express", re.compile(r"\bx-powered-by:\s*express\b", re.IGNORECASE)),
    ("PHP", re.compile(r"\bx-powered-by:\s*php(?:\/[\d\.]+)?\b|\.php", re.IGNORECASE)),
    ("Python", re.compile(r"\bpython(?:\/[\d\.]+)?\b", re.IGNORECASE)),
    ("React", re.compile(r"\bdata-reactroot\b|react-dom", re.IGNORECASE)),
    ("Cloudflare", re.compile(r"\bcf-ray\b|\bcloudflare\b", re.IGNORECASE)),
    ("OpenSSL", re.compile(r"\bopenssl(?:\/[\d\.]+)?\b", re.IGNORECASE)),
    ("Gunicorn", re.compile(r"\bgunicorn\b", re.IGNORECASE)),
]


class HttpProbeArgs(BaseModel):
    """Validated input parameters for the HTTP Probe tool."""

    target_url: str = Field(..., description="Target URL (e.g. http://127.0.0.1:8000/health)")
    method: str = Field(default="GET", description="HTTP request method (GET, POST, HEAD, OPTIONS)")
    path: str = Field(default="", description="Optional subpath route")
    headers: dict[str, str] = Field(default_factory=dict, description="Custom HTTP request headers")
    timeout_sec: float = Field(
        default=15.0, ge=1.0, le=120.0, description="Socket timeout in seconds"
    )
    follow_redirects: bool = Field(default=True, description="Whether to follow 3xx redirects")

    def get_full_url(self) -> str:
        """Construct canonical full target URL."""
        base = self.target_url.strip()
        if not (base.startswith("http://") or base.startswith("https://")):
            base = f"http://{base}"
        if self.path and self.path != "/":
            return f"{base.rstrip('/')}/{self.path.lstrip('/')}"
        return base


class HttpProbeResult(BaseModel):
    """Structured response parsed from raw HTTP probe execution output."""

    target_url: str
    status_code: int = Field(default=0, description="HTTP status code (0 if connection failed)")
    is_reachable: bool = Field(
        default=False, description="Whether target responded to HTTP request"
    )
    content_length: int = Field(default=0)
    content_type: str = Field(default="")
    title: str | None = Field(default=None, description="Extracted HTML <title> tag")
    server_header: str | None = Field(default=None, description="Extracted Server response header")
    headers: dict[str, str] = Field(default_factory=dict)
    tech_stack: list[str] = Field(
        default_factory=list, description="Detected frameworks and servers"
    )
    response_time_ms: float = Field(default=0.0)
    body_snippet: str = Field(default="", description="Snippet of response body")
    raw_stdout: str = Field(default="")
    raw_stderr: str = Field(default="")
    error_message: str | None = None


class HttpProbeTool(ToolInterface[HttpProbeArgs, HttpProbeResult]):
    """Concrete tool wrapper for active HTTP probing, technology detection, and endpoint profiling."""

    tool_id: str = "http_probe"
    name: str = "HTTP Web Route & Technology Prober"
    required_capability: str = "web_crawling"
    risk_level: ToolRiskLevel = ToolRiskLevel.INTRUSIVE

    def validate_args(self, raw_args: dict[str, Any]) -> HttpProbeArgs:
        """Validate raw arguments against HttpProbeArgs schema."""
        # Support aliases like 'url' -> 'target_url'
        processed = dict(raw_args)
        if "url" in processed and "target_url" not in processed:
            processed["target_url"] = processed["url"]
        return HttpProbeArgs(**processed)

    def build_argv(self, args: HttpProbeArgs) -> list[str]:
        """Construct safe curl CLI command tokens with header formatting."""
        full_url = args.get_full_url()

        # Build curl arguments: -i (include response headers), -s (silent), -S (show errors)
        argv = ["curl", "-i", "-s", "-S"]

        if args.follow_redirects:
            argv.append("-L")

        argv.extend(["--max-time", str(int(args.timeout_sec))])
        argv.extend(["-X", args.method.upper()])

        # Add custom headers
        for k, v in args.headers.items():
            # Sanitize header values against shell control characters
            clean_k = re.sub(r"[^\w\-]", "", k)
            clean_v = re.sub(r"[\r\n]", "", str(v))
            argv.extend(["-H", f"{clean_k}: {clean_v}"])

        argv.append(full_url)
        return argv

    def parse_output(self, process_result: ProcessResult, target_url: str = "") -> HttpProbeResult:
        """Parse raw curl HTTP wire response into structured HttpProbeResult."""
        stdout = process_result.stdout
        stderr = process_result.stderr
        duration_ms = round(process_result.duration_sec * 1000.0, 2)

        # 1. Check for failed connection / zero output
        if process_result.exit_code != 0 and not stdout:
            err_msg = (
                stderr.strip()
                or f"Process exited with non-zero exit code {process_result.exit_code}"
            )
            return HttpProbeResult(
                target_url=target_url or "unknown",
                status_code=0,
                is_reachable=False,
                response_time_ms=duration_ms,
                raw_stdout=stdout,
                raw_stderr=stderr,
                error_message=err_msg,
            )

        # 2. Split response headers from body
        # HTTP wire responses separate headers from body with \r\n\r\n or \n\n
        blocks = re.split(r"\r?\n\r?\n", stdout)
        if not blocks:
            return HttpProbeResult(
                target_url=target_url,
                is_reachable=False,
                raw_stdout=stdout,
                raw_stderr=stderr,
                error_message="Malformed HTTP response: no header blocks found",
            )

        # In case of 3xx redirects with -L, the final block is the body, and the preceding block is final headers
        body_snippet = blocks[-1] if len(blocks) > 1 else ""
        header_text = blocks[-2] if len(blocks) > 1 else blocks[0]

        # 3. Parse Status Line (e.g. "HTTP/1.1 200 OK" or "HTTP/2 200")
        status_code = 0
        headers_dict: dict[str, str] = {}
        header_lines = header_text.splitlines()

        for idx, line in enumerate(header_lines):
            line_str = line.strip()
            if idx == 0 and line_str.upper().startswith("HTTP/"):
                match = re.search(r"HTTP\/\S+\s+(\d{3})", line_str)
                if match:
                    status_code = int(match.group(1))
            elif ":" in line_str:
                k, v = line_str.split(":", 1)
                headers_dict[k.strip().lower()] = v.strip()

        # 4. Extract HTML Title Tag (<title>...</title>)
        title = None
        title_match = re.search(
            r"<title(?:\s+[^>]*)?>(.*?)</title>", body_snippet, re.IGNORECASE | re.DOTALL
        )
        if title_match:
            title = " ".join(title_match.group(1).split())

        # 5. Extract Server Header and Content Metadata
        server_header = headers_dict.get("server")
        content_type = headers_dict.get("content-type", "")
        content_length_str = headers_dict.get("content-length")
        content_length = (
            int(content_length_str)
            if content_length_str and content_length_str.isdigit()
            else len(body_snippet)
        )

        # 6. Technology Detection Heuristics
        tech_detected: set[str] = set()
        haystack = f"{stdout}\n{stderr}"
        for tech_name, pattern in TECH_SIGNATURES:
            if pattern.search(haystack):
                tech_detected.add(tech_name)

        is_reachable = status_code > 0

        return HttpProbeResult(
            target_url=target_url,
            status_code=status_code,
            is_reachable=is_reachable,
            content_length=content_length,
            content_type=content_type,
            title=title,
            server_header=server_header,
            headers=headers_dict,
            tech_stack=sorted(tech_detected),
            response_time_ms=duration_ms,
            body_snippet=body_snippet[:1000],
            raw_stdout=stdout,
            raw_stderr=stderr,
            error_message=None if is_reachable else (stderr.strip() or "Unreachable endpoint"),
        )

    async def execute_probe(
        self,
        args: HttpProbeArgs | dict[str, Any],
        cwd: str | None = None,
    ) -> HttpProbeResult:
        """Execute the probe and return structured result."""
        typed_args = args if isinstance(args, HttpProbeArgs) else self.validate_args(args)
        cmd_argv = self.build_argv(typed_args)

        worker = WorkerProcess(
            cmd=cmd_argv,
            cwd=cwd,
            timeout_sec=typed_args.timeout_sec,
        )

        process_result = await worker.execute()
        return self.parse_output(process_result, target_url=typed_args.get_full_url())


# Global singleton instance of HttpProbeTool
global_http_probe_tool = HttpProbeTool()
