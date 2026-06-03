from __future__ import annotations

import json
import logging
import time
from contextlib import suppress
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger("quantagent.exception_audit")
LOGGER.addHandler(logging.NullHandler())
LOGGER.propagate = False


def audit_suppressed_exception(
    location: str,
    exc: BaseException,
    *,
    project: str | Path | None = None,
    action: str = "suppressed",
    data: dict[str, Any] | None = None,
    **context: Any,
) -> None:
    """Record a swallowed exception without changing caller control flow."""
    merged_context = dict(context)
    if data:
        merged_context.update(data)
    record = {
        "timestamp_ms": int(time.time() * 1000),
        "location": str(location),
        "action": str(action),
        "exception_type": type(exc).__name__,
        "message": str(exc),
        "context": merged_context,
    }
    with suppress(Exception):
        LOGGER.warning(
            "suppressed exception at %s: %s: %s context=%s",
            location,
            type(exc).__name__,
            exc,
            merged_context,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
    with suppress(Exception):
        root = Path(project).expanduser().resolve(strict=False) if project is not None else Path.cwd()
        path = root / ".quantagent" / "exception_audit.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
