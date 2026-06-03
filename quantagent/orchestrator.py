from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .context_pack import build_context_pack
from .model_client import ModelClient, ModelRequest


APPROVE = "APPROVE"
NEEDS_WORK = "NEEDS_WORK"
REJECT = "REJECT"
VERDICTS = {APPROVE, NEEDS_WORK, REJECT}
ROLES = ("researcher", "auditor", "data_engineer")


@dataclass(frozen=True)
class RoleResult:
    role: str
    verdict: str
    summary: str
    findings: list[str] = field(default_factory=list)
    allowed_safe_actions: list[str] = field(default_factory=list)
    blocked_material_actions: list[str] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    required_actions: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrchestrationResult:
    project: Path
    task: str
    model: str
    created_at: str
    context_summary: str
    results: tuple[RoleResult, ...]

    @property
    def verdict(self) -> str:
        verdicts = {result.verdict for result in self.results}
        if REJECT in verdicts:
            return REJECT
        if NEEDS_WORK in verdicts:
            return NEEDS_WORK
        return APPROVE

    @property
    def role_consensus(self) -> dict[str, Any]:
        return build_role_consensus(self.results, self.verdict)

    @property
    def role_conflicts(self) -> list[dict[str, Any]]:
        return build_role_conflicts(self.results)


ROLE_INSTRUCTIONS = {
    "researcher": """You are the researcher role.
Focus on research logic, assumptions, alternative explanations, and what evidence is still missing.
You may recommend analyses to run later, but you must not execute experiments, modify strategy code, or claim unverified performance conclusions.""",
    "auditor": """You are the auditor role.
Focus on leakage, duplicate or polluted samples, unrealistic execution assumptions, hidden degradation, weak controls, and unsupported conclusions.
Be strict. If evidence is insufficient, choose NEEDS_WORK or REJECT. You must not execute experiments or change strategy code.""",
    "data_engineer": """You are the data_engineer role.
Focus on data readiness, lineage, schema checks, reproducibility, input/output files, and safe preparation steps.
Recommend data preparation and verification actions only. Do not run experiments, mutate datasets, or change strategy logic.""",
}


SYSTEM_PROMPT = """You are one role in a forked Mako subagent orchestration.

Each role receives the same project context and same task, then returns an independent structured review.
This orchestration is advisory only: do not execute experiments, do not modify strategy code, and do not mutate project data.

Return JSON only, with this exact shape:
{
  "role": "researcher|auditor|data_engineer",
  "verdict": "APPROVE|NEEDS_WORK|REJECT",
  "summary": "one concise paragraph",
  "findings": ["specific finding", "..."],
  "allowed_safe_actions": ["read-only/audit/reporting action that may be queued now", "..."],
  "blocked_material_actions": ["experiment/data mutation/strategy execution action that must stay blocked", "..."],
  "required_evidence": ["evidence artifact, hash, data check, approval, or validation needed before material action", "..."],
  "required_actions": ["specific required action", "..."]
}

Verdict guidance:
- APPROVE means the task is sufficiently researched/audited/prepared as an advisory step.
- NEEDS_WORK means more evidence, checks, or clarification are required.
- REJECT means the task is unsafe, invalid, or materially unsupported.
"""


def run_role_orchestration(project: Path | str, task: str, model: str = "gpt-5.5") -> OrchestrationResult:
    """Run fixed Mako roles in parallel against one context and task."""
    project_path = Path(project)
    pack = build_context_pack(project_path, task=task)
    prompt = _user_prompt(pack.text, task)

    results_by_role: dict[str, RoleResult] = {}
    with ThreadPoolExecutor(max_workers=len(ROLES)) as executor:
        futures = {
            executor.submit(_run_role, project_path, role, prompt, model): role
            for role in ROLES
        }
        for future in as_completed(futures):
            role = futures[future]
            try:
                results_by_role[role] = future.result()
            except Exception as exc:  # pragma: no cover - defensive boundary
                results_by_role[role] = RoleResult(
                    role=role,
                    verdict=NEEDS_WORK,
                    summary="Role orchestration failed before producing a structured result.",
                    findings=[f"{type(exc).__name__}: {exc}"],
                    allowed_safe_actions=[],
                    blocked_material_actions=[
                        "material actions blocked because one role failed to produce a structured result"
                    ],
                    required_evidence=["successful structured rerun for the failed role"],
                    required_actions=["Retry the role after resolving the orchestration error."],
                    usage={},
                )

    return OrchestrationResult(
        project=project_path,
        task=task,
        model=model,
        created_at=datetime.now().isoformat(timespec="seconds"),
        context_summary=f"{pack.budget_summary()}; {pack.source_summary()}",
        results=tuple(results_by_role[role] for role in ROLES),
    )


def render_orchestration_markdown(result: OrchestrationResult) -> str:
    lines = [
        "# Mako Role Orchestration",
        "",
        f"- created_at: {result.created_at}",
        f"- project: {result.project}",
        f"- model: {result.model}",
        f"- task: {result.task}",
        f"- overall_verdict: {result.verdict}",
        f"- context: {result.context_summary}",
        "",
        "## Role Results",
        "",
    ]
    for role_result in result.results:
        lines.extend(
            [
                f"### {role_result.role}",
                "",
                f"- verdict: {role_result.verdict}",
                f"- summary: {role_result.summary}",
                f"- usage: {_format_usage(role_result.usage)}",
                "",
                "Findings:",
            ]
        )
        lines.extend(_bullet_lines(role_result.findings))
        lines.extend(["", "Allowed safe actions:"])
        lines.extend(_bullet_lines(role_result.allowed_safe_actions))
        lines.extend(["", "Blocked material actions:"])
        lines.extend(_bullet_lines(role_result.blocked_material_actions))
        lines.extend(["", "Required evidence:"])
        lines.extend(_bullet_lines(role_result.required_evidence))
        lines.extend(["", "Required actions:"])
        lines.extend(_bullet_lines(role_result.required_actions))
        lines.append("")
    lines.extend(["## Machine Readable Summary", "", "Role consensus:"])
    lines.append(f"```json\n{json.dumps(result.role_consensus, ensure_ascii=False, indent=2)}\n```")
    lines.extend(["", "Role conflicts:"])
    lines.append(f"```json\n{json.dumps(result.role_conflicts, ensure_ascii=False, indent=2)}\n```")
    return "\n".join(lines).rstrip() + "\n"


def _run_role(project: Path, role: str, prompt: str, model: str) -> RoleResult:
    client = ModelClient()
    response = client.complete(
        ModelRequest(
            model=model,
            system=SYSTEM_PROMPT + "\n\n" + ROLE_INSTRUCTIONS[role],
            prompt=prompt,
            project=str(project),
        )
    )
    if not response.ok:
        return RoleResult(
            role=role,
            verdict=NEEDS_WORK,
            summary="Model call failed; treating the role as needing work.",
            findings=[response.error or "Unknown model client error."],
            allowed_safe_actions=[],
            blocked_material_actions=["material actions blocked until model connectivity or provider configuration is fixed"],
            required_evidence=["successful structured role response after provider connectivity is restored"],
            required_actions=["Fix model connectivity or provider configuration, then rerun orchestration."],
            usage=response.usage,
        )
    return _parse_role_result(role, response.text, response.usage)


def _user_prompt(context: str, task: str) -> str:
    return f"""Project context:
{context}

Task:
{task}

Remember: advisory review only. Do not execute experiments, change strategy code, or mutate data.
Return JSON only.
"""


def _parse_role_result(role: str, text: str, usage: dict[str, Any]) -> RoleResult:
    try:
        payload = _load_json_object(text)
    except ValueError as exc:
        return RoleResult(
            role=role,
            verdict=NEEDS_WORK,
            summary="Model returned an unparseable structured result.",
            findings=[f"{exc}", f"response_preview: {text[:500]}"],
            allowed_safe_actions=[],
            blocked_material_actions=["material actions blocked because this role did not return valid JSON"],
            required_evidence=["valid JSON role response containing findings, actions, blockers, and evidence"],
            required_actions=["Rerun the role and require valid JSON output."],
            usage=usage,
        )

    parsed_role = str(payload.get("role") or role).strip().lower()
    if parsed_role not in ROLES:
        parsed_role = role

    verdict = str(payload.get("verdict") or NEEDS_WORK).strip().upper()
    required_actions = _string_list(payload.get("required_actions"))
    findings = _string_list(payload.get("findings"))
    if verdict not in VERDICTS:
        findings.append(f"Invalid verdict returned by model: {verdict}")
        required_actions.append("Return one of APPROVE, NEEDS_WORK, or REJECT.")
        verdict = NEEDS_WORK

    summary = str(payload.get("summary") or "No summary returned.").strip()
    return RoleResult(
        role=parsed_role,
        verdict=verdict,
        summary=summary,
        findings=findings,
        allowed_safe_actions=_string_list(payload.get("allowed_safe_actions")),
        blocked_material_actions=_string_list(payload.get("blocked_material_actions")),
        required_evidence=_string_list(payload.get("required_evidence")),
        required_actions=required_actions,
        usage=usage,
    )


def build_role_consensus(results: tuple[RoleResult, ...], overall_verdict: str) -> dict[str, Any]:
    verdict_counts = {verdict: 0 for verdict in sorted(VERDICTS)}
    role_verdicts: dict[str, str] = {}
    for result in results:
        verdict_counts[result.verdict] = verdict_counts.get(result.verdict, 0) + 1
        role_verdicts[result.role] = result.verdict

    return {
        "overall_verdict": overall_verdict,
        "unanimous_verdict": len({result.verdict for result in results}) == 1,
        "role_verdicts": role_verdicts,
        "verdict_counts": verdict_counts,
        "shared_allowed_safe_actions": _shared_items(results, "allowed_safe_actions"),
        "shared_blocked_material_actions": _shared_items(results, "blocked_material_actions"),
        "shared_required_evidence": _shared_items(results, "required_evidence"),
        "role_action_counts": {
            result.role: {
                "allowed_safe_actions": len(result.allowed_safe_actions),
                "blocked_material_actions": len(result.blocked_material_actions),
                "required_evidence": len(result.required_evidence),
                "required_actions": len(result.required_actions),
            }
            for result in results
        },
    }


def build_role_conflicts(results: tuple[RoleResult, ...]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    verdicts = {result.verdict for result in results}
    if len(verdicts) > 1:
        conflicts.append(
            {
                "type": "verdict_disagreement",
                "roles": {result.role: result.verdict for result in results},
                "detail": "Roles did not return the same verdict.",
            }
        )

    approve_roles = [result.role for result in results if result.verdict == APPROVE]
    evidence_roles = [result.role for result in results if result.required_evidence]
    blocker_roles = [result.role for result in results if result.blocked_material_actions]
    if approve_roles and (evidence_roles or blocker_roles):
        conflicts.append(
            {
                "type": "approval_vs_blockers",
                "roles": {
                    "approve": approve_roles,
                    "required_evidence": evidence_roles,
                    "blocked_material_actions": blocker_roles,
                },
                "detail": "At least one role approved while another role still requires evidence or blocks material action.",
            }
        )

    allowed_index = _item_role_index(results, "allowed_safe_actions")
    blocked_index = _item_role_index(results, "blocked_material_actions")
    overlaps = sorted(set(allowed_index).intersection(blocked_index))
    for item in overlaps:
        conflicts.append(
            {
                "type": "action_classification_conflict",
                "action": item,
                "roles": {
                    "allowed_safe_actions": sorted(allowed_index[item]),
                    "blocked_material_actions": sorted(blocked_index[item]),
                },
                "detail": "The same normalized action appears as both allowed and blocked.",
            }
        )
    return conflicts


def _load_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    decoder = json.JSONDecoder()
    for index, char in enumerate(cleaned):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise ValueError("No JSON object found in model response.")


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _shared_items(results: tuple[RoleResult, ...], attr: str) -> list[dict[str, Any]]:
    index = _item_role_index(results, attr)
    shared = []
    for item, roles in sorted(index.items()):
        if len(roles) >= 2:
            shared.append({"item": item, "roles": sorted(roles)})
    return shared


def _item_role_index(results: tuple[RoleResult, ...], attr: str) -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    for result in results:
        for value in getattr(result, attr):
            normalized = _normalize_item(value)
            if normalized:
                index.setdefault(normalized, set()).add(result.role)
    return index


def _normalize_item(value: str) -> str:
    return " ".join(str(value).strip().lower().split())


def _bullet_lines(values: list[str]) -> list[str]:
    if not values:
        return ["- none"]
    return [f"- {value}" for value in values]


def _format_usage(usage: dict[str, Any]) -> str:
    if not usage:
        return "tokens: unavailable"
    prompt = usage.get("prompt_tokens") or usage.get("input_tokens")
    completion = usage.get("completion_tokens") or usage.get("output_tokens")
    total = usage.get("total_tokens")
    parts = []
    if prompt is not None:
        parts.append(f"input={prompt}")
    if completion is not None:
        parts.append(f"output={completion}")
    if total is not None:
        parts.append(f"total={total}")
    return "tokens: " + (", ".join(parts) if parts else str(usage))
