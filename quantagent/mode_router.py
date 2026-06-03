from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .agent_modes import AgentMode, get_agent_mode, list_agent_modes


PLAN_TERMS = (
    "plan",
    "proposal",
    "design",
    "architecture",
    "strategy",
    "evaluate",
    "assess",
    "compare",
    "roadmap",
    "计划",
    "方案",
    "设计",
    "架构",
    "评估",
    "评价",
    "怎么",
    "如何",
    "下一步",
)
BUILD_TERMS = (
    "implement",
    "build",
    "create",
    "generate",
    "add",
    "change",
    "modify",
    "update",
    "patch",
    "refactor",
    "fix",
    "write",
    "code",
    "接入",
    "实现",
    "新增",
    "修改",
    "修复",
    "开干",
    "继续",
    "写",
    "做",
    "补",
)
REVIEW_TERMS = (
    "review",
    "audit",
    "diff",
    "pr",
    "pull request",
    "regression",
    "risk",
    "inspect",
    "审查",
    "review",
    "看看",
    "风险",
    "漏洞",
    "回归",
)
REPAIR_TERMS = (
    "repair",
    "retry",
    "test failed",
    "failure",
    "broken",
    "traceback",
    "exception",
    "修失败",
    "失败",
    "报错",
    "挂了",
    "修测试",
)
RESEARCH_TERMS = (
    "research",
    "learn",
    "source",
    "search",
    "explain",
    "compare",
    "what is",
    "怎么写的",
    "源码",
    "学习",
    "调研",
    "对标",
    "抄",
    "借鉴",
)
ADMIN_TERMS = (
    "mcp",
    "daemon",
    "plugin",
    "gateway",
    "session bus",
    "approval",
    "permission",
    "doctor",
    "runtime",
    "sandbox",
    "worktree",
    "插件",
    "权限",
    "网关",
    "守护",
    "沙箱",
)


@dataclass(frozen=True)
class ModeSignal:
    name: str
    weight: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModeRoute:
    mode: str
    profile: str
    intent: str
    confidence: float
    previous_mode: str = ""
    transition: str = "stay"
    reasons: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()
    signals: tuple[ModeSignal, ...] = ()
    source: str = "heuristic"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["signals"] = [signal.to_dict() for signal in self.signals]
        return payload


@dataclass(frozen=True)
class ModeRouterDiagnostic:
    level: str
    message: str
    mode: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def route_agent_mode(
    project: str | Path | None,
    task: str,
    *,
    explicit_mode: str = "",
    previous_mode: str = "",
    failure_class: str = "",
    changed_paths: Iterable[str | Path] = (),
    input_provenance: str = "",
    tool_name: str = "",
) -> ModeRoute:
    """Select an agent mode from task intent and runtime evidence.

    This is intentionally deterministic. Model-based routing can sit above it
    later, but the agent loop needs a cheap local router for every tool turn.
    """
    modes = {mode.name: mode for mode in list_agent_modes(project)}
    if explicit_mode:
        mode = _known_mode(project, explicit_mode)
        return ModeRoute(
            mode=mode.name,
            profile=mode.profile,
            intent=_intent_for_mode(mode.name),
            confidence=1.0,
            previous_mode=previous_mode,
            transition=_transition(previous_mode, mode.name),
            reasons=(f"explicit mode {mode.name}",),
            alternatives=tuple(name for name in _ranked_names(modes, exclude=mode.name)[:3]),
            signals=(ModeSignal(mode.name, 100, "explicit user or caller selection"),),
            source="explicit",
        )

    scores: dict[str, int] = {name: 0 for name in modes}
    signals: list[ModeSignal] = []
    text = _normalize(" ".join([task, input_provenance, tool_name]))
    paths = tuple(_normalize_path(path) for path in changed_paths if str(path).strip())

    def add(mode: str, weight: int, reason: str) -> None:
        if mode not in scores:
            return
        scores[mode] += weight
        signals.append(ModeSignal(mode, weight, reason))

    if failure_class:
        if failure_class in {"verification_failed", "tool_failed", "diagnostic_failed", "command_failed"}:
            add("repair", 60, f"failure_class={failure_class}")
        elif failure_class == "policy_blocked":
            add("admin", 28, "policy blocked runtime needs permission/control-plane inspection")
            add("plan", 12, "policy block should be explained before mutation")

    if previous_mode == "build" and failure_class:
        add("repair", 22, "build mode failure should escalate to repair mode")
    if previous_mode == "repair" and not failure_class:
        add("review", 12, "repair completed work should be reviewed")

    _score_terms(text, PLAN_TERMS, lambda term: add("plan", 12, f"planning term: {term}"))
    _score_terms(text, BUILD_TERMS, lambda term: add("build", 14, f"build term: {term}"))
    _score_terms(text, REVIEW_TERMS, lambda term: add("review", 14, f"review term: {term}"))
    _score_terms(text, REPAIR_TERMS, lambda term: add("repair", 18, f"repair term: {term}"))
    _score_terms(text, RESEARCH_TERMS, lambda term: add("research", 10, f"research term: {term}"))
    _score_terms(text, ADMIN_TERMS, lambda term: add("admin", 16, f"admin term: {term}"))

    if tool_name:
        normalized_tool = tool_name.strip().lower()
        if normalized_tool in {"file_read", "file_search", "context", "repo-map", "repo_map", "diagnostics"}:
            add("research", 8, f"readonly tool requested: {normalized_tool}")
        if normalized_tool in {"file_edit", "file_write", "apply_patch", "apply-gate.apply"}:
            add("build", 24, f"mutating tool requested: {normalized_tool}")
        if normalized_tool in {"mcp", "mcp-daemon", "session-bus", "plugins"} or normalized_tool.startswith("mcp"):
            add("admin", 24, f"control-plane tool requested: {normalized_tool}")

    if paths:
        add("build", 10, f"{len(paths)} changed path(s) imply code work")
        if any(path.endswith((".diff", ".patch")) for path in paths):
            add("review", 16, "diff/patch path implies review")
        if any(path.startswith((".quantagent/", "AI_协作交接/")) for path in paths):
            add("admin", 8, "runtime/config path touched")
        if any(path.startswith("tests/") or "/tests/" in path for path in paths):
            add("repair", 8, "test path touched")

    if not signals:
        add("plan", 8, "no strong mutation signal; start in plan mode")
        add("research", 6, "unknown task benefits from evidence gathering")

    mode_name = _select_mode(scores, default="plan")
    if mode_name == "research" and scores.get("build", 0) >= scores.get("research", 0) and _has_any(text, BUILD_TERMS):
        mode_name = "build"
    if mode_name == "plan" and _has_any(text, BUILD_TERMS) and not _has_any(text, PLAN_TERMS):
        mode_name = "build"

    mode = modes.get(mode_name) or _known_mode(project, "plan")
    ranked = [name for name, _score in sorted(scores.items(), key=lambda item: (-item[1], item[0])) if name != mode.name]
    best = max(scores.values()) if scores else 0
    runner_up = scores.get(ranked[0], 0) if ranked else 0
    confidence = _confidence(best, runner_up)
    reasons = tuple(signal.reason for signal in sorted(signals, key=lambda item: -item.weight)[:8] if signal.name == mode.name)
    if not reasons:
        reasons = (f"highest heuristic score={scores.get(mode.name, 0)}",)
    return ModeRoute(
        mode=mode.name,
        profile=mode.profile,
        intent=_intent_for_mode(mode.name),
        confidence=confidence,
        previous_mode=previous_mode,
        transition=_transition(previous_mode, mode.name),
        reasons=reasons,
        alternatives=tuple(ranked[:3]),
        signals=tuple(sorted(signals, key=lambda item: (-item.weight, item.name))[:16]),
    )


def validate_mode_router(project: str | Path | None = None) -> list[ModeRouterDiagnostic]:
    diagnostics: list[ModeRouterDiagnostic] = []
    modes = {mode.name: mode for mode in list_agent_modes(project)}
    required = {"plan", "build", "review", "repair", "research", "admin"}
    missing = sorted(required - set(modes))
    diagnostics.extend(ModeRouterDiagnostic("error", f"missing builtin route target {name}", name) for name in missing)
    samples = {
        "plan": "设计一个补丁计划但不要改文件",
        "build": "实现自动 mode router 并接入 CLI",
        "review": "review this diff for regression risk",
        "repair": "tests failed with traceback, repair the loop",
        "research": "学习 ClaudeCode 源码思路并总结",
        "admin": "start MCP daemon and inspect permission approvals",
    }
    for expected, task in samples.items():
        route = route_agent_mode(project, task)
        if route.mode != expected:
            diagnostics.append(ModeRouterDiagnostic("warning", f"sample routed to {route.mode}, expected {expected}", expected))
    return diagnostics


def render_mode_route(route: ModeRoute) -> str:
    lines = [
        "# Agent Mode Route",
        "",
        f"- mode: {route.mode}",
        f"- profile: {route.profile}",
        f"- intent: {route.intent}",
        f"- confidence: {route.confidence:.2f}",
        f"- transition: {route.transition}",
        f"- previous_mode: {route.previous_mode or '-'}",
        f"- source: {route.source}",
        "",
        "## Reasons",
        "",
    ]
    lines.extend(f"- {reason}" for reason in (route.reasons or ("no route reason",)))
    if route.alternatives:
        lines.extend(["", "## Alternatives", ""])
        lines.extend(f"- {name}" for name in route.alternatives)
    if route.signals:
        lines.extend(["", "## Signals", ""])
        for signal in route.signals[:12]:
            lines.append(f"- {signal.name} +{signal.weight}: {signal.reason}")
    return "\n".join(lines) + "\n"


def render_mode_router_diagnostics(diagnostics: Iterable[ModeRouterDiagnostic]) -> str:
    items = list(diagnostics)
    if not items:
        return "Mode router diagnostics passed.\n"
    lines = ["# Mode Router Diagnostics", ""]
    for item in items:
        mode = f" mode={item.mode}" if item.mode else ""
        lines.append(f"- [{item.level}]{mode}: {item.message}")
    return "\n".join(lines) + "\n"


def _known_mode(project: str | Path | None, name: str) -> AgentMode:
    try:
        return get_agent_mode(project, name)
    except KeyError as exc:
        raise KeyError(f"unknown agent mode for router: {name}") from exc


def _ranked_names(modes: dict[str, AgentMode], *, exclude: str) -> list[str]:
    preferred = ["plan", "build", "review", "repair", "research", "admin"]
    return [name for name in preferred if name in modes and name != exclude] + sorted(name for name in modes if name not in preferred and name != exclude)


def _score_terms(text: str, terms: tuple[str, ...], callback: Any) -> None:
    for term in terms:
        normalized = _normalize(term)
        if not normalized:
            continue
        if _contains_term(text, normalized):
            callback(term)


def _contains_term(text: str, term: str) -> bool:
    if not term:
        return False
    if any(ord(char) > 127 for char in term):
        return term in text
    return re.search(r"(?<![a-z0-9_])" + re.escape(term) + r"(?![a-z0-9_])", text) is not None


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(_contains_term(text, _normalize(term)) for term in terms)


def _select_mode(scores: dict[str, int], *, default: str) -> str:
    if not scores:
        return default
    best_name, best_score = sorted(scores.items(), key=lambda item: (-item[1], _mode_tiebreaker(item[0])))[0]
    return best_name if best_score > 0 else default


def _mode_tiebreaker(name: str) -> int:
    order = {"repair": 0, "admin": 1, "build": 2, "review": 3, "plan": 4, "research": 5}
    return order.get(name, 20)


def _confidence(best: int, runner_up: int) -> float:
    if best <= 0:
        return 0.35
    margin = max(0, best - runner_up)
    raw = 0.45 + min(0.45, best / 120) + min(0.10, margin / 80)
    return round(min(0.99, raw), 2)


def _transition(previous: str, current: str) -> str:
    previous = previous.strip()
    if not previous:
        return "start"
    if previous == current:
        return "stay"
    return f"{previous}->{current}"


def _intent_for_mode(mode: str) -> str:
    return {
        "plan": "plan_without_mutation",
        "build": "make_reviewed_code_changes",
        "review": "inspect_evidence_and_risks",
        "repair": "fix_failed_validation_in_isolation",
        "research": "gather_and_summarize_evidence",
        "admin": "operate_runtime_control_plane",
    }.get(mode, "custom_mode")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _normalize_path(path: str | Path) -> str:
    return str(path).replace("\\", "/").strip().lstrip("./")
