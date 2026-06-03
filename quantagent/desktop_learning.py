from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


INTERCEPTS_VERSION = 1
INTERCEPTS_RELATIVE_PATH = Path(".quantagent") / "desktop" / "learning" / "intercepts.json"
_TOKEN_RE = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]+")


@dataclass(frozen=True)
class DesktopInterceptRule:
    rule_id: str
    failure_class: str
    failed_at: str
    sources: tuple[str, ...]
    goal_terms: tuple[str, ...]
    action_terms: tuple[str, ...]
    intercept: str
    source_autopsy: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["sources"] = list(self.sources)
        payload["goal_terms"] = list(self.goal_terms)
        payload["action_terms"] = list(self.action_terms)
        return payload


@dataclass(frozen=True)
class DesktopInterceptMatch:
    rule: DesktopInterceptRule
    score: float
    matched_on: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"rule": self.rule.to_dict(), "score": self.score, "matched_on": list(self.matched_on)}


def intercepts_path(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / INTERCEPTS_RELATIVE_PATH


def load_intercept_rules(project: str | Path) -> tuple[DesktopInterceptRule, ...]:
    path = intercepts_path(project)
    if not path.exists():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    if not isinstance(payload, Mapping) or payload.get("version") != INTERCEPTS_VERSION:
        return ()
    rules = [_rule_from_payload(item) for item in payload.get("rules") or []]
    return tuple(rule for rule in rules if rule is not None)


def save_intercept_rules(project: str | Path, rules: Iterable[DesktopInterceptRule]) -> Path:
    target = intercepts_path(project)
    target.parent.mkdir(parents=True, exist_ok=True)
    normalized = _dedupe_rules(rules)
    payload = {"version": INTERCEPTS_VERSION, "rules": [rule.to_dict() for rule in normalized]}
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def learn_intercepts_from_autopsy(
    project: str | Path,
    autopsy_path: str | Path,
    *,
    goal: str = "",
    action: str | Mapping[str, Any] = "",
) -> tuple[DesktopInterceptRule, ...]:
    path = Path(autopsy_path).expanduser().resolve(strict=False)
    extracted = extract_autopsy_signal(path)
    failure_class = extracted["failure_class"]
    failed_at = extracted["failed_at"]
    if not failure_class or not failed_at:
        return load_intercept_rules(project)

    resolved_goal = goal or extracted["goal"]
    resolved_action = _action_text(action) or extracted["action"]
    rule = build_intercept_rule(
        failure_class=failure_class,
        failed_at=failed_at,
        sources=extracted["sources"],
        goal=resolved_goal,
        action=resolved_action,
        source_autopsy=str(path),
    )
    rules = _dedupe_rules((*load_intercept_rules(project), rule))
    save_intercept_rules(project, rules)
    return tuple(rules)


def extract_autopsy_signal(autopsy_path: str | Path) -> dict[str, Any]:
    path = Path(autopsy_path).expanduser().resolve(strict=False)
    text = path.read_text(encoding="utf-8", errors="replace")
    suffix = path.suffix.lower()
    if suffix in {".jsonl", ".json"}:
        return _extract_json_signal(text)
    return _extract_markdown_signal(text)


def build_intercept_rule(
    *,
    failure_class: str,
    failed_at: str,
    sources: Iterable[str] = (),
    goal: str = "",
    action: str | Mapping[str, Any] = "",
    source_autopsy: str = "",
) -> DesktopInterceptRule:
    normalized_failure = _compact(failure_class)
    normalized_failed_at = _compact(failed_at)
    normalized_sources = tuple(_dedupe(str(source) for source in sources))
    goal_terms = tuple(_terms(goal))
    action_terms = tuple(_terms(_action_text(action)))
    intercept = _intercept_text(
        failure_class=normalized_failure,
        failed_at=normalized_failed_at,
        sources=normalized_sources,
    )
    rule_id = _rule_id(
        {
            "failure_class": normalized_failure,
            "failed_at": normalized_failed_at,
            "sources": normalized_sources,
            "goal_terms": goal_terms,
            "action_terms": action_terms,
            "intercept": intercept,
        }
    )
    return DesktopInterceptRule(
        rule_id=rule_id,
        failure_class=normalized_failure,
        failed_at=normalized_failed_at,
        sources=normalized_sources,
        goal_terms=goal_terms,
        action_terms=action_terms,
        intercept=intercept,
        source_autopsy=source_autopsy,
    )


def match_intercept_rule(
    project: str | Path,
    *,
    goal: str = "",
    action: str | Mapping[str, Any] = "",
    failure_class: str = "",
    min_score: float = 0.5,
) -> DesktopInterceptMatch | None:
    goal_terms = set(_terms(goal))
    action_terms = set(_terms(_action_text(action)))
    requested_failure = _compact(failure_class)
    best: DesktopInterceptMatch | None = None
    for rule in load_intercept_rules(project):
        if requested_failure and rule.failure_class != requested_failure:
            continue
        score, matched_on = _similarity(rule, goal_terms=goal_terms, action_terms=action_terms)
        if score < min_score:
            continue
        candidate = DesktopInterceptMatch(rule=rule, score=score, matched_on=tuple(matched_on))
        if best is None or (candidate.score, candidate.rule.rule_id) > (best.score, best.rule.rule_id):
            best = candidate
    return best


def _extract_markdown_signal(text: str) -> dict[str, Any]:
    failure_class = ""
    failed_at = ""
    goal = ""
    sources: list[str] = []
    in_sources = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            in_sources = line == "## Sources"
            continue
        key, value = _markdown_kv(line)
        if key == "failure_class":
            failure_class = _unknown_to_empty(value)
        elif key == "failed_at":
            failed_at = _unknown_to_empty(value)
        elif key == "command":
            goal = _unknown_to_empty(value)
        elif in_sources and line.startswith("- "):
            item = line[2:].strip()
            if item and item != "no source file found":
                sources.append(item)
    return {"failure_class": failure_class, "failed_at": failed_at, "sources": _dedupe(sources), "goal": goal, "action": ""}


def _extract_json_signal(text: str) -> dict[str, Any]:
    payloads = _json_payloads(text)
    failure_class = ""
    failed_at = ""
    goal = ""
    action = ""
    sources: list[str] = []
    failed_step: int | None = None

    for payload in payloads:
        if not isinstance(payload, Mapping):
            continue
        data = _mapping(payload.get("data"))
        meta = _mapping(payload.get("meta"))
        merged = {**meta, **data}
        kind = str(payload.get("kind") or "")
        summary = str(payload.get("summary") or payload.get("content") or "")
        step = _int_or_none(payload.get("step"))
        if payload.get("command") and not goal:
            goal = _compact(str(payload["command"]))
        if payload.get("failure_class"):
            failure_class = _compact(str(payload["failure_class"]))
        if payload.get("failed_at"):
            failed_at = _compact(str(payload["failed_at"]))
        sources.extend(_coerce_sources(payload.get("sources")))
        if kind == "query_start":
            goal = _compact(str(data.get("task") or summary.removeprefix("query started:")))
        if merged.get("failure_class"):
            failure_class = _compact(str(merged["failure_class"]))
        if merged.get("failed_at"):
            failed_at = _compact(str(merged["failed_at"]))
        sources.extend(_coerce_sources(merged.get("sources")))
        if payload.get("ok") is False and failed_step is None:
            failed_step = step
            if not failed_at:
                phase = str(merged.get("phase") or kind or "unknown")
                failed_at = f"{phase} step {step}" if step is not None else phase
        if _looks_like_action(kind, merged, summary) and (failed_step is None or step is None or step <= failed_step):
            action = _compact(str(merged.get("action") or merged.get("summary") or summary))

    if not failure_class:
        failure_class = _classify_from_status(payloads)
    return {"failure_class": failure_class, "failed_at": failed_at, "sources": _dedupe(sources), "goal": goal, "action": action}


def _json_payloads(text: str) -> list[Any]:
    stripped = text.strip()
    if not stripped:
        return []
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, list):
            return payload
        if isinstance(payload, Mapping):
            if isinstance(payload.get("evidence"), list):
                return [payload, *list(payload["evidence"])]
            return [payload]
    out: list[Any] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _rule_from_payload(payload: Any) -> DesktopInterceptRule | None:
    if not isinstance(payload, Mapping):
        return None
    failure_class = _compact(str(payload.get("failure_class") or ""))
    failed_at = _compact(str(payload.get("failed_at") or ""))
    intercept = _compact(str(payload.get("intercept") or ""))
    rule_id = _compact(str(payload.get("rule_id") or ""))
    if not failure_class or not failed_at or not intercept or not rule_id:
        return None
    return DesktopInterceptRule(
        rule_id=rule_id,
        failure_class=failure_class,
        failed_at=failed_at,
        sources=tuple(_dedupe(str(item) for item in payload.get("sources") or [])),
        goal_terms=tuple(_dedupe(str(item) for item in payload.get("goal_terms") or [])),
        action_terms=tuple(_dedupe(str(item) for item in payload.get("action_terms") or [])),
        intercept=intercept,
        source_autopsy=str(payload.get("source_autopsy") or ""),
    )


def _similarity(rule: DesktopInterceptRule, *, goal_terms: set[str], action_terms: set[str]) -> tuple[float, list[str]]:
    matched: list[str] = []
    scores: list[float] = []
    if rule.goal_terms and goal_terms:
        score = _jaccard(set(rule.goal_terms), goal_terms)
        scores.append(score)
        if score > 0:
            matched.append("goal")
    if rule.action_terms and action_terms:
        score = _jaccard(set(rule.action_terms), action_terms)
        scores.append(score)
        if score > 0:
            matched.append("action")
    if not scores:
        return 0.0, []
    return max(scores), matched


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _intercept_text(*, failure_class: str, failed_at: str, sources: tuple[str, ...]) -> str:
    source_hint = ", ".join(Path(source).name for source in sources[:3])
    parts = [
        "Before a similar desktop goal/action, block execution and require deterministic preflight",
        f"failure_class={failure_class}",
        f"failed_at={failed_at}",
    ]
    if source_hint:
        parts.append(f"sources={source_hint}")
    return "; ".join(parts)


def _rule_id(payload: Mapping[str, Any]) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "desktop-intercept:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _dedupe_rules(rules: Iterable[DesktopInterceptRule]) -> tuple[DesktopInterceptRule, ...]:
    best: dict[str, DesktopInterceptRule] = {}
    for rule in rules:
        best[rule.rule_id] = rule
    return tuple(best[key] for key in sorted(best))


def _markdown_kv(line: str) -> tuple[str, str]:
    if not line.startswith("- ") or ":" not in line:
        return "", ""
    key, value = line[2:].split(":", 1)
    return key.strip(), value.strip()


def _unknown_to_empty(value: str) -> str:
    compact = _compact(value)
    return "" if compact.lower() in {"unknown", "none", "(unknown)"} else compact


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _coerce_sources(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, (str, Path)):
        return [str(value)]
    if isinstance(value, Iterable):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def _looks_like_action(kind: str, payload: Mapping[str, Any], summary: str) -> bool:
    phase = str(payload.get("phase") or "").lower()
    action = str(payload.get("action") or "").lower()
    lowered = summary.lower()
    return kind == "action" or phase in {"act", "decide"} or action not in {"", "hold", "noop"} or " click" in f" {lowered}"


def _classify_from_status(payloads: list[Any]) -> str:
    for payload in reversed(payloads):
        if not isinstance(payload, Mapping):
            continue
        data = _mapping(payload.get("data"))
        if payload.get("kind") == "stop_failure" and data.get("failure_class"):
            return _compact(str(data["failure_class"]))
        status = str(payload.get("status") or data.get("status") or _mapping(payload.get("meta")).get("status") or "")
        if status:
            return _compact(status)
    return ""


def _action_text(action: str | Mapping[str, Any]) -> str:
    if isinstance(action, Mapping):
        fields = [
            action.get("action"),
            action.get("target"),
            action.get("summary"),
            action.get("text"),
            action.get("selector"),
        ]
        return _compact(" ".join(str(item) for item in fields if item))
    return _compact(str(action or ""))


def _terms(text: str) -> list[str]:
    compact = _compact(text).lower()
    terms = [item for item in _TOKEN_RE.findall(compact) if len(item) > 1 and item not in _STOP_TERMS]
    return _dedupe(terms)[:24]


def _compact(text: str) -> str:
    return " ".join(str(text).strip().split())


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        item = _compact(str(value))
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


_STOP_TERMS = {
    "a",
    "an",
    "and",
    "at",
    "before",
    "button",
    "by",
    "daemon",
    "desktop",
    "for",
    "in",
    "of",
    "on",
    "or",
    "step",
    "the",
    "to",
    "with",
}
