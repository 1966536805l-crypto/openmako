from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import json
import os
import socket
import tempfile
import threading
import time
import uuid
from hashlib import sha256
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .mcp_runtime import (
    McpCallResult,
    McpCatalog,
    McpLeaseRecord,
    call_mcp_tool,
    list_mcp_catalog,
    list_mcp_leases,
    load_mcp_servers,
    redact_mcp_error,
    stop_mcp_daemon_state,
)


MCP_DAEMON_VERSION = 1


@dataclass(frozen=True)
class McpDaemonConfig:
    project: str
    state_file: str = ""
    pid_file: str = ""
    socket_path: str = ""
    catalog_cache_file: str = ""
    calls_file: str = ""
    lease_ttl_seconds: float = 300.0

    @classmethod
    def for_project(cls, project: str | Path) -> "McpDaemonConfig":
        project_path = Path(project).expanduser().resolve(strict=False)
        directory = mcp_daemon_dir(project_path)
        return cls(
            project=str(project_path),
            state_file=str(directory / "state.json"),
            pid_file=str(directory / "daemon.pid"),
            socket_path=str(_short_socket_path(project_path)),
            catalog_cache_file=str(directory / "catalog.json"),
            calls_file=str(directory / "calls.jsonl"),
        )

    def resolved(self) -> "McpDaemonConfig":
        defaults = McpDaemonConfig.for_project(self.project)
        return McpDaemonConfig(
            project=str(Path(self.project).expanduser().resolve(strict=False)),
            state_file=self.state_file or defaults.state_file,
            pid_file=self.pid_file or defaults.pid_file,
            socket_path=self.socket_path or defaults.socket_path,
            catalog_cache_file=self.catalog_cache_file or defaults.catalog_cache_file,
            calls_file=self.calls_file or defaults.calls_file,
            lease_ttl_seconds=self.lease_ttl_seconds,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class McpDaemonCallRecord:
    call_id: str
    server: str
    tool: str
    ok: bool
    started_at_ms: int
    duration_ms: int
    invocation_id: str = ""
    approval_id: str = ""
    error: str = ""
    args_preview: str = ""
    result_preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class McpDaemonState:
    daemon_id: str
    project: str
    status: str
    pid: int | None
    socket_path: str
    state_file: str
    pid_file: str
    catalog_cache_file: str
    calls_file: str
    started_at_ms: int
    updated_at_ms: int
    catalog_cached_at_ms: int = 0
    catalog_tools: int = 0
    call_records: int = 0
    leases: list[McpLeaseRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    note: str = "external MCP daemon state; tests may run it in the current process"

    def to_dict(self) -> dict[str, Any]:
        return {
            "daemon_id": self.daemon_id,
            "project": self.project,
            "status": self.status,
            "pid": self.pid,
            "socket_path": self.socket_path,
            "state_file": self.state_file,
            "pid_file": self.pid_file,
            "catalog_cache_file": self.catalog_cache_file,
            "calls_file": self.calls_file,
            "started_at_ms": self.started_at_ms,
            "updated_at_ms": self.updated_at_ms,
            "catalog_cached_at_ms": self.catalog_cached_at_ms,
            "catalog_tools": self.catalog_tools,
            "call_records": self.call_records,
            "leases": [lease.to_dict() for lease in self.leases],
            "errors": self.errors,
            "note": self.note,
        }


@dataclass(frozen=True)
class McpDaemonRequest:
    method: str
    params: dict[str, Any] = field(default_factory=dict)
    request_id: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "McpDaemonRequest":
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        return cls(method=str(payload.get("method") or payload.get("op") or ""), params=params, request_id=str(payload.get("id") or payload.get("request_id") or ""))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.request_id, "method": self.method, "params": self.params}


@dataclass(frozen=True)
class McpDaemonResponse:
    ok: bool
    result: Any = None
    error: str = ""
    request_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = {"ok": self.ok}
        if self.request_id:
            payload["id"] = self.request_id
        if self.ok:
            payload["result"] = self.result
        else:
            payload["error"] = redact_mcp_error(self.error)
        return payload


class McpDaemon:
    def __init__(self, config: McpDaemonConfig | str | Path) -> None:
        if isinstance(config, McpDaemonConfig):
            self.config = config.resolved()
        else:
            self.config = McpDaemonConfig.for_project(config)
        self._shutdown = threading.Event()
        self._server_socket: socket.socket | None = None

    def start(self) -> McpDaemonState:
        return start_mcp_daemon(self.config)

    def status(self) -> McpDaemonState:
        return status_mcp_daemon(self.config)

    def stop(self) -> McpDaemonState:
        self._shutdown.set()
        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                pass
        return stop_mcp_daemon(self.config)

    def restart(self) -> McpDaemonState:
        stop_mcp_daemon(self.config)
        return start_mcp_daemon(self.config)

    def recover(self) -> McpDaemonState:
        return recover_mcp_daemon(self.config)

    def handle_request(self, request: McpDaemonRequest | dict[str, Any]) -> McpDaemonResponse:
        req = request if isinstance(request, McpDaemonRequest) else McpDaemonRequest.from_dict(request)
        try:
            if req.method == "status":
                return McpDaemonResponse(True, self.status().to_dict(), request_id=req.request_id)
            if req.method == "catalog":
                catalog = daemon_catalog(self.config, refresh=bool(req.params.get("refresh", False)))
                return McpDaemonResponse(True, catalog, request_id=req.request_id)
            if req.method == "call":
                result = daemon_call(
                    self.config,
                    server=str(req.params.get("server") or ""),
                    tool=str(req.params.get("tool") or ""),
                    arguments=req.params.get("arguments") if isinstance(req.params.get("arguments"), dict) else {},
                    approval_id=str(req.params.get("approval_id") or ""),
                    owner_approved=bool(req.params.get("owner_approved", False)),
                    profile=str(req.params.get("profile") or ""),
                )
                return McpDaemonResponse(True, result, request_id=req.request_id)
            if req.method == "shutdown":
                state = self.stop()
                return McpDaemonResponse(True, state.to_dict(), request_id=req.request_id)
            return McpDaemonResponse(False, error=f"unknown MCP daemon request: {req.method}", request_id=req.request_id)
        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:217", exc)
            return McpDaemonResponse(False, error=f"{type(exc).__name__}: {exc}", request_id=req.request_id)

    def serve_forever(self) -> None:
        state = self.start()
        socket_path = Path(state.socket_path)
        socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            socket_path.unlink()
        except FileNotFoundError:
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_socket = server
        server.bind(str(socket_path))
        server.listen(8)
        server.settimeout(0.1)
        _write_state(self.config, _state_with_status(status_mcp_daemon(self.config), "running", pid=os.getpid()))
        while not self._shutdown.is_set():
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                self._handle_socket_connection(conn)
        try:
            server.close()
        except OSError:
            pass
        self._server_socket = None

    def _handle_socket_connection(self, conn: socket.socket) -> None:
        stream = conn.makefile("rwb")
        for raw in stream:
            if not raw.strip():
                continue
            try:
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("request must be a JSON object")
                response = self.handle_request(payload)
            except Exception as exc:
                response = McpDaemonResponse(False, error=f"{type(exc).__name__}: {exc}")
            body = json.dumps(response.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
            stream.write(body.encode("utf-8"))
            stream.flush()
            if response.ok and isinstance(response.result, dict) and response.result.get("status") == "stopped":
                break


def mcp_daemon_dir(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "mcp_daemon"


def mcp_daemon_state_path(project: str | Path) -> Path:
    return mcp_daemon_dir(project) / "state.json"


def mcp_daemon_pid_path(project: str | Path) -> Path:
    return mcp_daemon_dir(project) / "daemon.pid"


def mcp_daemon_socket_path(project: str | Path) -> Path:
    return _short_socket_path(Path(project).expanduser().resolve(strict=False))


def mcp_daemon_catalog_cache_path(project: str | Path) -> Path:
    return mcp_daemon_dir(project) / "catalog.json"


def mcp_daemon_calls_path(project: str | Path) -> Path:
    return mcp_daemon_dir(project) / "calls.jsonl"


def start_mcp_daemon(config: McpDaemonConfig | str | Path) -> McpDaemonState:
    cfg = _config(config)
    previous = load_mcp_daemon_state(cfg, missing_ok=True)
    now = _now_ms()
    Path(cfg.state_file).parent.mkdir(parents=True, exist_ok=True)
    Path(cfg.pid_file).write_text(f"{os.getpid()}\n", encoding="utf-8")
    state = McpDaemonState(
        daemon_id=previous.daemon_id if previous else "mcp-daemon-" + uuid.uuid4().hex[:12],
        project=cfg.project,
        status="running",
        pid=os.getpid(),
        socket_path=cfg.socket_path,
        state_file=cfg.state_file,
        pid_file=cfg.pid_file,
        catalog_cache_file=cfg.catalog_cache_file,
        calls_file=cfg.calls_file,
        started_at_ms=previous.started_at_ms if previous and previous.status == "running" else now,
        updated_at_ms=now,
        catalog_cached_at_ms=_catalog_cached_at_ms(cfg),
        catalog_tools=len(_load_catalog_cache(cfg).get("tools", [])),
        call_records=len(load_mcp_daemon_calls(cfg)),
        leases=_safe_leases(cfg),
    )
    _write_state(cfg, state)
    return state


def status_mcp_daemon(config: McpDaemonConfig | str | Path) -> McpDaemonState:
    cfg = _config(config)
    state = load_mcp_daemon_state(cfg, missing_ok=True)
    if state is None:
        return McpDaemonState(
            daemon_id="",
            project=cfg.project,
            status="missing",
            pid=None,
            socket_path=cfg.socket_path,
            state_file=cfg.state_file,
            pid_file=cfg.pid_file,
            catalog_cache_file=cfg.catalog_cache_file,
            calls_file=cfg.calls_file,
            started_at_ms=0,
            updated_at_ms=_now_ms(),
            errors=["daemon state is missing"],
        )
    errors = list(state.errors)
    pid = _read_pid(cfg)
    status = state.status
    if status == "running" and pid is None:
        status = "stale"
        errors.append("pid file is missing or invalid")
    return McpDaemonState(
        daemon_id=state.daemon_id,
        project=cfg.project,
        status=status,
        pid=pid if status in {"running", "stale"} else None,
        socket_path=cfg.socket_path,
        state_file=cfg.state_file,
        pid_file=cfg.pid_file,
        catalog_cache_file=cfg.catalog_cache_file,
        calls_file=cfg.calls_file,
        started_at_ms=state.started_at_ms,
        updated_at_ms=_now_ms(),
        catalog_cached_at_ms=_catalog_cached_at_ms(cfg),
        catalog_tools=len(_load_catalog_cache(cfg).get("tools", [])),
        call_records=len(load_mcp_daemon_calls(cfg)),
        leases=_safe_leases(cfg),
        errors=errors,
    )


def stop_mcp_daemon(config: McpDaemonConfig | str | Path) -> McpDaemonState:
    cfg = _config(config)
    previous = load_mcp_daemon_state(cfg, missing_ok=True)
    try:
        Path(cfg.pid_file).unlink()
    except FileNotFoundError:
        pass
    try:
        if Path(cfg.socket_path).exists():
            Path(cfg.socket_path).unlink()
    except OSError:
        pass
    stop_mcp_daemon_state(cfg.project)
    now = _now_ms()
    state = McpDaemonState(
        daemon_id=previous.daemon_id if previous else "mcp-daemon-" + uuid.uuid4().hex[:12],
        project=cfg.project,
        status="stopped",
        pid=None,
        socket_path=cfg.socket_path,
        state_file=cfg.state_file,
        pid_file=cfg.pid_file,
        catalog_cache_file=cfg.catalog_cache_file,
        calls_file=cfg.calls_file,
        started_at_ms=previous.started_at_ms if previous else now,
        updated_at_ms=now,
        catalog_cached_at_ms=_catalog_cached_at_ms(cfg),
        catalog_tools=len(_load_catalog_cache(cfg).get("tools", [])),
        call_records=len(load_mcp_daemon_calls(cfg)),
        leases=_safe_leases(cfg),
    )
    _write_state(cfg, state)
    return state


def restart_mcp_daemon(config: McpDaemonConfig | str | Path) -> McpDaemonState:
    stop_mcp_daemon(config)
    return start_mcp_daemon(config)


def recover_mcp_daemon(config: McpDaemonConfig | str | Path) -> McpDaemonState:
    cfg = _config(config)
    state = load_mcp_daemon_state(cfg, missing_ok=True)
    if state is None:
        return start_mcp_daemon(cfg)
    if state.status == "running" and _read_pid(cfg) is None:
        return start_mcp_daemon(cfg)
    recovered = status_mcp_daemon(cfg)
    _write_state(cfg, recovered)
    return recovered


def load_mcp_daemon_state(config: McpDaemonConfig | str | Path, *, missing_ok: bool = False) -> McpDaemonState | None:
    cfg = _config(config)
    path = Path(cfg.state_file)
    if not path.exists():
        if missing_ok:
            return None
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _state_from_dict(payload, cfg)


def daemon_catalog(config: McpDaemonConfig | str | Path, *, refresh: bool = False) -> dict[str, Any]:
    cfg = _config(config)
    cached = _load_catalog_cache(cfg)
    if cached and not refresh:
        return cached
    try:
        catalog = list_mcp_catalog(cfg.project)
        payload = _catalog_to_payload(catalog, project=cfg.project)
    except Exception as exc:
        payload = {
            "version": MCP_DAEMON_VERSION,
            "project": cfg.project,
            "cached_at_ms": _now_ms(),
            "servers": [asdict(server) for server in load_mcp_servers(cfg.project)],
            "tools": [],
            "errors": [redact_mcp_error(f"{type(exc).__name__}: {exc}")],
        }
    Path(cfg.catalog_cache_file).parent.mkdir(parents=True, exist_ok=True)
    Path(cfg.catalog_cache_file).write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_state(cfg, status_mcp_daemon(cfg))
    return payload


def daemon_call(
    config: McpDaemonConfig | str | Path,
    *,
    server: str,
    tool: str,
    arguments: dict[str, Any] | None = None,
    approval_id: str = "",
    owner_approved: bool = False,
    profile: str = "",
) -> dict[str, Any]:
    cfg = _config(config)
    started = _now_ms()
    if not server or not tool:
        raise ValueError("server and tool are required")
    result = call_mcp_tool(
        cfg.project,
        server,
        tool,
        arguments or {},
        approval_id=approval_id or None,
        owner_approved=owner_approved,
        profile=profile,
    )
    record = _call_record_from_result(result, arguments or {}, started_at_ms=started)
    append_mcp_daemon_call(cfg, record)
    _write_state(cfg, status_mcp_daemon(cfg))
    return result.to_dict() | {"call_id": record.call_id}


def append_mcp_daemon_call(config: McpDaemonConfig | str | Path, record: McpDaemonCallRecord) -> Path:
    cfg = _config(config)
    path = Path(cfg.calls_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    return path


def load_mcp_daemon_calls(config: McpDaemonConfig | str | Path, *, limit: int = 1000) -> list[McpDaemonCallRecord]:
    cfg = _config(config)
    path = Path(cfg.calls_file)
    if not path.exists():
        return []
    rows: list[McpDaemonCallRecord] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(_call_record_from_dict(payload))
    return rows[-max(0, limit) :]


def request_mcp_daemon(config: McpDaemonConfig | str | Path, method: str, params: dict[str, Any] | None = None, *, timeout: float = 3.0) -> McpDaemonResponse:
    cfg = _config(config)
    request_id = "req-" + uuid.uuid4().hex[:10]
    body = json.dumps({"id": request_id, "method": method, "params": params or {}}, ensure_ascii=False, sort_keys=True) + "\n"
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(cfg.socket_path)
        client.sendall(body.encode("utf-8"))
        data = b""
        while not data.endswith(b"\n"):
            chunk = client.recv(65536)
            if not chunk:
                break
            data += chunk
    finally:
        client.close()
    payload = json.loads(data.decode("utf-8"))
    if payload.get("ok"):
        return McpDaemonResponse(True, payload.get("result"), request_id=str(payload.get("id") or request_id))
    return McpDaemonResponse(False, error=str(payload.get("error") or ""), request_id=str(payload.get("id") or request_id))


def _config(config: McpDaemonConfig | str | Path) -> McpDaemonConfig:
    return config.resolved() if isinstance(config, McpDaemonConfig) else McpDaemonConfig.for_project(config)


def _write_state(config: McpDaemonConfig, state: McpDaemonState) -> Path:
    path = Path(config.state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _state_from_dict(payload: dict[str, Any], config: McpDaemonConfig) -> McpDaemonState:
    leases = [_lease_from_dict(item) for item in payload.get("leases", []) if isinstance(item, dict)]
    return McpDaemonState(
        daemon_id=str(payload.get("daemon_id") or ""),
        project=str(payload.get("project") or config.project),
        status=str(payload.get("status") or "unknown"),
        pid=int(payload["pid"]) if payload.get("pid") is not None else None,
        socket_path=str(payload.get("socket_path") or config.socket_path),
        state_file=str(payload.get("state_file") or config.state_file),
        pid_file=str(payload.get("pid_file") or config.pid_file),
        catalog_cache_file=str(payload.get("catalog_cache_file") or config.catalog_cache_file),
        calls_file=str(payload.get("calls_file") or config.calls_file),
        started_at_ms=int(payload.get("started_at_ms") or 0),
        updated_at_ms=int(payload.get("updated_at_ms") or 0),
        catalog_cached_at_ms=int(payload.get("catalog_cached_at_ms") or 0),
        catalog_tools=int(payload.get("catalog_tools") or 0),
        call_records=int(payload.get("call_records") or 0),
        leases=leases,
        errors=[redact_mcp_error(str(error)) for error in payload.get("errors", [])],
        note=str(payload.get("note") or "external MCP daemon state; tests may run it in the current process"),
    )


def _state_with_status(state: McpDaemonState, status: str, *, pid: int | None) -> McpDaemonState:
    return McpDaemonState(
        daemon_id=state.daemon_id,
        project=state.project,
        status=status,
        pid=pid,
        socket_path=state.socket_path,
        state_file=state.state_file,
        pid_file=state.pid_file,
        catalog_cache_file=state.catalog_cache_file,
        calls_file=state.calls_file,
        started_at_ms=state.started_at_ms,
        updated_at_ms=_now_ms(),
        catalog_cached_at_ms=state.catalog_cached_at_ms,
        catalog_tools=state.catalog_tools,
        call_records=state.call_records,
        leases=state.leases,
        errors=state.errors,
    )


def _catalog_to_payload(catalog: McpCatalog, *, project: str) -> dict[str, Any]:
    return {
        "version": MCP_DAEMON_VERSION,
        "project": project,
        "cached_at_ms": _now_ms(),
        "servers": [asdict(server) for server in catalog.servers],
        "tools": [asdict(tool) for tool in catalog.tools],
        "errors": [redact_mcp_error(error) for error in catalog.errors],
    }


def _load_catalog_cache(config: McpDaemonConfig) -> dict[str, Any]:
    path = Path(config.catalog_cache_file)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    payload["errors"] = [redact_mcp_error(str(error)) for error in payload.get("errors", [])]
    return payload


def _catalog_cached_at_ms(config: McpDaemonConfig) -> int:
    cached = _load_catalog_cache(config)
    return int(cached.get("cached_at_ms") or 0)


def _call_record_from_result(result: McpCallResult, arguments: dict[str, Any], *, started_at_ms: int) -> McpDaemonCallRecord:
    return McpDaemonCallRecord(
        call_id="mcpd-call-" + uuid.uuid4().hex[:12],
        server=result.server,
        tool=result.tool,
        ok=result.ok,
        started_at_ms=started_at_ms,
        duration_ms=result.duration_ms,
        invocation_id=result.invocation_id,
        approval_id=result.approval_id,
        error=redact_mcp_error(result.error),
        args_preview=_json_preview(arguments),
        result_preview=_json_preview(result.result),
    )


def _call_record_from_dict(payload: dict[str, Any]) -> McpDaemonCallRecord:
    return McpDaemonCallRecord(
        call_id=str(payload.get("call_id") or ""),
        server=str(payload.get("server") or ""),
        tool=str(payload.get("tool") or ""),
        ok=bool(payload.get("ok")),
        started_at_ms=int(payload.get("started_at_ms") or 0),
        duration_ms=int(payload.get("duration_ms") or 0),
        invocation_id=str(payload.get("invocation_id") or ""),
        approval_id=str(payload.get("approval_id") or ""),
        error=redact_mcp_error(str(payload.get("error") or "")),
        args_preview=redact_mcp_error(str(payload.get("args_preview") or "")),
        result_preview=redact_mcp_error(str(payload.get("result_preview") or "")),
    )


def _lease_from_dict(payload: dict[str, Any]) -> McpLeaseRecord:
    return McpLeaseRecord(
        lease_id=str(payload.get("lease_id") or ""),
        server=str(payload.get("server") or ""),
        project=str(payload.get("project") or ""),
        transport=str(payload.get("transport") or ""),
        auth_profile=str(payload.get("auth_profile") or ""),
        created_at_ms=int(payload.get("created_at_ms") or 0),
        started_at_ms=int(payload.get("started_at_ms") or 0),
        last_used_at_ms=int(payload.get("last_used_at_ms") or 0),
        idle_ttl=float(payload.get("idle_ttl") or 0),
        status=str(payload.get("status") or ""),
        pid=int(payload["pid"]) if payload.get("pid") is not None else None,
        endpoint=redact_mcp_error(str(payload.get("endpoint") or "")),
        header_names=[str(value) for value in payload.get("header_names", [])],
    )


def _safe_leases(config: McpDaemonConfig) -> list[McpLeaseRecord]:
    try:
        return list_mcp_leases(config.project)
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:666", exc)
        return []


def _read_pid(config: McpDaemonConfig) -> int | None:
    try:
        text = Path(config.pid_file).read_text(encoding="utf-8").strip()
        return int(text) if text else None
    except (OSError, ValueError):
        return None


def _json_preview(value: Any, *, limit: int = 1200) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = str(value)
    text = redact_mcp_error(text)
    return text if len(text) <= limit else text[: limit - 18] + "...[truncated]"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _short_socket_path(project: Path) -> Path:
    digest = sha256(str(project).encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"quantagent-mcp-{digest}.sock"
