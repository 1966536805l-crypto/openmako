from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping

from .operator_auth import CONTROL, READ, WRITE, OperatorAuthPolicy, authorize_operator_command, command_scope
from .runtime_store import RuntimeQueueItem, enqueue_runtime_queue_item


DEFAULT_CHANNEL_QUEUE = "channel_gateway"
PAIRING_TTL_SECONDS = 600
STATE_VERSION = 1

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class ChannelGatewayResult:
    ok: bool
    status: str
    allowed: bool = False
    channel: str = ""
    sender: str = ""
    owner_key: str = ""
    message: str = ""
    code: str = ""
    paired: bool = False
    item_id: str = ""
    event_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ChannelGatewayEvent:
    event_id: str
    created_at: int
    event_type: str
    status: str
    channel: str = ""
    sender: str = ""
    owner_key: str = ""
    allowed: bool = False
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ChannelBinding:
    channel: str
    sender: str
    owner_key: str
    agent_id: str = "main"
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


def create_pairing_code(
    project: str | Path,
    *,
    owner_key: str,
    channel: str = "",
    agent_id: str = "main",
    ttl_seconds: float = PAIRING_TTL_SECONDS,
    code: str = "",
    now_ms: int | None = None,
) -> ChannelGatewayResult:
    project_path = _project_path(project)
    normalized_owner = _normalize_owner(owner_key)
    if not normalized_owner:
        raise ValueError("owner_key is required")
    normalized_channel = _normalize_endpoint(channel)
    normalized_agent = _normalize_agent(agent_id)
    issued_code = str(code or _new_pairing_code()).strip()
    if not issued_code:
        raise ValueError("pairing code is required")
    timestamp = _now_ms(now_ms)
    expires_at = timestamp + max(1, int(float(ttl_seconds) * 1000))

    with _locked_state(project_path) as state:
        state["codes"].append(
            {
                "code_id": "pair-" + uuid.uuid4().hex[:12],
                "code_hash": _hash_pairing_code(issued_code),
                "channel": normalized_channel,
                "owner_key": normalized_owner,
                "agent_id": normalized_agent,
                "created_at": timestamp,
                "expires_at": expires_at,
                "used_at": None,
            }
        )

    event_id = _record_event(
        project_path,
        "pairing_code_created",
        "pairing_code_created",
        channel=normalized_channel,
        owner_key=normalized_owner,
        allowed=True,
        payload={"expires_at": expires_at, "agent_id": normalized_agent},
    )
    return ChannelGatewayResult(
        ok=True,
        allowed=True,
        status="pairing_code_created",
        channel=normalized_channel,
        owner_key=normalized_owner,
        code=issued_code,
        event_id=event_id,
        payload={"expires_at": expires_at, "agent_id": normalized_agent},
    )


def pair_sender(
    project: str | Path,
    *,
    channel: str,
    sender: str,
    code: str,
    now_ms: int | None = None,
) -> ChannelGatewayResult:
    project_path = _project_path(project)
    normalized_channel = _normalize_endpoint(channel)
    normalized_sender = _normalize_endpoint(sender)
    timestamp = _now_ms(now_ms)
    if not normalized_channel:
        raise ValueError("channel is required")
    if not normalized_sender:
        raise ValueError("sender is required")
    code_hash = _hash_pairing_code(str(code or "").strip())

    owner_key = ""
    agent_id = "main"
    status = "invalid_pairing_code"
    paired = False
    with _locked_state(project_path) as state:
        for entry in state["codes"]:
            if entry.get("code_hash") != code_hash:
                continue
            if entry.get("used_at"):
                status = "pairing_code_used"
                break
            if int(entry.get("expires_at") or 0) < timestamp:
                status = "pairing_code_expired"
                break
            code_channel = str(entry.get("channel") or "")
            if code_channel and code_channel != normalized_channel:
                status = "invalid_pairing_channel"
                break
            owner_key = str(entry.get("owner_key") or "")
            agent_id = _normalize_agent(str(entry.get("agent_id") or "main"))
            entry["used_at"] = timestamp
            _upsert_binding(state, normalized_channel, normalized_sender, owner_key, timestamp, agent_id=agent_id)
            status = "paired"
            paired = True
            break

    event_id = _record_event(
        project_path,
        "pairing_attempt",
        status,
        channel=normalized_channel,
        sender=normalized_sender,
        owner_key=owner_key,
        allowed=paired,
        payload={"agent_id": agent_id},
    )
    return ChannelGatewayResult(
        ok=paired,
        allowed=paired,
        status=status,
        channel=normalized_channel,
        sender=normalized_sender,
        owner_key=owner_key,
        paired=paired,
        event_id=event_id,
        payload={"agent_id": agent_id},
    )


def resolve_sender_owner(
    project: str | Path,
    *,
    channel: str,
    sender: str,
) -> ChannelGatewayResult:
    project_path = _project_path(project)
    normalized_channel = _normalize_endpoint(channel)
    normalized_sender = _normalize_endpoint(sender)
    binding = _find_binding(project_path, normalized_channel, normalized_sender)
    if binding is None:
        event_id = _record_event(
            project_path,
            "sender_resolve",
            "pairing_required",
            channel=normalized_channel,
            sender=normalized_sender,
            allowed=False,
        )
        return ChannelGatewayResult(
            ok=False,
            allowed=False,
            status="pairing_required",
            channel=normalized_channel,
            sender=normalized_sender,
            event_id=event_id,
            message="sender must pair before sending channel commands",
        )
    event_id = _record_event(
        project_path,
        "sender_resolve",
        "resolved",
        channel=normalized_channel,
        sender=normalized_sender,
        owner_key=str(binding.get("owner_key") or ""),
        allowed=True,
    )
    return ChannelGatewayResult(
        ok=True,
        allowed=True,
        status="resolved",
        channel=normalized_channel,
        sender=normalized_sender,
        owner_key=str(binding.get("owner_key") or ""),
        event_id=event_id,
        payload={"agent_id": _normalize_agent(str(binding.get("agent_id") or "main"))},
    )


def bind_sender_agent(
    project: str | Path,
    *,
    channel: str,
    sender: str,
    agent_id: str,
) -> ChannelGatewayResult:
    project_path = _project_path(project)
    normalized_channel = _normalize_endpoint(channel)
    normalized_sender = _normalize_endpoint(sender)
    normalized_agent = _normalize_agent(agent_id)
    timestamp = _now_ms(None)
    with _locked_state(project_path) as state:
        binding = _find_binding_in_state(state, normalized_channel, normalized_sender)
        if binding is None:
            event_id = _record_event(
                project_path,
                "agent_binding_failed",
                "pairing_required",
                channel=normalized_channel,
                sender=normalized_sender,
                allowed=False,
                payload={"agent_id": normalized_agent},
            )
            return ChannelGatewayResult(
                ok=False,
                allowed=False,
                status="pairing_required",
                channel=normalized_channel,
                sender=normalized_sender,
                event_id=event_id,
                message="sender must pair before binding an agent",
                payload={"agent_id": normalized_agent},
            )
        binding["agent_id"] = normalized_agent
        binding["updated_at"] = timestamp
        owner_key = str(binding.get("owner_key") or "")
    event_id = _record_event(
        project_path,
        "agent_bound",
        "bound",
        channel=normalized_channel,
        sender=normalized_sender,
        owner_key=owner_key,
        allowed=True,
        payload={"agent_id": normalized_agent},
    )
    return ChannelGatewayResult(
        ok=True,
        allowed=True,
        status="bound",
        channel=normalized_channel,
        sender=normalized_sender,
        owner_key=owner_key,
        event_id=event_id,
        payload={"agent_id": normalized_agent},
    )


def list_channel_bindings(project: str | Path) -> tuple[ChannelBinding, ...]:
    state = _read_state(_state_path(_project_path(project)))
    bindings: list[ChannelBinding] = []
    for raw in state["bindings"]:
        bindings.append(
            ChannelBinding(
                channel=str(raw.get("channel") or ""),
                sender=str(raw.get("sender") or ""),
                owner_key=str(raw.get("owner_key") or ""),
                agent_id=_normalize_agent(str(raw.get("agent_id") or "main")),
                created_at=int(raw.get("created_at") or 0),
                updated_at=int(raw.get("updated_at") or 0),
            )
        )
    return tuple(bindings)


def handle_channel_message(
    project: str | Path,
    *,
    channel: str,
    sender: str,
    text: str,
    policy: OperatorAuthPolicy | Mapping[str, Any] | None = None,
    executor: Callable[[dict[str, Any]], Any] | None = None,
    allow_execute: bool = False,
    queue: str = DEFAULT_CHANNEL_QUEUE,
    now_ms: int | None = None,
) -> ChannelGatewayResult:
    project_path = _project_path(project)
    normalized_channel = _normalize_endpoint(channel)
    normalized_sender = _normalize_endpoint(sender)
    message_text = str(text or "").strip()
    resolved = resolve_sender_owner(project_path, channel=normalized_channel, sender=normalized_sender)
    if not resolved.ok:
        event_id = _record_event(
            project_path,
            "message_rejected",
            "pairing_required",
            channel=normalized_channel,
            sender=normalized_sender,
            allowed=False,
            payload={"text_preview": _preview(message_text)},
        )
        return ChannelGatewayResult(
            ok=False,
            allowed=False,
            status="pairing_required",
            channel=normalized_channel,
            sender=normalized_sender,
            event_id=event_id,
            message="sender must pair before sending channel commands",
        )

    owner_key = resolved.owner_key
    agent_id = str(resolved.payload.get("agent_id") or "main")
    command = _command_for_text(message_text)
    auth = authorize_operator_command(owner_key, command, policy or _default_policy(owner_key))
    if not auth.allowed:
        event_id = _record_event(
            project_path,
            "message_rejected",
            "denied",
            channel=normalized_channel,
            sender=normalized_sender,
            owner_key=owner_key,
            allowed=False,
            payload={"command": command, "reason": auth.reason, "text_preview": _preview(message_text), "agent_id": agent_id},
        )
        return ChannelGatewayResult(
            ok=False,
            allowed=False,
            status="denied",
            channel=normalized_channel,
            sender=normalized_sender,
            owner_key=owner_key,
            message=auth.reason,
            event_id=event_id,
            payload={"command": command, "scope": auth.scope, "agent_id": agent_id},
        )

    dispatch_payload = {
        "channel": normalized_channel,
        "sender": normalized_sender,
        "owner_key": owner_key,
        "agent_id": agent_id,
        "text": message_text,
        "command": command,
        "scope": auth.scope,
    }
    if executor is not None and allow_execute:
        result = executor(dict(dispatch_payload))
        event_id = _record_event(
            project_path,
            "message_executed",
            "executed",
            channel=normalized_channel,
            sender=normalized_sender,
            owner_key=owner_key,
            allowed=True,
            payload={"command": command, "result": _json_safe(result), "agent_id": agent_id},
        )
        return ChannelGatewayResult(
            ok=True,
            allowed=True,
            status="executed",
            channel=normalized_channel,
            sender=normalized_sender,
            owner_key=owner_key,
            event_id=event_id,
            payload={"command": command, "result": _json_safe(result), "agent_id": agent_id},
        )

    if command_scope(command) == READ:
        event_id = _record_event(
            project_path,
            "message_accepted",
            "accepted",
            channel=normalized_channel,
            sender=normalized_sender,
            owner_key=owner_key,
            allowed=True,
            payload={"command": command, "agent_id": agent_id},
        )
        return ChannelGatewayResult(
            ok=True,
            allowed=True,
            status="accepted",
            channel=normalized_channel,
            sender=normalized_sender,
            owner_key=owner_key,
            event_id=event_id,
            payload={"command": command, "scope": READ, "agent_id": agent_id},
        )

    target_queue = queue if queue != DEFAULT_CHANNEL_QUEUE or agent_id == "main" else f"{DEFAULT_CHANNEL_QUEUE}:{agent_id}"
    item = enqueue_runtime_queue_item(
        project_path,
        task=message_text or command,
        queue=target_queue,
        task_kind="channel_message",
        owner_key=owner_key,
        payload=dispatch_payload,
        priority=50,
        max_attempts=1,
    )
    event_id = _record_event(
        project_path,
        "message_queued",
        "queued",
        channel=normalized_channel,
        sender=normalized_sender,
        owner_key=owner_key,
        allowed=True,
        payload={"command": command, "queue": target_queue, "task_id": item.task_id, "agent_id": agent_id},
    )
    return ChannelGatewayResult(
        ok=True,
        allowed=True,
        status="queued",
        channel=normalized_channel,
        sender=normalized_sender,
        owner_key=owner_key,
        item_id=item.task_id,
        event_id=event_id,
        payload={"command": command, "queue": target_queue, "agent_id": agent_id, "task": _queue_item_payload(item)},
    )


def list_channel_gateway_events(
    project: str | Path,
    *,
    limit: int = 100,
) -> tuple[ChannelGatewayEvent, ...]:
    path = _events_path(_project_path(project))
    if not path.exists():
        return ()
    bounded_limit = max(1, min(int(limit), 1000))
    rows: list[ChannelGatewayEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-bounded_limit:]:
        if not line.strip():
            continue
        with contextlib.suppress(json.JSONDecodeError, TypeError, ValueError):
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(_event_from_payload(payload))
    return tuple(rows)


def _gateway_dir(project: Path) -> Path:
    path = project / ".quantagent" / "channel_gateway"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _state_path(project: Path) -> Path:
    return _gateway_dir(project) / "state.json"


def _lock_path(project: Path) -> Path:
    return _gateway_dir(project) / "state.lock"


def _events_path(project: Path) -> Path:
    return _gateway_dir(project) / "events.jsonl"


def _project_path(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False)


@contextlib.contextmanager
def _locked_state(project: Path) -> Iterator[dict[str, Any]]:
    with _file_lock(_lock_path(project)):
        state = _read_state(_state_path(project))
        yield state
        _write_state(_state_path(project), state)


@contextlib.contextmanager
def _file_lock(path: Path, *, timeout: float = 10.0, poll: float = 0.05) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fcntl  # type: ignore
    except ImportError:
        marker = path.with_suffix(path.suffix + ".held")
        deadline = time.monotonic() + timeout
        fd = -1
        while True:
            try:
                fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode("utf-8"))
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"channel gateway lock timeout: {marker}")
                time.sleep(poll)
        try:
            yield
        finally:
            if fd >= 0:
                os.close(fd)
            with contextlib.suppress(FileNotFoundError):
                marker.unlink()
        return

    deadline = time.monotonic() + timeout
    with path.open("a+", encoding="utf-8") as handle:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"channel gateway lock timeout: {path}")
                time.sleep(poll)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": STATE_VERSION, "codes": [], "bindings": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid channel gateway state: {path}")
    codes = payload.get("codes", [])
    bindings = payload.get("bindings", [])
    return {
        "version": int(payload.get("version") or STATE_VERSION),
        "codes": [dict(item) for item in codes if isinstance(item, dict)],
        "bindings": [dict(item) for item in bindings if isinstance(item, dict)],
    }


def _write_state(path: Path, state: Mapping[str, Any]) -> None:
    payload = {
        "version": STATE_VERSION,
        "codes": list(state.get("codes") or []),
        "bindings": list(state.get("bindings") or []),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _find_binding(project: Path, channel: str, sender: str) -> dict[str, Any] | None:
    state = _read_state(_state_path(project))
    return _find_binding_in_state(state, channel, sender)


def _find_binding_in_state(state: Mapping[str, Any], channel: str, sender: str) -> dict[str, Any] | None:
    for binding in state["bindings"]:
        if binding.get("channel") == channel and binding.get("sender") == sender:
            return binding
    return None


def _upsert_binding(state: dict[str, Any], channel: str, sender: str, owner_key: str, timestamp: int, *, agent_id: str = "main") -> None:
    for binding in state["bindings"]:
        if binding.get("channel") == channel and binding.get("sender") == sender:
            binding.update({"owner_key": owner_key, "updated_at": timestamp})
            binding.setdefault("agent_id", _normalize_agent(agent_id))
            return
    state["bindings"].append(
        {
            "channel": channel,
            "sender": sender,
            "owner_key": owner_key,
            "agent_id": _normalize_agent(agent_id),
            "created_at": timestamp,
            "updated_at": timestamp,
        }
    )


def _record_event(
    project: Path,
    event_type: str,
    status: str,
    *,
    channel: str = "",
    sender: str = "",
    owner_key: str = "",
    allowed: bool = False,
    payload: Mapping[str, Any] | None = None,
) -> str:
    event_id = "chan-" + uuid.uuid4().hex[:12]
    event = ChannelGatewayEvent(
        event_id=event_id,
        created_at=_now_ms(None),
        event_type=event_type,
        status=status,
        channel=channel,
        sender=sender,
        owner_key=owner_key,
        allowed=allowed,
        payload=dict(payload or {}),
    )
    path = _events_path(project)
    with _file_lock(path.with_suffix(path.suffix + ".lock")):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    return event_id


def _event_from_payload(payload: Mapping[str, Any]) -> ChannelGatewayEvent:
    return ChannelGatewayEvent(
        event_id=str(payload.get("event_id") or ""),
        created_at=int(payload.get("created_at") or 0),
        event_type=str(payload.get("event_type") or ""),
        status=str(payload.get("status") or ""),
        channel=str(payload.get("channel") or ""),
        sender=str(payload.get("sender") or ""),
        owner_key=str(payload.get("owner_key") or ""),
        allowed=bool(payload.get("allowed", False)),
        payload=dict(payload.get("payload") or {}),
    )


def _default_policy(owner_key: str) -> OperatorAuthPolicy:
    return OperatorAuthPolicy(
        allowed_senders=(owner_key,),
        sender_scopes={owner_key: (READ, CONTROL)},
        default_scopes=(READ,),
    )


def _command_for_text(text: str) -> str:
    value = str(text or "").strip()
    lowered = value.lower()
    if lowered in {"status", "help", "list", "summary"}:
        return "/" + lowered
    if lowered.startswith("exec:"):
        return "/exec " + value.split(":", 1)[1].strip()
    if value.startswith("/"):
        return value
    return "/start " + value


def _normalize_owner(owner_key: str) -> str:
    return _SPACE.sub("", _CONTROL_CHARS.sub("", str(owner_key or "").strip().lower()))


def _normalize_endpoint(value: str) -> str:
    text = _CONTROL_CHARS.sub("", str(value or "").strip().lower())
    text = text.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    return _SPACE.sub("", text)


def _normalize_agent(value: str) -> str:
    text = _normalize_endpoint(value).replace("/", "-")
    if not text:
        return "main"
    return re.sub(r"[^a-z0-9_.:-]+", "-", text)[:80] or "main"


def _new_pairing_code() -> str:
    return "pc_" + secrets.token_urlsafe(9)


def _hash_pairing_code(code: str) -> str:
    return hashlib.sha256(str(code or "").strip().encode("utf-8")).hexdigest()


def _preview(text: str, *, limit: int = 160) -> str:
    value = str(text or "").replace("\n", " ").strip()
    return value if len(value) <= limit else value[: limit - 1] + "..."


def _queue_item_payload(item: RuntimeQueueItem) -> dict[str, Any]:
    return item.to_dict() if hasattr(item, "to_dict") else {"task_id": item.task_id, "status": item.status}


def _now_ms(value: int | None) -> int:
    return int(value if value is not None else time.time() * 1000)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    if hasattr(value, "__dataclass_fields__"):
        return _json_safe(asdict(value))
    return value
