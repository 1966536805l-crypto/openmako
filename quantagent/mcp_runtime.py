from __future__ import annotations

from .exception_audit import audit_suppressed_exception
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import http.client
import ipaddress
import json
import os
import re
import select
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .approvals import ensure_approval_for_policy
from .checkpoints import create_checkpoint
from .openclaw_runtime_utils import split_args_preserving_quotes
from .policy_gate import enforce_tool
from .query_runtime import QueryRuntime
from .runtime_store import record_tool_invocation
from .sandbox_policy import ALLOW, ASK, DENY, matches_tool_pattern, sanitize_env


CONFIG_PATH = ".quantagent/mcp_servers.json"
SECRET_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)(api[_-]?key|token|password|secret)(['\"\s:=]+)[^,'\"\s}]+"),
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
)
SECRET_KEY_PATTERN = re.compile(
    r"(?i)(api[_-]?key|token|password|secret|passwd|pwd|credential|credentials|auth|bearer|private[_-]?key)"
)


@dataclass(frozen=True)
class McpServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    transport: str = "stdio"
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    auth_profile: str = ""
    env: dict[str, str] = field(default_factory=dict)
    timeout: float = 8.0
    idle_ttl: float = 60.0
    enabled: bool = True
    permissions: dict[str, str] = field(default_factory=dict)
    guards: dict[str, dict[str, Any]] = field(default_factory=dict)
    env_whitelist: tuple[str, ...] = ()
    session_scoped: bool = True

    @property
    def argv(self) -> list[str]:
        return [self.command, *self.args]


@dataclass(frozen=True)
class McpTool:
    server: str
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    policy_action: str = ASK


@dataclass(frozen=True)
class McpCatalog:
    servers: list[McpServerConfig]
    tools: list[McpTool]
    errors: list[str] = field(default_factory=list)
    session_id: str = ""


@dataclass(frozen=True)
class McpToolSchemaRecord:
    server: str
    tool: str
    schema_hash: str
    input_schema: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class McpSchemaSnapshot:
    schema: str
    snapshot_hash: str
    generated_at_ms: int
    tools: tuple[McpToolSchemaRecord, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "snapshot_hash": self.snapshot_hash,
            "generated_at_ms": self.generated_at_ms,
            "tools": [tool.to_dict() for tool in self.tools],
        }


@dataclass(frozen=True)
class McpSchemaDrift:
    previous_hash: str
    current_hash: str
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()

    @property
    def has_drift(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class McpCallResult:
    ok: bool
    server: str
    tool: str
    result: Any = None
    error: str = ""
    invocation_id: str = ""
    approval_id: str = ""
    duration_ms: int = 0
    session_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class McpSession:
    project: Path
    config: McpServerConfig
    session_id: str = ""
    proc: subprocess.Popen[str] | None = None
    initialized: bool = False
    last_used_at: float = 0.0
    _stdout_buffer: str = field(default="", repr=False, compare=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    def start(self) -> "McpSession":
        if self.proc and self.proc.poll() is None:
            return self
        self.proc = subprocess.Popen(
            self.config.argv,
            cwd=self.project,
            env=_mcp_env(self.config),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            text=True,
        )
        self.last_used_at = time.monotonic()
        return self

    def initialize(self) -> dict[str, Any]:
        response = self.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "quantagent", "version": "0.1.0"}})
        self.initialized = True
        self.notify("notifications/initialized", {})
        return response

    def ensure_initialized(self) -> None:
        if not self.initialized:
            self.initialize()

    def notify(self, method: str, params: dict[str, Any]) -> None:
        with self._lock:
            self.start()
            if not self.proc or not self.proc.stdin:
                raise RuntimeError("MCP session failed to start")
            message = {"jsonrpc": "2.0", "method": method, "params": params}
            self.proc.stdin.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
            self.proc.stdin.flush()
            self.last_used_at = time.monotonic()

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.start()
            if not self.proc or not self.proc.stdin or not self.proc.stdout:
                raise RuntimeError("MCP session failed to start")
            request_id = uuid.uuid4().hex[:10]
            request = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            body = json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n"
            self.proc.stdin.write(body)
            self.proc.stdin.flush()
            deadline = time.monotonic() + self.config.timeout
            stdout_fd = self.proc.stdout.fileno()
            while time.monotonic() < deadline:
                remaining = max(0.0, deadline - time.monotonic())
                ready, _, _ = select.select([stdout_fd], [], [], remaining)
                if not ready:
                    break
                chunk = os.read(stdout_fd, 4096)
                if not chunk:
                    if self.proc.poll() is not None:
                        break
                    continue
                self._stdout_buffer += chunk.decode("utf-8", errors="replace")
                while "\n" in self._stdout_buffer:
                    line, self._stdout_buffer = self._stdout_buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    response = json.loads(line)
                    if not isinstance(response, dict):
                        raise RuntimeError("MCP response must be a JSON object")
                    if response.get("id") != request_id:
                        continue
                    if response.get("error"):
                        raise RuntimeError(json.dumps(response["error"], ensure_ascii=False, sort_keys=True))
                    self.last_used_at = time.monotonic()
                    return response
            self.close()
            raise TimeoutError(redact_mcp_error(f"MCP session timed out: {self.config.name}/{method}"))

    def tools_list(self) -> list[dict[str, Any]]:
        self.ensure_initialized()
        response = self.request("tools/list", {})
        result = _response_result(response)
        return result.get("tools", []) if isinstance(result, dict) else []

    def tools_call(self, tool: str, arguments: dict[str, Any]) -> Any:
        self.ensure_initialized()
        response = self.request("tools/call", {"name": tool, "arguments": arguments})
        return _response_result(response)

    def cleanup_idle(self, *, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        if self.proc and self.proc.poll() is None and now - self.last_used_at >= self.config.idle_ttl:
            self.close(status="expired")
            return True
        return False

    def close(self, *, status: str = "stopped") -> None:
        if self.proc is None:
            return
        if self.project.exists():
            _write_mcp_lease(self.project, self.config, self, status=status)
        _terminate(self.proc)
        self.proc = None

    def __enter__(self) -> "McpSession":
        return self.start()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


@dataclass(frozen=True)
class McpManagerStatus:
    sessions: int
    active: list[str]
    lease_dir: str = ""
    leases: list["McpLeaseRecord"] = field(default_factory=list)
    note: str = "process-local MCP manager with persistent lease registry; no external daemon process"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class McpLeaseRecord:
    lease_id: str
    server: str
    project: str
    transport: str
    auth_profile: str
    created_at_ms: int
    started_at_ms: int
    last_used_at_ms: int
    idle_ttl: float
    status: str = "active"
    pid: int | None = None
    endpoint: str = ""
    header_names: list[str] = field(default_factory=list)
    session_id: str = ""
    scope: str = "global"
    env_names: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class McpDaemonState:
    project: str
    lease_dir: str
    registry_path: str
    leases: list[McpLeaseRecord]
    note: str = "daemon-capable state only; Mako has not started an external MCP daemon"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class McpManager:
    """Process-local MCP manager.

    CLI invocations are still separate processes, but long-running chat/agent
    runtimes can reuse stdio sessions instead of respawning servers per tool.
    """

    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str, str], McpSession] = {}
        self._lock = threading.RLock()

    def session(self, project: str | Path, config: McpServerConfig, *, session_id: str = "") -> McpSession:
        _validate_mcp_session_id(session_id)
        project_path = Path(project).expanduser().resolve(strict=False)
        normalized_session_id = _normalize_mcp_session_id(session_id)
        key = (str(project_path), config.name, normalized_session_id)
        with self._lock:
            existing = self._sessions.get(key)
            if existing and existing.proc and existing.proc.poll() is None:
                existing.cleanup_idle()
                if existing.proc and existing.proc.poll() is None:
                    _write_mcp_lease(project, config, existing, status="active")
                    return existing
            session = McpSession(project_path, config, session_id=normalized_session_id).start()
            self._sessions[key] = session
        _write_mcp_lease(project, config, session, status="active")
        return session

    def request(self, project: str | Path, config: McpServerConfig, method: str, params: dict[str, Any], *, session_id: str = "") -> dict[str, Any]:
        if config.transport in {"http", "sse"}:
            _write_mcp_remote_lease(project, config, status="active", session_id=session_id)
            try:
                return _http_request(config, method, params)
            except Exception:
                _write_mcp_remote_lease(project, config, status="error", session_id=session_id)
                raise
        session = self.session(project, config, session_id=session_id)
        if method not in {"initialize", "notifications/initialized"}:
            session.ensure_initialized()
        return session.request(method, params)

    def tools_list(self, project: str | Path, config: McpServerConfig, *, session_id: str = "") -> list[dict[str, Any]]:
        if config.transport in {"http", "sse"}:
            _write_mcp_remote_lease(project, config, status="active", session_id=session_id)
            try:
                _http_request(config, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "quantagent", "version": "0.1.0"}})
                response = _http_request(config, "tools/list", {})
            except Exception:
                _write_mcp_remote_lease(project, config, status="error", session_id=session_id)
                raise
            _write_mcp_remote_lease(project, config, status="active", session_id=session_id)
            result = _response_result(response)
            return result.get("tools", []) if isinstance(result, dict) else []
        return self.session(project, config, session_id=session_id).tools_list()

    def tools_call(self, project: str | Path, config: McpServerConfig, tool: str, arguments: dict[str, Any], *, session_id: str = "") -> Any:
        if config.transport in {"http", "sse"}:
            _write_mcp_remote_lease(project, config, status="active", session_id=session_id)
            try:
                _http_request(config, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "quantagent", "version": "0.1.0"}})
                response = _http_request(config, "tools/call", {"name": tool, "arguments": arguments})
            except Exception:
                _write_mcp_remote_lease(project, config, status="error", session_id=session_id)
                raise
            _write_mcp_remote_lease(project, config, status="active", session_id=session_id)
            return _response_result(response)
        return self.session(project, config, session_id=session_id).tools_call(tool, arguments)

    def cleanup_idle(self) -> int:
        removed = 0
        with self._lock:
            for key, session in list(self._sessions.items()):
                if session.cleanup_idle():
                    self._sessions.pop(key, None)
                    removed += 1
        return removed

    def stop(self, project: str | Path | None = None, server: str | None = None, session_id: str | None = None) -> int:
        project_key = str(Path(project).expanduser().resolve(strict=False)) if project is not None else ""
        session_filter = _normalize_mcp_session_id(session_id) if session_id is not None else None
        stopped = 0
        with self._lock:
            for key, session in list(self._sessions.items()):
                session_project, session_server, session_scope = key
                if project_key and session_project != project_key:
                    continue
                if server and session_server != server:
                    continue
                if session_filter is not None and session_scope != session_filter:
                    continue
                session.close(status="stopped")
                self._sessions.pop(key, None)
                stopped += 1
        return stopped

    def close_all(self) -> None:
        with self._lock:
            for session in self._sessions.values():
                session.close(status="stopped")
            self._sessions.clear()

    def status(self, project: str | Path | None = None, *, server: str | None = None, session_id: str | None = None) -> McpManagerStatus:
        active = []
        lease_dir = ""
        leases: dict[str, McpLeaseRecord] = {}
        project_filter = str(Path(project).expanduser().resolve(strict=False)) if project is not None else ""
        session_filter = _normalize_mcp_session_id(session_id) if session_id is not None else None
        projects = {project_filter} if project_filter else set()
        with self._lock:
            sessions = list(self._sessions.items())
        for (session_project, name, session_scope), session in sessions:
            if project_filter and session_project != project_filter:
                continue
            if server and name != server:
                continue
            if session_filter is not None and session_scope != session_filter:
                continue
            projects.add(session_project)
            lease_dir = str(mcp_lease_dir(session_project))
            if session.proc and session.proc.poll() is None:
                suffix = f"@{session_scope}" if session_scope else ""
                active.append(f"{session_project}:{name}{suffix}")
        for lease_project in projects:
            lease_dir = lease_dir or str(mcp_lease_dir(lease_project))
            for lease in list_mcp_leases(lease_project, server=server, session_id=session_filter):
                leases[f"{lease.project}:{lease.lease_id}"] = lease
        return McpManagerStatus(len(active), sorted(active), lease_dir, sorted(leases.values(), key=lambda item: item.lease_id))


MCP_MANAGER = McpManager()


def load_mcp_servers(project: str | Path) -> list[McpServerConfig]:
    path = Path(project).expanduser().resolve(strict=False) / CONFIG_PATH
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_servers = payload.get("mcp_servers", payload.get("servers", {})) if isinstance(payload, dict) else {}
    servers: list[McpServerConfig] = []
    if isinstance(raw_servers, dict):
        items = raw_servers.items()
    elif isinstance(raw_servers, list):
        items = ((str(item.get("name") or ""), item) for item in raw_servers if isinstance(item, dict))
    else:
        items = []
    for name, raw in items:
        if not isinstance(raw, dict):
            continue
        transport = str(raw.get("transport") or ("http" if raw.get("url") else "stdio")).lower()
        if transport not in {"stdio", "http", "sse"}:
            transport = "stdio"
        command = raw.get("command")
        if isinstance(command, list) and command:
            argv = [str(item) for item in command]
            command_text, args = argv[0], argv[1:]
        else:
            raw_command = str(command or raw.get("cmd") or "")
            split_command = split_args_preserving_quotes(raw_command, escape_mode="backslash-quote-only")
            command_text = split_command[0] if split_command else ""
            split_args = split_command[1:] if split_command else []
            args = split_args + [str(item) for item in raw.get("args", []) if item is not None]
        url = str(raw.get("url") or raw.get("endpoint") or "")
        if not name or (transport == "stdio" and not command_text) or (transport in {"http", "sse"} and not url):
            continue
        env = {str(key): str(value) for key, value in (raw.get("env") or {}).items()} if isinstance(raw.get("env"), dict) else {}
        headers = {str(key): str(value) for key, value in (raw.get("headers") or {}).items()} if isinstance(raw.get("headers"), dict) else {}
        permissions = _normalize_permissions(raw.get("permissions") or raw.get("permission") or raw.get("policy"))
        guards = _normalize_guards(raw.get("guards"))
        servers.append(
            McpServerConfig(
                name=str(name),
                command=command_text,
                args=args,
                transport=transport,
                url=url,
                headers=headers,
                auth_profile=str(raw.get("auth_profile") or raw.get("authProfile") or ""),
                env=env,
                timeout=float(raw.get("timeout", 8.0)),
                idle_ttl=float(raw.get("idle_ttl", raw.get("idleTtl", 60.0))),
                enabled=bool(raw.get("enabled", True)),
                permissions=permissions,
                guards=guards,
                env_whitelist=tuple(str(item) for item in raw.get("env_whitelist", raw.get("envWhitelist", [])) if item is not None) if isinstance(raw.get("env_whitelist", raw.get("envWhitelist", [])), list) else (),
                session_scoped=bool(raw.get("session_scoped", raw.get("sessionScoped", True))),
            )
        )
    return servers


def open_mcp_session(project: str | Path, server: str, *, session_id: str = "") -> McpSession:
    _validate_mcp_session_id(session_id)
    project_path = Path(project).expanduser().resolve(strict=False)
    config = _find_server(project_path, server)
    session = McpSession(project_path, config, session_id=_normalize_mcp_session_id(session_id)).start()
    _write_mcp_lease(project_path, config, session, status="active")
    return session


def mcp_lease_dir(project: str | Path) -> Path:
    project_path = Path(project).expanduser().resolve(strict=False)
    base = project_path / "AI_协作交接"
    if not base.exists():
        base = project_path / ".quantagent"
    return base / "mcp_leases"


def mcp_lease_registry_path(project: str | Path) -> Path:
    return mcp_lease_dir(project) / "registry.json"


def list_mcp_leases(project: str | Path, *, server: str | None = None, session_id: str | None = None) -> list[McpLeaseRecord]:
    leases = _read_mcp_leases(project)
    if server:
        leases = [lease for lease in leases if lease.server == server]
    if session_id is not None:
        normalized_session_id = _normalize_mcp_session_id(session_id)
        leases = [lease for lease in leases if lease.session_id == normalized_session_id]
    _sync_mcp_lease_registry(project, leases)
    return sorted(leases, key=lambda item: (item.server, item.session_id, item.lease_id))


def status_mcp_daemon_state(project: str | Path, *, server: str | None = None, session_id: str | None = None) -> McpDaemonState:
    project_path = Path(project).expanduser().resolve(strict=False)
    leases = list_mcp_leases(project_path, server=server, session_id=session_id)
    return McpDaemonState(
        project=str(project_path),
        lease_dir=str(mcp_lease_dir(project_path)),
        registry_path=str(mcp_lease_registry_path(project_path)),
        leases=leases,
    )


def start_mcp_daemon_state(project: str | Path, *, server: str | None = None, session_id: str = "") -> McpDaemonState:
    """Create daemon-capable persistent lease state without spawning a daemon."""

    project_path = Path(project).expanduser().resolve(strict=False)
    configs = [item for item in load_mcp_servers(project_path) if item.enabled and (not server or item.name == server)]
    for config in configs:
        if config.transport in {"http", "sse"}:
            _write_mcp_remote_lease(project_path, config, status="active", session_id=session_id)
        elif config.session_scoped:
            MCP_MANAGER.session(project_path, config, session_id=session_id)
        else:
            _write_mcp_remote_lease(project_path, config, status="configured", session_id=session_id)
    return status_mcp_daemon_state(project_path, server=server, session_id=session_id)


def stop_mcp_daemon_state(project: str | Path, *, server: str | None = None, session_id: str | None = None) -> McpDaemonState:
    project_path = Path(project).expanduser().resolve(strict=False)
    MCP_MANAGER.stop(project_path, server=server, session_id=session_id)
    configs = [item for item in load_mcp_servers(project_path) if item.enabled and (not server or item.name == server)]
    known = {config.name for config in configs}
    for config in configs:
        normalized_session_id = _normalize_mcp_session_id(session_id) if session_id is not None else ""
        existing = _read_mcp_lease(project_path, _mcp_lease_id(config.name, normalized_session_id))
        if config.transport in {"http", "sse"} or not existing or existing.status != "stopped":
            _write_mcp_remote_lease(project_path, config, status="stopped", session_id=normalized_session_id)
    for lease in list_mcp_leases(project_path, session_id=session_id):
        if server and lease.server != server:
            continue
        if lease.server not in known:
            _write_mcp_lease_record(project_path, McpLeaseRecord(**(lease.to_dict() | {"status": "stopped", "last_used_at_ms": _now_ms()})))
    return status_mcp_daemon_state(project_path, server=server, session_id=session_id)


def cleanup_mcp_lease_registry(
    project: str | Path,
    *,
    statuses: tuple[str, ...] = ("stopped", "expired"),
    max_age_seconds: float | None = None,
) -> int:
    now = _now_ms()
    removed = 0
    kept: list[McpLeaseRecord] = []
    for lease in _read_mcp_leases(project):
        stale = max_age_seconds is not None and now - lease.last_used_at_ms >= max_age_seconds * 1000
        if lease.status in statuses or stale:
            path = mcp_lease_dir(project) / f"{lease.lease_id}.json"
            try:
                path.unlink()
                removed += 1
            except FileNotFoundError:
                pass
            continue
        kept.append(lease)
    _sync_mcp_lease_registry(project, kept)
    return removed


def list_mcp_catalog(project: str | Path, *, server: str | None = None) -> McpCatalog:
    servers = [item for item in load_mcp_servers(project) if item.enabled and (not server or item.name == server)]
    tools: list[McpTool] = []
    errors: list[str] = []
    runtime = QueryRuntime(Path(project), persist=True)
    for config in servers:
        runtime.pre_tool(f"mcp:{config.name}:tools/list", args={"server": config.name})
        try:
            if config.session_scoped:
                raw_tools = MCP_MANAGER.tools_list(project, config)
            else:
                response = _transport_request(config, "tools/list", {}, project=project)
                raw_tools = _response_result(response).get("tools", []) if isinstance(_response_result(response), dict) else []
            for raw in raw_tools:
                if not isinstance(raw, dict):
                    continue
                tool_name = str(raw.get("name") or "")
                decision = resolve_mcp_permission(config, tool_name)
                if decision.action == DENY:
                    continue
                tools.append(
                    McpTool(
                        server=config.name,
                        name=tool_name,
                        description=str(raw.get("description") or ""),
                        input_schema=raw.get("inputSchema") if isinstance(raw.get("inputSchema"), dict) else {},
                        policy_action=decision.action,
                    )
                )
            runtime.post_tool(f"mcp:{config.name}:tools/list", ok=True, summary=f"{len(raw_tools)} tool(s)")
        except Exception as exc:
            error = redact_mcp_error(f"{type(exc).__name__}: {exc}")
            errors.append(f"{config.name}: {error}")
            runtime.post_tool(f"mcp:{config.name}:tools/list", ok=False, summary=error)
    return McpCatalog(servers=servers, tools=[tool for tool in tools if tool.name], errors=errors)


def call_mcp_tool(
    project: str | Path,
    server: str,
    tool: str,
    arguments: dict[str, Any] | None = None,
    *,
    approval_id: str | None = None,
    owner_approved: bool = False,
    profile: str = "",
    session_id: str = "",
) -> McpCallResult:
    started = time.monotonic()
    invocation_id = "mcp-inv-" + uuid.uuid4().hex[:12]
    arguments = arguments or {}
    logged_arguments = redact_mcp_payload(arguments)
    logged_session_id = _normalize_mcp_session_id(session_id)
    runtime = QueryRuntime(Path(project), persist=True)
    runtime.pre_tool(f"mcp:{server}:{tool}", args=logged_arguments)
    try:
        _validate_mcp_session_id(session_id)
        config = _find_server(project, server)
        agent_policy: dict[str, Any] = {}
        if profile:
            agent_decision = enforce_tool(
                profile,
                f"mcp:{server}:{tool}",
                reason=f"call MCP tool {server}/{tool}",
                owner_approved=owner_approved,
                project=project,
                args=logged_arguments,
            )
            agent_policy = agent_decision.metadata()
            if agent_decision.action == DENY:
                duration_ms = round((time.monotonic() - started) * 1000)
                record_tool_invocation(
                    project,
                    invocation_id=invocation_id,
                    tool=f"mcp:{server}:{tool}",
                    status="failed",
                    args=logged_arguments,
                    policy=agent_policy,
                    query_id=runtime.query_id,
                    session_id=logged_session_id or None,
                    summary=agent_decision.summary,
                    error_kind="policy_blocked",
                    duration_ms=duration_ms,
                )
                runtime.post_tool(
                    f"mcp:{server}:{tool}",
                    ok=False,
                    summary=agent_decision.summary,
                    data={"invocation_id": invocation_id},
                )
                return McpCallResult(False, server, tool, error=agent_decision.summary, invocation_id=invocation_id, duration_ms=duration_ms, session_id=logged_session_id)
            agent_approval = ensure_approval_for_policy(
                project,
                tool=f"mcp:{server}:{tool}",
                args=logged_arguments,
                policy=agent_policy,
                reason=f"agent profile {profile} permits MCP tool {server}/{tool}",
                approval_id=approval_id,
            )
            if agent_decision.action == ASK and not (owner_approved or agent_approval.allowed):
                duration_ms = round((time.monotonic() - started) * 1000)
                summary = agent_approval.summary if agent_approval.approval_id else agent_decision.summary
                record_tool_invocation(
                    project,
                    invocation_id=invocation_id,
                    tool=f"mcp:{server}:{tool}",
                    status="failed",
                    args=logged_arguments,
                    policy=agent_policy | {"approval_id": agent_approval.approval_id},
                    approval_id=agent_approval.approval_id or None,
                    query_id=runtime.query_id,
                    session_id=logged_session_id or None,
                    summary=summary,
                    error_kind="policy_blocked",
                    duration_ms=duration_ms,
                )
                runtime.post_tool(
                    f"mcp:{server}:{tool}",
                    ok=False,
                    summary=summary,
                    data={"invocation_id": invocation_id, "approval_id": agent_approval.approval_id},
                )
                return McpCallResult(False, server, tool, error=summary, invocation_id=invocation_id, approval_id=agent_approval.approval_id, duration_ms=duration_ms, session_id=logged_session_id)
        decision = resolve_mcp_permission(config, tool)
        policy = decision.to_dict() | ({"agent_policy": agent_policy} if agent_policy else {})
        approval = ensure_approval_for_policy(
            project,
            tool=f"mcp:{server}:{tool}",
            args=logged_arguments,
            policy=policy,
            reason=f"call MCP tool {server}/{tool}",
            approval_id=approval_id,
        )
        approved = owner_approved or approval.allowed
        if decision.action == DENY or (decision.action == ASK and not approved):
            duration_ms = round((time.monotonic() - started) * 1000)
            summary = approval.summary if approval.approval_id else decision.reason
            record_tool_invocation(
                project,
                invocation_id=invocation_id,
                tool=f"mcp:{server}:{tool}",
                status="failed",
                args=logged_arguments,
                policy=policy | {"approval_id": approval.approval_id},
                approval_id=approval.approval_id or None,
                query_id=runtime.query_id,
                session_id=logged_session_id or None,
                summary=summary,
                error_kind="policy_blocked",
                duration_ms=duration_ms,
            )
            runtime.post_tool(
                f"mcp:{server}:{tool}",
                ok=False,
                summary=summary,
                data={"invocation_id": invocation_id, "approval_id": approval.approval_id},
            )
            return McpCallResult(False, server, tool, error=summary, invocation_id=invocation_id, approval_id=approval.approval_id, duration_ms=duration_ms, session_id=logged_session_id)
        guarded_arguments = apply_mcp_argument_guards(config, tool, arguments)
        logged_guarded_arguments = redact_mcp_payload(guarded_arguments)
        checkpoint_id = _checkpoint_before_mcp_tool(project, server, tool, guarded_arguments)
        if config.session_scoped:
            result = MCP_MANAGER.tools_call(project, config, tool, guarded_arguments, session_id=session_id)
        else:
            response = _transport_request(config, "tools/call", {"name": tool, "arguments": guarded_arguments}, project=project)
            result = _response_result(response)
        duration_ms = round((time.monotonic() - started) * 1000)
        record_tool_invocation(
            project,
            invocation_id=invocation_id,
            tool=f"mcp:{server}:{tool}",
            status="ok",
            args=logged_guarded_arguments,
            policy=policy | {"approval_id": approval.approval_id, **({"checkpoint_id": checkpoint_id} if checkpoint_id else {})},
            approval_id=approval.approval_id or None,
            query_id=runtime.query_id,
            session_id=logged_session_id or None,
            summary="mcp tool ok",
            output_preview=_result_preview(result),
            checkpoint_id=checkpoint_id or None,
            duration_ms=duration_ms,
        )
        runtime.post_tool(f"mcp:{server}:{tool}", ok=True, summary="mcp tool ok", data={"invocation_id": invocation_id, "checkpoint_id": checkpoint_id})
        return McpCallResult(True, server, tool, result=result, invocation_id=invocation_id, approval_id=approval.approval_id, duration_ms=duration_ms, session_id=logged_session_id)
    except Exception as exc:
        duration_ms = round((time.monotonic() - started) * 1000)
        error = redact_mcp_error(f"{type(exc).__name__}: {exc}")
        record_tool_invocation(
            project,
            invocation_id=invocation_id,
            tool=f"mcp:{server}:{tool}",
            status="failed",
            args=logged_arguments,
            policy={"runtime": "mcp", "server": server},
            query_id=runtime.query_id,
            session_id=logged_session_id or None,
            summary=error,
            error_kind="mcp_error",
            duration_ms=duration_ms,
        )
        runtime.post_tool(f"mcp:{server}:{tool}", ok=False, summary=error, data={"invocation_id": invocation_id})
        return McpCallResult(False, server, tool, error=error, invocation_id=invocation_id, duration_ms=duration_ms, session_id=logged_session_id)


def call_mcp_tools_concurrently(
    project: str | Path,
    calls: Iterable[dict[str, Any]],
    *,
    max_workers: int = 4,
    owner_approved: bool = False,
    profile: str = "",
) -> list[McpCallResult]:
    call_items = list(calls)
    results: list[McpCallResult | None] = [None] * len(call_items)
    workers = max(1, min(int(max_workers or 1), max(1, len(call_items))))

    def run_one(index: int, call: dict[str, Any]) -> tuple[int, McpCallResult]:
        server_name = str(call.get("server") or "")
        tool_name = str(call.get("tool") or "")
        try:
            arguments_value = call.get("arguments") or {}
            arguments = arguments_value if isinstance(arguments_value, dict) else {}
            result = call_mcp_tool(
                project,
                server_name,
                tool_name,
                arguments,
                approval_id=str(call.get("approval_id") or "") or None,
                owner_approved=bool(call.get("owner_approved", owner_approved)),
                profile=str(call.get("profile") or profile),
                session_id=str(call.get("session_id") or ""),
            )
            return index, result
        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:call_mcp_tools_concurrently", exc)
            error = redact_mcp_error(f"{type(exc).__name__}: {exc}")
            return index, McpCallResult(False, server_name, tool_name, error=error)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(run_one, index, call) for index, call in enumerate(call_items)]
        for future in as_completed(futures):
            index, result = future.result()
            results[index] = result
    return [result if result is not None else McpCallResult(False, "", "", error="missing MCP call result") for result in results]


def render_mcp_servers(servers: list[McpServerConfig]) -> str:
    if not servers:
        return "No MCP servers configured.\n"
    lines = ["# MCP Servers", ""]
    for server in servers:
        state = "enabled" if server.enabled else "disabled"
        lease = f" idle_ttl={server.idle_ttl:g}s" if server.session_scoped else " one-shot"
        env = f" env_whitelist={','.join(server.env_whitelist)}" if server.env_whitelist else ""
        auth = f" auth_profile={server.auth_profile}" if server.auth_profile else ""
        target = server.url if server.transport in {"http", "sse"} else " ".join(server.argv)
        lines.append(f"- [{state}] {server.name}: {server.transport} {target}{lease}{env}{auth}")
    return "\n".join(lines) + "\n"


def render_mcp_tools(catalog: McpCatalog) -> str:
    lines = ["# MCP Tools", ""]
    if not catalog.tools:
        lines.append("No MCP tools discovered.")
    for tool in catalog.tools:
        description = f" - {tool.description}" if tool.description else ""
        lines.append(f"- {tool.server}/{tool.name}{description}")
    if catalog.errors:
        lines.extend(["", "## Errors"])
        lines.extend(f"- {error}" for error in catalog.errors)
    return "\n".join(lines) + "\n"


def build_mcp_schema_snapshot(catalog: McpCatalog) -> McpSchemaSnapshot:
    records = tuple(
        sorted(
            (
                McpToolSchemaRecord(
                    server=tool.server,
                    tool=tool.name,
                    schema_hash=_stable_hash(tool.input_schema),
                    input_schema=tool.input_schema,
                )
                for tool in catalog.tools
            ),
            key=lambda item: (item.server, item.tool),
        )
    )
    snapshot_hash = _stable_hash([{"server": item.server, "tool": item.tool, "schema_hash": item.schema_hash} for item in records])
    return McpSchemaSnapshot(
        schema="quantagent.mcp_schema_snapshot.v1",
        snapshot_hash=snapshot_hash,
        generated_at_ms=_now_ms(),
        tools=records,
    )


def detect_mcp_schema_drift(previous: McpSchemaSnapshot, current: McpSchemaSnapshot) -> McpSchemaDrift:
    previous_tools = {f"{tool.server}/{tool.tool}": tool for tool in previous.tools}
    current_tools = {f"{tool.server}/{tool.tool}": tool for tool in current.tools}
    previous_names = set(previous_tools)
    current_names = set(current_tools)
    shared = previous_names & current_names
    return McpSchemaDrift(
        previous_hash=previous.snapshot_hash,
        current_hash=current.snapshot_hash,
        added=tuple(sorted(current_names - previous_names)),
        removed=tuple(sorted(previous_names - current_names)),
        changed=tuple(sorted(name for name in shared if previous_tools[name].schema_hash != current_tools[name].schema_hash)),
    )


def redact_mcp_error(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(_redacted_secret_match, redacted)
    return redacted[:1000]


def redact_mcp_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            redacted[name] = "[redacted]" if SECRET_KEY_PATTERN.search(name) else redact_mcp_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_mcp_payload(item) for item in value]
    if isinstance(value, tuple):
        return [redact_mcp_payload(item) for item in value]
    if isinstance(value, str):
        return redact_mcp_error(value)
    return value


def _redacted_secret_match(match: re.Match[str]) -> str:
    if not match.lastindex:
        return "[redacted]"
    if match.lastindex >= 2:
        return match.group(1) + match.group(2) + "[redacted]"
    return match.group(1) + "[redacted]"


@dataclass(frozen=True)
class McpPermissionDecision:
    server: str
    tool: str
    action: str
    pattern: str
    reason: str

    @property
    def allowed(self) -> bool:
        return self.action == ALLOW

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"runtime": "mcp"}


def resolve_mcp_permission(config: McpServerConfig, tool: str) -> McpPermissionDecision:
    action = ASK
    matched = "*" if config.permissions else "<default-fail-closed>"
    for pattern, raw_action in config.permissions.items():
        if matches_tool_pattern(tool, pattern):
            action = raw_action
            matched = pattern
    if action not in {ALLOW, ASK, DENY}:
        action = ASK
    return McpPermissionDecision(config.name, tool, action, matched, f"{config.name}/{tool} {action} by MCP permission pattern {matched}")


def apply_mcp_argument_guards(config: McpServerConfig, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    guarded = dict(arguments)
    rules = _matching_guard_rules(config, tool)
    for rule in rules:
        for field in rule.get("deny_fields", []):
            if str(field) in guarded:
                raise PermissionError(f"MCP argument field denied by guard: {field}")
        defaults = rule.get("defaults", {})
        if isinstance(defaults, dict):
            for key, value in defaults.items():
                guarded.setdefault(str(key), value)
        force = rule.get("force", {})
        if isinstance(force, dict):
            for key, value in force.items():
                guarded[str(key)] = value
        must_equal = rule.get("must_equal", {})
        if isinstance(must_equal, dict):
            for key, value in must_equal.items():
                if guarded.get(str(key)) != value:
                    raise PermissionError(f"MCP argument field must equal guarded value: {key}")
    return guarded


def _matching_guard_rules(config: McpServerConfig, tool: str) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for pattern, rule in config.guards.items():
        if matches_tool_pattern(tool, pattern) and isinstance(rule, dict):
            rules.append(rule)
    return rules


def _normalize_permissions(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, str] = {}
    for pattern, action in raw.items():
        text = str(action).strip().lower()
        normalized[str(pattern)] = text if text in {ALLOW, ASK, DENY} else ASK
    return normalized


def _normalize_guards(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    return {str(pattern): value for pattern, value in raw.items() if isinstance(value, dict)}


def _find_server(project: str | Path, name: str) -> McpServerConfig:
    for server in load_mcp_servers(project):
        if server.name == name and server.enabled:
            return server
    raise KeyError(f"MCP server not found or disabled: {name}")


def _mcp_env(config: McpServerConfig) -> dict[str, str]:
    if config.env_whitelist:
        inherited = {key: os.environ[key] for key in config.env_whitelist if key in os.environ}
        inherited_allowlist = tuple(config.env_whitelist)
    else:
        inherited = os.environ.copy()
        inherited_allowlist = ()
    env = sanitize_env(inherited, allowlist=inherited_allowlist)
    env = sanitize_env(env, allowlist=())
    explicit = sanitize_env(config.env, allowlist=())
    env.update(explicit)
    return env


def _stdio_request(config: McpServerConfig, method: str, params: dict[str, Any], *, project: str | Path) -> dict[str, Any]:
    request_id = uuid.uuid4().hex[:10]
    request = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    proc = subprocess.Popen(
        config.argv,
        cwd=Path(project),
        env=_mcp_env(config),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    body = json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n"
    try:
        stdout, stderr = proc.communicate(body, timeout=config.timeout)
        response: dict[str, Any] | None = None
        for line in stdout.splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise RuntimeError("MCP response must be a JSON object")
            if payload.get("id") == request_id:
                response = payload
                break
        if response is None:
            raise RuntimeError(redact_mcp_error(stderr or "empty MCP response"))
        if response.get("error"):
            raise RuntimeError(json.dumps(response["error"], ensure_ascii=False, sort_keys=True))
        return response
    finally:
        _terminate(proc)


def _transport_request(config: McpServerConfig, method: str, params: dict[str, Any], *, project: str | Path) -> dict[str, Any]:
    if config.transport in {"http", "sse"}:
        return _http_request(config, method, params)
    return _stdio_request(config, method, params, project=project)


def _write_mcp_lease(project: str | Path, config: McpServerConfig, session: McpSession, *, status: str) -> Path:
    pid = session.proc.pid if session.proc else None
    record = _build_mcp_lease_record(project, config, status=status, pid=pid, session_id=session.session_id)
    return _write_mcp_lease_record(project, record)


def _write_mcp_remote_lease(project: str | Path, config: McpServerConfig, *, status: str, session_id: str = "") -> Path:
    record = _build_mcp_lease_record(project, config, status=status, endpoint=config.url if config.transport in {"http", "sse"} else "", session_id=session_id)
    return _write_mcp_lease_record(project, record)


def _write_mcp_lease_record(project: str | Path, record: McpLeaseRecord) -> Path:
    path = mcp_lease_dir(project) / f"{record.lease_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _sync_mcp_lease_registry(project, _read_mcp_leases(project))
    return path


def _build_mcp_lease_record(
    project: str | Path,
    config: McpServerConfig,
    *,
    status: str,
    pid: int | None = None,
    endpoint: str = "",
    session_id: str = "",
) -> McpLeaseRecord:
    now = _now_ms()
    normalized_session_id = _normalize_mcp_session_id(session_id)
    lease_id = _mcp_lease_id(config.name, normalized_session_id)
    previous = _read_mcp_lease(project, lease_id)
    created = previous.created_at_ms if previous else now
    started = previous.started_at_ms if previous else now
    return McpLeaseRecord(
        lease_id=lease_id,
        server=config.name,
        project=str(Path(project).expanduser().resolve(strict=False)),
        transport=config.transport,
        auth_profile=config.auth_profile,
        created_at_ms=created,
        started_at_ms=started,
        last_used_at_ms=now,
        idle_ttl=config.idle_ttl,
        status=status,
        pid=pid,
        endpoint=redact_mcp_error(endpoint),
        header_names=sorted(config.headers.keys()),
        session_id=normalized_session_id,
        scope="session" if normalized_session_id else "global",
        env_names=sorted(config.env.keys()),
    )


def _read_mcp_lease(project: str | Path, lease_id: str) -> McpLeaseRecord | None:
    path = mcp_lease_dir(project) / f"{lease_id}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return _lease_from_payload(payload)


def _read_mcp_leases(project: str | Path) -> list[McpLeaseRecord]:
    directory = mcp_lease_dir(project)
    if not directory.exists():
        return []
    leases: list[McpLeaseRecord] = []
    for path in sorted(directory.glob("lease-*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        lease = _lease_from_payload(payload)
        if lease:
            leases.append(lease)
    return leases


def _lease_from_payload(payload: Any) -> McpLeaseRecord | None:
    if not isinstance(payload, dict):
        return None
    now = _now_ms()
    lease_id = str(payload.get("lease_id") or "")
    server = str(payload.get("server") or "")
    if not lease_id or not server:
        return None
    created = int(payload.get("created_at_ms") or payload.get("started_at_ms") or now)
    header_names = payload.get("header_names", [])
    session_id = _normalize_mcp_session_id(payload.get("session_id") or "")
    env_names = payload.get("env_names", [])
    return McpLeaseRecord(
        lease_id=lease_id,
        server=server,
        project=str(payload.get("project") or ""),
        transport=str(payload.get("transport") or "stdio"),
        auth_profile=str(payload.get("auth_profile") or ""),
        created_at_ms=created,
        started_at_ms=int(payload.get("started_at_ms") or created),
        last_used_at_ms=int(payload.get("last_used_at_ms") or created),
        idle_ttl=float(payload.get("idle_ttl") or 0.0),
        status=str(payload.get("status") or "unknown"),
        pid=int(payload["pid"]) if payload.get("pid") is not None else None,
        endpoint=str(payload.get("endpoint") or ""),
        header_names=[str(item) for item in header_names] if isinstance(header_names, list) else [],
        session_id=session_id,
        scope=str(payload.get("scope") or ("session" if session_id else "global")),
        env_names=[str(item) for item in env_names] if isinstance(env_names, list) else [],
    )


def _sync_mcp_lease_registry(project: str | Path, leases: list[McpLeaseRecord]) -> Path:
    path = mcp_lease_registry_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "quantagent.mcp_leases.v1",
        "updated_at_ms": _now_ms(),
        "note": "Persistent lease registry only; no external MCP daemon process is implied.",
        "leases": [lease.to_dict() for lease in sorted(leases, key=lambda item: (item.server, item.session_id, item.lease_id))],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _normalize_mcp_session_id(session_id: object) -> str:
    text = str(session_id or "").strip()
    if not text:
        return ""
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", text)[:80]


def _validate_mcp_session_id(session_id: object) -> None:
    text = str(session_id or "").strip()
    if not text:
        return
    if text in {".", ".."} or _normalize_mcp_session_id(text) != text:
        raise PermissionError("invalid MCP session id")


def _mcp_lease_id(server: str, session_id: str = "") -> str:
    if not session_id:
        return f"lease-{server}"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", session_id)[:80]
    return f"lease-{server}-{safe}"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _http_request(config: McpServerConfig, method: str, params: dict[str, Any]) -> dict[str, Any]:
    request = {"jsonrpc": "2.0", "id": uuid.uuid4().hex[:10], "method": method, "params": params}
    data = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **config.headers}
    http_request = urllib.request.Request(config.url, data=data, headers=headers, method="POST")
    try:
        with _open_http_request(http_request, config) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(redact_mcp_error(f"HTTP {exc.code}: {body}")) from exc
    if config.transport == "sse" or body.lstrip().startswith("event:") or "\ndata:" in body[:200]:
        body = _extract_sse_json(body)
    response_payload = json.loads(body)
    if not isinstance(response_payload, dict):
        raise RuntimeError("MCP HTTP response must be a JSON object")
    if response_payload.get("error"):
        raise RuntimeError(json.dumps(response_payload["error"], ensure_ascii=False, sort_keys=True))
    return response_payload


def _open_http_request(http_request: urllib.request.Request, config: McpServerConfig) -> Any:
    # macOS system proxies can incorrectly route 127.0.0.1 MCP calls through a
    # user proxy. Local MCP transports must stay direct.
    if _is_loopback_url(config.url):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(http_request, timeout=config.timeout)
    try:
        return urllib.request.urlopen(http_request, timeout=config.timeout)
    except http.client.RemoteDisconnected:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(http_request, timeout=config.timeout)


def _is_loopback_url(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _extract_sse_json(body: str) -> str:
    data_lines: list[str] = []
    for line in body.splitlines():
        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())
    if not data_lines:
        return body
    return "\n".join(data_lines)


def _response_result(response: dict[str, Any]) -> Any:
    return response.get("result", {})


def _terminate(proc: subprocess.Popen[str]) -> None:
    try:
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=1)
            except Exception:
                proc.kill()
    finally:
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if stream:
                    stream.close()
            except Exception as exc:
                audit_suppressed_exception(f"{__name__}:1077", exc)
                pass


def _checkpoint_before_mcp_tool(project: str | Path, server: str, tool: str, arguments: dict[str, Any]) -> str:
    paths: list[str] = []
    for key in ("path", "paths", "file", "files", "target", "targets"):
        value = arguments.get(key)
        if isinstance(value, str) and value:
            paths.append(value)
        elif isinstance(value, list):
            paths.extend(str(item) for item in value if isinstance(item, (str, Path)) and str(item))
    if not paths:
        return ""
    try:
        return create_checkpoint(project, sorted(set(paths)), reason=f"before mcp tool: {server}/{tool}").checkpoint_id
    except (OSError, ValueError):
        return ""


def _result_preview(result: Any, *, limit: int = 3000) -> str:
    redacted = redact_mcp_payload(result)
    text = json.dumps(redacted, ensure_ascii=False, sort_keys=True) if not isinstance(redacted, str) else redacted
    return text if len(text) <= limit else text[: limit - 12] + "\n[trimmed]"


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
