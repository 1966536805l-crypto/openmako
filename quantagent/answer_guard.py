from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .evidence_ledger import EvidenceRecord, find_evidence, load_evidence
from .goal_contract import BLOCK, WARN, evaluate_goal_guard
from .quant_priority import build_quant_priority_review
from .quant_run_gate import build_quant_run_verdict, latest_quant_evidence_bundle, requires_quant_run_gate


ALLOW = "allow"
DATA_RE = re.compile(
    r"(?<![a-z0-9_])(?:\d+(?:\.\d+)?\s*(?:%|ms|s|sec|seconds|lines?|tests?|分|次|个|条|行|美元|元|万|千|亿)?|pf\s*=\s*\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
UNCERTAIN_FACT_RE = re.compile(r"(guess|probably|maybe|not sure|unverified|without checking|no source|猜|估计|大概|可能|不确定|未验证|没有来源|不查|编)", re.IGNORECASE)
EVIDENCE_MARKERS = (
    "source:",
    "evidence:",
    "command output",
    "from command",
    "from log",
    "from file",
    "official",
    "verified by",
    "path:",
    "result:",
    "trajectory:",
    "query_events:",
    "来源:",
    "证据:",
    "命令输出",
    "日志",
    "文件",
    "路径:",
)
UNCERTAINTY_OK_MARKERS = (
    "unknown",
    "unverified",
    "not verified",
    "not enough evidence",
    "needs verification",
    "cannot confirm",
    "未知",
    "未验证",
    "缺证据",
    "无法确认",
    "需要验证",
)


@dataclass(frozen=True)
class AnswerGuardFinding:
    action: str
    claim: str
    reason: str
    value: str = ""
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_ids"] = list(self.evidence_ids)
        return payload


@dataclass(frozen=True)
class AnswerGuardVerdict:
    action: str
    ok: bool
    answer: str
    findings: tuple[AnswerGuardFinding, ...] = ()
    evidence_used: tuple[EvidenceRecord, ...] = ()
    better_option: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "ok": self.ok,
            "answer": self.answer,
            "findings": [item.to_dict() for item in self.findings],
            "evidence_used": [item.to_dict() for item in self.evidence_used],
            "better_option": self.better_option,
        }


def guard_answer(
    project: str | Path | None,
    answer: str,
    *,
    goal: str = "",
    task: str = "",
    evidence: Iterable[EvidenceRecord] = (),
    strict: bool = True,
) -> AnswerGuardVerdict:
    text = answer.strip()
    if not text:
        return AnswerGuardVerdict(ALLOW, True, text)
    records = list(evidence)
    if project is not None:
        records = [*records, *load_evidence(project)]
    findings: list[AnswerGuardFinding] = []
    evidence_used: list[EvidenceRecord] = []
    is_runtime_summary = _is_agent_runtime_summary(text)

    if not is_runtime_summary:
        goal_decision = evaluate_goal_guard(project, text, goal=goal, task=task or goal)
        if not goal_decision.allowed:
            findings.append(AnswerGuardFinding(BLOCK, text[:500], goal_decision.reason, evidence_ids=()))

    quant_review = None
    if not is_runtime_summary:
        quant_review = build_quant_priority_review(project or ".", task or goal or text, answer=text, evidence=records, audit=False)
        if quant_review.action == BLOCK:
            reason = "quant priority gate blocked unsupported publish/live conclusion"
            if quant_review.missing_evidence:
                reason += ": missing " + ", ".join(item.key for item in quant_review.missing_evidence)
            findings.append(AnswerGuardFinding(BLOCK, text[:500], reason, evidence_ids=quant_review.matched_evidence_ids))
        elif quant_review.action == WARN:
            reason = "quant priority gate requires evidence before treating conclusion as fact"
            if quant_review.missing_evidence:
                reason += ": missing " + ", ".join(item.key for item in quant_review.missing_evidence)
            findings.append(AnswerGuardFinding(WARN, text[:500], reason, evidence_ids=quant_review.matched_evidence_ids))

    if quant_review is not None and quant_review.is_quant and requires_quant_run_gate(" ".join(part for part in (task, goal, text) if part)):
        bundle = latest_quant_evidence_bundle(project or ".")
        if bundle is None:
            findings.append(
                AnswerGuardFinding(
                    BLOCK,
                    text[:500],
                    "QuantRunGate evidence is required before metric/execution/live quant conclusions; run `mako quant run` first",
                )
            )
        else:
            gate_verdict = build_quant_run_verdict(bundle, task=task or goal, answer=text)
            if not gate_verdict.ok:
                findings.append(
                    AnswerGuardFinding(
                        BLOCK,
                        text[:500],
                        "QuantRunGate blocked this quant conclusion: " + "; ".join(gate_verdict.reasons),
                        evidence_ids=bundle.evidence_ids,
                    )
                )

    if not _is_agent_runtime_summary(text):
        for claim in extract_data_claims(text):
            value = _first_value(claim)
            if _is_uncertainty_statement(claim):
                findings.append(AnswerGuardFinding(ALLOW, claim, "uncertain data is explicitly marked unknown/unverified", value=value))
                continue
            matched = find_evidence(project or ".", claim, value=value, records=records)
            if matched:
                evidence_used.extend(matched)
                findings.append(AnswerGuardFinding(ALLOW, claim, "claim has matching verified evidence", value=value, evidence_ids=tuple(item.evidence_id for item in matched)))
                continue
            if _has_inline_evidence_marker(claim):
                findings.append(AnswerGuardFinding(WARN, claim, "claim has an inline evidence marker but no ledger record", value=value))
                continue
            action = BLOCK if strict else WARN
            findings.append(
                AnswerGuardFinding(
                    action,
                    claim,
                    "data-like claim lacks verified evidence; answer must say unknown/unverified or cite evidence",
                    value=value,
                )
            )

    blocks = [item for item in findings if item.action == BLOCK]
    warns = [item for item in findings if item.action == WARN]
    if blocks:
        return AnswerGuardVerdict(BLOCK, False, _blocked_answer(text, blocks), tuple(findings), tuple(_dedupe_evidence(evidence_used)))
    if warns:
        return AnswerGuardVerdict(WARN, True, text, tuple(findings), tuple(_dedupe_evidence(evidence_used)))
    return AnswerGuardVerdict(ALLOW, True, text, tuple(findings), tuple(_dedupe_evidence(evidence_used)))


def extract_data_claims(answer: str) -> list[str]:
    if _is_agent_runtime_summary(answer):
        return []
    claims: list[str] = []
    in_code = False
    for raw_line in answer.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not line:
            continue
        lowered = line.lower()
        has_data = DATA_RE.search(line) is not None or any(token in lowered for token in ("score", "tests", "passed", "failed", "price", "date", "version", "lines", "pf", "分", "测试", "通过", "价格", "日期", "版本", "行"))
        if has_data:
            claims.append(line[:600])
        elif UNCERTAIN_FACT_RE.search(line) and any(token in lowered for token in ("data", "number", "score", "result", "数据", "数字", "分数", "结果")):
            claims.append(line[:600])
    return claims


def _is_agent_runtime_summary(text: str) -> bool:
    lowered = text.lower()
    return (
        "trajectory was recorded by quantagent.agent_loop" in lowered
        or "agent loop mode route:" in lowered
        or "agent v2 completed via deprecated compatibility wrapper" in lowered
    )


def render_answer_guard_verdict(verdict: AnswerGuardVerdict) -> str:
    lines = [
        "# Answer Guard Verdict",
        "",
        f"- action: {verdict.action}",
        f"- ok: {str(verdict.ok).lower()}",
        f"- findings: {len(verdict.findings)}",
        f"- evidence_used: {len(verdict.evidence_used)}",
        "",
        "## Findings",
        "",
    ]
    if not verdict.findings:
        lines.append("- none")
    for finding in verdict.findings:
        evidence = f" evidence={','.join(finding.evidence_ids)}" if finding.evidence_ids else ""
        value = f" value={finding.value}" if finding.value else ""
        lines.append(f"- [{finding.action}]{value}{evidence}: {finding.reason}")
        lines.append(f"  claim: {finding.claim}")
    lines.extend(["", "## Answer", "", verdict.answer])
    return "\n".join(lines).rstrip() + "\n"


def _first_value(claim: str) -> str:
    match = DATA_RE.search(claim)
    return match.group(0).strip() if match else ""


def _has_inline_evidence_marker(claim: str) -> bool:
    lowered = claim.lower()
    return any(marker in lowered for marker in EVIDENCE_MARKERS)


def _is_uncertainty_statement(claim: str) -> bool:
    lowered = claim.lower()
    return any(marker in lowered for marker in UNCERTAINTY_OK_MARKERS)


def _blocked_answer(answer: str, blocks: list[AnswerGuardFinding]) -> str:
    lines = [
        "Answer blocked by data certainty guard.",
        "The draft contains data-like claims without verified evidence.",
        "",
        "Blocked claims:",
    ]
    lines.extend(f"- {item.claim}" for item in blocks[:8])
    lines.extend(["", "Safe answer:", "I cannot state those data points as fact until verified evidence is available."])
    return "\n".join(lines)


def _dedupe_evidence(records: Iterable[EvidenceRecord]) -> list[EvidenceRecord]:
    seen: set[str] = set()
    deduped: list[EvidenceRecord] = []
    for record in records:
        if record.evidence_id in seen:
            continue
        seen.add(record.evidence_id)
        deduped.append(record)
    return deduped
