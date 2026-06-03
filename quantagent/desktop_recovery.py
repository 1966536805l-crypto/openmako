from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Iterable, Mapping


RECOVERY_CHAIN = (
    "ax",
    "ocr",
    "som",
    "grid",
    "browser_reopen",
    "wait",
    "pause",
)

FAILURE_STATUSES = frozenset(
    {
        "failed",
        "error",
        "blocked",
        "stopped",
        "observe_failed",
        "tokenize_failed",
        "action_failed",
        "verify_failed",
        "step_budget_exhausted",
        "time_budget_exhausted",
    }
)

PAUSE_STATUSES = frozenset({"blocked", "stopped", "paused", "pause", "permission_denied"})

RECOVERY_ACTIONS: dict[str, str] = {
    "ax": "retry_ax_snapshot",
    "ocr": "retry_ocr_snapshot",
    "som": "retry_som_capture",
    "grid": "retry_grid_capture",
    "browser_reopen": "reopen_browser",
    "wait": "wait",
    "pause": "pause",
}

STRATEGY_REASONS: dict[str, str] = {
    "ax": "start recovery with accessibility snapshot",
    "ocr": "accessibility path already failed or produced no usable signal",
    "som": "OCR path already failed or produced no usable signal",
    "grid": "SoM path already failed or produced no usable signal",
    "browser_reopen": "visual targeting paths are exhausted; refresh browser context",
    "wait": "browser reopen was already attempted; allow UI state to settle once",
    "pause": "all automatic recovery paths are exhausted",
}

HIGH_RISK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "credential",
        re.compile(
            r"(密码|验证码|二次验证|密钥|私钥|助记词|凭证|\b(password|passcode|credential|otp|2fa|mfa|secret|api[_-]?key|private key|seed phrase)\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "payment",
        re.compile(r"(支付|付款|转账|提现|充值|银行卡|\b(pay|payment|purchase|checkout|transfer|withdraw|deposit)\b)", re.IGNORECASE),
    ),
    (
        "trading",
        re.compile(r"(交易|下单|买入|卖出|实盘|券商|\b(trade|trading|buy|sell|order|broker|position)\b)", re.IGNORECASE),
    ),
    (
        "high_risk",
        re.compile(r"(高风险|high[- ]?risk|unsafe|dangerous|destructive|delete|destroy|wipe|erase|删除|清空|格式化|抹掉)", re.IGNORECASE),
    ),
)


@dataclass(frozen=True)
class RecoveryRisk:
    blocked: bool
    category: str = ""
    matched: str = ""
    reason: str = ""

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecoveryStrategy:
    action: str
    source: str
    status: str
    reason: str
    confidence: float
    args: dict[str, Any] = field(default_factory=dict)
    risk: RecoveryRisk = field(default_factory=lambda: RecoveryRisk(False))
    attempted: tuple[str, ...] = ()

    @property
    def paused(self) -> bool:
        return self.action == "pause"

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["attempted"] = list(self.attempted)
        return payload


DesktopRecoveryRisk = RecoveryRisk
DesktopRecoveryStrategy = RecoveryStrategy


def plan_recovery_strategy(
    status: str | Mapping[str, Any] = "",
    records: Iterable[Any] | None = None,
    *,
    goal: str = "",
    browser: str = "Safari",
    wait_seconds: float = 2.0,
) -> RecoveryStrategy:
    """Plan the next desktop daemon recovery step without touching the desktop."""

    daemon_status, daemon_goal, daemon_records = _coerce_inputs(status, records)
    effective_goal = " ".join(str(goal or daemon_goal or "").split())
    normalized_records = tuple(_record_to_mapping(record) for record in daemon_records)
    risk = classify_recovery_risk(effective_goal, normalized_records)
    attempted = _attempted_sources(normalized_records)
    latest = _latest_failure(normalized_records)

    if risk.blocked:
        return RecoveryStrategy(
            action="pause",
            source="pause",
            status="paused",
            reason=risk.reason,
            confidence=1.0,
            args={"requires_operator": True},
            risk=risk,
            attempted=attempted,
        )

    normalized_status = _norm(daemon_status)
    if normalized_status in PAUSE_STATUSES:
        return RecoveryStrategy(
            action="pause",
            source="pause",
            status="paused",
            reason=f"daemon status requires operator pause: {normalized_status}",
            confidence=0.98,
            args={"requires_operator": True},
            risk=risk,
            attempted=attempted,
        )

    if normalized_status and normalized_status not in FAILURE_STATUSES:
        return RecoveryStrategy(
            action="wait",
            source="wait",
            status="planned",
            reason=f"daemon status is not a hard failure: {normalized_status}",
            confidence=0.55,
            args={"seconds": _safe_wait(wait_seconds)},
            risk=risk,
            attempted=attempted,
        )

    next_source = _next_source(attempted, latest)
    return RecoveryStrategy(
        action=RECOVERY_ACTIONS[next_source],
        source=next_source,
        status="paused" if next_source == "pause" else "planned",
        reason=STRATEGY_REASONS[next_source],
        confidence=_confidence_for(next_source, attempted),
        args=_args_for(next_source, browser=browser, wait_seconds=wait_seconds),
        risk=risk,
        attempted=attempted,
    )


def plan_desktop_recovery(
    status: str | Mapping[str, Any] = "",
    records: Iterable[Any] | None = None,
    *,
    goal: str = "",
    browser: str = "Safari",
    wait_seconds: float = 2.0,
) -> RecoveryStrategy:
    return plan_recovery_strategy(status, records, goal=goal, browser=browser, wait_seconds=wait_seconds)


def classify_recovery_risk(goal: str = "", records: Iterable[Any] | None = None) -> RecoveryRisk:
    haystack_parts = [str(goal or "")]
    for record in records or ():
        normalized = _record_to_mapping(record)
        haystack_parts.append(str(normalized.get("phase") or ""))
        haystack_parts.append(str(normalized.get("status") or ""))
        haystack_parts.append(str(normalized.get("summary") or ""))
        data = normalized.get("data")
        if data:
            haystack_parts.append(_stable_json(data))
    haystack = " ".join(part for part in haystack_parts if part).strip()
    if not haystack:
        return RecoveryRisk(False)
    for category, pattern in HIGH_RISK_PATTERNS:
        match = pattern.search(haystack)
        if match:
            matched = match.group(0)
            return RecoveryRisk(True, category, matched, f"pause recovery for high-risk {category}: {matched}")
    return RecoveryRisk(False)


def _coerce_inputs(status: str | Mapping[str, Any], records: Iterable[Any] | None) -> tuple[str, str, Iterable[Any]]:
    if isinstance(status, Mapping):
        payload = status
        return (
            str(payload.get("status") or ""),
            str(payload.get("goal") or ""),
            records if records is not None else _iter_records(payload.get("records")),
        )
    return str(status or ""), "", _iter_records(records)


def _iter_records(records: Any) -> Iterable[Any]:
    if records is None:
        return ()
    if isinstance(records, (str, bytes, Mapping)):
        return ()
    return records


def _record_to_mapping(record: Any) -> dict[str, Any]:
    if isinstance(record, Mapping):
        return dict(record)
    if is_dataclass(record):
        return asdict(record)
    payload: dict[str, Any] = {}
    for key in ("step", "phase", "status", "summary", "data"):
        if hasattr(record, key):
            payload[key] = getattr(record, key)
    return payload


def _attempted_sources(records: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    found: list[str] = []
    for record in records:
        text = _record_text(record)
        for source in RECOVERY_CHAIN[:-1]:
            if _source_seen(source, text) and source not in found:
                found.append(source)
    return tuple(found)


def _latest_failure(records: Iterable[Mapping[str, Any]]) -> Mapping[str, Any]:
    latest: Mapping[str, Any] = {}
    for record in records:
        status = _norm(record.get("status"))
        summary = str(record.get("summary") or "").lower()
        if status in FAILURE_STATUSES or "failed" in summary or "error" in summary or "no usable" in summary:
            latest = record
    return latest


def _next_source(attempted: tuple[str, ...], latest: Mapping[str, Any]) -> str:
    if not attempted and _latest_implies_missing_visual_signal(latest):
        return "ax"
    for source in RECOVERY_CHAIN:
        if source not in attempted:
            return source
    return "pause"


def _latest_implies_missing_visual_signal(record: Mapping[str, Any]) -> bool:
    if not record:
        return True
    phase = _norm(record.get("phase"))
    status = _norm(record.get("status"))
    summary = str(record.get("summary") or "").lower()
    return (
        phase in {"observe", "tokenize", "decide", "verify"}
        or status in {"observe_failed", "tokenize_failed", "verify_failed", "no_match"}
        or any(term in summary for term in ("no match", "not found", "stale", "no visible progress", "permission", "empty"))
    )


def _source_seen(source: str, text: str) -> bool:
    if source == "browser_reopen":
        return bool(re.search(r"\b(browser[_ -]?reopen|reopen[_ -]?browser|reopen|open browser|activate browser)\b", text))
    patterns = {
        "ax": r"\b(ax|accessibility|retry_ax_snapshot|ax_snapshot)\b",
        "ocr": r"\b(ocr|retry_ocr_snapshot)\b",
        "som": r"\b(som|set[- ]?of[- ]?marks|retry_som_capture)\b",
        "grid": r"\b(grid|retry_grid_capture)\b",
        "wait": r"\b(wait|sleep|settle)\b",
    }
    return bool(re.search(patterns[source], text))


def _record_text(record: Mapping[str, Any]) -> str:
    parts = [
        str(record.get("phase") or ""),
        str(record.get("status") or ""),
        str(record.get("summary") or ""),
        _stable_json(record.get("data") or {}),
    ]
    return " ".join(parts).lower()


def _args_for(source: str, *, browser: str, wait_seconds: float) -> dict[str, Any]:
    if source == "browser_reopen":
        return {"browser": str(browser or "Safari")}
    if source == "wait":
        return {"seconds": _safe_wait(wait_seconds)}
    if source == "pause":
        return {"requires_operator": True}
    return {"capture": source}


def _confidence_for(source: str, attempted: tuple[str, ...]) -> float:
    base = {
        "ax": 0.82,
        "ocr": 0.76,
        "som": 0.70,
        "grid": 0.64,
        "browser_reopen": 0.58,
        "wait": 0.50,
        "pause": 0.99,
    }[source]
    return max(0.35, round(base - (0.03 * len(attempted)), 2))


def _safe_wait(value: float) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = 2.0
    return max(0.0, min(seconds, 30.0))


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)
