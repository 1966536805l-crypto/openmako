from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class CompactMetrics:
    original_messages: int
    final_messages: int
    preserved_first: int
    preserved_last: int
    summarized_middle: int
    original_estimated_tokens: int
    compacted_estimated_tokens: int
    saved_estimated_tokens: int
    compression_ratio: float
    summary_trimmed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompactResult:
    messages: list[dict[str, Any]]
    metrics: CompactMetrics
    summary_entry: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "messages": self.messages,
            "metrics": self.metrics.to_dict(),
            "summary_entry": self.summary_entry,
        }


def estimate_tokens(value: Any) -> int:
    """Deterministic rough token estimate that avoids model/provider calls."""
    if value is None:
        return 0
    if not isinstance(value, str):
        try:
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            value = str(value)
    text = value.strip()
    if not text:
        return 0

    cjk_chars = sum(1 for char in text if _is_cjk(char))
    non_cjk = "".join(" " if _is_cjk(char) else char for char in text)
    ascii_chunks = re.findall(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]", non_cjk)
    ascii_estimate = sum(max(1, math.ceil(len(chunk) / 4)) for chunk in ascii_chunks)
    return max(1, cjk_chars + ascii_estimate)


def compact_trajectory(
    messages: list[Any],
    *,
    first_n: int = 2,
    last_n: int = 6,
    summary_role: str = "system",
    summary_kind: str = "trajectory_summary",
    target_summary_chars: int = 1800,
) -> CompactResult:
    """Protect the beginning/end of a trajectory and summarize the middle.

    The compressor is deliberately deterministic and standard-library only. It
    is intended for session/tool observation history, not for semantic memory.
    """
    normalized = [_message_to_dict(message) for message in messages]
    original_tokens = _estimate_messages_tokens(normalized)
    total = len(normalized)
    keep_first = max(0, min(first_n, total))
    keep_last = max(0, min(last_n, total - keep_first))
    middle_start = keep_first
    middle_end = total - keep_last
    middle = normalized[middle_start:middle_end]

    if not middle:
        metrics = _metrics(
            original_messages=total,
            final_messages=total,
            preserved_first=keep_first,
            preserved_last=keep_last,
            summarized_middle=0,
            original_tokens=original_tokens,
            compacted_tokens=original_tokens,
            summary_trimmed=False,
        )
        return CompactResult(messages=normalized, metrics=metrics)

    summary_text, trimmed = _summarize_middle(middle, target_summary_chars)
    middle_tokens = _estimate_messages_tokens(middle)
    summary_entry = {
        "role": summary_role,
        "content": summary_text,
        "meta": {
            "kind": summary_kind,
            "summarized_messages": len(middle),
            "original_estimated_tokens": middle_tokens,
            "summary_estimated_tokens": estimate_tokens(summary_text),
            "summary_trimmed": trimmed,
        },
    }
    compacted = normalized[:keep_first] + [summary_entry] + normalized[middle_end:]
    compacted_tokens = _estimate_messages_tokens(compacted)
    metrics = _metrics(
        original_messages=total,
        final_messages=len(compacted),
        preserved_first=keep_first,
        preserved_last=keep_last,
        summarized_middle=len(middle),
        original_tokens=original_tokens,
        compacted_tokens=compacted_tokens,
        summary_trimmed=trimmed,
    )
    return CompactResult(messages=compacted, metrics=metrics, summary_entry=summary_entry)


def compact_messages(messages: list[Any], **kwargs: Any) -> CompactResult:
    return compact_trajectory(messages, **kwargs)


def _metrics(
    *,
    original_messages: int,
    final_messages: int,
    preserved_first: int,
    preserved_last: int,
    summarized_middle: int,
    original_tokens: int,
    compacted_tokens: int,
    summary_trimmed: bool,
) -> CompactMetrics:
    saved = max(0, original_tokens - compacted_tokens)
    ratio = (compacted_tokens / original_tokens) if original_tokens else 1.0
    return CompactMetrics(
        original_messages=original_messages,
        final_messages=final_messages,
        preserved_first=preserved_first,
        preserved_last=preserved_last,
        summarized_middle=summarized_middle,
        original_estimated_tokens=original_tokens,
        compacted_estimated_tokens=compacted_tokens,
        saved_estimated_tokens=saved,
        compression_ratio=round(ratio, 4),
        summary_trimmed=summary_trimmed,
    )


def _message_to_dict(message: Any) -> dict[str, Any]:
    if isinstance(message, Mapping):
        return dict(message)
    if hasattr(message, "__dataclass_fields__"):
        return asdict(message)
    if hasattr(message, "__dict__"):
        return dict(vars(message))
    return {"role": "unknown", "content": str(message), "meta": {}}


def _estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(estimate_tokens(_stable_message_text(message)) for message in messages)


def _stable_message_text(message: dict[str, Any]) -> str:
    payload = {
        "role": message.get("role", ""),
        "content": message.get("content", ""),
        "meta": message.get("meta", {}),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _summarize_middle(messages: list[dict[str, Any]], target_chars: int) -> tuple[str, bool]:
    role_counts = _role_counts(messages)
    user_asks = _collect_user_asks(messages)
    tool_events = _collect_tool_events(messages)
    cautions = _collect_cautions(messages)

    lines = [
        f"Compacted {len(messages)} middle trajectory messages into a deterministic summary.",
        f"Role counts: {_format_counts(role_counts)}.",
    ]
    if user_asks:
        lines.append("Earlier user asks: " + " | ".join(user_asks) + ".")
    if tool_events:
        lines.append("Tool observations: " + " | ".join(tool_events) + ".")
    if cautions:
        lines.append("Failures/cautions: " + " | ".join(cautions) + ".")

    lines.append("Middle timeline:")
    for index, message in enumerate(messages, start=1):
        lines.append(f"- {index}. {_timeline_item(message)}")

    summary = "\n".join(lines)
    return _trim_text(summary, max(120, target_chars))


def _role_counts(messages: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for message in messages:
        role = str(message.get("role") or "unknown")
        counts[role] = counts.get(role, 0) + 1
    return counts


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{role}={counts[role]}" for role in sorted(counts)) or "none"


def _collect_user_asks(messages: list[dict[str, Any]], limit: int = 5) -> list[str]:
    asks = [
        _preview(str(message.get("content") or ""), 120)
        for message in messages
        if str(message.get("role") or "") == "user" and str(message.get("content") or "").strip()
    ]
    return asks[-limit:]


def _collect_tool_events(messages: list[dict[str, Any]], limit: int = 8) -> list[str]:
    events: list[str] = []
    for message in messages:
        meta = message.get("meta") if isinstance(message.get("meta"), Mapping) else {}
        tool = (
            meta.get("tool")
            or meta.get("name")
            or meta.get("stage")
            or message.get("tool")
            or message.get("name")
        )
        role = str(message.get("role") or "")
        if tool or role in {"tool", "observation"}:
            ok = meta.get("ok", message.get("ok", None))
            status = "ok" if ok is True else "failed" if ok is False else "seen"
            label = str(tool or role)
            summary = str(meta.get("summary") or message.get("summary") or message.get("content") or "")
            events.append(f"{label}:{status}:{_preview(summary, 90)}")
    return events[-limit:]


def _collect_cautions(messages: list[dict[str, Any]], limit: int = 8) -> list[str]:
    cautions: list[str] = []
    for message in messages:
        meta = message.get("meta") if isinstance(message.get("meta"), Mapping) else {}
        text = " ".join(
            str(part)
            for part in (
                message.get("content", ""),
                message.get("summary", ""),
                meta.get("summary", ""),
                meta.get("error", ""),
            )
        )
        lowered = text.lower()
        ok = meta.get("ok", message.get("ok", None))
        if ok is False or any(word in lowered for word in ("failed", "error", "blocked", "deny", "risk")):
            cautions.append(_preview(text, 120))
    return cautions[-limit:]


def _timeline_item(message: dict[str, Any]) -> str:
    role = str(message.get("role") or "unknown")
    meta = message.get("meta") if isinstance(message.get("meta"), Mapping) else {}
    tool = meta.get("tool") or meta.get("name") or message.get("tool") or message.get("name")
    content = str(message.get("content") or message.get("summary") or "")
    suffix = f" tool={tool}" if tool else ""
    ok = meta.get("ok", message.get("ok", None))
    if ok is True:
        suffix += " ok=true"
    elif ok is False:
        suffix += " ok=false"
    return f"[{role}{suffix}] {_preview(content, 160)}"


def _preview(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _trim_text(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    suffix = "\n[summary trimmed]"
    return text[: max(0, limit - len(suffix))].rstrip() + suffix, True


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x20000 <= code <= 0x2A6DF
        or 0x2A700 <= code <= 0x2B73F
        or 0x2B740 <= code <= 0x2B81F
        or 0x2B820 <= code <= 0x2CEAF
        or 0xF900 <= code <= 0xFAFF
    )
