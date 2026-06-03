from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .consensus import load_consensus_status
from .orchestrator import OrchestrationResult, render_orchestration_markdown, run_role_orchestration
from .quant_checks import audit_project
from .state import write_project_state
from .validation import validate_project_scripts


@dataclass
class AutoRunResult:
    task: str
    stage: str
    safe_actions_done: list[str]
    blocked_material_actions: list[str]
    audit_ok: bool
    validation_ok: bool
    next_action_queue: dict[str, list[dict[str, Any]]]
    role_consensus: dict[str, Any]
    role_conflicts: list[dict[str, Any]]
    orchestration: dict
    markdown_path: str
    json_path: str


def infer_next_task(project: Path) -> str:
    comm = project / "AI_协作交接"
    if (comm / "39_PRE_TICK_READY_CONTROL_PANEL.md").exists():
        return (
            "Pre-tick readiness loop: verify current P4 readiness, identify what can be done "
            "before tick data arrives, and list exact blockers for real 09:30 execution validation."
        )
    return "Review project state and propose the safest next quant research action."


def infer_stage(project: Path) -> str:
    comm = project / "AI_协作交接"
    if (comm / "39_PRE_TICK_READY_CONTROL_PANEL.md").exists():
        return "pre_tick_ready_waiting_for_tick_data"
    return "unknown"


def run_next(
    project: Path,
    task: str | None = None,
    model: str = "gpt-5.5",
) -> AutoRunResult:
    selected_task = task or infer_next_task(project)
    stage = infer_stage(project)

    safe_actions_done: list[str] = []
    blocked_material_actions: list[str] = []

    md_state, json_state = write_project_state(project)
    safe_actions_done.append(f"updated project state: {md_state.name}, {json_state.name}")

    audit_findings = audit_project(project)
    audit_ok = not any(finding.level == "error" for finding in audit_findings)
    safe_actions_done.append("ran project audit")

    validations = validate_project_scripts(project)
    validation_ok = all(item.ok for item in validations)
    safe_actions_done.append("ran script validation")

    consensus = load_consensus_status(project)
    if not consensus or not consensus.all_approved:
        blocked_material_actions.append(
            "material experiments/P4 execution/automatic data mutation blocked until three-pass ChatGPT consistency approval"
        )
    else:
        blocked_material_actions.append("material actions still require task-specific consensus, exact command, explicit dedup input, and evidence lock")

    orchestration = run_role_orchestration(project, selected_task, model=model)
    next_action_queue = build_next_action_queue(
        orchestration=orchestration,
        audit_ok=audit_ok,
        validation_ok=validation_ok,
        consensus=consensus,
    )
    out_dir = project / "AI_协作交接"
    if not out_dir.exists():
        out_dir = project
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = out_dir / f"AUTO_RUN_{stamp}.md"
    json_path = out_dir / f"AUTO_RUN_{stamp}.json"

    result = AutoRunResult(
        task=selected_task,
        stage=stage,
        safe_actions_done=safe_actions_done,
        blocked_material_actions=blocked_material_actions,
        audit_ok=audit_ok,
        validation_ok=validation_ok,
        next_action_queue=next_action_queue,
        role_consensus=orchestration.role_consensus,
        role_conflicts=orchestration.role_conflicts,
        orchestration=orchestration_to_dict(orchestration),
        markdown_path=str(md_path),
        json_path=str(json_path),
    )

    md_path.write_text(render_auto_run_markdown(result, orchestration, audit_findings, validations), encoding="utf-8")
    json_path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def orchestration_to_dict(orchestration: OrchestrationResult) -> dict:
    data = asdict(orchestration)
    data["project"] = str(orchestration.project)
    data["overall_verdict"] = orchestration.verdict
    data["role_consensus"] = orchestration.role_consensus
    data["role_conflicts"] = orchestration.role_conflicts
    return data


def build_next_action_queue(
    orchestration: OrchestrationResult,
    audit_ok: bool,
    validation_ok: bool,
    consensus,
) -> dict[str, list[dict[str, Any]]]:
    queue: dict[str, list[dict[str, Any]]] = {
        "allowed_safe_actions": [
            _action_item(
                action="Review the generated AUTO_RUN markdown/json report and route safe follow-up work by owner_role.",
                owner_role="operator",
                source="auto_runner",
            ),
            _action_item(
                action="Keep work to read-only audits, validation probes, state/report writes, and evidence collection.",
                owner_role="auto_runner",
                source="guardrail",
            ),
        ],
        "blocked_material_actions": [
            _action_item(
                action="Do not execute material experiments, P4 real execution, strategy changes, or data mutation from run-next.",
                owner_role="operator",
                source="guardrail",
            )
        ],
        "required_evidence": [],
    }

    if not audit_ok:
        queue["required_evidence"].append(
            _evidence_item(
                evidence="Resolve local audit errors or document why each finding is non-material before any material action.",
                owner_role="auditor",
                source="local_audit",
            )
        )
    if not validation_ok:
        queue["required_evidence"].append(
            _evidence_item(
                evidence="Restore passing script validation or capture explicit skip/failure reasons before material action.",
                owner_role="data_engineer",
                source="validation",
            )
        )

    if not consensus or not consensus.all_approved:
        queue["blocked_material_actions"].append(
            _action_item(
                action="Material experiments/P4 execution/automatic data mutation remain blocked until three-pass ChatGPT consistency approval.",
                owner_role="operator",
                source="consensus_gate",
            )
        )
        queue["required_evidence"].append(
            _evidence_item(
                evidence="Three ChatGPT consistency replies with APPROVE for the exact material action.",
                owner_role="operator",
                source="consensus_gate",
            )
        )
    else:
        queue["required_evidence"].append(
            _evidence_item(
                evidence="Exact task-specific command, dedup input confirmation, and evidence-lock metadata for any material action.",
                owner_role="operator",
                source="consensus_gate",
            )
        )

    for role_result in orchestration.results:
        for action in role_result.allowed_safe_actions:
            queue["allowed_safe_actions"].append(
                _action_item(action=action, owner_role=role_result.role, source="role_orchestration")
            )
        for action in role_result.blocked_material_actions:
            queue["blocked_material_actions"].append(
                _action_item(action=action, owner_role=role_result.role, source="role_orchestration")
            )
        for evidence in role_result.required_evidence:
            queue["required_evidence"].append(
                _evidence_item(evidence=evidence, owner_role=role_result.role, source="role_orchestration")
            )

    return {key: _dedupe_items(values) for key, values in queue.items()}


def render_auto_run_markdown(result: AutoRunResult, orchestration: OrchestrationResult, audit_findings, validations) -> str:
    lines = [
        "# Mako Auto Run",
        "",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- stage: {result.stage}",
        f"- task: {result.task}",
        f"- audit_ok: {str(result.audit_ok).lower()}",
        f"- validation_ok: {str(result.validation_ok).lower()}",
        "",
        "## Next Action Queue",
        "",
        "### allowed_safe_actions",
    ]
    lines.extend(_queue_lines(result.next_action_queue["allowed_safe_actions"], "action"))
    lines.extend(["", "### blocked_material_actions"])
    lines.extend(_queue_lines(result.next_action_queue["blocked_material_actions"], "action"))
    lines.extend(["", "### required_evidence"])
    lines.extend(_queue_lines(result.next_action_queue["required_evidence"], "evidence"))
    lines.extend(
        [
            "",
            "```json",
            json.dumps(result.next_action_queue, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Role Consensus",
            "",
            "```json",
            json.dumps(result.role_consensus, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Role Conflicts",
            "",
            "```json",
            json.dumps(result.role_conflicts, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Safe Actions Done",
        ]
    )
    lines.extend(f"- {item}" for item in result.safe_actions_done)
    lines.extend(["", "## Blocked Material Actions"])
    lines.extend(f"- {item}" for item in result.blocked_material_actions)
    lines.extend(["", "## Local Audit"])
    if audit_findings:
        for finding in audit_findings:
            path = f" ({finding.path})" if finding.path else ""
            lines.append(f"- [{finding.level}] {finding.title}{path}: {finding.detail}")
    else:
        lines.append("- no audit findings")
    lines.extend(["", "## Validation"])
    for item in validations:
        status = "ok" if item.ok else "fail"
        lines.append(f"- [{status}] {item.name}: {item.detail}")
    lines.extend(["", render_orchestration_markdown(orchestration)])
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This auto run may read, audit, validate, and write reports.",
            "- It must not run material experiments or P4 execution without task-specific three-pass ChatGPT consistency approval.",
            "- All quant conclusions remain research candidates unless backed by evidence-locked results.",
        ]
    )
    return "\n".join(lines) + "\n"


def _action_item(action: str, owner_role: str, source: str) -> dict[str, Any]:
    return {
        "action": action,
        "owner_role": owner_role,
        "source": source,
    }


def _evidence_item(evidence: str, owner_role: str, source: str) -> dict[str, Any]:
    return {
        "evidence": evidence,
        "owner_role": owner_role,
        "source": source,
    }


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    deduped = []
    for item in items:
        text = str(item.get("action") or item.get("evidence") or "")
        key = (" ".join(text.lower().split()), str(item.get("owner_role")), str(item.get("source")))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _queue_lines(items: list[dict[str, Any]], text_key: str) -> list[str]:
    if not items:
        return ["- none"]
    return [
        f"- [{item['owner_role']}] {item[text_key]} (source: {item['source']})"
        for item in items
    ]
