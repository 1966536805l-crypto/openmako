from __future__ import annotations

import json
import inspect
import hashlib
import time
import uuid
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


CONTROL_ACTIONS = frozenset({"activate", "open", "click", "grid-click", "som-click", "move", "type", "hotkey"})
TERMINAL_DECISION_STATUSES = frozenset({"done", "completed", "hold", "noop", "no_match", "skipped"})
POST_ACTION_VERIFY_ACTIONS = frozenset({"click", "type", "hotkey"})


@dataclass(frozen=True)
class DesktopDaemonRecord:
    step: int
    phase: str
    status: str
    summary: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DesktopDaemonResult:
    ok: bool
    status: str
    summary: str
    goal: str
    records: tuple[DesktopDaemonRecord, ...]
    results: tuple[dict[str, Any], ...]
    query_events_path: str
    trajectory_path: str
    stop_file: str
    state_path: str
    run_dir: str
    query_id: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "summary": self.summary,
            "goal": self.goal,
            "records": [record.to_payload() for record in self.records],
            "results": list(self.results),
            "query_events_path": self.query_events_path,
            "trajectory_path": self.trajectory_path,
            "stop_file": self.stop_file,
            "state_path": self.state_path,
            "run_dir": self.run_dir,
            "query_id": self.query_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False, indent=2)


@dataclass
class DesktopDaemonContext:
    project: Path
    goal: str
    run_dir: Path
    query_events_path: Path
    trajectory_path: Path
    state_path: Path
    stop_file: Path
    query_id: str
    execute: bool = False
    reviewed: bool = False
    allow_actions: bool = False
    max_steps: int = 20
    max_minutes: float = 30.0
    delay: float = 0.0
    step: int = 0
    started_monotonic: float = 0.0
    deadline_monotonic: float = 0.0
    last_observation: dict[str, Any] = field(default_factory=dict)
    last_tokens: dict[str, Any] = field(default_factory=dict)
    last_decision: dict[str, Any] = field(default_factory=dict)
    last_action_result: dict[str, Any] = field(default_factory=dict)

    @property
    def dry_run(self) -> bool:
        return not (self.execute and self.reviewed and self.allow_actions)


@dataclass(frozen=True)
class _DesktopSnapshot:
    has_state: bool
    screen_hash: str = ""
    token_signature: str = ""
    focus_signature: str = ""
    target_hashes: dict[str, str] = field(default_factory=dict)
    text: str = ""


Hook = Callable[..., Any]


def run_desktop_daemon_core(
    project: str | Path,
    goal: str,
    *,
    observe: Hook | None = None,
    tokenize: Hook | None = None,
    decide: Hook | None = None,
    act: Hook | None = None,
    verify: Hook | None = None,
    execute: bool = False,
    reviewed: bool = False,
    allow_actions: bool = False,
    max_steps: int = 20,
    max_minutes: float = 30.0,
    delay: float = 0.0,
    stop_file: str | Path | None = None,
    run_dir: str | Path | None = None,
    query_events_path: str | Path | None = None,
    trajectory_path: str | Path | None = None,
    state_path: str | Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> DesktopDaemonResult:
    """Run the injectable desktop daemon loop.

    The core is intentionally stdlib-only. Callers inject desktop-specific
    observe/tokenize/decide/act/verify functions and can unit-test every phase
    without importing GUI, OCR, model, or OS automation modules.
    """

    project_path = Path(project).expanduser().resolve(strict=False)
    resolved_run_dir = Path(run_dir).expanduser() if run_dir is not None else project_path / ".quantagent" / "desktop" / "daemon_core"
    if not resolved_run_dir.is_absolute():
        resolved_run_dir = project_path / resolved_run_dir
    resolved_run_dir.mkdir(parents=True, exist_ok=True)

    q_events = _resolve_path(project_path, query_events_path, resolved_run_dir / "query_events.jsonl")
    trajectory = _resolve_path(project_path, trajectory_path, resolved_run_dir / "trajectory.jsonl")
    state = _resolve_path(project_path, state_path, resolved_run_dir / "latest_state.json")
    stop_path = _resolve_path(project_path, stop_file, project_path / ".quantagent" / "desktop" / "STOP")

    bounded_steps = max(1, min(int(max_steps), 10000))
    bounded_minutes = max(0.0, float(max_minutes))
    bounded_delay = max(0.0, float(delay))
    query_id = "qa-" + uuid.uuid4().hex[:12]
    now = monotonic()
    context = DesktopDaemonContext(
        project=project_path,
        goal=" ".join(str(goal).strip().split()),
        run_dir=resolved_run_dir,
        query_events_path=q_events,
        trajectory_path=trajectory,
        state_path=state,
        stop_file=stop_path,
        query_id=query_id,
        execute=bool(execute),
        reviewed=bool(reviewed),
        allow_actions=bool(allow_actions),
        max_steps=bounded_steps,
        max_minutes=bounded_minutes,
        delay=bounded_delay,
        started_monotonic=now,
        deadline_monotonic=now + (bounded_minutes * 60.0),
    )
    records: list[DesktopDaemonRecord] = []
    results: list[dict[str, Any]] = []

    observe_fn = observe or _default_observe
    tokenize_fn = tokenize or _default_tokenize
    decide_fn = decide or _default_decide
    act_fn = act or _default_act
    verify_fn = verify or _default_verify

    _emit_query_event(
        q_events,
        "query_start",
        query_id,
        f"query started: {context.goal}",
        data={
            "task": context.goal,
            "mode": "desktop_daemon_core",
            "execute": context.execute,
            "reviewed": context.reviewed,
            "allow_actions": context.allow_actions,
            "max_steps": bounded_steps,
            "max_minutes": bounded_minutes,
            "stop_file": str(stop_path),
        },
    )
    _write_state(context, records, results, status="running", summary="desktop daemon core started")

    for step_no in range(1, bounded_steps + 1):
        context.step = step_no
        if stop_path.exists():
            return _finish(context, records, results, ok=False, status="stopped", summary=f"STOP file present before step {step_no}: {stop_path}")
        if monotonic() >= context.deadline_monotonic:
            return _finish(context, records, results, ok=True, status="time_budget_exhausted", summary=f"daemon exhausted {bounded_minutes:g} minute budget before step {step_no}")

        observation = _call_hook(observe_fn, context)
        observation_payload = _normalize_phase_payload(observation, default_status="ok", default_summary="observed")
        context.last_observation = observation_payload
        _record_phase(context, records, "observe", observation_payload, query_kind="pre_tool", trajectory_kind="observation")
        if not observation_payload["ok"]:
            return _finish(context, records, results, ok=False, status="observe_failed", summary=f"observe failed at step {step_no}: {observation_payload['summary']}")

        tokens = _call_hook(tokenize_fn, observation_payload, context)
        token_payload = _normalize_phase_payload(tokens, default_status="ok", default_summary="tokenized")
        context.last_tokens = token_payload
        _record_phase(context, records, "tokenize", token_payload, query_kind="post_tool", trajectory_kind="observation")
        if not token_payload["ok"]:
            return _finish(context, records, results, ok=False, status="tokenize_failed", summary=f"tokenize failed at step {step_no}: {token_payload['summary']}")

        decision = _call_hook(decide_fn, token_payload, context)
        decision_payload = _normalize_decision(decision)
        context.last_decision = decision_payload
        _record_phase(context, records, "decide", decision_payload, query_kind="post_tool", trajectory_kind="action")

        decision_status = decision_payload["status"]
        if not decision_payload["ok"] or decision_status == "blocked":
            return _finish(context, records, results, ok=False, status="blocked", summary=decision_payload["summary"])
        if _is_terminal_decision(decision_payload):
            return _finish(context, records, results, ok=True, status="completed", summary=decision_payload["summary"] or "daemon reached hold state")

        needs = _execution_needs(decision_payload, context)
        if needs:
            skipped = {
                "ok": True,
                "status": "skipped",
                "summary": "side-effect action skipped; needs " + ", ".join(needs),
                "needs": needs,
                "decision": decision_payload,
            }
            _record_phase(context, records, "act", skipped, query_kind="post_tool", trajectory_kind="action")
            return _finish(context, records, results, ok=True, status="dry_run", summary=skipped["summary"])

        _emit_query_event(q_events, "pre_tool", query_id, f"tool start: desktop_daemon_core.{decision_payload['action']}", step=step_no, name="desktop_daemon_core", data={"args": decision_payload})
        action_result = _call_hook(act_fn, decision_payload, context)
        action_payload = _normalize_phase_payload(action_result, default_status="ok", default_summary="acted")
        context.last_action_result = action_payload
        results.append(action_payload)
        _record_phase(context, records, "act", action_payload, query_kind="post_tool", trajectory_kind="action")
        if not action_payload["ok"]:
            return _finish(context, records, results, ok=False, status="action_failed", summary=f"action failed at step {step_no}: {action_payload['summary']}")

        verification = _call_hook(verify_fn, action_payload, decision_payload, context)
        verify_payload = _normalize_phase_payload(verification, default_status="ok", default_summary="verified")
        verify_payload = _enforce_post_action_progress(action_payload, decision_payload, context, verify_payload)
        _record_phase(context, records, "verify", verify_payload, query_kind="post_tool", trajectory_kind="observation")
        if not verify_payload["ok"]:
            return _finish(context, records, results, ok=False, status="verify_failed", summary=f"verify failed at step {step_no}: {verify_payload['summary']}")
        if verify_payload["status"] in {"done", "completed", "hold"}:
            return _finish(context, records, results, ok=True, status="completed", summary=verify_payload["summary"] or "daemon verified completion")

        _write_state(context, records, results, status="running", summary=verify_payload["summary"])
        if step_no < bounded_steps and bounded_delay > 0:
            sleep(bounded_delay)

    return _finish(context, records, results, ok=True, status="step_budget_exhausted", summary=f"daemon exhausted {bounded_steps} step(s) without terminal hold")


run_desktop_daemon = run_desktop_daemon_core


def _default_observe(context: DesktopDaemonContext) -> dict[str, Any]:
    return {"ok": True, "status": "ok", "summary": "no-op observation", "data": {"step": context.step}}


def _default_tokenize(observation: Mapping[str, Any], context: DesktopDaemonContext) -> dict[str, Any]:
    return {"ok": True, "status": "ok", "summary": "no-op tokenization", "tokens": (), "observation": observation}


def _default_decide(tokens: Mapping[str, Any], context: DesktopDaemonContext) -> dict[str, Any]:
    return {"ok": True, "status": "hold", "action": "hold", "summary": "no-op daemon hold", "tokens": tokens}


def _default_act(decision: Mapping[str, Any], context: DesktopDaemonContext) -> dict[str, Any]:
    return {"ok": True, "status": "ok", "summary": "no-op action", "decision": decision}


def _default_verify(action_result: Mapping[str, Any], decision: Mapping[str, Any], context: DesktopDaemonContext) -> dict[str, Any]:
    return {"ok": True, "status": "ok", "summary": "no-op verification", "result": action_result, "decision": decision}


def _enforce_post_action_progress(
    action_result: Mapping[str, Any],
    decision: Mapping[str, Any],
    context: DesktopDaemonContext,
    verify_payload: dict[str, Any],
) -> dict[str, Any]:
    action = str(decision.get("action") or "").strip().lower()
    if action not in POST_ACTION_VERIFY_ACTIONS or not bool(verify_payload.get("ok", True)):
        return verify_payload
    before = _desktop_snapshot_from_payload(context.last_tokens)
    after = _post_action_snapshot(action_result, verify_payload)
    target_id = _decision_target_id(decision)
    expected_target_hash = str(_decision_args(decision).get("target_hash") or decision.get("target_hash") or "")
    progress: dict[str, Any] = {
        "action": action,
        "before_screen_hash": _short_hash(before.screen_hash),
        "after_screen_hash": _short_hash(after.screen_hash),
        "screen_hash_changed": bool(before.screen_hash and after.screen_hash and before.screen_hash != after.screen_hash),
        "before_token_signature": _short_hash(before.token_signature),
        "after_token_signature": _short_hash(after.token_signature),
        "token_tree_changed": bool(before.token_signature and after.token_signature and before.token_signature != after.token_signature),
        "before_focus_signature": _short_hash(before.focus_signature),
        "after_focus_signature": _short_hash(after.focus_signature),
        "focus_changed": bool(before.focus_signature and after.focus_signature and before.focus_signature != after.focus_signature),
        "target_id": target_id,
    }
    target_changed = False
    if target_id:
        current_target_hash = after.target_hashes.get(target_id, "")
        progress["target_disappeared"] = before.target_hashes.get(target_id, "") != "" and current_target_hash == ""
        progress["target_hash_changed"] = bool(expected_target_hash and current_target_hash and current_target_hash != expected_target_hash)
        target_changed = bool(progress["target_disappeared"] or progress["target_hash_changed"])
    typed_visible = False
    if action == "type":
        typed = str(_decision_args(decision).get("text") or "")
        typed_visible = bool(typed and _normalize_text(typed) in after.text)
        progress["typed_text_visible"] = typed_visible
    changed = bool(
        progress["screen_hash_changed"]
        or progress["token_tree_changed"]
        or progress["focus_changed"]
        or target_changed
        or typed_visible
    )
    merged = dict(verify_payload)
    merged["post_action_progress"] = progress
    if changed:
        return merged
    reason = "post-action verify failed: no screen_hash, token tree, focus, or target-state progress after " + action
    if not before.has_state or not after.has_state:
        reason = "post-action verify failed: missing comparable desktop state after " + action
    merged.update({"ok": False, "status": "verify_failed", "summary": reason})
    return merged


def _post_action_snapshot(action_result: Mapping[str, Any], verify_payload: Mapping[str, Any]) -> _DesktopSnapshot:
    for payload in _snapshot_candidates(verify_payload) + _snapshot_candidates(action_result):
        snapshot = _desktop_snapshot_from_payload(payload)
        if snapshot.has_state:
            return snapshot
    return _DesktopSnapshot(False)


def _snapshot_candidates(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    candidates: list[Mapping[str, Any]] = [payload]
    for key in ("after", "current", "post", "post_action", "tokenization", "tokens", "observation", "state", "data", "result"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            candidates.append(value)
        elif isinstance(value, (list, tuple)):
            candidates.append({"tokens": value})
    return candidates


def _desktop_snapshot_from_payload(payload: Mapping[str, Any]) -> _DesktopSnapshot:
    tokens = _extract_tokens(payload)
    screen_hash = str(payload.get("screen_hash") or payload.get("screenshot_hash") or "")
    token_signature = _tokens_signature(tokens) if tokens else ""
    focus_signature = _focus_signature(tokens) if tokens else ""
    target_hashes = {_token_id(token): _token_hash(token) for token in tokens if _token_id(token)}
    text = " ".join(_normalize_text(str(_token_value(token, "text") or _token_value(token, "label") or "")) for token in tokens)
    return _DesktopSnapshot(bool(screen_hash or tokens), screen_hash, token_signature, focus_signature, target_hashes, text)


def _extract_tokens(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = payload.get("tokens")
    if not isinstance(raw, (list, tuple)):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _tokens_signature(tokens: list[Mapping[str, Any]]) -> str:
    return hashlib.sha256(json.dumps([_token_hash(token) for token in tokens], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _focus_signature(tokens: list[Mapping[str, Any]]) -> str:
    focused = []
    for token in tokens:
        raw = token.get("raw") if isinstance(token.get("raw"), Mapping) else {}
        if _truthy_state(token.get("focused") or token.get("focus") or raw.get("focused") or raw.get("focus") or token.get("selected") or raw.get("selected")):
            focused.append(
                {
                    "token_id": _token_id(token),
                    "text": str(_token_value(token, "text") or _token_value(token, "label") or ""),
                    "role": str(_token_value(token, "role") or ""),
                    "center": token.get("center"),
                }
            )
    return hashlib.sha256(json.dumps(focused, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _token_hash(token: Mapping[str, Any]) -> str:
    raw = token.get("raw") if isinstance(token.get("raw"), Mapping) else {}
    payload = {
        "token_id": _token_id(token),
        "text": str(_token_value(token, "text") or _token_value(token, "label") or ""),
        "role": str(_token_value(token, "role") or ""),
        "source": str(_token_value(token, "source") or ""),
        "bbox": token.get("bbox") or token.get("bounds"),
        "center": token.get("center"),
        "clickable": bool(token.get("clickable")),
        "state": {
            key: str(raw.get(key) or token.get(key) or "")
            for key in ("value", "enabled", "focused", "selected", "checked", "expanded")
            if (raw.get(key) if key in raw else token.get(key)) not in (None, "")
        },
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _token_id(token: Mapping[str, Any]) -> str:
    return str(token.get("token_id") or token.get("id") or "")


def _token_value(token: Mapping[str, Any], key: str) -> Any:
    if key in token:
        return token.get(key)
    raw = token.get("raw")
    if isinstance(raw, Mapping):
        return raw.get(key)
    return None


def _decision_args(decision: Mapping[str, Any]) -> Mapping[str, Any]:
    args = decision.get("args")
    return args if isinstance(args, Mapping) else decision


def _decision_target_id(decision: Mapping[str, Any]) -> str:
    args = _decision_args(decision)
    return str(decision.get("target_id") or args.get("target_id") or "")


def _truthy_state(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "selected", "focused"}


def _short_hash(value: str) -> str:
    return str(value or "")[:12]


def _normalize_text(text: str) -> str:
    return " ".join(str(text).strip().lower().split())


def _call_hook(func: Hook, *args: Any) -> Any:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return func(*args)
    positional = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
    ]
    if any(parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in signature.parameters.values()):
        return func(*args)
    if positional:
        return func(*args[: len(positional)])
    return func()


def _normalize_decision(value: Any) -> dict[str, Any]:
    payload = _to_payload(value)
    action = str(payload.get("action") or "")
    status = str(payload.get("status") or ("action" if action else "hold"))
    summary = str(payload.get("summary") or payload.get("reason") or status)
    ok = bool(payload.get("ok", status != "blocked"))
    normalized = _json_safe_dict(payload)
    normalized.update({"ok": ok, "status": status, "summary": summary, "action": action})
    if "side_effect" not in normalized and "has_side_effect" in normalized:
        normalized["side_effect"] = bool(normalized["has_side_effect"])
    return normalized


def _normalize_phase_payload(value: Any, *, default_status: str, default_summary: str) -> dict[str, Any]:
    payload = _to_payload(value)
    status = str(payload.get("status") or default_status)
    summary = str(payload.get("summary") or payload.get("reason") or default_summary)
    ok = bool(payload.get("ok", status not in {"failed", "blocked", "error"}))
    normalized = _json_safe_dict(payload)
    normalized.update({"ok": ok, "status": status, "summary": summary})
    return normalized


def _to_payload(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_payload") and callable(value.to_payload):
        payload = value.to_payload()
        if isinstance(payload, Mapping):
            return dict(payload)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {"value": value}


def _is_terminal_decision(decision: Mapping[str, Any]) -> bool:
    action = str(decision.get("action") or "").strip().lower()
    status = str(decision.get("status") or "").strip().lower()
    return status in TERMINAL_DECISION_STATUSES or action in {"", "hold", "noop", "none"}


def _decision_has_side_effect(decision: Mapping[str, Any]) -> bool:
    explicit = decision.get("side_effect")
    if explicit is None:
        explicit = decision.get("has_side_effect")
    if explicit is not None:
        return bool(explicit)
    action = str(decision.get("action") or "").strip().lower()
    return action not in {"", "hold", "noop", "none", "wait", "sleep", "observe", "tokenize", "verify"}


def _execution_needs(decision: Mapping[str, Any], context: DesktopDaemonContext) -> list[str]:
    if not _decision_has_side_effect(decision):
        return []
    needs: list[str] = []
    if not context.execute:
        needs.append("--execute")
    if not context.reviewed:
        needs.append("--reviewed")
    if not context.allow_actions:
        needs.append("--allow-actions")
    return needs


def _record_phase(
    context: DesktopDaemonContext,
    records: list[DesktopDaemonRecord],
    phase: str,
    payload: Mapping[str, Any],
    *,
    query_kind: str,
    trajectory_kind: str,
) -> None:
    status = str(payload.get("status") or "")
    summary = str(payload.get("summary") or status)
    ok = bool(payload.get("ok", True))
    data = _json_safe_dict({key: value for key, value in payload.items() if key not in {"ok", "status", "summary"}})
    records.append(DesktopDaemonRecord(context.step, phase, status, summary, data))
    name = "desktop_daemon_core" if query_kind in {"pre_tool", "post_tool"} else ""
    _emit_query_event(context.query_events_path, query_kind, context.query_id, summary, step=context.step, name=name, ok=ok, data={"phase": phase, **data})
    _emit_trajectory_event(context.trajectory_path, trajectory_kind, f"desktop-daemon-core step {context.step} {phase}: {summary}", step=context.step, ok=ok, meta={"phase": phase, **data})
    _write_state(context, records, (), status="running", summary=summary)


def _finish(
    context: DesktopDaemonContext,
    records: list[DesktopDaemonRecord],
    results: list[dict[str, Any]],
    *,
    ok: bool,
    status: str,
    summary: str,
) -> DesktopDaemonResult:
    _write_state(context, records, results, status=status, summary=summary)
    _emit_query_event(context.query_events_path, "stop" if ok else "stop_failure", context.query_id, summary, ok=ok, data={"failure_class": "" if ok else status})
    _emit_trajectory_event(context.trajectory_path, "step", f"desktop-daemon-core finished: {summary}", step=context.step or None, ok=ok, meta={"status": status})
    return DesktopDaemonResult(
        ok=ok,
        status=status,
        summary=summary,
        goal=context.goal,
        records=tuple(records),
        results=tuple(results),
        query_events_path=str(context.query_events_path),
        trajectory_path=str(context.trajectory_path),
        stop_file=str(context.stop_file),
        state_path=str(context.state_path),
        run_dir=str(context.run_dir),
        query_id=context.query_id,
    )


def _write_state(
    context: DesktopDaemonContext,
    records: list[DesktopDaemonRecord],
    results: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    status: str,
    summary: str,
) -> None:
    context.state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ok": status not in {"blocked", "failed", "stopped", "observe_failed", "tokenize_failed", "action_failed", "verify_failed"},
        "status": status,
        "summary": summary,
        "goal": context.goal,
        "step": context.step,
        "max_steps": context.max_steps,
        "max_minutes": context.max_minutes,
        "dry_run": context.dry_run,
        "execute": context.execute,
        "reviewed": context.reviewed,
        "allow_actions": context.allow_actions,
        "stop_file": str(context.stop_file),
        "query_events_path": str(context.query_events_path),
        "trajectory_path": str(context.trajectory_path),
        "records": [record.to_payload() for record in records],
        "results": list(results),
        "updated_at": _utc_timestamp(),
    }
    context.state_path.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _emit_query_event(
    path: Path,
    kind: str,
    query_id: str,
    summary: str,
    *,
    step: int | None = None,
    name: str = "",
    ok: bool | None = None,
    data: Mapping[str, Any] | None = None,
) -> None:
    payload = {
        "kind": kind,
        "query_id": query_id,
        "summary": summary[:500],
        "step": step,
        "name": name,
        "ok": ok,
        "timestamp": _utc_timestamp(),
        "data": _json_safe_dict(data or {}),
    }
    _append_jsonl(path, payload)


def _emit_trajectory_event(
    path: Path,
    kind: str,
    content: str,
    *,
    step: int | None = None,
    ok: bool | None = None,
    meta: Mapping[str, Any] | None = None,
) -> None:
    payload = {
        "kind": kind,
        "content": content,
        "step": step,
        "ok": ok,
        "timestamp": _utc_timestamp(),
        "meta": _json_safe_dict(meta or {}),
    }
    _append_jsonl(path, payload)


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_json_safe(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def _resolve_path(project: Path, value: str | Path | None, default: Path) -> Path:
    path = Path(value).expanduser() if value is not None else default
    if not path.is_absolute():
        path = project / path
    return path


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_safe_dict(data: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_safe(value) for key, value in sorted(data.items(), key=lambda item: str(item[0]))}


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _json_safe_dict(value)
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if is_dataclass(value):
        return _json_safe(asdict(value))
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True)
        return value
    except TypeError:
        return str(value)
