from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping


SKILL_LEARNING_REGISTRY_RELATIVE_PATH = Path(".quantagent") / "skill_learning" / "registry.jsonl"
_TOKEN_RE = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]+")
_FAIL_STATUSES = {"fail", "failed", "failure", "error", "blocked", "aborted", "lost"}
_PASS_STATUSES = {"pass", "passed", "success", "ok", "done"}
_ALLOWED_STATUSES = {"candidate", "approved", "rejected"}


@dataclass(frozen=True)
class SkillCandidate:
    name: str
    trigger: str
    evidence: tuple[str, ...]
    body: str
    status: str = "candidate"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "trigger": self.trigger,
            "evidence": list(self.evidence),
            "body": self.body,
            "status": self.status,
        }


def generate_skill_candidates(
    *,
    query_events: Iterable[Any] = (),
    trajectory: Iterable[Any] = (),
    runtime_view: Any | None = None,
    max_candidates: int = 4,
) -> tuple[SkillCandidate, ...]:
    """Derive inert skill candidates from successful and failed runtime signals."""
    records = []
    records.extend(_records_from_query_events(query_events))
    records.extend(_records_from_trajectory(trajectory))
    records.extend(_records_from_runtime_view(runtime_view))
    if not records:
        return ()

    task = _first_nonempty(record.get("task", "") for record in records)
    success_records = [record for record in records if record.get("ok") is True]
    failure_records = [record for record in records if record.get("ok") is False]

    candidates: list[SkillCandidate] = []
    if success_records:
        candidates.append(_build_candidate("success", task=task, records=success_records))
    if failure_records:
        candidates.append(_build_candidate("failure", task=task, records=failure_records))

    return tuple(_dedupe_candidates(candidates)[: max(0, max_candidates)])


def approve_skill_candidate(candidate: SkillCandidate | Mapping[str, Any]) -> SkillCandidate:
    return _with_status(candidate, "approved")


def reject_skill_candidate(candidate: SkillCandidate | Mapping[str, Any]) -> SkillCandidate:
    return _with_status(candidate, "rejected")


def registry_path(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / SKILL_LEARNING_REGISTRY_RELATIVE_PATH


def append_skill_candidates_registry(project: str | Path, candidates: Iterable[SkillCandidate | Mapping[str, Any]]) -> Path:
    target = registry_path(project)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        for candidate in candidates:
            normalized = normalize_skill_candidate(candidate)
            handle.write(json.dumps(normalized.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return target


def load_skill_candidates_registry(project: str | Path) -> tuple[SkillCandidate, ...]:
    target = registry_path(project)
    if not target.exists():
        return ()
    candidates: list[SkillCandidate] = []
    with target.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid skill candidate registry JSONL at line {line_number}: {exc.msg}") from exc
            if not isinstance(payload, Mapping):
                raise ValueError(f"Invalid skill candidate registry JSONL at line {line_number}: expected object")
            candidates.append(normalize_skill_candidate(payload))
    return tuple(candidates)


def normalize_skill_candidate(candidate: SkillCandidate | Mapping[str, Any]) -> SkillCandidate:
    if isinstance(candidate, SkillCandidate):
        _validate_status(candidate.status)
        return candidate
    evidence = candidate.get("evidence") or ()
    if isinstance(evidence, str):
        evidence_items = (evidence,)
    else:
        evidence_items = tuple(_compact(str(item)) for item in evidence if _compact(str(item)))
    status = str(candidate.get("status") or "candidate")
    _validate_status(status)
    normalized = SkillCandidate(
        name=_clean_name(str(candidate.get("name") or "")),
        trigger=_compact(str(candidate.get("trigger") or "")),
        evidence=evidence_items,
        body=_compact(str(candidate.get("body") or "")),
        status=status,
    )
    if not normalized.name:
        raise ValueError("skill candidate name is required")
    if not normalized.trigger:
        raise ValueError("skill candidate trigger is required")
    if not normalized.body:
        raise ValueError("skill candidate body is required")
    return normalized


def _records_from_query_events(events: Iterable[Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    task = ""
    for event in events:
        payload = _to_mapping(event)
        kind = str(payload.get("kind") or "")
        data = _mapping(payload.get("data"))
        if kind == "query_start":
            task = _compact(str(data.get("task") or payload.get("summary") or task))
        records.append(
            {
                "source": "query_events",
                "kind": kind,
                "name": str(payload.get("name") or data.get("tool") or ""),
                "summary": _compact(str(payload.get("summary") or data.get("summary") or kind)),
                "ok": _ok_from_payload(payload),
                "task": task,
                "step": payload.get("step"),
            }
        )
    return records


def _records_from_trajectory(events: Iterable[Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for event in events:
        payload = _to_mapping(event)
        meta = _mapping(payload.get("meta"))
        records.append(
            {
                "source": "trajectory",
                "kind": str(payload.get("kind") or ""),
                "name": str(meta.get("tool") or meta.get("command") or meta.get("phase") or ""),
                "summary": _compact(str(payload.get("content") or meta.get("summary") or "")),
                "ok": _ok_from_payload(payload),
                "task": _compact(str(meta.get("task") or meta.get("goal") or "")),
                "step": payload.get("step"),
            }
        )
    return records


def _records_from_runtime_view(view: Any | None) -> list[dict[str, Any]]:
    if view is None:
        return []
    payload = _runtime_payload(view)
    task = _compact(str(payload.get("task") or ""))
    records: list[dict[str, Any]] = []
    for item in payload.get("evidence") or []:
        evidence = _mapping(item)
        records.append(
            {
                "source": str(evidence.get("source") or "runtime_view"),
                "kind": str(evidence.get("kind") or "evidence"),
                "name": str(evidence.get("name") or evidence.get("evidence_id") or ""),
                "summary": _compact(str(evidence.get("summary") or "")),
                "ok": _ok_from_payload(evidence),
                "task": task,
                "step": evidence.get("step"),
            }
        )
    for step in payload.get("steps") or []:
        item = _mapping(step)
        records.append(
            {
                "source": "runtime_view",
                "kind": str(item.get("kind") or "step"),
                "name": str(item.get("name") or item.get("step_id") or ""),
                "summary": _compact(str(item.get("summary") or "")),
                "ok": _ok_from_payload(item),
                "task": task,
                "step": item.get("index"),
            }
        )
    if payload.get("summary"):
        records.append(
            {
                "source": "runtime_view",
                "kind": "summary",
                "name": "",
                "summary": _compact(str(payload.get("summary") or "")),
                "ok": _ok_from_payload(payload),
                "task": task,
                "step": None,
            }
        )
    return records


def _build_candidate(kind: str, *, task: str, records: list[dict[str, Any]]) -> SkillCandidate:
    selected = records[:6]
    trigger = _trigger(task, selected)
    evidence = tuple(_evidence_line(record) for record in selected)
    joined = " ".join(record["summary"] for record in selected if record.get("summary"))
    if kind == "failure":
        body = (
            f"Use this when {trigger}. Avoid the observed failure pattern: {_preview(joined, 360)}. "
            "Before acting, reproduce the failing signal, classify the failure, add a narrow guard or test, "
            "then retry the smallest change. Keep the skill inert until an operator approves it."
        )
        prefix = "avoid"
    else:
        body = (
            f"Use this when {trigger}. Repeat the observed successful pattern: {_preview(joined, 360)}. "
            "Preserve the evidence path, run the same verifier, and stop if fresh evidence contradicts the pattern. "
            "Keep the skill inert until an operator approves it."
        )
        prefix = "repeat"
    name = _candidate_name(prefix, trigger, body)
    return SkillCandidate(name=name, trigger=trigger, evidence=evidence, body=body)


def _with_status(candidate: SkillCandidate | Mapping[str, Any], status: str) -> SkillCandidate:
    normalized = normalize_skill_candidate(candidate)
    return replace(normalized, status=status)


def _candidate_name(prefix: str, trigger: str, body: str) -> str:
    terms = _terms(trigger)[:4]
    base = "-".join(terms) or "runtime-pattern"
    digest = hashlib.sha256(f"{trigger}\n{body}".encode("utf-8")).hexdigest()[:10]
    return _clean_name(f"{prefix}-{base}-{digest}")[:80].strip("-")


def _trigger(task: str, records: list[dict[str, Any]]) -> str:
    text_parts = [task]
    text_parts.extend(str(record.get("name") or "") for record in records)
    text_parts.extend(str(record.get("kind") or "") for record in records)
    text_parts.extend(str(record.get("summary") or "") for record in records[:3])
    terms = _dedupe(_terms(" ".join(text_parts)))
    if not terms:
        return "similar runtime pattern"
    return ", ".join(terms[:8])


def _evidence_line(record: Mapping[str, Any]) -> str:
    step = record.get("step")
    step_text = f" step={step}" if step is not None else ""
    status = "ok" if record.get("ok") is True else "failed" if record.get("ok") is False else "unknown"
    name = str(record.get("name") or record.get("kind") or "")
    summary = _preview(str(record.get("summary") or ""), 180)
    return f"{record.get('source')}:{name}{step_text} [{status}] {summary}".strip()


def _dedupe_candidates(candidates: Iterable[SkillCandidate]) -> list[SkillCandidate]:
    seen: set[tuple[str, str, str]] = set()
    out: list[SkillCandidate] = []
    for candidate in candidates:
        key = (candidate.trigger, candidate.body, candidate.status)
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


def _runtime_payload(view: Any) -> Mapping[str, Any]:
    if hasattr(view, "to_payload"):
        payload = view.to_payload()
        return _mapping(payload)
    return _mapping(view)


def _to_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "to_dict"):
        return _mapping(value.to_dict())
    if hasattr(value, "to_payload"):
        return _mapping(value.to_payload())
    try:
        return _mapping(asdict(value))
    except TypeError:
        return {}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _ok_from_payload(payload: Mapping[str, Any]) -> bool | None:
    ok = payload.get("ok")
    if isinstance(ok, bool):
        return ok
    status = str(payload.get("status") or "").lower()
    if status in _FAIL_STATUSES:
        return False
    if status in _PASS_STATUSES:
        return True
    return None


def _terms(text: str) -> list[str]:
    terms: list[str] = []
    for match in _TOKEN_RE.finditer(text.lower()):
        token = match.group(0).strip("_")
        if len(token) < 2:
            continue
        if token in {"the", "and", "for", "with", "this", "that", "step", "kind", "ok"}:
            continue
        terms.append(token)
    return terms


def _clean_name(text: str) -> str:
    lowered = text.strip().lower()
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", lowered)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned.strip("-")


def _compact(text: str) -> str:
    return " ".join(str(text).split())


def _preview(text: str, limit: int) -> str:
    compact = _compact(text)
    if limit <= 0 or len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 1)].rstrip() + "..."


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _first_nonempty(items: Iterable[str]) -> str:
    for item in items:
        compact = _compact(item)
        if compact:
            return compact
    return ""


def _validate_status(status: str) -> None:
    if status not in _ALLOWED_STATUSES:
        allowed = ", ".join(sorted(_ALLOWED_STATUSES))
        raise ValueError(f"Unknown skill candidate status {status!r}; expected one of: {allowed}")
