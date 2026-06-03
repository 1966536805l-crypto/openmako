from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
MEMORY_ENTRY_CHAR_BUDGET = 1375
MEMORY_RENDER_CHAR_BUDGET = 2200
MEMORY_ITEM_PREVIEW_CHARS = 220


INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ignore_prior_instructions",
        re.compile(
            r"\b(?:ignore|disregard|forget)\s+(?:all\s+|any\s+|the\s+)?"
            r"(?:(?:previous|prior|above|earlier)(?:\s+(?:system|developer|tool|safety))?|system|developer)\s+"
            r"(?:instructions?|messages?|rules?|prompts?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "override_system_policy",
        re.compile(
            r"\b(?:override|bypass|disable)\s+(?:the\s+)?"
            r"(?:system|developer|safety|tool)\s+(?:instructions?|messages?|rules?|policy|guardrails?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "prompt_exfiltration",
        re.compile(
            r"\b(?:reveal|print|dump|show|exfiltrate|leak)\s+(?:the\s+)?"
            r"(?:(?:system|developer|hidden)\s+){1,3}(?:prompt|message|instructions?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "credential_exfiltration",
        re.compile(
            r"\b(?:exfiltrate|leak|dump|print|send)\s+"
            r"(?:secrets?|api[_ -]?keys?|tokens?|credentials?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role_injection",
        re.compile(r"(?im)^\s*(?:system|developer|tool)\s*:\s*(?:ignore|override|disregard|you are)\b"),
    ),
    (
        "zh_ignore_prior_instructions",
        re.compile(r"(?:忽略|无视|忘记).{0,24}(?:系统|开发者|上面|之前|先前).{0,24}(?:指令|消息|规则|提示)"),
    ),
    (
        "zh_prompt_exfiltration",
        re.compile(r"(?:泄露|打印|输出|展示).{0,24}(?:系统|开发者|隐藏).{0,24}(?:提示词|提示|指令|消息)"),
    ),
)


@dataclass(frozen=True)
class MemorySafetyReport:
    ok: bool
    reasons: tuple[str, ...]
    original_chars: int
    stored_chars: int
    truncated: bool


@dataclass(frozen=True)
class MemoryEntry:
    id: int
    kind: str
    text: str
    source: str
    created_at: float
    meta: dict[str, Any]


def memory_dir(project: Path) -> Path:
    base = project / "AI_协作交接"
    return (base if base.exists() else project / ".quantagent") / "memory"


def memory_db_path(project: Path) -> Path:
    return memory_dir(project) / "memory.db"


class MemoryStore:
    """Small SQLite/FTS5 memory store inspired by Hermes/OpenClaw.

    It keeps Mako lightweight: one local DB, WAL when available, and a
    graceful LIKE fallback if FTS5 is unavailable.
    """

    def __init__(self, project: Path) -> None:
        self.project = project
        path = memory_db_path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.fts_enabled = self._init_db()

    def close(self) -> None:
        self.conn.close()

    def _init_db(self) -> bool:
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            self.conn.execute("PRAGMA journal_mode=DELETE")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                meta_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        fts_enabled = True
        try:
            self.conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                USING fts5(text, kind, source, content='memories', content_rowid='id')
                """
            )
        except sqlite3.OperationalError:
            fts_enabled = False
        if not self.conn.execute("SELECT 1 FROM schema_version LIMIT 1").fetchone():
            self.conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
        self.conn.commit()
        return fts_enabled

    def add(self, text: str, kind: str = "note", source: str = "", meta: dict[str, Any] | None = None) -> MemoryEntry:
        prepared_text, safety = prepare_memory_text(text)
        if not safety.ok:
            raise ValueError(f"unsafe memory text: {', '.join(safety.reasons)}")
        if not prepared_text:
            raise ValueError("memory text is empty")
        created_at = time.time()
        meta_payload = dict(meta or {})
        meta_payload["memory_budget"] = {
            "entry_char_budget": MEMORY_ENTRY_CHAR_BUDGET,
            "original_chars": safety.original_chars,
            "stored_chars": safety.stored_chars,
            "truncated": safety.truncated,
        }
        meta_payload["memory_safety"] = {"ok": True, "reasons": []}
        meta_json = json.dumps(meta_payload, ensure_ascii=False, sort_keys=True)
        cur = self.conn.execute(
            "INSERT INTO memories(kind, text, source, created_at, meta_json) VALUES (?, ?, ?, ?, ?)",
            (kind, prepared_text, source, created_at, meta_json),
        )
        rowid = int(cur.lastrowid)
        if self.fts_enabled:
            self.conn.execute(
                "INSERT INTO memories_fts(rowid, text, kind, source) VALUES (?, ?, ?, ?)",
                (rowid, prepared_text, kind, source),
            )
        self.conn.commit()
        return self.get(rowid)

    def get(self, rowid: int) -> MemoryEntry:
        row = self.conn.execute("SELECT * FROM memories WHERE id = ?", (rowid,)).fetchone()
        if not row:
            raise KeyError(f"memory not found: {rowid}")
        return _entry(row)

    def recent(self, limit: int = 20, kind: str | None = None) -> list[MemoryEntry]:
        if kind:
            rows = self.conn.execute(
                "SELECT * FROM memories WHERE kind = ? ORDER BY created_at DESC LIMIT ?",
                (kind, max(1, limit)),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?",
                (max(1, limit),),
            ).fetchall()
        return [_entry(row) for row in rows]

    def search(self, query: str, limit: int = 20) -> list[MemoryEntry]:
        query = query.strip()
        if not query:
            return []
        if self.fts_enabled:
            rows = self.conn.execute(
                """
                SELECT memories.*
                FROM memories_fts
                JOIN memories ON memories_fts.rowid = memories.id
                WHERE memories_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (_fts_query(query), max(1, limit)),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM memories
                WHERE text LIKE ? OR kind LIKE ? OR source LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (f"%{query}%", f"%{query}%", f"%{query}%", max(1, limit)),
            ).fetchall()
        return [_entry(row) for row in rows]


def _fts_query(query: str) -> str:
    parts = [part.replace('"', '""') for part in query.split() if part]
    return " OR ".join(f'"{part}"' for part in parts) if parts else '""'


def inspect_memory_text(text: str) -> MemorySafetyReport:
    original = str(text)
    cleaned = _clean_memory_text(original)
    reasons: list[str] = []
    if not cleaned:
        reasons.append("empty")
    for name, pattern in INJECTION_PATTERNS:
        if pattern.search(cleaned):
            reasons.append(name)
    stored_chars = min(len(cleaned), MEMORY_ENTRY_CHAR_BUDGET)
    return MemorySafetyReport(
        ok=not reasons,
        reasons=tuple(reasons),
        original_chars=len(cleaned),
        stored_chars=stored_chars,
        truncated=len(cleaned) > MEMORY_ENTRY_CHAR_BUDGET,
    )


def prepare_memory_text(text: str) -> tuple[str, MemorySafetyReport]:
    cleaned = _clean_memory_text(text)
    report = inspect_memory_text(cleaned)
    if not report.ok:
        return "", report
    if len(cleaned) <= MEMORY_ENTRY_CHAR_BUDGET:
        return cleaned, report
    return cleaned[: MEMORY_ENTRY_CHAR_BUDGET - 3].rstrip() + "...", report


def blocked_memory_placeholder(report: MemorySafetyReport) -> str:
    reason = ",".join(report.reasons) if report.reasons else "unknown"
    return f"[blocked unsafe memory text: {reason}]"


def _entry(row: sqlite3.Row) -> MemoryEntry:
    try:
        meta = json.loads(row["meta_json"] or "{}")
    except json.JSONDecodeError:
        meta = {}
    return MemoryEntry(
        id=int(row["id"]),
        kind=str(row["kind"]),
        text=str(row["text"]),
        source=str(row["source"]),
        created_at=float(row["created_at"]),
        meta=meta if isinstance(meta, dict) else {},
    )


def render_memories(entries: list[MemoryEntry], *, max_chars: int = MEMORY_RENDER_CHAR_BUDGET) -> str:
    if not entries:
        return "No memories.\n"
    lines = ["# Mako Memory", ""]
    rows = list(entries)
    omitted = 0
    for index, item in enumerate(rows):
        text = item.text.replace("\n", " ")
        if len(text) > MEMORY_ITEM_PREVIEW_CHARS:
            text = text[: MEMORY_ITEM_PREVIEW_CHARS - 3] + "..."
        source = f" source={item.source}" if item.source else ""
        line = f"- #{item.id} [{item.kind}]{source}: {text}"
        candidate = "\n".join(lines + [line]) + "\n"
        if max_chars > 0 and len(candidate) > max_chars:
            omitted = len(rows) - index
            break
        lines.append(line)
    if omitted:
        notice = f"- ... {omitted} more memories omitted by memory budget"
        candidate = "\n".join(lines + [notice]) + "\n"
        if max_chars <= 0 or len(candidate) <= max_chars:
            lines.append(notice)
    rendered = "\n".join(lines) + "\n"
    return _fit_chars(rendered, max_chars)


def _clean_memory_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def _fit_chars(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    if max_chars <= 4:
        return text[:max_chars]
    return text[: max_chars - 4].rstrip() + "...\n"
