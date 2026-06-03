from __future__ import annotations

import json
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 1
DEFAULT_MAX_ENTRIES = 100
MAX_ID_BYTES = 128
MAX_KEY_BYTES = 512

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_UNSET = object()


@dataclass(frozen=True)
class PluginStateEntry:
    plugin_id: str
    namespace: str
    key: str
    value: Any
    created_at: int
    expires_at: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PluginStateStoreProbeStep:
    name: str
    ok: bool
    code: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True)
class PluginStateStoreProbeResult:
    ok: bool
    db_path: str
    steps: tuple[PluginStateStoreProbeStep, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "db_path": self.db_path,
            "steps": [step.to_dict() for step in self.steps],
        }


class PluginStateStoreError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        operation: str,
        path: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.operation = operation
        self.path = path
        self.__cause__ = cause

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "code": self.code,
            "operation": self.operation,
            "message": str(self),
        }
        if self.path:
            payload["path"] = self.path
        return payload


class PluginStateKeyedStore:
    def __init__(
        self,
        project: str | Path,
        plugin_id: str,
        namespace: str,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        default_ttl_ms: int | None = None,
    ) -> None:
        self.project = Path(project).expanduser().resolve(strict=False)
        self.plugin_id = _validate_id(plugin_id, "plugin_id", "open")
        self.namespace = _validate_id(namespace, "namespace", "open")
        self.max_entries = _validate_positive_int(max_entries, "max_entries", "open")
        self.default_ttl_ms = _validate_ttl(default_ttl_ms, "open") if default_ttl_ms is not None else None
        self.db_path = plugin_state_db_path(self.project)
        ensure_plugin_state_store(self.project)

    def register(self, key: str, value: Any, *, ttl_ms: int | None | object = _UNSET) -> None:
        entry_key = _validate_key(key, "register")
        value_json = _json_dumps(value, "register")
        now = _now_ms()
        expires_at = self._expires_at(now, ttl_ms, "register")
        try:
            with _open_ready(self.db_path) as conn:
                conn.commit()
                conn.execute("BEGIN IMMEDIATE")
                _delete_expired_namespace(conn, self.plugin_id, self.namespace, now)
                conn.execute(
                    """
                    INSERT INTO plugin_state_entries (
                        plugin_id, namespace, entry_key, value_json, created_at, expires_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(plugin_id, namespace, entry_key) DO UPDATE SET
                        value_json = excluded.value_json,
                        created_at = excluded.created_at,
                        expires_at = excluded.expires_at
                    """,
                    (self.plugin_id, self.namespace, entry_key, value_json, now, expires_at),
                )
                _prune_namespace(conn, self.plugin_id, self.namespace, self.max_entries, now, keep_key=entry_key)
        except PluginStateStoreError:
            raise
        except sqlite3.Error as exc:
            raise _sqlite_error("Failed to register plugin state entry.", "PLUGIN_STATE_WRITE_FAILED", "register", self.db_path, exc)

    def register_if_absent(self, key: str, value: Any, *, ttl_ms: int | None | object = _UNSET) -> bool:
        entry_key = _validate_key(key, "register")
        value_json = _json_dumps(value, "register")
        now = _now_ms()
        expires_at = self._expires_at(now, ttl_ms, "register")
        try:
            with _open_ready(self.db_path) as conn:
                conn.commit()
                conn.execute("BEGIN IMMEDIATE")
                _delete_expired_namespace(conn, self.plugin_id, self.namespace, now)
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO plugin_state_entries (
                        plugin_id, namespace, entry_key, value_json, created_at, expires_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (self.plugin_id, self.namespace, entry_key, value_json, now, expires_at),
                )
                inserted = cursor.rowcount == 1
                if inserted:
                    _prune_namespace(conn, self.plugin_id, self.namespace, self.max_entries, now, keep_key=entry_key)
                return inserted
        except PluginStateStoreError:
            raise
        except sqlite3.Error as exc:
            raise _sqlite_error("Failed to register plugin state entry.", "PLUGIN_STATE_WRITE_FAILED", "register", self.db_path, exc)

    def lookup(self, key: str, default: Any = None) -> Any:
        entry_key = _validate_key(key, "lookup")
        row = self._live_row(entry_key, "lookup")
        if row is None:
            return default
        return _json_loads(str(row["value_json"]), "lookup", self.db_path)

    def consume(self, key: str, default: Any = None) -> Any:
        entry_key = _validate_key(key, "consume")
        now = _now_ms()
        try:
            with _open_ready(self.db_path) as conn:
                conn.commit()
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    """
                    SELECT value_json
                    FROM plugin_state_entries
                    WHERE plugin_id = ?
                      AND namespace = ?
                      AND entry_key = ?
                      AND (expires_at IS NULL OR expires_at > ?)
                    """,
                    (self.plugin_id, self.namespace, entry_key, now),
                ).fetchone()
                if row is None:
                    return default
                conn.execute(
                    """
                    DELETE FROM plugin_state_entries
                    WHERE plugin_id = ? AND namespace = ? AND entry_key = ?
                    """,
                    (self.plugin_id, self.namespace, entry_key),
                )
                return _json_loads(str(row["value_json"]), "consume", self.db_path)
        except PluginStateStoreError:
            raise
        except sqlite3.Error as exc:
            raise _sqlite_error("Failed to consume plugin state entry.", "PLUGIN_STATE_WRITE_FAILED", "consume", self.db_path, exc)

    def delete(self, key: str) -> bool:
        entry_key = _validate_key(key, "delete")
        try:
            with _open_ready(self.db_path) as conn:
                cursor = conn.execute(
                    """
                    DELETE FROM plugin_state_entries
                    WHERE plugin_id = ? AND namespace = ? AND entry_key = ?
                    """,
                    (self.plugin_id, self.namespace, entry_key),
                )
                return cursor.rowcount > 0
        except PluginStateStoreError:
            raise
        except sqlite3.Error as exc:
            raise _sqlite_error("Failed to delete plugin state entry.", "PLUGIN_STATE_WRITE_FAILED", "delete", self.db_path, exc)

    def entries(self) -> list[PluginStateEntry]:
        now = _now_ms()
        try:
            with _open_ready(self.db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT plugin_id, namespace, entry_key, value_json, created_at, expires_at
                    FROM plugin_state_entries
                    WHERE plugin_id = ?
                      AND namespace = ?
                      AND (expires_at IS NULL OR expires_at > ?)
                    ORDER BY created_at ASC, entry_key ASC
                    """,
                    (self.plugin_id, self.namespace, now),
                ).fetchall()
        except PluginStateStoreError:
            raise
        except sqlite3.Error as exc:
            raise _sqlite_error("Failed to list plugin state entries.", "PLUGIN_STATE_READ_FAILED", "entries", self.db_path, exc)
        return [_entry_from_row(row, "entries", self.db_path) for row in rows]

    def clear(self) -> int:
        try:
            with _open_ready(self.db_path) as conn:
                cursor = conn.execute(
                    """
                    DELETE FROM plugin_state_entries
                    WHERE plugin_id = ? AND namespace = ?
                    """,
                    (self.plugin_id, self.namespace),
                )
                return int(cursor.rowcount)
        except PluginStateStoreError:
            raise
        except sqlite3.Error as exc:
            raise _sqlite_error("Failed to clear plugin state entries.", "PLUGIN_STATE_WRITE_FAILED", "clear", self.db_path, exc)

    def sweep(self) -> int:
        now = _now_ms()
        try:
            with _open_ready(self.db_path) as conn:
                return _delete_expired_namespace(conn, self.plugin_id, self.namespace, now)
        except PluginStateStoreError:
            raise
        except sqlite3.Error as exc:
            raise _sqlite_error("Failed to sweep plugin state entries.", "PLUGIN_STATE_WRITE_FAILED", "sweep", self.db_path, exc)

    def probe(self) -> PluginStateStoreProbeResult:
        return probe_plugin_state_store(self.project)

    def _live_row(self, key: str, operation: str) -> sqlite3.Row | None:
        now = _now_ms()
        try:
            with _open_ready(self.db_path) as conn:
                return conn.execute(
                    """
                    SELECT plugin_id, namespace, entry_key, value_json, created_at, expires_at
                    FROM plugin_state_entries
                    WHERE plugin_id = ?
                      AND namespace = ?
                      AND entry_key = ?
                      AND (expires_at IS NULL OR expires_at > ?)
                    """,
                    (self.plugin_id, self.namespace, key, now),
                ).fetchone()
        except PluginStateStoreError:
            raise
        except sqlite3.Error as exc:
            raise _sqlite_error("Failed to read plugin state entry.", "PLUGIN_STATE_READ_FAILED", operation, self.db_path, exc)

    def _expires_at(self, now: int, ttl_ms: int | None | object, operation: str) -> int | None:
        effective_ttl = self.default_ttl_ms if ttl_ms is _UNSET else ttl_ms
        if effective_ttl is None:
            return None
        return now + _validate_ttl(effective_ttl, operation)


def plugin_state_db_path(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "plugin_state.sqlite"


def ensure_plugin_state_store(project: str | Path) -> Path:
    path = plugin_state_db_path(project)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _open_ready(path):
            pass
    except PluginStateStoreError:
        raise
    except sqlite3.Error as exc:
        raise _sqlite_error("Failed to open plugin state database.", "PLUGIN_STATE_OPEN_FAILED", "open", path, exc)
    return path


def create_plugin_state_keyed_store(
    project: str | Path,
    plugin_id: str,
    *,
    namespace: str,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    default_ttl_ms: int | None = None,
) -> PluginStateKeyedStore:
    return PluginStateKeyedStore(
        project,
        plugin_id,
        namespace,
        max_entries=max_entries,
        default_ttl_ms=default_ttl_ms,
    )


def open_plugin_state_keyed_store(
    project: str | Path,
    plugin_id: str,
    *,
    namespace: str,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    default_ttl_ms: int | None = None,
) -> PluginStateKeyedStore:
    return create_plugin_state_keyed_store(
        project,
        plugin_id,
        namespace=namespace,
        max_entries=max_entries,
        default_ttl_ms=default_ttl_ms,
    )


def sweep_expired_plugin_state_entries(project: str | Path) -> int:
    path = ensure_plugin_state_store(project)
    now = _now_ms()
    try:
        with _open_ready(path) as conn:
            cursor = conn.execute(
                """
                DELETE FROM plugin_state_entries
                WHERE expires_at IS NOT NULL AND expires_at <= ?
                """,
                (now,),
            )
            return int(cursor.rowcount)
    except PluginStateStoreError:
        raise
    except sqlite3.Error as exc:
        raise _sqlite_error("Failed to sweep plugin state entries.", "PLUGIN_STATE_WRITE_FAILED", "sweep", path, exc)


def probe_plugin_state_store(project: str | Path) -> PluginStateStoreProbeResult:
    path = plugin_state_db_path(project)
    steps: list[PluginStateStoreProbeStep] = []
    probe_key = f"probe-{_now_ms()}"

    def record(name: str, callback: Any) -> None:
        try:
            callback()
        except PluginStateStoreError as exc:
            steps.append(PluginStateStoreProbeStep(name, False, exc.code, str(exc)))
        except Exception as exc:
            steps.append(PluginStateStoreProbeStep(name, False, "PLUGIN_STATE_PROBE_FAILED", str(exc)))
        else:
            steps.append(PluginStateStoreProbeStep(name, True))

    record("open", lambda: ensure_plugin_state_store(project))

    store: PluginStateKeyedStore | None = None

    def open_store() -> None:
        nonlocal store
        store = create_plugin_state_keyed_store(project, "quantagent.probe", namespace="health", max_entries=2, default_ttl_ms=60_000)

    record("open-keyed-store", open_store)

    def write_read_consume() -> None:
        if store is None:
            raise PluginStateStoreError("probe store was not opened", code="PLUGIN_STATE_OPEN_FAILED", operation="probe", path=str(path))
        store.register(probe_key, {"probe": "probe-value"})
        if store.lookup(probe_key) != {"probe": "probe-value"}:
            raise PluginStateStoreError("probe lookup mismatch", code="PLUGIN_STATE_READ_FAILED", operation="probe", path=str(path))
        if store.consume(probe_key) != {"probe": "probe-value"}:
            raise PluginStateStoreError("probe consume mismatch", code="PLUGIN_STATE_READ_FAILED", operation="probe", path=str(path))

    record("write-read-consume", write_read_consume)
    record("sweep", lambda: sweep_expired_plugin_state_entries(project))
    if store is not None:
        record("clear", store.clear)

    return PluginStateStoreProbeResult(all(step.ok for step in steps), str(path), tuple(steps))


@contextmanager
def _open_ready(path: Path) -> Iterator[sqlite3.Connection]:
    conn = _connect_ready(path)
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        conn.close()


def _connect_ready(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        _ensure_schema(conn, path)
    except sqlite3.Error as exc:
        conn.close()
        raise _sqlite_error("Failed to initialize plugin state database.", "PLUGIN_STATE_OPEN_FAILED", "open", path, exc)
    except PluginStateStoreError:
        conn.close()
        raise
    return conn


def _ensure_schema(conn: sqlite3.Connection, path: Path) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            component TEXT PRIMARY KEY,
            version INTEGER NOT NULL
        )
        """
    )
    row = conn.execute("SELECT version FROM schema_version WHERE component = 'plugin_state_store'").fetchone()
    if row is not None and int(row["version"]) > SCHEMA_VERSION:
        raise PluginStateStoreError(
            f"unsupported plugin state schema version {row['version']}",
            code="PLUGIN_STATE_SCHEMA_UNSUPPORTED",
            operation="ensure-schema",
            path=str(path),
        )
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS plugin_state_entries (
            plugin_id TEXT NOT NULL,
            namespace TEXT NOT NULL,
            entry_key TEXT NOT NULL,
            value_json TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER,
            PRIMARY KEY (plugin_id, namespace, entry_key)
        );

        CREATE INDEX IF NOT EXISTS idx_plugin_state_expires_at
            ON plugin_state_entries(expires_at)
            WHERE expires_at IS NOT NULL;

        CREATE INDEX IF NOT EXISTS idx_plugin_state_namespace_created
            ON plugin_state_entries(plugin_id, namespace, created_at, entry_key);
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO schema_version (component, version) VALUES ('plugin_state_store', ?)",
        (SCHEMA_VERSION,),
    )


def _delete_expired_namespace(conn: sqlite3.Connection, plugin_id: str, namespace: str, now: int) -> int:
    cursor = conn.execute(
        """
        DELETE FROM plugin_state_entries
        WHERE plugin_id = ?
          AND namespace = ?
          AND expires_at IS NOT NULL
          AND expires_at <= ?
        """,
        (plugin_id, namespace, now),
    )
    return int(cursor.rowcount)


def _prune_namespace(
    conn: sqlite3.Connection,
    plugin_id: str,
    namespace: str,
    max_entries: int,
    now: int,
    *,
    keep_key: str,
) -> None:
    rows = conn.execute(
        """
        SELECT entry_key
        FROM plugin_state_entries
        WHERE plugin_id = ?
          AND namespace = ?
          AND (expires_at IS NULL OR expires_at > ?)
        ORDER BY
          CASE WHEN entry_key = ? THEN 1 ELSE 0 END ASC,
          created_at ASC,
          entry_key ASC
        """,
        (plugin_id, namespace, now, keep_key),
    ).fetchall()
    overflow = len(rows) - max_entries
    if overflow <= 0:
        return
    for row in rows[:overflow]:
        conn.execute(
            """
            DELETE FROM plugin_state_entries
            WHERE plugin_id = ? AND namespace = ? AND entry_key = ?
            """,
            (plugin_id, namespace, str(row["entry_key"])),
        )


def _entry_from_row(row: sqlite3.Row, operation: str, path: Path) -> PluginStateEntry:
    return PluginStateEntry(
        plugin_id=str(row["plugin_id"]),
        namespace=str(row["namespace"]),
        key=str(row["entry_key"]),
        value=_json_loads(str(row["value_json"]), operation, path),
        created_at=int(row["created_at"]),
        expires_at=_int_or_none(row["expires_at"]),
    )


def _validate_id(value: str, label: str, operation: str) -> str:
    text = str(value).strip()
    if not _SAFE_ID.fullmatch(text):
        raise PluginStateStoreError(
            f"plugin state {label} must start with a letter or number and contain only letters, numbers, '.', '_' or '-'",
            code="PLUGIN_STATE_INVALID_INPUT",
            operation=operation,
        )
    if len(text.encode("utf-8")) > MAX_ID_BYTES:
        raise PluginStateStoreError(
            f"plugin state {label} must be <= {MAX_ID_BYTES} bytes",
            code="PLUGIN_STATE_INVALID_INPUT",
            operation=operation,
        )
    return text


def _validate_key(value: str, operation: str) -> str:
    text = str(value).strip()
    if not text:
        raise PluginStateStoreError("plugin state key must not be empty", code="PLUGIN_STATE_INVALID_INPUT", operation=operation)
    if len(text.encode("utf-8")) > MAX_KEY_BYTES:
        raise PluginStateStoreError(
            f"plugin state key must be <= {MAX_KEY_BYTES} bytes",
            code="PLUGIN_STATE_INVALID_INPUT",
            operation=operation,
        )
    return text


def _validate_positive_int(value: int, label: str, operation: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PluginStateStoreError(
            f"plugin state {label} must be a positive integer",
            code="PLUGIN_STATE_INVALID_INPUT",
            operation=operation,
        )
    return value


def _validate_ttl(value: int, operation: str) -> int:
    return _validate_positive_int(value, "ttl_ms", operation)


def _json_dumps(value: Any, operation: str) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise PluginStateStoreError(
            "plugin state value must be JSON-serializable",
            code="PLUGIN_STATE_INVALID_INPUT",
            operation=operation,
            cause=exc,
        )


def _json_loads(value_json: str, operation: str, path: Path) -> Any:
    try:
        return json.loads(value_json)
    except json.JSONDecodeError as exc:
        raise PluginStateStoreError(
            "stored plugin state value is not valid JSON",
            code="PLUGIN_STATE_CORRUPT",
            operation=operation,
            path=str(path),
            cause=exc,
        )


def _sqlite_error(message: str, code: str, operation: str, path: Path, cause: sqlite3.Error) -> PluginStateStoreError:
    return PluginStateStoreError(message, code=code, operation=operation, path=str(path), cause=cause)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _int_or_none(value: Any) -> int | None:
    return None if value is None else int(value)
