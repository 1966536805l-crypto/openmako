from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .mcp_runtime import (
    McpCatalog,
    McpCallResult,
    McpLeaseRecord,
    call_mcp_tool,
    list_mcp_catalog,
    list_mcp_leases,
    load_mcp_servers,
    mcp_lease_registry_path,
    redact_mcp_error,
    start_mcp_daemon_state,
    status_mcp_daemon_state,
    stop_mcp_daemon_state,
)


GATEWAY_VERSION = 1


@dataclass(frozen=True)
class GatewayToolRecord:
    server: str
    name: str
    description: str = ""
    policy_action: str = "ask"
    input_schema: dict[str, Any] = field(default_factory=dict)
    discovered_at_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GatewayCallRecord:
    call_id: str
    server: str
    tool: str
    ok: bool
    started_at_ms: int
    duration_ms: int
    invocation_id: str = ""
    approval_id: str = ""
    error: str = ""
    result_preview: str = ""
    args_preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GatewayServerState:
    name: str
    transport: str
    enabled: bool
    status: str = "configured"
    tools: int = 0
    leases: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class McpGatewayState:
    gateway_id: str
    project: str
    status: str
    generated_at_ms: int
    servers: list[GatewayServerState] = field(default_factory=list)
    tools: list[GatewayToolRecord] = field(default_factory=list)
    leases: list[McpLeaseRecord] = field(default_factory=list)
    recent_calls: list[GatewayCallRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    note: str = "persistent MCP gateway registry; runtime calls still execute through configured MCP transports"

    def to_dict(self) -> dict[str, Any]:
        return {
            "gateway_id": self.gateway_id,
            "project": self.project,
            "status": self.status,
            "generated_at_ms": self.generated_at_ms,
            "servers": [item.to_dict() for item in self.servers],
            "tools": [item.to_dict() for item in self.tools],
            "leases": [item.to_dict() for item in self.leases],
            "recent_calls": [item.to_dict() for item in self.recent_calls],
            "errors": self.errors,
            "note": self.note,
        }


@dataclass(frozen=True)
class GatewayHealth:
    ok: bool
    status: str
    servers: int
    tools: int
    leases: int
    calls: int
    errors: list[str] = field(default_factory=list)
    gateway_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def gateway_dir(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "mcp_gateway"


def gateway_state_path(project: str | Path) -> Path:
    return gateway_dir(project) / "gateway.json"


def gateway_calls_path(project: str | Path) -> Path:
    return gateway_dir(project) / "calls.jsonl"


def start_mcp_gateway(project: str | Path, *, discover: bool = True, server: str | None = None) -> McpGatewayState:
    project_path = Path(project).expanduser().resolve(strict=False)
    start_mcp_daemon_state(project_path, server=server)
    return refresh_mcp_gateway(project_path, discover=discover, server=server, status="running")


def stop_mcp_gateway(project: str | Path, *, server: str | None = None) -> McpGatewayState:
    project_path = Path(project).expanduser().resolve(strict=False)
    stop_mcp_daemon_state(project_path, server=server)
    return refresh_mcp_gateway(project_path, discover=False, server=server, status="stopped")


def refresh_mcp_gateway(
    project: str | Path,
    *,
    discover: bool = True,
    server: str | None = None,
    status: str = "ready",
) -> McpGatewayState:
    project_path = Path(project).expanduser().resolve(strict=False)
    previous = load_mcp_gateway(project_path, missing_ok=True)
    configs = [config for config in load_mcp_servers(project_path) if not server or config.name == server]
    catalog = _safe_catalog(project_path, server=server) if discover else McpCatalog(configs, [], [])
    leases = list_mcp_leases(project_path, server=server)
    tools = [
        GatewayToolRecord(
            server=tool.server,
            name=tool.name,
            description=tool.description,
            policy_action=tool.policy_action,
            input_schema=tool.input_schema,
            discovered_at_ms=_now_ms(),
        )
        for tool in catalog.tools
    ]
    errors = [redact_mcp_error(error) for error in catalog.errors]
    server_states = _server_states(configs, tools, leases, errors)
    state = McpGatewayState(
        gateway_id=previous.gateway_id if previous else "mcp-gateway-" + uuid.uuid4().hex[:12],
        project=str(project_path),
        status=status,
        generated_at_ms=_now_ms(),
        servers=server_states,
        tools=tools,
        leases=leases,
        recent_calls=load_gateway_calls(project_path, limit=20),
        errors=errors,
    )
    write_mcp_gateway(project_path, state)
    return state


def load_mcp_gateway(project: str | Path, *, missing_ok: bool = False) -> McpGatewayState | None:
    path = gateway_state_path(project)
    if not path.exists():
        if missing_ok:
            return None
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    servers = [
        GatewayServerState(
            name=str(item.get("name") or ""),
            transport=str(item.get("transport") or ""),
            enabled=bool(item.get("enabled", True)),
            status=str(item.get("status") or "configured"),
            tools=int(item.get("tools") or 0),
            leases=int(item.get("leases") or 0),
            errors=[str(value) for value in item.get("errors", [])],
        )
        for item in payload.get("servers", [])
        if isinstance(item, dict)
    ]
    tools = [
        GatewayToolRecord(
            server=str(item.get("server") or ""),
            name=str(item.get("name") or ""),
            description=str(item.get("description") or ""),
            policy_action=str(item.get("policy_action") or "ask"),
            input_schema=item.get("input_schema") if isinstance(item.get("input_schema"), dict) else {},
            discovered_at_ms=int(item.get("discovered_at_ms") or 0),
        )
        for item in payload.get("tools", [])
        if isinstance(item, dict)
    ]
    leases = [
        McpLeaseRecord(
            lease_id=str(item.get("lease_id") or ""),
            server=str(item.get("server") or ""),
            project=str(item.get("project") or project),
            transport=str(item.get("transport") or ""),
            auth_profile=str(item.get("auth_profile") or ""),
            created_at_ms=int(item.get("created_at_ms") or 0),
            started_at_ms=int(item.get("started_at_ms") or 0),
            last_used_at_ms=int(item.get("last_used_at_ms") or 0),
            idle_ttl=float(item.get("idle_ttl") or 0),
            status=str(item.get("status") or "active"),
            pid=int(item["pid"]) if item.get("pid") is not None else None,
            endpoint=str(item.get("endpoint") or ""),
            header_names=[str(value) for value in item.get("header_names", [])],
        )
        for item in payload.get("leases", [])
        if isinstance(item, dict)
    ]
    recent_calls = [_call_record_from_dict(item) for item in payload.get("recent_calls", []) if isinstance(item, dict)]
    return McpGatewayState(
        gateway_id=str(payload.get("gateway_id") or ""),
        project=str(payload.get("project") or project),
        status=str(payload.get("status") or "unknown"),
        generated_at_ms=int(payload.get("generated_at_ms") or 0),
        servers=servers,
        tools=tools,
        leases=leases,
        recent_calls=recent_calls,
        errors=[str(value) for value in payload.get("errors", [])],
        note=str(payload.get("note") or "persistent MCP gateway registry; runtime calls still execute through configured MCP transports"),
    )


def write_mcp_gateway(project: str | Path, state: McpGatewayState) -> Path:
    path = gateway_state_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def gateway_call_tool(
    project: str | Path,
    server: str,
    tool: str,
    arguments: dict[str, Any] | None = None,
    *,
    approval_id: str | None = None,
    owner_approved: bool = False,
    profile: str = "",
) -> GatewayCallRecord:
    project_path = Path(project).expanduser().resolve(strict=False)
    started = _now_ms()
    result = call_mcp_tool(
        project_path,
        server,
        tool,
        arguments or {},
        approval_id=approval_id,
        owner_approved=owner_approved,
        profile=profile,
    )
    record = gateway_call_record_from_result(result, arguments or {}, started_at_ms=started)
    append_gateway_call(project_path, record)
    refresh_mcp_gateway(project_path, discover=False, status="running")
    return record


def gateway_call_record_from_result(result: McpCallResult, arguments: dict[str, Any], *, started_at_ms: int | None = None) -> GatewayCallRecord:
    return GatewayCallRecord(
        call_id="gw-call-" + uuid.uuid4().hex[:12],
        server=result.server,
        tool=result.tool,
        ok=result.ok,
        started_at_ms=started_at_ms or _now_ms(),
        duration_ms=result.duration_ms,
        invocation_id=result.invocation_id,
        approval_id=result.approval_id,
        error=redact_mcp_error(result.error),
        result_preview=_json_preview(result.result),
        args_preview=_json_preview(arguments),
    )


def append_gateway_call(project: str | Path, record: GatewayCallRecord) -> Path:
    path = gateway_calls_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    return path


def load_gateway_calls(project: str | Path, *, limit: int = 50) -> list[GatewayCallRecord]:
    path = gateway_calls_path(project)
    if not path.exists():
        return []
    rows: list[GatewayCallRecord] = []
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


def gateway_health(project: str | Path) -> GatewayHealth:
    project_path = Path(project).expanduser().resolve(strict=False)
    state = load_mcp_gateway(project_path, missing_ok=True)
    if state is None:
        return GatewayHealth(False, "missing", 0, 0, 0, 0, ["gateway state is missing"], str(gateway_state_path(project_path)))
    errors = list(state.errors)
    for server in state.servers:
        errors.extend(server.errors)
    lease_state = status_mcp_daemon_state(project_path)
    if Path(mcp_lease_registry_path(project_path)).exists() and not lease_state.leases and state.leases:
        errors.append("gateway has leases but MCP lease registry is empty")
    return GatewayHealth(
        ok=not errors,
        status=state.status,
        servers=len(state.servers),
        tools=len(state.tools),
        leases=len(state.leases),
        calls=len(load_gateway_calls(project_path, limit=1000)),
        errors=errors,
        gateway_path=str(gateway_state_path(project_path)),
    )


def render_mcp_gateway(state: McpGatewayState | GatewayHealth) -> str:
    if isinstance(state, GatewayHealth):
        lines = [
            "# MCP Gateway Health",
            "",
            f"- ok: {str(state.ok).lower()}",
            f"- status: {state.status}",
            f"- servers: {state.servers}",
            f"- tools: {state.tools}",
            f"- leases: {state.leases}",
            f"- calls: {state.calls}",
            f"- gateway_path: {state.gateway_path}",
        ]
        if state.errors:
            lines.extend(["", "## Errors"])
            lines.extend(f"- {error}" for error in state.errors[:12])
        return "\n".join(lines) + "\n"
    lines = [
        "# MCP Gateway",
        "",
        f"- gateway_id: {state.gateway_id}",
        f"- status: {state.status}",
        f"- servers: {len(state.servers)}",
        f"- tools: {len(state.tools)}",
        f"- leases: {len(state.leases)}",
        f"- recent_calls: {len(state.recent_calls)}",
        f"- note: {state.note}",
        "",
        "## Servers",
    ]
    if not state.servers:
        lines.append("- No MCP servers configured.")
    for server in state.servers:
        lines.append(f"- [{server.status}] {server.name} transport={server.transport} tools={server.tools} leases={server.leases}")
        for error in server.errors[:3]:
            lines.append(f"  error: {error}")
    if state.tools:
        lines.extend(["", "## Tools"])
        for tool in state.tools[:40]:
            lines.append(f"- {tool.server}/{tool.name} policy={tool.policy_action}: {tool.description}".rstrip())
    if state.recent_calls:
        lines.extend(["", "## Recent Calls"])
        for call in state.recent_calls[-10:]:
            mark = "ok" if call.ok else "fail"
            lines.append(f"- [{mark}] {call.server}/{call.tool} duration_ms={call.duration_ms} invocation={call.invocation_id or '-'}")
            if call.error:
                lines.append(f"  error: {call.error}")
    if state.errors:
        lines.extend(["", "## Errors"])
        lines.extend(f"- {error}" for error in state.errors[:12])
    return "\n".join(lines) + "\n"


def _safe_catalog(project: Path, *, server: str | None) -> McpCatalog:
    try:
        return list_mcp_catalog(project, server=server)
    except Exception as exc:
        configs = [config for config in load_mcp_servers(project) if not server or config.name == server]
        return McpCatalog(configs, [], [redact_mcp_error(f"{type(exc).__name__}: {exc}")])


def _server_states(
    configs: Sequence[Any],
    tools: Sequence[GatewayToolRecord],
    leases: Sequence[McpLeaseRecord],
    errors: Sequence[str],
) -> list[GatewayServerState]:
    by_server_errors: dict[str, list[str]] = {config.name: [] for config in configs}
    for error in errors:
        server = error.split(":", 1)[0]
        by_server_errors.setdefault(server, []).append(error)
    states: list[GatewayServerState] = []
    for config in configs:
        server_tools = [tool for tool in tools if tool.server == config.name]
        server_leases = [lease for lease in leases if lease.server == config.name]
        server_errors = by_server_errors.get(config.name, [])
        status = "error" if server_errors else "active" if server_leases else "configured"
        states.append(
            GatewayServerState(
                name=config.name,
                transport=config.transport,
                enabled=config.enabled,
                status=status,
                tools=len(server_tools),
                leases=len(server_leases),
                errors=server_errors,
            )
        )
    return states


def _call_record_from_dict(payload: dict[str, Any]) -> GatewayCallRecord:
    return GatewayCallRecord(
        call_id=str(payload.get("call_id") or ""),
        server=str(payload.get("server") or ""),
        tool=str(payload.get("tool") or ""),
        ok=bool(payload.get("ok")),
        started_at_ms=int(payload.get("started_at_ms") or 0),
        duration_ms=int(payload.get("duration_ms") or 0),
        invocation_id=str(payload.get("invocation_id") or ""),
        approval_id=str(payload.get("approval_id") or ""),
        error=redact_mcp_error(str(payload.get("error") or "")),
        result_preview=str(payload.get("result_preview") or ""),
        args_preview=str(payload.get("args_preview") or ""),
    )


def _json_preview(value: Any, *, limit: int = 1200) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = str(value)
    text = redact_mcp_error(text)
    return text if len(text) <= limit else text[: limit - 18] + "...[truncated]"


def _now_ms() -> int:
    return int(time.time() * 1000)
