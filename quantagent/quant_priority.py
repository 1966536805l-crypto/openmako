from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .evidence_ledger import EvidenceRecord, load_evidence
from .quant_checks import AuditFinding, audit_project


ALLOW = "allow"
WARN = "warn"
BLOCK = "block"

QUANT_TERMS = {
    "pf",
    "profit factor",
    "sharpe",
    "drawdown",
    "slippage",
    "capacity",
    "backtest",
    "pnl",
    "alpha",
    "fill",
    "broker",
    "tick",
    "execution",
    "position",
    "strategy",
    "回测",
    "收益",
    "回撤",
    "滑点",
    "容量",
    "成交",
    "逐笔",
    "券商",
    "仓位",
    "策略",
    "胜率",
    "实盘",
    "下单",
}
METRIC_TERMS = {
    "pf",
    "profit factor",
    "sharpe",
    "win rate",
    "drawdown",
    "pnl",
    "return",
    "收益",
    "回撤",
    "胜率",
    "盈亏",
}
EXECUTION_TERMS = {
    "09:30",
    "execution",
    "fill",
    "broker",
    "slippage",
    "capacity",
    "tick",
    "live",
    "go live",
    "trade live",
    "safe to trade",
    "成交",
    "撮合",
    "券商",
    "滑点",
    "容量",
    "逐笔",
    "实盘",
    "下单",
}
PUBLISH_TERMS = {
    "publish",
    "report",
    "state",
    "conclude",
    "confirmed",
    "proven",
    "go live",
    "deploy",
    "trade live",
    "safe to trade",
    "发布",
    "报告",
    "结论",
    "确认",
    "证明",
    "实盘",
    "下单",
    "可以上",
    "能交易",
}
EVIDENCE_TERMS = {
    "evidence",
    "source",
    "artifact",
    "hash",
    "dedup",
    "baseline",
    "row",
    "validation",
    "test",
    "registry",
    "broker",
    "fill",
    "slippage",
    "capacity",
    "证据",
    "来源",
    "产物",
    "哈希",
    "去重",
    "基线",
    "行数",
    "验证",
    "测试",
    "登记",
    "券商",
    "成交",
    "滑点",
    "容量",
}


@dataclass(frozen=True)
class QuantEvidenceRequirement:
    key: str
    description: str
    reason: str
    keywords: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuantPriorityReview:
    action: str
    is_quant: bool
    task: str
    intent: str
    required_evidence: tuple[QuantEvidenceRequirement, ...] = ()
    missing_evidence: tuple[QuantEvidenceRequirement, ...] = ()
    safe_next_actions: tuple[str, ...] = ()
    blocked_conclusions: tuple[str, ...] = ()
    audit_findings: tuple[AuditFinding, ...] = ()
    evidence_count: int = 0
    matched_evidence_ids: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.action != BLOCK

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "ok": self.ok,
            "is_quant": self.is_quant,
            "task": self.task,
            "intent": self.intent,
            "required_evidence": [item.to_dict() for item in self.required_evidence],
            "missing_evidence": [item.to_dict() for item in self.missing_evidence],
            "safe_next_actions": list(self.safe_next_actions),
            "blocked_conclusions": list(self.blocked_conclusions),
            "audit_findings": [asdict(item) for item in self.audit_findings],
            "evidence_count": self.evidence_count,
            "matched_evidence_ids": list(self.matched_evidence_ids),
            "notes": list(self.notes),
        }


def is_quant_task(text: str) -> bool:
    lowered = _norm(text)
    return any(_contains_quant_term(lowered, term) for term in QUANT_TERMS)


def _contains_quant_term(lowered_text: str, term: str) -> bool:
    if " " in term or any(ord(char) > 127 for char in term):
        return term in lowered_text
    return re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", lowered_text) is not None


def build_quant_priority_review(
    project: str | Path,
    task: str,
    *,
    answer: str = "",
    evidence: Iterable[EvidenceRecord] = (),
    audit: bool = True,
) -> QuantPriorityReview:
    project_path = Path(project).expanduser().resolve(strict=False)
    combined = " ".join(part for part in (task, answer) if part).strip()
    lowered = _norm(combined)
    quant = is_quant_task(combined)
    if not quant:
        return QuantPriorityReview(
            action=ALLOW,
            is_quant=False,
            task=task,
            intent="non_quant",
            notes=("no quant terms detected",),
        )

    intent = _intent(lowered)
    records = list(evidence) or load_evidence(project_path, limit=200)
    requirements = tuple(_requirements_for(lowered))
    matched_ids = tuple(_matching_evidence_ids(records, requirements))
    missing = tuple(req for req in requirements if not _requirement_satisfied(req, records))
    findings = tuple(audit_project(project_path)) if audit else ()
    audit_errors = tuple(item for item in findings if item.level == "error")
    blocked_conclusions = tuple(_blocked_conclusions(lowered, missing, audit_errors))
    safe_next_actions = tuple(_safe_next_actions(lowered, missing, audit_errors))

    if _wants_publish_or_live(lowered) and (missing or audit_errors):
        action = BLOCK
    elif missing or audit_errors:
        action = WARN
    else:
        action = ALLOW

    notes = [
        "quant-first mode active: no metric/execution conclusion is treated as fact without evidence",
        f"intent={intent}",
    ]
    if audit_errors:
        notes.append("local audit errors must be resolved before material conclusions")
    return QuantPriorityReview(
        action=action,
        is_quant=True,
        task=task,
        intent=intent,
        required_evidence=requirements,
        missing_evidence=missing,
        safe_next_actions=safe_next_actions,
        blocked_conclusions=blocked_conclusions,
        audit_findings=findings,
        evidence_count=len(records),
        matched_evidence_ids=matched_ids,
        notes=tuple(notes),
    )


def render_quant_priority_review(review: QuantPriorityReview) -> str:
    lines = [
        "# Quant Priority Review",
        "",
        f"- action: {review.action}",
        f"- ok: {str(review.ok).lower()}",
        f"- is_quant: {str(review.is_quant).lower()}",
        f"- intent: {review.intent}",
        f"- evidence_count: {review.evidence_count}",
        "",
        "## Required Evidence",
        "",
    ]
    if review.required_evidence:
        for item in review.required_evidence:
            missing = " missing" if item in review.missing_evidence else " ok-or-present"
            lines.append(f"- [{item.key}]{missing}: {item.description}")
            lines.append(f"  reason: {item.reason}")
    else:
        lines.append("- none")

    lines.extend(["", "## Blocked Conclusions", ""])
    lines.extend(f"- {item}" for item in review.blocked_conclusions) if review.blocked_conclusions else lines.append("- none")

    lines.extend(["", "## Safe Next Actions", ""])
    lines.extend(f"- {item}" for item in review.safe_next_actions) if review.safe_next_actions else lines.append("- none")

    lines.extend(["", "## Local Audit", ""])
    if review.audit_findings:
        for finding in review.audit_findings[:20]:
            path = f" ({finding.path})" if finding.path else ""
            lines.append(f"- [{finding.level}] {finding.title}{path}: {finding.detail}")
    else:
        lines.append("- no local audit findings")

    lines.extend(["", "## Notes", ""])
    lines.extend(f"- {item}" for item in review.notes) if review.notes else lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def _requirements_for(text: str) -> list[QuantEvidenceRequirement]:
    requirements = [
        QuantEvidenceRequirement(
            "dedup_baseline",
            "Deduplicated input/baseline must be identified.",
            "Duplicate or polluted samples can flip PF and ranking.",
            ("dedup", "去重", "baseline", "基线"),
        ),
        QuantEvidenceRequirement(
            "artifact_hashes",
            "Data/code artifact hashes and row counts must be present.",
            "A result without immutable artifacts is not reproducible.",
            ("hash", "sha256", "row", "rows", "哈希", "行数"),
        ),
    ]
    if any(term in text for term in METRIC_TERMS):
        requirements.append(
            QuantEvidenceRequirement(
                "metric_splits",
                "Metric claims need yearly/OOS split, not only aggregate PF.",
                "Aggregate metrics hide regime failure and 2025-style degradation.",
                ("year", "yearly", "oos", "2025", "split", "年度", "分年", "样本外"),
            )
        )
    if any(term in text for term in EXECUTION_TERMS):
        requirements.append(
            QuantEvidenceRequirement(
                "execution_evidence",
                "Execution claims need tick/fill/slippage/capacity or broker provenance.",
                "Backtest fills are not live execution evidence.",
                ("tick", "fill", "broker", "slippage", "capacity", "逐笔", "成交", "券商", "滑点", "容量"),
            )
        )
    return requirements


def _blocked_conclusions(
    text: str,
    missing: tuple[QuantEvidenceRequirement, ...],
    audit_errors: tuple[AuditFinding, ...],
) -> list[str]:
    if not missing and not audit_errors:
        return []
    blocked = [
        "Do not state PF/收益/胜率/回撤 improvement as confirmed.",
        "Do not approve live trading, order execution, or account/funds action.",
    ]
    if any(item.key == "execution_evidence" for item in missing):
        blocked.append("Do not claim 09:30/tick execution quality, slippage, or capacity.")
    if "1253" in text or audit_errors:
        blocked.append("Do not treat the polluted 1253-row baseline as clean evidence.")
    return blocked


def _safe_next_actions(
    text: str,
    missing: tuple[QuantEvidenceRequirement, ...],
    audit_errors: tuple[AuditFinding, ...],
) -> list[str]:
    actions = [
        "Run mako audit --deep and resolve errors before material conclusions.",
        "Record every accepted data/result fact with mako evidence add.",
    ]
    keys = {item.key for item in missing}
    if "dedup_baseline" in keys:
        actions.append("Locate or regenerate dedup baseline inputs before metric comparison.")
    if "artifact_hashes" in keys:
        actions.append("Capture data hash, code hash, params, row counts, and command output.")
    if "metric_splits" in keys:
        actions.append("Compute yearly/OOS split and compare aggregate PF against 2025 degradation.")
    if "execution_evidence" in keys:
        actions.append("Collect tick/fill/slippage/capacity or broker provenance before execution claims.")
    if audit_errors:
        actions.append("Treat audit errors as blockers for publishing or trading decisions.")
    return actions


def _matching_evidence_ids(records: list[EvidenceRecord], requirements: tuple[QuantEvidenceRequirement, ...]) -> list[str]:
    matched: list[str] = []
    for requirement in requirements:
        for record in records:
            if _record_matches(record, requirement):
                matched.append(record.evidence_id)
                break
    return matched


def _requirement_satisfied(requirement: QuantEvidenceRequirement, records: list[EvidenceRecord]) -> bool:
    return any(_record_matches(record, requirement) for record in records if record.verified)


def _record_matches(record: EvidenceRecord, requirement: QuantEvidenceRequirement) -> bool:
    text = _norm(" ".join([record.claim, record.value, record.source, record.path, record.command, record.tool]))
    return any(keyword in text for keyword in requirement.keywords)


def _intent(text: str) -> str:
    if _wants_publish_or_live(text):
        return "publish_or_live_decision"
    if any(term in text for term in EXECUTION_TERMS):
        return "execution_validation"
    if any(term in text for term in METRIC_TERMS):
        return "metric_claim"
    return "quant_research"


def _wants_publish_or_live(text: str) -> bool:
    if any(phrase in text for phrase in ("不要下结论", "不下结论", "先不下结论", "do not conclude", "without conclusion")):
        live_terms = ("live", "go live", "trade live", "safe to trade", "实盘", "下单", "可以上", "能交易")
        return any(term in text for term in live_terms)
    return any(term in text for term in PUBLISH_TERMS)


def _norm(text: str) -> str:
    return " ".join(str(text).lower().replace("_", " ").replace("-", " ").split())
