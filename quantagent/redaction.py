from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class FoldedLogGroup:
    fingerprint: str
    severity: str
    count: int
    first_seen: int
    last_seen: int
    examples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def redact_for_llm(value: Any, *, max_items: int = 20, max_string_chars: int = 2000) -> Any:
    if isinstance(value, dict):
        return {str(key): redact_for_llm(item, max_items=max_items, max_string_chars=max_string_chars) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return _redact_sequence(list(value), max_items=max_items, max_string_chars=max_string_chars)
    if isinstance(value, str):
        return _redact_string(value, max_string_chars=max_string_chars)
    return value


def fold_log_lines(text: str, *, examples_per_group: int = 2) -> list[FoldedLogGroup]:
    groups: dict[str, FoldedLogGroup] = {}
    for index, line in enumerate(text.splitlines(), start=1):
        compact = " ".join(line.split())
        if not compact:
            continue
        severity = _severity(compact)
        fingerprint = _fingerprint(compact)
        old = groups.get(fingerprint)
        examples = [] if old is None else list(old.examples)
        if len(examples) < examples_per_group:
            examples.append(compact[:500])
        groups[fingerprint] = FoldedLogGroup(
            fingerprint=fingerprint,
            severity=severity if old is None else _max_severity(old.severity, severity),
            count=1 if old is None else old.count + 1,
            first_seen=index if old is None else old.first_seen,
            last_seen=index,
            examples=examples,
        )
    return sorted(groups.values(), key=lambda item: (_severity_order(item.severity), -item.count, item.first_seen))


def render_redacted(value: Any) -> str:
    redacted = redact_for_llm(value)
    if isinstance(redacted, str):
        return redacted
    import json

    return json.dumps(redacted, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _redact_sequence(items: list[Any], *, max_items: int, max_string_chars: int) -> Any:
    if len(items) <= max_items:
        return [redact_for_llm(item, max_items=max_items, max_string_chars=max_string_chars) for item in items]
    numbers = [float(item) for item in items if isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(float(item))]
    if len(numbers) >= max(3, len(items) * 0.8):
        ordered = sorted(numbers)
        return {
            "redacted": "large_numeric_array",
            "count": len(items),
            "min": ordered[0],
            "max": ordered[-1],
            "mean": round(sum(numbers) / len(numbers), 6),
            "p05": _quantile(ordered, 0.05),
            "p50": _quantile(ordered, 0.50),
            "p95": _quantile(ordered, 0.95),
        }
    return {
        "redacted": "large_array",
        "count": len(items),
        "sample": [redact_for_llm(item, max_items=max_items, max_string_chars=max_string_chars) for item in items[:max_items]],
    }


def _redact_string(text: str, *, max_string_chars: int) -> str | dict[str, Any]:
    if len(text) <= max_string_chars:
        return text
    if "\n" in text:
        groups = fold_log_lines(text)
        return {
            "redacted": "large_log",
            "chars": len(text),
            "lines": len(text.splitlines()),
            "groups": [group.to_dict() for group in groups[:20]],
        }
    return text[: max(0, max_string_chars - 24)].rstrip() + "\n[string redacted]\n"


def _quantile(ordered: list[float], q: float) -> float:
    if not ordered:
        return 0.0
    index = (len(ordered) - 1) * q
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    if lower == upper:
        return round(ordered[lower], 6)
    fraction = index - lower
    return round(ordered[lower] * (1 - fraction) + ordered[upper] * fraction, 6)


def _severity(line: str) -> str:
    upper = line.upper()
    if "ERROR" in upper or "EXCEPTION" in upper or "FAILED" in upper:
        return "error"
    if "WARN" in upper or "WARNING" in upper:
        return "warn"
    return "info"


def _fingerprint(line: str) -> str:
    lowered = line.lower()
    lowered = re.sub(r"0x[0-9a-f]+", "0xHEX", lowered)
    lowered = re.sub(r"\b\d+(?:\.\d+)?\b", "N", lowered)
    lowered = re.sub(r"/[A-Za-z0-9_./-]+", "/PATH", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered[:240]


def _max_severity(left: str, right: str) -> str:
    return left if _severity_order(left) <= _severity_order(right) else right


def _severity_order(value: str) -> int:
    return {"error": 0, "warn": 1, "info": 2}.get(value, 3)
