from __future__ import annotations

from .exception_audit import audit_suppressed_exception
from contextlib import contextmanager
import json
import re
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .input_provenance import annotate_inter_session_text, normalize_input_provenance
from .lifecycle_hooks import run_lifecycle_hook
from .runtime_store import append_runtime_message, ensure_runtime_store, record_compact_event, search_messages, upsert_session
from .trajectory_compact import compact_messages


@dataclass
class SessionMessage:
    role: str
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionRecord:
    session_id: str
    title: str
    project: str
    created_at: str
    updated_at: str
    summary: str = ""
    messages: list[SessionMessage] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SessionLock:
    project: Path
    session_id: str
    owner: str
    token: str
    acquired_at: int
    expires_at: int


class SessionLockError(RuntimeError):
    pass


def sessions_dir(project: Path) -> Path:
    base = project / "AI_协作交接"
    legacy = project / "quantagent_sessions"
    if legacy.exists():
        return legacy
    return (base if base.exists() else project) / "quantagent_sessions"


def _slug(text: str) -> str:
    text = re.sub(r"\s+", "-", text.strip().lower())
    text = re.sub(r"[^a-z0-9._-]+", "", text)
    return text[:40].strip("-") or "session"


def new_session_id(title: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{_slug(title)}"


def session_path(project: Path, session_id: str) -> Path:
    return sessions_dir(project) / f"{session_id}.json"


def save_session(project: Path, record: SessionRecord) -> Path:
    directory = sessions_dir(project)
    directory.mkdir(parents=True, exist_ok=True)
    record.updated_at = datetime.now().isoformat(timespec="seconds")
    path = session_path(project, record.session_id)
    path.write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    upsert_session(
        project,
        session_id=record.session_id,
        source="cli",
        title=record.title,
        project_path=record.project,
        started_at=record.created_at,
        summary=record.summary,
    )
    return path


def create_session(project: Path, title: str = "Mako session") -> SessionRecord:
    now = datetime.now().isoformat(timespec="seconds")
    record = SessionRecord(
        session_id=new_session_id(title),
        title=title,
        project=str(project),
        created_at=now,
        updated_at=now,
    )
    save_session(project, record)
    run_lifecycle_hook(
        project,
        "session_start",
        {"session_id": record.session_id, "title": record.title, "project": record.project},
        session_id=record.session_id,
    )
    return record


def load_session(project: Path, session_id: str) -> SessionRecord:
    path = session_path(project, session_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    messages = [SessionMessage(**item) for item in data.get("messages", [])]
    return SessionRecord(
        session_id=data["session_id"],
        title=data.get("title") or data["session_id"],
        project=data.get("project") or str(project),
        created_at=data.get("created_at") or "",
        updated_at=data.get("updated_at") or "",
        summary=data.get("summary") or "",
        messages=messages,
    )


def list_sessions(project: Path) -> list[SessionRecord]:
    directory = sessions_dir(project)
    if not directory.exists():
        return []
    records: list[SessionRecord] = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        try:
            records.append(load_session(project, path.stem))
        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:121", exc)
            continue
    return records


def latest_session(project: Path) -> SessionRecord | None:
    records = list_sessions(project)
    return records[0] if records else None


def append_message(
    project: Path,
    session_id: str,
    role: str,
    content: str,
    meta: dict[str, Any] | None = None,
) -> SessionRecord:
    record = load_session(project, session_id)
    message_meta = dict(meta or {})
    provenance = normalize_input_provenance(message_meta.get("provenance"))
    if provenance:
        message_meta["provenance"] = provenance.to_dict()
    message_content = annotate_inter_session_text(content, provenance) if role == "user" else content
    message = SessionMessage(role=role, content=message_content, meta=message_meta)
    record.messages.append(message)
    save_session(project, record)
    append_runtime_message(
        project,
        session_id=session_id,
        role=role,
        content=message_content,
        timestamp=message.timestamp,
        tool_calls=message_meta.get("tool_calls"),
        tool_name=message_meta.get("tool_name"),
        token_count=_int_meta(message_meta, "token_count"),
        finish_reason=str(message_meta.get("finish_reason") or ""),
        reasoning=str(message_meta.get("reasoning_summary") or message_meta.get("reasoning") or ""),
        meta=message_meta,
    )
    return record


def acquire_session_lock(
    project: str | Path,
    session_id: str,
    owner: str,
    ttl_seconds: int = 300,
) -> SessionLock | None:
    if not session_id or not owner or ttl_seconds <= 0:
        return None
    project_path = Path(project).expanduser().resolve(strict=False)
    now_ms = _now_ms()
    expires_ms = now_ms + int(ttl_seconds * 1000)
    token = uuid.uuid4().hex
    conn: sqlite3.Connection | None = None
    try:
        conn = _session_lock_connection(project_path)
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT owner, expires_at FROM session_locks WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row and str(row["owner"]) != owner and int(row["expires_at"] or 0) > now_ms:
            conn.execute("ROLLBACK")
            return None
        conn.execute(
            """
            INSERT INTO session_locks (
                session_id, owner, token, acquired_at, renewed_at, expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                owner = excluded.owner,
                token = excluded.token,
                renewed_at = excluded.renewed_at,
                expires_at = excluded.expires_at
            """,
            (session_id, owner, token, now_ms, now_ms, expires_ms),
        )
        conn.execute("COMMIT")
        return SessionLock(
            project=project_path,
            session_id=session_id,
            owner=owner,
            token=token,
            acquired_at=now_ms,
            expires_at=expires_ms,
        )
    except Exception as exc:
        _rollback_quietly(conn)
        audit_suppressed_exception(f"{__name__}:acquire_session_lock", exc)
        return None
    finally:
        if conn is not None:
            conn.close()


def release_session_lock(project: str | Path, session_id: str, owner: str) -> bool:
    if not session_id or not owner:
        return False
    conn: sqlite3.Connection | None = None
    try:
        conn = _session_lock_connection(project)
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "DELETE FROM session_locks WHERE session_id = ? AND owner = ?",
            (session_id, owner),
        )
        released = cursor.rowcount > 0
        conn.execute("COMMIT")
        return released
    except Exception as exc:
        _rollback_quietly(conn)
        audit_suppressed_exception(f"{__name__}:release_session_lock", exc)
        return False
    finally:
        if conn is not None:
            conn.close()


@contextmanager
def with_session_lock(
    project: str | Path,
    session_id: str,
    owner: str,
    ttl_seconds: int = 300,
) -> Iterator[SessionLock]:
    lock = acquire_session_lock(project, session_id, owner, ttl_seconds=ttl_seconds)
    if lock is None:
        raise SessionLockError(f"session lock unavailable: {session_id}")
    try:
        yield lock
    finally:
        release_session_lock(project, session_id, owner)


def search_session_messages(project: Path, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
    return search_messages(project, query, limit=limit)


def export_session(project: Path, session_id: str, *, format: str = "json") -> str:
    record = load_session(project, session_id)
    if format == "json":
        return json.dumps(record.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if format != "markdown":
        raise ValueError("format must be json or markdown")
    lines = [
        f"# Session Export: {record.title}",
        "",
        f"- session_id: {record.session_id}",
        f"- project: {record.project}",
        f"- created_at: {record.created_at}",
        f"- updated_at: {record.updated_at}",
        f"- messages: {len(record.messages)}",
        "",
    ]
    if record.summary:
        lines.extend(["## Summary", "", record.summary.strip(), ""])
    lines.append("## Messages")
    for message in record.messages:
        lines.extend(["", f"### {message.timestamp} {message.role}", "", message.content.strip()])
        if message.meta:
            lines.extend(["", "```json", json.dumps(message.meta, ensure_ascii=False, indent=2, sort_keys=True), "```"])
    return "\n".join(lines).rstrip() + "\n"


def close_session(project: Path, session_id: str, *, reason: str = "") -> SessionRecord:
    record = load_session(project, session_id)
    run_lifecycle_hook(
        project,
        "session_end",
        {
            "session_id": record.session_id,
            "title": record.title,
            "project": record.project,
            "messages": len(record.messages),
            "reason": reason,
        },
        session_id=record.session_id,
    )
    suffix = f" reason={reason}" if reason else ""
    stamp = datetime.now().isoformat(timespec="seconds")
    ended = f"Session ended at {stamp}{suffix}."
    record.summary = (record.summary.rstrip() + "\n" if record.summary else "") + ended
    save_session(project, record)
    return record


def compact_session(project: Path, session_id: str, keep_last: int = 8) -> SessionRecord:
    record = load_session(project, session_id)
    if len(record.messages) > keep_last:
        result = compact_messages(record.messages, first_n=1, last_n=keep_last)
        summary_entry = result.summary_entry
        summary_text = str(summary_entry.get("content") or "") if summary_entry else ""
        metrics = result.metrics.to_dict()
        try:
            record_compact_event(
                project,
                model="session",
                reason="manual_session_compact",
                mode="session",
                applied=True,
                session_id=session_id,
                target_tokens=0,
                original_estimated_tokens=int(metrics.get("original_estimated_tokens") or 0),
                compacted_estimated_tokens=int(metrics.get("compacted_estimated_tokens") or 0),
                saved_estimated_tokens=int(metrics.get("saved_estimated_tokens") or 0),
                protected_user_request=False,
                tokenizer_source="heuristic:trajectory_compact",
                token_count_exact=False,
                details={
                    "original_messages": metrics.get("original_messages"),
                    "compacted_messages": metrics.get("final_messages"),
                    "persisted_messages": keep_last,
                    "preserved_first": metrics.get("preserved_first"),
                    "preserved_last": metrics.get("preserved_last"),
                    "summarized_middle": metrics.get("summarized_middle"),
                    "summary_trimmed": metrics.get("summary_trimmed"),
                },
            )
        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:239", exc)
        prefix = (record.summary.rstrip() + "\n" if record.summary else "")
        record.summary = prefix + summary_text + "\n" + "Metrics: " + json.dumps(metrics, ensure_ascii=False, sort_keys=True)
        record.messages = [
            SessionMessage(
                role=str(item.get("role") or "unknown"),
                content=str(item.get("content") or ""),
                timestamp=str(item.get("timestamp") or datetime.now().isoformat(timespec="seconds")),
                meta=dict(item.get("meta") or {}),
            )
            for item in result.messages[-keep_last:]
        ]
    save_session(project, record)
    return record


def render_session(record: SessionRecord, limit: int = 20) -> str:
    lines = [
        f"# Session {record.session_id}",
        "",
        f"- title: {record.title}",
        f"- project: {record.project}",
        f"- created: {record.created_at}",
        f"- updated: {record.updated_at}",
        f"- messages: {len(record.messages)}",
    ]
    if record.summary:
        lines.extend(["", "## Summary", "", record.summary.strip()])
    lines.extend(["", "## Recent Messages", ""])
    for message in record.messages[-limit:]:
        content = message.content.strip().replace("\n", " ")
        if len(content) > 220:
            content = content[:217] + "..."
        lines.append(f"- {message.timestamp} [{message.role}] {content}")
    return "\n".join(lines) + "\n"


def render_session_search(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No matching session messages.\n"
    lines = ["# Session Search", ""]
    for row in rows:
        content = str(row.get("content") or "").replace("\n", " ")
        if len(content) > 220:
            content = content[:217] + "..."
        lines.append(f"- {row.get('session_id')} {row.get('role')} {row.get('timestamp')}: {content}")
    return "\n".join(lines) + "\n"


def _int_meta(meta: dict[str, Any], key: str) -> int | None:
    value = meta.get(key)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _session_lock_connection(project: str | Path) -> sqlite3.Connection:
    db_path = ensure_runtime_store(project)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS session_locks (
            session_id TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            token TEXT NOT NULL,
            acquired_at INTEGER NOT NULL,
            renewed_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_session_locks_expires_at ON session_locks(expires_at)")
    return conn


def _rollback_quietly(conn: sqlite3.Connection | None) -> None:
    if conn is None:
        return
    try:
        conn.execute("ROLLBACK")
    except sqlite3.Error:
        return


def _now_ms() -> int:
    return int(time.time() * 1000)
