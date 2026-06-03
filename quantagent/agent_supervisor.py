from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .mode_router import route_agent_mode
from .quant_priority import is_quant_task
from .quant_run_gate import requires_live_quant_evidence, requires_quant_run_gate
from .subagents import SubagentRecord, refresh_subagents, start_subagent
from .task_state import ABORTED, BLOCKED, FAILED, LOST, PASSED, RUNNING, add_task, task_dir, update_task


TERMINAL = {PASSED, FAILED, ABORTED, BLOCKED, LOST}


@dataclass(frozen=True)
class SupervisorSubagentSpec:
    role: str
    task: str
    agent_profile: str
    node_id: str = ""
    depends_on: tuple[str, ...] = ()
    repair_for: str = ""
    context_mode: str = "fork"
    isolate_worktree: bool = False
    include_validation: bool = False
    required: bool = True
    reason: str = ""
    tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["depends_on"] = list(self.depends_on)
        payload["tools"] = list(self.tools)
        payload["disallowed_tools"] = list(self.disallowed_tools)
        return payload


@dataclass(frozen=True)
class SupervisorLaunch:
    role: str
    ok: bool
    node_id: str = ""
    subagent_id: str = ""
    child_task_id: str = ""
    child_session_id: str = ""
    status: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentSupervisorRun:
    supervisor_id: str
    project: str
    task: str
    action: str
    ok: bool
    parent_task_id: str = ""
    route: dict[str, Any] = field(default_factory=dict)
    plan: tuple[SupervisorSubagentSpec, ...] = ()
    launches: tuple[SupervisorLaunch, ...] = ()
    node_status: dict[str, str] = field(default_factory=dict)
    terminal: bool = False
    summary: str = ""
    warnings: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "supervisor_id": self.supervisor_id,
            "project": self.project,
            "task": self.task,
            "action": self.action,
            "ok": self.ok,
            "parent_task_id": self.parent_task_id,
            "route": self.route,
            "plan": [item.to_dict() for item in self.plan],
            "launches": [item.to_dict() for item in self.launches],
            "node_status": self.node_status,
            "terminal": self.terminal,
            "summary": self.summary,
            "warnings": list(self.warnings),
            "artifacts": list(self.artifacts),
            "created_at": self.created_at,
        }


def build_supervisor_plan(
    project: str | Path,
    task: str,
    *,
    include_validation: bool = True,
    changed_paths: Iterable[str | Path] = (),
) -> tuple[SupervisorSubagentSpec, ...]:
    project_path = Path(project).expanduser().resolve(strict=False)
    paths = tuple(str(path).replace("\\", "/").strip().lstrip("./") for path in changed_paths if str(path).strip())
    route = route_agent_mode(project_path, task, changed_paths=paths, input_provenance="agent-supervisor")
    quant = is_quant_task(task) or requires_quant_run_gate(task) or requires_live_quant_evidence(task)
    needs_code = route.mode in {"build", "repair"} or bool(paths)
    needs_review = route.mode in {"build", "repair", "review"} or quant

    specs: list[SupervisorSubagentSpec] = [
        SupervisorSubagentSpec(
            role="researcher",
            task=_role_task(
                "researcher",
                task,
                "Inspect the codebase and evidence. Return compact JSON with relevant_files, risks, blockers, and next_actions. Do not edit files.",
            ),
            agent_profile="audit",
            node_id="researcher",
            context_mode="fork",
            include_validation=False,
            reason="read-only context scout before any write agent",
            tools=("status", "context", "audit", "file_read", "file_search"),
            disallowed_tools=("edit", "file_write", "file_edit", "apply_patch", "shell"),
        )
    ]
    if needs_code:
        specs.append(
            SupervisorSubagentSpec(
                role="coder",
                task=_role_task(
                    "coder",
                    task,
                    "Implement the smallest useful change in an isolated worktree. Return JSON with changed_paths, tests_run, risks, and blockers.",
                ),
                agent_profile="build",
                node_id="coder",
                depends_on=("researcher",),
                context_mode="isolated",
                isolate_worktree=True,
                include_validation=include_validation,
                reason="bounded implementation in an isolated workspace",
                tools=("status", "context", "audit", "validate", "file_read", "file_search", "edit", "shell"),
            )
        )
    if quant:
        specs.append(
            SupervisorSubagentSpec(
                role="quant-execution",
                task=_role_task(
                    "quant-execution",
                    task,
                    "Run quant evidence discovery/gates where applicable. Return JSON with research_ready, live_ready, evidence_paths, blockers, and verdict.",
                ),
                agent_profile="quant-auditor",
                node_id="quant-execution",
                depends_on=("researcher",),
                context_mode="fork",
                include_validation=False,
                reason="domain evidence gate for quant claims",
                tools=("status", "context", "audit", "validate", "file_read", "file_search"),
                disallowed_tools=("edit", "file_write", "file_edit", "apply_patch", "shell"),
            )
        )
    if include_validation and needs_review:
        verifier_deps = ["researcher"]
        if needs_code:
            verifier_deps.append("coder")
        if quant:
            verifier_deps.append("quant-execution")
        specs.append(
            SupervisorSubagentSpec(
                role="verifier",
                task=_role_task(
                    "verifier",
                    task,
                    "Verify child outputs and project evidence. Run safe validation if available. Return JSON with pass_fail, tests, residual_risks, and required_followups.",
                ),
                agent_profile="audit",
                node_id="verifier",
                depends_on=tuple(verifier_deps),
                context_mode="fork",
                include_validation=False,
                reason="independent read-only verification pass",
                tools=("status", "context", "audit", "validate", "file_read", "file_search"),
                disallowed_tools=("edit", "file_write", "file_edit", "apply_patch"),
            )
        )
    return tuple(specs)


def run_agent_supervisor(
    project: str | Path,
    task: str,
    *,
    include_validation: bool = True,
    changed_paths: Iterable[str | Path] = (),
    plan_only: bool = False,
) -> AgentSupervisorRun:
    project_path = Path(project).expanduser().resolve(strict=False)
    route = route_agent_mode(project_path, task, changed_paths=tuple(str(path) for path in changed_paths), input_provenance="agent-supervisor")
    plan = build_supervisor_plan(project_path, task, include_validation=include_validation, changed_paths=changed_paths)
    supervisor_id = "asup-" + str(int(time.time() * 1000))
    parent = add_task(
        project_path,
        f"agent supervisor: {task[:80]}",
        detail=f"roles={','.join(item.role for item in plan)} route={route.mode}",
        status=PASSED if plan_only else RUNNING,
    )

    launches: list[SupervisorLaunch] = []
    warnings: list[str] = []
    if not plan_only:
        launches, warnings = _launch_ready_nodes(project_path, parent.id, task, plan, launches=(), records=())
    ok = not any(not launch.ok for launch in launches) if launches else True
    if not plan_only:
        update_task(
            project_path,
            parent.id,
            status=RUNNING if ok else FAILED,
            note=f"supervisor launched {sum(1 for launch in launches if launch.ok)}/{len(plan)} ready subagents",
        )
    run = AgentSupervisorRun(
        supervisor_id=supervisor_id,
        project=str(project_path),
        task=task,
        action="plan" if plan_only else "launch",
        ok=ok,
        parent_task_id=parent.id,
        route=route.to_dict(),
        plan=plan,
        launches=tuple(launches),
        node_status=_node_status(plan, launches, ()),
        terminal=plan_only,
        summary=_supervisor_summary(plan, launches, (), terminal=plan_only),
        warnings=tuple(warnings),
    )
    path = save_agent_supervisor_run(project_path, run)
    return AgentSupervisorRun(
        supervisor_id=run.supervisor_id,
        project=run.project,
        task=run.task,
        action=run.action,
        ok=run.ok,
        parent_task_id=run.parent_task_id,
        route=run.route,
        plan=run.plan,
        launches=run.launches,
        node_status=run.node_status,
        terminal=run.terminal,
        summary=run.summary,
        warnings=run.warnings,
        artifacts=(str(path),),
        created_at=run.created_at,
    )


def refresh_agent_supervisor(project: str | Path, parent_task_id: str = "") -> AgentSupervisorRun | None:
    project_path = Path(project).expanduser().resolve(strict=False)
    records = refresh_subagents(project_path)
    runs = load_agent_supervisor_runs(project_path)
    if not parent_task_id and runs:
        parent_task_id = runs[-1].parent_task_id
    for run in reversed(runs):
        if run.parent_task_id == parent_task_id:
            plan = list(run.plan)
            launches = _refresh_launch_statuses(run.launches, records)
            for spec in list(plan):
                node_id = _spec_node(spec)
                if spec.repair_for or _has_repair_for(plan, node_id):
                    continue
                if spec.required and _raw_node_status(node_id, launches, records) in {FAILED, ABORTED, BLOCKED, "launch_failed"}:
                    plan.append(_repair_spec(spec, run.task))
            new_launches, new_warnings = _launch_ready_nodes(project_path, run.parent_task_id, run.task, plan, launches=launches, records=records)
            warnings = tuple(dict.fromkeys([*run.warnings, *new_warnings]))
            status, terminal, ok = _terminal_state(plan, new_launches, records)
            try:
                update_task(
                    project_path,
                    run.parent_task_id,
                    status=status,
                    note=f"supervisor refresh: {status}",
                )
            except KeyError:
                pass
            refreshed = AgentSupervisorRun(
                supervisor_id=run.supervisor_id,
                project=run.project,
                task=run.task,
                action="refresh",
                ok=ok,
                parent_task_id=run.parent_task_id,
                route=run.route,
                plan=tuple(plan),
                launches=tuple(new_launches),
                node_status=_node_status(plan, new_launches, records),
                terminal=terminal,
                summary=_supervisor_summary(plan, new_launches, records, terminal=terminal),
                warnings=warnings,
                artifacts=run.artifacts,
                created_at=run.created_at,
            )
            path = save_agent_supervisor_run(project_path, refreshed)
            return AgentSupervisorRun(
                supervisor_id=refreshed.supervisor_id,
                project=refreshed.project,
                task=refreshed.task,
                action=refreshed.action,
                ok=refreshed.ok,
                parent_task_id=refreshed.parent_task_id,
                route=refreshed.route,
                plan=refreshed.plan,
                launches=refreshed.launches,
                node_status=refreshed.node_status,
                terminal=refreshed.terminal,
                summary=refreshed.summary,
                warnings=refreshed.warnings,
                artifacts=tuple(dict.fromkeys([*refreshed.artifacts, str(path)])),
                created_at=refreshed.created_at,
            )
    return None


def get_agent_supervisor_run(project: str | Path, supervisor_id: str = "") -> AgentSupervisorRun | None:
    runs = load_agent_supervisor_runs(project)
    if not runs:
        return None
    if not supervisor_id:
        return runs[-1]
    for run in reversed(runs):
        if run.supervisor_id == supervisor_id:
            return run
    raise KeyError(f"agent supervisor run not found: {supervisor_id}")


def supervisor_store_path(project: str | Path) -> Path:
    return task_dir(Path(project).expanduser().resolve(strict=False)) / "agent_supervisor_runs.json"


def load_agent_supervisor_runs(project: str | Path) -> list[AgentSupervisorRun]:
    path = supervisor_store_path(project)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_runs = payload.get("runs", []) if isinstance(payload, dict) else []
    return [_run_from_dict(item) for item in raw_runs if isinstance(item, dict)]


def save_agent_supervisor_run(project: str | Path, run: AgentSupervisorRun) -> Path:
    project_path = Path(project).expanduser().resolve(strict=False)
    runs = [item for item in load_agent_supervisor_runs(project_path) if item.supervisor_id != run.supervisor_id]
    runs.append(run)
    path = supervisor_store_path(project_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"runs": [item.to_dict() for item in runs]}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def render_agent_supervisor_run(run: AgentSupervisorRun) -> str:
    lines = [
        "# Agent Supervisor",
        "",
        f"- supervisor_id: {run.supervisor_id}",
        f"- action: {run.action}",
        f"- ok: {str(run.ok).lower()}",
        f"- terminal: {str(run.terminal).lower()}",
        f"- parent_task_id: {run.parent_task_id or '-'}",
        f"- route: {run.route.get('mode') or '-'}",
        f"- roles: {', '.join(item.role for item in run.plan) or '-'}",
        f"- summary: {run.summary or '-'}",
        "",
        "## Plan",
        "",
    ]
    for spec in run.plan:
        iso = " isolated" if spec.isolate_worktree else ""
        deps = ",".join(spec.depends_on) if spec.depends_on else "-"
        repair = f" repair_for={spec.repair_for}" if spec.repair_for else ""
        lines.append(f"- {_spec_node(spec)}: role={spec.role} profile={spec.agent_profile} context={spec.context_mode}{iso} deps={deps} required={str(spec.required).lower()}{repair}")
        if spec.reason:
            lines.append(f"  reason: {spec.reason}")
    lines.extend(["", "## Node Status", ""])
    if run.node_status:
        lines.extend(f"- {node}: {status}" for node, status in sorted(run.node_status.items()))
    else:
        lines.append("- none")
    lines.extend(["", "## Launches", ""])
    if not run.launches:
        lines.append("- none")
    for launch in run.launches:
        status = launch.status or ("ok" if launch.ok else "failed")
        detail = launch.subagent_id or launch.error or "-"
        lines.append(f"- {launch.role}: {status} {detail}")
    if run.warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {item}" for item in run.warnings)
    if run.artifacts:
        lines.extend(["", "## Artifacts", ""])
        lines.extend(f"- {item}" for item in run.artifacts)
    return "\n".join(lines).rstrip() + "\n"


def _launch_ready_nodes(
    project: Path,
    parent_task_id: str,
    task: str,
    plan: Iterable[SupervisorSubagentSpec],
    *,
    launches: Iterable[SupervisorLaunch],
    records: Iterable[SubagentRecord],
) -> tuple[list[SupervisorLaunch], list[str]]:
    specs = list(plan)
    result = list(launches)
    warnings: list[str] = []
    launched = {_launch_node(launch): launch for launch in result}
    record_list = list(records)
    for spec in specs:
        node_id = _spec_node(spec)
        if node_id in launched:
            continue
        if not all(_effective_ok(dep, specs, result, record_list) for dep in spec.depends_on):
            continue
        try:
            record = start_subagent(
                project,
                spec.task,
                parent_task_id=parent_task_id,
                context_mode=spec.context_mode,
                title=f"{spec.role}: {task[:60]}",
                include_validation=spec.include_validation,
                agent_profile=spec.agent_profile,
                tools=spec.tools,
                disallowed_tools=spec.disallowed_tools,
                isolate_worktree=spec.isolate_worktree,
            )
            launch = _launch_from_record(spec, record)
        except (OSError, ValueError, KeyError) as exc:
            launch = SupervisorLaunch(role=spec.role, node_id=node_id, ok=False, error=f"{type(exc).__name__}: {exc}", status="launch_failed")
            if spec.required:
                warnings.append(f"{node_id} launch failed: {exc}")
        result.append(launch)
        launched[node_id] = launch
    return result, warnings


def _refresh_launch_statuses(launches: Iterable[SupervisorLaunch], records: Iterable[SubagentRecord]) -> list[SupervisorLaunch]:
    by_subagent = {record.subagent_id: record for record in records}
    refreshed: list[SupervisorLaunch] = []
    for launch in launches:
        record = by_subagent.get(launch.subagent_id)
        if not record:
            refreshed.append(launch)
            continue
        refreshed.append(
            SupervisorLaunch(
                role=launch.role,
                ok=launch.ok,
                node_id=launch.node_id,
                subagent_id=launch.subagent_id,
                child_task_id=launch.child_task_id,
                child_session_id=launch.child_session_id,
                status=record.status,
                error=launch.error,
            )
        )
    return refreshed


def _repair_spec(spec: SupervisorSubagentSpec, task: str) -> SupervisorSubagentSpec:
    node_id = _spec_node(spec)
    return SupervisorSubagentSpec(
        role="repair-" + spec.role,
        node_id="repair-" + node_id,
        repair_for=node_id,
        depends_on=spec.depends_on,
        task=_role_task(
            "repair-" + spec.role,
            task,
            f"The supervisor detected failed node {node_id}. Inspect its artifacts, repair the smallest cause in an isolated worktree, and return JSON with fixed, changed_paths, tests_run, blockers, and residual_risks.",
        ),
        agent_profile="build",
        context_mode="isolated",
        isolate_worktree=True,
        include_validation=True,
        required=True,
        reason=f"automatic repair for failed node {node_id}",
        tools=("status", "context", "audit", "validate", "file_read", "file_search", "edit", "shell"),
    )


def _terminal_state(
    plan: Iterable[SupervisorSubagentSpec],
    launches: Iterable[SupervisorLaunch],
    records: Iterable[SubagentRecord],
) -> tuple[str, bool, bool]:
    specs = list(plan)
    launch_list = list(launches)
    record_list = list(records)
    statuses = _node_status(specs, launch_list, record_list)
    if any(status == RUNNING for status in statuses.values()):
        return RUNNING, False, True
    required = [spec for spec in specs if spec.required]
    if required and all(_effective_ok(_spec_node(spec), specs, launch_list, record_list) for spec in required):
        return PASSED, True, True
    failed = [
        spec
        for spec in required
        if _raw_node_status(_spec_node(spec), launch_list, record_list) in {FAILED, ABORTED, BLOCKED, "launch_failed"}
        and not _effective_ok(_spec_node(spec), specs, launch_list, record_list)
    ]
    if failed:
        return FAILED, True, False
    return RUNNING, False, True


def _node_status(
    plan: Iterable[SupervisorSubagentSpec],
    launches: Iterable[SupervisorLaunch],
    records: Iterable[SubagentRecord],
) -> dict[str, str]:
    specs = list(plan)
    launch_list = list(launches)
    record_list = list(records)
    statuses: dict[str, str] = {}
    for spec in specs:
        node_id = _spec_node(spec)
        raw = _raw_node_status(node_id, launch_list, record_list)
        if raw in {FAILED, ABORTED, BLOCKED, "launch_failed"} and _effective_ok(node_id, specs, launch_list, record_list):
            raw = "repaired"
        elif raw == "pending" and spec.depends_on:
            raw = "ready" if all(_effective_ok(dep, specs, launch_list, record_list) for dep in spec.depends_on) else "waiting"
        statuses[node_id] = raw
    return statuses


def _supervisor_summary(
    plan: Iterable[SupervisorSubagentSpec],
    launches: Iterable[SupervisorLaunch],
    records: Iterable[SubagentRecord],
    *,
    terminal: bool,
) -> str:
    statuses = _node_status(plan, launches, records)
    counts: dict[str, int] = {}
    for status in statuses.values():
        counts[status] = counts.get(status, 0) + 1
    rendered = ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "none"
    suffix = "terminal" if terminal else "active"
    return f"{len(statuses)} DAG node(s); {rendered}; {suffix}"


def _effective_ok(
    node_id: str,
    plan: Iterable[SupervisorSubagentSpec],
    launches: Iterable[SupervisorLaunch],
    records: Iterable[SubagentRecord],
) -> bool:
    specs = list(plan)
    if _raw_node_status(node_id, launches, records) == PASSED:
        return True
    for spec in specs:
        if spec.repair_for == node_id and _raw_node_status(_spec_node(spec), launches, records) == PASSED:
            return True
    return False


def _raw_node_status(
    node_id: str,
    launches: Iterable[SupervisorLaunch],
    records: Iterable[SubagentRecord],
) -> str:
    record_by_subagent = {record.subagent_id: record for record in records}
    for launch in launches:
        if _launch_node(launch) != node_id:
            continue
        if not launch.ok:
            return launch.status or "launch_failed"
        record = record_by_subagent.get(launch.subagent_id)
        return record.status if record else (launch.status or RUNNING)
    return "pending"


def _has_repair_for(plan: Iterable[SupervisorSubagentSpec], node_id: str) -> bool:
    return any(spec.repair_for == node_id for spec in plan)


def _spec_node(spec: SupervisorSubagentSpec) -> str:
    return spec.node_id or spec.role


def _launch_node(launch: SupervisorLaunch) -> str:
    return launch.node_id or launch.role


def _role_task(role: str, task: str, instruction: str) -> str:
    return "\n".join(
        [
            f"Role: {role}",
            instruction,
            "Use clean evidence. Do not invent outcomes.",
            "",
            "Supervisor task:",
            task,
        ]
    )


def _launch_from_record(spec: SupervisorSubagentSpec, record: SubagentRecord) -> SupervisorLaunch:
    return SupervisorLaunch(
        role=spec.role,
        ok=True,
        node_id=_spec_node(spec),
        subagent_id=record.subagent_id,
        child_task_id=record.child_task_id,
        child_session_id=record.child_session_id,
        status=record.status,
    )


def _run_from_dict(payload: dict[str, Any]) -> AgentSupervisorRun:
    return AgentSupervisorRun(
        supervisor_id=str(payload.get("supervisor_id") or ""),
        project=str(payload.get("project") or ""),
        task=str(payload.get("task") or ""),
        action=str(payload.get("action") or ""),
        ok=bool(payload.get("ok")),
        parent_task_id=str(payload.get("parent_task_id") or ""),
        route=dict(payload.get("route") or {}),
        plan=tuple(_spec_from_dict(item) for item in payload.get("plan") or () if isinstance(item, dict)),
        launches=tuple(_launch_from_dict_payload(item) for item in payload.get("launches") or () if isinstance(item, dict)),
        node_status={str(key): str(value) for key, value in dict(payload.get("node_status") or {}).items()},
        terminal=bool(payload.get("terminal")),
        summary=str(payload.get("summary") or ""),
        warnings=tuple(str(item) for item in payload.get("warnings") or ()),
        artifacts=tuple(str(item) for item in payload.get("artifacts") or ()),
        created_at=str(payload.get("created_at") or datetime.now().isoformat(timespec="seconds")),
    )


def _spec_from_dict(payload: dict[str, Any]) -> SupervisorSubagentSpec:
    return SupervisorSubagentSpec(
        role=str(payload.get("role") or ""),
        task=str(payload.get("task") or ""),
        agent_profile=str(payload.get("agent_profile") or ""),
        node_id=str(payload.get("node_id") or ""),
        depends_on=tuple(str(item) for item in payload.get("depends_on") or ()),
        repair_for=str(payload.get("repair_for") or ""),
        context_mode=str(payload.get("context_mode") or "fork"),
        isolate_worktree=bool(payload.get("isolate_worktree")),
        include_validation=bool(payload.get("include_validation")),
        required=bool(payload.get("required", True)),
        reason=str(payload.get("reason") or ""),
        tools=tuple(str(item) for item in payload.get("tools") or ()),
        disallowed_tools=tuple(str(item) for item in payload.get("disallowed_tools") or ()),
    )


def _launch_from_dict_payload(payload: dict[str, Any]) -> SupervisorLaunch:
    return SupervisorLaunch(
        role=str(payload.get("role") or ""),
        ok=bool(payload.get("ok")),
        node_id=str(payload.get("node_id") or ""),
        subagent_id=str(payload.get("subagent_id") or ""),
        child_task_id=str(payload.get("child_task_id") or ""),
        child_session_id=str(payload.get("child_session_id") or ""),
        status=str(payload.get("status") or ""),
        error=str(payload.get("error") or ""),
    )
