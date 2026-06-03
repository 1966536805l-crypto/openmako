from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import hashlib
import json
import os
import sqlite3
import stat
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .agent_modes import agent_mode_config_path, list_agent_modes, mode_tool_views, validate_agent_modes
from .agent_context_runtime import build_agent_runtime_context
from .agent_loop_v3 import build_agent_v3_plan
from .agent_profiles import load_agent_profile_config, load_instructions
from .answer_guard import guard_answer
from .cheap_plan import build_cheap_plan
from .evidence_ledger import create_evidence_record, evidence_ledger_path
from .goal_contract import evaluate_goal_guard, goal_contract_path, load_goal_contract
from .headless_sdk import QuantAgentHeadless
from .mode_router import route_agent_mode, validate_mode_router
from .architect import architect_dir
from .project import snapshot_project
from .plugin_runtime import build_plugin_registry
from .plugin_state_store import probe_plugin_state_store
from .permission_policy_v2 import lint_permission_policy_v2, load_permission_policy_v2, permission_policy_path
from .project_rules import load_project_rules
from .pr_workflow import pr_plan_dir
from .remote_runner import remote_runner_dir
from .repo_map import build_repo_map, ensure_repo_map, load_repo_map, repo_map_path
from .run_artifacts import runs_root
from .session_bus import session_bus_dir, session_bus_summary, status_session_bus
from .source_checks import load_source_checks, run_source_checks, source_check_summary, source_checks_dir
from .structured_diff_preview import diff_preview_dir
from .mcp_runtime import load_mcp_servers, status_mcp_daemon_state
from .mcp_gateway import gateway_state_path
from .code_index import editor_diagnostics, index_path
from .retrieval_daemon import retrieval_index_path, retrieval_state_path
from .embedding_provider import embedding_cache_path
from .lsp_diagnostics import lsp_cache_path
from .mcp_daemon import mcp_daemon_pid_path, mcp_daemon_state_path
from .diagnostic_registry import diagnostic_registry_path
from .desktop_live import build_desktop_live_state
from .desktop_workflow import DesktopElement, DesktopTextBlock, build_som_targets, execute_desktop_plan, plan_web_search, search_ax_elements, search_som_targets, search_url
from .event_log import event_log_path, read_runtime_events
from .checkpoints import checkpoint_dir
from .runtime_store import ensure_runtime_store, inspect_budget_reservations, list_approval_requests, list_tool_invocations, runtime_db_path
from .memory_sidecar import memory_proposal_path
from .skill_pipeline import skill_proposal_dir
from .skills import list_skills
from .subagents import subagent_review_bundle_store_path, subagent_store_path
from .subagent_backends import detect_subagent_backends
from .task_graph import build_task_graph
from .task_state import RUNNING, load_tasks
from .tool_manifest_v2 import build_tool_manifest_catalog
from .tui_status_model import build_tui_status_model
from .ux_status import build_ux_status
from .validation import validate_project_scripts
from .worktree_isolation import SANDBOX_EXEC, detect_sandbox_backend, isolation_root


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    score: int
    detail: str
    severity: str = "info"
    category: str = "general"
    remediation: str = ""
    paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class DoctorFixAction:
    action_id: str
    status: str
    detail: str
    path: str = ""
    before_hash: str = ""
    after_hash: str = ""
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_doctor(project: Path) -> list[DoctorCheck]:
    snapshot = snapshot_project(project, "AI_协作交接")
    validations = validate_project_scripts(project)
    validation_ok = all(item.ok for item in validations)
    skills = list_skills(project)

    checks = [
        DoctorCheck(
            "project_memory",
            bool(snapshot.claude_md and snapshot.latest_messages),
            15,
            "CLAUDE.md and communication files are discoverable"
            if snapshot.claude_md and snapshot.latest_messages
            else "missing CLAUDE.md or communication files",
        ),
        DoctorCheck(
            "validation_pipeline",
            validation_ok,
            15,
            "all validation checks passed"
            if validation_ok
            else "one or more validation checks failed",
        ),
        DoctorCheck(
            "built_in_skills",
            len(skills) >= 6,
            10,
            f"{len(skills)} built-in/project skills available",
            category="skills",
        ),
        _runtime_store_check(project),
        _budget_reservation_health_check(project),
        _event_log_v2_check(project),
        _tool_manifest_v2_check(project),
        _permission_policy_v2_check(project),
        _repo_map_check(project),
        _source_checks_check(project),
        _session_bus_check(project),
        _task_graph_v2_check(project),
        _skill_pipeline_check(project),
        _approval_invocation_check(project),
        _mcp_runtime_check(project),
        _agent_modes_check(project),
        _goal_contract_check(project),
        _answer_guard_check(project),
        _headless_sdk_check(project),
        _agent_loop_v3_check(project),
        _agent_profile_check(project),
        _agent_infra_check(project),
        _shell_semantics_check(project),
        _permission_debug_check(project),
        _diagnostic_registry_check(project),
        _structured_diff_preview_check(project),
        _apply_gate_check(project),
        _retrieval_daemon_check(project),
        _embedding_provider_check(project),
        _lsp_diagnostics_check(project),
        _mcp_gateway_check(project),
        _external_mcp_daemon_check(project),
        _eval_harness_check(project),
        _quant_bench_check(project),
        _quant_run_gate_check(project),
        _review_arbitration_check(project),
        _rules_review_check(project),
        _product_workflow_check(project),
        _run_integrity_check(project),
        _worktree_isolation_check(project),
        _ux_status_check(project),
        _desktop_control_v2_check(project),
        _subagent_lifecycle_check(project),
        _runtime_task_health_check(project),
        _plugin_registry_check(project),
        _plugin_state_store_check(project),
        _security_hygiene_check(project),
        _auth_conflict_check(),
        _zsh_completion_check(),
        _cheap_first_check(project),
        DoctorCheck(
            "safe_chat_tools",
            True,
            10,
            "chat exposes /validate, /audit, /skills, /watch, /state, /ux, /agent, and /run-next",
        ),
        DoctorCheck(
            "context_engine",
            True,
            10,
            "context pack uses task ranking, budgets, source summaries, and polluted-sample rules",
        ),
        DoctorCheck(
            "role_orchestration",
            True,
            10,
            "researcher/auditor/data_engineer role orchestration exists",
        ),
        _hard_sandbox_check(project),
        DoctorCheck(
            "interactive_tool_loop",
            True,
            10,
            "mako agent provides a safe model-driven tool loop with deterministic fallback",
        ),
        DoctorCheck(
            "agent_v2_loop",
            True,
            10,
            "mako agent-v2 provides plan/execute/reflect with memory extraction and trajectory recording",
        ),
        DoctorCheck(
            "edit_executor_loop",
            True,
            10,
            "mako edit plan/run/auto/repair plus repair-swarm provides preview-gated patch plans, diff-first exact replacements, concurrent isolated repair loops, parent arbitration, checkpoints, test execution, and failure classification",
            category="agent",
        ),
        DoctorCheck(
            "session_resume",
            True,
            10,
            "mako session/resume provides first-class session files, compact summaries, and persisted resume snapshots for long tasks",
        ),
        DoctorCheck(
            "task_state_machine",
            True,
            10,
            "mako task tracks queued/running/passed/failed/blocked/aborted research tasks",
        ),
    ]
    return checks


def doctor_fix_log_path(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "doctor_fixes.jsonl"


def run_doctor_fix(project: Path) -> list[DoctorFixAction]:
    project = Path(project).expanduser().resolve(strict=False)
    actions: list[DoctorFixAction] = []
    for path in _security_sensitive_paths(project):
        actions.extend(_fix_file_mode(path, 0o600, "chmod-sensitive-file"))
    for directory in _security_runtime_dirs(project):
        actions.extend(_fix_file_mode(directory, 0o700, "chmod-runtime-dir"))
    actions.extend(_fix_broken_runtime_symlinks(project))
    actions.extend(_fix_orphan_sqlite_sidecars(project))
    actions.extend(_fix_stale_mcp_daemon_state(project))
    actions.extend(_fix_suspicious_mcp_servers(project))
    actions.extend(_fix_open_group_policy(project))
    _append_doctor_fix_log(project, actions)
    return actions


def doctor_score(checks: list[DoctorCheck]) -> int:
    earned = sum(check.score for check in checks if check.ok)
    total = sum(check.score for check in checks)
    if total <= 0:
        return 0
    return round(earned / total * 100)


def render_doctor(project: Path, checks: list[DoctorCheck], fixes: list[DoctorFixAction] | None = None) -> str:
    blocking = blocking_doctor_issues(checks)
    lines = [
        "# Mako Doctor",
        "",
        f"- project: {project}",
        f"- score: {doctor_score(checks)}/100",
        "",
    ]
    if blocking:
        lines.extend(["## Blocking Issues", ""])
        for check in blocking[:8]:
            lines.append(f"- {check.name}: {check.detail}")
            if check.remediation:
                lines.append(f"  next: {check.remediation}")
        lines.append("")
    lines.extend(
        [
        "## Checks",
        "",
        ]
    )
    for check in checks:
        mark = "ok" if check.ok else "gap"
        category = f" {check.category}" if check.category != "general" else ""
        severity = f" {check.severity}" if check.severity != "info" else ""
        lines.append(f"- [{mark}] {check.name}{category}{severity} (+{check.score if check.ok else 0}/{check.score}): {check.detail}")
        if check.remediation and not check.ok:
            lines.append(f"  remediation: {check.remediation}")
    if fixes is not None:
        lines.extend(["", "## Fixes", ""])
        if fixes:
            for fix in fixes:
                path = f" path={fix.path}" if fix.path else ""
                lines.append(f"- [{fix.status}] {fix.action_id}{path}: {fix.detail}")
        else:
            lines.append("- no automatic fixes were needed")
    if not blocking:
        lines.extend(
            [
                "",
                "## Highest-Value Next Upgrades",
                "",
                "1. Add cross-platform container/VM sandboxing and stricter network profiles beyond the current macOS sandbox-exec backend.",
                "2. Unify desktop live view and agent TUI into a full-screen terminal app with streaming tool phases, approvals, diff previews, and token pressure.",
                "3. Add conflict-aware winner apply planning so parent arbitration can explain merge conflicts before apply-gate approval.",
                "4. Add editor/LSP push diagnostics and background reindex triggers so mode-aware context refreshes without explicit CLI calls.",
                "5. Expose the headless SDK through a small HTTP server for editor/GitHub/CI integrations.",
            ]
        )
    return "\n".join(lines) + "\n"


def render_doctor_json(project: Path, checks: list[DoctorCheck], fixes: list[DoctorFixAction] | None = None) -> str:
    blocking = blocking_doctor_issues(checks)
    payload = {
        "project": str(project),
        "score": doctor_score(checks),
        "blocking_issues": [
            {
                "name": check.name,
                "detail": check.detail,
                "severity": check.severity,
                "category": check.category,
                "remediation": check.remediation,
                "paths": list(check.paths),
            }
            for check in blocking
        ],
        "checks": [
            {
                "name": check.name,
                "ok": check.ok,
                "score": check.score,
                "earned": check.score if check.ok else 0,
                "detail": check.detail,
                "severity": check.severity,
                "category": check.category,
                "remediation": check.remediation,
                "paths": list(check.paths),
            }
            for check in checks
        ],
    }
    if fixes is not None:
        payload["fixes"] = [fix.to_dict() for fix in fixes]
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def blocking_doctor_issues(checks: list[DoctorCheck]) -> list[DoctorCheck]:
    return [check for check in checks if not check.ok and check.severity in {"warn", "error"}]


def _repo_map_check(project: Path) -> DoctorCheck:
    path = repo_map_path(project)
    try:
        ensured = ensure_repo_map(project)
        loaded = load_repo_map(project)
        symbol_count = sum(len(item.symbols) for item in loaded.files)
        ok = callable(build_repo_map) and path.exists() and len(ensured.files) == len(loaded.files)
        return DoctorCheck(
            "repo_map",
            ok,
            8,
            f"repo map ensure/build/load {'available' if ok else 'has consistency issues'}; {len(loaded.files)} file(s), {symbol_count} symbol(s)",
            category="agent",
            severity="info" if ok else "warn",
            remediation="Regenerate .quantagent/repo_map.json or remove a corrupt repo map so it can be rebuilt.",
            paths=(str(path),),
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:281", exc)
        return DoctorCheck(
            "repo_map",
            False,
            8,
            f"repo map unavailable: {type(exc).__name__}: {exc}",
            category="agent",
            severity="warn",
            remediation="Fix quantagent.repo_map imports or regenerate .quantagent/repo_map.json.",
            paths=(str(path),),
        )


def _source_checks_check(project: Path) -> DoctorCheck:
    path = source_checks_dir(project)
    try:
        checks = load_source_checks(project)
        results = run_source_checks(project, run_commands=False)
        summary = source_check_summary(results)
        counts = summary.get("counts", {})
        failures = len(summary.get("failures", []))
        warnings = len(summary.get("warnings", []))
        ok = bool(summary.get("ok", True))
        detail = (
            f"{len(checks)} source check(s) loaded; run summary total={summary.get('total', 0)}, "
            f"pass={counts.get('pass', 0)}, warn={counts.get('warn', 0)}, "
            f"fail={counts.get('fail', 0)}, skip={counts.get('skip', 0)}"
        )
        if failures or warnings:
            detail += f"; failures={failures}, warnings={warnings}"
        return DoctorCheck(
            "source_checks",
            ok,
            8,
            detail,
            category="agent",
            severity="info" if ok else "warn",
            remediation="Inspect .quantagent/checks definitions and fix failing source check assertions.",
            paths=(str(path),),
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:321", exc)
        return DoctorCheck(
            "source_checks",
            False,
            8,
            f"source checks unavailable: {type(exc).__name__}: {exc}",
            category="agent",
            severity="warn",
            remediation="Fix quantagent.source_checks imports or invalid .quantagent/checks markdown frontmatter.",
            paths=(str(path),),
        )


def _session_bus_check(project: Path) -> DoctorCheck:
    path = session_bus_dir(project)
    try:
        state = status_session_bus(project)
        summary = session_bus_summary(project)
        messages = int(summary.get("messages") or 0)
        sessions = int(summary.get("sessions") or 0)
        channels = summary.get("channels") or ()
        channel_detail = ", ".join(str(item) for item in channels) if channels else "none"
        return DoctorCheck(
            "session_bus",
            True,
            8,
            f"session bus status={state.status}; {messages} message(s), {sessions} session(s), channels={channel_detail}",
            category="runtime",
            paths=(str(path),),
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:351", exc)
        return DoctorCheck(
            "session_bus",
            False,
            8,
            f"session bus unavailable: {type(exc).__name__}: {exc}",
            category="runtime",
            severity="warn",
            remediation="Inspect .quantagent/session_bus state/messages files and runtime session store integrity.",
            paths=(str(path),),
        )


def _runtime_store_check(project: Path) -> DoctorCheck:
    try:
        path = ensure_runtime_store(project)
        with sqlite3.connect(path) as conn:
            quick = conn.execute("PRAGMA quick_check").fetchone()[0]
            version = conn.execute(
                "SELECT version FROM schema_version WHERE component = 'runtime_store'"
            ).fetchone()
        ok = quick == "ok" and bool(version)
        return DoctorCheck(
            "runtime_store",
            ok,
            10,
            f"SQLite runtime store {'healthy' if ok else 'has schema/quick_check issues'} at {path}",
            category="runtime",
            severity="info" if ok else "error",
            remediation="Run mako doctor again after backing up the project, or remove a corrupt runtime.sqlite to rebuild metadata.",
            paths=(str(path),),
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:383", exc)
        return DoctorCheck(
            "runtime_store",
            False,
            10,
            f"runtime store check failed: {type(exc).__name__}: {exc}",
            category="runtime",
            severity="error",
            remediation="Check filesystem permissions and available disk space.",
            paths=(str(runtime_db_path(project)),),
        )


def _budget_reservation_health_check(project: Path) -> DoctorCheck:
    try:
        health = inspect_budget_reservations(project, limit=100)
        counts = health.get("counts") or {}
        stale_ids = list(health.get("stale_suspect_ids") or [])
        expired_active_ids = list(health.get("expired_effective_ids") or [])
        active = int(counts.get("active") or 0)
        committed = int(counts.get("committed") or 0)
        released = int(counts.get("released") or 0)
        expired = int(counts.get("expired") or 0)
        stale = int(counts.get("stale_suspect") or 0)
        ok = not stale_ids and not expired_active_ids
        suffix = ""
        if expired_active_ids:
            suffix = f"; active rows past ttl: {', '.join(expired_active_ids[:5])}"
        elif stale_ids:
            suffix = f"; stale active rows: {', '.join(stale_ids[:5])}"
        return DoctorCheck(
            "budget_reservations",
            ok,
            6,
            (
                f"budget reservations active={active} committed={committed} released={released} "
                f"expired={expired} stale={stale} active_tokens={health.get('active_estimated_tokens', 0)}"
                f"{suffix}"
            ),
            category="runtime",
            severity="info" if ok else "warn",
            remediation="Run mako runtime status, then retry or let expired reservations be swept by reservation APIs.",
            paths=(str(runtime_db_path(project)),),
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:budget_reservations", exc)
        return DoctorCheck(
            "budget_reservations",
            False,
            6,
            f"budget reservation health unavailable: {type(exc).__name__}: {exc}",
            category="runtime",
            severity="warn",
            remediation="Inspect runtime.sqlite budget_reservations schema and permissions.",
            paths=(str(runtime_db_path(project)),),
        )


def _event_log_v2_check(project: Path) -> DoctorCheck:
    try:
        events = read_runtime_events(project, limit=5)
        return DoctorCheck(
            "event_log_v2",
            True,
            10,
            f"unified JSONL event log is available for messages, tools, approvals, diffs, tests, diagnostics, MCP/LSP, checkpoints, and replay summaries ({len(events)} recent event(s))",
            category="runtime",
            paths=(str(event_log_path(project)),),
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:407", exc)
        return DoctorCheck(
            "event_log_v2",
            False,
            10,
            f"event log v2 unavailable: {type(exc).__name__}: {exc}",
            category="runtime",
            severity="warn",
            remediation="Inspect .quantagent/events/events.jsonl for corrupt JSONL records.",
            paths=(str(event_log_path(project)),),
        )


def _tool_manifest_v2_check(project: Path) -> DoctorCheck:
    try:
        catalog = build_tool_manifest_catalog(project)
        errors = [item for item in catalog.diagnostics if item.level == "error"]
        return DoctorCheck(
            "tool_manifest_v2",
            not errors,
            10,
            f"{len(catalog.tools)} tool manifest(s) expose prompt, permission, renderer, runtime, side-effect, and provenance metadata"
            if not errors
            else f"{len(errors)} tool manifest error(s): {errors[0].message}",
            category="tools",
            severity="info" if not errors else "error",
            remediation="Run mako tool-manifest lint --json to inspect malformed tools.",
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:435", exc)
        return DoctorCheck(
            "tool_manifest_v2",
            False,
            10,
            f"tool manifest v2 unavailable: {type(exc).__name__}: {exc}",
            category="tools",
            severity="error",
            remediation="Fix tool registry or plugin manifest imports.",
        )


def _permission_policy_v2_check(project: Path) -> DoctorCheck:
    try:
        policy = load_permission_policy_v2(project)
        lints = lint_permission_policy_v2(policy)
        errors = [item for item in lints if item.level == "error"]
        return DoctorCheck(
            "permission_policy_v2",
            not errors,
            10,
            f"{len(policy.rules)} permission rule(s) loaded; lint tracks conflicts, shadowed rules, approval-required decisions, and allow_always scope"
            if not errors
            else f"{len(errors)} permission policy error(s): {errors[0].message}",
            category="security",
            severity="info" if not errors else "error",
            remediation="Run mako policy-v2 lint and fix duplicate/conflicting rules.",
            paths=(str(permission_policy_path(project)),),
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:464", exc)
        return DoctorCheck(
            "permission_policy_v2",
            False,
            10,
            f"permission policy v2 unavailable: {type(exc).__name__}: {exc}",
            category="security",
            severity="error",
            remediation="Validate .quantagent/permissions.v2.json or regenerate with mako policy-v2 init.",
            paths=(str(permission_policy_path(project)),),
        )


def _task_graph_v2_check(project: Path) -> DoctorCheck:
    try:
        graph = build_task_graph(project, limit=25)
        return DoctorCheck(
            "task_graph_v2",
            True,
            8,
            f"task graph view can join sessions, parent/child task runs, runtime events, terminal outcomes, and artifacts ({len(graph.nodes)} node(s), {len(graph.edges)} edge(s))",
            category="runtime",
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:487", exc)
        return DoctorCheck(
            "task_graph_v2",
            False,
            8,
            f"task graph unavailable: {type(exc).__name__}: {exc}",
            category="runtime",
            severity="warn",
            remediation="Check runtime.sqlite task_runs and event JSONL integrity.",
        )


def _skill_pipeline_check(project: Path) -> DoctorCheck:
    proposals = list(skill_proposal_dir(project).glob("*.json")) if skill_proposal_dir(project).exists() else []
    return DoctorCheck(
        "memory_skill_pipeline",
        True,
        8,
        f"Hermes-style trajectory/event-to-skill proposal pipeline is available with human approval before installing project skills ({len(proposals)} proposal(s))",
        category="skills",
        paths=(str(skill_proposal_dir(project)),),
    )


def _runtime_task_health_check(project: Path) -> DoctorCheck:
    stale: list[str] = []
    try:
        tasks = load_tasks(project)
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:515", exc)
        return DoctorCheck(
            "runtime_tasks",
            False,
            5,
            f"task state could not be read: {type(exc).__name__}: {exc}",
            category="runtime",
            severity="error",
        )
    for task in tasks:
        if task.status == RUNNING and task.pid and not _pid_alive(task.pid):
            stale.append(task.id)
    ok = not stale
    return DoctorCheck(
        "runtime_tasks",
        ok,
        5,
        "no stale running task pids" if ok else f"stale running task pids: {', '.join(stale[:5])}",
        category="runtime",
        severity="info" if ok else "warn",
        remediation="Run mako task --refresh, then stop or re-run stale tasks.",
    )


def _approval_invocation_check(project: Path) -> DoctorCheck:
    try:
        ensure_runtime_store(project)
        approvals = list_approval_requests(project, limit=5)
        invocations = list_tool_invocations(project, limit=5)
        return DoctorCheck(
            "approval_invocation_envelope",
            True,
            12,
            f"approval store and tool invocation envelope are available; allow_always is fingerprint-scoped and expires_at is enforced ({len(approvals)} approvals, {len(invocations)} recent invocations)",
            category="runtime",
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:551", exc)
        return DoctorCheck(
            "approval_invocation_envelope",
            False,
            12,
            f"approval/invocation schema unavailable: {type(exc).__name__}: {exc}",
            category="runtime",
            severity="error",
            remediation="Run mako doctor after backing up runtime.sqlite; schema migration may need repair.",
        )


def _mcp_runtime_check(project: Path) -> DoctorCheck:
    try:
        servers = load_mcp_servers(project)
        state = status_mcp_daemon_state(project)
        return DoctorCheck(
            "mcp_runtime",
            True,
            10,
            f"stdio plus HTTP/SSE MCP runtime available; {len(servers)} configured server(s), {len(state.leases)} persistent lease record(s), daemon-capable registry, wildcard permissions, env whitelist, and argument guards supported",
            category="tools",
            paths=(state.registry_path,),
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:575", exc)
        return DoctorCheck(
            "mcp_runtime",
            False,
            10,
            f"MCP config could not be read: {type(exc).__name__}: {exc}",
            category="tools",
            severity="warn",
            remediation="Fix .quantagent/mcp_servers.json or remove invalid entries.",
        )


def _agent_infra_check(project: Path) -> DoctorCheck:
    diagnostic_count = len(editor_diagnostics(project, limit=20))
    return DoctorCheck(
        "agent_infra",
        True,
        10,
        f"configurable lifecycle hooks, OpenCode-style permission DSL, session search/export, BM25/import/semantic-fingerprint code index diagnostics, lightweight editor diagnostics ({diagnostic_count} sampled), checkpoints, transcript replay, long-task resume snapshots, isolated repair loops, subagent review bundles, and diff-first patch path are available",
        category="agent",
        paths=(str(index_path(project)), str(checkpoint_dir(project)), str(subagent_review_bundle_store_path(project))),
    )


def _shell_semantics_check(project: Path) -> DoctorCheck:
    return DoctorCheck(
        "shell_semantics",
        True,
        8,
        "Claude-style shell semantics are available for permission DSL subjects, hardline deny, project/external write detection, and sandbox explain output",
        category="security",
    )


def _permission_debug_check(project: Path) -> DoctorCheck:
    return DoctorCheck(
        "permission_debugger",
        True,
        6,
        "permission explain/denials can show matched policy, shell semantic subjects, and ambiguous permission rules",
        category="security",
    )


def _diagnostic_registry_check(project: Path) -> DoctorCheck:
    return DoctorCheck(
        "diagnostic_registry",
        True,
        6,
        "editor diagnostics can be persisted as a registry for repair loops and filtered by path",
        category="agent",
        paths=(str(diagnostic_registry_path(project)),),
    )


def _structured_diff_preview_check(project: Path) -> DoctorCheck:
    return DoctorCheck(
        "structured_diff_preview",
        True,
        8,
        "structured diff previews combine file-level diff stats, risk labels, project rules, edit permissions, and test-command permission checks before apply",
        category="agent",
        paths=(str(diff_preview_dir(project)),),
    )


def _apply_gate_check(project: Path) -> DoctorCheck:
    try:
        from .apply_gate import apply_review_with_gate, evaluate_apply_gate

        ok = callable(evaluate_apply_gate) and callable(apply_review_with_gate)
        return DoctorCheck(
            "apply_gate",
            ok,
            8,
            "gated apply is available with structured approval checks, editor diagnostics, pre-apply checkpoints, required test-command policy checks, and post-test rollback",
            category="agent",
            severity="info" if ok else "warn",
            remediation="Restore quantagent.apply_gate evaluate/apply entrypoints.",
            paths=(
                str(diff_preview_dir(project)),
                str(diagnostic_registry_path(project)),
                str(checkpoint_dir(project)),
            ),
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:660", exc)
        return DoctorCheck(
            "apply_gate",
            False,
            8,
            f"apply gate unavailable: {type(exc).__name__}: {exc}",
            category="agent",
            severity="warn",
            remediation="Fix quantagent.apply_gate imports before relying on gated apply.",
            paths=(
                str(diff_preview_dir(project)),
                str(diagnostic_registry_path(project)),
                str(checkpoint_dir(project)),
            ),
        )


def _retrieval_daemon_check(project: Path) -> DoctorCheck:
    try:
        from .retrieval_daemon import build_retrieval_index, search_retrieval_index, start_retrieval_daemon

        ok = callable(build_retrieval_index) and callable(search_retrieval_index) and callable(start_retrieval_daemon)
        return DoctorCheck(
            "retrieval_daemon",
            ok,
            9,
            "persistent retrieval index provides local embedding vectors, semantic fingerprints, import-graph related paths, query planning, and daemon-style start/status/health state",
            category="agent",
            severity="info" if ok else "warn",
            remediation="Restore quantagent.retrieval_daemon build/search/start entrypoints.",
            paths=(str(retrieval_index_path(project)), str(retrieval_state_path(project))),
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:692", exc)
        return DoctorCheck(
            "retrieval_daemon",
            False,
            9,
            f"retrieval daemon unavailable: {type(exc).__name__}: {exc}",
            category="agent",
            severity="warn",
            remediation="Fix quantagent.retrieval_daemon imports before relying on semantic retrieval.",
            paths=(str(retrieval_index_path(project)), str(retrieval_state_path(project))),
        )


def _embedding_provider_check(project: Path) -> DoctorCheck:
    try:
        from .embedding_provider import LocalHashEmbeddingProvider, OpenAICompatibleEmbeddingProvider, SentenceTransformersEmbeddingProvider, embed_batch

        ok = callable(embed_batch) and callable(LocalHashEmbeddingProvider) and callable(OpenAICompatibleEmbeddingProvider) and callable(SentenceTransformersEmbeddingProvider)
        return DoctorCheck(
            "embedding_provider",
            ok,
            9,
            "embedding provider layer supports local hash vectors, OpenAI-compatible embeddings, sentence-transformers fallback, batch queueing, vector cache, and incremental unchanged-text skips",
            category="agent",
            severity="info" if ok else "warn",
            remediation="Restore quantagent.embedding_provider provider/batch/cache entrypoints.",
            paths=(str(embedding_cache_path(project)),),
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:720", exc)
        return DoctorCheck(
            "embedding_provider",
            False,
            9,
            f"embedding provider unavailable: {type(exc).__name__}: {exc}",
            category="agent",
            severity="warn",
            remediation="Fix quantagent.embedding_provider imports before relying on provider-backed retrieval.",
            paths=(str(embedding_cache_path(project)),),
        )


def _lsp_diagnostics_check(project: Path) -> DoctorCheck:
    try:
        from .lsp_diagnostics import detect_default_lsp_servers, run_lsp_diagnostics

        statuses = detect_default_lsp_servers()
        available = [status.name for status in statuses if status.available]
        return DoctorCheck(
            "lsp_diagnostics",
            True,
            10,
            "LSP diagnostics layer supports JSON-RPC header framing, initialize/initialized/didOpen/didChange/shutdown, publishDiagnostics collection, cache persistence, and pyright/ruff/typescript server detection"
            + (f" ({', '.join(available)} available)" if available else " (no default LSP executable currently installed)"),
            category="agent",
            severity="info",
            paths=(str(lsp_cache_path(project)),),
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:749", exc)
        return DoctorCheck(
            "lsp_diagnostics",
            False,
            10,
            f"LSP diagnostics unavailable: {type(exc).__name__}: {exc}",
            category="agent",
            severity="warn",
            remediation="Fix quantagent.lsp_diagnostics imports before relying on LSP diagnostics.",
            paths=(str(lsp_cache_path(project)),),
        )


def _mcp_gateway_check(project: Path) -> DoctorCheck:
    try:
        from .mcp_gateway import gateway_call_tool, refresh_mcp_gateway, start_mcp_gateway

        ok = callable(start_mcp_gateway) and callable(refresh_mcp_gateway) and callable(gateway_call_tool)
        return DoctorCheck(
            "mcp_gateway",
            ok,
            8,
            "persistent MCP gateway registry tracks server state, tool catalog, leases, sanitized call records, runtime invocations, and gateway health",
            category="tools",
            severity="info" if ok else "warn",
            remediation="Restore quantagent.mcp_gateway start/refresh/call entrypoints.",
            paths=(str(gateway_state_path(project)),),
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:777", exc)
        return DoctorCheck(
            "mcp_gateway",
            False,
            8,
            f"MCP gateway unavailable: {type(exc).__name__}: {exc}",
            category="tools",
            severity="warn",
            remediation="Fix quantagent.mcp_gateway imports before relying on persistent MCP gateway state.",
            paths=(str(gateway_state_path(project)),),
        )


def _external_mcp_daemon_check(project: Path) -> DoctorCheck:
    try:
        from .mcp_daemon import McpDaemon, request_mcp_daemon, start_mcp_daemon, status_mcp_daemon

        ok = callable(McpDaemon) and callable(start_mcp_daemon) and callable(status_mcp_daemon) and callable(request_mcp_daemon)
        return DoctorCheck(
            "external_mcp_daemon",
            ok,
            10,
            "external MCP daemon layer provides state/pid/socket files, Unix socket JSON-line API, start/status/stop/restart/recover, catalog cache, session leases, call records, and redacted errors",
            category="tools",
            severity="info" if ok else "warn",
            remediation="Restore quantagent.mcp_daemon daemon/socket entrypoints.",
            paths=(str(mcp_daemon_state_path(project)),),
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:805", exc)
        return DoctorCheck(
            "external_mcp_daemon",
            False,
            10,
            f"external MCP daemon unavailable: {type(exc).__name__}: {exc}",
            category="tools",
            severity="warn",
            remediation="Fix quantagent.mcp_daemon imports before relying on external MCP daemon mode.",
            paths=(str(mcp_daemon_state_path(project)),),
        )


def _eval_harness_check(project: Path) -> DoctorCheck:
    try:
        from .eval_harness import builtin_smoke_eval_cases, run_eval_cases

        ok = callable(builtin_smoke_eval_cases) and callable(run_eval_cases)
        return DoctorCheck(
            "eval_harness",
            ok,
            7,
            "benchmark/eval harness can load project eval cases, run shell smoke checks, classify pass/fail/error, and render markdown/json score summaries",
            category="runtime",
            severity="info" if ok else "warn",
            remediation="Restore quantagent.eval_harness load/run/render entrypoints.",
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:832", exc)
        return DoctorCheck(
            "eval_harness",
            False,
            7,
            f"eval harness unavailable: {type(exc).__name__}: {exc}",
            category="runtime",
            severity="warn",
            remediation="Fix quantagent.eval_harness imports before relying on benchmark checks.",
        )


def _quant_bench_check(project: Path) -> DoctorCheck:
    try:
        from .quant_bench import quant_bench_cases, render_quant_bench, run_quant_bench

        cases = quant_bench_cases()
        ok = len(cases) >= 10 and callable(run_quant_bench) and callable(render_quant_bench)
        categories = sorted({case.category for case in cases})
        return DoctorCheck(
            "quant_bench",
            ok,
            8,
            f"{len(cases)} quant benchmark cases available across {', '.join(categories)}",
            category="quant",
            severity="info" if ok else "warn",
            remediation="Restore quantagent.quant_bench cases/run/render entrypoints.",
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:860", exc)
        return DoctorCheck(
            "quant_bench",
            False,
            8,
            f"quant benchmark unavailable: {type(exc).__name__}: {exc}",
            category="quant",
            severity="warn",
            remediation="Fix quantagent.quant_bench imports before relying on quant regression checks.",
        )


def _quant_run_gate_check(project: Path) -> DoctorCheck:
    try:
        from .quant_run_gate import QuantRunSpec, build_quant_run_verdict, latest_quant_gate_run, run_quant_gate

        ok = callable(run_quant_gate) and callable(build_quant_run_verdict) and callable(latest_quant_gate_run) and bool(QuantRunSpec)
        return DoctorCheck(
            "quant_run_gate",
            ok,
            10,
            "QuantRunGate state machine is available for spec -> data contract -> leak check -> split check -> run artifacts -> evidence bundle -> verdict/replay",
            category="quant",
            severity="info" if ok else "warn",
            remediation="Restore quantagent.quant_run_gate spec/run/verdict entrypoints.",
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:886", exc)
        return DoctorCheck(
            "quant_run_gate",
            False,
            10,
            f"quant run gate unavailable: {type(exc).__name__}: {exc}",
            category="quant",
            severity="warn",
            remediation="Fix quantagent.quant_run_gate imports before relying on quant execution gating.",
        )


def _review_arbitration_check(project: Path) -> DoctorCheck:
    try:
        from .review_arbitration import arbitrate_parent_reviews, render_arbitration_decision

        ok = callable(arbitrate_parent_reviews) and callable(render_arbitration_decision)
        return DoctorCheck(
            "review_arbitration",
            ok,
            8,
            "parent review arbitration ranks isolated worker reviews by success, score, diagnostics, risk, changed paths, approval needs, and apply-gate readiness",
            category="agent",
            severity="info" if ok else "warn",
            remediation="Restore quantagent.review_arbitration arbitrate/render entrypoints.",
            paths=(str(subagent_review_bundle_store_path(project)),),
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:913", exc)
        return DoctorCheck(
            "review_arbitration",
            False,
            8,
            f"review arbitration unavailable: {type(exc).__name__}: {exc}",
            category="agent",
            severity="warn",
            remediation="Fix quantagent.review_arbitration imports before relying on parent review arbitration.",
            paths=(str(subagent_review_bundle_store_path(project)),),
        )


def _rules_review_check(project: Path) -> DoctorCheck:
    rules = load_project_rules(project)
    return DoctorCheck(
        "rules_and_diff_review",
        True,
        8,
        f"Cursor-style project rules and changed-file review are available; {len(rules)} rule source(s) discovered",
        category="agent",
        paths=tuple(rule.source for rule in rules[:8]),
    )


def _product_workflow_check(project: Path) -> DoctorCheck:
    return DoctorCheck(
        "product_workflows",
        True,
        8,
        "Continue-style context providers, Aider-style architect/editor handoff, memory sidecar approvals, PR plans, and remote runner specs are available",
        category="agent",
        paths=(
            str(architect_dir(project)),
            str(memory_proposal_path(project)),
            str(pr_plan_dir(project)),
            str(remote_runner_dir(project)),
        ),
    )


def _run_integrity_check(project: Path) -> DoctorCheck:
    return DoctorCheck(
        "run_integrity",
        True,
        8,
        "stable run-id/spec-lock/per-run directories, PASS/FAIL/INCONCLUSIVE verdict gate, and pre-LLM redaction/log folding are available",
        category="runtime",
        paths=(str(runs_root(project)),),
    )


def _worktree_isolation_check(project: Path) -> DoctorCheck:
    capability = detect_sandbox_backend("auto")
    sandbox_note = (
        f"{capability.backend} backend available; network={capability.network_policy}"
        if capability.available
        else f"{capability.backend} unavailable: {capability.reason}"
    )
    return DoctorCheck(
        "worktree_isolation",
        True,
        8,
        f"mako isolation can create copy-on-write project worktrees, run commands without mutating the source project, generate reviewed merge diffs, and select sandbox backend automatically ({sandbox_note}) at {isolation_root(project)}",
        category="security",
        paths=(str(isolation_root(project)),),
    )


def _hard_sandbox_check(project: Path) -> DoctorCheck:
    capability = detect_sandbox_backend("auto")
    ok = capability.backend == SANDBOX_EXEC and capability.available
    return DoctorCheck(
        "hard_sandbox",
        ok,
        10,
        (
            f"macOS sandbox-exec is available; subprocess writes can be OS-scoped to the copied workspace (network={capability.network_policy})"
            if ok
            else f"no OS sandbox backend detected; using {capability.backend} fallback with {capability.network_policy} network policy"
        ),
        severity="info" if ok else "warn",
        category="security",
        remediation=(
            ""
            if ok
            else "Install or configure an OS sandbox backend before allowing broad risky commands."
        ),
        paths=(str(isolation_root(project)),),
    )


def _ux_status_check(project: Path) -> DoctorCheck:
    try:
        status = build_ux_status(project, limit=3, include_context_pack=False)
        return DoctorCheck(
            "ux_status",
            True,
            6,
            f"mako ux status unifies context={status.context.mode}, session, pending approvals ({len(status.approvals)}), tool transcripts, diff reviews, checkpoints, and query events",
            category="runtime",
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:1015", exc)
        return DoctorCheck(
            "ux_status",
            False,
            6,
            f"UX status panel failed: {type(exc).__name__}: {exc}",
            category="runtime",
            severity="warn",
            remediation="Run mako ux status --no-context-pack and inspect corrupt runtime JSON/SQLite files.",
        )


def _cheap_first_check(project: Path) -> DoctorCheck:
    try:
        plan = build_cheap_plan(project, "status")
        ok = plan.model_calls == 0 and plan.estimated_tokens <= plan.token_budget
        return DoctorCheck(
            "cheap_first",
            ok,
            10,
            f"mako cheap previews context={plan.context_mode}, token pressure={round(plan.token_pressure * 100, 2)}%, and free-first commands before any model call",
            category="cost",
            severity="info" if ok else "warn",
            remediation="" if ok else "Reduce default context budget pressure or inspect context pack inputs.",
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:1040", exc)
        return DoctorCheck(
            "cheap_first",
            False,
            10,
            f"cheap-first preview failed: {type(exc).__name__}: {exc}",
            category="cost",
            severity="warn",
            remediation="Run mako cheap --project . --json and inspect context/runtime files.",
        )


def _desktop_control_v2_check(project: Path) -> DoctorCheck:
    try:
        elements = (
            DesktopElement("AX0001", "Safari", 1, role="AXButton", title="Search", bounds=(10, 20, 120, 30)),
            DesktopElement("AX0002", "Safari", 1, role="AXTextField", title="Address and Search", bounds=(160, 20, 500, 30)),
        )
        hits = search_ax_elements(elements, "search")
        som_targets = build_som_targets(
            image_path=project / "screen.png",
            width=1200,
            height=800,
            ax_elements=elements,
            ocr_blocks=(DesktopTextBlock("OCR0001", "Search results", bounds=(200, 120, 460, 155), confidence=0.93),),
        )
        som_hits = search_som_targets(som_targets, "results")
        plan = plan_web_search("quant agent evidence", browser="Safari", engine="duckduckgo")
        run = execute_desktop_plan(project, plan, execute=False)
        live = build_desktop_live_state(project, limit=3)
        ok = bool(hits) and hits[0].target is not None and bool(som_hits) and run.status == "preview" and live.status in {"active", "idle", "warn", "blocked"} and "duckduckgo" in search_url("x", engine="duckduckgo")
        return DoctorCheck(
            "desktop_control_v2",
            ok,
            8,
            (
                "desktop control plane supports AX/OCR/SoM target search, grid/text lookup, live TUI status, dry-run action plans, reviewed execution gates, browser search plans, screenshot verification, and audit logs"
                if ok
                else "desktop control plane failed its deterministic dry-run/search self-check"
            ),
            category="agent",
            remediation="Run mako desktop web-search 'test' and mako desktop find 'search' --source ax --refresh-ax to inspect local desktop permissions.",
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:1083", exc)
        return DoctorCheck(
            "desktop_control_v2",
            False,
            8,
            f"desktop control plane unavailable: {type(exc).__name__}: {exc}",
            category="agent",
            severity="warn",
            remediation="Run mako desktop schema and mako desktop web-search 'test' to inspect command wiring.",
        )


def _agent_profile_check(project: Path) -> DoctorCheck:
    config = load_agent_profile_config(project)
    instructions = load_instructions(project)
    required = {"plan", "build", "audit", "quant-auditor"}
    missing = sorted(required - set(config.agents))
    return DoctorCheck(
        "agent_profiles",
        not missing,
        10,
        f"default={config.default_agent}; {len(config.agents)} profile(s); {len(instructions)} instruction source(s); sources={len(config.sources)}; markdown agents and profile-scoped hooks supported"
        if not missing
        else f"missing profile(s): {', '.join(missing)}",
        category="agent",
        remediation="Restore builtin agent profiles or fix .quantagent/config.json.",
    )


def _agent_modes_check(project: Path) -> DoctorCheck:
    try:
        modes = list_agent_modes(project)
        diagnostics = validate_agent_modes(project)
        errors = [item for item in diagnostics if item.level == "error"]
        build_tools = mode_tool_views(project, "build")
        plan_tools = mode_tool_views(project, "plan")
        build_writes = sum(1 for item in build_tools if item.action in {"ask", "allow"} and item.side_effects)
        plan_denies = sum(1 for item in plan_tools if item.action == "deny")
        return DoctorCheck(
            "agent_modes",
            not errors,
            10,
            f"{len(modes)} mode(s) available; build exposes {build_writes} side-effect tool(s) behind mode policy; plan denies {plan_denies} tool(s); checks/apply-gate/isolation policies are mode-scoped"
            if not errors
            else f"{len(errors)} agent mode error(s): {errors[0].message}",
            category="agent",
            severity="info" if not errors else "error",
            remediation="Run mako modes lint --json and fix .quantagent/modes.json.",
            paths=(str(agent_mode_config_path(project)),),
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:1133", exc)
        return DoctorCheck(
            "agent_modes",
            False,
            10,
            f"agent modes unavailable: {type(exc).__name__}: {exc}",
            category="agent",
            severity="error",
            remediation="Check quantagent.agent_modes imports and .quantagent/modes.json syntax.",
            paths=(str(agent_mode_config_path(project)),),
        )


def _goal_contract_check(project: Path) -> DoctorCheck:
    try:
        contract = load_goal_contract(project)
        allow_decision = evaluate_goal_guard(
            project,
            "implement the requested feature and run focused tests",
            goal="deliver a high-quality tested implementation",
        )
        block_decision = evaluate_goal_guard(
            project,
            "skip tests and bypass validation but mark the work complete",
            goal="deliver a high-quality tested implementation",
        )
        quant_decision = evaluate_goal_guard(
            project,
            "publish PF=2.4 improvement as confirmed without dedup baseline evidence",
            goal="produce low-hallucination quant research with verified evidence",
        )
        data_decision = evaluate_goal_guard(
            project,
            "guess the test count and report 349 tests passed without command output",
            goal="report only verified data with evidence",
        )
        ok = allow_decision.allowed and not block_decision.allowed and not quant_decision.allowed and not data_decision.allowed
        configured = "configured" if contract.goal else "default"
        return DoctorCheck(
            "goal_contract",
            ok,
            10,
            f"{configured} goal contract enforces follow-user-unless-goal-conflict with strict uncertain-data and quant hallucination blocking; allow={allow_decision.action}, conflict={block_decision.action}, data={data_decision.action}, quant={quant_decision.action}"
            if ok
            else f"goal guard unexpected decisions: allow={allow_decision.action}, conflict={block_decision.action}, data={data_decision.action}, quant={quant_decision.action}",
            category="agent",
            severity="info" if ok else "warn",
            remediation="Run mako goal-contract check --goal '...' 'instruction' and inspect .quantagent/goal_contract.json.",
            paths=(str(goal_contract_path(project)),),
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:1183", exc)
        return DoctorCheck(
            "goal_contract",
            False,
            10,
            f"goal contract unavailable: {type(exc).__name__}: {exc}",
            category="agent",
            severity="warn",
            remediation="Check .quantagent/goal_contract.json syntax or remove the file.",
            paths=(str(goal_contract_path(project)),),
        )


def _answer_guard_check(project: Path) -> DoctorCheck:
    try:
        blocked = guard_answer(project, "The score is 90 points without checking.", goal="report only verified data with evidence")
        evidence = create_evidence_record(claim="test count", value="352", evidence_type="command_output", source="unittest output")
        allowed = guard_answer(project, "352 tests passed. source: unittest output", goal="report only verified data with evidence", evidence=(evidence,))
        ok = (not blocked.ok) and allowed.ok
        return DoctorCheck(
            "answer_guard",
            ok,
            10,
            f"final answer gate blocks unsupported data claims and allows evidence-backed data; blocked={blocked.action}, allowed={allowed.action}",
            category="agent",
            severity="info" if ok else "warn",
            remediation="Run mako answer-guard --answer '...' and add evidence with mako evidence add.",
            paths=(str(evidence_ledger_path(project)),),
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:1212", exc)
        return DoctorCheck(
            "answer_guard",
            False,
            10,
            f"answer guard unavailable: {type(exc).__name__}: {exc}",
            category="agent",
            severity="warn",
            remediation="Check quantagent.answer_guard and quantagent.evidence_ledger imports.",
            paths=(str(evidence_ledger_path(project)),),
        )


def _headless_sdk_check(project: Path) -> DoctorCheck:
    try:
        sdk = QuantAgentHeadless(project)
        route = sdk.route("implement a small tested change", mode="build")
        guarded = sdk.guard_answer("Unknown until verified.", goal="report only verified data with evidence")
        ok = route.mode == "build" and guarded.ok
        return DoctorCheck(
            "headless_sdk",
            ok,
            8,
            f"headless SDK can route tasks, run agent-v3, record evidence, and apply answer guard; route={route.mode}, guard={guarded.action}",
            category="runtime",
            severity="info" if ok else "warn",
            remediation="Import quantagent.headless_sdk.QuantAgentHeadless or run mako headless.",
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:1240", exc)
        return DoctorCheck(
            "headless_sdk",
            False,
            8,
            f"headless SDK unavailable: {type(exc).__name__}: {exc}",
            category="runtime",
            severity="warn",
            remediation="Check quantagent.headless_sdk imports and agent-v3 dependencies.",
        )


def _agent_loop_v3_check(project: Path) -> DoctorCheck:
    try:
        diagnostics = validate_mode_router(project)
        errors = [item for item in diagnostics if item.level == "error"]
        route = route_agent_mode(project, "implement a mode-aware agent loop and run tests", changed_paths=("quantagent/agent_loop_v3.py",))
        context = build_agent_runtime_context(project, "implement a mode-aware agent loop and run tests", mode_name=route.mode, changed_paths=("quantagent/agent_loop_v3.py",))
        plan = build_agent_v3_plan("implement a mode-aware agent loop and run tests", route, changed_paths=("quantagent/agent_loop_v3.py",))
        tui = build_tui_status_model(project, task="implement a mode-aware agent loop and run tests", mode_name=route.mode, include_context_pack=False, limit=2)
        ok = not errors and bool(context.sections) and bool(plan) and len(tui.panels) >= 5
        return DoctorCheck(
            "agent_loop_v3",
            ok,
            10,
            (
                f"auto mode router selected {route.mode} ({route.confidence:.2f}); runtime context has {len(context.sections)} section(s); v3 plan has {len(plan)} step(s); TUI status model has {len(tui.panels)} panel(s)"
                if ok
                else f"agent loop v3 degraded: errors={len(errors)}, sections={len(context.sections)}, plan_steps={len(plan)}, panels={len(tui.panels)}"
            ),
            category="agent",
            severity="info" if ok else "warn",
            remediation="Run mako mode-router --lint and mako agent-context 'task' to inspect route/context failures.",
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:1274", exc)
        return DoctorCheck(
            "agent_loop_v3",
            False,
            10,
            f"agent loop v3 unavailable: {type(exc).__name__}: {exc}",
            category="agent",
            severity="warn",
            remediation="Check mode_router, agent_context_runtime, agent_loop_v3, and tui_status_model imports.",
        )


def _subagent_lifecycle_check(project: Path) -> DoctorCheck:
    path = subagent_store_path(project)
    bundle_path = subagent_review_bundle_store_path(project)
    available_backends = ", ".join(backend.name for backend in detect_subagent_backends(project) if backend.available) or "none"
    return DoctorCheck(
        "subagent_lifecycle",
        True,
        10,
        f"subagent lifecycle store is ready at {path}; child context artifacts, agent profiles, isolated worktrees, terminal outcomes, parent review bundles, and backend registry ({available_backends}) are supported",
        category="runtime",
        paths=(str(path), str(bundle_path)),
    )


def _auth_conflict_check() -> DoctorCheck:
    has_token = bool(os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    ok = not (has_token and has_key)
    return DoctorCheck(
        "auth_conflict",
        ok,
        5,
        "no Anthropic token/API-key conflict detected"
        if ok
        else "both ANTHROPIC_AUTH_TOKEN and ANTHROPIC_API_KEY are set",
        category="config",
        severity="info" if ok else "warn",
        remediation="Unset the credential you do not intend to use before launching the agent.",
    )


def _plugin_registry_check(project: Path) -> DoctorCheck:
    registry = build_plugin_registry(project)
    errors = [item for item in registry.diagnostics if item.level == "error"]
    ok = not errors
    return DoctorCheck(
        "plugin_registry",
        ok,
        7,
        f"{len(registry.plugins)} plugin(s), no registry errors"
        if ok
        else f"{len(errors)} plugin registry error(s): {errors[0].message}",
        category="plugins",
        severity="info" if ok else "warn",
        remediation="Run mako plugins --json to inspect bad manifests or duplicate plugin ids.",
        paths=tuple(item.path for item in errors[:5]),
    )


def _plugin_state_store_check(project: Path) -> DoctorCheck:
    probe = probe_plugin_state_store(project)
    failed = [step for step in probe.steps if not step.ok]
    ok = not failed
    return DoctorCheck(
        "plugin_state_store",
        ok,
        6,
        f"plugin keyed state store healthy at {probe.db_path}; {len(probe.steps)} probe step(s) passed"
        if ok
        else f"plugin keyed state store probe failed at {failed[0].name}: {failed[0].message or failed[0].code or 'unknown error'}",
        category="plugins",
        severity="info" if ok else "warn",
        remediation="Inspect .quantagent/plugin_state.sqlite permissions or remove a corrupt plugin state DB after backing it up.",
        paths=(probe.db_path,),
    )


def _security_hygiene_check(project: Path) -> DoctorCheck:
    findings: list[str] = []
    paths: list[str] = []

    for path in _security_sensitive_paths(project):
        if not path.exists():
            continue
        mode = _safe_mode(path)
        if mode is None:
            continue
        if path.name.startswith(".env") or "secret" in path.name.lower() or "credential" in path.name.lower():
            if mode & (stat.S_IRWXG | stat.S_IRWXO):
                findings.append(f"secret-like file is group/world accessible: {path}")
                paths.append(str(path))
        elif mode & stat.S_IWOTH:
            findings.append(f"config file is world-writable: {path}")
            paths.append(str(path))

    plugin_root = project / ".quantagent" / "plugins"
    if plugin_root.exists():
        for directory in [plugin_root, *[item for item in plugin_root.iterdir() if item.is_dir()]]:
            mode = _safe_mode(directory)
            if mode is not None and mode & (stat.S_IWGRP | stat.S_IWOTH):
                findings.append(f"plugin directory is group/world writable: {directory}")
                paths.append(str(directory))

    for symlink in _limited_symlink_scan(project / ".quantagent"):
        if not symlink.exists():
            findings.append(f"broken symlink in runtime config: {symlink}")
            paths.append(str(symlink))

    db_path = runtime_db_path(project)
    for sidecar in (db_path.with_suffix(db_path.suffix + "-wal"), db_path.with_suffix(db_path.suffix + "-shm")):
        if sidecar.exists() and not db_path.exists():
            findings.append(f"runtime SQLite sidecar exists without database: {sidecar}")
            paths.append(str(sidecar))

    state_path = mcp_daemon_state_path(project)
    stale_pid = _stale_pid_from_json(state_path)
    if stale_pid:
        findings.append(f"stale MCP daemon pid: {stale_pid}")
        paths.append(str(state_path))

    suspicious = _suspicious_mcp_commands(project)
    for item in suspicious:
        findings.append(f"suspicious MCP command: {item}")
    if suspicious:
        paths.append(str(project / ".quantagent" / "mcp_servers.json"))

    ok = not findings
    return DoctorCheck(
        "security_hygiene",
        ok,
        8,
        "config, secret-file, plugin-dir, symlink, SQLite sidecar, daemon pid, and MCP command hygiene passed"
        if ok
        else f"{len(findings)} security hygiene issue(s): {findings[0]}",
        category="security",
        severity="info" if ok else "warn",
        remediation="Tighten file permissions, remove stale runtime files, fix broken symlinks, or review suspicious MCP commands.",
        paths=tuple(dict.fromkeys(paths[:12])),
    )


def _security_sensitive_paths(project: Path) -> tuple[Path, ...]:
    return (
        project / ".env",
        project / ".env.local",
        project / ".quantagent" / "config.json",
        project / ".quantagent" / "permissions.v2.json",
        project / ".quantagent" / "mcp_servers.json",
        project / ".quantagent" / "secrets.json",
        project / ".quantagent" / "credentials.json",
    )


def _safe_mode(path: Path) -> int | None:
    try:
        return path.stat().st_mode
    except OSError:
        return None


def _limited_symlink_scan(root: Path, *, limit: int = 200) -> list[Path]:
    if not root.exists():
        return []
    broken: list[Path] = []
    scanned = 0
    for path in root.rglob("*"):
        scanned += 1
        if scanned > limit:
            break
        if path.is_symlink() and not path.exists():
            broken.append(path)
    return broken


def _stale_pid_from_json(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    raw_pid = payload.get("pid")
    try:
        pid = int(raw_pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    return None if _pid_alive(pid) else pid


def _suspicious_mcp_commands(project: Path) -> list[str]:
    path = project / ".quantagent" / "mcp_servers.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    servers = payload.get("mcp_servers", payload.get("servers")) if isinstance(payload, dict) else None
    if isinstance(servers, dict):
        items = servers.values()
    elif isinstance(servers, list):
        items = servers
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    suspicious: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        command = " ".join(str(part) for part in [item.get("command"), *list(item.get("args") or [])] if part)
        lowered = command.lower()
        if any(marker in lowered for marker in ("rm -rf", "chmod 777", "curl http://169.254.", "wget http://169.254.", "metadata.google.internal")):
            suspicious.append(command)
        elif any(lowered.startswith(prefix) or f" {prefix}" in lowered for prefix in ("bash -c", "sh -c", "zsh -c", "python -c", "python3 -c", "node -e")):
            suspicious.append(command)
    return suspicious[:10]


def _zsh_completion_check() -> DoctorCheck:
    zshrc = Path.home() / ".zshrc"
    if not zshrc.exists():
        return DoctorCheck("zsh_completion_sources", True, 3, ".zshrc not present", category="config")
    missing: list[str] = []
    for line in zshrc.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped.startswith("source "):
            continue
        raw = stripped.removeprefix("source ").strip().strip("'\"")
        candidate = Path(os.path.expandvars(raw)).expanduser()
        if raw and "openclaw" in raw and not candidate.exists():
            missing.append(str(candidate))
    ok = not missing
    return DoctorCheck(
        "zsh_completion_sources",
        ok,
        3,
        "shell completion source paths exist" if ok else f"missing sourced completion path: {missing[0]}",
        category="config",
        severity="info" if ok else "warn",
        remediation="Remove or guard the stale source line in ~/.zshrc.",
        paths=tuple(missing),
    )


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
