from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .safety import ALLOW as SAFETY_ALLOW, assess_quant_claim


GOAL_CONTRACT_PATH = ".quantagent/goal_contract.json"
ALLOW = "allow"
WARN = "warn"
BLOCK = "block"

QUALITY_TERMS = {
    "quality",
    "reliable",
    "correct",
    "tested",
    "validation",
    "test",
    "tests",
    "safe",
    "security",
    "audit",
    "review",
    "高质量",
    "质量",
    "可靠",
    "正确",
    "测试",
    "验证",
    "安全",
    "审查",
}
SKIP_TERMS = {
    "skip",
    "bypass",
    "ignore",
    "disable",
    "turn off",
    "remove guard",
    "no test",
    "without tests",
    "不要测试",
    "跳过",
    "绕过",
    "忽略",
    "关闭",
    "禁用",
    "别测",
    "不用测",
}
DESTRUCTIVE_TERMS = {
    "delete everything",
    "wipe",
    "rm -rf",
    "reset hard",
    "drop all",
    "清空",
    "全删",
    "删库",
    "硬重置",
}
OBEDIENCE_TERMS = {
    "obey",
    "follow",
    "listen",
    "听从",
    "听话",
    "照做",
    "必须",
}
QUANT_TERMS = {
    "quant",
    "backtest",
    "alpha",
    "pf",
    "profit factor",
    "sharpe",
    "drawdown",
    "slippage",
    "capacity",
    "fill",
    "execution",
    "09:30",
    "1253",
    "tick",
    "p4",
    "量化",
    "回测",
    "收益",
    "胜率",
    "滑点",
    "容量",
    "成交",
    "逐笔",
    "实盘",
    "交易",
}
QUANT_METRIC_TERMS = {
    "pf",
    "pf=",
    "profit factor",
    "return",
    "returns",
    "sharpe",
    "drawdown",
    "win rate",
    "alpha",
    "收益",
    "回撤",
    "胜率",
    "超额",
}
CLAIM_TERMS = {
    "claim",
    "conclude",
    "prove",
    "publish",
    "report",
    "approve",
    "declare",
    "say",
    "assert",
    "结论",
    "证明",
    "宣称",
    "发布",
    "报告",
    "通过",
    "确认",
    "断言",
}
EVIDENCE_TERMS = {
    "evidence",
    "hash",
    "dedup",
    "baseline",
    "artifact",
    "csv",
    "test",
    "validation",
    "diagnostic",
    "slippage",
    "capacity",
    "broker",
    "fill",
    "source",
    "证据",
    "哈希",
    "去重",
    "基线",
    "产物",
    "测试",
    "验证",
    "诊断",
    "滑点",
    "容量",
    "券商",
    "成交",
    "来源",
}
HALLUCINATION_RELAX_TERMS = {
    "guess",
    "estimate without data",
    "assume it passed",
    "make up",
    "hallucinate",
    "no evidence needed",
    "不用证据",
    "不要证据",
    "编一个",
    "猜",
    "假装通过",
    "直接说通过",
}
DATA_TERMS = {
    "data",
    "number",
    "metric",
    "score",
    "count",
    "price",
    "date",
    "time",
    "version",
    "benchmark",
    "performance",
    "result",
    "test result",
    "line count",
    "数据",
    "数字",
    "指标",
    "分数",
    "多少分",
    "数量",
    "价格",
    "日期",
    "时间",
    "版本",
    "性能",
    "结果",
    "测试结果",
    "行数",
}
DATA_EVIDENCE_TERMS = EVIDENCE_TERMS | {
    "log",
    "output",
    "command output",
    "official",
    "measured",
    "observed",
    "query",
    "database",
    "source file",
    "timestamp",
    "日志",
    "输出",
    "命令输出",
    "官方",
    "实测",
    "观测",
    "查询",
    "数据库",
    "源文件",
    "时间戳",
}
UNCERTAIN_DATA_TERMS = {
    "guess",
    "roughly guess",
    "estimate without data",
    "assume",
    "probably",
    "maybe",
    "not sure",
    "uncertain",
    "unverified",
    "no source",
    "without source",
    "without checking",
    "make up",
    "fabricate",
    "猜",
    "估计",
    "大概",
    "可能",
    "不确定",
    "没把握",
    "未验证",
    "没有来源",
    "不用查",
    "不查",
    "编",
    "编一个",
}
DATA_ASSERTION_TERMS = CLAIM_TERMS | {
    "answer",
    "tell",
    "state",
    "summarize",
    "score",
    "rate",
    "calculate",
    "count",
    "return",
    "给出",
    "回答",
    "告诉",
    "说明",
    "总结",
    "打分",
    "评分",
    "计算",
    "统计",
}
DATA_NUMERIC_RE = re.compile(
    r"(?<![a-z0-9_])(?:\d+(?:\.\d+)?\s*(?:%|ms|s|sec|seconds|lines?|tests?|分|次|个|条|行|美元|元|万|千|亿)?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GoalContract:
    goal: str = ""
    obedience: str = "follow_user_unless_goal_conflict"
    constraints: tuple[str, ...] = ()
    success_criteria: tuple[str, ...] = ()
    conflict_policy: str = "block_goal_conflict"
    data_strict: bool = True
    uncertainty_policy: str = "block_uncertain_data_claims"
    quant_strict: bool = True
    hallucination_policy: str = "block_unsupported_quant_claims"
    source: str = "runtime"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["constraints"] = list(self.constraints)
        payload["success_criteria"] = list(self.success_criteria)
        return payload


@dataclass(frozen=True)
class GoalGuardDecision:
    action: str
    instruction: str
    goal: str
    reason: str
    confidence: float
    conflicts: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    contract: GoalContract | None = None

    @property
    def allowed(self) -> bool:
        return self.action in {ALLOW, WARN}

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["conflicts"] = list(self.conflicts)
        payload["warnings"] = list(self.warnings)
        payload["contract"] = self.contract.to_dict() if self.contract is not None else None
        return payload


def goal_contract_path(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / GOAL_CONTRACT_PATH


def load_goal_contract(project: str | Path | None = None) -> GoalContract:
    if project is None:
        return GoalContract()
    path = goal_contract_path(project)
    if not path.exists():
        return GoalContract(source="default")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("goal contract must be a JSON object")
    return _contract_from_mapping(data, source=str(path))


def save_goal_contract(
    project: str | Path,
    *,
    goal: str,
    constraints: Iterable[str] = (),
    success_criteria: Iterable[str] = (),
    obedience: str = "follow_user_unless_goal_conflict",
    conflict_policy: str = "block_goal_conflict",
    data_strict: bool = True,
    uncertainty_policy: str = "block_uncertain_data_claims",
    quant_strict: bool = True,
    hallucination_policy: str = "block_unsupported_quant_claims",
) -> Path:
    contract = GoalContract(
        goal=goal.strip(),
        obedience=obedience.strip() or "follow_user_unless_goal_conflict",
        constraints=tuple(str(item).strip() for item in constraints if str(item).strip()),
        success_criteria=tuple(str(item).strip() for item in success_criteria if str(item).strip()),
        conflict_policy=conflict_policy.strip() or "block_goal_conflict",
        data_strict=data_strict,
        uncertainty_policy=uncertainty_policy.strip() or "block_uncertain_data_claims",
        quant_strict=quant_strict,
        hallucination_policy=hallucination_policy.strip() or "block_unsupported_quant_claims",
        source="project",
    )
    path = goal_contract_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(contract.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def evaluate_goal_guard(
    project: str | Path | None,
    instruction: str,
    *,
    goal: str = "",
    task: str = "",
    constraints: Iterable[str] = (),
    success_criteria: Iterable[str] = (),
) -> GoalGuardDecision:
    loaded = load_goal_contract(project) if project is not None else GoalContract()
    contract = GoalContract(
        goal=goal.strip() or loaded.goal or task.strip(),
        obedience=loaded.obedience,
        constraints=tuple(str(item).strip() for item in constraints if str(item).strip()) or loaded.constraints,
        success_criteria=tuple(str(item).strip() for item in success_criteria if str(item).strip()) or loaded.success_criteria,
        conflict_policy=loaded.conflict_policy,
        data_strict=loaded.data_strict,
        uncertainty_policy=loaded.uncertainty_policy,
        quant_strict=loaded.quant_strict,
        hallucination_policy=loaded.hallucination_policy,
        source="runtime" if goal or constraints or success_criteria else loaded.source,
    )
    instruction_text = instruction.strip()
    if not instruction_text:
        return GoalGuardDecision(ALLOW, instruction_text, contract.goal, "empty instruction; nothing to block", 0.5, contract=contract)
    data_evidence = _strict_data_conflicts(instruction_text, contract)
    data_warnings = _strict_data_warnings(instruction_text, contract)
    if data_evidence:
        return GoalGuardDecision(
            BLOCK,
            instruction_text,
            contract.goal,
            "data certainty guard blocked an uncertain or unsupported data claim",
            min(0.98, 0.80 + 0.05 * len(data_evidence)),
            conflicts=tuple(data_evidence),
            warnings=tuple(data_warnings),
            contract=contract,
        )
    quant_evidence = _strict_quant_conflicts(instruction_text, contract)
    quant_warnings = _strict_quant_warnings(instruction_text, contract)
    if quant_evidence:
        return GoalGuardDecision(
            BLOCK,
            instruction_text,
            contract.goal,
            "quant strict hallucination guard blocked an unsupported or goal-damaging instruction",
            min(0.98, 0.82 + 0.04 * len(quant_evidence)),
            conflicts=tuple(quant_evidence),
            warnings=tuple(quant_warnings),
            contract=contract,
        )
    if not contract.goal or _same_goal_and_instruction(contract.goal, instruction_text):
        return GoalGuardDecision(
            ALLOW,
            instruction_text,
            contract.goal,
            "no separate higher-order goal; user instruction is treated as the goal",
            0.7,
            warnings=tuple(data_warnings + quant_warnings),
            contract=contract,
        )

    evidence = _conflict_evidence(instruction_text, contract)
    warnings = _warning_evidence(instruction_text, contract) + data_warnings + quant_warnings
    if evidence:
        return GoalGuardDecision(
            BLOCK,
            instruction_text,
            contract.goal,
            "instruction conflicts with the stated goal contract",
            min(0.95, 0.72 + 0.06 * len(evidence)),
            conflicts=tuple(evidence),
            warnings=tuple(warnings),
            contract=contract,
        )
    if warnings:
        return GoalGuardDecision(
            WARN,
            instruction_text,
            contract.goal,
            "instruction may weaken the stated goal, but conflict is not strong enough to block",
            min(0.85, 0.55 + 0.05 * len(warnings)),
            warnings=tuple(warnings),
            contract=contract,
        )
    return GoalGuardDecision(
        ALLOW,
        instruction_text,
        contract.goal,
        "instruction is compatible with the stated goal; obey by default",
        0.82,
        contract=contract,
    )


def render_goal_contract(contract: GoalContract) -> str:
    lines = [
        "# Goal Contract",
        "",
        f"- goal: {contract.goal or '-'}",
        f"- obedience: {contract.obedience}",
        f"- conflict_policy: {contract.conflict_policy}",
        f"- data_strict: {str(contract.data_strict).lower()}",
        f"- uncertainty_policy: {contract.uncertainty_policy}",
        f"- quant_strict: {str(contract.quant_strict).lower()}",
        f"- hallucination_policy: {contract.hallucination_policy}",
        f"- source: {contract.source}",
        "",
        "## Constraints",
        "",
    ]
    lines.extend(f"- {item}" for item in contract.constraints) if contract.constraints else lines.append("- none")
    lines.extend(["", "## Success Criteria", ""])
    lines.extend(f"- {item}" for item in contract.success_criteria) if contract.success_criteria else lines.append("- none")
    return "\n".join(lines) + "\n"


def render_goal_guard_decision(decision: GoalGuardDecision) -> str:
    lines = [
        "# Goal Guard Decision",
        "",
        f"- action: {decision.action}",
        f"- allowed: {str(decision.allowed).lower()}",
        f"- confidence: {decision.confidence:.2f}",
        f"- reason: {decision.reason}",
        f"- goal: {decision.goal or '-'}",
        f"- instruction: {decision.instruction or '-'}",
    ]
    if decision.conflicts:
        lines.extend(["", "## Conflicts", ""])
        lines.extend(f"- {item}" for item in decision.conflicts)
    if decision.warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {item}" for item in decision.warnings)
    if decision.contract is not None:
        lines.extend(["", "## Contract", ""])
        lines.append(f"- obedience: {decision.contract.obedience}")
        lines.append(f"- conflict_policy: {decision.contract.conflict_policy}")
        lines.append(f"- data_strict: {str(decision.contract.data_strict).lower()}")
        lines.append(f"- uncertainty_policy: {decision.contract.uncertainty_policy}")
        lines.append(f"- quant_strict: {str(decision.contract.quant_strict).lower()}")
        lines.append(f"- hallucination_policy: {decision.contract.hallucination_policy}")
        lines.append(f"- source: {decision.contract.source}")
    return "\n".join(lines) + "\n"


def _contract_from_mapping(data: dict[str, Any], *, source: str) -> GoalContract:
    return GoalContract(
        goal=str(data.get("goal") or data.get("objective") or ""),
        obedience=str(data.get("obedience") or "follow_user_unless_goal_conflict"),
        constraints=tuple(str(item) for item in _list(data.get("constraints"))),
        success_criteria=tuple(str(item) for item in _list(data.get("success_criteria") or data.get("successCriteria"))),
        conflict_policy=str(data.get("conflict_policy") or data.get("conflictPolicy") or "block_goal_conflict"),
        data_strict=_bool(data.get("data_strict", data.get("dataStrict", True))),
        uncertainty_policy=str(data.get("uncertainty_policy") or data.get("uncertaintyPolicy") or "block_uncertain_data_claims"),
        quant_strict=_bool(data.get("quant_strict", data.get("quantStrict", True))),
        hallucination_policy=str(data.get("hallucination_policy") or data.get("hallucinationPolicy") or "block_unsupported_quant_claims"),
        source=source,
    )


def _conflict_evidence(instruction: str, contract: GoalContract) -> list[str]:
    text = _normalize(instruction)
    goal_text = _normalize(" ".join([contract.goal, *contract.constraints, *contract.success_criteria]))
    evidence: list[str] = []
    if _has_any(text, SKIP_TERMS) and _has_any(goal_text, QUALITY_TERMS):
        evidence.append("instruction asks to skip/bypass safeguards while goal requires quality, testing, validation, or safety")
    if _has_any(text, DESTRUCTIVE_TERMS) and not _has_any(goal_text, {"delete", "remove", "清空", "删除", "重置"}):
        evidence.append("instruction is broadly destructive but the goal does not require destructive cleanup")
    protected_terms = _goal_keywords(goal_text)
    negated = _negated_goal_terms(text, protected_terms)
    if negated:
        evidence.append("instruction negates goal-critical term(s): " + ", ".join(sorted(negated)[:8]))
    if "ignore" in text and ("goal" in text or "objective" in text or "目标" in text):
        evidence.append("instruction explicitly asks to ignore the stated goal")
    return evidence


def _warning_evidence(instruction: str, contract: GoalContract) -> list[str]:
    text = _normalize(instruction)
    goal_text = _normalize(" ".join([contract.goal, *contract.constraints, *contract.success_criteria]))
    warnings: list[str] = []
    if _has_any(text, SKIP_TERMS) and not _has_any(goal_text, QUALITY_TERMS):
        warnings.append("instruction asks to skip or bypass something; verify it does not weaken the goal")
    if _has_any(text, OBEDIENCE_TERMS) and ("unless" not in text and "除非" not in text):
        warnings.append("strict obedience requested; still applying goal-conflict guard")
    return warnings


def _strict_data_conflicts(instruction: str, contract: GoalContract) -> list[str]:
    if not contract.data_strict:
        return []
    text = _normalize(instruction)
    goal_text = _normalize(" ".join([contract.goal, *contract.constraints, *contract.success_criteria]))
    if not _is_data_context(text, goal_text):
        return []
    if _is_code_repair_instruction(text):
        return []
    evidence: list[str] = []
    if _has_any(text, UNCERTAIN_DATA_TERMS) and (_has_any(text, DATA_ASSERTION_TERMS) or _has_numeric_data(text) or _has_any(text, DATA_TERMS)):
        evidence.append("instruction asks to provide or assert data while admitting uncertainty, guessing, fabrication, or no checking")
    if _has_any(text, DATA_ASSERTION_TERMS) and _has_numeric_data(text) and (not _has_any(text, DATA_EVIDENCE_TERMS) or _negates_data_evidence(text)):
        evidence.append("data or numeric conclusion requested without source, log, command output, file, official source, or measured evidence")
    if _negates_data_evidence(text) and (_has_any(text, DATA_ASSERTION_TERMS) or _has_numeric_data(text) or _has_any(text, DATA_TERMS)):
        evidence.append("instruction explicitly negates required data evidence")
    if _has_any(text, {"assume it passed", "假装通过", "直接说通过"}) and _has_any(text, {"test", "tests", "validation", "测试", "验证"}):
        evidence.append("instruction asks to report verification success without verification evidence")
    return evidence


def _strict_data_warnings(instruction: str, contract: GoalContract) -> list[str]:
    if not contract.data_strict:
        return []
    text = _normalize(instruction)
    goal_text = _normalize(" ".join([contract.goal, *contract.constraints, *contract.success_criteria]))
    if not _is_data_context(text, goal_text):
        return []
    if _is_code_repair_instruction(text):
        return []
    warnings = [
        "data strict mode active: uncertain data may be reported only as unknown/unverified, not as fact",
    ]
    if _has_any(text, DATA_TERMS) and not _has_any(text, DATA_EVIDENCE_TERMS):
        warnings.append("data request has no explicit evidence source; collect or cite evidence before answering")
    return warnings


def _strict_quant_conflicts(instruction: str, contract: GoalContract) -> list[str]:
    if not contract.quant_strict:
        return []
    text = _normalize(instruction)
    goal_text = _normalize(" ".join([contract.goal, *contract.constraints, *contract.success_criteria]))
    if not _is_quant_context(text, goal_text):
        return []
    evidence: list[str] = []
    safety = assess_quant_claim(instruction)
    if safety.action != SAFETY_ALLOW:
        evidence.append("quant claim safety gate: " + "; ".join(safety.reasons or (safety.level,)))
    if _has_any(text, HALLUCINATION_RELAX_TERMS):
        evidence.append("instruction relaxes evidence or invites guessing/fabrication in a quant context")
    if _negates_evidence(text):
        evidence.append("instruction explicitly negates required quant evidence")
    if _has_any(text, SKIP_TERMS) and _has_any(goal_text, QUALITY_TERMS | QUANT_TERMS):
        evidence.append("instruction skips tests/evidence while the quant goal requires strict validation")
    if _has_any(text, CLAIM_TERMS) and _mentions_quant_metric(text) and (not _has_any(text, EVIDENCE_TERMS) or _negates_evidence(text)):
        evidence.append("quant metric conclusion requested without evidence, artifact, baseline, hash, or validation reference")
    if _mentions_execution_claim(text) and not _has_any(text, {"slippage", "capacity", "fill", "broker", "滑点", "容量", "成交", "券商"}):
        evidence.append("execution/trading claim lacks slippage, capacity, or fill evidence")
    if _mentions_live_or_money_action(text) and not _has_any(goal_text, {"live", "order", "trade", "实盘", "下单", "交易"}):
        evidence.append("instruction moves toward live trading/account action outside the stated goal")
    return evidence


def _strict_quant_warnings(instruction: str, contract: GoalContract) -> list[str]:
    if not contract.quant_strict:
        return []
    text = _normalize(instruction)
    goal_text = _normalize(" ".join([contract.goal, *contract.constraints, *contract.success_criteria]))
    if not _is_quant_context(text, goal_text):
        return []
    warnings = [
        "quant strict mode active: claims need dedup baselines, artifacts, hashes, diagnostics, or test evidence",
    ]
    if _mentions_quant_metric(text) and not _has_any(text, EVIDENCE_TERMS):
        warnings.append("quant metric mentioned without explicit evidence terms")
    return warnings


def _is_quant_context(instruction_text: str, goal_text: str) -> bool:
    return _has_any(instruction_text, QUANT_TERMS) or _has_any(goal_text, QUANT_TERMS)


def _is_data_context(instruction_text: str, goal_text: str) -> bool:
    return (
        _has_any(instruction_text, DATA_TERMS | DATA_ASSERTION_TERMS | UNCERTAIN_DATA_TERMS)
        or _has_any(goal_text, DATA_TERMS)
        or _has_numeric_data(instruction_text)
    )


def _mentions_execution_claim(text: str) -> bool:
    return _has_any(text, {"execution", "fill", "broker", "trade", "order", "09:30", "成交", "实盘", "下单", "交易"})


def _mentions_quant_metric(text: str) -> bool:
    return _has_any(text, QUANT_METRIC_TERMS) or re.search(r"\bpf\s*=", text, flags=re.IGNORECASE) is not None


def _negates_evidence(text: str) -> bool:
    evidence_words = ("evidence", "dedup", "baseline", "artifact", "hash", "validation", "test", "证据", "去重", "基线", "产物", "哈希", "验证", "测试")
    negators = ("without", "no", "not", "skip", "ignore", "bypass", "不要", "不用", "没有", "跳过", "忽略", "绕过")
    for negator in negators:
        for word in evidence_words:
            if _contains(text, f"{negator} {word}") or _contains(text, f"{negator}{word}"):
                return True
    return False


def _negates_data_evidence(text: str) -> bool:
    evidence_words = (
        "evidence",
        "source",
        "log",
        "output",
        "command output",
        "file",
        "official",
        "measured",
        "verified",
        "data",
        "test",
        "validation",
        "证据",
        "来源",
        "日志",
        "输出",
        "文件",
        "官方",
        "实测",
        "验证",
        "数据",
        "测试",
    )
    negators = ("without", "no", "not", "skip", "ignore", "bypass", "不要", "不用", "没有", "跳过", "忽略", "绕过", "不查")
    for negator in negators:
        for word in evidence_words:
            if _contains(text, f"{negator} {word}") or _contains(text, f"{negator}{word}"):
                return True
    return False


def _has_numeric_data(text: str) -> bool:
    return DATA_NUMERIC_RE.search(text) is not None


def _is_code_repair_instruction(text: str) -> bool:
    return _has_any(text, {"repair", "fix", "implement", "debug", "refactor", "unit test", "unit tests"}) and _has_any(
        text,
        {"subject.py", ".py", "function", "unit test", "unit tests", "contract", "tests pass"},
    )


def _mentions_live_or_money_action(text: str) -> bool:
    return _has_any(text, {"buy", "sell", "order", "withdraw", "transfer", "live trade", "下单", "买入", "卖出", "转账", "提现"})


def _goal_keywords(goal_text: str) -> set[str]:
    tokens = {
        token
        for token in re.findall(r"[a-z][a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", goal_text.lower())
        if token not in {"the", "and", "for", "with", "that", "this", "一个", "这个", "目标", "实现"}
    }
    return set(list(tokens)[:80])


def _negated_goal_terms(text: str, terms: set[str]) -> set[str]:
    negators = ("no", "not", "without", "skip", "ignore", "disable", "remove", "不要", "不用", "别", "跳过", "忽略", "禁用", "删除")
    hits: set[str] = set()
    for term in terms:
        for negator in negators:
            if _contains(text, f"{negator} {term}") or _contains(text, f"{negator}{term}"):
                hits.add(term)
    return hits


def _same_goal_and_instruction(goal: str, instruction: str) -> bool:
    normalized_goal = _normalize(goal)
    normalized_instruction = _normalize(instruction)
    return normalized_goal == normalized_instruction or normalized_instruction in normalized_goal


def _has_any(text: str, terms: Iterable[str]) -> bool:
    return any(_contains(text, _normalize(term)) for term in terms)


def _contains(text: str, term: str) -> bool:
    if not term:
        return False
    if any(ord(char) > 127 for char in term):
        return term in text
    return re.search(r"(?<![a-z0-9_])" + re.escape(term) + r"(?![a-z0-9_])", text) is not None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        return [value]
    return []


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", "否", "关闭"}
    if value is None:
        return False
    return bool(value)
