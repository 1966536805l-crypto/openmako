from __future__ import annotations

import json
import multiprocessing as mp
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


MESSAGE_TASK = "TASK"
MESSAGE_HANDOFF = "HANDOFF"
MESSAGE_REVIEW_REQUEST = "REVIEW_REQUEST"
MESSAGE_REVIEW_RESULT = "REVIEW_RESULT"
MESSAGE_DECISION = "DECISION"
MESSAGE_ERROR = "ERROR"
MESSAGE_TYPES = {
    MESSAGE_TASK,
    MESSAGE_HANDOFF,
    MESSAGE_REVIEW_REQUEST,
    MESSAGE_REVIEW_RESULT,
    MESSAGE_DECISION,
    MESSAGE_ERROR,
}

MESSAGE_UNREAD = "unread"
MESSAGE_RUNNING = "running"
MESSAGE_DONE = "done"
MESSAGE_FAILED = "failed"
MESSAGE_STATES = {MESSAGE_UNREAD, MESSAGE_RUNNING, MESSAGE_DONE, MESSAGE_FAILED}

EVENT_SENT = "MESSAGE_SENT"
EVENT_RUNNING = "MESSAGE_RUNNING"
EVENT_DONE = "MESSAGE_DONE"
EVENT_FAILED = "MESSAGE_FAILED"
EVENT_HEARTBEAT = "HEARTBEAT"
EVENTS_TO_STATE = {
    EVENT_SENT: MESSAGE_UNREAD,
    EVENT_RUNNING: MESSAGE_RUNNING,
    EVENT_DONE: MESSAGE_DONE,
    EVENT_FAILED: MESSAGE_FAILED,
}

DECISIONS = {"MERGE", "REQUEST_CHANGES", "ROLLBACK", "WAIT_FOR_EVIDENCE"}
HEARTBEAT_STATES = {"idle", "running", "error", "stale"}
DEFAULT_AGENTS = {"diagnoser", "executor", "reviewer"}
FORBIDDEN_SHARED_CHAT = "shared_chat.md"
DEFAULT_LEASE_SECONDS = 300.0
DEFAULT_STALE_SECONDS = 60.0
DEFAULT_LOCK_TTL_SECONDS = 30.0


@dataclass(frozen=True)
class TaskCard:
    id: str
    goal: str
    scope_allowed: list[str] = field(default_factory=list)
    scope_forbidden: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    risk_level: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceFact:
    id: str
    text: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceInference:
    id: str
    fact_ids: list[str]
    text: str
    confidence: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceAction:
    id: str
    inference_ids: list[str]
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidencePacket:
    task_id: str
    facts: list[EvidenceFact] = field(default_factory=list)
    inferences: list[EvidenceInference] = field(default_factory=list)
    actions: list[EvidenceAction] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "facts": [item.to_dict() for item in self.facts],
            "inferences": [item.to_dict() for item in self.inferences],
            "actions": [item.to_dict() for item in self.actions],
            "blocked": list(self.blocked),
        }


@dataclass(frozen=True)
class Handoff:
    task_id: str
    lines: list[str]
    allowed_files: list[str] = field(default_factory=list)
    forbidden_files: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BlindReview:
    task_id: str
    task_card: dict[str, Any]
    diff_summary: str
    test_result: str
    changed_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Decision:
    task_id: str
    status: str
    reason: str = ""
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentMessage:
    id: str
    task_id: str
    from_agent: str
    to_agent: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = MESSAGE_UNREAD
    created_at: str = ""
    updated_at: str = ""
    lease_id: str = ""
    lease_expires_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MessageLease:
    lease_id: str
    message_id: str
    claimed_by: str
    lease_expires_at: float
    created_at: str = ""
    event_id: str = ""

    def expired(self, now: float | None = None) -> bool:
        return self.lease_expires_at < float(_now_seconds() if now is None else now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentHeartbeat:
    agent_id: str
    status: str
    current_task_id: str = ""
    last_seen_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RelayEvent:
    id: str
    message_id: str
    task_id: str
    agent_id: str
    event_type: str
    status: str
    created_at: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def append_jsonl(path: str | Path, obj: dict[str, Any]) -> Path:
    target = Path(path).expanduser().resolve(strict=False)
    _reject_shared_chat_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")
    return target


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path).expanduser().resolve(strict=False)
    _reject_shared_chat_path(target)
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    with target.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def write_json_atomic(path: str | Path, obj: dict[str, Any]) -> Path:
    target = Path(path).expanduser().resolve(strict=False)
    _reject_shared_chat_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + f".tmp-{uuid.uuid4().hex}")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    return target


def relay_root(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "relay"


def agents_root(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "agents"


def event_log(project: str | Path) -> Path:
    return relay_root(project) / "events.jsonl"


def state_lock_path(project: str | Path) -> Path:
    return relay_root(project) / "state.lock"


def create_task_card(
    project: str | Path,
    goal: str,
    *,
    task_id: str = "",
    scope_allowed: Iterable[str] = (),
    scope_forbidden: Iterable[str] = (),
    success_criteria: Iterable[str] = (),
    risk_level: str = "medium",
) -> TaskCard:
    _ensure_no_shared_chat_reference({"goal": goal, "scope_allowed": list(scope_allowed), "scope_forbidden": list(scope_forbidden)})
    card = TaskCard(
        id=task_id or "relay-" + uuid.uuid4().hex[:8],
        goal=str(goal or "").strip(),
        scope_allowed=[str(item) for item in scope_allowed],
        scope_forbidden=[str(item) for item in scope_forbidden],
        success_criteria=[str(item) for item in success_criteria],
        risk_level=str(risk_level or "medium"),
    )
    validate_task_card(card)
    append_jsonl(relay_root(project) / "relay_tasks.jsonl", card.to_dict())
    write_json_atomic(relay_root(project) / "latest.json", {"task_card": card.to_dict()})
    return card


def validate_task_card(card: TaskCard) -> None:
    if not card.id:
        raise ValueError("task card id is required")
    if not card.goal:
        raise ValueError("task card goal is required")
    _ensure_no_shared_chat_reference(card.to_dict())


def parse_evidence_packet(payload: dict[str, Any]) -> EvidencePacket:
    packet = EvidencePacket(
        task_id=str(payload.get("task_id") or ""),
        facts=[
            EvidenceFact(id=str(item.get("id") or ""), text=str(item.get("text") or ""), source=str(item.get("source") or ""))
            for item in _list_of_dicts(payload.get("facts"))
        ],
        inferences=[
            EvidenceInference(
                id=str(item.get("id") or ""),
                fact_ids=[str(value) for value in item.get("fact_ids", [])] if isinstance(item.get("fact_ids"), list) else [],
                text=str(item.get("text") or ""),
                confidence=str(item.get("confidence") or "medium"),
            )
            for item in _list_of_dicts(payload.get("inferences"))
        ],
        actions=[
            EvidenceAction(
                id=str(item.get("id") or ""),
                inference_ids=[str(value) for value in item.get("inference_ids", [])] if isinstance(item.get("inference_ids"), list) else [],
                text=str(item.get("text") or ""),
            )
            for item in _list_of_dicts(payload.get("actions"))
        ],
        blocked=[str(item) for item in payload.get("blocked", [])] if isinstance(payload.get("blocked"), list) else [],
    )
    validate_evidence_packet(packet)
    return packet


def validate_evidence_packet(packet: EvidencePacket) -> None:
    if not packet.task_id:
        raise ValueError("evidence packet task_id is required")
    fact_ids: set[str] = set()
    for fact in packet.facts:
        if not fact.id:
            raise ValueError("FACT id is required")
        if not fact.source:
            raise ValueError(f"FACT {fact.id} source is required")
        fact_ids.add(fact.id)
    inference_ids: set[str] = set()
    for inference in packet.inferences:
        if not inference.id:
            raise ValueError("INFERENCE id is required")
        if not inference.fact_ids:
            raise ValueError(f"INFERENCE {inference.id} must bind at least one FACT")
        missing = [fact_id for fact_id in inference.fact_ids if fact_id not in fact_ids]
        if missing:
            raise ValueError(f"INFERENCE {inference.id} references unknown FACT(s): {', '.join(missing)}")
        inference_ids.add(inference.id)
    for action in packet.actions:
        if not action.id:
            raise ValueError("ACTION id is required")
        if not action.inference_ids:
            raise ValueError(f"ACTION {action.id} must bind at least one INFERENCE")
        missing = [inference_id for inference_id in action.inference_ids if inference_id not in inference_ids]
        if missing:
            raise ValueError(f"ACTION {action.id} references unknown INFERENCE(s): {', '.join(missing)}")
    _ensure_no_shared_chat_reference(packet.to_dict())


def parse_handoff(payload: dict[str, Any]) -> Handoff:
    handoff = Handoff(
        task_id=str(payload.get("task_id") or ""),
        lines=[str(item) for item in payload.get("lines", [])] if isinstance(payload.get("lines"), list) else [],
        allowed_files=[str(item) for item in payload.get("allowed_files", [])] if isinstance(payload.get("allowed_files"), list) else [],
        forbidden_files=[str(item) for item in payload.get("forbidden_files", [])] if isinstance(payload.get("forbidden_files"), list) else [],
        success_criteria=[str(item) for item in payload.get("success_criteria", [])] if isinstance(payload.get("success_criteria"), list) else [],
    )
    validate_handoff(handoff)
    return handoff


def validate_handoff(handoff: Handoff) -> None:
    if not handoff.task_id:
        raise ValueError("handoff task_id is required")
    if len(handoff.lines) > 10:
        raise ValueError("handoff must be 10 lines or fewer")
    _ensure_no_shared_chat_reference(handoff.to_dict())


def parse_blind_review(payload: dict[str, Any]) -> BlindReview:
    review = BlindReview(
        task_id=str(payload.get("task_id") or ""),
        task_card=payload.get("task_card") if isinstance(payload.get("task_card"), dict) else {},
        diff_summary=str(payload.get("diff_summary") or ""),
        test_result=str(payload.get("test_result") or ""),
        changed_files=[str(item) for item in payload.get("changed_files", [])] if isinstance(payload.get("changed_files"), list) else [],
    )
    validate_blind_review_payload(payload)
    return review


def validate_blind_review_payload(payload: dict[str, Any]) -> None:
    forbidden = {"executor_explanation", "author_explanation"}
    found = sorted(_find_keys(payload, forbidden))
    if found:
        raise ValueError("blind review payload must not include author explanation fields: " + ", ".join(found))
    if not str(payload.get("task_id") or ""):
        raise ValueError("blind review task_id is required")
    _ensure_no_shared_chat_reference(payload)


def parse_decision(payload: dict[str, Any]) -> Decision:
    decision = Decision(
        task_id=str(payload.get("task_id") or ""),
        status=str(payload.get("status") or "").upper(),
        reason=str(payload.get("reason") or ""),
        evidence_ids=[str(item) for item in payload.get("evidence_ids", [])] if isinstance(payload.get("evidence_ids"), list) else [],
    )
    validate_decision(decision)
    return decision


def validate_decision(decision: Decision) -> None:
    if not decision.task_id:
        raise ValueError("decision task_id is required")
    if decision.status not in DECISIONS:
        raise ValueError(f"invalid decision status: {decision.status}")
    _ensure_no_shared_chat_reference(decision.to_dict())


def send_message(
    project: str | Path,
    *,
    to_agent: str,
    message_type: str,
    task_id: str,
    payload: dict[str, Any],
    from_agent: str = "user",
    message_id: str = "",
) -> AgentMessage:
    project_path = Path(project).expanduser().resolve(strict=False)
    _validate_agent_id(to_agent)
    _validate_agent_id(from_agent, allow_user=True)
    normalized_type = str(message_type or "").upper()
    if normalized_type not in MESSAGE_TYPES:
        raise ValueError(f"invalid message type: {message_type}")
    _validate_payload_for_message(normalized_type, to_agent, payload)
    now = _now()
    message = AgentMessage(
        id=message_id or "msg-" + uuid.uuid4().hex[:12],
        task_id=str(task_id or payload.get("task_id") or ""),
        from_agent=str(from_agent),
        to_agent=str(to_agent),
        type=normalized_type,
        payload=dict(payload),
        status=MESSAGE_UNREAD,
        created_at=now,
        updated_at=now,
    )
    if not message.task_id:
        raise ValueError("message task_id is required")
    with _state_lock(project_path):
        if _message_id_exists(project_path, message.id):
            raise ValueError(f"message id already exists: {message.id}")
        append_jsonl(_inbox_path(project_path, to_agent), message.to_dict())
        _append_event(
            project_path,
            message_id=message.id,
            task_id=message.task_id,
            agent_id=to_agent,
            event_type=EVENT_SENT,
            status=MESSAGE_UNREAD,
            payload={"from_agent": from_agent, "to_agent": to_agent, "type": normalized_type},
        )
    return message


def read_inbox(project: str | Path, agent_id: str, *, requester_agent: str | None = None) -> list[AgentMessage]:
    if requester_agent is None:
        raise PermissionError("requester_agent is required to read an agent inbox")
    _require_same_agent(agent_id, requester_agent)
    return [_message_from_dict(item) for item in read_jsonl(_inbox_path(project, agent_id))]


def list_agent_messages(project: str | Path, agent_id: str, *, requester_agent: str | None = None) -> list[dict[str, Any]]:
    messages = read_inbox(project, agent_id, requester_agent=requester_agent)
    return [_message_with_state(project, message) for message in messages]


def get_message_state(project: str | Path, message_id: str) -> str:
    if not str(message_id or ""):
        raise ValueError("message_id is required")
    events = read_jsonl(event_log(project))
    state = _message_state_from_events(events, message_id)
    if state:
        return state
    message = _find_message(project, message_id)
    if message is None:
        raise KeyError(f"message not found: {message_id}")
    if message.status != MESSAGE_UNREAD:
        raise ValueError("inbox message status must remain unread; events are the state source")
    return MESSAGE_UNREAD


def get_active_lease(project: str | Path, message_id: str) -> MessageLease | None:
    events = read_jsonl(event_log(project))
    return _active_lease_from_events(events, message_id)


def mark_running(
    project: str | Path,
    agent_id: str,
    message_id: str,
    *,
    lease_seconds: float = DEFAULT_LEASE_SECONDS,
) -> AgentMessage:
    project_path = Path(project).expanduser().resolve(strict=False)
    with _state_lock(project_path):
        message = _message_for_agent(project_path, agent_id, message_id)
        events = read_jsonl(event_log(project_path))
        state = _message_state_from_events(events, message_id) or _initial_message_state(message)
        if state != MESSAGE_UNREAD:
            raise ValueError(f"message cannot be marked running from state: {state}")
        lease = _create_lease(message.id, agent_id, lease_seconds)
        _append_event(
            project_path,
            message_id=message.id,
            task_id=message.task_id,
            agent_id=agent_id,
            event_type=EVENT_RUNNING,
            status=MESSAGE_RUNNING,
            payload=lease.to_dict(),
        )
        update_heartbeat(project_path, agent_id, status=MESSAGE_RUNNING, current_task_id=message.task_id)
        return _message_with_lease(message, lease)


def poll_once(
    project: str | Path,
    agent_id: str,
    *,
    requester_agent: str | None = None,
    lock_ttl_seconds: float = DEFAULT_LOCK_TTL_SECONDS,
    lease_seconds: float = DEFAULT_LEASE_SECONDS,
    stale_seconds: float = DEFAULT_STALE_SECONDS,
) -> AgentMessage | None:
    _require_same_agent(agent_id, requester_agent)
    project_path = Path(project).expanduser().resolve(strict=False)
    _validate_agent_id(agent_id)
    with _state_lock(project_path, ttl_seconds=lock_ttl_seconds):
        now = _now_seconds()
        events = read_jsonl(event_log(project_path))
        for message in read_inbox(project_path, agent_id, requester_agent=agent_id):
            state = _message_state_from_events(events, message.id) or _initial_message_state(message)
            if state == MESSAGE_UNREAD or _can_reclaim(project_path, message.id, events, now=now, stale_seconds=stale_seconds):
                lease = _create_lease(message.id, agent_id, lease_seconds, now=now)
                _append_event(
                    project_path,
                    message_id=message.id,
                    task_id=message.task_id,
                    agent_id=agent_id,
                    event_type=EVENT_RUNNING,
                    status=MESSAGE_RUNNING,
                    payload=lease.to_dict(),
                )
                update_heartbeat(project_path, agent_id, status=MESSAGE_RUNNING, current_task_id=message.task_id)
                return _message_with_lease(message, lease)
        update_heartbeat(project_path, agent_id, status="idle", current_task_id="")
        return None


def mark_done(project: str | Path, agent_id: str, message_id: str, output: dict[str, Any], *, lease_id: str = "") -> AgentMessage:
    project_path = Path(project).expanduser().resolve(strict=False)
    with _state_lock(project_path):
        message = _message_for_agent(project_path, agent_id, message_id)
        events = read_jsonl(event_log(project_path))
        lease = _validate_active_lease(events, message_id, lease_id=lease_id, now=_now_seconds())
        payload = {"lease_id": lease.lease_id, "result": dict(output)}
        _append_event(project_path, message_id=message.id, task_id=message.task_id, agent_id=agent_id, event_type=EVENT_DONE, status=MESSAGE_DONE, payload=payload)
        write_outbox(project_path, agent_id, message, payload, status=MESSAGE_DONE)
        update_heartbeat(project_path, agent_id, status="idle", current_task_id="")
        return _message_with_lease(message, lease)


def mark_failed(project: str | Path, agent_id: str, message_id: str, output: dict[str, Any], *, lease_id: str = "") -> AgentMessage:
    project_path = Path(project).expanduser().resolve(strict=False)
    with _state_lock(project_path):
        message = _message_for_agent(project_path, agent_id, message_id)
        events = read_jsonl(event_log(project_path))
        lease = _validate_active_lease(events, message_id, lease_id=lease_id, now=_now_seconds())
        payload = dict(output)
        if "error" not in payload:
            payload["error"] = payload.get("summary") or "message failed"
        event_payload = {"lease_id": lease.lease_id, "result": payload}
        _append_event(project_path, message_id=message.id, task_id=message.task_id, agent_id=agent_id, event_type=EVENT_FAILED, status=MESSAGE_FAILED, payload=event_payload)
        write_outbox(project_path, agent_id, message, event_payload, status=MESSAGE_FAILED)
        update_heartbeat(project_path, agent_id, status="error", current_task_id=message.task_id)
        return _message_with_lease(message, lease)


def write_outbox(project: str | Path, agent_id: str, message: AgentMessage, output: dict[str, Any], *, status: str) -> Path:
    _validate_agent_id(agent_id)
    payload = {
        "message_id": message.id,
        "task_id": message.task_id,
        "agent_id": agent_id,
        "status": status,
        "output": dict(output),
        "created_at": _now(),
    }
    _ensure_no_shared_chat_reference(payload)
    return append_jsonl(_outbox_path(project, agent_id), payload)


def update_heartbeat(
    project: str | Path,
    agent_id: str,
    *,
    status: str,
    current_task_id: str = "",
) -> AgentHeartbeat:
    _validate_agent_id(agent_id)
    normalized = str(status or "idle")
    if normalized not in HEARTBEAT_STATES:
        raise ValueError(f"invalid heartbeat status: {status}")
    heartbeat = AgentHeartbeat(agent_id=agent_id, status=normalized, current_task_id=str(current_task_id or ""), last_seen_at=_now())
    write_json_atomic(_heartbeat_path(project, agent_id), heartbeat.to_dict())
    _append_event(
        project,
        message_id="",
        task_id=heartbeat.current_task_id,
        agent_id=agent_id,
        event_type=EVENT_HEARTBEAT,
        status=normalized,
        payload=heartbeat.to_dict(),
    )
    return heartbeat


def detect_stale_heartbeat(project: str | Path, agent_id: str, *, stale_after_seconds: float = 60.0) -> AgentHeartbeat:
    _validate_agent_id(agent_id)
    path = _heartbeat_path(project, agent_id)
    if not path.exists():
        return AgentHeartbeat(agent_id=agent_id, status="stale", last_seen_at="")
    payload = json.loads(path.read_text(encoding="utf-8"))
    heartbeat = AgentHeartbeat(
        agent_id=str(payload.get("agent_id") or agent_id),
        status=str(payload.get("status") or "stale"),
        current_task_id=str(payload.get("current_task_id") or ""),
        last_seen_at=str(payload.get("last_seen_at") or ""),
    )
    if not heartbeat.last_seen_at or _now_seconds() - _parse_timestamp(heartbeat.last_seen_at) > float(stale_after_seconds):
        stale = AgentHeartbeat(agent_id=agent_id, status="stale", current_task_id=heartbeat.current_task_id, last_seen_at=heartbeat.last_seen_at)
        write_json_atomic(path, stale.to_dict())
        _append_event(project, message_id="", task_id=stale.current_task_id, agent_id=agent_id, event_type=EVENT_HEARTBEAT, status="stale", payload=stale.to_dict())
        return stale
    return heartbeat


def is_agent_stale(project: str | Path, agent_id: str, *, now: float | None = None, stale_seconds: float = DEFAULT_STALE_SECONDS) -> bool:
    _validate_agent_id(agent_id)
    path = _heartbeat_path(project, agent_id)
    if not path.exists():
        return True
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    status = str(payload.get("status") or "")
    if status in {"error", "stale"}:
        return True
    last_seen = _parse_timestamp(str(payload.get("last_seen_at") or ""))
    if last_seen <= 0:
        return True
    return float(_now_seconds() if now is None else now) - last_seen > float(stale_seconds)


def reclaim_expired(
    project: str | Path,
    agent_id: str,
    *,
    lease_seconds: float = DEFAULT_LEASE_SECONDS,
    stale_seconds: float = DEFAULT_STALE_SECONDS,
) -> list[AgentMessage]:
    project_path = Path(project).expanduser().resolve(strict=False)
    _validate_agent_id(agent_id)
    reclaimed: list[AgentMessage] = []
    with _state_lock(project_path):
        now = _now_seconds()
        events = read_jsonl(event_log(project_path))
        for message in read_inbox(project_path, agent_id, requester_agent=agent_id):
            if not _can_reclaim(project_path, message.id, events, now=now, stale_seconds=stale_seconds):
                continue
            lease = _create_lease(message.id, agent_id, lease_seconds, now=now)
            event = _append_event(
                project_path,
                message_id=message.id,
                task_id=message.task_id,
                agent_id=agent_id,
                event_type=EVENT_RUNNING,
                status=MESSAGE_RUNNING,
                payload=lease.to_dict(),
            )
            lease = MessageLease(
                lease_id=lease.lease_id,
                message_id=lease.message_id,
                claimed_by=lease.claimed_by,
                lease_expires_at=lease.lease_expires_at,
                created_at=lease.created_at,
                event_id=event.id,
            )
            reclaimed.append(_message_with_lease(message, lease))
            events.append(event.to_dict())
        if reclaimed:
            update_heartbeat(project_path, agent_id, status=MESSAGE_RUNNING, current_task_id=reclaimed[0].task_id)
        else:
            update_heartbeat(project_path, agent_id, status="idle", current_task_id="")
    return reclaimed


def watch_loop(
    project: str | Path,
    agent_id: str,
    *,
    interval: float = 2.0,
    max_iterations: int | None = None,
    requester_agent: str | None = None,
    lease_seconds: float = DEFAULT_LEASE_SECONDS,
) -> list[AgentMessage]:
    claimed: list[AgentMessage] = []
    iterations = 0
    while True:
        if max_iterations is not None and iterations >= max(0, int(max_iterations)):
            break
        iterations += 1
        message = poll_once(project, agent_id, requester_agent=requester_agent, lease_seconds=lease_seconds)
        if message is not None:
            claimed.append(message)
        elif interval > 0:
            time.sleep(float(interval))
    return claimed


def list_events(project: str | Path, *, task_id: str = "", message_id: str = "") -> list[dict[str, Any]]:
    rows = read_jsonl(event_log(project))
    if task_id:
        rows = [row for row in rows if str(row.get("task_id") or "") == task_id]
    if message_id:
        rows = [row for row in rows if str(row.get("message_id") or "") == message_id]
    return rows


def relay_status(project: str | Path, *, task_id: str) -> dict[str, Any]:
    if not task_id:
        raise ValueError("task_id is required")
    events = read_jsonl(event_log(project))
    messages = []
    agents: set[str] = set()
    for agent_dir in sorted(agents_root(project).glob("*")):
        if not agent_dir.is_dir():
            continue
        agent_id = agent_dir.name
        try:
            inbox = read_inbox(project, agent_id, requester_agent=agent_id)
        except (PermissionError, ValueError):
            continue
        for message in inbox:
            if message.task_id != task_id:
                continue
            agents.add(agent_id)
            active_lease = _active_lease_from_events(events, message.id)
            messages.append(
                {
                    **message.to_dict(),
                    "state": _message_state_from_events(events, message.id) or _initial_message_state(message),
                    "active_lease": active_lease.to_dict() if active_lease else None,
                    "last_event": _last_message_event(events, message.id),
                }
            )
    heartbeats = {agent_id: _heartbeat_snapshot(project, agent_id) for agent_id in sorted(agents)}
    return {"task_id": task_id, "messages": messages, "heartbeats": heartbeats, "last_event": _last_task_event(events, task_id)}


def run_demo(project: str | Path) -> dict[str, Any]:
    task_id = "relay-demo-" + uuid.uuid4().hex[:8]
    card = create_task_card(
        project,
        "Demonstrate Agent Bus handoff without real AI",
        task_id=task_id,
        scope_allowed=["quantagent/relay.py"],
        scope_forbidden=["long_context.md"],
        success_criteria=["demo reaches MERGE decision"],
        risk_level="low",
    )
    packet = {
        "task_id": task_id,
        "facts": [{"id": "F1", "text": "demo task card created", "source": "relay.demo"}],
        "inferences": [{"id": "I1", "fact_ids": ["F1"], "text": "executor can receive bounded handoff", "confidence": "high"}],
        "actions": [{"id": "A1", "inference_ids": ["I1"], "text": "send handoff to executor"}],
        "blocked": [],
    }
    parse_evidence_packet(packet)
    handoff = {
        "task_id": task_id,
        "lines": ["Process this synthetic demo handoff.", "Return a deterministic local result."],
        "allowed_files": [],
        "forbidden_files": ["long_context.md"],
        "success_criteria": ["executor marks done"],
    }
    sent = send_message(project, to_agent="executor", from_agent="diagnoser", message_type=MESSAGE_HANDOFF, task_id=task_id, payload=handoff)
    claimed = poll_once(project, "executor", requester_agent="executor", lease_seconds=60)
    if claimed is None:
        raise RuntimeError("demo executor did not claim handoff")
    done = mark_done(project, "executor", claimed.id, {"summary": "executor completed demo"}, lease_id=claimed.lease_id)
    review_payload = {
        "task_id": task_id,
        "task_card": card.to_dict(),
        "diff_summary": "no code diff in demo",
        "test_result": "synthetic pass",
        "changed_files": [],
    }
    review_msg = send_message(project, to_agent="reviewer", from_agent="executor", message_type=MESSAGE_REVIEW_REQUEST, task_id=task_id, payload=review_payload)
    review_claim = poll_once(project, "reviewer", requester_agent="reviewer", lease_seconds=60)
    if review_claim is None:
        raise RuntimeError("demo reviewer did not claim review request")
    review_done = mark_done(project, "reviewer", review_claim.id, {"summary": "review passed"}, lease_id=review_claim.lease_id)
    decision_payload = {"task_id": task_id, "status": "MERGE", "reason": "demo evidence and review passed", "evidence_ids": ["F1"]}
    parse_decision(decision_payload)
    decision_msg = send_message(project, to_agent="diagnoser", from_agent="reviewer", message_type=MESSAGE_DECISION, task_id=task_id, payload=decision_payload)
    return {
        "ok": True,
        "task_id": task_id,
        "card": card.to_dict(),
        "packet": packet,
        "handoff_message": sent.to_dict(),
        "executor_done": done.to_dict(),
        "review_message": review_msg.to_dict(),
        "review_done": review_done.to_dict(),
        "decision": decision_payload,
        "decision_message": decision_msg.to_dict(),
        "status": relay_status(project, task_id=task_id),
    }


def run_stress(
    project: str | Path,
    *,
    agents: Iterable[str],
    workers: int,
    messages: int,
    lease_seconds: float = 60.0,
) -> dict[str, Any]:
    project_path = Path(project).expanduser().resolve(strict=False)
    agent_list = [str(agent) for agent in agents if str(agent)]
    if not agent_list:
        raise ValueError("at least one agent is required")
    worker_count = max(1, int(workers))
    message_count = max(0, int(messages))
    stress_task_id = "relay-stress-" + uuid.uuid4().hex[:8]
    for index in range(message_count):
        agent = agent_list[index % len(agent_list)]
        send_message(
            project_path,
            to_agent=agent,
            from_agent="diagnoser",
            message_type=MESSAGE_HANDOFF,
            task_id=stress_task_id,
            payload={
                "task_id": stress_task_id,
                "lines": [f"stress message {index}"],
                "allowed_files": [],
                "forbidden_files": ["long_context.md"],
                "success_criteria": ["mark done"],
            },
            message_id=f"msg-{stress_task_id}-{index}",
        )
    queue: mp.Queue[dict[str, Any]] = mp.Queue()
    processes = [
        mp.Process(target=_stress_worker, args=(str(project_path), tuple(agent_list), lease_seconds, queue))
        for _ in range(worker_count)
    ]
    for process in processes:
        process.start()
    results: list[dict[str, Any]] = []
    for process in processes:
        process.join(timeout=30)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
    while not queue.empty():
        item = queue.get()
        if isinstance(item, dict):
            results.append(item)
    done_ids = [message_id for item in results for message_id in item.get("done", [])]
    duplicate_done = sorted({message_id for message_id in done_ids if done_ids.count(message_id) > 1})
    states = {f"msg-{stress_task_id}-{index}": get_message_state(project_path, f"msg-{stress_task_id}-{index}") for index in range(message_count)}
    worker_errors = [error for item in results for error in item.get("errors", [])]
    return {
        "ok": not worker_errors and not duplicate_done and all(state == MESSAGE_DONE for state in states.values()),
        "task_id": stress_task_id,
        "workers": worker_count,
        "messages": message_count,
        "done": len(done_ids),
        "unique_done": len(set(done_ids)),
        "duplicate_done": duplicate_done,
        "worker_errors": worker_errors,
        "states": states,
        "worker_results": results,
    }


def render_relay_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, AgentMessage):
        return value.to_dict()
    if isinstance(value, AgentHeartbeat):
        return value.to_dict()
    if isinstance(value, TaskCard):
        return value.to_dict()
    if isinstance(value, RelayEvent):
        return value.to_dict()
    if isinstance(value, dict):
        return value
    return {"value": value}


def _message_state_from_events(events: Iterable[dict[str, Any]], message_id: str) -> str:
    state = ""
    for event in events:
        if str(event.get("message_id") or "") != str(message_id):
            continue
        event_type = str(event.get("event_type") or "")
        if event_type in EVENTS_TO_STATE:
            state = EVENTS_TO_STATE[event_type]
    return state


def _active_lease_from_events(events: Iterable[dict[str, Any]], message_id: str) -> MessageLease | None:
    latest_running: dict[str, Any] | None = None
    state = ""
    for event in events:
        if str(event.get("message_id") or "") != str(message_id):
            continue
        event_type = str(event.get("event_type") or "")
        if event_type in EVENTS_TO_STATE:
            state = EVENTS_TO_STATE[event_type]
        if event_type == EVENT_RUNNING:
            latest_running = event
    if state != MESSAGE_RUNNING or not latest_running:
        return None
    payload = latest_running.get("payload") if isinstance(latest_running.get("payload"), dict) else {}
    lease_id = str(payload.get("lease_id") or "")
    claimed_by = str(payload.get("claimed_by") or latest_running.get("agent_id") or "")
    if not lease_id or not claimed_by:
        return None
    return MessageLease(
        lease_id=lease_id,
        message_id=str(payload.get("message_id") or message_id),
        claimed_by=claimed_by,
        lease_expires_at=float(payload.get("lease_expires_at") or 0.0),
        created_at=str(payload.get("created_at") or latest_running.get("created_at") or ""),
        event_id=str(latest_running.get("id") or ""),
    )


def _validate_active_lease(events: list[dict[str, Any]], message_id: str, *, lease_id: str, now: float) -> MessageLease:
    state = _message_state_from_events(events, message_id)
    if state != MESSAGE_RUNNING:
        raise ValueError(f"message cannot finish from state: {state or MESSAGE_UNREAD}")
    lease = _active_lease_from_events(events, message_id)
    if lease is None:
        raise ValueError("active lease is required")
    if lease_id and lease.lease_id != lease_id:
        raise ValueError("lease_id does not match active lease")
    if lease.expired(now):
        raise ValueError("active lease has expired")
    return lease


def _can_reclaim(project: str | Path, message_id: str, events: list[dict[str, Any]], *, now: float, stale_seconds: float) -> bool:
    if _message_state_from_events(events, message_id) != MESSAGE_RUNNING:
        return False
    lease = _active_lease_from_events(events, message_id)
    if lease is None or not lease.expired(now):
        return False
    return is_agent_stale(project, lease.claimed_by, now=now, stale_seconds=stale_seconds)


def _create_lease(message_id: str, agent_id: str, lease_seconds: float, *, now: float | None = None) -> MessageLease:
    timestamp = _now_seconds() if now is None else float(now)
    return MessageLease(
        lease_id="lease-" + uuid.uuid4().hex[:12],
        message_id=message_id,
        claimed_by=agent_id,
        lease_expires_at=timestamp + max(0.001, float(lease_seconds)),
        created_at=str(timestamp),
    )


def _message_with_lease(message: AgentMessage, lease: MessageLease) -> AgentMessage:
    return AgentMessage(
        id=message.id,
        task_id=message.task_id,
        from_agent=message.from_agent,
        to_agent=message.to_agent,
        type=message.type,
        payload=dict(message.payload),
        status=message.status,
        created_at=message.created_at,
        updated_at=message.updated_at,
        lease_id=lease.lease_id,
        lease_expires_at=lease.lease_expires_at,
    )


def _initial_message_state(message: AgentMessage) -> str:
    if message.status != MESSAGE_UNREAD:
        raise ValueError("inbox message status must remain unread; events are the state source")
    return MESSAGE_UNREAD


def _last_message_event(events: Iterable[dict[str, Any]], message_id: str) -> dict[str, Any] | None:
    latest = None
    for event in events:
        if str(event.get("message_id") or "") == message_id:
            latest = event
    return latest


def _last_task_event(events: Iterable[dict[str, Any]], task_id: str) -> dict[str, Any] | None:
    latest = None
    for event in events:
        if str(event.get("task_id") or "") == task_id:
            latest = event
    return latest


def _heartbeat_snapshot(project: str | Path, agent_id: str) -> dict[str, Any]:
    path = _heartbeat_path(project, agent_id)
    if not path.exists():
        return AgentHeartbeat(agent_id=agent_id, status="stale", last_seen_at="").to_dict()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AgentHeartbeat(agent_id=agent_id, status="stale", last_seen_at="").to_dict()
    return payload if isinstance(payload, dict) else AgentHeartbeat(agent_id=agent_id, status="stale", last_seen_at="").to_dict()


def _stress_worker(project: str, agents: tuple[str, ...], lease_seconds: float, queue: Any) -> None:
    done: list[str] = []
    errors: list[str] = []
    empty_rounds = 0
    while empty_rounds < 3:
        claimed = None
        for agent_id in agents:
            try:
                claimed = poll_once(project, agent_id, requester_agent=agent_id, lease_seconds=lease_seconds)
            except RuntimeError:
                time.sleep(0.01)
                continue
            except Exception as exc:
                errors.append(f"{agent_id}:{type(exc).__name__}:{exc}")
                continue
            if claimed is not None:
                try:
                    mark_done(project, agent_id, claimed.id, {"summary": "stress done"}, lease_id=claimed.lease_id)
                    done.append(claimed.id)
                except Exception as exc:
                    errors.append(f"{claimed.id}:{type(exc).__name__}:{exc}")
                break
        if claimed is None:
            empty_rounds += 1
            time.sleep(0.01)
        else:
            empty_rounds = 0
    queue.put({"pid": os.getpid(), "done": done, "errors": errors})


def _validate_payload_for_message(message_type: str, to_agent: str, payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("message payload must be a JSON object")
    _ensure_no_shared_chat_reference(payload)
    if to_agent == "executor":
        if message_type in {MESSAGE_TASK, MESSAGE_HANDOFF}:
            if "actions" in payload or "facts" in payload or "inferences" in payload:
                parse_evidence_packet(payload)
            elif "lines" in payload:
                parse_handoff(payload)
            else:
                raise ValueError("executor payload must be a valid EvidencePacket or Handoff")
    if message_type == MESSAGE_HANDOFF:
        parse_handoff(payload)
    elif message_type == MESSAGE_REVIEW_REQUEST:
        parse_blind_review(payload)
    elif message_type == MESSAGE_DECISION:
        parse_decision(payload)
    elif message_type == MESSAGE_ERROR:
        _ensure_no_shared_chat_reference(payload)
    elif message_type == MESSAGE_TASK and "actions" in payload:
        parse_evidence_packet(payload)


def _append_event(
    project: str | Path,
    *,
    message_id: str,
    task_id: str,
    agent_id: str,
    event_type: str,
    status: str,
    payload: dict[str, Any] | None = None,
) -> RelayEvent:
    event = RelayEvent(
        id="evt-" + uuid.uuid4().hex[:12],
        message_id=str(message_id or ""),
        task_id=str(task_id or ""),
        agent_id=str(agent_id or ""),
        event_type=event_type,
        status=status,
        created_at=_now(),
        payload=payload or {},
    )
    append_jsonl(event_log(project), event.to_dict())
    return event


def _message_with_state(project: str | Path, message: AgentMessage) -> dict[str, Any]:
    payload = message.to_dict()
    payload["state"] = get_message_state(project, message.id)
    return payload


def _message_for_agent(project: str | Path, agent_id: str, message_id: str) -> AgentMessage:
    _validate_agent_id(agent_id)
    for message in read_inbox(project, agent_id, requester_agent=agent_id):
        if message.id == message_id:
            return message
    raise KeyError(f"message not found in {agent_id} inbox: {message_id}")


def _find_message(project: str | Path, message_id: str) -> AgentMessage | None:
    for agent_dir in agents_root(project).glob("*"):
        inbox = agent_dir / "inbox.jsonl"
        if not inbox.exists():
            continue
        for row in read_jsonl(inbox):
            if str(row.get("id") or "") == message_id:
                return _message_from_dict(row)
    return None


def _message_id_exists(project: str | Path, message_id: str) -> bool:
    if not message_id:
        return False
    return _find_message(project, message_id) is not None


def _message_from_dict(data: dict[str, Any]) -> AgentMessage:
    return AgentMessage(
        id=str(data.get("id") or ""),
        task_id=str(data.get("task_id") or ""),
        from_agent=str(data.get("from_agent") or ""),
        to_agent=str(data.get("to_agent") or ""),
        type=str(data.get("type") or ""),
        payload=data.get("payload") if isinstance(data.get("payload"), dict) else {},
        status=str(data.get("status") or MESSAGE_UNREAD),
        created_at=str(data.get("created_at") or ""),
        updated_at=str(data.get("updated_at") or ""),
        lease_id=str(data.get("lease_id") or ""),
        lease_expires_at=float(data.get("lease_expires_at") or 0.0),
    )


def _inbox_path(project: str | Path, agent_id: str) -> Path:
    _validate_agent_id(agent_id)
    return agents_root(project) / agent_id / "inbox.jsonl"


def _outbox_path(project: str | Path, agent_id: str) -> Path:
    _validate_agent_id(agent_id)
    return agents_root(project) / agent_id / "outbox.jsonl"


def _heartbeat_path(project: str | Path, agent_id: str) -> Path:
    _validate_agent_id(agent_id)
    return agents_root(project) / agent_id / "heartbeat.json"


def _lock_path(project: str | Path, agent_id: str) -> Path:
    _validate_agent_id(agent_id)
    return agents_root(project) / agent_id / "poll.lock"


class _state_lock:
    def __init__(self, project: Path, *, ttl_seconds: float = DEFAULT_LOCK_TTL_SECONDS, wait_seconds: float = 5.0) -> None:
        self.path = state_lock_path(project)
        self.ttl_seconds = ttl_seconds
        self.wait_seconds = wait_seconds
        self.fd: int | None = None

    def __enter__(self) -> "_state_lock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = _now_seconds() + max(0.0, self.wait_seconds)
        while True:
            try:
                if self.path.exists() and _now_seconds() - self.path.stat().st_mtime > self.ttl_seconds:
                    self.path.unlink(missing_ok=True)
            except FileNotFoundError:
                pass
            try:
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, str(os.getpid()).encode("utf-8"))
                return self
            except FileExistsError as exc:
                if _now_seconds() >= deadline:
                    raise RuntimeError("relay state lock is already held") from exc
                time.sleep(0.005)

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        self.path.unlink(missing_ok=True)


class _agent_lock:
    def __init__(self, project: Path, agent_id: str, *, ttl_seconds: float) -> None:
        self.path = _lock_path(project, agent_id)
        self.ttl_seconds = ttl_seconds
        self.fd: int | None = None

    def __enter__(self) -> "_agent_lock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and _now_seconds() - self.path.stat().st_mtime > self.ttl_seconds:
            self.path.unlink(missing_ok=True)
        try:
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError("agent poll lock is already held") from exc
        os.write(self.fd, str(os.getpid()).encode("utf-8"))
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        self.path.unlink(missing_ok=True)


def _require_same_agent(agent_id: str, requester_agent: str | None) -> None:
    _validate_agent_id(agent_id)
    if requester_agent is None:
        raise PermissionError("requester_agent is required")
    if requester_agent != agent_id:
        raise PermissionError(f"agent {requester_agent} cannot read {agent_id} inbox")


def _validate_agent_id(agent_id: str, *, allow_user: bool = False) -> None:
    text = str(agent_id or "")
    if allow_user and text == "user":
        return
    if not text or "/" in text or "\\" in text or text.startswith(".") or ".." in text:
        raise ValueError(f"invalid agent_id: {agent_id}")


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _find_keys(value: Any, keys: set[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in keys:
                found.add(str(key))
            found.update(_find_keys(item, keys))
    elif isinstance(value, list):
        for item in value:
            found.update(_find_keys(item, keys))
    return found


def _ensure_no_shared_chat_reference(value: Any) -> None:
    if _contains_shared_chat(value):
        raise ValueError("shared_chat.md is forbidden; relay files are message queues, not chat")


def _contains_shared_chat(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_shared_chat(key) or _contains_shared_chat(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_shared_chat(item) for item in value)
    return FORBIDDEN_SHARED_CHAT in str(value).lower()


def _reject_shared_chat_path(path: Path) -> None:
    lowered = str(path).lower()
    if path.name.lower() == FORBIDDEN_SHARED_CHAT or FORBIDDEN_SHARED_CHAT in lowered:
        raise ValueError("shared_chat.md is forbidden")


def _now() -> str:
    return str(_now_seconds())


def _now_seconds() -> float:
    return time.time()


def _parse_timestamp(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return 0.0
