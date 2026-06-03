from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .task_state import ABORTED, BLOCKED, FAILED, LOST, PASSED, RUNNING, ResearchTask, task_dir
from .token_accounting import env_budget_limits, estimate_cost_usd, evaluate_budget_limits


SCHEMA_VERSION = 1
TERMINAL_STATUSES = {PASSED, FAILED, BLOCKED, ABORTED, LOST}
RUNTIME_QUEUE_QUEUED = "queued"
RUNTIME_QUEUE_RUNNING = "running"
RUNTIME_QUEUE_PAUSED = "paused"
RUNTIME_QUEUE_FAILED = "failed"
RUNTIME_QUEUE_DONE = "done"
RUNTIME_QUEUE_STOPPED = "stopped"
RUNTIME_QUEUE_BLOCKED = "blocked"
RUNTIME_QUEUE_LOST = "lost"
RUNTIME_QUEUE_STATUSES = {
    RUNTIME_QUEUE_QUEUED,
    RUNTIME_QUEUE_RUNNING,
    RUNTIME_QUEUE_PAUSED,
    RUNTIME_QUEUE_FAILED,
    RUNTIME_QUEUE_DONE,
    RUNTIME_QUEUE_STOPPED,
    RUNTIME_QUEUE_BLOCKED,
    RUNTIME_QUEUE_LOST,
}
RUNTIME_QUEUE_TERMINAL_STATUSES = {RUNTIME_QUEUE_DONE, RUNTIME_QUEUE_STOPPED, RUNTIME_QUEUE_BLOCKED, RUNTIME_QUEUE_LOST}


@dataclass(frozen=True)
class TaskRunRecord:
    task_id: str
    runtime: str
    task_kind: str
    task: str
    status: str
    delivery_status: str
    notify_policy: str
    created_at: int
    started_at: int | None = None
    ended_at: int | None = None
    cleanup_after: int | None = None
    owner_key: str = "local"
    scope_kind: str = "project"
    requester_session_key: str | None = None
    child_session_key: str | None = None
    parent_flow_id: str | None = None
    parent_task_id: str | None = None
    agent_id: str | None = None
    run_id: str | None = None
    label: str | None = None
    error: str | None = None
    progress_summary: str | None = None
    terminal_summary: str | None = None
    terminal_outcome: str | None = None


@dataclass(frozen=True)
class RuntimeQueueItem:
    task_id: str
    task: str
    status: str
    queue: str = "default"
    task_kind: str = "manual"
    priority: int = 50
    owner_key: str = "local"
    lease_owner: str | None = None
    lease_expires_at: int | None = None
    heartbeat_at: int | None = None
    session_lock_key: str | None = None
    stop_file: str | None = None
    resume_of: str | None = None
    attempts: int = 0
    max_attempts: int = 1
    created_at: int = 0
    updated_at: int = 0
    started_at: int | None = None
    ended_at: int | None = None
    summary: str = ""
    error: str = ""
    payload_json: str = "{}"

    @property
    def item_id(self) -> str:
        return self.task_id

    @property
    def id(self) -> str:
        return self.task_id

    @property
    def payload(self) -> dict[str, Any]:
        try:
            value = json.loads(self.payload_json or "{}")
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["item_id"] = self.item_id
        data["id"] = self.id
        data["payload"] = self.payload
        return data


@dataclass(frozen=True)
class RuntimeSessionRecord:
    id: str
    source: str
    title: str
    started_at: int
    ended_at: int | None = None
    parent_session_id: str | None = None
    model: str | None = None
    message_count: int = 0
    tool_call_count: int = 0
    api_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    estimated_cost_usd: float | None = None
    actual_cost_usd: float | None = None
    cost_status: str | None = None


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    fingerprint: str
    tool: str
    action: str
    status: str
    reason: str
    policy_json: str
    args_json: str
    created_at: int
    decided_at: int | None = None
    decision: str | None = None
    decision_reason: str | None = None
    expires_at: int | None = None


@dataclass(frozen=True)
class ToolInvocationRecord:
    invocation_id: str
    tool: str
    status: str
    started_at: int
    ended_at: int | None = None
    approval_id: str | None = None
    query_id: str | None = None
    session_id: str | None = None
    args_hash: str = ""
    args_json: str = "{}"
    policy_json: str = "{}"
    summary: str = ""
    output_preview: str = ""
    error_kind: str = ""
    duration_ms: int | None = None
    checkpoint_id: str | None = None


@dataclass(frozen=True)
class ModelCallRecord:
    id: int
    query_id: str | None
    session_id: str | None
    task_id: str | None
    agent_id: str | None
    run_id: str | None
    model: str
    provider: str
    ok: bool
    started_at: int
    ended_at: int | None = None
    duration_ms: int | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    estimated_cost_usd: float | None = None
    actual_cost_usd: float | None = None
    cost_status: str = "unpriced"
    cost_source: str = ""
    pricing_version: str = ""
    preflight_applied: bool = False
    provider_retry_applied: bool = False
    pressure: float | None = None
    pressure_state: str = ""
    error_kind: str = ""
    error: str = ""


@dataclass(frozen=True)
class CompactEventRecord:
    id: int
    query_id: str | None
    session_id: str | None
    task_id: str | None
    agent_id: str | None
    run_id: str | None
    model: str
    reason: str
    mode: str
    applied: bool
    created_at: int
    target_tokens: int = 0
    original_estimated_tokens: int = 0
    compacted_estimated_tokens: int = 0
    saved_estimated_tokens: int = 0
    protected_user_request: bool = False
    tokenizer_source: str = ""
    token_count_exact: bool = False


@dataclass(frozen=True)
class BudgetReservationRecord:
    reservation_id: str
    status: str
    session_id: str
    query_id: str | None
    model: str
    provider: str
    estimated_tokens: int
    estimated_cost_usd: float | None
    created_at: int
    expires_at: int
    task_id: str | None = None
    agent_id: str | None = None
    run_id: str | None = None
    actual_tokens: int = 0
    actual_cost_usd: float | None = None
    model_call_id: int | None = None
    release_reason: str = ""
    updated_at: int | None = None
    completed_at: int | None = None
    checks_json: str = ""


def runtime_db_path(project: str | Path) -> Path:
    return task_dir(Path(project).expanduser().resolve(strict=False)) / "runtime.sqlite"


def ensure_runtime_store(project: str | Path) -> Path:
    path = runtime_db_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(path) as conn:
        _ensure_schema(conn)
    return path


def upsert_session(
    project: str | Path,
    *,
    session_id: str,
    source: str = "cli",
    title: str = "",
    project_path: str = "",
    started_at: str | int | None = None,
    parent_session_id: str | None = None,
    model: str | None = None,
    model_config: dict[str, Any] | str | None = None,
    system_prompt: str = "",
    summary: str = "",
) -> RuntimeSessionRecord:
    path = ensure_runtime_store(project)
    started_ms = _coerce_ms(started_at) or _now_ms()
    model_config_json = _json_dumps(model_config) if model_config is not None else None
    with _connect(path) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO sessions (
                id, source, model, model_config, system_prompt, parent_session_id,
                started_at, title, project_path, summary
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                source=excluded.source,
                model=COALESCE(excluded.model, sessions.model),
                model_config=COALESCE(excluded.model_config, sessions.model_config),
                system_prompt=COALESCE(NULLIF(excluded.system_prompt, ''), sessions.system_prompt),
                parent_session_id=COALESCE(excluded.parent_session_id, sessions.parent_session_id),
                title=COALESCE(NULLIF(excluded.title, ''), sessions.title),
                project_path=COALESCE(NULLIF(excluded.project_path, ''), sessions.project_path),
                summary=COALESCE(NULLIF(excluded.summary, ''), sessions.summary)
            """,
            (
                session_id,
                source,
                model,
                model_config_json,
                system_prompt,
                parent_session_id,
                started_ms,
                title or session_id,
                project_path,
                summary,
            ),
        )
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return _session_from_row(row)


def end_session(
    project: str | Path,
    session_id: str,
    *,
    reason: str = "",
    ended_at: str | int | None = None,
    summary: str = "",
) -> RuntimeSessionRecord | None:
    path = ensure_runtime_store(project)
    ended_ms = _coerce_ms(ended_at) or _now_ms()
    with _connect(path) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            UPDATE sessions
            SET ended_at = ?, end_reason = ?, summary = COALESCE(NULLIF(?, ''), summary)
            WHERE id = ?
            """,
            (ended_ms, reason, summary, session_id),
        )
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return _session_from_row(row) if row else None


def append_runtime_message(
    project: str | Path,
    *,
    session_id: str,
    role: str,
    content: str,
    tool_call_id: str | None = None,
    tool_calls: Any | None = None,
    tool_name: str | None = None,
    timestamp: str | int | None = None,
    token_count: int | None = None,
    finish_reason: str | None = None,
    reasoning: str | None = None,
    meta: dict[str, Any] | None = None,
) -> int:
    path = ensure_runtime_store(project)
    timestamp_ms = _coerce_ms(timestamp) or _now_ms()
    with _connect(path) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT OR IGNORE INTO sessions (id, source, started_at, title)
            VALUES (?, 'cli', ?, ?)
            """,
            (session_id, timestamp_ms, session_id),
        )
        cursor = conn.execute(
            """
            INSERT INTO messages (
                session_id, role, content, tool_call_id, tool_calls, tool_name, timestamp,
                token_count, finish_reason, reasoning, meta_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                role,
                content,
                tool_call_id,
                _json_dumps(tool_calls) if tool_calls is not None else None,
                tool_name,
                timestamp_ms,
                token_count,
                finish_reason,
                reasoning,
                _json_dumps(meta or {}),
            ),
        )
        conn.execute(
            """
            UPDATE sessions
            SET message_count = message_count + 1,
                tool_call_count = tool_call_count + CASE WHEN ? IS NULL THEN 0 ELSE 1 END
            WHERE id = ?
            """,
            (tool_name, session_id),
        )
        return int(cursor.lastrowid)


def record_model_call(
    project: str | Path,
    *,
    model: str,
    provider: str = "",
    ok: bool,
    query_id: str | None = None,
    session_id: str | None = None,
    task_id: str | None = None,
    agent_id: str | None = None,
    run_id: str | None = None,
    usage: dict[str, Any] | None = None,
    token_budget: dict[str, Any] | None = None,
    compression: dict[str, Any] | None = None,
    error_kind: str = "",
    error: str = "",
    started_at: str | int | None = None,
    ended_at: str | int | None = None,
    duration_ms: int | None = None,
) -> int:
    path = ensure_runtime_store(project)
    started_ms = _coerce_ms(started_at) or _now_ms()
    ended_ms = _coerce_ms(ended_at) if ended_at is not None else None
    if duration_ms is None and ended_ms is not None:
        duration_ms = max(0, ended_ms - started_ms)
    usage_payload = dict(usage or {})
    budget_payload = dict(token_budget or {})
    compression_payload = dict(compression or {})
    normalized = _normalize_model_usage(model, usage_payload, budget_payload, project=project)
    query_key = query_id or None
    session_key = session_id or None
    with _connect(path) as conn:
        _ensure_schema(conn)
        if session_key:
            conn.execute(
                """
                INSERT OR IGNORE INTO sessions (id, source, started_at, title)
                VALUES (?, 'model', ?, ?)
                """,
                (session_key, started_ms, session_key),
            )
        cursor = conn.execute(
            """
            INSERT INTO model_calls (
                query_id, session_id, task_id, agent_id, run_id, model, provider, ok, error_kind, error,
                started_at, ended_at, duration_ms,
                input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
                reasoning_tokens, total_tokens, estimated_input_tokens, estimated_output_tokens,
                estimated_cost_usd, actual_cost_usd, cost_status, cost_source, pricing_version,
                preflight_applied, provider_retry_applied, pressure, pressure_state,
                usage_json, token_budget_json, compression_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                query_key,
                session_key,
                task_id or None,
                agent_id or None,
                run_id or None,
                model,
                provider,
                1 if ok else 0,
                error_kind,
                error[:2000],
                started_ms,
                ended_ms,
                duration_ms,
                normalized["input_tokens"],
                normalized["output_tokens"],
                normalized["cache_read_tokens"],
                normalized["cache_write_tokens"],
                normalized["reasoning_tokens"],
                normalized["total_tokens"],
                normalized["estimated_input_tokens"],
                normalized["estimated_output_tokens"],
                normalized["estimated_cost_usd"],
                normalized["actual_cost_usd"],
                normalized["cost_status"],
                normalized["cost_source"],
                normalized["pricing_version"],
                1 if budget_payload.get("preflight_applied") else 0,
                1 if budget_payload.get("provider_retry_applied") else 0,
                _float_or_none(budget_payload.get("pressure")),
                str(budget_payload.get("pressure_state") or ""),
                _json_dumps(usage_payload),
                _json_dumps(budget_payload),
                _json_dumps(compression_payload),
            ),
        )
        if session_key and (usage_payload or ok) and not _local_budget_blocked(budget_payload) and not _budget_reservation_already_finalized(budget_payload):
            _update_session_model_usage(conn, session_key, model, provider, normalized)
        return int(cursor.lastrowid)


def list_model_calls(
    project: str | Path,
    *,
    limit: int = 50,
    query_id: str | None = None,
    session_id: str | None = None,
) -> list[ModelCallRecord]:
    path = ensure_runtime_store(project)
    clauses: list[str] = []
    params: list[Any] = []
    if query_id:
        clauses.append("query_id = ?")
        params.append(query_id)
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(limit)
    with _connect(path) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            f"""
            SELECT * FROM model_calls
            {where}
            ORDER BY started_at DESC, id DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
    return [_model_call_from_row(row) for row in rows]


def record_compact_event(
    project: str | Path,
    *,
    model: str,
    reason: str,
    mode: str,
    applied: bool,
    query_id: str | None = None,
    session_id: str | None = None,
    task_id: str | None = None,
    agent_id: str | None = None,
    run_id: str | None = None,
    target_tokens: int = 0,
    original_estimated_tokens: int = 0,
    compacted_estimated_tokens: int = 0,
    saved_estimated_tokens: int = 0,
    protected_user_request: bool = False,
    tokenizer_source: str = "",
    token_count_exact: bool = False,
    details: dict[str, Any] | None = None,
    created_at: str | int | None = None,
) -> int:
    path = ensure_runtime_store(project)
    created_ms = _coerce_ms(created_at) or _now_ms()
    with _connect(path) as conn:
        _ensure_schema(conn)
        if session_id:
            conn.execute(
                """
                INSERT OR IGNORE INTO sessions (id, source, started_at, title)
                VALUES (?, 'compact', ?, ?)
                """,
                (session_id, created_ms, session_id),
            )
        cursor = conn.execute(
            """
            INSERT INTO compact_events (
                query_id, session_id, task_id, agent_id, run_id, model, reason, mode,
                applied, target_tokens, original_estimated_tokens, compacted_estimated_tokens,
                saved_estimated_tokens, protected_user_request, tokenizer_source,
                token_count_exact, created_at, details_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                query_id or None,
                session_id or None,
                task_id or None,
                agent_id or None,
                run_id or None,
                model,
                reason,
                mode,
                1 if applied else 0,
                target_tokens,
                original_estimated_tokens,
                compacted_estimated_tokens,
                saved_estimated_tokens,
                1 if protected_user_request else 0,
                tokenizer_source,
                1 if token_count_exact else 0,
                created_ms,
                _json_dumps(details or {}),
            ),
        )
        return int(cursor.lastrowid)


def list_compact_events(
    project: str | Path,
    *,
    limit: int = 50,
    query_id: str | None = None,
    session_id: str | None = None,
) -> list[CompactEventRecord]:
    path = ensure_runtime_store(project)
    clauses: list[str] = []
    params: list[Any] = []
    if query_id:
        clauses.append("query_id = ?")
        params.append(query_id)
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(limit)
    with _connect(path) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            f"""
            SELECT * FROM compact_events
            {where}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
    return [_compact_event_from_row(row) for row in rows]


def reserve_model_budget(
    project: str | Path,
    *,
    session_id: str,
    model: str,
    provider: str = "",
    estimated_tokens: int,
    estimated_cost_usd: float | None = None,
    query_id: str | None = None,
    task_id: str | None = None,
    agent_id: str | None = None,
    run_id: str | None = None,
    ttl_seconds: int | None = None,
    checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    limits = env_budget_limits()
    session_limits_configured = any(
        limits.get(name)
        for name in ("max_session_tokens", "max_session_model_calls", "max_session_cost_usd")
    )
    if not session_id or not session_limits_configured:
        return {"status": "not_required"}
    path = ensure_runtime_store(project)
    now_ms = _now_ms()
    ttl_ms = _reservation_ttl_ms(ttl_seconds)
    expires_ms = now_ms + ttl_ms
    reservation_id = "br-" + uuid.uuid4().hex[:16]
    conn = _connect(path)
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        _expire_budget_reservations(conn, now_ms)
        conn.execute(
            """
            INSERT OR IGNORE INTO sessions (id, source, started_at, title)
            VALUES (?, 'model', ?, ?)
            """,
            (session_id, now_ms, session_id),
        )
        session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        active = conn.execute(
            """
            SELECT
                COALESCE(SUM(estimated_tokens), 0) AS active_tokens,
                COALESCE(SUM(estimated_cost_usd), 0) AS active_cost,
                COUNT(*) AS active_calls
            FROM budget_reservations
            WHERE session_id = ? AND status = 'active' AND expires_at > ?
            """,
            (session_id, now_ms),
        ).fetchone()
        session_tokens = int(session["input_tokens"] or 0) + int(session["output_tokens"] or 0) + int(session["reasoning_tokens"] or 0)
        session_tokens += int(active["active_tokens"] or 0)
        session_calls = int(session["api_call_count"] or 0) + int(active["active_calls"] or 0)
        session_cost = _float_or_none(session["actual_cost_usd"])
        if session_cost is None:
            session_cost = _float_or_none(session["estimated_cost_usd"]) or 0.0
        session_cost += float(active["active_cost"] or 0.0)
        evaluated = evaluate_budget_limits(
            request_estimated_tokens=max(0, int(estimated_tokens)),
            session_tokens=session_tokens,
            session_model_calls=session_calls,
            session_cost_usd=float(session_cost),
            estimated_request_cost_usd=estimated_cost_usd,
        )
        evaluated_payload = [check.to_dict() for check in evaluated]
        exceeded = [check for check in evaluated if check.exceeded]
        if exceeded:
            conn.commit()
            first = exceeded[0]
            return {
                "status": "blocked",
                "reason": "budget_reservation_exceeded",
                "summary": f"budget reservation blocked model call: {first.name} projected {first.projected} > limit {first.limit} {first.unit}",
                "checks": evaluated_payload,
            }
        conn.execute(
            """
            INSERT INTO budget_reservations (
                reservation_id, status, session_id, query_id, task_id, agent_id, run_id,
                model, provider, estimated_tokens, estimated_cost_usd, created_at,
                expires_at, updated_at, checks_json
            )
            VALUES (?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reservation_id,
                session_id,
                query_id or None,
                task_id or None,
                agent_id or None,
                run_id or None,
                model,
                provider,
                max(0, int(estimated_tokens)),
                estimated_cost_usd,
                now_ms,
                expires_ms,
                now_ms,
                _json_dumps(checks or evaluated_payload),
            ),
        )
        conn.commit()
        return {
            "status": "reserved",
            "reservation_id": reservation_id,
            "session_id": session_id,
            "estimated_tokens": max(0, int(estimated_tokens)),
            "estimated_cost_usd": estimated_cost_usd,
            "expires_at": expires_ms,
            "checks": evaluated_payload,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def commit_budget_reservation(
    project: str | Path,
    reservation_id: str,
    *,
    actual_tokens: int = 0,
    actual_cost_usd: float | None = None,
    model_call_id: int | None = None,
) -> bool:
    return _finish_budget_reservation(
        project,
        reservation_id,
        status="committed",
        actual_tokens=actual_tokens,
        actual_cost_usd=actual_cost_usd,
        model_call_id=model_call_id,
        release_reason="",
    )


def release_budget_reservation(
    project: str | Path,
    reservation_id: str,
    *,
    reason: str = "",
    model_call_id: int | None = None,
) -> bool:
    return _finish_budget_reservation(
        project,
        reservation_id,
        status="released",
        actual_tokens=0,
        actual_cost_usd=None,
        model_call_id=model_call_id,
        release_reason=reason,
    )


def get_budget_reservation(project: str | Path, reservation_id: str) -> BudgetReservationRecord | None:
    if not reservation_id:
        return None
    path = ensure_runtime_store(project)
    now_ms = _now_ms()
    with _connect(path) as conn:
        _ensure_schema(conn)
        _expire_budget_reservations(conn, now_ms)
        row = conn.execute(
            "SELECT * FROM budget_reservations WHERE reservation_id = ?",
            (reservation_id,),
        ).fetchone()
    return _budget_reservation_from_row(row) if row else None


def expire_budget_reservations(project: str | Path, *, now_ms: int | None = None) -> int:
    path = ensure_runtime_store(project)
    effective_now_ms = int(now_ms if now_ms is not None else _now_ms())
    with _connect(path) as conn:
        _ensure_schema(conn)
        return _expire_budget_reservations(conn, effective_now_ms)


def list_budget_reservations(
    project: str | Path,
    *,
    limit: int = 50,
    session_id: str | None = None,
    status: str | None = None,
) -> list[BudgetReservationRecord]:
    path = ensure_runtime_store(project)
    now_ms = _now_ms()
    with _connect(path) as conn:
        _ensure_schema(conn)
        _expire_budget_reservations(conn, now_ms)
        clauses: list[str] = []
        params: list[Any] = []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT * FROM budget_reservations
            {where}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
    return [_budget_reservation_from_row(row) for row in rows]


def inspect_budget_reservations(
    project: str | Path,
    *,
    limit: int = 200,
    now_ms: int | None = None,
    stale_ms: int | None = None,
) -> dict[str, Any]:
    path = ensure_runtime_store(project)
    effective_now_ms = int(now_ms if now_ms is not None else _now_ms())
    ttl_ms = _reservation_ttl_ms()
    effective_stale_ms = int(stale_ms if stale_ms is not None else max(ttl_ms * 2, ttl_ms + 300_000))
    with _connect(path) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT * FROM budget_reservations
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    counts: dict[str, int] = {
        "active": 0,
        "committed": 0,
        "released": 0,
        "expired": 0,
        "stale_suspect": 0,
    }
    active_tokens = 0
    active_cost = 0.0
    stale_ids: list[str] = []
    expired_effective_ids: list[str] = []
    recent: list[dict[str, Any]] = []
    for row in rows:
        item = _budget_reservation_from_row(row)
        effective_status = item.status
        if item.status == "active" and item.expires_at <= effective_now_ms:
            effective_status = "expired"
            expired_effective_ids.append(item.reservation_id)
        counts[effective_status] = counts.get(effective_status, 0) + 1
        ttl_remaining_ms = item.expires_at - effective_now_ms
        if item.status == "active" and ttl_remaining_ms > 0:
            active_tokens += item.estimated_tokens
            active_cost += float(item.estimated_cost_usd or 0.0)
            updated_at = item.updated_at or item.created_at
            if effective_now_ms - updated_at > effective_stale_ms:
                counts["stale_suspect"] += 1
                stale_ids.append(item.reservation_id)
        payload = asdict(item)
        payload["effective_status"] = effective_status
        payload["ttl_remaining_ms"] = ttl_remaining_ms
        recent.append(payload)
    return {
        "now_ms": effective_now_ms,
        "stale_ms": effective_stale_ms,
        "counts": counts,
        "active_calls": counts.get("active", 0),
        "active_estimated_tokens": active_tokens,
        "active_estimated_cost_usd": active_cost,
        "stale_suspect_ids": stale_ids,
        "expired_effective_ids": expired_effective_ids,
        "recent_reservations": recent,
    }


def list_runtime_sessions(project: str | Path, *, limit: int = 50) -> list[RuntimeSessionRecord]:
    path = ensure_runtime_store(project)
    with _connect(path) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT * FROM sessions
            ORDER BY COALESCE(ended_at, started_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_session_from_row(row) for row in rows]


def get_runtime_session(project: str | Path, session_id: str) -> RuntimeSessionRecord | None:
    if not session_id:
        return None
    path = ensure_runtime_store(project)
    with _connect(path) as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return _session_from_row(row) if row else None


def record_task_run(
    project: str | Path,
    task: ResearchTask,
    *,
    runtime: str = "quantagent",
    owner_key: str | None = None,
    scope_kind: str | None = None,
    requester_session_key: str | None = None,
    child_session_key: str | None = None,
    parent_flow_id: str | None = None,
    parent_task_id: str | None = None,
    agent_id: str | None = None,
    run_id: str | None = None,
    label: str | None = None,
    delivery_status: str | None = None,
    notify_policy: str | None = None,
    progress_summary: str | None = None,
    terminal_summary: str | None = None,
    terminal_outcome: str | None = None,
    error: str | None = None,
    cleanup_after: int | None = None,
) -> TaskRunRecord:
    path = ensure_runtime_store(project)
    created_ms = _coerce_ms(task.created_at) or _now_ms()
    updated_ms = _coerce_ms(task.updated_at) or _now_ms()
    started_ms = created_ms if task.status in {RUNNING, PASSED, FAILED, ABORTED, LOST} else None
    ended_ms = updated_ms if task.status in TERMINAL_STATUSES else None
    owner_key = owner_key or getattr(task, "owner_key", "") or "local"
    scope_kind = scope_kind or getattr(task, "scope_kind", "") or "project"
    requester_session_key = requester_session_key or getattr(task, "requester_session_key", "") or None
    child_session_key = child_session_key or getattr(task, "child_session_key", "") or None
    parent_task_id = parent_task_id or getattr(task, "parent_task_id", "") or None
    notify_policy = notify_policy or getattr(task, "notify_policy", "") or "on_complete"
    cleanup_after = cleanup_after if cleanup_after is not None else getattr(task, "cleanup_after", None)
    delivery_status = delivery_status or ("ready" if task.status in TERMINAL_STATUSES else "pending")
    terminal_outcome = terminal_outcome or _terminal_outcome(task.status)
    progress_summary = progress_summary or task.detail or task.title
    terminal_summary = terminal_summary or (getattr(task, "terminal_summary", "") or None)
    terminal_summary = terminal_summary if task.status in TERMINAL_STATUSES else None
    with _connect(path) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO task_runs (
                task_id, runtime, task_kind, source_id, requester_session_key, owner_key,
                scope_kind, child_session_key, parent_flow_id, parent_task_id, agent_id,
                run_id, label, task, status, delivery_status, notify_policy, created_at,
                started_at, ended_at, last_event_at, cleanup_after, error, progress_summary,
                terminal_summary, terminal_outcome, command_json, pid, output_path,
                error_path, status_path, evidence_json, detail
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                runtime=excluded.runtime,
                task_kind=excluded.task_kind,
                requester_session_key=COALESCE(excluded.requester_session_key, task_runs.requester_session_key),
                owner_key=excluded.owner_key,
                scope_kind=excluded.scope_kind,
                child_session_key=COALESCE(excluded.child_session_key, task_runs.child_session_key),
                parent_flow_id=COALESCE(excluded.parent_flow_id, task_runs.parent_flow_id),
                parent_task_id=COALESCE(excluded.parent_task_id, task_runs.parent_task_id),
                agent_id=COALESCE(excluded.agent_id, task_runs.agent_id),
                run_id=COALESCE(excluded.run_id, task_runs.run_id),
                label=COALESCE(excluded.label, task_runs.label),
                task=excluded.task,
                status=excluded.status,
                delivery_status=excluded.delivery_status,
                notify_policy=excluded.notify_policy,
                started_at=COALESCE(excluded.started_at, task_runs.started_at),
                ended_at=excluded.ended_at,
                last_event_at=excluded.last_event_at,
                cleanup_after=excluded.cleanup_after,
                error=excluded.error,
                progress_summary=excluded.progress_summary,
                terminal_summary=COALESCE(excluded.terminal_summary, task_runs.terminal_summary),
                terminal_outcome=COALESCE(excluded.terminal_outcome, task_runs.terminal_outcome),
                command_json=excluded.command_json,
                pid=excluded.pid,
                output_path=excluded.output_path,
                error_path=excluded.error_path,
                status_path=excluded.status_path,
                evidence_json=excluded.evidence_json,
                detail=excluded.detail
            """,
            (
                task.id,
                runtime,
                task.kind,
                None,
                requester_session_key,
                owner_key,
                scope_kind,
                child_session_key,
                parent_flow_id,
                parent_task_id,
                agent_id,
                run_id,
                label or task.title,
                task.title,
                task.status,
                delivery_status,
                notify_policy,
                created_ms,
                started_ms,
                ended_ms,
                updated_ms,
                cleanup_after,
                error,
                progress_summary,
                terminal_summary,
                terminal_outcome,
                _json_dumps(task.command),
                task.pid,
                task.output_path or None,
                task.error_path or None,
                task.status_path or None,
                _json_dumps(task.evidence),
                task.detail or None,
            ),
        )
        _upsert_delivery_state(conn, task.id, delivery_status)
        row = conn.execute("SELECT * FROM task_runs WHERE task_id = ?", (task.id,)).fetchone()
    return _task_run_from_row(row)


def get_task_run(project: str | Path, task_id: str) -> TaskRunRecord | None:
    path = ensure_runtime_store(project)
    with _connect(path) as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT * FROM task_runs WHERE task_id = ?", (task_id,)).fetchone()
    return _task_run_from_row(row) if row else None


def list_task_runs(project: str | Path, *, status: str | None = None, limit: int = 50) -> list[TaskRunRecord]:
    path = ensure_runtime_store(project)
    with _connect(path) as conn:
        _ensure_schema(conn)
        if status:
            rows = conn.execute(
                """
                SELECT * FROM task_runs
                WHERE status = ?
                ORDER BY last_event_at DESC
                LIMIT ?
                """,
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM task_runs
                ORDER BY last_event_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [_task_run_from_row(row) for row in rows]


def enqueue_runtime_queue_item(
    project: str | Path,
    *,
    item_id: str | None = None,
    task: str = "",
    queue: str = "default",
    task_kind: str = "manual",
    payload: dict[str, Any] | str | None = None,
    priority: int = 50,
    owner_key: str = "local",
    session_lock_key: str = "",
    stop_file: str = "",
    resume_of: str = "",
    max_attempts: int = 3,
    now_ms: int | None = None,
) -> RuntimeQueueItem:
    path = ensure_runtime_store(project)
    task_id = _runtime_queue_id(item_id)
    normalized_queue = _runtime_queue_name(queue)
    timestamp = int(now_ms if now_ms is not None else _now_ms())
    payload_data = payload if payload is not None else {}
    payload_json = _json_dumps(payload_data)
    task_text = str(task or "")
    if not task_text and isinstance(payload_data, dict):
        task_text = str(payload_data.get("goal") or payload_data.get("task") or "")
    if not task_text:
        task_text = task_id
    with _connect(path) as conn:
        _ensure_schema(conn)
        try:
            conn.execute(
                """
                INSERT INTO runtime_queue (
                    task_id, queue, task, task_kind, status, priority, owner_key,
                    session_lock_key, stop_file, resume_of, max_attempts,
                    created_at, updated_at, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    normalized_queue,
                    task_text,
                    str(task_kind or "manual"),
                    RUNTIME_QUEUE_QUEUED,
                    int(priority),
                    str(owner_key or "local"),
                    str(session_lock_key or "") or None,
                    str(stop_file or "") or None,
                    str(resume_of or "") or None,
                    max(1, int(max_attempts or 1)),
                    timestamp,
                    timestamp,
                    payload_json,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"runtime queue item already exists: {task_id}") from exc
        row = conn.execute("SELECT * FROM runtime_queue WHERE task_id = ?", (task_id,)).fetchone()
    return _runtime_queue_item_from_row(row)


def list_runtime_queue_items(
    project: str | Path,
    *,
    queue: str = "default",
    status: str | Iterable[str] | None = None,
    limit: int = 100,
) -> list[RuntimeQueueItem]:
    path = ensure_runtime_store(project)
    normalized_queue = _runtime_queue_name(queue)
    bounded_limit = max(1, min(int(limit), 1000))
    statuses = _runtime_queue_status_filter(status)
    with _connect(path) as conn:
        _ensure_schema(conn)
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            rows = conn.execute(
                f"""
                SELECT * FROM runtime_queue
                WHERE queue = ? AND status IN ({placeholders})
                ORDER BY priority ASC, created_at ASC, task_id ASC
                LIMIT ?
                """,
                (normalized_queue, *statuses, bounded_limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM runtime_queue
                WHERE queue = ?
                ORDER BY priority ASC, created_at ASC, task_id ASC
                LIMIT ?
                """,
                (normalized_queue, bounded_limit),
            ).fetchall()
    return [_runtime_queue_item_from_row(row) for row in rows]


def claim_runtime_queue_item(
    project: str | Path,
    *,
    queue: str = "default",
    lease_owner: str,
    lease_seconds: float = 300.0,
    now_ms: int | None = None,
) -> RuntimeQueueItem | None:
    if not str(lease_owner or "").strip():
        raise ValueError("lease_owner is required")
    path = ensure_runtime_store(project)
    normalized_queue = _runtime_queue_name(queue)
    timestamp = int(now_ms if now_ms is not None else _now_ms())
    lease_until = timestamp + _lease_ms(lease_seconds)
    conn = _connect(path)
    conn.isolation_level = None
    try:
        _ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT * FROM runtime_queue
            WHERE queue = ?
              AND attempts < max_attempts
              AND (
                status = ?
                OR (status = ? AND lease_expires_at IS NOT NULL AND lease_expires_at < ?)
              )
            ORDER BY CASE status WHEN ? THEN 0 ELSE 1 END, priority ASC, created_at ASC, task_id ASC
            LIMIT 1
            """,
            (normalized_queue, RUNTIME_QUEUE_QUEUED, RUNTIME_QUEUE_RUNNING, timestamp, RUNTIME_QUEUE_QUEUED),
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        conn.execute(
            """
            UPDATE runtime_queue
            SET status = ?, lease_owner = ?, lease_expires_at = ?, heartbeat_at = ?,
                attempts = attempts + 1, started_at = COALESCE(started_at, ?),
                updated_at = ?, ended_at = NULL, error = NULL
            WHERE task_id = ?
            """,
            (RUNTIME_QUEUE_RUNNING, str(lease_owner), lease_until, timestamp, timestamp, timestamp, row["task_id"]),
        )
        claimed = conn.execute("SELECT * FROM runtime_queue WHERE task_id = ?", (row["task_id"],)).fetchone()
        conn.commit()
        return _runtime_queue_item_from_row(claimed)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def heartbeat_runtime_queue_item(
    project: str | Path,
    item_id: str,
    *,
    lease_owner: str,
    lease_seconds: float = 300.0,
    now_ms: int | None = None,
) -> RuntimeQueueItem:
    path = ensure_runtime_store(project)
    project_path = Path(project).expanduser().resolve(strict=False)
    timestamp = int(now_ms if now_ms is not None else _now_ms())
    lease_until = timestamp + _lease_ms(lease_seconds)
    with _connect(path) as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT * FROM runtime_queue WHERE task_id = ?", (_runtime_queue_id(item_id),)).fetchone()
        _require_runtime_queue_running(row, lease_owner)
        stop_file = str(row["stop_file"] or "")
        if stop_file and _runtime_queue_stop_file_present(project_path, stop_file):
            conn.execute(
                """
                UPDATE runtime_queue
                SET status = ?, heartbeat_at = ?, updated_at = ?, ended_at = ?,
                    summary = ?, lease_expires_at = NULL
                WHERE task_id = ?
                """,
                (RUNTIME_QUEUE_STOPPED, timestamp, timestamp, timestamp, f"STOP file present: {stop_file}", row["task_id"]),
            )
        else:
            conn.execute(
                """
                UPDATE runtime_queue
                SET heartbeat_at = ?, lease_expires_at = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (timestamp, lease_until, timestamp, row["task_id"]),
            )
        updated = conn.execute("SELECT * FROM runtime_queue WHERE task_id = ?", (row["task_id"],)).fetchone()
    return _runtime_queue_item_from_row(updated)


def complete_runtime_queue_item(
    project: str | Path,
    item_id: str,
    *,
    lease_owner: str,
    result: dict[str, Any] | str | None = None,
    now_ms: int | None = None,
) -> RuntimeQueueItem:
    payload = result if result is not None else {}
    return _finish_runtime_queue_item(
        project,
        item_id,
        lease_owner=lease_owner,
        status=RUNTIME_QUEUE_DONE,
        summary="runtime queue item completed",
        payload=payload,
        now_ms=now_ms,
    )


def fail_runtime_queue_item(
    project: str | Path,
    item_id: str,
    *,
    lease_owner: str,
    error: str = "",
    result: dict[str, Any] | str | None = None,
    now_ms: int | None = None,
) -> RuntimeQueueItem:
    return _finish_runtime_queue_item(
        project,
        item_id,
        lease_owner=lease_owner,
        status=RUNTIME_QUEUE_FAILED,
        summary=str(error or "runtime queue item failed"),
        payload=result,
        error=error,
        now_ms=now_ms,
    )


def pause_runtime_queue_item(
    project: str | Path,
    item_id: str,
    *,
    lease_owner: str,
    reason: str = "",
    result: dict[str, Any] | str | None = None,
    now_ms: int | None = None,
) -> RuntimeQueueItem:
    return _finish_runtime_queue_item(
        project,
        item_id,
        lease_owner=lease_owner,
        status=RUNTIME_QUEUE_PAUSED,
        summary=str(reason or "runtime queue item paused"),
        payload=result,
        error=str(reason or ""),
        now_ms=now_ms,
    )


def block_runtime_queue_item(
    project: str | Path,
    item_id: str,
    *,
    lease_owner: str,
    reason: str = "",
    result: dict[str, Any] | str | None = None,
    now_ms: int | None = None,
) -> RuntimeQueueItem:
    return _finish_runtime_queue_item(
        project,
        item_id,
        lease_owner=lease_owner,
        status=RUNTIME_QUEUE_BLOCKED,
        summary=str(reason or "runtime queue item blocked"),
        payload=result,
        error=str(reason or ""),
        now_ms=now_ms,
    )


def stop_runtime_queue_item(
    project: str | Path,
    item_id: str,
    *,
    lease_owner: str | None = None,
    reason: str = "",
    now_ms: int | None = None,
) -> RuntimeQueueItem:
    path = ensure_runtime_store(project)
    timestamp = int(now_ms if now_ms is not None else _now_ms())
    with _connect(path) as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT * FROM runtime_queue WHERE task_id = ?", (_runtime_queue_id(item_id),)).fetchone()
        if row is None:
            raise ValueError(f"runtime queue item not found: {item_id}")
        status = str(row["status"])
        if status in RUNTIME_QUEUE_TERMINAL_STATUSES:
            raise ValueError(f"runtime queue item is terminal: {status}")
        if status == RUNTIME_QUEUE_RUNNING and lease_owner is not None and str(row["lease_owner"] or "") != str(lease_owner):
            raise ValueError("runtime queue lease owner mismatch")
        conn.execute(
            """
            UPDATE runtime_queue
            SET status = ?, summary = ?, updated_at = ?, ended_at = ?,
                lease_expires_at = NULL
            WHERE task_id = ?
            """,
            (RUNTIME_QUEUE_STOPPED, str(reason or "runtime queue item stopped"), timestamp, timestamp, row["task_id"]),
        )
        updated = conn.execute("SELECT * FROM runtime_queue WHERE task_id = ?", (row["task_id"],)).fetchone()
    return _runtime_queue_item_from_row(updated)


def resume_runtime_queue_item(
    project: str | Path,
    item_id: str,
    *,
    now_ms: int | None = None,
) -> RuntimeQueueItem:
    path = ensure_runtime_store(project)
    timestamp = int(now_ms if now_ms is not None else _now_ms())
    with _connect(path) as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT * FROM runtime_queue WHERE task_id = ?", (_runtime_queue_id(item_id),)).fetchone()
        if row is None:
            raise ValueError(f"runtime queue item not found: {item_id}")
        status = str(row["status"])
        if status not in {RUNTIME_QUEUE_PAUSED, RUNTIME_QUEUE_FAILED, RUNTIME_QUEUE_BLOCKED}:
            raise ValueError(f"runtime queue item cannot resume from status: {status}")
        conn.execute(
            """
            UPDATE runtime_queue
            SET status = ?, lease_owner = NULL, lease_expires_at = NULL,
                heartbeat_at = NULL, updated_at = ?, ended_at = NULL
            WHERE task_id = ?
            """,
            (RUNTIME_QUEUE_QUEUED, timestamp, row["task_id"]),
        )
        updated = conn.execute("SELECT * FROM runtime_queue WHERE task_id = ?", (row["task_id"],)).fetchone()
    return _runtime_queue_item_from_row(updated)


def save_skill_snapshot(
    project: str | Path,
    *,
    snapshot_id: str,
    prompt: str,
    skills: Iterable[dict[str, Any]],
    session_id: str | None = None,
    run_id: str | None = None,
    skill_filter: Iterable[str] | None = None,
    version: int | None = None,
) -> str:
    path = ensure_runtime_store(project)
    created_at = _now_ms()
    with _connect(path) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO skill_snapshots (
                id, session_id, run_id, prompt, skills_json, skill_filter_json, version, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                session_id=excluded.session_id,
                run_id=excluded.run_id,
                prompt=excluded.prompt,
                skills_json=excluded.skills_json,
                skill_filter_json=excluded.skill_filter_json,
                version=excluded.version
            """,
            (
                snapshot_id,
                session_id,
                run_id,
                prompt,
                _json_dumps(list(skills)),
                _json_dumps(list(skill_filter or [])),
                version or created_at,
                created_at,
            ),
        )
    return snapshot_id


def search_messages(project: str | Path, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
    path = ensure_runtime_store(project)
    query = query.strip()
    if not query:
        return []
    with _connect(path) as conn:
        _ensure_schema(conn)
        if _table_exists(conn, "messages_fts"):
            rows = conn.execute(
                """
                SELECT m.id, m.session_id, m.role, m.content, m.tool_name, m.timestamp
                FROM messages_fts f
                JOIN messages m ON m.id = f.rowid
                WHERE messages_fts MATCH ?
                ORDER BY m.timestamp DESC
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, session_id, role, content, tool_name, timestamp
                FROM messages
                WHERE content LIKE ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (f"%{query}%", limit),
            ).fetchall()
    return [dict(row) for row in rows]


def record_query_event(project: str | Path, event: Any) -> int:
    payload = event.to_dict() if hasattr(event, "to_dict") else dict(event)
    path = ensure_runtime_store(project)
    with _connect(path) as conn:
        _ensure_schema(conn)
        cursor = conn.execute(
            """
            INSERT INTO query_events (
                query_id, kind, summary, step, name, ok, timestamp, data_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(payload.get("query_id") or ""),
                str(payload.get("kind") or ""),
                str(payload.get("summary") or ""),
                payload.get("step"),
                str(payload.get("name") or ""),
                _bool_to_int(payload.get("ok")),
                _coerce_ms(payload.get("timestamp")) or _now_ms(),
                _json_dumps(payload.get("data") or {}),
            ),
        )
        return int(cursor.lastrowid)


def load_runtime_query_events(project: str | Path, *, query_id: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
    path = ensure_runtime_store(project)
    with _connect(path) as conn:
        _ensure_schema(conn)
        if query_id:
            rows = conn.execute(
                """
                SELECT * FROM query_events
                WHERE query_id = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (query_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM query_events
                ORDER BY id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [dict(row) for row in rows]


def upsert_approval_request(
    project: str | Path,
    *,
    approval_id: str,
    fingerprint: str,
    tool: str,
    action: str,
    status: str,
    reason: str,
    policy: dict[str, Any],
    args: dict[str, Any],
    expires_at: int | None = None,
) -> ApprovalRecord:
    path = ensure_runtime_store(project)
    now = _now_ms()
    with _connect(path) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO approval_requests (
                approval_id, fingerprint, tool, action, status, reason, policy_json,
                args_json, created_at, expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fingerprint) DO UPDATE SET
                status=CASE
                    WHEN approval_requests.status IN ('approved', 'denied', 'allow_always') THEN approval_requests.status
                    ELSE excluded.status
                END,
                reason=excluded.reason,
                policy_json=excluded.policy_json,
                args_json=excluded.args_json,
                expires_at=COALESCE(excluded.expires_at, approval_requests.expires_at)
            """,
            (
                approval_id,
                fingerprint,
                tool,
                action,
                status,
                reason,
                _json_dumps(policy),
                _json_dumps(args),
                now,
                expires_at,
            ),
        )
        row = conn.execute("SELECT * FROM approval_requests WHERE fingerprint = ?", (fingerprint,)).fetchone()
    return _approval_from_row(row)


def decide_approval_request(
    project: str | Path,
    approval_id: str,
    *,
    decision: str,
    reason: str = "",
) -> ApprovalRecord | None:
    if decision not in {"approved", "denied", "allow_always", "expired"}:
        raise ValueError(f"invalid approval decision: {decision}")
    path = ensure_runtime_store(project)
    decided_at = _now_ms()
    with _connect(path) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            UPDATE approval_requests
            SET status = ?, decision = ?, decision_reason = ?, decided_at = ?
            WHERE approval_id = ?
            """,
            (decision, decision, reason, decided_at, approval_id),
        )
        row = conn.execute("SELECT * FROM approval_requests WHERE approval_id = ?", (approval_id,)).fetchone()
    return _approval_from_row(row) if row else None


def get_approval_request(project: str | Path, approval_id: str) -> ApprovalRecord | None:
    path = ensure_runtime_store(project)
    with _connect(path) as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT * FROM approval_requests WHERE approval_id = ?", (approval_id,)).fetchone()
    return _approval_from_row(row) if row else None


def list_approval_requests(project: str | Path, *, status: str | None = None, limit: int = 50) -> list[ApprovalRecord]:
    path = ensure_runtime_store(project)
    with _connect(path) as conn:
        _ensure_schema(conn)
        if status:
            rows = conn.execute(
                """
                SELECT * FROM approval_requests
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM approval_requests
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [_approval_from_row(row) for row in rows]


def record_tool_invocation(
    project: str | Path,
    *,
    invocation_id: str,
    tool: str,
    status: str,
    args: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    approval_id: str | None = None,
    query_id: str | None = None,
    session_id: str | None = None,
    summary: str = "",
    error_kind: str = "",
    output_preview: str = "",
    checkpoint_id: str | None = None,
    started_at: int | None = None,
    ended_at: int | None = None,
    duration_ms: int | None = None,
) -> ToolInvocationRecord:
    path = ensure_runtime_store(project)
    started = started_at or _now_ms()
    ended = ended_at if ended_at is not None else (started + duration_ms if duration_ms is not None else None)
    args_json = _json_dumps(args or {})
    policy_json = _json_dumps(policy or {})
    args_hash = _sha256_text(args_json)
    with _connect(path) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO tool_invocations (
                invocation_id, query_id, session_id, tool, status, approval_id, args_json,
                args_hash, policy_json, summary, output_preview, error_kind, started_at,
                ended_at, duration_ms, checkpoint_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(invocation_id) DO UPDATE SET
                status=excluded.status,
                approval_id=COALESCE(excluded.approval_id, tool_invocations.approval_id),
                args_json=excluded.args_json,
                args_hash=excluded.args_hash,
                policy_json=excluded.policy_json,
                summary=excluded.summary,
                output_preview=COALESCE(NULLIF(excluded.output_preview, ''), tool_invocations.output_preview),
                error_kind=excluded.error_kind,
                ended_at=excluded.ended_at,
                duration_ms=excluded.duration_ms,
                checkpoint_id=COALESCE(excluded.checkpoint_id, tool_invocations.checkpoint_id)
            """,
            (
                invocation_id,
                query_id,
                session_id,
                tool,
                status,
                approval_id,
                args_json,
                args_hash,
                policy_json,
                summary,
                output_preview[:4000],
                error_kind,
                started,
                ended,
                duration_ms,
                checkpoint_id,
            ),
        )
        row = conn.execute("SELECT * FROM tool_invocations WHERE invocation_id = ?", (invocation_id,)).fetchone()
    return _tool_invocation_from_row(row)


def get_tool_invocation(project: str | Path, invocation_id: str) -> ToolInvocationRecord | None:
    path = ensure_runtime_store(project)
    with _connect(path) as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT * FROM tool_invocations WHERE invocation_id = ?", (invocation_id,)).fetchone()
    return _tool_invocation_from_row(row) if row else None


def list_tool_invocations(project: str | Path, *, limit: int = 50) -> list[ToolInvocationRecord]:
    path = ensure_runtime_store(project)
    with _connect(path) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT * FROM tool_invocations
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_tool_invocation_from_row(row) for row in rows]


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            component TEXT PRIMARY KEY,
            version INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            user_id TEXT,
            model TEXT,
            model_config TEXT,
            system_prompt TEXT,
            parent_session_id TEXT,
            started_at INTEGER NOT NULL,
            ended_at INTEGER,
            end_reason TEXT,
            message_count INTEGER DEFAULT 0,
            tool_call_count INTEGER DEFAULT 0,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cache_read_tokens INTEGER DEFAULT 0,
            cache_write_tokens INTEGER DEFAULT 0,
            reasoning_tokens INTEGER DEFAULT 0,
            billing_provider TEXT,
            billing_base_url TEXT,
            billing_mode TEXT,
            estimated_cost_usd REAL,
            actual_cost_usd REAL,
            cost_status TEXT,
            cost_source TEXT,
            pricing_version TEXT,
            title TEXT,
            project_path TEXT,
            summary TEXT,
            api_call_count INTEGER DEFAULT 0,
            handoff_state TEXT,
            handoff_platform TEXT,
            handoff_error TEXT,
            FOREIGN KEY (parent_session_id) REFERENCES sessions(id)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            role TEXT NOT NULL,
            content TEXT,
            tool_call_id TEXT,
            tool_calls TEXT,
            tool_name TEXT,
            timestamp INTEGER NOT NULL,
            token_count INTEGER,
            finish_reason TEXT,
            reasoning TEXT,
            reasoning_content TEXT,
            reasoning_details TEXT,
            codex_reasoning_items TEXT,
            codex_message_items TEXT,
            meta_json TEXT
        );

        CREATE TABLE IF NOT EXISTS task_runs (
            task_id TEXT PRIMARY KEY,
            runtime TEXT NOT NULL,
            task_kind TEXT,
            source_id TEXT,
            requester_session_key TEXT,
            owner_key TEXT NOT NULL,
            scope_kind TEXT NOT NULL,
            child_session_key TEXT,
            parent_flow_id TEXT,
            parent_task_id TEXT,
            agent_id TEXT,
            run_id TEXT,
            label TEXT,
            task TEXT NOT NULL,
            status TEXT NOT NULL,
            delivery_status TEXT NOT NULL,
            notify_policy TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            started_at INTEGER,
            ended_at INTEGER,
            last_event_at INTEGER,
            cleanup_after INTEGER,
            error TEXT,
            progress_summary TEXT,
            terminal_summary TEXT,
            terminal_outcome TEXT,
            command_json TEXT,
            pid INTEGER,
            output_path TEXT,
            error_path TEXT,
            status_path TEXT,
            evidence_json TEXT,
            detail TEXT
        );

        CREATE TABLE IF NOT EXISTS task_delivery_state (
            task_id TEXT PRIMARY KEY REFERENCES task_runs(task_id) ON DELETE CASCADE,
            requester_origin_json TEXT,
            last_notified_event_at INTEGER
        );

        CREATE TABLE IF NOT EXISTS runtime_queue (
            task_id TEXT PRIMARY KEY,
            queue TEXT NOT NULL DEFAULT 'default',
            task TEXT NOT NULL,
            task_kind TEXT NOT NULL DEFAULT 'manual',
            status TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 50,
            owner_key TEXT NOT NULL DEFAULT 'local',
            lease_owner TEXT,
            lease_expires_at INTEGER,
            heartbeat_at INTEGER,
            session_lock_key TEXT,
            stop_file TEXT,
            resume_of TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            started_at INTEGER,
            ended_at INTEGER,
            summary TEXT,
            error TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS query_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            summary TEXT,
            step INTEGER,
            name TEXT,
            ok INTEGER,
            timestamp INTEGER NOT NULL,
            data_json TEXT
        );

        CREATE TABLE IF NOT EXISTS approval_requests (
            approval_id TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL UNIQUE,
            tool TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT,
            policy_json TEXT,
            args_json TEXT,
            created_at INTEGER NOT NULL,
            decided_at INTEGER,
            decision TEXT,
            decision_reason TEXT,
            expires_at INTEGER
        );

        CREATE TABLE IF NOT EXISTS tool_invocations (
            invocation_id TEXT PRIMARY KEY,
            query_id TEXT,
            session_id TEXT,
            tool TEXT NOT NULL,
            status TEXT NOT NULL,
            approval_id TEXT REFERENCES approval_requests(approval_id),
            args_json TEXT,
            policy_json TEXT,
            summary TEXT,
            error_kind TEXT,
            started_at INTEGER NOT NULL,
            ended_at INTEGER,
            duration_ms INTEGER
        );

        CREATE TABLE IF NOT EXISTS model_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_id TEXT,
            session_id TEXT REFERENCES sessions(id),
            task_id TEXT,
            agent_id TEXT,
            run_id TEXT,
            model TEXT NOT NULL,
            provider TEXT,
            ok INTEGER NOT NULL,
            error_kind TEXT,
            error TEXT,
            started_at INTEGER NOT NULL,
            ended_at INTEGER,
            duration_ms INTEGER,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cache_read_tokens INTEGER DEFAULT 0,
            cache_write_tokens INTEGER DEFAULT 0,
            reasoning_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            estimated_input_tokens INTEGER DEFAULT 0,
            estimated_output_tokens INTEGER DEFAULT 0,
            estimated_cost_usd REAL,
            actual_cost_usd REAL,
            cost_status TEXT,
            cost_source TEXT,
            pricing_version TEXT,
            preflight_applied INTEGER DEFAULT 0,
            provider_retry_applied INTEGER DEFAULT 0,
            pressure REAL,
            pressure_state TEXT,
            usage_json TEXT,
            token_budget_json TEXT,
            compression_json TEXT
        );

        CREATE TABLE IF NOT EXISTS compact_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_id TEXT,
            session_id TEXT REFERENCES sessions(id),
            task_id TEXT,
            agent_id TEXT,
            run_id TEXT,
            model TEXT NOT NULL,
            reason TEXT,
            mode TEXT,
            applied INTEGER NOT NULL,
            target_tokens INTEGER DEFAULT 0,
            original_estimated_tokens INTEGER DEFAULT 0,
            compacted_estimated_tokens INTEGER DEFAULT 0,
            saved_estimated_tokens INTEGER DEFAULT 0,
            protected_user_request INTEGER DEFAULT 0,
            tokenizer_source TEXT,
            token_count_exact INTEGER DEFAULT 0,
            created_at INTEGER NOT NULL,
            details_json TEXT
        );

        CREATE TABLE IF NOT EXISTS budget_reservations (
            reservation_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            query_id TEXT,
            task_id TEXT,
            agent_id TEXT,
            run_id TEXT,
            model TEXT NOT NULL,
            provider TEXT,
            estimated_tokens INTEGER DEFAULT 0,
            estimated_cost_usd REAL,
            actual_tokens INTEGER DEFAULT 0,
            actual_cost_usd REAL,
            model_call_id INTEGER REFERENCES model_calls(id),
            release_reason TEXT,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            updated_at INTEGER,
            completed_at INTEGER,
            checks_json TEXT
        );

        CREATE TABLE IF NOT EXISTS skill_snapshots (
            id TEXT PRIMARY KEY,
            session_id TEXT REFERENCES sessions(id),
            run_id TEXT,
            prompt TEXT NOT NULL,
            skills_json TEXT NOT NULL,
            skill_filter_json TEXT,
            version INTEGER,
            created_at INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_source ON sessions(source);
        CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, timestamp);
        CREATE INDEX IF NOT EXISTS idx_task_runs_run_id ON task_runs(run_id);
        CREATE INDEX IF NOT EXISTS idx_task_runs_status ON task_runs(status);
        CREATE INDEX IF NOT EXISTS idx_task_runs_runtime_status ON task_runs(runtime, status);
        CREATE INDEX IF NOT EXISTS idx_task_runs_cleanup_after ON task_runs(cleanup_after);
        CREATE INDEX IF NOT EXISTS idx_task_runs_last_event_at ON task_runs(last_event_at);
        CREATE INDEX IF NOT EXISTS idx_task_runs_owner_key ON task_runs(owner_key);
        CREATE INDEX IF NOT EXISTS idx_task_runs_parent_flow_id ON task_runs(parent_flow_id);
        CREATE INDEX IF NOT EXISTS idx_task_runs_child_session_key ON task_runs(child_session_key);
        CREATE INDEX IF NOT EXISTS idx_runtime_queue_claim ON runtime_queue(queue, status, priority, created_at);
        CREATE INDEX IF NOT EXISTS idx_runtime_queue_lease ON runtime_queue(status, lease_expires_at);
        CREATE INDEX IF NOT EXISTS idx_runtime_queue_owner ON runtime_queue(owner_key, status);
        CREATE INDEX IF NOT EXISTS idx_runtime_queue_session_lock ON runtime_queue(session_lock_key, status);
        CREATE INDEX IF NOT EXISTS idx_runtime_queue_resume_of ON runtime_queue(resume_of);
        CREATE INDEX IF NOT EXISTS idx_query_events_query_id ON query_events(query_id);
        CREATE INDEX IF NOT EXISTS idx_query_events_kind ON query_events(kind);
        CREATE INDEX IF NOT EXISTS idx_query_events_timestamp ON query_events(timestamp);
        CREATE INDEX IF NOT EXISTS idx_approval_requests_status ON approval_requests(status);
        CREATE INDEX IF NOT EXISTS idx_approval_requests_fingerprint ON approval_requests(fingerprint);
        CREATE INDEX IF NOT EXISTS idx_approval_requests_tool ON approval_requests(tool);
        CREATE INDEX IF NOT EXISTS idx_tool_invocations_tool ON tool_invocations(tool);
        CREATE INDEX IF NOT EXISTS idx_tool_invocations_status ON tool_invocations(status);
        CREATE INDEX IF NOT EXISTS idx_tool_invocations_approval_id ON tool_invocations(approval_id);
        CREATE INDEX IF NOT EXISTS idx_tool_invocations_query_id ON tool_invocations(query_id);
        CREATE INDEX IF NOT EXISTS idx_model_calls_query_id ON model_calls(query_id);
        CREATE INDEX IF NOT EXISTS idx_model_calls_session_id ON model_calls(session_id);
        CREATE INDEX IF NOT EXISTS idx_model_calls_model ON model_calls(model);
        CREATE INDEX IF NOT EXISTS idx_model_calls_started ON model_calls(started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_model_calls_task_id ON model_calls(task_id);
        CREATE INDEX IF NOT EXISTS idx_model_calls_agent_id ON model_calls(agent_id);
        CREATE INDEX IF NOT EXISTS idx_compact_events_query_id ON compact_events(query_id);
        CREATE INDEX IF NOT EXISTS idx_compact_events_session_id ON compact_events(session_id);
        CREATE INDEX IF NOT EXISTS idx_compact_events_created ON compact_events(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_budget_reservations_session_status ON budget_reservations(session_id, status);
        CREATE INDEX IF NOT EXISTS idx_budget_reservations_status_expires ON budget_reservations(status, expires_at);
        CREATE INDEX IF NOT EXISTS idx_budget_reservations_query_id ON budget_reservations(query_id);
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO schema_version (component, version) VALUES ('runtime_store', ?)",
        (SCHEMA_VERSION,),
    )
    _ensure_column(conn, "sessions", "input_tokens", "INTEGER DEFAULT 0")
    _ensure_column(conn, "sessions", "output_tokens", "INTEGER DEFAULT 0")
    _ensure_column(conn, "sessions", "cache_read_tokens", "INTEGER DEFAULT 0")
    _ensure_column(conn, "sessions", "cache_write_tokens", "INTEGER DEFAULT 0")
    _ensure_column(conn, "sessions", "reasoning_tokens", "INTEGER DEFAULT 0")
    _ensure_column(conn, "sessions", "billing_provider", "TEXT")
    _ensure_column(conn, "sessions", "billing_base_url", "TEXT")
    _ensure_column(conn, "sessions", "billing_mode", "TEXT")
    _ensure_column(conn, "sessions", "estimated_cost_usd", "REAL")
    _ensure_column(conn, "sessions", "actual_cost_usd", "REAL")
    _ensure_column(conn, "sessions", "cost_status", "TEXT")
    _ensure_column(conn, "sessions", "cost_source", "TEXT")
    _ensure_column(conn, "sessions", "pricing_version", "TEXT")
    _ensure_column(conn, "sessions", "api_call_count", "INTEGER DEFAULT 0")
    _ensure_column(conn, "model_calls", "task_id", "TEXT")
    _ensure_column(conn, "model_calls", "agent_id", "TEXT")
    _ensure_column(conn, "model_calls", "run_id", "TEXT")
    _ensure_column(conn, "tool_invocations", "args_hash", "TEXT")
    _ensure_column(conn, "tool_invocations", "output_preview", "TEXT")
    _ensure_column(conn, "tool_invocations", "checkpoint_id", "TEXT")
    _ensure_column(conn, "runtime_queue", "queue", "TEXT DEFAULT 'default'")
    _ensure_optional_fts(conn)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if any(str(row["name"]) == column for row in rows):
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def _ensure_optional_fts(conn: sqlite3.Connection) -> None:
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                content,
                tool_name,
                content='messages',
                content_rowid='id'
            )
            """
        )
        conn.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, content, tool_name)
                VALUES (new.id, COALESCE(new.content, ''), COALESCE(new.tool_name, ''));
            END;
            CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, content, tool_name)
                VALUES('delete', old.id, COALESCE(old.content, ''), COALESCE(old.tool_name, ''));
            END;
            CREATE TRIGGER IF NOT EXISTS messages_fts_update AFTER UPDATE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, content, tool_name)
                VALUES('delete', old.id, COALESCE(old.content, ''), COALESCE(old.tool_name, ''));
                INSERT INTO messages_fts(rowid, content, tool_name)
                VALUES (new.id, COALESCE(new.content, ''), COALESCE(new.tool_name, ''));
            END;
            """
        )
    except sqlite3.OperationalError:
        return


def _upsert_delivery_state(conn: sqlite3.Connection, task_id: str, delivery_status: str) -> None:
    if delivery_status not in {"ready", "delivered"}:
        return
    conn.execute(
        """
        INSERT INTO task_delivery_state (task_id, requester_origin_json, last_notified_event_at)
        VALUES (?, '{}', ?)
        ON CONFLICT(task_id) DO UPDATE SET last_notified_event_at = excluded.last_notified_event_at
        """,
        (task_id, _now_ms()),
    )


def _update_session_model_usage(conn: sqlite3.Connection, session_id: str, model: str, provider: str, usage: dict[str, Any]) -> None:
    estimated_cost = usage.get("estimated_cost_usd")
    actual_cost = usage.get("actual_cost_usd")
    updates = [
        "model=COALESCE(NULLIF(?, ''), model)",
        "billing_provider=COALESCE(NULLIF(?, ''), billing_provider)",
        "billing_base_url=COALESCE(NULLIF(?, ''), billing_base_url)",
        "api_call_count=api_call_count + 1",
        "input_tokens=input_tokens + ?",
        "output_tokens=output_tokens + ?",
        "cache_read_tokens=cache_read_tokens + ?",
        "cache_write_tokens=cache_write_tokens + ?",
        "reasoning_tokens=reasoning_tokens + ?",
        "cost_status=CASE WHEN ? = 'unpriced' THEN COALESCE(cost_status, ?) ELSE ? END",
        "cost_source=CASE WHEN ? = '' THEN cost_source ELSE ? END",
        "pricing_version=COALESCE(NULLIF(?, ''), pricing_version)",
    ]
    params: list[Any] = [
        model,
        provider,
        provider,
        usage["input_tokens"],
        usage["output_tokens"],
        usage["cache_read_tokens"],
        usage["cache_write_tokens"],
        usage["reasoning_tokens"],
        usage["cost_status"],
        usage["cost_status"],
        usage["cost_status"],
        usage["cost_source"],
        usage["cost_source"],
        usage["pricing_version"],
    ]
    if estimated_cost is not None:
        updates.append("estimated_cost_usd=COALESCE(estimated_cost_usd, 0) + ?")
        params.append(estimated_cost)
    if actual_cost is not None:
        updates.append("actual_cost_usd=COALESCE(actual_cost_usd, 0) + ?")
        params.append(actual_cost)
    params.append(session_id)
    conn.execute(f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?", tuple(params))


def _local_budget_blocked(token_budget: dict[str, Any]) -> bool:
    for key in ("budget_guard", "budget_reservation"):
        value = token_budget.get(key)
        if isinstance(value, dict) and value.get("status") == "blocked":
            return True
    return False


def _budget_reservation_already_finalized(token_budget: dict[str, Any]) -> bool:
    reservation = token_budget.get("budget_reservation")
    if not isinstance(reservation, dict):
        return False
    return str(reservation.get("status") or "") in {"committed", "released", "expired"}


def _finish_budget_reservation(
    project: str | Path,
    reservation_id: str,
    *,
    status: str,
    actual_tokens: int,
    actual_cost_usd: float | None,
    model_call_id: int | None,
    release_reason: str,
) -> bool:
    if not reservation_id:
        return False
    if status not in {"committed", "released"}:
        raise ValueError("budget reservation terminal status must be committed or released")
    path = ensure_runtime_store(project)
    now_ms = _now_ms()
    conn = _connect(path)
    conn.isolation_level = None
    try:
        _ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            UPDATE budget_reservations
            SET status = ?,
                actual_tokens = ?,
                actual_cost_usd = ?,
                model_call_id = COALESCE(?, model_call_id),
                release_reason = ?,
                updated_at = ?,
                completed_at = ?
            WHERE reservation_id = ? AND status = 'active'
            """,
            (
                status,
                max(0, int(actual_tokens)),
                actual_cost_usd,
                model_call_id,
                release_reason,
                now_ms,
                now_ms,
                reservation_id,
            ),
        )
        if cursor.rowcount > 0:
            conn.commit()
            return True
        row = conn.execute(
            "SELECT status FROM budget_reservations WHERE reservation_id = ?",
            (reservation_id,),
        ).fetchone()
        conn.commit()
        if not row:
            return False
        existing_status = str(row["status"])
        if existing_status == status:
            return True
        return False
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _expire_budget_reservations(conn: sqlite3.Connection, now_ms: int) -> int:
    cursor = conn.execute(
        """
        UPDATE budget_reservations
        SET status = 'expired',
            updated_at = ?,
            completed_at = ?,
            release_reason = COALESCE(NULLIF(release_reason, ''), 'ttl_expired')
        WHERE status = 'active' AND expires_at <= ?
        """,
        (now_ms, now_ms, now_ms),
    )
    return cursor.rowcount


def _normalize_model_usage(
    model: str,
    usage: dict[str, Any],
    token_budget: dict[str, Any],
    *,
    project: str | Path | None = None,
) -> dict[str, Any]:
    input_tokens = _first_int(
        usage,
        "prompt_tokens",
        "input_tokens",
        "inputTokens",
    )
    output_tokens = _first_int(
        usage,
        "completion_tokens",
        "output_tokens",
        "outputTokens",
    )
    cache_read_tokens = _first_int(
        usage,
        "cache_read_tokens",
        "cache_read_input_tokens",
        "cached_tokens",
    )
    if cache_read_tokens <= 0:
        cache_read_tokens = _nested_int(usage, "prompt_tokens_details", "cached_tokens") or _nested_int(usage, "input_tokens_details", "cached_tokens")
    cache_write_tokens = _first_int(
        usage,
        "cache_write_tokens",
        "cache_creation_input_tokens",
        "cache_write_input_tokens",
    )
    reasoning_tokens = _first_int(
        usage,
        "reasoning_tokens",
    )
    if reasoning_tokens <= 0:
        reasoning_tokens = _nested_int(usage, "completion_tokens_details", "reasoning_tokens") or _nested_int(usage, "output_tokens_details", "reasoning_tokens")
    total_tokens = _first_int(usage, "total_tokens", "totalTokens")
    if total_tokens <= 0:
        total_tokens = input_tokens + output_tokens
    estimated_input_tokens = _first_int(
        token_budget,
        "retry_compressed_estimated_tokens",
        "compressed_estimated_tokens",
        "original_estimated_tokens",
    )
    estimated_output_tokens = _nested_int(token_budget, "model_profile", "output_reserve_tokens")
    actual_cost = _first_float(usage, "actual_cost_usd", "cost_usd", "total_cost_usd", "cost")
    estimated_cost = _first_float(usage, "estimated_cost_usd", "estimated_cost")
    cost_source = "provider_usage" if actual_cost is not None or estimated_cost is not None else ""
    pricing_version = str(usage.get("pricing_version") or "")
    normalized = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": total_tokens,
        "estimated_input_tokens": estimated_input_tokens,
        "estimated_output_tokens": estimated_output_tokens,
        "estimated_cost_usd": estimated_cost,
        "actual_cost_usd": actual_cost,
        "cost_status": "actual" if actual_cost is not None else "estimated" if estimated_cost is not None else "unpriced",
        "cost_source": cost_source,
        "pricing_version": pricing_version,
    }
    if normalized["cost_status"] == "unpriced" and total_tokens > 0:
        priced_cost, price_source, price_version = estimate_cost_usd(model, normalized, project)
        if priced_cost is not None:
            normalized.update(
                {
                    "estimated_cost_usd": priced_cost,
                    "cost_status": "estimated",
                    "cost_source": "local_price_table",
                    "pricing_version": price_version or price_source,
                }
            )
    return normalized


def _task_run_from_row(row: sqlite3.Row) -> TaskRunRecord:
    return TaskRunRecord(
        task_id=str(row["task_id"]),
        runtime=str(row["runtime"]),
        task_kind=str(row["task_kind"] or ""),
        task=str(row["task"]),
        status=str(row["status"]),
        delivery_status=str(row["delivery_status"]),
        notify_policy=str(row["notify_policy"]),
        created_at=int(row["created_at"]),
        started_at=_int_or_none(row["started_at"]),
        ended_at=_int_or_none(row["ended_at"]),
        cleanup_after=_int_or_none(row["cleanup_after"]),
        owner_key=str(row["owner_key"]),
        scope_kind=str(row["scope_kind"]),
        requester_session_key=row["requester_session_key"],
        child_session_key=row["child_session_key"],
        parent_flow_id=row["parent_flow_id"],
        parent_task_id=row["parent_task_id"],
        agent_id=row["agent_id"],
        run_id=row["run_id"],
        label=row["label"],
        error=row["error"],
        progress_summary=row["progress_summary"],
        terminal_summary=row["terminal_summary"],
        terminal_outcome=row["terminal_outcome"],
    )


def _session_from_row(row: sqlite3.Row) -> RuntimeSessionRecord:
    return RuntimeSessionRecord(
        id=str(row["id"]),
        source=str(row["source"]),
        title=str(row["title"] or row["id"]),
        started_at=int(row["started_at"]),
        ended_at=_int_or_none(row["ended_at"]),
        parent_session_id=row["parent_session_id"],
        model=row["model"],
        message_count=int(row["message_count"] or 0),
        tool_call_count=int(row["tool_call_count"] or 0),
        api_call_count=int(row["api_call_count"] or 0),
        input_tokens=int(row["input_tokens"] or 0),
        output_tokens=int(row["output_tokens"] or 0),
        cache_read_tokens=int(row["cache_read_tokens"] or 0),
        cache_write_tokens=int(row["cache_write_tokens"] or 0),
        reasoning_tokens=int(row["reasoning_tokens"] or 0),
        estimated_cost_usd=_float_or_none(row["estimated_cost_usd"]),
        actual_cost_usd=_float_or_none(row["actual_cost_usd"]),
        cost_status=row["cost_status"],
    )


def _approval_from_row(row: sqlite3.Row) -> ApprovalRecord:
    return ApprovalRecord(
        approval_id=str(row["approval_id"]),
        fingerprint=str(row["fingerprint"]),
        tool=str(row["tool"]),
        action=str(row["action"]),
        status=str(row["status"]),
        reason=str(row["reason"] or ""),
        policy_json=str(row["policy_json"] or "{}"),
        args_json=str(row["args_json"] or "{}"),
        created_at=int(row["created_at"]),
        decided_at=_int_or_none(row["decided_at"]),
        decision=row["decision"],
        decision_reason=row["decision_reason"],
        expires_at=_int_or_none(row["expires_at"]),
    )


def _tool_invocation_from_row(row: sqlite3.Row) -> ToolInvocationRecord:
    return ToolInvocationRecord(
        invocation_id=str(row["invocation_id"]),
        tool=str(row["tool"]),
        status=str(row["status"]),
        started_at=int(row["started_at"]),
        ended_at=_int_or_none(row["ended_at"]),
        approval_id=row["approval_id"],
        query_id=row["query_id"],
        session_id=row["session_id"],
        args_hash=str(row["args_hash"] or ""),
        args_json=str(row["args_json"] or "{}"),
        policy_json=str(row["policy_json"] or "{}"),
        summary=str(row["summary"] or ""),
        output_preview=str(row["output_preview"] or ""),
        error_kind=str(row["error_kind"] or ""),
        duration_ms=_int_or_none(row["duration_ms"]),
        checkpoint_id=row["checkpoint_id"],
    )


def _model_call_from_row(row: sqlite3.Row) -> ModelCallRecord:
    return ModelCallRecord(
        id=int(row["id"]),
        query_id=row["query_id"],
        session_id=row["session_id"],
        task_id=row["task_id"],
        agent_id=row["agent_id"],
        run_id=row["run_id"],
        model=str(row["model"]),
        provider=str(row["provider"] or ""),
        ok=bool(row["ok"]),
        started_at=int(row["started_at"]),
        ended_at=_int_or_none(row["ended_at"]),
        duration_ms=_int_or_none(row["duration_ms"]),
        input_tokens=int(row["input_tokens"] or 0),
        output_tokens=int(row["output_tokens"] or 0),
        cache_read_tokens=int(row["cache_read_tokens"] or 0),
        cache_write_tokens=int(row["cache_write_tokens"] or 0),
        reasoning_tokens=int(row["reasoning_tokens"] or 0),
        total_tokens=int(row["total_tokens"] or 0),
        estimated_input_tokens=int(row["estimated_input_tokens"] or 0),
        estimated_output_tokens=int(row["estimated_output_tokens"] or 0),
        estimated_cost_usd=_float_or_none(row["estimated_cost_usd"]),
        actual_cost_usd=_float_or_none(row["actual_cost_usd"]),
        cost_status=str(row["cost_status"] or "unpriced"),
        cost_source=str(row["cost_source"] or ""),
        pricing_version=str(row["pricing_version"] or ""),
        preflight_applied=bool(row["preflight_applied"]),
        provider_retry_applied=bool(row["provider_retry_applied"]),
        pressure=_float_or_none(row["pressure"]),
        pressure_state=str(row["pressure_state"] or ""),
        error_kind=str(row["error_kind"] or ""),
        error=str(row["error"] or ""),
    )


def _compact_event_from_row(row: sqlite3.Row) -> CompactEventRecord:
    return CompactEventRecord(
        id=int(row["id"]),
        query_id=row["query_id"],
        session_id=row["session_id"],
        task_id=row["task_id"],
        agent_id=row["agent_id"],
        run_id=row["run_id"],
        model=str(row["model"] or ""),
        reason=str(row["reason"] or ""),
        mode=str(row["mode"] or ""),
        applied=bool(row["applied"]),
        created_at=int(row["created_at"]),
        target_tokens=int(row["target_tokens"] or 0),
        original_estimated_tokens=int(row["original_estimated_tokens"] or 0),
        compacted_estimated_tokens=int(row["compacted_estimated_tokens"] or 0),
        saved_estimated_tokens=int(row["saved_estimated_tokens"] or 0),
        protected_user_request=bool(row["protected_user_request"]),
        tokenizer_source=str(row["tokenizer_source"] or ""),
        token_count_exact=bool(row["token_count_exact"]),
    )


def _budget_reservation_from_row(row: sqlite3.Row) -> BudgetReservationRecord:
    return BudgetReservationRecord(
        reservation_id=str(row["reservation_id"]),
        status=str(row["status"]),
        session_id=str(row["session_id"]),
        query_id=row["query_id"],
        model=str(row["model"]),
        provider=str(row["provider"] or ""),
        estimated_tokens=int(row["estimated_tokens"] or 0),
        estimated_cost_usd=_float_or_none(row["estimated_cost_usd"]),
        created_at=int(row["created_at"]),
        expires_at=int(row["expires_at"]),
        task_id=row["task_id"],
        agent_id=row["agent_id"],
        run_id=row["run_id"],
        actual_tokens=int(row["actual_tokens"] or 0),
        actual_cost_usd=_float_or_none(row["actual_cost_usd"]),
        model_call_id=_int_or_none(row["model_call_id"]),
        release_reason=str(row["release_reason"] or ""),
        updated_at=_int_or_none(row["updated_at"]),
        completed_at=_int_or_none(row["completed_at"]),
        checks_json=str(row["checks_json"] or ""),
    )


def _runtime_queue_item_from_row(row: sqlite3.Row) -> RuntimeQueueItem:
    return RuntimeQueueItem(
        task_id=str(row["task_id"]),
        queue=str(row["queue"] or "default"),
        task=str(row["task"] or ""),
        task_kind=str(row["task_kind"] or "manual"),
        status=str(row["status"] or RUNTIME_QUEUE_QUEUED),
        priority=int(row["priority"] or 0),
        owner_key=str(row["owner_key"] or "local"),
        lease_owner=row["lease_owner"],
        lease_expires_at=_int_or_none(row["lease_expires_at"]),
        heartbeat_at=_int_or_none(row["heartbeat_at"]),
        session_lock_key=row["session_lock_key"],
        stop_file=row["stop_file"],
        resume_of=row["resume_of"],
        attempts=int(row["attempts"] or 0),
        max_attempts=int(row["max_attempts"] or 0),
        created_at=int(row["created_at"] or 0),
        updated_at=int(row["updated_at"] or 0),
        started_at=_int_or_none(row["started_at"]),
        ended_at=_int_or_none(row["ended_at"]),
        summary=str(row["summary"] or ""),
        error=str(row["error"] or ""),
        payload_json=str(row["payload_json"] or "{}"),
    )


def _finish_runtime_queue_item(
    project: str | Path,
    item_id: str,
    *,
    lease_owner: str,
    status: str,
    summary: str,
    payload: dict[str, Any] | str | None = None,
    error: str = "",
    now_ms: int | None = None,
) -> RuntimeQueueItem:
    _validate_runtime_queue_status(status)
    path = ensure_runtime_store(project)
    timestamp = int(now_ms if now_ms is not None else _now_ms())
    with _connect(path) as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT * FROM runtime_queue WHERE task_id = ?", (_runtime_queue_id(item_id),)).fetchone()
        _require_runtime_queue_running(row, lease_owner)
        updates = [
            "status = ?",
            "summary = ?",
            "error = ?",
            "updated_at = ?",
            "ended_at = ?",
            "lease_expires_at = NULL",
        ]
        params: list[Any] = [status, str(summary or ""), str(error or ""), timestamp, timestamp]
        if payload is not None:
            updates.append("payload_json = ?")
            params.append(_json_dumps(payload))
        params.append(row["task_id"])
        conn.execute(f"UPDATE runtime_queue SET {', '.join(updates)} WHERE task_id = ?", tuple(params))
        updated = conn.execute("SELECT * FROM runtime_queue WHERE task_id = ?", (row["task_id"],)).fetchone()
    return _runtime_queue_item_from_row(updated)


def _require_runtime_queue_running(row: sqlite3.Row | None, lease_owner: str) -> None:
    if row is None:
        raise ValueError("runtime queue item not found")
    status = str(row["status"] or "")
    if status != RUNTIME_QUEUE_RUNNING:
        raise ValueError(f"runtime queue item is not running: {status}")
    if str(row["lease_owner"] or "") != str(lease_owner):
        raise ValueError("runtime queue lease owner mismatch")


def _runtime_queue_stop_file_present(project: Path, stop_file: str) -> bool:
    path = Path(stop_file).expanduser()
    if not path.is_absolute():
        path = project / path
    return path.exists()


def _runtime_queue_id(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return "rq-" + uuid.uuid4().hex[:12]
    return text


def _runtime_queue_name(value: str | None) -> str:
    return str(value or "default").strip() or "default"


def _runtime_queue_status_filter(status: str | Iterable[str] | None) -> list[str]:
    if status is None:
        return []
    if isinstance(status, str):
        values = [status]
    else:
        values = [str(item) for item in status]
    normalized = []
    for item in values:
        text = item.strip()
        if not text:
            continue
        _validate_runtime_queue_status(text)
        normalized.append(text)
    return normalized


def _validate_runtime_queue_status(status: str) -> None:
    if status not in RUNTIME_QUEUE_STATUSES:
        raise ValueError(f"invalid runtime queue status: {status}")


def _lease_ms(seconds: float) -> int:
    return max(1, int(float(seconds) * 1000))


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?", (name,)).fetchone()
    return row is not None


def _terminal_outcome(status: str) -> str | None:
    if status == PASSED:
        return "success"
    if status == FAILED:
        return "failed"
    if status == BLOCKED:
        return "blocked"
    if status == ABORTED:
        return "aborted"
    if status == LOST:
        return "lost"
    return None


def _sha256_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json_dumps(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _coerce_ms(value: str | int | float | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return int(number if number > 10_000_000_000 else number * 1000)
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        pass
    else:
        return int(number if number > 10_000_000_000 else number * 1000)
    try:
        from datetime import datetime

        return int(datetime.fromisoformat(text).timestamp() * 1000)
    except ValueError:
        return None


def _now_ms() -> int:
    return int(time.time() * 1000)


def _int_or_none(value: Any) -> int | None:
    return None if value is None else int(value)


def _int_or_zero(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, number)


def _first_int(data: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = _int_or_zero(data.get(key))
        if value:
            return value
    return 0


def _nested_int(data: dict[str, Any], *keys: str) -> int:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return 0
        current = current.get(key)
    return _int_or_zero(current)


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_float(data: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _float_or_none(data.get(key))
        if value is not None:
            return value
    return None


def _reservation_ttl_ms(ttl_seconds: int | None = None) -> int:
    if ttl_seconds is None:
        try:
            ttl_seconds = int(os.environ.get("QUANTAGENT_MODEL_BUDGET_RESERVATION_TTL_SECONDS", "300"))
        except ValueError:
            ttl_seconds = 300
    return max(1, int(ttl_seconds)) * 1000


def _bool_to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return 1 if bool(value) else 0
