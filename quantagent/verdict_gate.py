from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


PASS = "PASS"
FAIL = "FAIL"
INCONCLUSIVE = "INCONCLUSIVE"
VERDICTS = {PASS, FAIL, INCONCLUSIVE}


@dataclass(frozen=True)
class VerdictDecision:
    verdict: str
    reason: str
    source: str = ""
    evidence: list[str] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.verdict == PASS

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"allowed": self.allowed}


def normalize_verdict(value: str) -> str:
    text = str(value or "").strip().upper()
    aliases = {
        "OK": PASS,
        "APPROVE": PASS,
        "APPROVED": PASS,
        "PASSED": PASS,
        "REJECT": FAIL,
        "REJECTED": FAIL,
        "FAILED": FAIL,
        "NEEDS_WORK": INCONCLUSIVE,
        "UNKNOWN": INCONCLUSIVE,
        "WARN": INCONCLUSIVE,
    }
    text = aliases.get(text, text)
    return text if text in VERDICTS else INCONCLUSIVE


def gate_verdicts(decisions: Iterable[VerdictDecision | dict[str, Any] | str]) -> VerdictDecision:
    rows = [_coerce_decision(item) for item in decisions]
    if not rows:
        return VerdictDecision(INCONCLUSIVE, "no verdict evidence provided")
    failing = [item for item in rows if item.verdict == FAIL]
    if failing:
        return VerdictDecision(FAIL, "one or more checks failed: " + "; ".join(item.reason for item in failing[:3]), evidence=_evidence(rows))
    inconclusive = [item for item in rows if item.verdict == INCONCLUSIVE]
    if inconclusive:
        return VerdictDecision(INCONCLUSIVE, "one or more checks are inconclusive: " + "; ".join(item.reason for item in inconclusive[:3]), evidence=_evidence(rows))
    return VerdictDecision(PASS, f"{len(rows)} check(s) passed", evidence=_evidence(rows))


def verdict_from_findings(findings: Iterable[Any], *, source: str = "findings") -> VerdictDecision:
    rows = list(findings)
    if not rows:
        return VerdictDecision(PASS, "no findings", source=source)
    levels = [str(getattr(item, "level", getattr(item, "severity", "")) or "").lower() for item in rows]
    if any(level == "error" for level in levels):
        return VerdictDecision(FAIL, "error finding present", source=source, evidence=[_finding_text(item) for item in rows[:8]])
    if any(level in {"warn", "warning"} for level in levels):
        return VerdictDecision(INCONCLUSIVE, "warning finding present", source=source, evidence=[_finding_text(item) for item in rows[:8]])
    return VerdictDecision(PASS, "informational findings only", source=source, evidence=[_finding_text(item) for item in rows[:8]])


def render_verdict(decision: VerdictDecision) -> str:
    lines = [
        "# Verdict Gate",
        "",
        f"- verdict: {decision.verdict}",
        f"- allowed: {str(decision.allowed).lower()}",
        f"- reason: {decision.reason}",
    ]
    if decision.source:
        lines.append(f"- source: {decision.source}")
    if decision.evidence:
        lines.extend(["", "## Evidence", ""])
        lines.extend(f"- {item}" for item in decision.evidence)
    return "\n".join(lines) + "\n"


def _coerce_decision(value: VerdictDecision | dict[str, Any] | str) -> VerdictDecision:
    if isinstance(value, VerdictDecision):
        return value
    if isinstance(value, dict):
        return VerdictDecision(
            normalize_verdict(str(value.get("verdict") or value.get("status") or "")),
            str(value.get("reason") or value.get("summary") or ""),
            source=str(value.get("source") or ""),
            evidence=[str(item) for item in value.get("evidence", [])] if isinstance(value.get("evidence"), list) else [],
        )
    return VerdictDecision(normalize_verdict(value), str(value))


def _evidence(rows: list[VerdictDecision]) -> list[str]:
    evidence: list[str] = []
    for row in rows:
        evidence.extend(row.evidence)
    return evidence[:20]


def _finding_text(item: Any) -> str:
    title = str(getattr(item, "title", getattr(item, "code", "finding")) or "finding")
    detail = str(getattr(item, "detail", getattr(item, "message", "")) or "")
    path = getattr(item, "path", "")
    return f"{path} {title}: {detail}".strip()
