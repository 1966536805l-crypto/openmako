from __future__ import annotations

import argparse
import importlib
import json
import math
import shlex
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import __version__
from .agent_loop import QuantAgent, render_agent_result, run_agent_loop
from .agent_autopsy import build_agent_autopsy, dumps_agent_autopsy_json, render_agent_autopsy, run_agent_autopsy_command, write_agent_autopsy
from .branding import PRODUCT_NAME, PRIMARY_CLI, LEGACY_CLI
from .agent_loop_v3 import render_agent_v3_result, run_agent_loop_v3
from .agent_context_runtime import build_agent_runtime_context, render_agent_runtime_context
from .agent_gateway import build_agent_gateway_status, render_agent_gateway_html, render_agent_gateway_json, write_agent_gateway_html
from .agent_runtime import build_agent_runtime_view, render_agent_runtime_view
from .agent_modes import get_agent_mode, list_agent_modes, mode_tool_views, render_agent_mode, render_agent_modes, render_mode_decision, render_mode_tool_views, resolve_agent_mode_permission, validate_agent_modes
from .agent_profiles import load_agent_profile_config, load_instructions, render_agent_profile, render_agent_profiles, render_instructions
from .agent_supervisor import get_agent_supervisor_run, load_agent_supervisor_runs, refresh_agent_supervisor, render_agent_supervisor_run, run_agent_supervisor
from .agent_v2 import run_agent_v2
from .answer_guard import guard_answer, render_answer_guard_verdict
from .apply_gate import apply_review_with_gate, evaluate_apply_gate, render_apply_gate_result, render_apply_gate_verdict
from .architect import create_architect_plan, list_architect_plans, load_architect_plan, render_architect_plan
from .approvals import approve, deny, get_approval, list_approvals, render_approval, render_approvals
from .auto_runner import run_next
from .better_option import render_better_option_hint, suggest_better_option
from .broker_gateway import BrokerGatewaySpec, build_broker_gateway_snapshot, render_broker_gateway_snapshot
from .checkpoints import create_checkpoint, list_checkpoints, load_checkpoint, render_checkpoint_detail, render_checkpoints, restore_checkpoint
from .channel_gateway import bind_sender_agent, create_pairing_code, handle_channel_message, list_channel_bindings, list_channel_gateway_events, pair_sender, resolve_sender_owner
from .code_eval_fixtures import list_code_eval_fixtures, render_code_eval_fixture_list, render_code_eval_json, render_code_eval_markdown, render_code_eval_solve_json, render_code_eval_solve_markdown, run_code_eval_pack, run_code_eval_solve_pack
from .coding_bench import CodingBenchTask, builtin_coding_bench_tasks, load_coding_bench_tasks, render_coding_bench_json, render_coding_bench_markdown, render_coding_bench_stability_json, render_coding_bench_stability_markdown, run_coding_bench, run_coding_bench_stability, run_coding_bench_task
from .code_index import build_code_index, diagnose_code_index, editor_diagnostics, related_files, render_code_index_health, render_code_search_hits, render_editor_diagnostics, render_related_files, search_code_index, write_code_index
from .config import load_config
from .chat_ui import choose_context_decision, run_chat
from .cheap_plan import build_cheap_plan, render_cheap_plan
from .consensus import create_consensus_request, load_consensus_status, render_status
from .context_pack import build_context_pack
from .context_providers import gather_context_providers, parse_context_refs, render_context_provider_results
from .compact_budget import auto_compact_messages, plan_auto_compact, render_compact_plan
from .diagnostic_registry import load_diagnostic_registry, refresh_diagnostic_registry, render_diagnostic_registry
from .demo_fix import render_fix_demo, run_fix_demo
from .doctor import blocking_doctor_issues, doctor_score, render_doctor, render_doctor_json, run_doctor
from .desktop_control import activate_app, click_grid_cell, front_window, frontmost_app, hotkey, latest_grid, pointer, screenshot, screenshot_grid, type_text
from .desktop_agent import render_desktop_agent_result, run_desktop_agent
from .desktop_guardian import render_desktop_guardian_result, run_desktop_guardian
from .desktop_intelligence import (
    build_desktop_tokenization,
    decide_desktop_action,
    latest_desktop_tokenization,
    load_desktop_tokenization,
    render_desktop_daemon_result,
    render_desktop_decision,
    render_desktop_tokenization,
    run_desktop_daemon,
)
from .desktop_overnight import render_desktop_overnight_result, run_desktop_overnight
from .desktop_plan import plan_click, render_click_plan
from .desktop_live import build_desktop_live_state, render_desktop_live_html, render_desktop_live_json, render_desktop_live_state, run_desktop_live, write_desktop_live_html
from .desktop_send_confirm import render_desktop_send_confirm_result, run_desktop_send_confirm
from .desktop_workflow import (
    ax_snapshot,
    click_som_target,
    desktop_find,
    execute_desktop_plan,
    load_desktop_plan,
    ocr_image,
    open_target,
    plan_find_and_click,
    plan_open_target,
    plan_web_search,
    render_desktop_hits,
    render_desktop_plan,
    render_desktop_run,
    som_capture,
)
from .edit_loop import (
    ChangeSetCandidate,
    ChangeSetPlan,
    EditPlan,
    FileReplacement,
    AutoPatchSpec,
    _run_patch_plan_from_patch_plan,
    create_patch_plan,
    load_patch_plan,
    propose_repair_candidates,
    run_isolated_repair_loop,
    run_auto_patch,
    run_change_set_retry,
    run_edit_test_retry,
    write_patch_plan,
)
from .experiment_runner import ExperimentSpec, fmt_pf, resolve_default_input, run_experiment
from .eval_harness import append_eval_ledger, build_eval_gap_report, build_eval_scorecard, builtin_code_eval_cases, builtin_smoke_eval_cases, latest_eval_ledger_row, load_eval_cases, render_eval_gap_report, render_eval_json, render_eval_markdown, render_eval_scorecard, run_eval_cases
from .event_log import append_runtime_event, event_log_stats, export_events, read_runtime_events, render_event_log, replay_summary
from .evidence_court import EVIDENCE_COURT_SCHEMA_VERSION, build_audit_record_from_claude_transcript, build_audit_record_from_codex_transcript, build_audit_record_from_jsonl, build_audit_record_from_openhands_transcript, build_audit_record_from_swe_agent_transcript, build_audit_record_report, build_bad_run_demo_report, build_missing_tests_demo_report, build_out_of_scope_demo_report, dumps_evidence_court_json, evidence_court_verdict, render_evidence_court_report
from .evidence_ledger import load_evidence, record_evidence, render_evidence
from .embedding_provider import (
    EmbeddingJob,
    LocalHashEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    SentenceTransformersEmbeddingProvider,
    embed_batch,
    embedding_cache_path,
    render_embedding_status,
)
from .ecosystem import build_ecosystem_catalog, filter_ecosystem_catalog, render_ecosystem_catalog, write_ecosystem_catalog
from .file_ops import diff_exact_replace_preview, read_preview, replace_exact, search_text, unified_diff_preview, write_text
from .gui_patterns import gui_action_schema, render_mode_notes, target_to_coordinate, targets_from_grid
from .goal_contract import evaluate_goal_guard, load_goal_contract, render_goal_contract, render_goal_guard_decision, save_goal_contract
from .headless_sdk import render_headless_json, render_headless_result, run_headless
from .hermes_learning import learn_from_query_events, render_hermes_learning_report
from .learning_effect import LearningEffectTask, LearningTaskResult, create_learning_command_runner, load_learning_effect_tasks, render_learning_effect_json, run_learning_effect_regression
from .hooks import run_hooks_once
from .hook_runner import HookContext, HookSpec, normalize_hook_event, run_configured_hooks
from .journal import append_journal
from .memory_extract import add_candidates_to_store, extract_from_report, extract_from_tool_loop, extract_memory_candidates
from .memory_sidecar import approve_memory_proposal, deny_memory_proposal, load_memory_proposals, propose_memories, render_memory_proposals
from .memory_store import MemoryStore, render_memories
from .mode_router import render_mode_route, render_mode_router_diagnostics, route_agent_mode, validate_mode_router
from .model_client import ModelClient, ModelRequest
from .multi_agent import create_review_request
from .lsp_diagnostics import detect_default_lsp_servers, load_lsp_snapshot, render_lsp_json, render_lsp_markdown, run_lsp_diagnostics
from .mcp_gateway import gateway_call_tool, gateway_health, load_mcp_gateway, refresh_mcp_gateway, render_mcp_gateway, start_mcp_gateway, stop_mcp_gateway
from .mcp_daemon import (
    McpDaemon,
    daemon_call,
    daemon_catalog,
    recover_mcp_daemon,
    request_mcp_daemon,
    restart_mcp_daemon,
    start_mcp_daemon,
    status_mcp_daemon,
    stop_mcp_daemon,
)
from .mcp_runtime import MCP_MANAGER, build_mcp_schema_snapshot, call_mcp_tool, cleanup_mcp_lease_registry, list_mcp_catalog, load_mcp_servers, render_mcp_servers, render_mcp_tools, start_mcp_daemon_state, status_mcp_daemon_state, stop_mcp_daemon_state
from .permission_debug import explain_permission, recent_permission_denials, render_permission_explanation, render_recent_denials
from .permission_policy_v2 import add_permission_rule_v2, evaluate_permission_v2, lint_permission_policy_v2, load_permission_policy_v2, render_permission_decision, render_permission_lints, save_permission_policy_v2
from .plugin_runtime import build_plugin_install_snapshot, build_plugin_registry, render_plugin_registry, render_plugin_trust_reports, write_plugin_registry
from .policy_gate import enforce_tool
from .diff_review import create_diff_review, render_diff_review_report
from .pr_workflow import create_pr_plan, list_pr_plans, load_pr_plan, render_pr_plan
from .project_rules import load_project_rules, match_project_rules, render_project_rules
from .project import snapshot_project
from .query_runtime import QueryRuntime, load_query_events, render_query_events
from .quant_auditor import audit_target
from .quant_auto_evidence import render_quant_auto_evidence, run_quant_auto_evidence
from .quant_broker_evidence import import_broker_evidence, render_broker_evidence_import, render_broker_evidence_import_json
from .quant_checks import audit_project
from .quant_data_contract import render_quant_data_contract, validate_quant_data_contract
from .quant_data_adapter import discover_quant_data, render_quant_data_adapter
from .quant_data_sample import QuantDataSampleSpec, render_quant_data_sample, sample_local_quant_data
from .quant_execution_gate import QuantExecutionEvidenceSpec, render_quant_execution_gate, run_quant_execution_gate
from .quant_expectations import render_quant_expectations, run_quant_expectations
from .quant_judge import QuantJudgeSpec, render_quant_judge, render_quant_judge_json, run_quant_judge
from .quant_leak_check import render_quant_leak_check, run_quant_leak_check
from .quant_bench import render_quant_bench, render_quant_bench_json, run_quant_bench, score_quant_bench
from .quant_priority import build_quant_priority_review, render_quant_priority_review
from .quant_run_gate import (
    QuantRunSpec,
    build_quant_run_verdict,
    latest_quant_gate_run,
    load_quant_gate_run,
    render_quant_evidence_bundle,
    render_quant_gate_json,
    render_quant_gate_run,
    render_quant_verdict,
    replay_quant_gate,
    run_quant_gate,
)
from .reporting import build_audit_report, build_status_report
from .result_registry import load_registry, render_registry_markdown
from .remote_runner import create_remote_runner_spec, list_remote_runner_specs, load_remote_runner_spec, render_remote_runner_spec
from . import relay as relay_bus
from .repair_scheduler import render_repair_scheduler_result, run_multi_worker_repair
from .retrieval_daemon import (
    build_retrieval_index,
    ensure_retrieval_index,
    load_retrieval_daemon_state,
    related_retrieval_paths,
    render_retrieval_hits,
    render_retrieval_index,
    render_retrieval_state,
    retrieval_health,
    search_retrieval_index,
    start_retrieval_daemon,
    stop_retrieval_daemon,
    write_retrieval_index,
)
from .repo_map import build_repo_map, ensure_repo_map, related_repo_paths, render_repo_context, render_repo_map, render_repo_map_hits, search_repo_map, write_repo_map
from .review_arbitration import arbitrate_parent_reviews, render_arbitration_decision
from .resume import create_resume_snapshot, list_resume_snapshots, load_resume_snapshot, render_resume_snapshot, render_resume_snapshots, resume_agent, resume_last_failure, resume_session, resume_task
from .runtime_store import claim_runtime_queue_item, enqueue_runtime_queue_item, heartbeat_runtime_queue_item, list_runtime_queue_items, resume_runtime_queue_item, stop_runtime_queue_item
from .runtime_ledger import build_runtime_ledger_snapshot, render_runtime_json, render_runtime_ledger, render_runtime_search, search_runtime_ledger
from .safety import SafetyPolicy, assess_command, assess_quant_claim, policy_summary
from .sandbox_policy import classify_tool, render_profiles
from .session_bus import list_bus_messages, render_bus_messages, render_session_bus_state, send_bus_message, session_bus_summary, start_session_bus, status_session_bus, stop_session_bus
from .shell_semantics import classify_shell_command, render_shell_semantics
from .sessions import append_message, close_session, compact_session, create_session, export_session, latest_session, list_sessions, load_session, render_session, render_session_search, search_session_messages
from .skills import install_skill, list_skill_registry, list_skills, select_skills
from .skill_pipeline import SkillEvalResult, approve_skill_proposal, curate_skill_proposals, learning_effect_report_evidence, list_skill_proposals, load_skill_proposal, propose_file_bundle_repair_skill_from_trajectory, propose_skill_from_events, propose_skill_from_trajectory, propose_subject_repair_skill, propose_subject_repair_skill_from_trajectory, reject_skill_proposal, render_skill_proposal, render_skill_proposals, rollback_skill_proposal_install, run_skill_eval_command
from .state import write_project_state
from .source_checks import load_source_checks, render_source_check_results, render_source_checks, run_source_checks, source_check_summary
from .subagents import create_subagent_review_bundle, get_subagent, load_subagents, load_subagent_review_bundles, refresh_subagents, render_subagent_review_bundle, render_subagents, start_subagent, stop_subagent
from .subagent_backends import detect_subagent_backends, render_subagent_backends
from .swarm import render_swarm_run, run_repair_swarm, run_swarm
from .structured_diff_preview import create_preview_from_isolation_review, create_structured_diff_preview, render_structured_diff_preview, save_structured_diff_preview
from .task_runtime import get_runtime_task, read_task_output, refresh_runtime_tasks, render_task_detail, resume_runtime_task, start_agent_task, start_shell_task, stop_runtime_task
from .task_graph import build_task_graph, render_task_graph
from .task_state import VALID_STATUSES, add_task, load_tasks, render_tasks, update_task
from .todo import load_task_plan, load_todos, render_task_plan, save_todos, set_plan_item, set_todo_status
from .tool_loop import run_tool_loop
from .tool_registry import list_tools
from .tool_manifest_v2 import build_tool_manifest_catalog, find_tool_manifest, render_tool_manifest, render_tool_manifest_catalog
from .tool_call_transcript import load_tool_call_trace, list_tool_call_traces, render_tool_call_trace, render_tool_call_traces
from .tool_transcript import load_tool_transcript, list_tool_transcripts, render_tool_transcript, render_tool_transcripts
from .toolsets import render_toolsets
from .tools import run_command_args
from .tui_status_model import build_tui_status_model, render_tui_status_json, render_tui_status_model
from .ux_status import build_ux_status, render_ux_status, render_ux_status_json
from .validation import validate_project_scripts
from .workspace_trust import ensure_workspace_trusted
from .worktree_isolation import apply_isolation_review, create_isolated_worktree, create_isolation_review, list_isolated_worktrees, load_isolated_worktree, load_isolation_review, remove_isolated_worktree, render_isolated_worktree, render_isolated_worktrees, render_isolation_review, run_in_isolated_worktree


def cmd_status(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    snapshot = snapshot_project(config.project, config.communication_dir_name)
    print(build_status_report(config.project))
    if args.preview and snapshot.claude_md:
        print("## CLAUDE.md Preview")
        print(snapshot.claude_md.read_text(encoding="utf-8", errors="replace")[:2000])
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    if args.hooks:
        event = run_hooks_once(config.project, force=args.force)
        latest = event.latest_file.name if event.latest_file else "none"
        print(f"{event.action}: {latest}")
        return 0
    snapshot = snapshot_project(config.project, config.communication_dir_name)
    print("Latest communication files:")
    for path in snapshot.latest_messages[: args.limit]:
        print(f"- {path.stat().st_mtime:.0f} {path.name}")
    return 0


def cmd_agent_autopsy(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    run_result = None
    if args.run_command is not None:
        command = [item for item in args.run_command if item != "--"]
        if not command:
            print("agent-autopsy error: --run requires a command")
            return 2
        run_result = run_agent_autopsy_command(
            config.project,
            command,
            source_agent=args.source_agent,
            title=args.title,
            timeout=args.timeout,
        )
        report = run_result.report
    else:
        report = build_agent_autopsy(
            config.project,
            trajectory_path=args.trajectory,
            query_events_path=args.query_events,
            failure_file=args.failure_file,
            failure_text=args.failure,
            source_agent=args.source_agent,
            title=args.title,
            command=args.command_line,
            limit=args.limit,
        )
    if args.output:
        write_agent_autopsy(report, args.output)
    if args.json:
        if run_result is not None:
            print(json.dumps(run_result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(dumps_agent_autopsy_json(report))
    else:
        print(render_agent_autopsy(report), end="")
        if run_result is not None:
            print(f"Wrapped command exit_code: {run_result.exit_code}")
        if args.output:
            print(f"\nWrote autopsy report: {Path(args.output).expanduser().resolve(strict=False)}")
    return 0


def cmd_evidence_court(args: argparse.Namespace) -> int:
    if args.evidence_court_command == "record" and args.record_command == "from-jsonl":
        try:
            record = build_audit_record_from_jsonl(args.events)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"evidence-court error: {exc}", file=sys.stderr)
            return 2
        record_json = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            Path(args.output).expanduser().resolve(strict=False).write_text(record_json, encoding="utf-8")
        else:
            print(record_json, end="")
        return 0
    if args.evidence_court_command == "record" and args.record_command == "from-codex-transcript":
        try:
            record = build_audit_record_from_codex_transcript(args.transcript)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"evidence-court error: {exc}", file=sys.stderr)
            return 2
        record_json = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            Path(args.output).expanduser().resolve(strict=False).write_text(record_json, encoding="utf-8")
        else:
            print(record_json, end="")
        return 0
    if args.evidence_court_command == "record" and args.record_command == "from-claude-transcript":
        try:
            record = build_audit_record_from_claude_transcript(args.transcript)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"evidence-court error: {exc}", file=sys.stderr)
            return 2
        record_json = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            Path(args.output).expanduser().resolve(strict=False).write_text(record_json, encoding="utf-8")
        else:
            print(record_json, end="")
        return 0
    if args.evidence_court_command == "record" and args.record_command == "from-openhands-transcript":
        try:
            record = build_audit_record_from_openhands_transcript(args.transcript)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"evidence-court error: {exc}", file=sys.stderr)
            return 2
        record_json = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            Path(args.output).expanduser().resolve(strict=False).write_text(record_json, encoding="utf-8")
        else:
            print(record_json, end="")
        return 0
    if args.evidence_court_command == "record" and args.record_command == "from-swe-agent-transcript":
        try:
            record = build_audit_record_from_swe_agent_transcript(args.transcript)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"evidence-court error: {exc}", file=sys.stderr)
            return 2
        record_json = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            Path(args.output).expanduser().resolve(strict=False).write_text(record_json, encoding="utf-8")
        else:
            print(record_json, end="")
        return 0
    if args.evidence_court_command == "audit":
        try:
            report = build_audit_record_report(args.record)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"evidence-court error: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(dumps_evidence_court_json(report), end="")
        else:
            print(render_evidence_court_report(report), end="")
        if args.ci and _evidence_court_ci_failed(evidence_court_verdict(report), args.fail_on):
            return 1
        return 0
    if args.evidence_court_command == "validate":
        try:
            build_audit_record_report(args.record)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"evidence-court error: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(
                json.dumps(
                    {
                        "schema_version": EVIDENCE_COURT_SCHEMA_VERSION,
                        "status": "accepted",
                        "record": str(Path(args.record).expanduser().resolve(strict=False)),
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print("record accepted")
        return 0
    if args.evidence_court_command == "demo" and args.demo_command == "bad-run":
        try:
            report = build_bad_run_demo_report(args.project)
        except FileNotFoundError as exc:
            print(f"evidence-court error: {exc}", file=sys.stderr)
            return 2
        print(render_evidence_court_report(report), end="")
        return 0
    if args.evidence_court_command == "demo" and args.demo_command == "missing-tests":
        print(render_evidence_court_report(build_missing_tests_demo_report()), end="")
        return 0
    if args.evidence_court_command == "demo" and args.demo_command == "out-of-scope":
        print(render_evidence_court_report(build_out_of_scope_demo_report()), end="")
        return 0
    print("evidence-court error: unsupported command", file=sys.stderr)
    return 2


def _evidence_court_ci_failed(verdict: str, fail_on: str) -> bool:
    return verdict == "FAIL" or (fail_on == "suspicious" and verdict == "SUSPICIOUS")


def cmd_hooks(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    profiles = load_agent_profile_config(config.project)
    try:
        if args.hooks_command == "list":
            specs = _hook_specs_for_profile(profiles, args.profile)
            if args.json:
                print(json.dumps([spec.to_dict() for spec in specs], ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(_render_hook_specs(specs, profile=args.profile), end="")
            return 0
        if args.hooks_command == "run":
            payload = json.loads(args.payload_json or "{}")
            if not isinstance(payload, dict):
                print("hooks error: --payload-json must be an object")
                return 2
            specs = _hook_specs_for_profile(profiles, args.profile)
            if args.command:
                specs.append(
                    HookSpec(
                        event=args.event,
                        command=args.command,
                        matcher=args.matcher,
                        timeout_ms=args.timeout_ms,
                        priority=args.priority,
                        failure_policy="fail_closed" if args.fail_closed else "fail_open",
                    )
                )
            result = run_configured_hooks(
                config.project,
                args.event,
                payload,
                specs,
                HookContext(project=str(config.project), plugin_id=args.profile or "cli"),
            )
            if args.json:
                print(json.dumps(result.__dict__, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(_render_hook_run_result(result), end="")
            return 1 if result.blocked else 0
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"hooks error: {exc}")
        return 2
    print("hooks error: unknown command")
    return 2


def cmd_rules(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    paths = args.path or []
    rules = match_project_rules(config.project, paths) if paths else load_project_rules(config.project)
    if args.json:
        print(json.dumps([asdict(rule) for rule in rules], ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_project_rules(rules), end="")
    return 0


def _hook_specs_for_profile(profiles: Any, profile_name: str) -> list[HookSpec]:
    if not profile_name:
        return []
    profile = profiles.agents.get(profile_name)
    if profile is None:
        raise KeyError(profile_name)
    return _hook_specs_from_raw(profile.hooks)


def _hook_specs_from_raw(raw: Any) -> list[HookSpec]:
    specs: list[HookSpec] = []
    if not raw:
        return specs
    if isinstance(raw, list):
        for item in raw:
            specs.extend(_hook_specs_from_item("", item))
        return specs
    if isinstance(raw, dict):
        for event, value in raw.items():
            specs.extend(_hook_specs_from_item(str(event), value))
    return specs


def _hook_specs_from_item(event: str, raw: Any) -> list[HookSpec]:
    if isinstance(raw, list):
        specs: list[HookSpec] = []
        for item in raw:
            specs.extend(_hook_specs_from_item(event, item))
        return specs
    if isinstance(raw, dict):
        payload = dict(raw)
        payload.setdefault("event", event)
        return [HookSpec.from_mapping(payload)]
    if isinstance(raw, str):
        return [HookSpec(event=event, command=raw)]
    return []


def _render_hook_specs(specs: list[HookSpec], *, profile: str) -> str:
    if not specs:
        return f"No configured hooks for profile {profile}.\n"
    lines = [f"# Hooks for {profile}", ""]
    for spec in specs:
        matcher = f" matcher={spec.matcher}" if spec.matcher else ""
        async_note = " async" if spec.async_ else ""
        lines.append(f"- {normalize_hook_event(spec.event)} priority={spec.priority}{matcher}{async_note}: {spec.command}")
    return "\n".join(lines) + "\n"


def _render_hook_run_result(result: Any) -> str:
    lines = [
        f"# Hook Run {result.event}",
        "",
        f"- blocked: {result.blocked}",
        f"- handled: {result.handled}",
        f"- summaries: {len(result.summaries)}",
        f"- errors: {len(result.errors)}",
    ]
    if result.summaries:
        lines.extend(["", "## Summaries", *[f"- {item}" for item in result.summaries]])
    if result.errors:
        lines.extend(["", "## Errors", *[f"- {item}" for item in result.errors]])
    lines.extend(["", "## Payload", "", json.dumps(result.payload, ensure_ascii=False, indent=2, sort_keys=True)])
    return "\n".join(lines).rstrip() + "\n"


def _json_arg(value: str | None, *, default: Any) -> Any:
    if value is None or value == "":
        return default
    parsed = json.loads(value)
    return parsed


def _non_negative_finite_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a finite non-negative number") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be a finite non-negative number")
    return parsed


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a non-negative integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def _render_event_stats(stats: dict[str, Any]) -> str:
    lines = [
        "# Mako Event Stats",
        "",
        f"- count: {stats.get('count', 0)}",
        f"- first_timestamp_ms: {stats.get('first_timestamp_ms') or ''}",
        f"- last_timestamp_ms: {stats.get('last_timestamp_ms') or ''}",
        "",
        "## By Kind",
        "",
    ]
    for key, value in (stats.get("by_kind") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## By Status", ""])
    for key, value in (stats.get("by_status") or {}).items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines) + "\n"


def cmd_audit(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    if args.deep or args.target:
        target = Path(args.target).expanduser() if args.target else None
        findings = audit_target(config.project, target)
        if not findings:
            print("No findings from QuantAuditor.")
        else:
            for finding in findings:
                path = f" ({finding.path})" if finding.path else ""
                print(f"- [{finding.level}] {finding.title}{path}: {finding.detail}")
    else:
        findings = audit_project(config.project)
        print(build_audit_report(config.project))
    return 1 if any(f.level == "error" for f in findings) else 0


def cmd_quant(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.quant_command == "check":
            answer = args.answer or ""
            if args.answer_file:
                path = Path(args.answer_file).expanduser()
                if not path.is_absolute():
                    path = config.project / path
                answer = path.read_text(encoding="utf-8", errors="replace")
            review = build_quant_priority_review(
                config.project,
                args.task or "",
                answer=answer,
                audit=not args.no_audit,
            )
            print(json.dumps(review.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_quant_priority_review(review), end="" if not args.json else "\n")
            return 0 if review.ok else 1
        if args.quant_command == "data-contract":
            result = validate_quant_data_contract(
                args.path,
                kind=args.kind,
                strict_dedup=args.strict_dedup,
            )
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_quant_data_contract(result), end="" if not args.json else "\n")
            return 0 if result.ok else 1
        if args.quant_command == "data-adapter":
            result = discover_quant_data(
                config.project,
                args.root or (),
                max_files=args.max_files,
                sample_zip_members=args.sample_zip_members,
            )
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_quant_data_adapter(result), end="" if not args.json else "\n")
            return 0 if result.artifacts else 1
        if args.quant_command == "expectations":
            result = run_quant_expectations(
                args.path,
                kind=args.kind,
                sample_rows=args.sample_rows,
                hash_bytes=args.hash_bytes,
            )
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_quant_expectations(result), end="" if not args.json else "\n")
            return 0 if result.ok else 1
        if args.quant_command == "data-sample":
            result = sample_local_quant_data(
                config.project,
                QuantDataSampleSpec(
                    root=args.root,
                    code=args.code,
                    kind=args.kind,
                    freq=args.freq,
                    adjust=args.adjust,
                    date=args.date or "",
                    start=args.start or "",
                    end=args.end or "",
                    max_rows=args.max_rows,
                    output_path=args.output or "",
                ),
            )
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_quant_data_sample(result), end="" if not args.json else "\n")
            return 0 if result.ok else 1
        if args.quant_command == "auto-evidence":
            result = run_quant_auto_evidence(
                config.project,
                args.task or "",
                input_path=args.input or "",
                strategy_roots=args.strategy_root or (),
                data_roots=args.data_root or (),
                code=args.code or "",
                date=args.date or "",
                execution_source=args.execution_source or "",
                max_files=args.max_files,
                sample_zip_members=args.sample_zip_members,
                max_rows=args.max_rows,
                strict_dedup=not args.no_strict_dedup,
            )
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_quant_auto_evidence(result), end="" if not args.json else "\n")
            return 0 if result.ok else 1
        if args.quant_command == "execution-gate":
            result = run_quant_execution_gate(
                config.project,
                QuantExecutionEvidenceSpec(
                    tick_path=args.tick or "",
                    fill_path=args.fill or "",
                    broker_path=args.broker or "",
                    order_path=args.order or "",
                    position_path=args.position or "",
                    account_path=args.account or "",
                    slippage_path=args.slippage or "",
                    capacity_path=args.capacity or "",
                    execution_source=args.execution_source or "",
                ),
            )
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_quant_execution_gate(result), end="" if not args.json else "\n")
            return 0 if result.live_ready else 1
        if args.quant_command == "broker-gateway":
            result = build_broker_gateway_snapshot(
                config.project,
                BrokerGatewaySpec(
                    broker_path=args.broker or "",
                    fill_path=args.fill or "",
                    order_path=args.order or "",
                    position_path=args.position or "",
                    account_path=args.account or "",
                    source=args.source or "",
                    gateway=args.gateway or "",
                ),
            )
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_broker_gateway_snapshot(result), end="" if not args.json else "\n")
            return 0 if result.ok else 1
        if args.quant_command == "broker-import":
            result = import_broker_evidence(
                config.project,
                args.path or (),
                source=args.source or "",
                broker_name=args.broker_name or "",
                output_dir=args.output_dir or "",
                max_files=args.max_files,
                max_rows_per_file=args.max_rows,
                redact_accounts=not args.no_redact,
            )
            print(render_broker_evidence_import_json(result) if args.json else render_broker_evidence_import(result), end="")
            return 0 if result.ok else 1
        if args.quant_command == "leak-check":
            result = run_quant_leak_check(args.path, max_files=args.max_files)
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_quant_leak_check(result), end="" if not args.json else "\n")
            return 0 if result.ok else 1
        if args.quant_command == "bench":
            run = run_quant_bench(config.project, keep_workspace=args.keep_workspace)
            print(render_quant_bench_json(run) if args.json else render_quant_bench(run), end="")
            summary = score_quant_bench(run)
            return 0 if summary["score"] == summary["max_score"] else 1
        if args.quant_command == "run":
            input_path = Path(args.input).expanduser()
            name = args.name or input_path.stem
            spec = QuantRunSpec(
                name=name,
                input_path=str(input_path),
                return_col=args.return_col,
                date_col=args.date_col,
                threshold_col=args.threshold_col or "",
                threshold_lte=args.threshold,
                data_kind=args.kind,
                strict_dedup=not args.no_strict_dedup,
                oos_start=args.oos_start or "",
                oos_end=args.oos_end or "",
                fees_bps=args.fees_bps,
                slippage_bps=args.slippage_bps,
                capacity_notes=args.capacity_notes or "",
                execution_source=args.execution_source or "",
                tick_path=args.tick or "",
                fill_path=args.fill or "",
                broker_path=args.broker or "",
                order_path=args.order or "",
                position_path=args.position or "",
                account_path=args.account or "",
                slippage_path=args.slippage or "",
                capacity_path=args.capacity or "",
                assumptions=tuple(args.assumption or ()),
            )
            run = run_quant_gate(config.project, spec)
            print(render_quant_gate_json(run) if args.json else render_quant_gate_run(run), end="")
            return 0 if run.verdict.ok else 1
        if args.quant_command == "evidence":
            run = load_quant_gate_run(config.project, args.gate_id) if args.gate_id else latest_quant_gate_run(config.project)
            if run is None:
                print("quant error: no quant run gate evidence found; run `mako quant run` first")
                return 1
            print(json.dumps(run.evidence_bundle.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n" if args.json else render_quant_evidence_bundle(run.evidence_bundle), end="")
            return 0 if run.evidence_bundle.research_ready else 1
        if args.quant_command == "live-status":
            run = load_quant_gate_run(config.project, args.gate_id) if args.gate_id else latest_quant_gate_run(config.project)
            if run is None:
                print("quant error: no quant live evidence found; run `mako quant run` first")
                return 1
            payload = _quant_live_status_payload(run)
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n" if args.json else _render_quant_live_status(payload), end="")
            return 0 if payload["live_ready"] else 1
        if args.quant_command == "verdict":
            run = load_quant_gate_run(config.project, args.gate_id) if args.gate_id else latest_quant_gate_run(config.project)
            if run is None:
                print("quant error: no quant run gate verdict found; run `mako quant run` first")
                return 1
            verdict = build_quant_run_verdict(run.evidence_bundle, task=args.task or "", answer=args.answer or "") if (args.task or args.answer) else run.verdict
            print(json.dumps(verdict.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n" if args.json else render_quant_verdict(verdict), end="")
            return 0 if verdict.ok else 1
        if args.quant_command == "replay":
            run = replay_quant_gate(config.project, args.gate_id or "")
            print(render_quant_gate_json(run) if args.json else render_quant_gate_run(run), end="")
            return 0 if run.verdict.ok else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"quant error: {exc}")
        return 2
    print("quant error: unknown command")
    return 2


def _quant_live_status_payload(run: Any) -> dict[str, Any]:
    bundle = run.evidence_bundle
    execution_gate = dict(bundle.execution_gate or {})
    artifacts = [item for item in execution_gate.get("artifacts") or [] if isinstance(item, dict)]
    issues = [item for item in execution_gate.get("issues") or [] if isinstance(item, dict)]
    blockers = [item for item in issues if str(item.get("level") or "").lower() == "block"]
    required = [str(item) for item in execution_gate.get("required_evidence") or ("tick", "fill", "broker", "slippage", "capacity")]
    present = sorted({str(item.get("evidence_type") or "") for item in artifacts if item.get("exists") and item.get("evidence_type")})
    missing = sorted(
        {
            str(item.get("evidence_type") or "")
            for item in blockers
            if str(item.get("code") or "") in {"missing_evidence_path", "missing_evidence_file", "file_not_found", "empty_file", "directory_not_file"}
            and item.get("evidence_type")
        }
    )
    return {
        "gate_id": run.gate_id,
        "run_id": bundle.run_id,
        "research_ready": bundle.research_ready,
        "live_ready": bundle.live_ready,
        "action": "pass" if bundle.live_ready else "block",
        "execution_source": bundle.execution_source or str(execution_gate.get("execution_source") or ""),
        "required_evidence": required,
        "present_evidence": present,
        "missing_evidence": missing,
        "blockers": blockers,
        "artifact_count": len(artifacts),
    }


def _render_quant_live_status(payload: dict[str, Any]) -> str:
    lines = [
        "# Quant Live Status",
        "",
        f"- action: {payload['action']}",
        f"- research_ready: {str(payload['research_ready']).lower()}",
        f"- live_ready: {str(payload['live_ready']).lower()}",
        f"- gate_id: {payload['gate_id']}",
        f"- run_id: {payload['run_id'] or '-'}",
        f"- execution_source: {payload['execution_source'] or '-'}",
        f"- required_evidence: {', '.join(payload['required_evidence']) or '-'}",
        f"- present_evidence: {', '.join(payload['present_evidence']) or '-'}",
        f"- missing_evidence: {', '.join(payload['missing_evidence']) or '-'}",
        "",
        "## Blockers",
        "",
    ]
    blockers = payload.get("blockers") or []
    if not blockers:
        lines.append("- none")
    for issue in blockers:
        evidence_type = issue.get("evidence_type") or "-"
        code = issue.get("code") or "block"
        message = issue.get("message") or ""
        lines.append(f"- {evidence_type}: {code} - {message}")
    return "\n".join(lines).rstrip() + "\n"


def cmd_judge(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    target = str(args.target or "").strip()
    scenario = args.scenario
    input_path = args.input or ""
    if target and not input_path:
        if target.upper() in {"A", "D"}:
            scenario = target.upper()
        else:
            input_path = target
    result = run_quant_judge(
        config.project,
        QuantJudgeSpec(
            scenario=scenario,
            input_path=input_path,
            name=args.name or "",
            return_col=args.return_col,
            date_col=args.date_col,
            threshold_col=args.threshold_col,
            threshold_lte=args.threshold,
            data_kind=args.kind,
            strict_dedup=not args.no_strict_dedup,
            oos_start=args.oos_start or "",
            oos_end=args.oos_end or "",
            fees_bps=args.fees_bps,
            slippage_bps=args.slippage_bps,
            capacity_notes=args.capacity_notes or "",
            execution_source=args.execution_source or "",
            tick_path=args.tick or "",
            fill_path=args.fill or "",
            broker_path=args.broker or "",
            order_path=args.order or "",
            position_path=args.position or "",
            account_path=args.account or "",
            slippage_path=args.slippage or "",
            capacity_path=args.capacity or "",
            assumptions=tuple(args.assumption or ()),
        ),
    )
    print(render_quant_judge_json(result) if args.json else render_quant_judge(result), end="")
    return 0 if result.ok else 1


def cmd_report(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    report = build_status_report(config.project) + "\n" + build_audit_report(config.project)
    out_dir = config.communication_dir if config.communication_dir.exists() else config.project
    out_path = out_dir / "QUANTAGENT_STATUS_REPORT.md"
    out_path.write_text(report, encoding="utf-8")
    print(out_path)
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    if args.ref:
        refs = []
        for item in args.ref:
            refs.extend(parse_context_refs(item) or [item])
        results = gather_context_providers(config.project, refs, limit=args.limit)
        if args.json:
            print(json.dumps([result.to_dict() for result in results], ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(render_context_provider_results(results), end="")
        return 0 if all(result.ok for result in results) else 1
    pack = build_context_pack(config.project, task=args.task)
    if args.write:
        out_dir = config.communication_dir if config.communication_dir.exists() else config.project
        out_path = out_dir / "QUANTAGENT_CONTEXT_PACK.md"
        manifest_path = out_dir / "QUANTAGENT_CONTEXT_MANIFEST.json"
        out_path.write_text(pack.text, encoding="utf-8")
        manifest_path.write_text(
            json.dumps(
                {
                    "project": str(pack.project),
                    "char_budget": pack.char_budget,
                    "chars_used": pack.chars_used,
                    "token_budget": pack.token_budget,
                    "estimated_tokens": pack.estimated_tokens,
                    "budget_summary": pack.budget_summary(),
                    "sections": pack.sections,
                    "sources": [str(path) for path in pack.sources],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(out_path)
        print(manifest_path)
    else:
        print(pack.text)
    return 0


def cmd_cheap(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    plan = build_cheap_plan(config.project, " ".join(args.task or ()))
    if args.json:
        print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_cheap_plan(plan), end="")
    return 0


def cmd_architect(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.architect_command == "plan":
            plan = create_architect_plan(
                config.project,
                args.task,
                paths=args.path or (),
                tests=[args.test] if args.test else (),
                context_refs=args.ref or (),
            )
            print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_architect_plan(config.project, plan, include_context=args.context))
            return 0
        if args.architect_command == "list":
            plans = list_architect_plans(config.project, limit=args.limit)
            if args.json:
                print(json.dumps([plan.to_dict() for plan in plans], ensure_ascii=False, indent=2, sort_keys=True))
            else:
                for plan in plans:
                    print(f"{plan.plan_id}\t{plan.created_at}\t{plan.task}")
            return 0
        if args.architect_command == "show":
            plan = load_architect_plan(config.project, args.plan_id)
            print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_architect_plan(config.project, plan, include_context=args.context))
            return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"architect error: {exc}")
        return 2
    print("architect error: unknown command")
    return 2


def cmd_pr(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.pr_command == "plan":
            plan = create_pr_plan(
                config.project,
                args.task,
                title=args.title or "",
                base_branch=args.base_branch or "",
                branch=args.branch or "",
                tests=[args.test] if args.test else (),
            )
            print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_pr_plan(plan))
            return 0
        if args.pr_command == "list":
            plans = list_pr_plans(config.project, limit=args.limit)
            if args.json:
                print(json.dumps([plan.to_dict() for plan in plans], ensure_ascii=False, indent=2, sort_keys=True))
            else:
                for plan in plans:
                    print(f"{plan.pr_id}\t{plan.branch}\t{plan.title}")
            return 0
        if args.pr_command == "show":
            plan = load_pr_plan(config.project, args.pr_id)
            print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_pr_plan(plan))
            return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"pr error: {exc}")
        return 2
    print("pr error: unknown command")
    return 2


def cmd_runner(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.runner_command == "plan":
            spec = create_remote_runner_spec(
                config.project,
                args.task,
                setup_commands=args.setup or (),
                run_commands=args.run or (),
                network_allowlist=args.allow_network or (),
                secrets_required=args.secret or (),
                timeout_minutes=args.timeout_minutes,
            )
            print(json.dumps(spec.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_remote_runner_spec(spec))
            return 0
        if args.runner_command == "list":
            specs = list_remote_runner_specs(config.project, limit=args.limit)
            if args.json:
                print(json.dumps([spec.to_dict() for spec in specs], ensure_ascii=False, indent=2, sort_keys=True))
            else:
                for spec in specs:
                    print(f"{spec.runner_id}\t{spec.timeout_minutes}m\t{spec.task}")
            return 0
        if args.runner_command == "show":
            spec = load_remote_runner_spec(config.project, args.runner_id)
            print(json.dumps(spec.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_remote_runner_spec(spec))
            return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"runner error: {exc}")
        return 2
    print("runner error: unknown command")
    return 2


def cmd_query_events(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    events = load_query_events(config.project)
    print(render_query_events(events, limit=args.limit))
    return 0


def cmd_ux(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    if args.ux_command == "status":
        status = build_ux_status(
            config.project,
            task=args.task or "",
            limit=args.limit,
            include_context_pack=not args.no_context_pack,
        )
        QueryRuntime(config.project).emit(
            "ux_status",
            "rendered unified UX status",
            ok=True,
            data={
                "pending_approvals": len(status.approvals),
                "tools": len(status.tools),
                "reviews": len(status.reviews),
                "checkpoints": len(status.checkpoints),
                "context_mode": status.context.mode,
                "estimated_tokens": status.context.estimated_tokens,
                "token_budget": status.context.token_budget,
            },
        )
        print(render_ux_status_json(status) if args.json else render_ux_status(status), end="")
        return 0
    print("ux error: unknown command")
    return 2


def cmd_tools(args: argparse.Namespace) -> int:
    for tool in list_tools():
        print(f"{tool.name}\t{tool.risk}\t{tool.description}")
    return 0


def cmd_event_log(args: argparse.Namespace) -> int:
    project = load_config(args.project).project
    if args.event_log_command == "append":
        data = _json_arg(args.data, default={})
        event = append_runtime_event(
            project,
            kind=args.kind,
            summary=args.summary,
            status=args.status,
            session_id=args.session_id or "",
            task_id=args.task_id or "",
            correlation_id=args.correlation_id or "",
            tool=args.tool or "",
            data=data,
            artifacts=args.artifact or (),
        )
        print(json.dumps(event.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    events = read_runtime_events(
        project,
        kind=getattr(args, "kind", None),
        status=getattr(args, "status", None),
        session_id=getattr(args, "session_id", None),
        task_id=getattr(args, "task_id", None),
        correlation_id=getattr(args, "correlation_id", None),
        limit=getattr(args, "limit", 200),
    )
    if args.event_log_command == "list":
        if args.json:
            print(json.dumps([event.to_dict() for event in events], ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(render_event_log(events, limit=args.limit), end="")
        return 0
    if args.event_log_command == "stats":
        stats = event_log_stats(events)
        print(json.dumps(stats.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else _render_event_stats(stats.to_dict()))
        return 0
    if args.event_log_command == "replay":
        print(replay_summary(events, max_lines=args.limit))
        return 0
    if args.event_log_command == "export":
        print(export_events(events, output_format=args.format), end="")
        return 0
    print("event-log error: unknown command")
    return 2


def cmd_tool_manifest(args: argparse.Namespace) -> int:
    project = load_config(args.project).project
    catalog = build_tool_manifest_catalog(project)
    if args.tool_manifest_command == "list":
        if args.json:
            print(json.dumps(catalog.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(render_tool_manifest_catalog(catalog), end="")
        return 0
    if args.tool_manifest_command == "show":
        print(render_tool_manifest(find_tool_manifest(catalog, args.name)), end="")
        return 0
    if args.tool_manifest_command == "lint":
        diagnostics = [item.to_dict() for item in catalog.diagnostics]
        if args.json:
            print(json.dumps(diagnostics, ensure_ascii=False, indent=2, sort_keys=True))
        elif diagnostics:
            for item in catalog.diagnostics:
                print(f"[{item.level}] {item.tool}: {item.message}")
        else:
            print("No tool manifest v2 issues.")
        return 1 if any(item.level == "error" for item in catalog.diagnostics) else 0
    if args.tool_manifest_command == "export":
        print(json.dumps(catalog.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print("tool-manifest error: unknown command")
    return 2


def cmd_policy_v2(args: argparse.Namespace) -> int:
    project = load_config(args.project).project
    if args.policy_v2_command == "init":
        policy = load_permission_policy_v2(project)
        path = save_permission_policy_v2(project, policy)
        print(path)
        return 0
    policy = load_permission_policy_v2(project)
    if args.policy_v2_command == "lint":
        lints = lint_permission_policy_v2(policy)
        if args.json:
            print(json.dumps([item.to_dict() for item in lints], ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(render_permission_lints(lints), end="")
        return 1 if any(item.level == "error" for item in lints) else 0
    if args.policy_v2_command == "evaluate":
        decision = evaluate_permission_v2(project, tool=args.tool, args=_json_arg(args.args_json, default={}))
        if args.json:
            print(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(render_permission_decision(decision), end="")
        return 0
    if args.policy_v2_command == "add-rule":
        policy, rule = add_permission_rule_v2(
            project,
            action=args.action,
            tool=args.tool,
            arg_contains=args.arg_contains or (),
            risk=args.risk or "",
            priority=args.priority,
            reason=args.reason or "",
            allow_always=args.allow_always,
            rule_id=args.rule_id or "",
        )
        if args.json:
            print(json.dumps({"path": policy.source_path, "rule": rule.to_dict()}, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"added {rule.rule_id} {rule.action} tool={rule.tool} priority={rule.priority}")
        return 0
    if args.policy_v2_command == "show":
        print(json.dumps(policy.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print("policy-v2 error: unknown command")
    return 2


def cmd_task_graph(args: argparse.Namespace) -> int:
    project = load_config(args.project).project
    graph = build_task_graph(project, limit=args.limit)
    if args.json:
        print(json.dumps(graph.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_task_graph(graph), end="")
    return 0


def _runtime_queue_payload(item: Any | None, *, action: str, ok: bool = True, status: str = "ok") -> dict[str, Any]:
    return {
        "ok": ok,
        "action": action,
        "status": status,
        "task": item.to_dict() if item is not None and hasattr(item, "to_dict") else item,
    }


def _print_runtime_queue_payload(payload: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    task = payload.get("task")
    if task is None:
        print(f"{payload.get('action')}: {payload.get('status')}")
        return
    if isinstance(task, list):
        for item in task:
            print(f"{item.get('task_id') or item.get('id')} {item.get('status')} {item.get('task')}")
        return
    if isinstance(task, dict):
        print(f"{task.get('task_id') or task.get('id')} {task.get('status')} {task.get('task')}")
        return
    print(str(task))


def cmd_runtime_queue(args: argparse.Namespace) -> int:
    project = load_config(args.project).project
    try:
        if args.runtime_queue_command == "list":
            items = list_runtime_queue_items(project, queue=args.queue, status=args.status or None, limit=args.limit)
            payload = {"ok": True, "action": "list", "status": "ok", "task": [item.to_dict() for item in items], "count": len(items)}
            _print_runtime_queue_payload(payload, json_output=args.json)
            return 0
        if args.runtime_queue_command == "enqueue":
            metadata = _json_arg(args.metadata_json, default={})
            item = enqueue_runtime_queue_item(
                project,
                item_id=args.item_id or None,
                task=args.task,
                queue=args.queue,
                task_kind=args.task_kind,
                payload=metadata | {"goal": args.task},
                priority=args.priority,
                max_attempts=args.max_attempts,
                stop_file=args.stop_file,
                session_lock_key=args.session_lock_key,
                resume_of=args.resume_of,
            )
            _print_runtime_queue_payload(_runtime_queue_payload(item, action="enqueue"), json_output=args.json)
            return 0
        if args.runtime_queue_command == "claim":
            item = claim_runtime_queue_item(project, queue=args.queue, lease_owner=args.worker_id, lease_seconds=args.lease_seconds)
            payload = _runtime_queue_payload(item, action="claim", ok=item is not None, status="running" if item else "empty")
            _print_runtime_queue_payload(payload, json_output=args.json)
            return 0 if item is not None else 1
        if args.runtime_queue_command == "heartbeat":
            item = heartbeat_runtime_queue_item(project, args.task_id, lease_owner=args.worker_id, lease_seconds=args.lease_seconds)
            _print_runtime_queue_payload(_runtime_queue_payload(item, action="heartbeat", status=item.status), json_output=args.json)
            return 0
        if args.runtime_queue_command == "stop":
            item = stop_runtime_queue_item(project, args.task_id, lease_owner=args.worker_id or None, reason=args.reason)
            _print_runtime_queue_payload(_runtime_queue_payload(item, action="stop", status=item.status), json_output=args.json)
            return 0
        if args.runtime_queue_command == "resume":
            item = resume_runtime_queue_item(project, args.task_id)
            _print_runtime_queue_payload(_runtime_queue_payload(item, action="resume", status=item.status), json_output=args.json)
            return 0
    except (ValueError, json.JSONDecodeError) as exc:
        payload = {"ok": False, "action": getattr(args, "runtime_queue_command", "queue"), "status": "error", "error": str(exc)}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"runtime queue error: {exc}")
        return 2
    print("runtime queue error: unknown command")
    return 2


def _json_arg(raw: str, *, default: dict[str, Any]) -> dict[str, Any]:
    if not raw:
        return dict(default)
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("JSON argument must be an object")
    return payload


def _print_channel_payload(value: Any, *, json_output: bool) -> None:
    payload = _payload_from_result(value)
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                print(f"{item.get('event_id', '')} {item.get('status', '')} {item.get('channel', '')}:{item.get('sender', '')}".strip())
            else:
                print(item)
        return
    if isinstance(payload, dict):
        parts = [str(payload.get("status") or "")]
        if payload.get("owner_key"):
            parts.append(str(payload["owner_key"]))
        if payload.get("item_id"):
            parts.append(str(payload["item_id"]))
        if payload.get("message"):
            parts.append(str(payload["message"]))
        print(" ".join(part for part in parts if part))
        return
    print(str(payload))


def cmd_channel(args: argparse.Namespace) -> int:
    project = load_config(args.project).project
    try:
        if args.channel_command == "pair-code":
            result = create_pairing_code(
                project,
                owner_key=args.owner_key,
                channel=args.channel,
                agent_id=args.agent_id,
                ttl_seconds=args.ttl_seconds,
            )
            _print_channel_payload(result, json_output=args.json)
            return 0
        if args.channel_command == "pair":
            result = pair_sender(project, channel=args.channel, sender=args.sender, code=args.code)
            _print_channel_payload(result, json_output=args.json)
            return 0 if result.ok else 1
        if args.channel_command == "resolve":
            result = resolve_sender_owner(project, channel=args.channel, sender=args.sender)
            _print_channel_payload(result, json_output=args.json)
            return 0 if result.ok else 1
        if args.channel_command == "bind-agent":
            result = bind_sender_agent(project, channel=args.channel, sender=args.sender, agent_id=args.agent_id)
            _print_channel_payload(result, json_output=args.json)
            return 0 if result.ok else 1
        if args.channel_command == "bindings":
            bindings = list_channel_bindings(project)
            _print_channel_payload([binding.to_dict() for binding in bindings], json_output=args.json)
            return 0
        if args.channel_command == "send":
            policy = _json_arg(args.policy_json, default={}) if args.policy_json else None
            result = handle_channel_message(
                project,
                channel=args.channel,
                sender=args.sender,
                text=args.text,
                policy=policy,
                allow_execute=False,
                queue=args.queue,
            )
            _print_channel_payload(result, json_output=args.json)
            return 0 if result.ok else 1
        if args.channel_command == "events":
            events = list_channel_gateway_events(project, limit=args.limit)
            _print_channel_payload([event.to_dict() for event in events], json_output=args.json)
            return 0
    except (ValueError, json.JSONDecodeError) as exc:
        payload = {"ok": False, "status": "error", "error": str(exc), "action": getattr(args, "channel_command", "channel")}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"channel error: {exc}")
        return 2
    print("channel error: unknown command")
    return 2


def cmd_agent_gateway(args: argparse.Namespace) -> int:
    project = load_config(args.project).project
    status = build_agent_gateway_status(project, event_limit=args.event_limit, queue_limit=args.queue_limit, skill_limit=args.skill_limit)
    if args.agent_gateway_command == "status":
        print(render_agent_gateway_json(status) if args.json else render_agent_gateway_html(status), end="")
        return 0
    if args.agent_gateway_command == "dashboard":
        if args.html_out:
            path = write_agent_gateway_html(status, args.html_out)
            print(json.dumps({"ok": True, "path": path}, ensure_ascii=False, indent=2, sort_keys=True) if args.json else path)
            return 0
        print(render_agent_gateway_html(status), end="")
        return 0
    print("agent-gateway error: unknown command")
    return 2


def _relay_input_payload(path: str) -> dict[str, Any]:
    if not path:
        return {}
    text = sys.stdin.read() if path == "-" else Path(path).expanduser().read_text(encoding="utf-8")
    payload = json.loads(text or "{}")
    if not isinstance(payload, dict):
        raise ValueError("relay input must be a JSON object")
    return payload


def _print_relay_payload(payload: Any, *, json_output: bool) -> None:
    if hasattr(payload, "to_dict"):
        payload = payload.to_dict()
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                print(f"{item.get('id') or item.get('message_id') or item.get('event_type', '')} {item.get('state') or item.get('status', '')}".strip())
            else:
                print(item)
        return
    if isinstance(payload, dict):
        print(
            " ".join(
                str(part)
                for part in (
                    payload.get("id") or payload.get("message_id") or payload.get("task_id") or payload.get("agent_id") or payload.get("action") or "",
                    payload.get("state") or payload.get("status") or "",
                    payload.get("type") or "",
                )
                if part
            )
        )
        return
    print(str(payload))


def cmd_relay(args: argparse.Namespace) -> int:
    project = load_config(args.project).project
    try:
        if args.relay_command == "card":
            card = relay_bus.create_task_card(
                project,
                args.goal,
                task_id=args.task_id,
                scope_allowed=args.allowed or (),
                scope_forbidden=args.forbidden or (),
                success_criteria=args.success or (),
                risk_level=args.risk_level,
            )
            _print_relay_payload(card, json_output=args.json)
            return 0
        if args.relay_command == "send":
            payload = _relay_input_payload(args.input)
            message = relay_bus.send_message(
                project,
                to_agent=args.to,
                from_agent=args.from_agent,
                message_type=args.type,
                task_id=args.task,
                payload=payload,
                message_id=args.message_id,
            )
            _print_relay_payload(message, json_output=args.json)
            return 0
        if args.relay_command == "inbox":
            messages = relay_bus.list_agent_messages(project, args.agent, requester_agent=args.as_agent or args.agent)
            _print_relay_payload(messages, json_output=args.json)
            return 0
        if args.relay_command == "poll":
            message = relay_bus.poll_once(project, args.agent, requester_agent=args.as_agent or args.agent, lease_seconds=args.lease_seconds)
            payload = {"ok": message is not None, "status": "running" if message else "empty", "message": message.to_dict() if message else None}
            _print_relay_payload(payload, json_output=args.json)
            return 0 if message is not None else 1
        if args.relay_command == "watch":
            messages = relay_bus.watch_loop(
                project,
                args.agent,
                interval=args.interval,
                max_iterations=args.max_iterations,
                requester_agent=args.as_agent or args.agent,
                lease_seconds=args.lease_seconds,
            )
            payload = {"ok": True, "status": "ok", "count": len(messages), "messages": [message.to_dict() for message in messages]}
            _print_relay_payload(payload, json_output=args.json)
            return 0
        if args.relay_command == "done":
            output = _relay_input_payload(args.output)
            message = relay_bus.mark_done(project, args.agent, args.message, output, lease_id=args.lease)
            _print_relay_payload({"ok": True, "status": "done", "message": message.to_dict()}, json_output=args.json)
            return 0
        if args.relay_command == "fail":
            output = _relay_input_payload(args.output)
            message = relay_bus.mark_failed(project, args.agent, args.message, output, lease_id=args.lease)
            _print_relay_payload({"ok": True, "status": "failed", "message": message.to_dict()}, json_output=args.json)
            return 0
        if args.relay_command == "reclaim":
            messages = relay_bus.reclaim_expired(project, args.agent, lease_seconds=args.lease_seconds, stale_seconds=args.stale_seconds)
            _print_relay_payload({"ok": True, "status": "ok", "count": len(messages), "messages": [message.to_dict() for message in messages]}, json_output=args.json)
            return 0
        if args.relay_command == "status":
            status = relay_bus.relay_status(project, task_id=args.task)
            _print_relay_payload(status, json_output=args.json)
            return 0
        if args.relay_command == "demo":
            result = relay_bus.run_demo(project)
            _print_relay_payload(result, json_output=args.json)
            return 0
        if args.relay_command == "stress":
            agents = [item.strip() for chunk in args.agents for item in chunk.split(",") if item.strip()]
            result = relay_bus.run_stress(project, agents=agents, workers=args.workers, messages=args.messages, lease_seconds=args.lease_seconds)
            _print_relay_payload(result, json_output=args.json)
            return 0 if result.get("ok") else 1
        if args.relay_command == "heartbeat":
            heartbeat = relay_bus.update_heartbeat(project, args.agent, status=args.status, current_task_id=args.task or "")
            if args.stale_after is not None:
                heartbeat = relay_bus.detect_stale_heartbeat(project, args.agent, stale_after_seconds=args.stale_after)
            _print_relay_payload(heartbeat, json_output=args.json)
            return 0
        if args.relay_command == "events":
            events = relay_bus.list_events(project, task_id=args.task or "", message_id=args.message or "")
            _print_relay_payload(events, json_output=args.json)
            return 0
    except (OSError, ValueError, KeyError, PermissionError, RuntimeError, json.JSONDecodeError) as exc:
        payload = {"ok": False, "status": "error", "action": getattr(args, "relay_command", "relay"), "error": str(exc)}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"relay error: {exc}")
        return 2
    print("relay error: unknown command")
    return 2


def cmd_runtime(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    if args.runtime_command == "status":
        snapshot = build_runtime_ledger_snapshot(config.project, limit=args.limit)
        print(render_runtime_json(snapshot) if args.json else render_runtime_ledger(snapshot), end="")
        return 0
    if args.runtime_command == "export":
        snapshot = build_runtime_ledger_snapshot(config.project, limit=args.limit)
        print(render_runtime_json(snapshot), end="")
        return 0
    if args.runtime_command == "search":
        result = search_runtime_ledger(config.project, args.query, limit=args.limit)
        print(render_runtime_json(result) if args.json else render_runtime_search(result), end="")
        return 0 if result.get("messages") else 1
    if args.runtime_command == "agent":
        view = build_agent_runtime_view(
            config.project,
            task=args.task,
            query_events_path=args.query_events or None,
            trajectory_path=args.trajectory or None,
            desktop_state_path=args.desktop_state or None,
            eval_json_path=args.eval_json or None,
            soak_json_path=args.soak_json or None,
        )
        print(view.to_json() if args.json else render_agent_runtime_view(view), end="" if not args.json else "\n")
        return 0 if view.ok or view.status == "pending" else 1
    if args.runtime_command == "queue":
        return cmd_runtime_queue(args)
    print("runtime error: unknown command")
    return 2


def cmd_skill_pipeline(args: argparse.Namespace) -> int:
    project = load_config(args.project).project
    if args.skill_pipeline_command == "propose-trajectory":
        proposal = propose_skill_from_trajectory(
            project,
            args.trajectory,
            name=args.name or "",
            description=args.description or "",
            triggers=args.trigger or (),
        )
        print(render_skill_proposal(proposal), end="")
        return 0
    if args.skill_pipeline_command == "propose-events":
        proposal = propose_skill_from_events(
            project,
            name=args.name,
            description=args.description,
            triggers=args.trigger or (),
            limit=args.limit,
        )
        print(render_skill_proposal(proposal), end="")
        return 0
    if args.skill_pipeline_command == "propose-subject-repair":
        source_path = Path(args.source_file).expanduser()
        if not source_path.is_absolute():
            source_path = project / source_path
        try:
            source = source_path.read_text(encoding="utf-8")
            proposal = propose_subject_repair_skill(
                project,
                name=args.name or f"{args.function}-repair",
                description=args.description or "",
                triggers=args.trigger or (),
                function_name=args.function,
                source=source,
                evidence=(str(source_path), *(args.evidence or ())),
            )
        except (OSError, ValueError) as exc:
            print(f"skill-pipeline error: {exc}")
            return 2
        print(render_skill_proposal(proposal), end="")
        return 0
    if args.skill_pipeline_command == "propose-subject-repair-from-trajectory":
        workspace = Path(args.workspace).expanduser() if args.workspace else None
        if workspace is not None and not workspace.is_absolute():
            workspace = project / workspace
        try:
            proposal = propose_subject_repair_skill_from_trajectory(
                project,
                args.trajectory,
                workspace=workspace,
                name=args.name or "",
                description=args.description or "",
                triggers=args.trigger or (),
            )
        except (OSError, ValueError) as exc:
            print(f"skill-pipeline error: {exc}")
            return 2
        print(render_skill_proposal(proposal), end="")
        return 0
    if args.skill_pipeline_command == "propose-file-bundle-repair-from-trajectory":
        workspace = Path(args.workspace).expanduser() if args.workspace else None
        if workspace is not None and not workspace.is_absolute():
            workspace = project / workspace
        try:
            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                args.trajectory,
                workspace=workspace,
                name=args.name or "",
                description=args.description or "",
                triggers=args.trigger or (),
            )
        except (OSError, ValueError) as exc:
            print(f"skill-pipeline error: {exc}")
            return 2
        print(render_skill_proposal(proposal), end="")
        return 0
    if args.skill_pipeline_command == "list":
        proposals = list_skill_proposals(project)
        if args.json:
            print(json.dumps([item.to_dict() for item in proposals], ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(render_skill_proposals(proposals), end="")
        return 0
    if args.skill_pipeline_command == "show":
        print(render_skill_proposal(load_skill_proposal(project, args.proposal_id)), end="")
        return 0
    if args.skill_pipeline_command == "curate":
        curated = curate_skill_proposals(list_skill_proposals(project))
        if args.json:
            print(
                json.dumps(
                    [
                        {
                            "proposal": item.proposal.to_dict(),
                            "score": item.score,
                            "reproduction_score": item.reproduction_score,
                            "evidence_score": item.evidence_score,
                            "risk_score": item.risk_score,
                            "benefit_score": item.benefit_score,
                        }
                        for item in curated
                    ],
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            for item in curated:
                print(f"{item.score:.3f}\t{item.proposal.proposal_id}\t{item.proposal.name}")
        return 0
    if args.skill_pipeline_command == "approve":
        if not args.eval_command:
            print("skill-pipeline error: --eval-command is required for skill approval")
            return 2
        try:
            eval_result = run_skill_eval_command(
                project,
                args.eval_command,
                summary=args.eval_summary or "",
                evidence=tuple(args.eval_evidence or ()),
            )
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            print(f"skill-pipeline error: eval command failed to run: {exc}")
            return 2
        if eval_result.returncode != 0:
            print("skill-pipeline error: skill approval requires executed eval command returncode 0")
            return 2
        if not eval_result.passed:
            print("skill-pipeline error: skill approval requires passing eval")
            return 2
        inline_report = args.require_learning_effect if isinstance(args.require_learning_effect, str) else ""
        learning_result = _load_skill_learning_effect_gate(
            project,
            report_path=args.learning_effect_report or inline_report,
            command=args.learning_effect_command or "",
        )
        if not learning_result["passed"]:
            print(f"skill-pipeline error: {learning_result['error']}")
            return 2
        eval_result = _merge_learning_effect_eval_result(eval_result, learning_result)
        try:
            path = approve_skill_proposal(project, args.proposal_id, force=args.force, eval_result=eval_result)
        except (PermissionError, FileExistsError, KeyError) as exc:
            print(f"skill-pipeline error: {exc}")
            return 2
        print(path)
        return 0
    if args.skill_pipeline_command == "reject":
        try:
            proposal = reject_skill_proposal(project, args.proposal_id, reason=args.reason or "")
        except KeyError as exc:
            print(f"skill-pipeline error: {exc}")
            return 2
        print(render_skill_proposal(proposal), end="")
        return 0
    if args.skill_pipeline_command == "rollback":
        try:
            proposal = rollback_skill_proposal_install(project, args.proposal_id, reason=args.reason or "")
        except KeyError as exc:
            print(f"skill-pipeline error: {exc}")
            return 2
        print(render_skill_proposal(proposal), end="")
        return 0
    print("skill-pipeline error: unknown command")
    return 2


def _load_skill_learning_effect_gate(project: str | Path, *, report_path: str, command: str) -> dict[str, Any]:
    clean_report = str(report_path).strip()
    clean_command = str(command).strip()
    if clean_report and clean_command:
        return {"passed": False, "error": "use only one of --learning-effect-report or --learning-effect-command"}
    if clean_report:
        path = Path(clean_report).expanduser()
        if not path.is_absolute():
            path = Path(project).expanduser().resolve(strict=False) / path
        if not path.exists():
            return {"passed": False, "error": f"learning-effect report not found: {path}"}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"passed": False, "error": f"learning-effect report is not valid JSON: {exc}"}
        source = f"report:{path}"
        return _validate_skill_learning_effect_payload(payload, source=source)
    if clean_command:
        try:
            completed = subprocess.run(
                clean_command,
                cwd=Path(project).expanduser().resolve(strict=False),
                shell=True,
                text=True,
                capture_output=True,
                timeout=300,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"passed": False, "error": f"learning-effect command failed to run: {exc}"}
        if completed.returncode != 0:
            return {"passed": False, "error": f"learning-effect command exited {completed.returncode}"}
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            return {"passed": False, "error": f"learning-effect command stdout is not valid JSON: {exc}"}
        result = _validate_skill_learning_effect_payload(payload, source=f"command:{clean_command}")
        result["stdout_summary"] = _preview_cli_text(completed.stdout, 800)
        result["stderr_summary"] = _preview_cli_text(completed.stderr, 800)
        return result
    return {"passed": False, "error": "learning-effect gate requires --learning-effect-report or --learning-effect-command"}


def _validate_skill_learning_effect_payload(payload: Any, *, source: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"passed": False, "error": "learning-effect report must be a JSON object"}
    try:
        evidence = learning_effect_report_evidence(payload)
    except PermissionError as exc:
        return {"passed": False, "error": str(exc)}
    status = str(evidence.get("status") or "").strip().lower()
    score_delta = float(evidence["score_delta"])
    if status != "pass":
        return {"passed": False, "error": f"learning-effect report status is not pass: {status or 'missing'}"}
    if score_delta <= 0:
        return {"passed": False, "error": f"learning-effect score_delta must be > 0, got {score_delta:g}"}
    evidence = dict(evidence)
    evidence["source"] = source
    return {"passed": True, "evidence": evidence, "report": payload, "score_delta": score_delta, "source": source}


def _merge_learning_effect_eval_result(eval_result: SkillEvalResult | None, learning_result: dict[str, Any]) -> SkillEvalResult:
    evidence_json = json.dumps(
        {"learning_effect": learning_result["evidence"]},
        ensure_ascii=False,
        sort_keys=True,
    )
    if eval_result is None:
        raise PermissionError("skill approval requires eval command before learning-effect gate")
    return SkillEvalResult(
        passed=eval_result.passed,
        command=eval_result.command,
        summary=eval_result.summary,
        evidence=tuple(eval_result.evidence) + (evidence_json,),
        returncode=eval_result.returncode,
        stdout_summary=eval_result.stdout_summary,
        stderr_summary=eval_result.stderr_summary,
        require_learning_effect=True,
        learning_effect_report=learning_result.get("report"),
        executed=eval_result.executed,
    )


def _preview_cli_text(text: str, max_chars: int) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max(0, max_chars - 1)].rstrip() + "..."


def cmd_skills(args: argparse.Namespace) -> int:
    project = load_config(args.project).project if getattr(args, "project", None) or args.install else None
    if args.install:
        installed = install_skill(project or load_config(args.project).project, args.install, name=args.name, force=args.force)
        if args.json:
            registry = [record.to_dict() for record in list_skill_registry(project or load_config(args.project).project) if record.name == installed.name]
            print(json.dumps(registry[0] if registry else {"name": installed.name, "path": installed.path}, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"installed {installed.name}\t{installed.description}")
            print(installed.path)
        return 0
    skills = select_skills(args.match, project=project) if args.match else list_skills(project)
    if not skills:
        print("[]" if args.json else "No matching skills.")
        return 0
    if args.json:
        records = list_skill_registry(project)
        wanted = {skill.name for skill in skills}
        print(json.dumps([record.to_dict() for record in records if record.name in wanted], ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    for skill in skills:
        print(f"{skill.name}\t{skill.description}")
        if args.show:
            source = f" ({skill.source})" if skill.source != "builtin" else ""
            print(f"  triggers: {', '.join(skill.triggers)}{source}")
            print(f"  {skill.body}")
    return 0


def cmd_safety(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    policy = SafetyPolicy(project=config.project, communication_dir_name=config.communication_dir_name)
    if args.check_command:
        decision = assess_command(args.check_command, cwd=config.project, policy=policy)
        print(decision.render())
        return 0 if decision.allowed else 1
    if args.check_claim:
        decision = assess_quant_claim(args.check_claim)
        print(decision.render())
        return 0 if decision.allowed else 1
    print(policy_summary(policy))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    results = validate_project_scripts(config.project)
    lines = []
    ok = True
    for result in results:
        mark = result.status if result.ok else "fail"
        lines.append(f"- [{mark}] {result.name}: {result.detail}")
        ok = ok and result.ok
    body = "\n".join(lines)
    path = append_journal(config.project, "validation", body)
    print(body)
    print(f"\njournal: {path}")
    return 0 if ok else 1


def cmd_checks(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.checks_command == "list":
            checks = load_source_checks(config.project)
            print(json.dumps([check.to_dict() for check in checks], ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_source_checks(checks))
            return 0
        if args.checks_command == "run":
            results = run_source_checks(
                config.project,
                paths=args.path or (),
                run_commands=args.run_commands,
                timeout=args.timeout,
            )
            summary = source_check_summary(results)
            if args.json:
                print(
                    json.dumps(
                        {"summary": summary, "results": [result.to_dict() for result in results]},
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                print(render_source_check_results(results))
            return 0 if summary.get("ok") else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"checks error: {exc}")
        return 2
    print("checks error: unknown command")
    return 2


def cmd_doctor(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    checks = run_doctor(config.project)
    body = render_doctor_json(config.project, checks) if args.json else render_doctor(config.project, checks)
    if args.write:
        out_dir = config.communication_dir if config.communication_dir.exists() else config.project
        out_path = out_dir / ("QUANTAGENT_DOCTOR.json" if args.json else "QUANTAGENT_DOCTOR.md")
        out_path.write_text(body, encoding="utf-8")
        print(out_path)
    else:
        print(body)
    return 1 if blocking_doctor_issues(checks) else 0


def cmd_onboard(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    checks = run_doctor(config.project)
    score = doctor_score(checks)
    failed = [check for check in checks if not check.ok]
    model_configured = ModelClient().configured
    next_commands = [
        f"{PRIMARY_CLI} doctor --project {json.dumps(str(config.project))}",
        f"{PRIMARY_CLI} agent --project {json.dumps(str(config.project))} \"audit this repo and propose a safe fix plan\"",
        f"{PRIMARY_CLI} runtime --project {json.dumps(str(config.project))} status",
    ]
    if args.json:
        print(
            json.dumps(
                {
                    "project": str(config.project),
                    "score": score,
                    "checks": len(checks),
                    "failed_checks": [
                        {
                            "name": check.name,
                            "category": check.category,
                            "severity": check.severity,
                            "detail": check.detail,
                        }
                        for check in failed
                    ],
                    "model_configured": model_configured,
                    "next_commands": next_commands,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    lines = [
        "# OpenMako Onboard",
        "",
        f"- project: {config.project}",
        f"- doctor: {score}/100 across {len(checks)} checks",
        f"- model auth: {'configured' if model_configured else 'not configured'}",
    ]
    if failed:
        lines.append("- failed checks:")
        lines.extend(f"  - {check.name}: {check.detail}" for check in failed[:5])
    else:
        lines.append("- failed checks: none")
    lines.extend(
        [
            "",
            "## Next Commands",
            "",
            *[f"- `{command}`" for command in next_commands],
        ]
    )
    print("\n".join(lines) + "\n")
    return 0


def cmd_state(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    md_path, json_path = write_project_state(config.project)
    print(md_path)
    print(json_path)
    return 0


def cmd_todo(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    if args.task_id:
        if args.set_plan:
            item_id, status = args.set_plan
            items = set_plan_item(config.project, args.task_id, item_id, status, title=args.title or "", detail=args.detail or "")
        else:
            items = load_task_plan(config.project, args.task_id)
        print(render_task_plan(args.task_id, items))
        return 0
    if args.set:
        item_id, status = args.set
        items = set_todo_status(config.project, item_id, status)
    else:
        items = load_todos(config.project)
        if args.write:
            save_todos(config.project, items)
    for item in items:
        print(f"[{item.status}] {item.priority} {item.id}: {item.title} - {item.detail}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    if args.diff:
        report = create_diff_review(
            config.project,
            args.path,
            staged=args.staged,
            max_diff_lines=args.max_diff_lines,
        )
        if args.json:
            print(json.dumps(asdict(report), ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(render_diff_review_report(report, include_diff=not args.no_diff), end="")
        return 1 if any(item.severity == "error" for item in report.findings) else 0
    if not args.task:
        print("review error: task is required unless --diff is set")
        return 2
    path = create_review_request(
        config.project,
        args.task,
        primary_model=config.primary_model,
        review_model=config.review_model,
    )
    append_journal(config.project, "review_request", f"Created review request: {path}\nTask: {args.task}")
    print(path)
    return 0


def cmd_consensus(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    if args.new:
        status = create_consensus_request(config.project, args.new, ask_chatgpt=not args.no_chatgpt)
        print(render_status(status))
        print("Three-pass ChatGPT consistency approval required before material execution.")
        return 0 if status.all_approved else 1
    status = load_consensus_status(config.project, request_id=args.id)
    print(render_status(status))
    return 0 if status and status.all_approved else 1


def cmd_loop(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    if not args.consensus_id:
        status = create_consensus_request(config.project, f"Run Mako loop task: {args.task}")
        print(render_status(status))
        print("blocked: three-pass ChatGPT consistency approval required. Re-run with --consensus-id after all three votes approve.")
        return 2
    status = load_consensus_status(config.project, request_id=args.consensus_id)
    if not status or not status.all_approved:
        print(render_status(status))
        print("blocked: three-pass ChatGPT consistency approval is required before loop execution")
        return 2
    result = QuantAgent(config.project, model=args.model or config.primary_model, base_url=args.base_url).run_once(args.task)
    out_dir = config.communication_dir if config.communication_dir.exists() else config.project
    out_path = out_dir / "QUANTAGENT_LAST_RUN.json"
    result.write_json(out_path)
    print(result.to_json())
    print(f"\nresult: {out_path}")
    return 0 if result.ok else 1


def cmd_model_test(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    model = args.model or config.primary_model
    client = ModelClient(base_url=args.base_url, timeout=args.timeout)
    response = client.complete(
        ModelRequest(
            model=model,
            system="You are a concise model connectivity tester.",
            prompt=args.prompt,
        )
    )
    print(f"provider: {response.provider}")
    print(f"model: {response.model}")
    if response.ok:
        print("ok: true")
        print(response.text)
        return 0
    print("ok: false")
    print(response.error)
    return 1


def cmd_ask(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    model = args.model or config.primary_model
    decision = choose_context_decision(args.task)
    agent = QuantAgent(config.project, model=model, base_url=args.base_url)
    response = agent.ask_model(args.task, token_budget=decision.token_budget)
    if response.ok:
        path = append_journal(
            config.project,
            "model_ask",
            f"model={model}\ncontext_mode={decision.mode}\ntoken_budget={decision.token_budget}\n\nTask:\n{args.task}\n\nResponse:\n{response.text}",
        )
        print(response.text)
        print(f"\njournal: {path}")
        return 0
    print(response.error)
    return 1


def cmd_fix(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    if args.path and (args.old is not None or args.new is not None):
        if args.old is None or args.new is None:
            print("fix error: --old and --new must be provided together")
            return 2
        default_plan = create_patch_plan(
            config.project,
            args.task,
            paths=[args.path],
            test_command=args.test or (),
            max_attempts=args.max_rounds,
        )
        result = run_auto_patch(
            config.project,
            AutoPatchSpec(
                task=args.task,
                path=args.path,
                old=args.old,
                new=args.new,
                test_command=default_plan.test_command,
                expected_count=args.expected_count,
                max_rounds=args.max_rounds,
                timeout=args.timeout,
                reviewed=True,
            ),
            apply=args.apply,
            profile=args.agent_profile or "",
        )
        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(_render_fix_auto_result(result, apply=args.apply), end="")
        return 0 if result.ok or (not args.apply and bool(result.preview)) else 1

    plan = create_patch_plan(
        config.project,
        args.task,
        paths=args.path_list or (),
        test_command=args.test or (),
        max_attempts=args.max_rounds,
    )
    out = args.out or str(config.project / ".quantagent" / "fix_plan.json")
    path = write_patch_plan(out, plan)
    if args.json:
        payload = plan.to_dict()
        payload["plan_path"] = str(path)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(_render_fix_plan(path, plan), end="")
    return 0


def _render_fix_auto_result(result: Any, *, apply: bool) -> str:
    lines = [
        "# Mako Fix",
        "",
        f"- status: {'applied' if result.ok and apply else 'preview'}",
        f"- summary: {result.summary}",
    ]
    if result.checkpoint_id:
        lines.append(f"- checkpoint: {result.checkpoint_id}")
    if result.plan.test_command:
        lines.append(f"- tests: {' '.join(result.plan.test_command)}")
    if result.preview:
        lines.extend(["", "## Diff", "", "```diff", result.preview.rstrip(), "```"])
    if not apply and result.preview:
        lines.extend(["", "Next: rerun with `--apply` after reviewing the diff."])
    return "\n".join(lines) + "\n"


def _render_fix_plan(path: Path, plan: Any) -> str:
    files = ", ".join(item.path for item in plan.files) or "none inferred"
    tests = " ".join(plan.test_command) if plan.test_command else "none"
    return "\n".join(
        [
            "# Mako Fix Plan",
            "",
            f"- plan: {path}",
            f"- task: {plan.task}",
            f"- files: {files}",
            f"- tests: {tests}",
            "",
            "To apply a known replacement in one step:",
            f"`mako fix {json.dumps(plan.task, ensure_ascii=False)} --path <file> --old <old> --new <new> --apply`",
            "",
        ]
    )


def cmd_demo(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    if args.demo_command == "fix":
        result = run_fix_demo(config.project)
        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(render_fix_demo(result), end="")
        return 0 if result.ok else 1
    print("demo error: unknown command")
    return 2


def cmd_chat(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    return run_chat(
        project=config.project,
        model=args.model or config.primary_model,
        base_url=args.base_url,
        once=args.once,
        long=args.long,
        deep_context=args.deep_context,
        save_report=args.save_report,
        stream_file=not args.no_stream_file,
    )


def cmd_experiment(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    if not args.consensus_id:
        status = create_consensus_request(
            config.project,
            f"Run experiment scenario={args.scenario} threshold={args.threshold} input={args.input or 'default'}",
        )
        print(render_status(status))
        print("blocked: three-pass ChatGPT consistency approval required. Re-run with --consensus-id after all three votes approve.")
        return 2
    status = load_consensus_status(config.project, request_id=args.consensus_id)
    if not status or not status.all_approved:
        print(render_status(status))
        print("blocked: three-pass ChatGPT consistency approval is required before experiment execution")
        return 2
    input_path = Path(args.input).expanduser() if args.input else resolve_default_input(config.project, args.scenario)
    if not input_path.exists():
        print(f"input not found: {input_path}")
        return 2
    threshold_col = args.threshold_col if args.threshold is not None else None
    name = args.name
    if not name:
        threshold_part = f"_{threshold_col}_lte_{args.threshold}" if args.threshold is not None else ""
        name = f"{input_path.stem}{threshold_part}"
    try:
        payload = run_experiment(
            config.project,
            ExperimentSpec(
                name=name,
                input_path=input_path,
                return_col=args.return_col,
                date_col=args.date_col,
                threshold_col=threshold_col,
                threshold_lte=args.threshold,
            ),
        )
    except ValueError as exc:
        print(f"experiment invalid: {exc}")
        return 2
    entry = payload["registry_entry"]
    print(
        f"{payload['name']}: trades={payload['metrics']['trades']} "
        f"PF={fmt_pf(payload['metrics']['profit_factor'])} "
        f"avg={payload['metrics']['avg_return']:.4%}"
    )
    print(entry["json_path"])
    print(entry["markdown_path"])
    return 0


def cmd_registry(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    entries = load_registry(config.project)
    if args.latest:
        entries = entries[-1:]
    if args.json:
        import json

        print(json.dumps([entry.__dict__ for entry in entries[-args.limit :]], ensure_ascii=False, indent=2))
    else:
        print(render_registry_markdown(entries, limit=args.limit))
    return 0


def cmd_run_p4(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    if not args.consensus_id:
        status = create_consensus_request(config.project, "Run P4 real execution framework")
        print(render_status(status))
        print("blocked: three-pass ChatGPT consistency approval required. Re-run with --consensus-id after all three votes approve.")
        return 2
    status = load_consensus_status(config.project, request_id=args.consensus_id)
    if not status or not status.all_approved:
        print(render_status(status))
        print("blocked: three-pass ChatGPT consistency approval is required before P4 execution")
        return 2
    script = next(config.project.glob("**/p4_real_execution_framework.py"), None)
    if not script:
        print("p4_real_execution_framework.py not found")
        return 2
    result = run_command_args(["python3", script, "--help"], cwd=script.parent, timeout=60)
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    if result.blocked:
        print(f"blocked: {result.reason}")
    return result.returncode


def cmd_run_next(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    result = run_next(
        config.project,
        task=args.task,
        model=args.model or config.primary_model,
    )
    print(f"stage: {result.stage}")
    print(f"audit_ok: {result.audit_ok}")
    print(f"validation_ok: {result.validation_ok}")
    print(f"markdown: {result.markdown_path}")
    print(f"json: {result.json_path}")
    verdict = result.orchestration.get("overall_verdict") or result.orchestration.get("verdict")
    if verdict:
        print(f"role_verdict: {verdict}")
    return 0 if result.audit_ok and result.validation_ok else 1


def cmd_agent(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    if args.subagents != "off":
        result = run_agent_supervisor(
            config.project,
            args.task,
            include_validation=not args.no_validate,
            changed_paths=args.path or (),
            plan_only=args.subagents == "plan-only",
        )
        out_dir = _agent_result_out_dir(config)
        out_path = out_dir / "QUANTAGENT_AGENT_SUPERVISOR_LAST.json"
        out_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(render_agent_supervisor_run(result), end="")
            print(f"result: {out_path}")
        return 0 if result.ok else 1
    if not args.legacy_tool_loop:
        result = run_agent_loop(
            config.project,
            args.task,
            explicit_mode=args.mode or "",
            include_validation=not args.no_validate,
            stop_on_required_failure=args.stop_on_failure,
            strict_approval=args.strict_approval,
            goal=args.goal or "",
            goal_guard=not args.no_goal_guard,
            changed_paths=args.path or (),
            input_provenance=args.input_provenance or "agent",
            max_duration_seconds=args.max_duration_seconds,
            max_steps=args.max_steps,
            learning_context=args.learning_context,
            learning_project=args.learning_project or None,
        )
        out_dir = _agent_result_out_dir(config)
        out_path = out_dir / "QUANTAGENT_AGENT_V3_LAST.json"
        result.to_agent_result().write_json(out_path)
        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(render_agent_result(result), end="")
            print(f"result: {out_path}")
        return 0 if result.ok else 1
    result = run_tool_loop(
        config.project,
        args.task,
        model=args.model or config.primary_model,
        base_url=args.base_url,
        max_steps=args.max_steps if args.max_steps is not None else 4,
    )
    out_dir = _agent_result_out_dir(config)
    out_path = out_dir / "QUANTAGENT_TOOL_LOOP_LAST.json"
    result.write_json(out_path)
    print(result.summary)
    print(f"\nstage: {result.stage}")
    print(f"ok: {str(result.ok).lower()}")
    print(f"result: {out_path}")
    return 0 if result.ok else 1


def cmd_agent_supervisor(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.supervisor_command == "list":
            runs = load_agent_supervisor_runs(config.project)
            if args.json:
                print(json.dumps([run.to_dict() for run in runs], ensure_ascii=False, indent=2, sort_keys=True))
            elif not runs:
                print("No agent supervisor runs.")
            else:
                for run in runs[-args.limit :]:
                    print(f"- {run.supervisor_id}: parent={run.parent_task_id} action={run.action} terminal={str(run.terminal).lower()} ok={str(run.ok).lower()} roles={','.join(item.role for item in run.plan)}")
            return 0
        if args.supervisor_command == "show":
            run = get_agent_supervisor_run(config.project, args.supervisor_id or "")
            if run is None:
                print("agent-supervisor error: no supervisor runs found")
                return 1
            print(json.dumps(run.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_agent_supervisor_run(run), end="" if not args.json else "\n")
            return 0 if run.ok else 1
        if args.supervisor_command == "refresh":
            run = refresh_agent_supervisor(config.project, args.parent_task_id or "")
            if run is None:
                print("agent-supervisor error: no matching supervisor run found")
                return 1
            print(json.dumps(run.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_agent_supervisor_run(run), end="" if not args.json else "\n")
            return 0 if run.ok else 1
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"agent-supervisor error: {exc}")
        return 2
    print("agent-supervisor error: unknown command")
    return 2


def cmd_agent_v2(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    if not args.legacy_v2:
        result = run_agent_loop_v3(
            config.project,
            args.task,
            explicit_mode=args.mode or "",
            include_validation=not args.no_validate,
            stop_on_required_failure=args.stop_on_failure,
            goal=args.goal or "",
            goal_guard=not args.no_goal_guard,
            input_provenance="agent-v2-default",
            max_duration_seconds=args.max_duration_seconds,
            max_steps=args.max_steps,
        )
        out_dir = _agent_result_out_dir(config)
        out_path = out_dir / "QUANTAGENT_AGENT_V3_LAST.json"
        result.to_agent_result().write_json(out_path)
        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(render_agent_v3_result(result), end="")
            print(f"result: {out_path}")
        return 0 if result.ok else 1
    result = run_agent_v2(
        config.project,
        args.task,
        include_validation=not args.no_validate,
        stop_on_required_failure=args.stop_on_failure,
    )
    out_dir = _agent_result_out_dir(config)
    out_path = out_dir / "QUANTAGENT_AGENT_V2_LAST.json"
    result.to_agent_result().write_json(out_path)
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(result.summary)
        print(f"\nok: {str(result.ok).lower()}")
        print(f"trajectory: {result.trajectory_path}")
        print(f"result: {out_path}")
    return 0 if result.ok else 1


def cmd_agent_v3(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    result = run_agent_loop_v3(
        config.project,
        args.task,
        explicit_mode=args.mode or "",
        include_validation=not args.no_validate,
        stop_on_required_failure=args.stop_on_failure,
        strict_approval=args.strict_approval,
        goal=args.goal or "",
        goal_guard=not args.no_goal_guard,
        changed_paths=args.path or (),
        input_provenance=args.input_provenance or "",
        max_duration_seconds=args.max_duration_seconds,
        max_steps=args.max_steps,
    )
    out_dir = _agent_result_out_dir(config)
    out_path = out_dir / "QUANTAGENT_AGENT_V3_LAST.json"
    result.to_agent_result().write_json(out_path)
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_agent_v3_result(result), end="")
        print(f"result: {out_path}")
    return 0 if result.ok else 1


def _agent_result_out_dir(config: Any) -> Path:
    config.communication_dir.mkdir(parents=True, exist_ok=True)
    return config.communication_dir


def cmd_goal_contract(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.goal_command == "show":
            contract = load_goal_contract(config.project)
            print(json.dumps(contract.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_goal_contract(contract), end="" if not args.json else "\n")
            return 0
        if args.goal_command == "set":
            path = save_goal_contract(
                config.project,
                goal=args.goal,
                constraints=args.constraint or (),
                success_criteria=args.success or (),
                data_strict=not args.no_data_strict,
                uncertainty_policy=args.uncertainty_policy or "block_uncertain_data_claims",
                quant_strict=not args.no_quant_strict,
                hallucination_policy=args.hallucination_policy or "block_unsupported_quant_claims",
            )
            contract = load_goal_contract(config.project)
            if args.json:
                print(json.dumps({"path": str(path), "contract": contract.to_dict()}, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(f"saved: {path}")
                print(render_goal_contract(contract), end="")
            return 0
        if args.goal_command == "check":
            decision = evaluate_goal_guard(
                config.project,
                args.instruction,
                goal=args.goal or "",
                constraints=args.constraint or (),
                success_criteria=args.success or (),
            )
            print(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_goal_guard_decision(decision), end="" if not args.json else "\n")
            return 0 if decision.allowed else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"goal-contract error: {exc}")
        return 2
    print("goal-contract error: unknown command")
    return 2


def cmd_evidence(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.evidence_command == "add":
            record = record_evidence(
                config.project,
                claim=args.claim,
                value=args.value or "",
                evidence_type=args.type or "manual",
                source=args.source or "",
                command=args.command or "",
                path=args.path or "",
                tool=args.tool or "",
                confidence=args.confidence,
                verified=not args.unverified,
            )
            print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_evidence([record]), end="" if not args.json else "\n")
            return 0
        if args.evidence_command == "list":
            records = load_evidence(config.project, limit=args.limit)
            print(json.dumps([record.to_dict() for record in records], ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_evidence(records), end="" if not args.json else "\n")
            return 0
    except (OSError, ValueError) as exc:
        print(f"evidence error: {exc}")
        return 2
    print("evidence error: unknown command")
    return 2


def cmd_answer_guard(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    text = args.answer or ""
    if args.answer_file:
        path = Path(args.answer_file).expanduser()
        if not path.is_absolute():
            path = config.project / path
        text = path.read_text(encoding="utf-8", errors="replace")
    verdict = guard_answer(config.project, text, goal=args.goal or "", task=args.task or "", strict=not args.warn_only)
    print(json.dumps(verdict.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_answer_guard_verdict(verdict), end="" if not args.json else "\n")
    return 0 if verdict.ok else 1


def cmd_better_option(args: argparse.Namespace) -> int:
    hint = suggest_better_option(args.task or "", goal=args.goal or "", mode=args.mode or "")
    print(json.dumps(hint.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_better_option_hint(hint), end="" if not args.json else "\n")
    return 0


def cmd_headless(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    result = run_headless(
        config.project,
        args.task,
        mode=args.mode or "",
        goal=args.goal or "",
        changed_paths=args.path or (),
        include_validation=not args.no_validate,
        strict_approval=args.strict_approval,
        max_duration_seconds=args.max_duration_seconds,
        max_steps=args.max_steps,
    )
    print(render_headless_json(result) if args.json else render_headless_result(result), end="")
    return 0 if result.ok else 1


def cmd_mode_router(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.lint:
            diagnostics = validate_mode_router(config.project)
            if args.json:
                print(json.dumps([item.to_dict() for item in diagnostics], ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(render_mode_router_diagnostics(diagnostics), end="")
            return 1 if any(item.level == "error" for item in diagnostics) else 0
        route = route_agent_mode(
            config.project,
            args.task or "",
            explicit_mode=args.mode or "",
            previous_mode=args.previous_mode or "",
            failure_class=args.failure_class or "",
            changed_paths=args.path or (),
            input_provenance=args.input_provenance or "",
            tool_name=args.tool or "",
        )
        print(json.dumps(route.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_mode_route(route), end="" if not args.json else "\n")
        return 0
    except (KeyError, ValueError) as exc:
        print(f"mode-router error: {exc}")
        return 2


def cmd_agent_context(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        context = build_agent_runtime_context(
            config.project,
            args.task or "status",
            mode_name=args.mode or "",
            previous_mode=args.previous_mode or "",
            failure_class=args.failure_class or "",
            changed_paths=args.path or (),
            input_provenance=args.input_provenance or "",
            tool_name=args.tool or "",
            include_repo_map=not args.no_repo_map,
            include_diagnostics=not args.no_diagnostics,
            include_source_checks=not args.no_source_checks,
            include_runtime=not args.no_runtime,
        )
        print(json.dumps(context.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_agent_runtime_context(context), end="" if not args.json else "\n")
        return 0 if context.ok else 1
    except (OSError, ValueError, KeyError) as exc:
        print(f"agent-context error: {exc}")
        return 2


def cmd_tool_call_trace(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.trace_command == "list":
            traces = list_tool_call_traces(config.project, limit=args.limit)
            print(json.dumps([trace.to_dict() for trace in traces], ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_tool_call_traces(traces), end="" if not args.json else "\n")
            return 0
        if args.trace_command == "show":
            trace = load_tool_call_trace(config.project, args.invocation_id)
            print(json.dumps(trace.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_tool_call_trace(trace), end="" if not args.json else "\n")
            return 0
    except KeyError as exc:
        print(f"tool-call-trace error: {exc}")
        return 2
    print("tool-call-trace error: unknown command")
    return 2


def cmd_tui_model(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        model = build_tui_status_model(
            config.project,
            task=args.task or "status",
            mode_name=args.mode or "",
            include_context_pack=args.context_pack,
            limit=args.limit,
        )
        print(render_tui_status_json(model) if args.json else render_tui_status_model(model), end="")
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"tui-model error: {exc}")
        return 2


def cmd_session(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    if args.search:
        print(render_session_search(search_session_messages(config.project, args.search, limit=args.limit)))
        return 0
    if args.export:
        body = export_session(config.project, args.export, format=args.format)
        if args.out:
            Path(args.out).expanduser().write_text(body, encoding="utf-8")
            print(args.out)
        else:
            print(body, end="")
        return 0
    if args.new is not None:
        record = create_session(config.project, args.new or "Mako session")
        print(render_session(record))
        return 0
    if args.end:
        print(render_session(close_session(config.project, args.end, reason=args.reason or "")))
        return 0
    if args.latest:
        record = latest_session(config.project)
        if not record:
            print("No sessions.")
            return 1
        print(render_session(record))
        return 0
    if args.show:
        print(render_session(load_session(config.project, args.show)))
        return 0
    if args.compact:
        print(render_session(compact_session(config.project, args.compact, keep_last=args.keep_last)))
        return 0
    if args.append:
        session_id, role, content = args.append
        print(render_session(append_message(config.project, session_id, role, content)))
        return 0
    records = list_sessions(config.project)
    if not records:
        print("No sessions.")
        return 0
    for record in records[: args.limit]:
        print(f"{record.session_id}\t{record.updated_at}\t{len(record.messages)}\t{record.title}")
    return 0


def cmd_session_bus(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.session_bus_command == "start":
            state = start_session_bus(config.project, owner=args.owner, channels=args.channel or ("cli",))
            print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_session_bus_state(state))
            return 0
        if args.session_bus_command == "stop":
            state = stop_session_bus(config.project, reason=args.reason or "")
            print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_session_bus_state(state))
            return 0
        if args.session_bus_command == "status":
            state = status_session_bus(config.project)
            print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_session_bus_state(state))
            return 0
        if args.session_bus_command == "send":
            metadata = _json_arg(args.metadata_json, default={})
            if not isinstance(metadata, dict):
                print("session-bus error: --metadata-json must be an object")
                return 2
            message = send_bus_message(
                config.project,
                channel=args.channel,
                sender=args.sender,
                target=args.target,
                session_id=args.session_id or "",
                content=args.content,
                metadata=metadata,
            )
            print(json.dumps(message.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_bus_messages([message]))
            return 0
        if args.session_bus_command == "messages":
            messages = list_bus_messages(config.project, session_id=args.session_id or "", channel=args.channel or "", limit=args.limit)
            print(json.dumps([message.to_dict() for message in messages], ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_bus_messages(messages))
            return 0
        if args.session_bus_command == "summary":
            summary = session_bus_summary(config.project)
            print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) if args.json else _render_session_bus_summary(summary))
            return 0
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        print(f"session-bus error: {exc}")
        return 2
    print("session-bus error: unknown command")
    return 2


def _render_session_bus_summary(summary: dict[str, Any]) -> str:
    state = summary.get("state") or {}
    channels = summary.get("channels") or []
    lines = [
        "# Session Bus Summary",
        "",
        f"- bus_id: {state.get('bus_id') or '(not started)'}",
        f"- status: {state.get('status') or 'stopped'}",
        f"- owner: {state.get('owner') or 'local'}",
        f"- messages: {summary.get('messages', 0)}",
        f"- sessions: {summary.get('sessions', 0)}",
        f"- channels: {', '.join(channels) if channels else '(none)'}",
    ]
    return "\n".join(lines) + "\n"


def cmd_task(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.run_agent is not None:
            task = start_agent_task(
                config.project,
                args.run_agent,
                title=args.title or "",
                include_validation=not args.no_validation,
                stop_on_failure=args.stop_on_failure,
            )
            print(render_tasks([task]))
            return 0
        if args.run_shell is not None:
            task = start_shell_task(
                config.project,
                args.run_shell,
                title=args.title or "",
                allow_risky=args.allow_risky,
            )
            print(render_tasks([task]))
            return 0 if task.status != "blocked" else 1
        if args.stop:
            task = stop_runtime_task(config.project, args.stop)
            print(render_tasks([task]))
            return 0
        if args.output:
            print(read_task_output(config.project, args.output, stream="stderr" if args.stderr else "stdout", tail_chars=args.tail))
            return 0
        if args.refresh:
            print(render_tasks(refresh_runtime_tasks(config.project)))
            return 0
        if args.add:
            task = add_task(config.project, args.add, detail=args.detail or "", status=args.status)
            print(render_tasks([task]))
            return 0
        if args.set:
            task_id, status = args.set
            task = update_task(config.project, task_id, status=status, note=args.note or "", evidence=args.evidence)
            print(render_tasks([task]))
            return 0
        print(render_tasks(load_tasks(config.project)))
        return 0
    except (ValueError, KeyError) as exc:
        print(f"task error: {exc}")
        return 2


def cmd_tasks(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.tasks_command == "list":
            tasks = refresh_runtime_tasks(config.project) if args.refresh else load_tasks(config.project)
            if args.json:
                print(json.dumps([task.__dict__ for task in tasks], ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(render_tasks(tasks), end="")
            return 0
        if args.tasks_command == "show":
            task = get_runtime_task(config.project, args.task_id, refresh=not args.no_refresh)
            output = "" if args.no_output else read_task_output(config.project, args.task_id, stream="stderr" if args.stderr else "stdout", tail_chars=args.tail)
            subagent = _subagent_for_task(config.project, task.id)
            if args.json:
                payload = task.__dict__ | {"output_preview": output, "subagent": subagent}
                print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(render_task_detail(task, output_preview=output, subagent=subagent), end="")
            return 0
        if args.tasks_command == "output":
            print(read_task_output(config.project, args.task_id, stream="stderr" if args.stderr else "stdout", tail_chars=args.tail), end="")
            return 0
        if args.tasks_command == "stop":
            task = stop_runtime_task(config.project, args.task_id)
            print(json.dumps(task.__dict__, ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_tasks([task]), end="" if not args.json else "\n")
            return 0
        if args.tasks_command == "resume":
            task = resume_runtime_task(
                config.project,
                args.task_id,
                title=args.title or "",
                allow_risky=args.allow_risky,
                include_validation=not args.no_validation,
                stop_on_failure=args.stop_on_failure,
            )
            print(json.dumps(task.__dict__, ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_tasks([task]), end="" if not args.json else "\n")
            return 0
    except (ValueError, KeyError) as exc:
        print(f"tasks error: {exc}")
        return 2
    print("tasks error: unknown command")
    return 2


def _subagent_for_task(project: str | Path, task_id: str) -> dict[str, Any]:
    try:
        records = load_subagents(project)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    for record in records:
        if record.child_task_id == task_id or record.parent_task_id == task_id:
            return record.to_dict()
    return {}


_NIGHT_API_NAMES = (
    "enqueue_night_task",
    "load_night_tasks",
    "run_night_daemon",
    "stop_night_task",
    "resume_night_task",
    "night_status",
    "render_night_tasks",
    "render_night_status",
    "render_night_result",
)


_DESKTOP_EVAL_API_NAMES = (
    "run_desktop_eval",
    "render_desktop_eval_result",
    "load_desktop_eval_run",
    "list_desktop_eval_runs",
)


_DESKTOP_SOAK_API_NAMES = (
    "run_desktop_soak",
    "render_desktop_soak_result",
    "load_desktop_soak_run",
    "latest_desktop_soak_run",
    "list_desktop_soak_runs",
)


def _load_night_api() -> dict[str, Any]:
    module_names = ("quantagent.night_daemon", "quantagent.desktop_night", "quantagent.desktop_night_daemon")
    missing_modules: list[str] = []
    incomplete_modules: list[str] = []
    for module_name in module_names:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name == module_name:
                missing_modules.append(module_name)
                continue
            raise
        missing_names = [name for name in _NIGHT_API_NAMES if not hasattr(module, name)]
        if missing_names:
            incomplete_modules.append(f"{module_name} missing {', '.join(missing_names)}")
            continue
        return {name: getattr(module, name) for name in _NIGHT_API_NAMES}
    details = "; ".join(incomplete_modules or [f"missing {', '.join(missing_modules)}"])
    raise RuntimeError(f"night daemon core unavailable: {details}")


def _load_desktop_eval_api() -> dict[str, Any]:
    try:
        module = importlib.import_module("quantagent.desktop_eval")
    except ModuleNotFoundError as exc:
        if exc.name == "quantagent.desktop_eval":
            raise RuntimeError("desktop eval core unavailable: quantagent.desktop_eval") from exc
        raise
    missing = [name for name in _DESKTOP_EVAL_API_NAMES if not hasattr(module, name)]
    if missing:
        raise RuntimeError(f"desktop eval core incomplete: missing {', '.join(missing)}")
    return {name: getattr(module, name) for name in _DESKTOP_EVAL_API_NAMES}


def _load_desktop_soak_api() -> dict[str, Any]:
    try:
        module = importlib.import_module("quantagent.desktop_soak")
    except ModuleNotFoundError as exc:
        if exc.name == "quantagent.desktop_soak":
            raise RuntimeError("desktop soak core unavailable: quantagent.desktop_soak") from exc
        raise
    missing = [name for name in _DESKTOP_SOAK_API_NAMES if not hasattr(module, name)]
    if missing:
        raise RuntimeError(f"desktop soak core incomplete: missing {', '.join(missing)}")
    return {name: getattr(module, name) for name in _DESKTOP_SOAK_API_NAMES}


def _run_desktop_l4_soak_cli(project: str | Path, args: argparse.Namespace) -> int:
    if args.cycles < 1:
        print("desktop l4-soak error: --cycles must be >= 1")
        return 2
    try:
        from .desktop_l4_soak import DesktopL4SoakConfig, run_desktop_l4_soak

        result = run_desktop_l4_soak(_build_desktop_l4_soak_config(DesktopL4SoakConfig, project, args))
        payload = _payload_from_desktop_l4_soak_result(result)
    except Exception as exc:
        print(f"desktop l4-soak error: {exc}")
        return 2

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(_render_desktop_l4_soak_result(payload), end="")
    return _desktop_l4_soak_exit_code(result, payload)


def _build_desktop_l4_soak_config(config_type: Any, project: str | Path, args: argparse.Namespace) -> Any:
    fields = getattr(config_type, "__dataclass_fields__", None)
    kwargs: dict[str, Any] = {"project": project}
    for name in (
        "dry_run",
        "execute",
        "reviewed",
        "allow_actions",
        "interval_seconds",
        "stop_file",
        "goal",
        "loop_threshold",
        "trajectory_path",
        "heartbeat_path",
        "status_path",
        "result_path",
        "phase_timeout_seconds",
    ):
        if hasattr(args, name) and (fields is None or name in fields):
            value = getattr(args, name)
            if value is not None:
                kwargs[name] = value
    if fields is not None:
        kwargs["max_cycles" if "max_cycles" in fields and "cycles" not in fields else "cycles"] = args.cycles
        return config_type(**kwargs)
    try:
        return config_type(**kwargs, cycles=args.cycles)
    except TypeError:
        return config_type(**kwargs, max_cycles=args.cycles)


def _payload_from_desktop_l4_soak_result(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return _payload_from_result(value)


def _render_desktop_l4_soak_result(payload: Any) -> str:
    if not isinstance(payload, dict):
        return f"{payload}\n"
    summary = str(payload.get("summary") or "").strip()
    status = str(payload.get("status") or "").strip()
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    lines = ["# Desktop L4 Soak", ""]
    if status:
        lines.append(f"- status: {status}")
    if payload.get("ok") is not None:
        lines.append(f"- ok: {str(bool(payload.get('ok'))).lower()}")
    if "cycles" in metrics:
        lines.append(f"- cycles: {metrics['cycles']}")
    if "actions_executed" in metrics:
        lines.append(f"- actions_executed: {metrics['actions_executed']}")
    if "verification_failures" in metrics:
        lines.append(f"- verification_failures: {metrics['verification_failures']}")
    if "loop_stops" in metrics:
        lines.append(f"- loop_stops: {metrics['loop_stops']}")
    if "watchdog_kills" in metrics:
        lines.append(f"- watchdog_kills: {metrics['watchdog_kills']}")
    if "phase_timeouts" in metrics:
        lines.append(f"- phase_timeouts: {metrics['phase_timeouts']}")
    if summary:
        lines.extend(["", summary])
    return "\n".join(lines).rstrip() + "\n"


def _desktop_l4_soak_exit_code(result: Any, payload: Any) -> int:
    status = ""
    ok = False
    if isinstance(payload, dict):
        status = str(payload.get("status") or "").strip().lower()
        ok = bool(payload.get("ok", False))
    else:
        status = str(getattr(result, "status", "") or "").strip().lower()
        ok = bool(getattr(result, "ok", False))
    if ok or status == "completed":
        return 0
    if status in {"blocked", "paused", "stopped", "failed", "verify_failed"}:
        return 1
    return 1


def _payload_from_result(value: Any) -> Any:
    if hasattr(value, "to_payload"):
        return value.to_payload()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, (list, tuple)):
        return [_payload_from_result(item) for item in value]
    if isinstance(value, dict):
        return {key: _payload_from_result(item) for key, item in value.items()}
    return value


def _print_night_json(value: Any) -> None:
    if hasattr(value, "to_json"):
        print(value.to_json())
        return
    print(json.dumps(_payload_from_result(value), ensure_ascii=False, indent=2, sort_keys=True))


def _night_run_options(args: argparse.Namespace) -> dict[str, Any]:
    options = {
        "execute": args.execute,
        "reviewed": args.reviewed,
        "allow_actions": args.allow_actions,
        "max_steps": args.max_steps,
        "max_minutes": args.max_minutes,
        "delay": args.delay,
        "stop_file": args.stop_file,
        "include_grid": args.include_grid,
        "token_limit": args.token_limit,
    }
    if hasattr(args, "max_tasks"):
        options["max_tasks"] = args.max_tasks
    if hasattr(args, "watch"):
        options["watch"] = args.watch
    if hasattr(args, "idle_sleep"):
        options["idle_sleep"] = args.idle_sleep
    if hasattr(args, "failure_pause"):
        options["failure_pause"] = args.failure_pause
    if hasattr(args, "runtime_queue"):
        options["runtime_queue"] = args.runtime_queue
    if hasattr(args, "worker_id"):
        options["worker_id"] = args.worker_id
    if hasattr(args, "lease_seconds"):
        options["lease_seconds"] = args.lease_seconds
    return options


def _night_enqueue_options(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "max_steps": args.max_steps,
        "max_minutes": args.max_minutes,
        "delay": args.delay,
        "stop_file": args.stop_file,
        "include_grid": args.include_grid,
        "token_limit": args.token_limit,
    }


def cmd_desktop_daemon(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        api = _load_night_api()
        if args.desktop_daemon_command == "run":
            if getattr(args, "runtime_queue", None):
                if args.goal:
                    print("desktop-daemon error: choose either goal or --runtime-queue")
                    return 2
                if not getattr(args, "worker_id", ""):
                    print("desktop-daemon error: --worker-id is required with --runtime-queue")
                    return 2
            if args.goal:
                api["enqueue_night_task"](
                    config.project,
                    args.goal,
                    priority=args.priority,
                    **_night_enqueue_options(args),
                )
                if args.max_tasks is None:
                    args.max_tasks = 1
            result = api["run_night_daemon"](config.project, **_night_run_options(args))
        elif args.desktop_daemon_command == "enqueue":
            result = api["enqueue_night_task"](
                config.project,
                args.goal,
                priority=args.priority,
                **_night_enqueue_options(args),
            )
        elif args.desktop_daemon_command == "status":
            result = api["night_status"](config.project)
        elif args.desktop_daemon_command == "stop":
            if args.task_id and args.all:
                print("desktop-daemon error: choose either task_id or --all")
                return 2
            result = api["stop_night_task"](config.project, task_id=args.task_id or "", all_tasks=args.all)
        elif args.desktop_daemon_command == "resume":
            result = api["resume_night_task"](config.project, args.task_id, **_night_enqueue_options(args))
        else:
            print("desktop-daemon error: unknown command")
            return 2
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"desktop-daemon error: {exc}")
        return 2

    if args.json:
        _print_night_json(result)
    else:
        print(api["render_night_result"](result), end="")
    return 0 if getattr(result, "ok", True) else 1


def cmd_desktop_eval(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        api = _load_desktop_eval_api()
        if args.desktop_eval_command == "run":
            result = api["run_desktop_eval"](
                config.project,
                suite=args.suite,
                scenario=args.scenario or "",
                duration_minutes=args.duration_minutes,
                max_steps=args.max_steps,
                execute=args.execute,
                reviewed=args.reviewed,
                allow_actions=args.allow_actions,
                stop_file=args.stop_file,
                scenario_timeout_seconds=args.scenario_timeout,
            )
            if args.json:
                print(result.to_json() if hasattr(result, "to_json") else json.dumps(_payload_from_result(result), ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(api["render_desktop_eval_result"](result), end="")
            return 0 if getattr(result, "ok", True) else 1
        if args.desktop_eval_command == "list":
            result = api["list_desktop_eval_runs"](config.project)
            print(json.dumps(_payload_from_result(result), ensure_ascii=False, indent=2, sort_keys=True) if args.json else _render_desktop_eval_runs(result), end="" if not args.json else "\n")
            return 0
        if args.desktop_eval_command == "show":
            result = api["load_desktop_eval_run"](args.path)
            if args.json:
                print(result.to_json() if hasattr(result, "to_json") else json.dumps(_payload_from_result(result), ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(api["render_desktop_eval_result"](result), end="")
            return 0
        if args.desktop_eval_command == "soak":
            soak_api = _load_desktop_soak_api()
            result = soak_api["run_desktop_soak"](
                config.project,
                suite=args.suite,
                hours=args.hours,
                interval_seconds=args.interval,
                max_cycles=args.max_cycles,
                max_steps=args.max_steps,
                execute=args.execute,
                reviewed=args.reviewed,
                allow_actions=args.allow_actions,
                guardian=not args.no_guardian,
                require_evidence=args.require_evidence,
                watchdog=not args.no_watchdog,
                cycle_timeout_seconds=args.cycle_timeout,
                watchdog_interval_seconds=args.watchdog_interval,
                stop_file=args.stop_file,
            )
            if args.json:
                print(result.to_json() if hasattr(result, "to_json") else json.dumps(_payload_from_result(result), ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(soak_api["render_desktop_soak_result"](result), end="")
            return 0 if getattr(result, "ok", True) else 1
        if args.desktop_eval_command == "soak-latest":
            soak_api = _load_desktop_soak_api()
            result = soak_api["latest_desktop_soak_run"](config.project)
            if args.json:
                print(result.to_json() if hasattr(result, "to_json") else json.dumps(_payload_from_result(result), ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(soak_api["render_desktop_soak_result"](result), end="")
            return 0 if getattr(result, "status", "") == "running" or getattr(result, "ok", True) else 1
        if args.desktop_eval_command == "soak-show":
            soak_api = _load_desktop_soak_api()
            result = soak_api["load_desktop_soak_run"](args.path)
            if args.json:
                print(result.to_json() if hasattr(result, "to_json") else json.dumps(_payload_from_result(result), ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(soak_api["render_desktop_soak_result"](result), end="")
            return 0 if getattr(result, "ok", True) else 1
        if args.desktop_eval_command == "soak-list":
            soak_api = _load_desktop_soak_api()
            result = soak_api["list_desktop_soak_runs"](config.project)
            print(json.dumps(_payload_from_result(result), ensure_ascii=False, indent=2, sort_keys=True) if args.json else _render_desktop_soak_runs(result), end="" if not args.json else "\n")
            return 0
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"desktop-eval error: {exc}")
        return 2
    print("desktop-eval error: unknown command")
    return 2


def _render_desktop_eval_runs(runs: Any) -> str:
    items = list(runs or [])
    if not items:
        return "No desktop eval runs.\n"
    lines = ["# Desktop Eval Runs", ""]
    for item in items[-30:]:
        payload = _payload_from_result(item)
        if not isinstance(payload, dict):
            lines.append(f"- {payload}")
            continue
        run_id = payload.get("run_id") or payload.get("id") or payload.get("path") or "-"
        status = payload.get("status") or "-"
        score = ""
        metrics = payload.get("metrics")
        if isinstance(metrics, dict) and metrics.get("score") is not None:
            score = f" score={metrics.get('score')}"
        path = payload.get("json_path") or payload.get("path") or ""
        suffix = f" {path}" if path else ""
        lines.append(f"- {run_id} [{status}]{score}{suffix}")
    return "\n".join(lines).rstrip() + "\n"


def _render_desktop_soak_runs(runs: Any) -> str:
    items = list(runs or [])
    if not items:
        return "No desktop soak runs.\n"
    lines = ["# Desktop Soak Runs", ""]
    for item in items[-30:]:
        payload = _payload_from_result(item)
        if not isinstance(payload, dict):
            lines.append(f"- {payload}")
            continue
        metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
        run_id = payload.get("run_id") or "-"
        status = payload.get("status") or "-"
        level = metrics.get("level", "-")
        score = metrics.get("score", "-")
        hours = metrics.get("long_run_hours", 0)
        path = payload.get("json_path") or ""
        try:
            hours_text = f"{float(hours):.3f}h"
        except (TypeError, ValueError):
            hours_text = "-"
        suffix = f" {path}" if path else ""
        lines.append(f"- {run_id} [{status}] level={level} score={score} long_run={hours_text}{suffix}")
    return "\n".join(lines).rstrip() + "\n"


def cmd_desktop(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    if args.desktop_command == "front":
        result = frontmost_app()
    elif args.desktop_command == "guard":
        result = run_desktop_guardian(
            config.project,
            watch=args.watch,
            interval=args.interval,
            max_minutes=args.max_minutes,
            max_event_age_seconds=args.max_event_age_seconds,
            same_action_limit=args.same_action_limit,
            state_path=args.state_path or None,
            query_events_path=args.query_events_path or None,
            trajectory_path=args.trajectory_path or None,
            stop_file=args.stop_file or None,
        )
        if args.json:
            print(result.to_json())
        else:
            print(render_desktop_guardian_result(result), end="")
        return 0 if result.ok else 1
    elif args.desktop_command == "live":
        probe = bool(getattr(args, "probe", False))
        probe_network_url = str(getattr(args, "probe_network", "") or "")
        state = build_desktop_live_state(config.project, limit=args.limit, probe=probe, probe_network_url=probe_network_url)
        if getattr(args, "html_out", None):
            path = write_desktop_live_html(state, args.html_out)
            print(path)
            return 0
        if getattr(args, "html", False):
            print(render_desktop_live_html(state), end="")
            return 0
        if args.json:
            print(render_desktop_live_json(state), end="")
            return 0
        if args.once:
            print(render_desktop_live_state(state, color=not args.no_color), end="")
            return 0
        return run_desktop_live(config.project, interval=args.interval, limit=args.limit, once=False, color=not args.no_color, probe=probe, probe_network_url=probe_network_url)
    elif args.desktop_command == "window":
        result = front_window()
    elif args.desktop_command == "open":
        plan = plan_open_target(config.project, args.target, kind=args.kind, browser=args.browser, cwd=args.cwd)
        run = open_target(config.project, args.target, kind=args.kind, browser=args.browser, cwd=args.cwd, execute=args.execute, reviewed=args.reviewed)
        if args.json:
            print(run.to_json())
        elif args.plan_only:
            print(render_desktop_plan(plan))
        else:
            print(render_desktop_plan(plan))
            print(render_desktop_run(run))
        return 0 if run.ok else 1
    elif args.desktop_command == "shot":
        result = screenshot(config.project, name=args.name)
    elif args.desktop_command == "grid":
        result = screenshot_grid(config.project, cols=args.cols, rows=args.rows, name=args.name)
    elif args.desktop_command == "ax":
        result = ax_snapshot(config.project, max_depth=args.depth, limit=args.limit, name=args.name)
    elif args.desktop_command == "ocr":
        result = ocr_image(config.project, image_path=args.image, name=args.name)
    elif args.desktop_command == "som":
        result = som_capture(
            config.project,
            image_path=args.image,
            include_ax=not args.no_ax,
            include_ocr=not args.no_ocr,
            include_grid=args.include_grid,
            cols=args.cols,
            rows=args.rows,
            name=args.name,
        )
    elif args.desktop_command == "tokenize":
        tokenization = build_desktop_tokenization(
            config.project,
            image_path=args.image,
            include_ax=not args.no_ax,
            include_ocr=not args.no_ocr,
            include_som=not args.no_som,
            include_grid=args.include_grid,
            cols=args.cols,
            rows=args.rows,
            limit=args.limit,
            name=args.name,
        )
        print(tokenization.to_json() if args.json else render_desktop_tokenization(tokenization), end="" if not args.json else "\n")
        return 0 if tokenization.ok else 1
    elif args.desktop_command == "decide":
        token_path = Path(args.tokens).expanduser() if args.tokens else latest_desktop_tokenization(config.project)
        if token_path and not token_path.is_absolute():
            token_path = config.project / token_path
        if not token_path or not token_path.exists():
            print("desktop error: no tokenization file found; run `mako desktop tokenize` first")
            return 2
        decision = decide_desktop_action(
            args.goal,
            load_desktop_tokenization(token_path),
            last_action=args.last_action,
            last_result=args.last_result,
            browser=args.browser,
            engine=args.engine,
        )
        print(decision.to_json() if args.json else render_desktop_decision(decision), end="" if not args.json else "\n")
        return 0 if decision.ok else 1
    elif args.desktop_command == "daemon":
        daemon = run_desktop_daemon(
            config.project,
            args.goal,
            execute=args.execute,
            reviewed=args.reviewed,
            allow_actions=args.allow_actions,
            browser=args.browser,
            engine=args.engine,
            max_steps=args.max_steps,
            delay=args.delay,
            stop_file=args.stop_file,
            include_grid=args.include_grid,
            token_limit=args.token_limit,
        )
        print(daemon.to_json() if args.json else render_desktop_daemon_result(daemon), end="" if not args.json else "\n")
        return 0 if daemon.ok else 1
    elif args.desktop_command == "night":
        try:
            api = _load_night_api()
            if args.night_command == "enqueue":
                result = api["enqueue_night_task"](config.project, args.goal, **_night_enqueue_options(args))
                if args.json:
                    _print_night_json(result)
                else:
                    print(api["render_night_result"](result), end="")
                return 0 if getattr(result, "ok", True) else 1
            if args.night_command == "run":
                if getattr(args, "runtime_queue", None) and not getattr(args, "worker_id", ""):
                    print("desktop night error: --worker-id is required with --runtime-queue")
                    return 2
                result = api["run_night_daemon"](config.project, **_night_run_options(args))
                if args.json:
                    _print_night_json(result)
                else:
                    print(api["render_night_result"](result), end="")
                return 0 if getattr(result, "ok", True) else 1
            if args.night_command == "status":
                status = api["night_status"](config.project)
                if args.json:
                    _print_night_json(status)
                else:
                    print(api["render_night_status"](status), end="")
                return 0
            if args.night_command == "stop":
                if args.task_id and args.all:
                    print("desktop night error: choose either task_id or --all")
                    return 2
                result = api["stop_night_task"](config.project, task_id=args.task_id or "", all_tasks=args.all)
                if args.json:
                    _print_night_json(result)
                else:
                    print(api["render_night_result"](result), end="")
                return 0 if getattr(result, "ok", True) else 1
            if args.night_command == "resume":
                result = api["resume_night_task"](config.project, args.task_id, **_night_enqueue_options(args))
                if args.json:
                    _print_night_json(result)
                else:
                    print(api["render_night_result"](result), end="")
                return 0 if getattr(result, "ok", True) else 1
        except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
            print(f"desktop night error: {exc}")
            return 2
        print("desktop night error: unknown command")
        return 2
    elif args.desktop_command == "l4-soak":
        return _run_desktop_l4_soak_cli(config.project, args)
    elif args.desktop_command == "find":
        result = desktop_find(
            config.project,
            args.query,
            source=args.source,
            limit=args.limit,
            ax_path=args.ax,
            grid_path=args.grid,
            ocr_path=args.ocr,
            som_path=args.som,
            refresh_ax=args.refresh_ax,
            refresh_som=args.refresh_som,
        )
        print(result.to_json() if args.json else render_desktop_hits(result))
        return 0 if result.ok else 1
    elif args.desktop_command == "web-search":
        plan = plan_web_search(args.query, browser=args.browser, engine=args.engine)
        run = execute_desktop_plan(config.project, plan, execute=args.execute, reviewed=args.reviewed, verify_after=args.verify_after)
        if args.json:
            print(run.to_json())
        elif args.plan_only:
            print(render_desktop_plan(plan))
        else:
            print(render_desktop_plan(plan))
            print(render_desktop_run(run))
        return 0 if run.ok else 1
    elif args.desktop_command == "find-click":
        plan = plan_find_and_click(config.project, args.query, source=args.source)
        run = execute_desktop_plan(config.project, plan, execute=args.execute, reviewed=args.reviewed, verify_after=args.verify_after)
        if args.json:
            print(run.to_json())
        else:
            print(render_desktop_plan(plan))
            print(render_desktop_run(run))
        return 0 if run.ok else 1
    elif args.desktop_command == "run":
        plan = load_desktop_plan(Path(args.plan).expanduser())
        run = execute_desktop_plan(config.project, plan, execute=args.execute, reviewed=args.reviewed, verify_after=args.verify_after)
        print(run.to_json() if args.json else render_desktop_run(run))
        return 0 if run.ok else 1
    elif args.desktop_command == "plan-click":
        path = Path(args.grid).expanduser() if args.grid else latest_grid(config.project)
        if not path:
            print("desktop error: no grid file found; run `mako desktop grid` first")
            return 2
        payload = json.loads(path.read_text(encoding="utf-8"))
        plan = plan_click(payload, args.query)
        print(plan.to_json() if args.json else render_click_plan(plan))
        return 0 if plan.ok else 1
    elif args.desktop_command == "grid-click":
        result = click_grid_cell(config.project, args.cell, grid_path=args.grid)
    elif args.desktop_command == "som-click":
        result = click_som_target(config.project, args.mark, som_path=args.som)
    elif args.desktop_command == "send-confirm":
        send_result = run_desktop_send_confirm(
            config.project,
            args.text,
            count=args.count,
            execute=args.execute,
            reviewed=args.reviewed,
            confirm=not args.no_confirm,
            confirm_timeout=args.confirm_timeout,
            poll_interval=args.poll_interval,
            interval=args.interval,
            max_count=args.max_count,
            stop_file=args.stop_file,
        )
        print(send_result.to_json() if args.json else render_desktop_send_confirm_result(send_result), end="" if not args.json else "\n")
        return 0 if send_result.ok else 1
    elif args.desktop_command == "schema":
        print(json.dumps(gui_action_schema(), ensure_ascii=False, indent=2))
        return 0
    elif args.desktop_command == "modes":
        print(render_mode_notes())
        return 0
    elif args.desktop_command == "targets":
        path = Path(args.grid).expanduser() if args.grid else latest_grid(config.project)
        if not path:
            print("desktop error: no grid file found; run `mako desktop grid` first")
            return 2
        payload = json.loads(path.read_text(encoding="utf-8"))
        targets = targets_from_grid(payload)
        if args.json:
            print(json.dumps([target.to_payload() for target in targets], ensure_ascii=False, indent=2))
        else:
            for target in targets:
                coord = target_to_coordinate(target, grid_payload=payload)
                print(f"{target.value}\t{coord[0]},{coord[1]}" if coord else str(target.value))
        return 0
    elif args.desktop_command == "activate":
        result = activate_app(args.app)
    elif args.desktop_command == "type":
        result = type_text(args.text)
    elif args.desktop_command == "hotkey":
        result = hotkey(args.keys)
    elif args.desktop_command == "click":
        result = pointer(config.project, "click", args.x, args.y)
    elif args.desktop_command == "move":
        result = pointer(config.project, "move", args.x, args.y)
    else:
        print("desktop error: unknown command")
        return 2
    print(result.to_json() if args.json else result.summary)
    return 0 if result.ok else 1


def cmd_desktop_agent(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    result = run_desktop_agent(
        config.project,
        args.instruction,
        execute=args.execute,
        reviewed=args.reviewed,
        browser=args.browser,
        max_actions=args.max_actions,
        delay=args.delay,
        verify_after=args.verify_after,
        stop_file=args.stop_file,
    )
    print(result.to_json() if args.json else render_desktop_agent_result(result), end="" if not args.json else "\n")
    return 0 if result.ok else 1


def cmd_desktop_overnight(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    result = run_desktop_overnight(
        config.project,
        args.goal,
        execute=args.execute,
        reviewed=args.reviewed,
        allow_actions=args.allow_actions,
        browser=args.browser,
        max_rounds=args.max_rounds,
        max_minutes=args.max_minutes,
        delay=args.delay,
        max_actions=args.max_actions,
        stop_file=args.stop_file,
        require_action_approval=args.require_action_approval,
        approval_id=args.approval_id or None,
    )
    print(result.to_json() if args.json else render_desktop_overnight_result(result), end="" if not args.json else "\n")
    return 0 if result.ok else 1


def _print_file_result(result, as_json: bool = False) -> int:
    if as_json:
        import json

        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    else:
        print(result.summary)
        if "preview" in result.data:
            print(result.data["preview"])
        if "diff" in result.data:
            print(result.data["diff"])
        if "matches" in result.data:
            for match in result.data["matches"]:
                print(f"{match['path']}:{match['line']}: {match['preview']}")
    return 0 if result.ok else 1


def cmd_files(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    if args.files_command == "read":
        result = read_preview(config.project, args.path, max_chars=args.max_chars)
    elif args.files_command == "search":
        result = search_text(
            config.project,
            args.pattern,
            path=args.path,
            max_results=args.max_results,
            glob=args.glob,
            case_sensitive=not args.ignore_case,
        )
    elif args.files_command == "diff-replace":
        result = diff_exact_replace_preview(
            config.project,
            args.path,
            args.old,
            args.new,
            expected_count=args.expected_count,
        )
    elif args.files_command == "replace":
        result = replace_exact(
            config.project,
            args.path,
            args.old,
            args.new,
            expected_count=args.expected_count,
        )
    elif args.files_command == "diff-write":
        result = unified_diff_preview(config.project, args.path, args.text)
    elif args.files_command == "write":
        result = write_text(config.project, args.path, args.text)
    else:
        print("files error: unknown command")
        return 2
    return _print_file_result(result, as_json=args.json)


def _render_memory_candidates(candidates) -> str:
    if not candidates:
        return "No memory candidates.\n"
    lines = ["# Memory Candidates", ""]
    for index, candidate in enumerate(candidates, start=1):
        text = candidate.text.replace("\n", " ")
        if len(text) > 220:
            text = text[:217] + "..."
        lines.append(f"- {index}. [{candidate.kind}] confidence={candidate.confidence:.2f} source={candidate.source}: {text}")
    return "\n".join(lines) + "\n"


def cmd_memory(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    if args.learn_runtime:
        report = learn_from_query_events(config.project, query_id=args.query_id, limit=args.limit, min_confidence=args.min_confidence)
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_hermes_learning_report(report))
        return 0
    if args.propose_text:
        proposals = propose_memories(config.project, args.propose_text, source=args.source or "cli:sidecar", min_confidence=args.min_confidence)
        print(json.dumps([proposal.to_dict() for proposal in proposals], ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_memory_proposals(proposals))
        return 0
    if args.proposals:
        proposals = load_memory_proposals(config.project, status=args.status)
        print(json.dumps([proposal.to_dict() for proposal in proposals], ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_memory_proposals(proposals))
        return 0
    if args.approve_proposal:
        try:
            proposal = approve_memory_proposal(config.project, args.approve_proposal, reason=args.reason or "")
        except ValueError as exc:
            print(f"memory error: {exc}")
            return 2
        print(json.dumps(proposal.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_memory_proposals([proposal]))
        return 0
    if args.deny_proposal:
        proposal = deny_memory_proposal(config.project, args.deny_proposal, reason=args.reason or "")
        print(json.dumps(proposal.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_memory_proposals([proposal]))
        return 0
    candidates = None
    if args.extract_text:
        candidates = extract_memory_candidates(args.extract_text, source=args.source or "cli:text")
    elif args.extract_report:
        path = Path(args.extract_report).expanduser()
        if not path.is_absolute():
            path = config.project / path
        candidates = extract_from_report(path.read_text(encoding="utf-8", errors="replace"), source=args.source or str(path))
    elif args.extract_session:
        record = load_session(config.project, args.extract_session)
        source = args.source or f"session:{record.session_id}"
        candidates = extract_memory_candidates(record.messages, source=source)
    elif args.extract_tool_loop:
        path = Path(args.extract_tool_loop).expanduser()
        if not path.is_absolute():
            path = config.project / path
        payload = json.loads(path.read_text(encoding="utf-8"))
        candidates = extract_from_tool_loop(payload, source=args.source or str(path))

    if candidates is not None:
        if args.dry_run:
            print(_render_memory_candidates(candidates))
            return 0
        entries = add_candidates_to_store(config.project, candidates)
        print(render_memories(entries))
        return 0

    store = MemoryStore(config.project)
    try:
        if args.add:
            try:
                entry = store.add(args.add, kind=args.kind, source=args.source or "")
            except ValueError as exc:
                print(f"memory error: {exc}")
                return 2
            print(render_memories([entry]))
            return 0
        if args.search:
            print(render_memories(store.search(args.search, limit=args.limit)))
            return 0
        print(render_memories(store.recent(limit=args.limit, kind=args.kind if args.kind_filter else None)))
        return 0
    finally:
        store.close()


def cmd_toolsets(args: argparse.Namespace) -> int:
    try:
        print(render_toolsets(args.name))
        return 0
    except (KeyError, ValueError) as exc:
        print(f"toolsets error: {exc}")
        return 2


def cmd_edit_loop(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    if not args.test:
        print("edit-loop error: --test requires a command")
        return 2
    if args.plan_json:
        try:
            plan = _load_change_set_plan(args.plan_json, args.test, args.max_attempts, args.timeout, args.allow_risky_tests, not args.keep_failed)
        except (OSError, ValueError, TypeError) as exc:
            print(f"edit-loop error: {exc}")
            return 2
        result = run_change_set_retry(config.project, plan)
        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(result.summary)
            for attempt in result.attempts:
                label = f" ({attempt.name})" if attempt.name else ""
                print(f"- attempt {attempt.index}{label}: {attempt.summary}")
                if attempt.blocked:
                    print(f"  blocked: {attempt.reason}")
                if attempt.stderr_preview:
                    print(attempt.stderr_preview)
        return 0 if result.ok else 1

    if not args.path or args.old is None or not args.new_values:
        print("edit-loop error: provide PATH --old --new, or use --plan-json")
        return 2
    result = run_edit_test_retry(
        config.project,
        EditPlan(
            path=args.path,
            old=args.old,
            candidate_replacements=args.new_values,
            test_command=args.test,
            expected_count=args.expected_count,
            max_attempts=args.max_attempts,
            timeout=args.timeout,
            before_context=args.before,
            after_context=args.after,
            allow_risky_tests=args.allow_risky_tests,
            restore_on_failure=not args.keep_failed,
        ),
    )
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(result.summary)
        for attempt in result.attempts:
            print(f"- attempt {attempt.index}: {attempt.summary}")
            if attempt.blocked:
                print(f"  blocked: {attempt.reason}")
            if attempt.stderr_preview:
                print(attempt.stderr_preview)
    return 0 if result.ok else 1


def _load_change_set_plan(
    path: str,
    test_command: list[str],
    max_attempts: int,
    timeout: int,
    allow_risky_tests: bool,
    restore_on_failure: bool,
) -> ChangeSetPlan:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    raw_candidates = payload.get("candidates") if isinstance(payload, dict) else None
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ValueError("plan JSON must contain a non-empty candidates list")
    candidates: list[ChangeSetCandidate] = []
    for raw_candidate in raw_candidates:
        if not isinstance(raw_candidate, dict):
            raise ValueError("each candidate must be an object")
        raw_edits = raw_candidate.get("edits")
        if not isinstance(raw_edits, list) or not raw_edits:
            raise ValueError("each candidate must contain a non-empty edits list")
        edits: list[FileReplacement] = []
        for raw_edit in raw_edits:
            if not isinstance(raw_edit, dict):
                raise ValueError("each edit must be an object")
            try:
                edit_path = raw_edit["path"]
                old = raw_edit["old"]
                new = raw_edit["new"]
            except KeyError as exc:
                raise ValueError(f"edit missing required field: {exc.args[0]}") from exc
            if not all(isinstance(value, str) for value in (edit_path, old, new)):
                raise ValueError("edit path, old, and new must be strings")
            edits.append(
                FileReplacement(
                    path=edit_path,
                    old=old,
                    new=new,
                    expected_count=int(raw_edit.get("expected_count", 1)),
                    before_context=raw_edit.get("before"),
                    after_context=raw_edit.get("after"),
                )
            )
        candidates.append(ChangeSetCandidate(edits=edits, name=str(raw_candidate.get("name") or "")))
    return ChangeSetPlan(
        candidates=candidates,
        test_command=test_command,
        max_attempts=max_attempts,
        timeout=timeout,
        allow_risky_tests=allow_risky_tests,
        restore_on_failure=restore_on_failure,
    )


def cmd_sandbox(args: argparse.Namespace) -> int:
    try:
        project_path = None
        if getattr(args, "project", None):
            project_path = load_config(args.project).project
        if args.explain_shell:
            project_for_shell = project_path or Path.cwd()
            semantics = classify_shell_command(
                args.explain_shell,
                cwd=args.cwd or project_for_shell,
                project=project_for_shell,
            )
            if args.json:
                print(json.dumps(semantics.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(render_shell_semantics(semantics), end="")
            return 1 if semantics.deny_hardline else 0
        if args.check_tool:
            args_payload = json.loads(args.args_json or "{}")
            if not isinstance(args_payload, dict):
                print("sandbox error: --args-json must be an object")
                return 2
            if args.json:
                decision = enforce_tool(
                    args.profile,
                    args.check_tool,
                    reason=args.reason or "",
                    owner_approved=args.approve,
                    project=project_path,
                    args=args_payload,
                )
                print(json.dumps(decision.metadata(), ensure_ascii=False, indent=2))
                return 0 if decision.allowed else 1
            decision = enforce_tool(
                args.profile,
                args.check_tool,
                reason=args.reason or "",
                owner_approved=args.approve,
                project=project_path,
                args=args_payload,
            )
            print(f"{decision.action.upper()} {args.profile}: {decision.summary}")
            return 0 if decision.allowed else 1
        print(render_profiles(args.profile if args.show_profile else None))
        return 0
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"sandbox error: {exc}")
        return 2


def cmd_plugins(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    registry = build_plugin_registry(config.project)
    if args.snapshot or args.write_snapshot or args.compare_snapshot:
        snapshot = build_plugin_install_snapshot(registry)
        snapshot_payload = snapshot.to_dict()
        previous_payload = _load_snapshot_json(args.compare_snapshot, project=config.project) if args.compare_snapshot else None
        written_path = _write_snapshot_json(args.write_snapshot, snapshot_payload, project=config.project) if args.write_snapshot else None
        if previous_payload is not None:
            diff = _diff_plugin_snapshot_payloads(previous_payload, snapshot_payload)
            if written_path is not None:
                diff["snapshot_path"] = str(written_path)
            print(json.dumps(diff, ensure_ascii=False, indent=2, sort_keys=True) if args.json else _render_snapshot_diff("Plugin Install Snapshot Diff", diff), end="" if not args.json else "\n")
            return 1 if diff["has_drift"] or any(item.level == "error" for item in registry.diagnostics) else 0
        if written_path is not None and not args.json:
            print(f"wrote: {written_path}")
        if args.json:
            if written_path is not None:
                snapshot_payload = {**snapshot_payload, "snapshot_path": str(written_path)}
            print(json.dumps(snapshot_payload, ensure_ascii=False, indent=2, sort_keys=True))
        elif not written_path:
            print(_render_snapshot_summary("Plugin Install Snapshot", snapshot_payload), end="")
        return 0 if not any(item.level == "error" for item in registry.diagnostics) else 1
    if args.refresh:
        path = write_plugin_registry(config.project, registry)
        print(path)
        return 0 if not any(item.level == "error" for item in registry.diagnostics) else 1
    if args.trust_report:
        print(render_plugin_trust_reports(registry), end="")
        return 0 if not any(item.level == "error" for item in registry.diagnostics) else 1
    if args.json:
        print(json.dumps(registry.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_plugin_registry(registry))
    return 0 if not any(item.level == "error" for item in registry.diagnostics) else 1


def _resolve_snapshot_path(raw_path: str, *, project: Path) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = project / path
    return path.resolve(strict=False)


def _load_snapshot_json(raw_path: str, *, project: Path) -> dict[str, Any]:
    path = _resolve_snapshot_path(raw_path, project=project)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("snapshot must be a JSON object")
    return payload


def _write_snapshot_json(raw_path: str, payload: dict[str, Any], *, project: Path) -> Path:
    path = _resolve_snapshot_path(raw_path, project=project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _snapshot_items(payload: dict[str, Any], key: str, id_keys: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    raw_items = payload.get(key, [])
    if not isinstance(raw_items, list):
        raise ValueError(f"snapshot field {key!r} must be a list")
    items: dict[str, dict[str, Any]] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            raise ValueError(f"snapshot field {key!r} must contain objects")
        item_id = "/".join(str(item.get(name, "")) for name in id_keys).strip("/")
        if not item_id:
            raise ValueError(f"snapshot item in {key!r} is missing identifier fields")
        items[item_id] = item
    return items


def _diff_plugin_snapshot_payloads(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    previous_items = _snapshot_items(previous, "plugins", ("plugin_id",))
    current_items = _snapshot_items(current, "plugins", ("plugin_id",))
    return _snapshot_diff_payload(previous, current, previous_items, current_items)


def _diff_mcp_schema_snapshot_payloads(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    previous_items = _snapshot_items(previous, "tools", ("server", "tool"))
    current_items = _snapshot_items(current, "tools", ("server", "tool"))
    previous_hashes = {name: item.get("schema_hash") for name, item in previous_items.items()}
    current_hashes = {name: item.get("schema_hash") for name, item in current_items.items()}
    shared = set(previous_hashes) & set(current_hashes)
    payload = {
        "schema": "quantagent.snapshot_diff.v1",
        "previous_hash": str(previous.get("snapshot_hash", "")),
        "current_hash": str(current.get("snapshot_hash", "")),
        "added": sorted(set(current_items) - set(previous_items)),
        "removed": sorted(set(previous_items) - set(current_items)),
        "changed": sorted(name for name in shared if previous_hashes[name] != current_hashes[name]),
    }
    payload["has_drift"] = bool(payload["added"] or payload["removed"] or payload["changed"])
    return payload


def _snapshot_diff_payload(
    previous: dict[str, Any],
    current: dict[str, Any],
    previous_items: dict[str, dict[str, Any]],
    current_items: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    shared = set(previous_items) & set(current_items)
    payload = {
        "schema": "quantagent.snapshot_diff.v1",
        "previous_hash": str(previous.get("snapshot_hash", "")),
        "current_hash": str(current.get("snapshot_hash", "")),
        "added": sorted(set(current_items) - set(previous_items)),
        "removed": sorted(set(previous_items) - set(current_items)),
        "changed": sorted(name for name in shared if previous_items[name] != current_items[name]),
    }
    payload["has_drift"] = bool(payload["added"] or payload["removed"] or payload["changed"])
    return payload


def _render_snapshot_summary(title: str, payload: dict[str, Any]) -> str:
    count = len(payload.get("plugins", payload.get("tools", [])))
    return "\n".join(
        [
            f"# {title}",
            "",
            f"- schema: {payload.get('schema', '')}",
            f"- snapshot_hash: {payload.get('snapshot_hash', '')}",
            f"- items: {count}",
        ]
    ) + "\n"


def _render_snapshot_diff(title: str, payload: dict[str, Any]) -> str:
    lines = [
        f"# {title}",
        "",
        f"- status: {'drift' if payload.get('has_drift') else 'clean'}",
        f"- previous_hash: {payload.get('previous_hash', '')}",
        f"- current_hash: {payload.get('current_hash', '')}",
        f"- added: {len(payload.get('added') or [])}",
        f"- removed: {len(payload.get('removed') or [])}",
        f"- changed: {len(payload.get('changed') or [])}",
    ]
    if payload.get("snapshot_path"):
        lines.append(f"- snapshot_path: {payload['snapshot_path']}")
    for key in ("added", "removed", "changed"):
        values = payload.get(key) or []
        if values:
            lines.extend(["", f"## {key.title()}", ""])
            lines.extend(f"- {value}" for value in values)
    return "\n".join(lines) + "\n"


def cmd_ecosystem(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    catalog = build_ecosystem_catalog(config.project)
    if args.refresh:
        path = write_ecosystem_catalog(config.project, catalog)
        if not args.json:
            print(path)
    if args.search or args.kind:
        catalog = filter_ecosystem_catalog(catalog, query=args.search or "", kind=args.kind or "")
    if args.json:
        print(json.dumps(catalog.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_ecosystem_catalog(catalog, limit=args.limit), end="")
    return 1 if any(item.level == "error" for item in catalog.diagnostics) else 0


def cmd_permissions(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.permissions_command == "explain":
            payload = json.loads(args.args_json or "{}")
            if not isinstance(payload, dict):
                print("permissions error: --args-json must be an object")
                return 2
            explanation = explain_permission(config.project, profile=args.profile, tool=args.tool, args=payload, owner_approved=args.approve)
            if args.json:
                print(json.dumps(explanation.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(render_permission_explanation(explanation), end="")
            return 0 if explanation.decision.get("allowed") else 1
        if args.permissions_command == "denials":
            records = recent_permission_denials(config.project, limit=args.limit)
            if args.json:
                print(json.dumps([record.__dict__ for record in records], ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(render_recent_denials(records), end="")
            return 0
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"permissions error: {exc}")
        return 2
    print("permissions error: unknown command")
    return 2


def cmd_diagnostics(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    if args.diagnostics_command == "refresh":
        snapshot = refresh_diagnostic_registry(config.project, limit=args.limit)
    else:
        try:
            snapshot = load_diagnostic_registry(config.project)
        except FileNotFoundError:
            snapshot = refresh_diagnostic_registry(config.project, limit=args.limit)
    if args.json:
        print(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_diagnostic_registry(snapshot, paths=args.path or ()), end="")
    return 1 if any(item.level == "error" for item in snapshot.diagnostics) else 0


def cmd_compact_budget(args: argparse.Namespace) -> int:
    messages = [{"role": "user", "content": item} for item in args.message]
    plan, result = auto_compact_messages(messages, token_budget=args.token_budget, pressure_threshold=args.threshold) if args.apply else (plan_auto_compact(messages, token_budget=args.token_budget, pressure_threshold=args.threshold), None)
    if args.json:
        print(json.dumps({"plan": plan.to_dict(), "result": result.to_dict() if result else None}, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_compact_plan(plan), end="")
        if result:
            print(f"compacted_messages: {len(result.messages)}")
            print(f"saved_estimated_tokens: {result.metrics.saved_estimated_tokens}")
    return 0


def cmd_diff_preview(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.review_id:
            review = load_isolation_review(config.project, args.review_id)
            preview = create_preview_from_isolation_review(
                config.project,
                review,
                task=args.task or "",
                test_command=args.test or (),
                profile=args.profile,
            )
        else:
            if args.diff_file:
                diff_path = Path(args.diff_file).expanduser()
                if not diff_path.is_absolute():
                    diff_path = config.project / diff_path
                diff_text = diff_path.read_text(encoding="utf-8", errors="replace")
                source = f"file:{diff_path}"
            elif args.diff:
                diff_text = args.diff
                source = "argument"
            else:
                print("diff-preview error: --diff, --diff-file, or --review-id is required")
                return 2
            preview = create_structured_diff_preview(
                config.project,
                diff_text,
                task=args.task or "",
                source=source,
                test_command=args.test or (),
                profile=args.profile,
            )
        if args.write:
            path = save_structured_diff_preview(config.project, preview)
            if not args.json:
                print(f"saved: {path}")
        if args.json:
            print(json.dumps(preview.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(render_structured_diff_preview(preview, include_diff=args.include_diff), end="")
        return 1 if preview.approval_required and args.fail_on_approval else 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"diff-preview error: {exc}")
        return 2


def cmd_apply_gate(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        common = {
            "preview_id": args.preview_id or "",
            "test_command": args.test or (),
            "profile": args.profile,
            "approved": args.approve,
            "allow_no_tests": args.allow_no_tests,
            "allow_diagnostic_errors": args.allow_diagnostic_errors,
            "allow_high_risk": args.allow_high_risk,
            "source_checks_enabled": not args.no_source_checks,
            "run_source_check_commands": args.run_source_check_commands,
            "expected_review_id": args.expected_review_id or "",
        }
        if args.apply_gate_command == "evaluate":
            verdict = evaluate_apply_gate(config.project, args.review_id, **common)
            print(json.dumps(verdict.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_apply_gate_verdict(verdict), end="" if not args.json else "\n")
            return 0 if verdict.allowed else 1
        if args.apply_gate_command == "apply":
            result = apply_review_with_gate(
                config.project,
                args.review_id,
                **common,
                rollback_on_failure=not args.no_rollback,
            )
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_apply_gate_result(result), end="" if not args.json else "\n")
            return 0 if result.ok else 1
    except (OSError, ValueError, KeyError, PermissionError) as exc:
        print(f"apply-gate error: {exc}")
        return 2
    print("apply-gate error: unknown command")
    return 2


def cmd_approval(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.approval_command == "list":
            records = list_approvals(config.project, status=args.status, limit=args.limit)
            if args.json:
                print(json.dumps([record.__dict__ for record in records], ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(render_approvals(records))
            return 0
        if args.approval_command == "show":
            record = get_approval(config.project, args.approval_id)
            if args.json:
                print(json.dumps(record.__dict__, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(render_approval(record))
            return 0
        if args.approval_command == "approve":
            record = approve(config.project, args.approval_id, allow_always=args.allow_always, reason=args.reason or "")
            print(render_approval(record))
            return 0
        if args.approval_command == "deny":
            record = deny(config.project, args.approval_id, reason=args.reason or "")
            print(render_approval(record))
            return 0
    except (KeyError, ValueError) as exc:
        print(f"approval error: {exc}")
        return 2
    print("approval error: unknown command")
    return 2


def cmd_mcp(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.mcp_command == "list":
            servers = load_mcp_servers(config.project)
            if args.json:
                print(json.dumps([server.__dict__ for server in servers], ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(render_mcp_servers(servers))
            return 0
        if args.mcp_command == "tools":
            catalog = list_mcp_catalog(config.project, server=args.server)
            if args.json:
                print(
                    json.dumps(
                        {
                            "servers": [server.__dict__ for server in catalog.servers],
                            "tools": [tool.__dict__ for tool in catalog.tools],
                            "errors": catalog.errors,
                        },
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                print(render_mcp_tools(catalog))
            return 0 if not catalog.errors else 1
        if args.mcp_command == "schema-snapshot":
            catalog = list_mcp_catalog(config.project, server=args.server)
            snapshot = build_mcp_schema_snapshot(catalog)
            snapshot_payload = snapshot.to_dict()
            if catalog.errors:
                snapshot_payload["errors"] = list(catalog.errors)
            previous_payload = _load_snapshot_json(args.compare, project=config.project) if args.compare else None
            written_path = _write_snapshot_json(args.write, snapshot_payload, project=config.project) if args.write else None
            if previous_payload is not None:
                diff = _diff_mcp_schema_snapshot_payloads(previous_payload, snapshot_payload)
                if catalog.errors:
                    diff["errors"] = list(catalog.errors)
                if written_path is not None:
                    diff["snapshot_path"] = str(written_path)
                print(json.dumps(diff, ensure_ascii=False, indent=2, sort_keys=True) if args.json else _render_snapshot_diff("MCP Schema Drift", diff), end="" if not args.json else "\n")
                return 1 if diff["has_drift"] or catalog.errors else 0
            if written_path is not None and not args.json:
                print(f"wrote: {written_path}")
            if args.json:
                if written_path is not None:
                    snapshot_payload = {**snapshot_payload, "snapshot_path": str(written_path)}
                print(json.dumps(snapshot_payload, ensure_ascii=False, indent=2, sort_keys=True))
            elif not written_path:
                print(_render_snapshot_summary("MCP Schema Snapshot", snapshot_payload), end="")
            return 0 if not catalog.errors else 1
        if args.mcp_command == "call":
            arguments = json.loads(args.args_json or "{}")
            if not isinstance(arguments, dict):
                print("mcp error: --args-json must be an object")
                return 2
            result = call_mcp_tool(config.project, args.server, args.tool, arguments, approval_id=args.approval_id, owner_approved=args.approve, profile=args.agent_profile or "")
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else (json.dumps(result.result, ensure_ascii=False, indent=2) if result.ok else result.error))
            return 0 if result.ok else 1
        if args.mcp_command == "status":
            status = MCP_MANAGER.status()
            print(json.dumps(status.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else f"active MCP sessions: {status.sessions}")
            return 0
        if args.mcp_command == "daemon-status":
            state = status_mcp_daemon_state(config.project, server=args.server)
            print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else _render_mcp_daemon_state(state))
            return 0
        if args.mcp_command == "daemon-start":
            state = start_mcp_daemon_state(config.project, server=args.server)
            print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else _render_mcp_daemon_state(state))
            return 0
        if args.mcp_command == "daemon-stop":
            state = stop_mcp_daemon_state(config.project, server=args.server)
            print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else _render_mcp_daemon_state(state))
            return 0
        if args.mcp_command == "daemon-cleanup":
            removed = cleanup_mcp_lease_registry(config.project, max_age_seconds=args.max_age_seconds)
            print(f"removed {removed} MCP lease record(s)")
            return 0
        if args.mcp_command == "gateway-start":
            state = start_mcp_gateway(config.project, discover=not args.no_discover, server=args.server)
            print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_mcp_gateway(state))
            return 0 if not state.errors else 1
        if args.mcp_command == "gateway-stop":
            state = stop_mcp_gateway(config.project, server=args.server)
            print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_mcp_gateway(state))
            return 0
        if args.mcp_command == "gateway-status":
            state = load_mcp_gateway(config.project, missing_ok=True)
            if state is None:
                health = gateway_health(config.project)
                print(json.dumps(health.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_mcp_gateway(health))
                return 1
            print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_mcp_gateway(state))
            return 0 if not state.errors else 1
        if args.mcp_command == "gateway-refresh":
            state = refresh_mcp_gateway(config.project, discover=not args.no_discover, server=args.server)
            print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_mcp_gateway(state))
            return 0 if not state.errors else 1
        if args.mcp_command == "gateway-health":
            health = gateway_health(config.project)
            print(json.dumps(health.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_mcp_gateway(health))
            return 0 if health.ok else 1
        if args.mcp_command == "gateway-call":
            arguments = json.loads(args.args_json or "{}")
            if not isinstance(arguments, dict):
                print("mcp error: --args-json must be an object")
                return 2
            record = gateway_call_tool(config.project, args.server, args.tool, arguments, approval_id=args.approval_id, owner_approved=args.approve, profile=args.agent_profile or "")
            print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else (record.result_preview if record.ok else record.error))
            return 0 if record.ok else 1
        if args.mcp_command == "cleanup":
            removed = MCP_MANAGER.cleanup_idle()
            print(f"cleaned {removed} idle MCP session(s)")
            return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"mcp error: {exc}")
        return 2
    print("mcp error: unknown command")
    return 2


def _render_mcp_daemon_state(state: Any) -> str:
    lines = [
        "# MCP Daemon State",
        "",
        f"- project: {state.project}",
        f"- lease_dir: {state.lease_dir}",
        f"- registry: {state.registry_path}",
        f"- leases: {len(state.leases)}",
        f"- note: {state.note}",
    ]
    if state.leases:
        lines.extend(["", "## Leases", ""])
        for lease in state.leases:
            target = lease.endpoint or (f"pid={lease.pid}" if lease.pid else "-")
            lines.append(f"- [{lease.status}] {lease.server}/{lease.transport}: {target}")
    return "\n".join(lines) + "\n"


def cmd_subagent(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.subagent_command == "start":
            record = start_subagent(
                config.project,
                args.task,
                parent_task_id=args.parent_task_id,
                context_mode=args.context_mode,
                title=args.title or "",
                include_validation=not args.no_validation,
                agent_profile=args.profile or "build",
                permission_mode=args.permission_mode or "",
                model=args.model or "",
                effort=args.effort or "",
                tools=args.tool or (),
                disallowed_tools=args.disallow_tool or (),
                mcp_servers=args.mcp_server or (),
                hooks=args.hook or (),
                skills=args.skill or (),
                background=not args.foreground,
                isolate_worktree=args.isolate_worktree,
            )
            print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_subagents([record]))
            return 0
        if args.subagent_command == "list":
            records = refresh_subagents(config.project) if args.refresh else load_subagents(config.project)
            print(json.dumps([record.to_dict() for record in records], ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_subagents(records))
            return 0
        if args.subagent_command == "show":
            record = get_subagent(config.project, args.subagent_id)
            print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_subagents([record]))
            return 0
        if args.subagent_command == "stop":
            record = stop_subagent(config.project, args.subagent_id)
            print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_subagents([record]))
            return 0
        if args.subagent_command == "bundle":
            bundle = create_subagent_review_bundle(config.project, parent_task_id=args.parent_task_id, subagent_ids=args.subagent_id or None)
            print(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_subagent_review_bundle(bundle))
            return 0
        if args.subagent_command == "bundles":
            bundles = load_subagent_review_bundles(config.project)
            if args.json:
                print(json.dumps([bundle.to_dict() for bundle in bundles], ensure_ascii=False, indent=2, sort_keys=True))
            elif not bundles:
                print("No subagent review bundles.")
            else:
                for bundle in bundles[-args.limit :]:
                    print(render_subagent_review_bundle(bundle))
            return 0
        if args.subagent_command == "backends":
            backends = detect_subagent_backends(config.project)
            print(json.dumps([backend.to_dict() for backend in backends], ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_subagent_backends(backends))
            return 0
    except (ValueError, KeyError) as exc:
        print(f"subagent error: {exc}")
        return 2
    print("subagent error: unknown command")
    return 2


def cmd_edit(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.edit_command == "plan":
            plan = create_patch_plan(
                config.project,
                args.task,
                paths=args.path or (),
                test_command=args.test or (),
                max_attempts=args.max_attempts,
            )
            if args.out:
                path = write_patch_plan(args.out, plan)
                print(path)
            print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.edit_command == "run":
            plan = load_patch_plan(args.plan_json)
            result = _run_patch_plan_from_patch_plan(config.project, plan, apply=args.apply, timeout=args.timeout, profile=args.agent_profile or "")
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if result.ok else 1
        if args.edit_command == "auto":
            result = run_auto_patch(
                config.project,
                AutoPatchSpec(
                    task=args.task,
                    path=args.path,
                    old=args.old,
                    new=args.new,
                    test_command=args.test or (),
                    expected_count=args.expected_count,
                    max_rounds=args.max_rounds,
                    timeout=args.timeout,
                    reviewed=args.reviewed,
                ),
                apply=args.apply,
                profile=args.agent_profile or "",
            )
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else result.summary)
            if not args.json and result.preview:
                print(result.preview)
            return 0 if result.ok else 1
        if args.edit_command == "repair":
            plan = load_patch_plan(args.plan_json)
            failure = args.failure or ""
            if args.failure_file:
                failure_path = Path(args.failure_file).expanduser()
                if not failure_path.is_absolute():
                    failure_path = config.project / failure_path
                failure = failure_path.read_text(encoding="utf-8", errors="replace")
            if args.workers > 1:
                result = run_multi_worker_repair(
                    config.project,
                    plan,
                    failure,
                    workers=args.workers,
                    max_rounds=args.max_rounds,
                    model=args.model or "",
                    base_url=args.base_url,
                    timeout=args.timeout,
                    profile=args.agent_profile or "build",
                )
                print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_repair_scheduler_result(result))
                return 0 if result.ok else 1
            if args.isolated_loop:
                result = run_isolated_repair_loop(
                    config.project,
                    plan,
                    failure,
                    max_rounds=args.max_rounds,
                    model=args.model or "",
                    base_url=args.base_url,
                    timeout=args.timeout,
                )
            else:
                result = propose_repair_candidates(config.project, plan, failure, model=args.model or "", base_url=args.base_url)
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if result.ok else 1
    except (OSError, ValueError, TypeError) as exc:
        print(f"edit error: {exc}")
        return 2
    print("edit error: unknown command")
    return 2


def cmd_repo_map(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.repo_map_command == "build":
            repo_map = build_repo_map(config.project)
            path = write_repo_map(config.project, repo_map)
            if args.json:
                payload = repo_map.to_dict()
                payload["path"] = str(path)
                print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(f"{path}\nfiles: {len(repo_map.files)}")
            return 0
        if args.repo_map_command == "show":
            repo_map = ensure_repo_map(config.project, rebuild=args.rebuild)
            print(json.dumps(repo_map.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_repo_map(repo_map, max_files=args.max_files))
            return 0
        if args.repo_map_command == "search":
            hits = search_repo_map(config.project, args.query, limit=args.limit, rebuild=args.rebuild)
            print(json.dumps([hit.to_dict() for hit in hits], ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_repo_map_hits(hits))
            return 0
        if args.repo_map_command == "related":
            hits = related_repo_paths(config.project, args.path, limit=args.limit, rebuild=args.rebuild)
            print(json.dumps([hit.to_dict() for hit in hits], ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_repo_map_hits(hits))
            return 0
        if args.repo_map_command == "context":
            print(render_repo_context(config.project, args.query, budget_chars=args.budget_chars, rebuild=args.rebuild), end="")
            return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"repo-map error: {exc}")
        return 2
    print("repo-map error: unknown command")
    return 2


def cmd_index(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    if args.index_command == "build":
        index = build_code_index(config.project)
        path = write_code_index(config.project, index)
        print(f"{path}\nchunks: {len(index.chunks)}")
        return 0
    if args.index_command == "search":
        hits = search_code_index(config.project, args.query, limit=args.limit, rebuild=args.rebuild)
        if args.json:
            print(json.dumps([hit.__dict__ for hit in hits], ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(render_code_search_hits(hits))
        return 0
    if args.index_command == "related":
        hits = related_files(config.project, args.path, limit=args.limit, rebuild=args.rebuild)
        if args.json:
            print(json.dumps([hit.__dict__ for hit in hits], ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(render_related_files(hits))
        return 0
    if args.index_command == "editor-diagnostics":
        diagnostics = editor_diagnostics(config.project, limit=args.limit)
        if args.json:
            print(json.dumps([asdict(item) for item in diagnostics], ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(render_editor_diagnostics(diagnostics))
        return 0 if not any(item.level == "error" for item in diagnostics) else 1
    if args.index_command == "diagnose":
        health = diagnose_code_index(config.project, rebuild=args.rebuild, include_editor_diagnostics=args.editor_diagnostics)
        if args.json:
            print(json.dumps(health.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(render_code_index_health(health))
        return 0 if not any(item.level == "error" for item in health.diagnostics) else 1
    print("index error: unknown command")
    return 2


def cmd_retrieval(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.retrieval_command == "build":
            index = build_retrieval_index(config.project, rebuild_code_index=args.rebuild_code_index)
            path = write_retrieval_index(config.project, index)
            if args.json:
                print(json.dumps(index.to_dict() | {"path": str(path)}, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(render_retrieval_index(index), end="")
            return 0
        if args.retrieval_command == "search":
            hits = search_retrieval_index(config.project, args.query, limit=args.limit, seed_paths=args.seed_path or [], rebuild=args.rebuild)
            print(json.dumps([hit.to_dict() for hit in hits], ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_retrieval_hits(hits))
            return 0
        if args.retrieval_command == "related":
            hits = related_retrieval_paths(config.project, args.path, limit=args.limit, rebuild=args.rebuild)
            print(json.dumps([hit.to_dict() for hit in hits], ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_retrieval_hits(hits))
            return 0
        if args.retrieval_command == "start":
            state = start_retrieval_daemon(config.project, rebuild=args.rebuild)
            print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_retrieval_state(state))
            return 0
        if args.retrieval_command == "stop":
            state = stop_retrieval_daemon(config.project)
            print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_retrieval_state(state))
            return 0
        if args.retrieval_command == "status":
            state = load_retrieval_daemon_state(config.project, missing_ok=True)
            if state is None:
                health = retrieval_health(config.project)
                print(json.dumps(health.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_retrieval_state(health))
                return 1
            print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_retrieval_state(state))
            return 0
        if args.retrieval_command == "health":
            health = retrieval_health(config.project)
            print(json.dumps(health.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_retrieval_state(health))
            return 0 if health.ok else 1
        if args.retrieval_command == "ensure":
            index = ensure_retrieval_index(config.project, rebuild=args.rebuild)
            print(json.dumps(index.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_retrieval_index(index))
            return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"retrieval error: {exc}")
        return 2
    print("retrieval error: unknown command")
    return 2


def cmd_eval(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.eval_command == "scorecard":
            scorecard = build_eval_scorecard(latest_eval_ledger_row(config.project))
            print(json.dumps(scorecard, ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_eval_scorecard(scorecard), end="" if not args.json else "\n")
            return 0 if scorecard["status"] == "pass" else 1
        cases = load_eval_cases(config.project)
        if args.builtin or (not cases and not args.builtin_code):
            cases.extend(builtin_smoke_eval_cases())
        if args.builtin_code:
            cases.extend(builtin_code_eval_cases())
        if args.tag:
            wanted = set(args.tag)
            cases = [case for case in cases if wanted & set(case.tags)]
        if args.eval_command == "list":
            payload = [case.to_dict() for case in cases]
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                for case in cases:
                    print(f"- {case.id}: {case.command}")
            return 0
        if args.eval_command == "run":
            run = run_eval_cases(config.project, cases)
            print(render_eval_json(run) if args.json else render_eval_markdown(run))
            return 0 if all(result.score == result.max_score for result in run.results) else 1
        if args.eval_command == "once":
            run = run_eval_cases(config.project, cases)
            append_eval_ledger(run)
            scorecard = build_eval_scorecard(run.to_dict())
            if args.json:
                print(json.dumps({"run": run.to_dict(), "scorecard": scorecard}, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(render_eval_gap_report(build_eval_gap_report(run)), end="")
                print()
                print(render_eval_scorecard(scorecard), end="")
            return 0 if all(result.score == result.max_score for result in run.results) else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"eval error: {exc}")
        return 2
    print("eval error: unknown command")
    return 2


def cmd_code_eval(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        fixtures = list_code_eval_fixtures()
        all_fixture_ids = [item.id for item in fixtures]

        # Support both --fixture id1 --fixture id2 and --fixture id1,id2,id3
        if hasattr(args, 'all') and args.all:
            # --all flag: use all fixtures
            pass
        elif args.fixture:
            # Expand comma-separated fixture IDs
            expanded = []
            for item in args.fixture:
                expanded.extend(f.strip() for f in item.split(',') if f.strip())
            wanted = set(expanded)
            fixtures = tuple(item for item in fixtures if item.id in wanted)
            missing = sorted(wanted - {item.id for item in fixtures})
            if missing:
                available = ', '.join(all_fixture_ids[:5])
                hint = f"\n\nAvailable fixtures: {available}{'...' if len(all_fixture_ids) > 5 else ''}\nRun 'mako code-eval list' to see all fixtures."
                raise KeyError(f"unknown code eval fixture(s): {', '.join(missing)}{hint}")
        if args.code_eval_command == "list":
            if args.json:
                print(json.dumps([item.to_dict() for item in fixtures], ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(render_code_eval_fixture_list(fixtures), end="")
            return 0
        if args.code_eval_command == "run":
            run = run_code_eval_pack(
                config.project,
                fixture_ids=[item.id for item in fixtures],
                apply_oracle=not args.no_oracle,
                keep_workspaces=not args.clean,
            )
            print(render_code_eval_json(run) if args.json else render_code_eval_markdown(run), end="" if not args.json else "\n")
            return 0 if run.summary["failed"] == 0 else 1
        if args.code_eval_command == "solve":
            run = run_code_eval_solve_pack(
                config.project,
                fixture_ids=[item.id for item in fixtures],
                model=args.model or "",
                base_url=args.base_url or None,
                max_rounds=args.max_rounds,
                keep_workspaces=not args.clean,
            )
            print(render_code_eval_solve_json(run) if args.json else render_code_eval_solve_markdown(run), end="" if not args.json else "\n")
            return 0 if run.summary["failed"] == 0 else 1
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"code-eval error: {exc}")
        return 2
    print("code-eval error: unknown command")
    return 2


def cmd_coding_bench(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        tasks = load_coding_bench_tasks(args.task_file) if args.task_file else builtin_coding_bench_tasks()
        if args.limit is not None:
            tasks = tasks[: max(args.limit, 0)]
        if args.coding_bench_command == "list":
            if args.json:
                print(json.dumps([task.to_dict() for task in tasks], ensure_ascii=False, indent=2, sort_keys=True))
            else:
                for task in tasks:
                    tags = ",".join(task.tags) if task.tags else "-"
                    print(f"- {task.id}: {task.instruction} [{tags}]")
            return 0
        if args.coding_bench_command == "run":
            repeats = max(getattr(args, "repeats", 1) or 1, 1)
            if repeats > 1:
                stability = run_coding_bench_stability(
                    config.project,
                    agent_command=getattr(args, "agent_command", ""),
                    agent=getattr(args, "agent", ""),
                    task_file=args.task_file or None,
                    limit=args.limit,
                    repeats=repeats,
                    keep_workspaces=args.keep_workspaces,
                )
                print(
                    render_coding_bench_stability_json(stability)
                    if args.json
                    else render_coding_bench_stability_markdown(stability),
                    end="" if not args.json else "\n",
                )
                summary = stability.summary()
                return 0 if summary["solved"] == summary["total_task_attempts"] and summary["total_task_attempts"] > 0 else 1
            run = run_coding_bench(
                config.project,
                agent_command=getattr(args, "agent_command", ""),
                agent=getattr(args, "agent", ""),
                task_file=args.task_file or None,
                limit=args.limit,
                keep_workspaces=args.keep_workspaces,
            )
            print(render_coding_bench_json(run) if args.json else render_coding_bench_markdown(run), end="" if not args.json else "\n")
            summary = run.summary()
            return 0 if summary["solved"] == summary["total"] and summary["total"] > 0 else 1
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"coding-bench error: {exc}")
        return 2
    print("coding-bench error: unknown command")
    return 2


def cmd_learning_effect(args: argparse.Namespace) -> int:
    if args.learning_effect_command != "run":
        print("learning-effect error: unknown command")
        return 2
    project_value, project_error = _resolve_learning_effect_project(args)
    if project_error:
        print(project_error)
        return 2
    task_file, task_file_error = _resolve_learning_effect_option_alias(
        getattr(args, "task_file", ""),
        getattr(args, "tasks_file", ""),
        "--task-file",
        "--tasks",
    )
    if task_file_error:
        print(task_file_error)
        return 2
    approved_command, approved_command_error = _resolve_learning_effect_option_alias(
        getattr(args, "approved_learning_command", ""),
        getattr(args, "agent_command_alias", ""),
        "--approved-learning-command",
        "--agent-command",
    )
    if approved_command_error:
        print(approved_command_error)
        return 2

    config = load_config(project_value)
    no_learning_command = (args.no_learning_command or "").strip()
    if not no_learning_command or not approved_command:
        print("learning-effect error: real --no-learning-command and --approved-learning-command are required")
        return 2

    try:
        if args.coding_bench or args.bench_task_file:
            tasks = _load_learning_effect_bench_tasks(args, task_file=task_file)
            learning_tasks = [LearningEffectTask(task.id, task.instruction, task.tags) for task in tasks.values()]

            def runner(task: LearningEffectTask, approved_learning: bool) -> LearningTaskResult:
                command = approved_command if approved_learning else no_learning_command
                bench_task = tasks[task.id]
                return _run_learning_effect_coding_bench_task(config.project, bench_task, command, approved_learning)

            report = run_learning_effect_regression(learning_tasks, runner)
        else:
            if not task_file:
                print("learning-effect error: --task-file is required unless --coding-bench or --bench-task-file is used")
                return 2
            tasks = load_learning_effect_tasks(task_file)

            def runner(task: LearningEffectTask, approved_learning: bool) -> LearningTaskResult:
                command = approved_command if approved_learning else no_learning_command
                return _run_learning_effect_command(config.project, task, command, approved_learning)

            report = run_learning_effect_regression(tasks, runner)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"learning-effect error: {exc}")
        return 2

    print(render_learning_effect_json(report) if args.json else _render_learning_effect_markdown(report), end="")
    return 0 if report.status == "pass" else 1


def _resolve_learning_effect_project(args: argparse.Namespace) -> tuple[str | None, str]:
    before_run = getattr(args, "project", None) or ""
    after_run = getattr(args, "learning_effect_project", "") or ""
    if before_run and after_run and _normalize_project_arg(before_run) != _normalize_project_arg(after_run):
        return None, "learning-effect error: conflicting --project values before and after run"
    return after_run or before_run or None, ""


def _normalize_project_arg(value: str) -> str:
    return str(Path(value).expanduser().resolve(strict=False))


def _resolve_learning_effect_option_alias(
    primary_value: str,
    alias_value: str,
    primary_flag: str,
    alias_flag: str,
) -> tuple[str, str]:
    primary = (primary_value or "").strip()
    alias = (alias_value or "").strip()
    if primary and alias and primary != alias:
        return "", f"learning-effect error: use only one of {primary_flag} or {alias_flag}"
    return primary or alias, ""


def _load_learning_effect_bench_tasks(args: argparse.Namespace, *, task_file: str = "") -> dict[str, CodingBenchTask]:
    bench_task_file = args.bench_task_file or task_file or ""
    tasks = load_coding_bench_tasks(bench_task_file) if bench_task_file else builtin_coding_bench_tasks()
    if args.limit is not None:
        tasks = tasks[: max(args.limit, 0)]
    return {task.id: task for task in tasks}


def _run_learning_effect_command(
    project: Path,
    task: LearningEffectTask,
    command_template: str,
    approved_learning: bool,
) -> LearningTaskResult:
    runner = create_learning_command_runner(
        no_learning_command=command_template,
        approved_learning_command=command_template,
        project=project,
        python=sys.executable,
    )
    return runner(task, approved_learning)


def _run_learning_effect_coding_bench_task(
    project: Path,
    task: CodingBenchTask,
    agent_command: str,
    approved_learning: bool,
) -> LearningTaskResult:
    mode = "approved" if approved_learning else "no_learning"
    with tempfile.TemporaryDirectory(prefix="mako learning effect ") as tmp:
        workspace = Path(tmp) / mode / task.id
        result = run_coding_bench_task(task, workspace, agent_command=agent_command)
    failure_class = result.failure_class or ("" if result.solved else result.status)
    evidence = (result.message or result.status,)
    return LearningTaskResult(task.id, result.solved, max(result.iterations, 1), failure_class, evidence)


def _parse_learning_effect_stdout(stdout: str) -> dict[str, Any] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _learning_effect_evidence(payload: dict[str, Any], proc: subprocess.CompletedProcess[str]) -> tuple[str, ...]:
    evidence = payload.get("evidence") or ()
    if isinstance(evidence, str):
        items = (evidence,)
    else:
        items = tuple(str(item) for item in evidence if str(item).strip())
    return items or (_preview_learning_effect_output(proc.stdout, proc.stderr),)


def _preview_learning_effect_output(stdout: str, stderr: str) -> str:
    text = (stdout.strip() or stderr.strip() or "command completed")[:300]
    return text.replace("\n", " ")


def _render_learning_effect_markdown(report: Any) -> str:
    lines = [
        "# Learning Effect",
        "",
        f"- status: {report.status}",
        f"- total: {report.total}",
        f"- solved_no_learning: {report.solved.get('no_learning', 0)}",
        f"- solved_approved_learning: {report.solved.get('approved_learning', 0)}",
        f"- score_delta: {report.score_delta}",
    ]
    if report.gap:
        lines.append(f"- gap: {report.gap}")
    lines.extend(["", "## Comparisons", ""])
    for comparison in report.comparisons:
        marker = "PASS" if comparison.approved_learning.solved else "FAIL"
        lines.append(
            f"- [{marker}] {comparison.task_id}: "
            f"no_learning={comparison.no_learning.solved}; "
            f"approved_learning={comparison.approved_learning.solved}; "
            f"score_delta={comparison.score_delta}"
        )
    return "\n".join(lines).rstrip() + "\n"


def cmd_swarm(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    task = (args.task_option or " ".join(args.task or [])).strip()
    if not task and not args.repair_plan:
        print("swarm error: task is required")
        return 2
    try:
        if args.repair_plan:
            plan_path = Path(args.repair_plan).expanduser()
            if not plan_path.is_absolute():
                plan_path = config.project / plan_path
            plan = load_patch_plan(plan_path)
            failure = args.failure or ""
            if args.failure_file:
                failure_path = Path(args.failure_file).expanduser()
                if not failure_path.is_absolute():
                    failure_path = config.project / failure_path
                failure = failure_path.read_text(encoding="utf-8", errors="replace")
            run = run_repair_swarm(
                config.project,
                plan,
                failure,
                workers=args.workers,
                max_rounds=args.max_rounds,
                model=args.model or "",
                base_url=args.base_url,
                timeout=args.timeout,
                agent_profile=args.agent_profile or "build",
            )
        else:
            run = run_swarm(
                config.project,
                task,
                workers=args.workers,
                worker_command=args.worker_command,
                test_command=args.test,
                timeout=args.timeout,
                sandbox_backend=args.sandbox_backend,
                network=args.network,
                allow_risky_worker=args.allow_risky_worker,
                allow_risky_test=args.allow_risky_test,
                agent_profile=args.agent_profile or "build",
                use_default_worker=not args.no_default_worker,
            )
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"swarm error: {exc}")
        return 2
    print(json.dumps(run.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_swarm_run(run), end="" if not args.json else "\n")
    return 0 if run.ok else 1


def cmd_arbitrate(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    decision = arbitrate_parent_reviews(project=config.project, review_ids=args.review_id or [], profile=args.agent_profile or "build")
    print(render_arbitration_decision(decision, format="json" if args.json else "markdown"), end="")
    return 0 if decision.apply_gate_ready else 1


def cmd_lsp(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.lsp_command == "status":
            statuses = detect_default_lsp_servers()
            if args.json:
                print(json.dumps([asdict(status) for status in statuses], ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print("# LSP Server Status\n")
                for status in statuses:
                    mark = "ok" if status.available else "missing"
                    print(f"- [{mark}] {status.name}: {' '.join(status.command)}")
                    if status.reason:
                        print(f"  reason: {status.reason}")
            return 0
        if args.lsp_command == "run":
            snapshot = run_lsp_diagnostics(config.project, args.path, timeout=args.timeout)
            print(render_lsp_json(snapshot) if args.json else render_lsp_markdown(snapshot))
            return 0 if not any(item.severity == 1 for item in snapshot.diagnostics) else 1
        if args.lsp_command == "cache":
            snapshot = load_lsp_snapshot(config.project)
            print(render_lsp_json(snapshot) if args.json else render_lsp_markdown(snapshot))
            return 0 if snapshot.status.available else 1
    except (OSError, ValueError, TimeoutError, RuntimeError, FileNotFoundError) as exc:
        print(f"lsp error: {exc}")
        return 2
    print("lsp error: unknown command")
    return 2


def cmd_embeddings(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        provider = _embedding_provider_from_args(args)
        if args.embeddings_command == "status":
            status = provider.status()
            print(render_embedding_status(status, fmt="json" if args.json else "markdown"), end="")
            return 0 if status.available else 1
        if args.embeddings_command == "embed":
            texts = list(args.text or [])
            for path in args.text_file or []:
                texts.append(Path(path).read_text(encoding="utf-8", errors="replace"))
            jobs = [EmbeddingJob(f"text-{index}", text, {"index": index}) for index, text in enumerate(texts)]
            batch = embed_batch(config.project, provider, jobs)
            print(render_embedding_status(batch, fmt="json" if args.json else "markdown"), end="")
            return 0 if not batch.unavailable else 1
        if args.embeddings_command == "cache-path":
            print(embedding_cache_path(config.project))
            return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"embeddings error: {exc}")
        return 2
    print("embeddings error: unknown command")
    return 2


def cmd_mcp_daemon(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.mcp_daemon_command == "start":
            state = start_mcp_daemon(config.project)
            print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else _render_external_mcp_daemon_state(state))
            return 0
        if args.mcp_daemon_command == "status":
            state = status_mcp_daemon(config.project)
            print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else _render_external_mcp_daemon_state(state))
            return 0 if state.status == "running" else 1
        if args.mcp_daemon_command == "stop":
            state = stop_mcp_daemon(config.project)
            print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else _render_external_mcp_daemon_state(state))
            return 0
        if args.mcp_daemon_command == "restart":
            state = restart_mcp_daemon(config.project)
            print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else _render_external_mcp_daemon_state(state))
            return 0
        if args.mcp_daemon_command == "recover":
            state = recover_mcp_daemon(config.project)
            print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else _render_external_mcp_daemon_state(state))
            return 0 if state.status in {"running", "stopped"} else 1
        if args.mcp_daemon_command == "catalog":
            payload = daemon_catalog(config.project, refresh=args.refresh)
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if not payload.get("errors") else 1
        if args.mcp_daemon_command == "call":
            arguments = json.loads(args.args_json or "{}")
            if not isinstance(arguments, dict):
                print("mcp-daemon error: --args-json must be an object")
                return 2
            payload = daemon_call(config.project, server=args.server, tool=args.tool, arguments=arguments, approval_id=args.approval_id or "", owner_approved=args.approve, profile=args.agent_profile or "")
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if payload.get("ok") else 1
        if args.mcp_daemon_command == "request":
            params = json.loads(args.params_json or "{}")
            if not isinstance(params, dict):
                print("mcp-daemon error: --params-json must be an object")
                return 2
            response = request_mcp_daemon(config.project, args.method, params, timeout=args.timeout)
            print(json.dumps(response.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if response.ok else 1
        if args.mcp_daemon_command == "serve":
            McpDaemon(config.project).serve_forever()
            return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"mcp-daemon error: {exc}")
        return 2
    print("mcp-daemon error: unknown command")
    return 2


def _render_external_mcp_daemon_state(state: Any) -> str:
    lines = [
        "# External MCP Daemon",
        "",
        f"- daemon_id: {state.daemon_id or '-'}",
        f"- status: {state.status}",
        f"- pid: {state.pid if state.pid is not None else '-'}",
        f"- socket_path: {state.socket_path}",
        f"- catalog_tools: {state.catalog_tools}",
        f"- call_records: {state.call_records}",
        f"- leases: {len(state.leases)}",
    ]
    if state.errors:
        lines.extend(["", "## Errors"])
        lines.extend(f"- {error}" for error in state.errors[:12])
    return "\n".join(lines) + "\n"


def _embedding_provider_from_args(args: argparse.Namespace) -> Any:
    provider = args.provider or "local"
    if provider == "local":
        return LocalHashEmbeddingProvider(model=args.model or "quantagent-local-hash-v1", dimensions=args.dimensions)
    if provider == "openai":
        return OpenAICompatibleEmbeddingProvider(model=args.model or "text-embedding-3-small", dimensions=args.dimensions or 1536)
    if provider in {"sentence-transformers", "sentence_transformers"}:
        return SentenceTransformersEmbeddingProvider(model=args.model or "sentence-transformers/all-MiniLM-L6-v2", dimensions=args.dimensions or 384)
    raise ValueError(f"unknown embedding provider: {provider}")


def cmd_checkpoint(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.checkpoint_command == "create":
            record = create_checkpoint(config.project, args.path, task_id=args.task_id or "", plan_id=args.plan_id or "", reason=args.reason or "")
            print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_checkpoints([record]))
            return 0
        if args.checkpoint_command == "list":
            records = list_checkpoints(config.project, limit=args.limit)
            print(json.dumps([record.to_dict() for record in records], ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_checkpoints(records))
            return 0
        if args.checkpoint_command == "show":
            record = load_checkpoint(config.project, args.checkpoint_id)
            print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_checkpoint_detail(record, include_text=args.include_text))
            return 0
        if args.checkpoint_command == "restore":
            record = restore_checkpoint(config.project, args.checkpoint_id)
            print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_checkpoints([record]))
            return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"checkpoint error: {exc}")
        return 2
    print("checkpoint error: unknown command")
    return 2


def cmd_transcript(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.transcript_command == "list":
            rows = list_tool_transcripts(config.project, limit=args.limit)
            print(json.dumps([row.to_dict() for row in rows], ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_tool_transcripts(rows))
            return 0
        if args.transcript_command == "show":
            row = load_tool_transcript(config.project, args.invocation_id)
            print(json.dumps(row.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_tool_transcript(row))
            return 0
    except KeyError as exc:
        print(f"transcript error: {exc}")
        return 2
    print("transcript error: unknown command")
    return 2


def cmd_agent_profile(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    profiles = load_agent_profile_config(config.project)
    try:
        if args.agent_profile_command == "list":
            print(json.dumps(profiles.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_agent_profiles(profiles))
            return 0
        if args.agent_profile_command == "show":
            profile = profiles.agents[args.name]
            print(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_agent_profile(profile))
            return 0
        if args.agent_profile_command == "check":
            args_payload = json.loads(args.args_json or "{}")
            if not isinstance(args_payload, dict):
                print("agent-profile error: --args-json must be an object")
                return 2
            decision = enforce_tool(args.name, args.tool, reason=args.reason or "", owner_approved=args.approve, project=config.project, args=args_payload)
            print(json.dumps(decision.metadata(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else f"{decision.action.upper()} {args.name}: {decision.summary}")
            return 0 if decision.allowed else 1
        if args.agent_profile_command == "instructions":
            instructions = load_instructions(config.project)
            if args.json:
                print(json.dumps([item.to_dict() for item in instructions], ensure_ascii=False, indent=2, sort_keys=True))
            elif args.show:
                print(render_instructions(instructions), end="")
                for item in instructions:
                    print(f"\n## {item.path}\n")
                    print(item.text)
            else:
                print(render_instructions(instructions))
            return 0
    except (KeyError, json.JSONDecodeError) as exc:
        print(f"agent-profile error: {exc}")
        return 2
    print("agent-profile error: unknown command")
    return 2


def cmd_modes(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.modes_command == "list":
            modes = list_agent_modes(config.project)
            print(json.dumps([mode.to_dict() for mode in modes], ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_agent_modes(modes), end="" if not args.json else "\n")
            return 0
        if args.modes_command == "show":
            mode = get_agent_mode(config.project, args.name)
            print(json.dumps(mode.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_agent_mode(mode), end="" if not args.json else "\n")
            return 0
        if args.modes_command == "evaluate":
            decision = resolve_agent_mode_permission(config.project, args.name, args.tool, owner_approved=args.approve)
            if decision is None:
                print(f"modes error: unknown mode {args.name}")
                return 2
            print(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_mode_decision(decision), end="" if not args.json else "\n")
            return 0 if decision.allowed else 1
        if args.modes_command == "tools":
            views = mode_tool_views(config.project, args.name)
            if args.json:
                print(json.dumps([view.to_dict() for view in views], ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(render_mode_tool_views(views, mode_name=args.name), end="")
            return 0
        if args.modes_command == "lint":
            diagnostics = validate_agent_modes(config.project)
            if args.json:
                print(json.dumps([item.to_dict() for item in diagnostics], ensure_ascii=False, indent=2, sort_keys=True))
            elif diagnostics:
                for item in diagnostics:
                    print(f"[{item.level}] {item.mode}: {item.message}")
            else:
                print("No agent mode issues.")
            return 1 if any(item.level == "error" for item in diagnostics) else 0
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"modes error: {exc}")
        return 2
    print("modes error: unknown command")
    return 2


def cmd_resume(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.resume_command == "last-failure":
            bundle = resume_last_failure(config.project)
        elif args.resume_command == "task":
            bundle = resume_task(config.project, args.task_id)
        elif args.resume_command == "agent":
            bundle = resume_agent(config.project, args.subagent_id or "")
        elif args.resume_command == "session":
            bundle = resume_session(config.project)
        elif args.resume_command == "compact":
            snapshot = create_resume_snapshot(
                config.project,
                args.kind,
                source_id=args.source_id or "",
                target_summary_chars=args.target_chars,
                auto=args.auto,
            )
            if args.json:
                print(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(render_resume_snapshot(snapshot, include_body=args.include_body), end="")
            return 0
        elif args.resume_command == "list":
            snapshots = list_resume_snapshots(config.project, limit=args.limit)
            if args.json:
                print(json.dumps([snapshot.to_dict() for snapshot in snapshots], ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(render_resume_snapshots(snapshots), end="")
            return 0
        elif args.resume_command == "show":
            snapshot = load_resume_snapshot(config.project, args.snapshot_id)
            if args.json:
                print(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(render_resume_snapshot(snapshot, include_body=args.include_body), end="")
            return 0
        else:
            print("resume error: unknown command")
            return 2
    except (KeyError, ValueError) as exc:
        print(f"resume error: {exc}")
        return 2
    if args.json:
        print(json.dumps(bundle.__dict__, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"# Resume {bundle.kind}\n\n- summary: {bundle.summary}\n- command: {bundle.command}\n\n{bundle.body}", end="")
    return 0


def cmd_isolation(args: argparse.Namespace) -> int:
    config = load_config(args.project)
    try:
        if args.isolation_command == "create":
            record = create_isolated_worktree(config.project, reason=args.reason or "", include=args.include or ())
            print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_isolated_worktree(record))
            return 0
        if args.isolation_command == "list":
            records = list_isolated_worktrees(config.project, limit=args.limit)
            print(json.dumps([record.to_dict() for record in records], ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_isolated_worktrees(records))
            return 0
        if args.isolation_command == "show":
            record = load_isolated_worktree(config.project, args.worktree_id)
            print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_isolated_worktree(record))
            return 0
        if args.isolation_command == "run":
            command = list(args.command)
            if command and command[0] == "--":
                command = command[1:]
            if not command:
                print("isolation error: command is empty")
                return 2
            result = run_in_isolated_worktree(
                config.project,
                command,
                worktree_id=args.worktree_id or "",
                timeout=args.timeout,
                allow_risky=args.allow_risky,
                reason=args.reason or "",
                sandbox_backend=args.sandbox_backend,
                network=args.network,
            )
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else result.stdout_preview or result.stderr_preview or result.reason)
            return 0 if result.ok else 1
        if args.isolation_command == "remove":
            record = remove_isolated_worktree(config.project, args.worktree_id)
            print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_isolated_worktree(record))
            return 0
        if args.isolation_command == "review":
            review = create_isolation_review(config.project, args.worktree_id)
            print(json.dumps(review.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_isolation_review(review, include_diff=args.diff))
            return 0
        if args.isolation_command == "show-review":
            review = load_isolation_review(config.project, args.review_id)
            print(json.dumps(review.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_isolation_review(review, include_diff=args.diff))
            return 0
        if args.isolation_command == "apply-review":
            review = apply_isolation_review(config.project, args.review_id, reviewed=args.reviewed)
            print(json.dumps(review.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_isolation_review(review, include_diff=False))
            return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"isolation error: {exc}")
        return 2
    print("isolation error: unknown command")
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PRIMARY_CLI,
        description=f"{PRODUCT_NAME} local evidence-first assistant. Run `{PRIMARY_CLI}` with no subcommand to open chat. `{LEGACY_CLI}` remains as a compatibility alias.",
    )
    parser.add_argument("--version", action="version", version=f"{PRIMARY_CLI} {__version__}")
    parser.add_argument("--trust-workspace", action="store_true", help="Trust this workspace and skip the startup prompt")
    parser.add_argument("--no-trust-prompt", action="store_true", help="Skip the startup workspace trust prompt")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_project(p: argparse.ArgumentParser) -> None:
        p.add_argument("--project", default=None, help="Quant project path")

    p = sub.add_parser("status")
    add_project(p)
    p.add_argument("--preview", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("watch")
    add_project(p)
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--hooks", action="store_true", help="Run one hook pass")
    p.add_argument("--force", action="store_true", help="Force hook actions")
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("agent-autopsy", help="Build a deterministic report for a failed agent run")
    add_project(p)
    p.add_argument("--trajectory", default=None, help="Trajectory JSONL produced by an agent run")
    p.add_argument("--query-events", default=None, help="Query events JSONL produced by an agent run")
    p.add_argument("--failure-file", default=None, help="Failure log to include in the autopsy")
    p.add_argument("--failure", default="", help="Inline failure text")
    p.add_argument("--source-agent", default="unknown", help="Agent or wrapper that produced the failing run")
    p.add_argument("--title", default="", help="Report title")
    p.add_argument("--command", dest="command_line", default="", help="Command wrapped by this autopsy run")
    p.add_argument("--limit", type=int, default=40, help="Maximum trace evidence items to keep in the report")
    p.add_argument("--timeout", type=int, default=600, help="Timeout in seconds for --run wrapper mode")
    p.add_argument("--output", default=None, help="Write markdown report to this path")
    p.add_argument("--json", action="store_true")
    p.add_argument("--run", dest="run_command", nargs=argparse.REMAINDER, help="Run and capture an agent command before building the autopsy")
    p.set_defaults(func=cmd_agent_autopsy)

    p = sub.add_parser("evidence-court", help="Render Evidence Court reports from supplied or demo agent-run evidence")
    evidence_court_sub = p.add_subparsers(dest="evidence_court_command", required=True)
    ap = evidence_court_sub.add_parser("audit", help="Audit a JSON agent-run record")
    ap.add_argument("--json", action="store_true", help="Print a machine-readable verdict envelope")
    ap.add_argument("--ci", action="store_true", help="Return exit code 1 when the verdict is FAIL")
    ap.add_argument("--fail-on", choices=("fail", "suspicious"), default="fail", help="CI failure threshold; default: fail")
    ap.add_argument("record", help="Path to a JSON record with claimed_task, files_read, files_edited, commands_run, test_output, and final_claim")
    ap.set_defaults(func=cmd_evidence_court)
    vp = evidence_court_sub.add_parser("validate", help="Validate that a supplied audit record is accepted by the current parser")
    vp.add_argument("--json", action="store_true", help="Print machine-readable acceptance status")
    vp.add_argument("record", help="Path to a JSON record to structurally validate")
    vp.set_defaults(func=cmd_evidence_court)
    rp = evidence_court_sub.add_parser("record", help="Build audit records from simple event inputs")
    record_sub = rp.add_subparsers(dest="record_command", required=True)
    rjp = record_sub.add_parser("from-jsonl", help="Convert simple JSONL events into an audit record JSON")
    rjp.add_argument("--output", default=None, help="Write the generated audit record JSON to this path")
    rjp.add_argument("events", help="Path to JSONL events with task/read/edit/command/final_claim kinds")
    rjp.set_defaults(func=cmd_evidence_court)
    rcp = record_sub.add_parser(
        "from-codex-transcript",
        help="Convert a supplied Codex-style transcript JSON into an audit record JSON",
    )
    rcp.add_argument("--output", default=None, help="Write the generated audit record JSON to this path")
    rcp.add_argument("transcript", help="Path to a supplied Codex-style transcript JSON")
    rcp.set_defaults(func=cmd_evidence_court)
    rlp = record_sub.add_parser(
        "from-claude-transcript",
        help="Convert a supplied Claude-style transcript JSON into an audit record JSON",
    )
    rlp.add_argument("--output", default=None, help="Write the generated audit record JSON to this path")
    rlp.add_argument("transcript", help="Path to a supplied Claude-style transcript JSON")
    rlp.set_defaults(func=cmd_evidence_court)
    rop = record_sub.add_parser(
        "from-openhands-transcript",
        help="Convert a supplied OpenHands-style transcript JSON into an audit record JSON",
    )
    rop.add_argument("--output", default=None, help="Write the generated audit record JSON to this path")
    rop.add_argument("transcript", help="Path to a supplied OpenHands-style transcript JSON")
    rop.set_defaults(func=cmd_evidence_court)
    rsp = record_sub.add_parser(
        "from-swe-agent-transcript",
        help="Convert a supplied SWE-agent-style transcript JSON into an audit record JSON",
    )
    rsp.add_argument("--output", default=None, help="Write the generated audit record JSON to this path")
    rsp.add_argument("transcript", help="Path to a supplied SWE-agent-style transcript JSON")
    rsp.set_defaults(func=cmd_evidence_court)
    ep = evidence_court_sub.add_parser("demo", help="Run built-in Evidence Court demos")
    ep.add_argument("--project", default=".", help="Repository root containing demo fixtures")
    demo_sub = ep.add_subparsers(dest="demo_command", required=True)
    dp = demo_sub.add_parser("bad-run", help="Show a failed coding-agent run with test evidence")
    dp.set_defaults(func=cmd_evidence_court)
    dp = demo_sub.add_parser("missing-tests", help="Show a success claim with no test evidence")
    dp.set_defaults(func=cmd_evidence_court)
    dp = demo_sub.add_parser("out-of-scope", help="Show an edit outside the claimed patch scope")
    dp.set_defaults(func=cmd_evidence_court)

    p = sub.add_parser("hooks")
    add_project(p)
    hooks_sub = p.add_subparsers(dest="hooks_command", required=True)
    hp = hooks_sub.add_parser("list")
    hp.add_argument("--profile", default="build", help="Agent profile whose hook config should be shown")
    hp.add_argument("--json", action="store_true")
    hp.set_defaults(func=cmd_hooks)
    hp = hooks_sub.add_parser("run")
    hp.add_argument("event", help="Hook event name, e.g. PreToolUse or before_tool_call")
    hp.add_argument("--profile", default="build", help="Agent profile whose hook config should be used")
    hp.add_argument("--payload-json", default="{}")
    hp.add_argument("--command", default=None, help="Ad-hoc shell hook command to run in addition to configured hooks")
    hp.add_argument("--matcher", default=None)
    hp.add_argument("--timeout-ms", type=int, default=None)
    hp.add_argument("--priority", type=int, default=0)
    hp.add_argument("--fail-closed", action="store_true")
    hp.add_argument("--json", action="store_true")
    hp.set_defaults(func=cmd_hooks)

    p = sub.add_parser("rules")
    add_project(p)
    p.add_argument("--path", action="append", help="Only show rules matching this project-relative path")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_rules)

    p = sub.add_parser("audit")
    add_project(p)
    p.add_argument("--deep", action="store_true", help="Run QuantAuditor checks")
    p.add_argument("--target", default=None, help="Audit one CSV or JSON result")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("quant")
    add_project(p)
    quant_sub = p.add_subparsers(dest="quant_command", required=True)
    qp = quant_sub.add_parser("check")
    qp.add_argument("task", nargs="?", default="", help="Quant task or conclusion to gate")
    qp.add_argument("--answer", default="", help="Draft answer/conclusion to gate")
    qp.add_argument("--answer-file", default="", help="Read draft answer/conclusion from a file")
    qp.add_argument("--no-audit", action="store_true", help="Skip local project audit findings in this check")
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_quant)
    qp = quant_sub.add_parser("data-contract")
    qp.add_argument("path", help="CSV path to validate before backtesting")
    qp.add_argument("--kind", default="auto", choices=["auto", "trade_csv", "return_series", "generic_csv"])
    qp.add_argument("--strict-dedup", action="store_true", help="Treat non-dedup-marked trade CSV names as blocking errors")
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_quant)
    qp = quant_sub.add_parser("data-adapter")
    qp.add_argument("root", nargs="*", help="Local data root(s) to inspect; defaults to project plus known Desktop/Downloads quant roots")
    qp.add_argument("--max-files", type=int, default=5000)
    qp.add_argument("--sample-zip-members", type=int, default=20)
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_quant)
    qp = quant_sub.add_parser("expectations")
    qp.add_argument("path", help="CSV path to validate with expectation-suite checks")
    qp.add_argument(
        "--kind",
        default="auto",
        choices=[
            "auto",
            "generic_csv",
            "trade_csv",
            "return_series",
            "market_bar_csv",
            "minute_bar_csv",
            "tick_trade_csv",
            "fill_csv",
            "broker_csv",
            "slippage_csv",
            "capacity_csv",
            "position_csv",
        ],
    )
    qp.add_argument("--sample-rows", type=int, default=5000)
    qp.add_argument("--hash-bytes", type=int, default=16 * 1024 * 1024, help="Bytes to hash from file head; use 0 to skip")
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_quant)
    qp = quant_sub.add_parser("data-sample")
    qp.add_argument("root", help="Local quant data root or archive file")
    qp.add_argument("--code", required=True, help="Stock code such as 000001 or sh600000")
    qp.add_argument("--kind", default="auto", choices=["auto", "market_bar", "minute_bar", "tick_trade"])
    qp.add_argument("--freq", default="1m", help="Minute frequency: 1m/5m/15m/30m/60m")
    qp.add_argument("--adjust", default="前复权", help="Daily archive adjustment preference: 前复权/后复权/不复权")
    qp.add_argument("--date", default="", help="Single trading date YYYY-MM-DD, required for tick 7z")
    qp.add_argument("--start", default="", help="Start date YYYY-MM-DD")
    qp.add_argument("--end", default="", help="End date YYYY-MM-DD")
    qp.add_argument("--max-rows", type=int, default=1000)
    qp.add_argument("--output", default="", help="Output CSV path; defaults to .quantagent/data_samples")
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_quant)
    qp = quant_sub.add_parser("auto-evidence")
    qp.add_argument("task", nargs="?", default="", help="Quant task, e.g. 这个策略咋样")
    qp.add_argument("--input", default="", help="Explicit strategy/position/backtest CSV to judge")
    qp.add_argument("--strategy-root", action="append", help="Additional root to search for strategy output CSVs")
    qp.add_argument("--data-root", action="append", help="Additional local quant data root or archive to inspect/sample")
    qp.add_argument("--code", default="", help="Override sampled stock code such as 000001")
    qp.add_argument("--date", default="", help="Override sampled trading date YYYY-MM-DD")
    qp.add_argument("--execution-source", default="", help="Human-readable execution provenance; defaults to local file evidence when found")
    qp.add_argument("--max-files", type=int, default=5000)
    qp.add_argument("--sample-zip-members", type=int, default=20)
    qp.add_argument("--max-rows", type=int, default=1000)
    qp.add_argument("--no-strict-dedup", action="store_true", help="Do not require dedup/check_dedup naming on trade inputs")
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_quant)
    qp = quant_sub.add_parser("execution-gate")
    qp.add_argument("--tick", default="", help="Tick/逐笔 evidence file")
    qp.add_argument("--fill", default="", help="Fill/成交 evidence file")
    qp.add_argument("--broker", default="", help="Broker/account provenance evidence file")
    qp.add_argument("--order", default="", help="Order lifecycle evidence file")
    qp.add_argument("--position", default="", help="Position reconciliation evidence file")
    qp.add_argument("--account", default="", help="Account snapshot evidence file")
    qp.add_argument("--slippage", default="", help="Slippage evidence file")
    qp.add_argument("--capacity", default="", help="Capacity/liquidity evidence file")
    qp.add_argument("--execution-source", default="", help="Human-readable broker/data provenance")
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_quant)
    qp = quant_sub.add_parser("broker-gateway")
    qp.add_argument("--broker", default="", help="Broker/account provenance CSV/JSON")
    qp.add_argument("--fill", default="", help="Broker fill/trade CSV/JSON")
    qp.add_argument("--order", default="", help="Broker order CSV/JSON")
    qp.add_argument("--position", default="", help="Broker position CSV/JSON")
    qp.add_argument("--account", default="", help="Broker account CSV/JSON")
    qp.add_argument("--source", default="", help="Human-readable broker export provenance")
    qp.add_argument("--gateway", default="", help="Gateway/broker name if not present in the file")
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_quant)
    qp = quant_sub.add_parser("broker-import")
    qp.add_argument("path", nargs="+", help="Broker export file or directory: 成交记录/委托记录/资金持仓/交割单 CSV/TXT/HTML-XLS")
    qp.add_argument("--source", default="", help="Human-readable export provenance, e.g. 华泰证券PC客户端 2026-05-25")
    qp.add_argument("--broker-name", default="", help="Broker name if the export does not include one")
    qp.add_argument("--output-dir", default="", help="Output directory; defaults to .quantagent/broker_evidence/<import_id>")
    qp.add_argument("--max-files", type=int, default=200)
    qp.add_argument("--max-rows", type=int, default=5000)
    qp.add_argument("--no-redact", action="store_true", help="Keep account IDs instead of hashing them")
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_quant)
    qp = quant_sub.add_parser("leak-check")
    qp.add_argument("path", help="CSV/Python file or project directory to scan for leakage patterns")
    qp.add_argument("--max-files", type=int, default=500)
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_quant)
    qp = quant_sub.add_parser("bench")
    qp.add_argument("--keep-workspace", action="store_true", help="Preserve generated benchmark fixtures under the project quant_bench directory")
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_quant)
    qp = quant_sub.add_parser("run")
    qp.add_argument("input", help="Deduplicated trade CSV or return series to gate before quant conclusions")
    qp.add_argument("--name", default="")
    qp.add_argument("--return-col", default="net_return")
    qp.add_argument("--date-col", default="entry_date")
    qp.add_argument("--threshold-col", default="")
    qp.add_argument("--threshold", type=float, default=None)
    qp.add_argument("--kind", default="trade_csv", choices=["auto", "trade_csv", "return_series", "generic_csv"])
    qp.add_argument("--no-strict-dedup", action="store_true", help="Do not require dedup/check_dedup naming on trade inputs")
    qp.add_argument("--oos-start", default="")
    qp.add_argument("--oos-end", default="")
    qp.add_argument("--fees-bps", type=float, default=0.0)
    qp.add_argument("--slippage-bps", type=float, default=0.0)
    qp.add_argument("--capacity-notes", default="")
    qp.add_argument("--execution-source", default="", help="Broker/fill/tick evidence source; required before live_ready can be true")
    qp.add_argument("--tick", default="", help="Tick/逐笔 evidence file for live_ready")
    qp.add_argument("--fill", default="", help="Fill/成交 evidence file for live_ready")
    qp.add_argument("--broker", default="", help="Broker/account evidence file for live_ready")
    qp.add_argument("--order", default="", help="Order lifecycle evidence file for live_ready")
    qp.add_argument("--position", default="", help="Position reconciliation evidence file for live_ready")
    qp.add_argument("--account", default="", help="Account snapshot evidence file for live_ready")
    qp.add_argument("--slippage", default="", help="Slippage evidence file for live_ready")
    qp.add_argument("--capacity", default="", help="Capacity evidence file for live_ready")
    qp.add_argument("--assumption", action="append", help="Explicit modeling assumption recorded in the evidence bundle")
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_quant)
    qp = quant_sub.add_parser("evidence")
    qp.add_argument("--gate-id", default="", help="Show one gate run instead of the latest")
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_quant)
    qp = quant_sub.add_parser("live-status")
    qp.add_argument("--gate-id", default="", help="Show live evidence status for one gate run instead of the latest")
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_quant)
    qp = quant_sub.add_parser("verdict")
    qp.add_argument("--gate-id", default="", help="Evaluate one gate run instead of the latest")
    qp.add_argument("--task", default="", help="Optional task text to check against this gate")
    qp.add_argument("--answer", default="", help="Optional answer/conclusion text to check against this gate")
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_quant)
    qp = quant_sub.add_parser("replay")
    qp.add_argument("--gate-id", default="", help="Replay one gate run instead of the latest")
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_quant)

    p = sub.add_parser("judge", help="One-command quant strategy verdict with evidence lock")
    add_project(p)
    p.add_argument("target", nargs="?", default="", help="Optional scenario A/D or explicit strategy CSV path")
    p.add_argument("--scenario", default="A", choices=["A", "D"])
    p.add_argument("--input", default="", help="Explicit strategy/position/backtest CSV to judge")
    p.add_argument("--name", default="")
    p.add_argument("--return-col", default="net_return")
    p.add_argument("--date-col", default="entry_date")
    p.add_argument("--threshold-col", default="t1_auction_return")
    p.add_argument("--threshold", type=float, default=None)
    p.add_argument("--kind", default="trade_csv", choices=["auto", "trade_csv", "return_series", "generic_csv"])
    p.add_argument("--no-strict-dedup", action="store_true", help="Do not require dedup/check_dedup naming on trade inputs")
    p.add_argument("--oos-start", default="")
    p.add_argument("--oos-end", default="")
    p.add_argument("--fees-bps", type=float, default=0.0)
    p.add_argument("--slippage-bps", type=float, default=0.0)
    p.add_argument("--capacity-notes", default="")
    p.add_argument("--execution-source", default="", help="Broker/fill/tick evidence source; required before live_ready can be true")
    p.add_argument("--tick", default="", help="Tick/逐笔 evidence file for live_ready")
    p.add_argument("--fill", default="", help="Fill/成交 evidence file for live_ready")
    p.add_argument("--broker", default="", help="Broker/account evidence file for live_ready")
    p.add_argument("--order", default="", help="Order lifecycle evidence file for live_ready")
    p.add_argument("--position", default="", help="Position reconciliation evidence file for live_ready")
    p.add_argument("--account", default="", help="Account snapshot evidence file for live_ready")
    p.add_argument("--slippage", default="", help="Slippage evidence file for live_ready")
    p.add_argument("--capacity", default="", help="Capacity evidence file for live_ready")
    p.add_argument("--assumption", action="append", help="Explicit modeling assumption recorded in the evidence bundle")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_judge)

    p = sub.add_parser("report")
    add_project(p)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("context")
    add_project(p)
    p.add_argument("--write", action="store_true")
    p.add_argument("--task", default=None, help="Task text used to rank context relevance")
    p.add_argument("--ref", action="append", help="Named context provider reference such as @diff, @file:path, @repo-map, @problems")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_context)

    p = sub.add_parser("cheap", help="Preview the free-first path before any model call")
    add_project(p)
    p.add_argument("--json", action="store_true", help="Render machine-readable cheap plan")
    p.add_argument("task", nargs="*", help="Optional task text used to estimate context mode and free-first commands")
    p.set_defaults(func=cmd_cheap)

    p = sub.add_parser("architect")
    add_project(p)
    architect_sub = p.add_subparsers(dest="architect_command", required=True)
    ap = architect_sub.add_parser("plan")
    ap.add_argument("task")
    ap.add_argument("--path", action="append")
    ap.add_argument("--ref", action="append")
    ap.add_argument("--test", nargs=argparse.REMAINDER)
    ap.add_argument("--context", action="store_true", help="Render referenced context providers with the plan")
    ap.add_argument("--json", action="store_true")
    ap.set_defaults(func=cmd_architect)
    ap = architect_sub.add_parser("list")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--json", action="store_true")
    ap.set_defaults(func=cmd_architect)
    ap = architect_sub.add_parser("show")
    ap.add_argument("plan_id")
    ap.add_argument("--context", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.set_defaults(func=cmd_architect)

    p = sub.add_parser("pr")
    add_project(p)
    pr_sub = p.add_subparsers(dest="pr_command", required=True)
    pp = pr_sub.add_parser("plan")
    pp.add_argument("task")
    pp.add_argument("--title", default=None)
    pp.add_argument("--base-branch", default=None)
    pp.add_argument("--branch", default=None)
    pp.add_argument("--test", nargs=argparse.REMAINDER)
    pp.add_argument("--json", action="store_true")
    pp.set_defaults(func=cmd_pr)
    pp = pr_sub.add_parser("list")
    pp.add_argument("--limit", type=int, default=20)
    pp.add_argument("--json", action="store_true")
    pp.set_defaults(func=cmd_pr)
    pp = pr_sub.add_parser("show")
    pp.add_argument("pr_id")
    pp.add_argument("--json", action="store_true")
    pp.set_defaults(func=cmd_pr)

    p = sub.add_parser("runner")
    add_project(p)
    runner_sub = p.add_subparsers(dest="runner_command", required=True)
    rp = runner_sub.add_parser("plan")
    rp.add_argument("task")
    rp.add_argument("--setup", nargs="+", action="append")
    rp.add_argument("--run", nargs="+", action="append")
    rp.add_argument("--allow-network", action="append")
    rp.add_argument("--secret", action="append")
    rp.add_argument("--timeout-minutes", type=int, default=30)
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_runner)
    rp = runner_sub.add_parser("list")
    rp.add_argument("--limit", type=int, default=20)
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_runner)
    rp = runner_sub.add_parser("show")
    rp.add_argument("runner_id")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_runner)

    p = sub.add_parser("query-events")
    add_project(p)
    p.add_argument("--limit", type=int, default=12)
    p.set_defaults(func=cmd_query_events)

    p = sub.add_parser("ux")
    add_project(p)
    ux_sub = p.add_subparsers(dest="ux_command", required=True)
    up = ux_sub.add_parser("status")
    up.add_argument("--task", default=None, help="Task text used to show context mode and budget")
    up.add_argument("--limit", type=int, default=5)
    up.add_argument("--no-context-pack", action="store_true", help="Skip building the context pack estimate")
    up.add_argument("--json", action="store_true")
    up.set_defaults(func=cmd_ux)

    p = sub.add_parser("tui-model")
    add_project(p)
    p.add_argument("--json", action="store_true")
    p.add_argument("--mode", default="")
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--context-pack", action="store_true", help="Include full UX context pack estimate")
    p.add_argument("task", nargs="?", default="status")
    p.set_defaults(func=cmd_tui_model)

    p = sub.add_parser("tools")
    p.set_defaults(func=cmd_tools)

    p = sub.add_parser("event-log")
    add_project(p)
    event_log_sub = p.add_subparsers(dest="event_log_command", required=True)
    ep = event_log_sub.add_parser("append")
    ep.add_argument("kind")
    ep.add_argument("summary")
    ep.add_argument("--status", default="observed")
    ep.add_argument("--session-id", default="")
    ep.add_argument("--task-id", default="")
    ep.add_argument("--correlation-id", default="")
    ep.add_argument("--tool", default="")
    ep.add_argument("--data", default="{}")
    ep.add_argument("--artifact", action="append")
    ep.set_defaults(func=cmd_event_log)
    ep = event_log_sub.add_parser("list")
    ep.add_argument("--kind")
    ep.add_argument("--status")
    ep.add_argument("--session-id")
    ep.add_argument("--task-id")
    ep.add_argument("--correlation-id")
    ep.add_argument("--limit", type=int, default=40)
    ep.add_argument("--json", action="store_true")
    ep.set_defaults(func=cmd_event_log)
    ep = event_log_sub.add_parser("stats")
    ep.add_argument("--kind")
    ep.add_argument("--status")
    ep.add_argument("--limit", type=int, default=1000)
    ep.add_argument("--json", action="store_true")
    ep.set_defaults(func=cmd_event_log)
    ep = event_log_sub.add_parser("replay")
    ep.add_argument("--limit", type=int, default=20)
    ep.set_defaults(func=cmd_event_log)
    ep = event_log_sub.add_parser("export")
    ep.add_argument("--format", default="json", choices=["json", "jsonl", "markdown"])
    ep.add_argument("--limit", type=int, default=1000)
    ep.set_defaults(func=cmd_event_log)

    p = sub.add_parser("tool-manifest")
    add_project(p)
    manifest_sub = p.add_subparsers(dest="tool_manifest_command", required=True)
    mp = manifest_sub.add_parser("list")
    mp.add_argument("--json", action="store_true")
    mp.set_defaults(func=cmd_tool_manifest)
    mp = manifest_sub.add_parser("show")
    mp.add_argument("name")
    mp.set_defaults(func=cmd_tool_manifest)
    mp = manifest_sub.add_parser("lint")
    mp.add_argument("--json", action="store_true")
    mp.set_defaults(func=cmd_tool_manifest)
    mp = manifest_sub.add_parser("export")
    mp.set_defaults(func=cmd_tool_manifest)

    p = sub.add_parser("policy-v2")
    add_project(p)
    policy_sub = p.add_subparsers(dest="policy_v2_command", required=True)
    pp = policy_sub.add_parser("init")
    pp.set_defaults(func=cmd_policy_v2)
    pp = policy_sub.add_parser("show")
    pp.set_defaults(func=cmd_policy_v2)
    pp = policy_sub.add_parser("lint")
    pp.add_argument("--json", action="store_true")
    pp.set_defaults(func=cmd_policy_v2)
    pp = policy_sub.add_parser("evaluate")
    pp.add_argument("tool")
    pp.add_argument("--args-json", default="{}")
    pp.add_argument("--json", action="store_true")
    pp.set_defaults(func=cmd_policy_v2)
    pp = policy_sub.add_parser("add-rule")
    pp.add_argument("--action", required=True, choices=["allow", "ask", "deny"])
    pp.add_argument("--tool", default="*")
    pp.add_argument("--arg-contains", action="append", help="Only match when serialized tool args contain this fragment")
    pp.add_argument("--risk", default="")
    pp.add_argument("--priority", type=int, default=50)
    pp.add_argument("--reason", default="")
    pp.add_argument("--allow-always", action="store_true")
    pp.add_argument("--rule-id", default="")
    pp.add_argument("--json", action="store_true")
    pp.set_defaults(func=cmd_policy_v2)

    p = sub.add_parser("channel", help="Pair channel senders and route channel messages into the runtime queue")
    add_project(p)
    channel_sub = p.add_subparsers(dest="channel_command", required=True)
    cp = channel_sub.add_parser("pair-code")
    cp.add_argument("--owner-key", required=True)
    cp.add_argument("--channel", default="")
    cp.add_argument("--agent-id", default="main", help="Agent id initially bound to this paired sender")
    cp.add_argument("--ttl-seconds", type=float, default=600.0)
    cp.add_argument("--json", action="store_true")
    cp.set_defaults(func=cmd_channel)
    cp = channel_sub.add_parser("pair")
    cp.add_argument("--channel", required=True)
    cp.add_argument("--sender", required=True)
    cp.add_argument("--code", required=True)
    cp.add_argument("--json", action="store_true")
    cp.set_defaults(func=cmd_channel)
    cp = channel_sub.add_parser("resolve")
    cp.add_argument("--channel", required=True)
    cp.add_argument("--sender", required=True)
    cp.add_argument("--json", action="store_true")
    cp.set_defaults(func=cmd_channel)
    cp = channel_sub.add_parser("bind-agent")
    cp.add_argument("--channel", required=True)
    cp.add_argument("--sender", required=True)
    cp.add_argument("--agent-id", required=True)
    cp.add_argument("--json", action="store_true")
    cp.set_defaults(func=cmd_channel)
    cp = channel_sub.add_parser("bindings")
    cp.add_argument("--json", action="store_true")
    cp.set_defaults(func=cmd_channel)
    cp = channel_sub.add_parser("send")
    cp.add_argument("--channel", required=True)
    cp.add_argument("--sender", required=True)
    cp.add_argument("--queue", default="channel_gateway")
    cp.add_argument("--policy-json", default="")
    cp.add_argument("--json", action="store_true")
    cp.add_argument("text")
    cp.set_defaults(func=cmd_channel)
    cp = channel_sub.add_parser("events")
    cp.add_argument("--limit", type=int, default=100)
    cp.add_argument("--json", action="store_true")
    cp.set_defaults(func=cmd_channel)

    p = sub.add_parser("agent-gateway", help="Inspect the local agent gateway control plane")
    add_project(p)
    gateway_sub = p.add_subparsers(dest="agent_gateway_command", required=True)
    gp = gateway_sub.add_parser("status")
    gp.add_argument("--event-limit", type=int, default=50)
    gp.add_argument("--queue-limit", type=int, default=50)
    gp.add_argument("--skill-limit", type=int, default=50)
    gp.add_argument("--json", action="store_true")
    gp.set_defaults(func=cmd_agent_gateway)
    gp = gateway_sub.add_parser("dashboard")
    gp.add_argument("--event-limit", type=int, default=50)
    gp.add_argument("--queue-limit", type=int, default=50)
    gp.add_argument("--skill-limit", type=int, default=50)
    gp.add_argument("--html-out", default="")
    gp.add_argument("--json", action="store_true")
    gp.set_defaults(func=cmd_agent_gateway)

    p = sub.add_parser("relay", help="Structured agent handoff and local Agent Bus")
    add_project(p)
    relay_sub = p.add_subparsers(dest="relay_command", required=True)
    rp = relay_sub.add_parser("card")
    rp.add_argument("goal")
    rp.add_argument("--task-id", default="")
    rp.add_argument("--allowed", action="append", default=[])
    rp.add_argument("--forbidden", action="append", default=[])
    rp.add_argument("--success", action="append", default=[])
    rp.add_argument("--risk-level", default="medium")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_relay)
    rp = relay_sub.add_parser("send")
    rp.add_argument("--to", required=True)
    rp.add_argument("--type", required=True)
    rp.add_argument("--task", required=True)
    rp.add_argument("--input", required=True)
    rp.add_argument("--from-agent", default="user")
    rp.add_argument("--message-id", default="")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_relay)
    rp = relay_sub.add_parser("inbox")
    rp.add_argument("--agent", required=True)
    rp.add_argument("--as-agent", default="")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_relay)
    rp = relay_sub.add_parser("poll")
    rp.add_argument("--agent", required=True)
    rp.add_argument("--as-agent", default="")
    rp.add_argument("--lease-seconds", type=float, default=300.0)
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_relay)
    rp = relay_sub.add_parser("watch")
    rp.add_argument("--agent", required=True)
    rp.add_argument("--as-agent", default="")
    rp.add_argument("--interval", type=float, default=2.0)
    rp.add_argument("--max-iterations", type=int, default=None)
    rp.add_argument("--lease-seconds", type=float, default=300.0)
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_relay)
    rp = relay_sub.add_parser("done")
    rp.add_argument("--agent", required=True)
    rp.add_argument("--message", required=True)
    rp.add_argument("--lease", default="")
    rp.add_argument("--output", required=True)
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_relay)
    rp = relay_sub.add_parser("fail")
    rp.add_argument("--agent", required=True)
    rp.add_argument("--message", required=True)
    rp.add_argument("--lease", default="")
    rp.add_argument("--output", required=True)
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_relay)
    rp = relay_sub.add_parser("reclaim")
    rp.add_argument("--agent", required=True)
    rp.add_argument("--lease-seconds", type=float, default=300.0)
    rp.add_argument("--stale-seconds", type=float, default=60.0)
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_relay)
    rp = relay_sub.add_parser("status")
    rp.add_argument("--task", required=True)
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_relay)
    rp = relay_sub.add_parser("demo")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_relay)
    rp = relay_sub.add_parser("stress")
    rp.add_argument("--agents", action="append", required=True)
    rp.add_argument("--workers", type=int, default=5)
    rp.add_argument("--messages", type=int, default=100)
    rp.add_argument("--lease-seconds", type=float, default=60.0)
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_relay)
    rp = relay_sub.add_parser("heartbeat")
    rp.add_argument("--agent", required=True)
    rp.add_argument("--status", default="idle")
    rp.add_argument("--task", default="")
    rp.add_argument("--stale-after", type=float, default=None)
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_relay)
    rp = relay_sub.add_parser("events")
    rp.add_argument("--task", default="")
    rp.add_argument("--message", default="")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_relay)

    p = sub.add_parser("task-graph")
    add_project(p)
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_task_graph)

    p = sub.add_parser("runtime")
    add_project(p)
    runtime_sub = p.add_subparsers(dest="runtime_command", required=True)
    rp = runtime_sub.add_parser("status")
    rp.add_argument("--limit", type=int, default=20)
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_runtime)
    rp = runtime_sub.add_parser("export")
    rp.add_argument("--limit", type=int, default=100)
    rp.set_defaults(func=cmd_runtime)
    rp = runtime_sub.add_parser("search")
    rp.add_argument("query")
    rp.add_argument("--limit", type=int, default=20)
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_runtime)
    rp = runtime_sub.add_parser("agent")
    rp.add_argument("--task", default="")
    rp.add_argument("--query-events", default="")
    rp.add_argument("--trajectory", default="")
    rp.add_argument("--desktop-state", default="")
    rp.add_argument("--eval-json", default="")
    rp.add_argument("--soak-json", default="")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_runtime)
    rp = runtime_sub.add_parser("queue")
    queue_sub = rp.add_subparsers(dest="runtime_queue_command", required=True)
    qp = queue_sub.add_parser("list")
    qp.add_argument("--queue", default="default")
    qp.add_argument("--status", action="append")
    qp.add_argument("--limit", type=int, default=50)
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_runtime)
    qp = queue_sub.add_parser("enqueue")
    qp.add_argument("task")
    qp.add_argument("--item-id", default="")
    qp.add_argument("--queue", default="default")
    qp.add_argument("--task-kind", default="manual")
    qp.add_argument("--priority", type=int, default=50)
    qp.add_argument("--max-attempts", type=int, default=3)
    qp.add_argument("--metadata-json", default="")
    qp.add_argument("--stop-file", default="")
    qp.add_argument("--session-lock-key", default="")
    qp.add_argument("--resume-of", default="")
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_runtime)
    qp = queue_sub.add_parser("claim")
    qp.add_argument("--queue", default="default")
    qp.add_argument("--worker-id", required=True)
    qp.add_argument("--lease-seconds", type=float, default=300.0)
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_runtime)
    qp = queue_sub.add_parser("heartbeat")
    qp.add_argument("task_id")
    qp.add_argument("--worker-id", required=True)
    qp.add_argument("--lease-seconds", type=float, default=300.0)
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_runtime)
    qp = queue_sub.add_parser("stop")
    qp.add_argument("task_id")
    qp.add_argument("--worker-id", default="")
    qp.add_argument("--reason", default="")
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_runtime)
    qp = queue_sub.add_parser("resume")
    qp.add_argument("task_id")
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_runtime)

    p = sub.add_parser("skill-pipeline")
    add_project(p)
    skill_pipeline_sub = p.add_subparsers(dest="skill_pipeline_command", required=True)
    sp = skill_pipeline_sub.add_parser("propose-trajectory")
    sp.add_argument("trajectory")
    sp.add_argument("--name")
    sp.add_argument("--description")
    sp.add_argument("--trigger", action="append")
    sp.set_defaults(func=cmd_skill_pipeline)
    sp = skill_pipeline_sub.add_parser("propose-events")
    sp.add_argument("--name", required=True)
    sp.add_argument("--description", required=True)
    sp.add_argument("--trigger", action="append")
    sp.add_argument("--limit", type=int, default=80)
    sp.set_defaults(func=cmd_skill_pipeline)
    sp = skill_pipeline_sub.add_parser("propose-subject-repair")
    sp.add_argument("--name", default="")
    sp.add_argument("--description", default="")
    sp.add_argument("--trigger", action="append")
    sp.add_argument("--function", required=True)
    sp.add_argument("--source-file", required=True)
    sp.add_argument("--evidence", action="append")
    sp.set_defaults(func=cmd_skill_pipeline)
    sp = skill_pipeline_sub.add_parser("propose-subject-repair-from-trajectory")
    sp.add_argument("trajectory")
    sp.add_argument("--workspace", default="")
    sp.add_argument("--name", default="")
    sp.add_argument("--description", default="")
    sp.add_argument("--trigger", action="append")
    sp.set_defaults(func=cmd_skill_pipeline)
    sp = skill_pipeline_sub.add_parser("propose-file-bundle-repair-from-trajectory")
    sp.add_argument("trajectory")
    sp.add_argument("--workspace", default="")
    sp.add_argument("--name", default="")
    sp.add_argument("--description", default="")
    sp.add_argument("--trigger", action="append")
    sp.set_defaults(func=cmd_skill_pipeline)
    sp = skill_pipeline_sub.add_parser("list")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_skill_pipeline)
    sp = skill_pipeline_sub.add_parser("show")
    sp.add_argument("proposal_id")
    sp.set_defaults(func=cmd_skill_pipeline)
    sp = skill_pipeline_sub.add_parser("curate")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_skill_pipeline)
    sp = skill_pipeline_sub.add_parser("approve")
    sp.add_argument("proposal_id")
    sp.add_argument("--force", action="store_true")
    sp.add_argument("--eval-command", default="")
    sp.add_argument("--eval-summary", default="")
    sp.add_argument("--eval-evidence", action="append")
    sp.add_argument("--require-learning-effect", nargs="?", const=True, default=False)
    sp.add_argument("--learning-effect-report", default="")
    sp.add_argument("--learning-effect-command", default="")
    sp.set_defaults(func=cmd_skill_pipeline)
    sp = skill_pipeline_sub.add_parser("reject")
    sp.add_argument("proposal_id")
    sp.add_argument("--reason", default="")
    sp.set_defaults(func=cmd_skill_pipeline)
    sp = skill_pipeline_sub.add_parser("rollback")
    sp.add_argument("proposal_id")
    sp.add_argument("--reason", default="")
    sp.set_defaults(func=cmd_skill_pipeline)

    p = sub.add_parser("skills")
    add_project(p)
    p.add_argument("--match", default=None, help="Show skills selected for a task")
    p.add_argument("--show", action="store_true", help="Show full skill instructions")
    p.add_argument("--install", default=None, help="Install a local SKILL.md or directory into .quantagent/skills")
    p.add_argument("--name", default=None, help="Override installed skill directory name")
    p.add_argument("--force", action="store_true", help="Replace an installed skill with the same name")
    p.add_argument("--json", action="store_true", help="Emit skill registry records as JSON")
    p.set_defaults(func=cmd_skills)

    p = sub.add_parser("safety")
    add_project(p)
    p.add_argument("--check-command", default=None, help="Classify a shell command before running it")
    p.add_argument("--check-claim", default=None, help="Classify a quant conclusion before publishing it")
    p.set_defaults(func=cmd_safety)

    p = sub.add_parser("validate")
    add_project(p)
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("checks")
    add_project(p)
    checks_sub = p.add_subparsers(dest="checks_command", required=True)
    cp = checks_sub.add_parser("list")
    cp.add_argument("--json", action="store_true")
    cp.set_defaults(func=cmd_checks)
    cp = checks_sub.add_parser("run")
    cp.add_argument("--path", action="append", default=[])
    cp.add_argument("--run-commands", action="store_true")
    cp.add_argument("--timeout", type=int, default=120)
    cp.add_argument("--json", action="store_true")
    cp.set_defaults(func=cmd_checks)

    p = sub.add_parser("doctor")
    add_project(p)
    p.add_argument("--write", action="store_true", help="Write QUANTAGENT_DOCTOR.md")
    p.add_argument("--json", action="store_true", help="Render machine-readable doctor output")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("onboard")
    add_project(p)
    p.add_argument("--json", action="store_true", help="Render machine-readable onboarding status")
    p.set_defaults(func=cmd_onboard)

    p = sub.add_parser("state")
    add_project(p)
    p.set_defaults(func=cmd_state)

    p = sub.add_parser("todo")
    add_project(p)
    p.add_argument("--write", action="store_true")
    p.add_argument("--set", nargs=2, metavar=("ID", "STATUS"))
    p.add_argument("--task-id", default=None, help="Show or update a task-bound Claude-style checklist")
    p.add_argument("--set-plan", nargs=2, metavar=("ID", "STATUS"), help="Set task checklist item to pending/in_progress/completed")
    p.add_argument("--title", default=None)
    p.add_argument("--detail", default=None)
    p.set_defaults(func=cmd_todo)

    p = sub.add_parser("review")
    add_project(p)
    p.add_argument("task", nargs="?")
    p.add_argument("--diff", action="store_true", help="Review changed or selected files instead of creating a model review request")
    p.add_argument("--path", action="append", help="Project-relative path to include in --diff review")
    p.add_argument("--staged", action="store_true", help="Use staged git diff for --diff review")
    p.add_argument("--no-diff", action="store_true", help="Hide unified diff in --diff review output")
    p.add_argument("--max-diff-lines", type=int, default=400)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("consensus")
    add_project(p)
    p.add_argument("--new", default=None, help="Create a new three-pass ChatGPT consistency request for this task")
    p.add_argument("--id", default=None, help="Check one consensus request id")
    p.add_argument("--no-chatgpt", action="store_true", help="Only write the request, do not call ChatGPT")
    p.set_defaults(func=cmd_consensus)

    p = sub.add_parser("loop")
    add_project(p)
    p.add_argument("--model", default=None)
    p.add_argument("--base-url", default=None)
    p.add_argument("--consensus-id", default=None)
    p.add_argument("task")
    p.set_defaults(func=cmd_loop)

    p = sub.add_parser("model-test")
    add_project(p)
    p.add_argument("--model", default=None)
    p.add_argument("--base-url", default=None)
    p.add_argument("--timeout", type=int, default=60)
    p.add_argument("--prompt", default="Reply with exactly: Mako model connection ok")
    p.set_defaults(func=cmd_model_test)

    p = sub.add_parser("ask")
    add_project(p)
    p.add_argument("--model", default=None)
    p.add_argument("--base-url", default=None)
    p.add_argument("task")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("fix", help="Low-friction safe edit path: preview by default, apply only with --apply")
    add_project(p)
    p.add_argument("task")
    p.add_argument("--path", default=None, help="Target file for a known replacement")
    p.add_argument("--path-list", action="append", help="Planning-only target file; repeatable")
    p.add_argument("--old", default=None, help="Exact text to replace")
    p.add_argument("--new", default=None, help="Replacement text")
    p.add_argument("--expected-count", type=int, default=1)
    p.add_argument("--test", nargs=argparse.REMAINDER)
    p.add_argument("--max-rounds", type=int, default=2)
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--apply", action="store_true", help="Apply the reviewed exact replacement and run tests")
    p.add_argument("--agent-profile", default=None, help="Apply an agent permission matrix before editing")
    p.add_argument("--out", default=None, help="Plan output path when no exact replacement is provided")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_fix)

    p = sub.add_parser("demo", help="Run proof demos that show Mako fixing code with evidence")
    add_project(p)
    demo_sub = p.add_subparsers(dest="demo_command", required=True)
    dp = demo_sub.add_parser("fix", help="Create a failing test project, fix it, and show red-to-green proof")
    dp.add_argument("--json", action="store_true")
    dp.set_defaults(func=cmd_demo)

    p = sub.add_parser("chat")
    add_project(p)
    p.add_argument("--model", default=None)
    p.add_argument("--base-url", default=None)
    p.add_argument("--once", default=None, help="Ask one message and exit")
    p.add_argument("--long", action="store_true", help="Ask for a fuller structured report")
    p.add_argument("--deep-context", action="store_true", help="Use a large context pack; expensive, only for full reconstruction")
    p.add_argument("--save-report", action="store_true", help="Save each answer as a markdown report in AI_协作交接")
    p.add_argument("--no-stream-file", action="store_true", help="Do not append replies to CHAT_REVIEW_STREAM.md")
    p.set_defaults(func=cmd_chat)

    p = sub.add_parser("experiment")
    add_project(p)
    p.add_argument("--scenario", default="A", choices=["A", "D"])
    p.add_argument("--input", default=None)
    p.add_argument("--name", default=None)
    p.add_argument("--return-col", default="net_return")
    p.add_argument("--date-col", default="entry_date")
    p.add_argument("--threshold-col", default="t1_auction_return")
    p.add_argument("--threshold", type=float, default=None)
    p.add_argument("--consensus-id", default=None)
    p.set_defaults(func=cmd_experiment)

    p = sub.add_parser("registry")
    add_project(p)
    p.add_argument("--latest", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_registry)

    p = sub.add_parser("run-p4")
    add_project(p)
    p.add_argument("--consensus-id", default=None)
    p.set_defaults(func=cmd_run_p4)

    p = sub.add_parser("run-next")
    add_project(p)
    p.add_argument("--model", default=None)
    p.add_argument("--task", default=None, help="Override the inferred next task")
    p.set_defaults(func=cmd_run_next)

    p = sub.add_parser("agent")
    add_project(p)
    p.add_argument("--model", default=None)
    p.add_argument("--base-url", default=None)
    p.add_argument("--max-steps", type=_non_negative_int, default=None, help="Stop the default agent before the next step after this many steps; legacy tool loop defaults to 4 when omitted")
    p.add_argument("--legacy-tool-loop", action="store_true", help="Use the old model/tool loop instead of the default agent-v3 path")
    p.add_argument("--json", action="store_true")
    p.add_argument("--mode", default="")
    p.add_argument("--path", action="append")
    p.add_argument("--input-provenance", default="")
    p.add_argument("--no-validate", action="store_true")
    p.add_argument("--stop-on-failure", action="store_true")
    p.add_argument("--strict-approval", action="store_true")
    p.add_argument("--max-duration-seconds", type=_non_negative_finite_float, default=None, help="Stop the agent loop before the next step after this many seconds")
    p.add_argument("--learning-context", choices=["auto", "on", "off"], default="auto", help="Control approved project skill context for deterministic planning")
    p.add_argument("--learning-project", default="", help="Read approved project skills from this project while editing --project")
    p.add_argument("--goal", default="")
    p.add_argument("--no-goal-guard", action="store_true")
    p.add_argument("--subagents", choices=["off", "auto", "plan-only"], default="off", help="Use supervisor-driven subagents instead of the single agent-v3 loop")
    p.add_argument("task")
    p.set_defaults(func=cmd_agent)

    p = sub.add_parser("agent-supervisor")
    add_project(p)
    supervisor_sub = p.add_subparsers(dest="supervisor_command", required=True)
    sp = supervisor_sub.add_parser("list")
    sp.add_argument("--limit", type=int, default=20)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_agent_supervisor)
    sp = supervisor_sub.add_parser("show")
    sp.add_argument("supervisor_id", nargs="?")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_agent_supervisor)
    sp = supervisor_sub.add_parser("refresh")
    sp.add_argument("parent_task_id", nargs="?")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_agent_supervisor)

    p = sub.add_parser("agent-v2")
    add_project(p)
    p.add_argument("--json", action="store_true")
    p.add_argument("--legacy-v2", action="store_true", help="Use the old v2 plan/execute/reflect loop instead of the default agent-v3 path")
    p.add_argument("--mode", default="")
    p.add_argument("--goal", default="")
    p.add_argument("--no-goal-guard", action="store_true")
    p.add_argument("--no-validate", action="store_true", help="Skip validation step")
    p.add_argument("--stop-on-failure", action="store_true", help="Stop after the first required failure")
    p.add_argument("--max-duration-seconds", type=_non_negative_finite_float, default=None, help="Stop the agent loop before the next step after this many seconds")
    p.add_argument("--max-steps", type=_non_negative_int, default=None, help="Stop the agent loop before the next step after this many steps")
    p.add_argument("task")
    p.set_defaults(func=cmd_agent_v2)

    p = sub.add_parser("agent-v3")
    add_project(p)
    p.add_argument("--json", action="store_true")
    p.add_argument("--mode", default="", help="Force an agent mode such as plan/build/review/repair/research/admin")
    p.add_argument("--path", action="append", help="Changed path used for mode routing and source checks")
    p.add_argument("--input-provenance", default="", help="Where the task came from, such as diff, user, hook, or session")
    p.add_argument("--no-validate", action="store_true", help="Skip validation step")
    p.add_argument("--stop-on-failure", action="store_true", help="Stop after the first required failure")
    p.add_argument("--strict-approval", action="store_true", help="Block ask decisions unless an approval exists")
    p.add_argument("--max-duration-seconds", type=_non_negative_finite_float, default=None, help="Stop the agent loop before the next step after this many seconds")
    p.add_argument("--max-steps", type=_non_negative_int, default=None, help="Stop the agent loop before the next step after this many steps")
    p.add_argument("--goal", default="", help="Higher-order user goal. Instructions are obeyed unless they conflict with this goal.")
    p.add_argument("--no-goal-guard", action="store_true", help="Disable goal-conflict guard for this run")
    p.add_argument("task")
    p.set_defaults(func=cmd_agent_v3)

    p = sub.add_parser("goal-contract")
    add_project(p)
    goal_sub = p.add_subparsers(dest="goal_command", required=True)
    gp = goal_sub.add_parser("show")
    gp.add_argument("--json", action="store_true")
    gp.set_defaults(func=cmd_goal_contract)
    gp = goal_sub.add_parser("set")
    gp.add_argument("goal")
    gp.add_argument("--constraint", action="append", default=[])
    gp.add_argument("--success", action="append", default=[])
    gp.add_argument("--no-data-strict", action="store_true", help="Disable generic uncertain-data blocking for this saved contract")
    gp.add_argument("--uncertainty-policy", default="block_uncertain_data_claims")
    gp.add_argument("--no-quant-strict", action="store_true", help="Disable strict quant hallucination blocking for this saved contract")
    gp.add_argument("--hallucination-policy", default="block_unsupported_quant_claims")
    gp.add_argument("--json", action="store_true")
    gp.set_defaults(func=cmd_goal_contract)
    gp = goal_sub.add_parser("check")
    gp.add_argument("instruction")
    gp.add_argument("--goal", default="")
    gp.add_argument("--constraint", action="append", default=[])
    gp.add_argument("--success", action="append", default=[])
    gp.add_argument("--json", action="store_true")
    gp.set_defaults(func=cmd_goal_contract)

    p = sub.add_parser("evidence")
    add_project(p)
    evidence_sub = p.add_subparsers(dest="evidence_command", required=True)
    ep = evidence_sub.add_parser("add")
    ep.add_argument("claim")
    ep.add_argument("--value", default="")
    ep.add_argument("--type", default="manual")
    ep.add_argument("--source", default="")
    ep.add_argument("--command", default="")
    ep.add_argument("--path", default="")
    ep.add_argument("--tool", default="")
    ep.add_argument("--confidence", type=float, default=1.0)
    ep.add_argument("--unverified", action="store_true")
    ep.add_argument("--json", action="store_true")
    ep.set_defaults(func=cmd_evidence)
    ep = evidence_sub.add_parser("list")
    ep.add_argument("--limit", type=int, default=50)
    ep.add_argument("--json", action="store_true")
    ep.set_defaults(func=cmd_evidence)

    p = sub.add_parser("answer-guard")
    add_project(p)
    p.add_argument("--answer", default="")
    p.add_argument("--answer-file", default="")
    p.add_argument("--goal", default="")
    p.add_argument("--task", default="")
    p.add_argument("--warn-only", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_answer_guard)

    p = sub.add_parser("better-option")
    p.add_argument("--goal", default="")
    p.add_argument("--mode", default="")
    p.add_argument("--json", action="store_true")
    p.add_argument("task", nargs="?", default="")
    p.set_defaults(func=cmd_better_option)

    p = sub.add_parser("headless")
    add_project(p)
    p.add_argument("--json", action="store_true")
    p.add_argument("--mode", default="")
    p.add_argument("--goal", default="")
    p.add_argument("--path", action="append")
    p.add_argument("--no-validate", action="store_true")
    p.add_argument("--strict-approval", action="store_true")
    p.add_argument("--max-duration-seconds", type=_non_negative_finite_float, default=None, help="Stop the agent loop before the next step after this many seconds")
    p.add_argument("--max-steps", type=_non_negative_int, default=None, help="Stop the agent loop before the next step after this many steps")
    p.add_argument("task")
    p.set_defaults(func=cmd_headless)

    p = sub.add_parser("mode-router")
    add_project(p)
    p.add_argument("--json", action="store_true")
    p.add_argument("--lint", action="store_true", help="Run router diagnostics instead of routing one task")
    p.add_argument("--mode", default="", help="Explicit mode override")
    p.add_argument("--previous-mode", default="")
    p.add_argument("--failure-class", default="")
    p.add_argument("--path", action="append", help="Changed path")
    p.add_argument("--tool", default="", help="Tool name about to run")
    p.add_argument("--input-provenance", default="")
    p.add_argument("task", nargs="?", default="")
    p.set_defaults(func=cmd_mode_router)

    p = sub.add_parser("agent-context")
    add_project(p)
    p.add_argument("--json", action="store_true")
    p.add_argument("--mode", default="", help="Explicit mode override")
    p.add_argument("--previous-mode", default="")
    p.add_argument("--failure-class", default="")
    p.add_argument("--path", action="append", help="Changed path")
    p.add_argument("--tool", default="", help="Tool name about to run")
    p.add_argument("--input-provenance", default="")
    p.add_argument("--no-repo-map", action="store_true")
    p.add_argument("--no-diagnostics", action="store_true")
    p.add_argument("--no-source-checks", action="store_true")
    p.add_argument("--no-runtime", action="store_true")
    p.add_argument("task", nargs="?", default="status")
    p.set_defaults(func=cmd_agent_context)

    p = sub.add_parser("session")
    add_project(p)
    p.add_argument("--new", nargs="?", const=f"{PRODUCT_NAME} session", default=None)
    p.add_argument("--end", default=None, help="Close a session and emit SessionEnd hooks")
    p.add_argument("--reason", default="", help="Reason used with --end")
    p.add_argument("--latest", action="store_true")
    p.add_argument("--show", default=None)
    p.add_argument("--compact", default=None)
    p.add_argument("--keep-last", type=int, default=8)
    p.add_argument("--append", nargs=3, metavar=("ID", "ROLE", "TEXT"))
    p.add_argument("--search", default=None)
    p.add_argument("--export", default=None)
    p.add_argument("--format", default="json", choices=["json", "markdown"])
    p.add_argument("--out", default=None)
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_session)

    p = sub.add_parser("session-bus")
    add_project(p)
    session_bus_sub = p.add_subparsers(dest="session_bus_command", required=True)
    bp = session_bus_sub.add_parser("start")
    bp.add_argument("--owner", default="local")
    bp.add_argument("--channel", action="append", default=[])
    bp.add_argument("--json", action="store_true")
    bp.set_defaults(func=cmd_session_bus)
    bp = session_bus_sub.add_parser("stop")
    bp.add_argument("--reason", default="")
    bp.add_argument("--json", action="store_true")
    bp.set_defaults(func=cmd_session_bus)
    bp = session_bus_sub.add_parser("status")
    bp.add_argument("--json", action="store_true")
    bp.set_defaults(func=cmd_session_bus)
    bp = session_bus_sub.add_parser("send")
    bp.add_argument("content")
    bp.add_argument("--channel", default="cli")
    bp.add_argument("--sender", default="cli")
    bp.add_argument("--target", default="agent")
    bp.add_argument("--session-id", default="")
    bp.add_argument("--metadata-json", default="{}")
    bp.add_argument("--json", action="store_true")
    bp.set_defaults(func=cmd_session_bus)
    bp = session_bus_sub.add_parser("messages")
    bp.add_argument("--session-id", default="")
    bp.add_argument("--channel", default="")
    bp.add_argument("--limit", type=int, default=50)
    bp.add_argument("--json", action="store_true")
    bp.set_defaults(func=cmd_session_bus)
    bp = session_bus_sub.add_parser("summary")
    bp.add_argument("--json", action="store_true")
    bp.set_defaults(func=cmd_session_bus)

    p = sub.add_parser("task")
    add_project(p)
    p.add_argument("--add", default=None)
    p.add_argument("--detail", default=None)
    p.add_argument("--status", default="queued", choices=sorted(VALID_STATUSES))
    p.add_argument("--set", nargs=2, metavar=("ID", "STATUS"))
    p.add_argument("--note", default=None)
    p.add_argument("--evidence", default=None)
    p.add_argument("--run-agent", default=None, help="Start a background local agent task")
    p.add_argument("--run-shell", nargs=argparse.REMAINDER, default=None, help="Start a guarded background shell task")
    p.add_argument("--title", default=None, help="Title for --run-agent or --run-shell task")
    p.add_argument("--no-validation", action="store_true", help="Skip validation inside --run-agent")
    p.add_argument("--stop-on-failure", action="store_true", help="Stop --run-agent after the first required failure")
    p.add_argument("--allow-risky", action="store_true", help="Allow ASK-level shell tasks; DENY remains blocked")
    p.add_argument("--refresh", action="store_true", help="Refresh runtime task statuses before listing")
    p.add_argument("--stop", default=None, help="Stop a running runtime task")
    p.add_argument("--output", default=None, help="Show runtime task stdout")
    p.add_argument("--stderr", action="store_true", help="Show stderr for --output")
    p.add_argument("--tail", type=int, default=4000)
    p.set_defaults(func=cmd_task)

    p = sub.add_parser("tasks")
    add_project(p)
    tasks_sub = p.add_subparsers(dest="tasks_command", required=True)
    tp = tasks_sub.add_parser("list")
    tp.add_argument("--refresh", action="store_true")
    tp.add_argument("--json", action="store_true")
    tp.set_defaults(func=cmd_tasks)
    tp = tasks_sub.add_parser("show")
    tp.add_argument("task_id")
    tp.add_argument("--no-refresh", action="store_true")
    tp.add_argument("--no-output", action="store_true")
    tp.add_argument("--stderr", action="store_true")
    tp.add_argument("--tail", type=int, default=4000)
    tp.add_argument("--json", action="store_true")
    tp.set_defaults(func=cmd_tasks)
    tp = tasks_sub.add_parser("output")
    tp.add_argument("task_id")
    tp.add_argument("--stderr", action="store_true")
    tp.add_argument("--tail", type=int, default=4000)
    tp.set_defaults(func=cmd_tasks)
    tp = tasks_sub.add_parser("stop")
    tp.add_argument("task_id")
    tp.add_argument("--json", action="store_true")
    tp.set_defaults(func=cmd_tasks)
    tp = tasks_sub.add_parser("resume")
    tp.add_argument("task_id")
    tp.add_argument("--title", default="")
    tp.add_argument("--allow-risky", action="store_true")
    tp.add_argument("--no-validation", action="store_true")
    tp.add_argument("--stop-on-failure", action="store_true")
    tp.add_argument("--json", action="store_true")
    tp.set_defaults(func=cmd_tasks)

    p = sub.add_parser("desktop")
    add_project(p)
    p.add_argument("--json", action="store_true")
    desktop_sub = p.add_subparsers(dest="desktop_command", required=True)

    dp = desktop_sub.add_parser("live")
    dp.add_argument("--once", action="store_true", help="Render one frame and exit")
    dp.add_argument("--interval", type=float, default=1.0, help="Refresh interval in seconds")
    dp.add_argument("--limit", type=int, default=8)
    dp.add_argument("--no-color", action="store_true")
    dp.add_argument("--probe", action="store_true", help="Run read-only screenshot and accessibility readiness probes")
    dp.add_argument("--probe-network", default="", help="Run a read-only network HEAD probe against this URL")
    dp.add_argument("--html", action="store_true", help="Render one static HTML dashboard to stdout")
    dp.add_argument("--html-out", default="", help="Write one static HTML dashboard to this path")
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("guard", help="Watch desktop daemon artifacts and write STOP when invariants fail")
    dp.add_argument("--watch", action="store_true", help="Keep checking until STOP or max-minutes")
    dp.add_argument("--interval", type=float, default=2.0)
    dp.add_argument("--max-minutes", type=float, default=0.0)
    dp.add_argument("--max-event-age-seconds", type=float, default=180.0)
    dp.add_argument("--same-action-limit", type=int, default=3)
    dp.add_argument("--state-path", default="")
    dp.add_argument("--query-events-path", default="")
    dp.add_argument("--trajectory-path", default="")
    dp.add_argument("--stop-file", default="")
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("front")
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("window")
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("open")
    dp.add_argument("target", help="App name, URL, path, search text, or 'terminal'")
    dp.add_argument("--kind", choices=["auto", "app", "url", "path", "terminal", "search"], default="auto")
    dp.add_argument("--browser", default="", help="Browser app for URL opens, or search engine for --kind search")
    dp.add_argument("--cwd", default="", help="Directory for --kind terminal")
    dp.add_argument("--execute", action="store_true", help="Actually open the target")
    dp.add_argument("--reviewed", action="store_true", help="Confirm the open action was reviewed")
    dp.add_argument("--plan-only", action="store_true")
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("shot")
    dp.add_argument("--name", default=None)
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("grid")
    dp.add_argument("--name", default=None)
    dp.add_argument("--cols", type=int, default=12)
    dp.add_argument("--rows", type=int, default=8)
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("ax")
    dp.add_argument("--name", default=None)
    dp.add_argument("--depth", type=int, default=4)
    dp.add_argument("--limit", type=int, default=500)
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("ocr")
    dp.add_argument("--image", default=None, help="Image path; defaults to a fresh screenshot")
    dp.add_argument("--name", default=None)
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("som")
    dp.add_argument("--image", default=None, help="Image path; defaults to a fresh screenshot")
    dp.add_argument("--name", default=None)
    dp.add_argument("--cols", type=int, default=12)
    dp.add_argument("--rows", type=int, default=8)
    dp.add_argument("--no-ax", action="store_true")
    dp.add_argument("--no-ocr", action="store_true")
    dp.add_argument("--include-grid", action="store_true")
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("tokenize")
    dp.add_argument("--image", default=None, help="Image path; defaults to a fresh screenshot")
    dp.add_argument("--name", default=None)
    dp.add_argument("--cols", type=int, default=12)
    dp.add_argument("--rows", type=int, default=8)
    dp.add_argument("--limit", type=int, default=240)
    dp.add_argument("--no-ax", action="store_true")
    dp.add_argument("--no-ocr", action="store_true")
    dp.add_argument("--no-som", action="store_true")
    dp.add_argument("--include-grid", action="store_true")
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("decide")
    dp.add_argument("goal")
    dp.add_argument("--tokens", default=None, help="Tokenization JSON path; defaults to latest_tokenize.json")
    dp.add_argument("--last-action", default="")
    dp.add_argument("--last-result", default="")
    dp.add_argument("--browser", default="Safari")
    dp.add_argument("--engine", choices=["google", "duckduckgo", "ddg", "bing"], default="google")
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("daemon")
    dp.add_argument("goal")
    dp.add_argument("--execute", action="store_true", help="Actually run decided desktop actions")
    dp.add_argument("--reviewed", action="store_true", help="Confirm this daemon run was reviewed")
    dp.add_argument("--allow-actions", action="store_true", help="Allow desktop side effects after review")
    dp.add_argument("--browser", default="Safari")
    dp.add_argument("--engine", choices=["google", "duckduckgo", "ddg", "bing"], default="google")
    dp.add_argument("--max-steps", type=int, default=20)
    dp.add_argument("--delay", type=float, default=1.0)
    dp.add_argument("--stop-file", default=None)
    dp.add_argument("--include-grid", action="store_true")
    dp.add_argument("--token-limit", type=int, default=240)
    dp.set_defaults(func=cmd_desktop)

    def add_night_runtime_options(night_parser: argparse.ArgumentParser, *, include_execute: bool) -> None:
        if include_execute:
            night_parser.add_argument("--execute", action="store_true", help="Actually run queued night tasks")
            night_parser.add_argument("--reviewed", action="store_true", help="Confirm this night daemon run was reviewed")
            night_parser.add_argument("--allow-actions", action="store_true", help="Allow desktop side effects after review")
        night_parser.add_argument("--max-steps", type=int, default=20)
        night_parser.add_argument("--max-minutes", type=float, default=480.0)
        night_parser.add_argument("--delay", type=float, default=30.0)
        night_parser.add_argument("--stop-file", default=None, help="Abort before the next step when this file exists")
        night_parser.add_argument("--include-grid", action="store_true")
        night_parser.add_argument("--token-limit", type=int, default=240)
        night_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS)

    def add_runtime_queue_worker_options(night_parser: argparse.ArgumentParser) -> None:
        night_parser.add_argument("--runtime-queue", default=None, help="Claim tasks from this unified runtime queue instead of the legacy JSON queue")
        night_parser.add_argument("--worker-id", default="", help="Lease owner for runtime queue claims")
        night_parser.add_argument("--lease-seconds", type=float, default=300.0, help="Runtime queue lease duration")

    dp = desktop_sub.add_parser("night", help="Queue, run, and inspect bounded Night Daemon desktop tasks")
    dp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    night_sub = dp.add_subparsers(dest="night_command", required=True)

    np = night_sub.add_parser("enqueue")
    np.add_argument("goal")
    add_night_runtime_options(np, include_execute=False)
    np.set_defaults(func=cmd_desktop)

    np = night_sub.add_parser("run")
    add_night_runtime_options(np, include_execute=True)
    add_runtime_queue_worker_options(np)
    np.set_defaults(func=cmd_desktop)

    np = night_sub.add_parser("status")
    np.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    np.set_defaults(func=cmd_desktop)

    np = night_sub.add_parser("stop")
    np.add_argument("task_id", nargs="?")
    np.add_argument("--all", action="store_true")
    np.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    np.set_defaults(func=cmd_desktop)

    np = night_sub.add_parser("resume")
    np.add_argument("task_id")
    add_night_runtime_options(np, include_execute=False)
    np.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("l4-soak", help="Run the Desktop L4 soak worker")
    dp.add_argument("--cycles", type=int, default=1)
    dp.add_argument("--dry-run", dest="dry_run", action="store_true", default=True, help="Run without desktop side effects")
    dp.add_argument("--no-dry-run", dest="dry_run", action="store_false", help="Use real desktop screenshot/observe/act hooks")
    dp.add_argument("--execute", action="store_true", help="Allow live l4-soak execution when paired with --reviewed and --allow-actions")
    dp.add_argument("--reviewed", action="store_true", help="Confirm this l4-soak run was reviewed")
    dp.add_argument("--allow-actions", action="store_true", help="Allow desktop side effects after review")
    dp.add_argument("--goal", default="")
    dp.add_argument("--interval-seconds", type=float, default=0.0)
    dp.add_argument("--stop-file", default="")
    dp.add_argument("--loop-threshold", type=int, default=None)
    dp.add_argument("--trajectory-path", default="")
    dp.add_argument("--heartbeat-path", default="")
    dp.add_argument("--status-path", default="")
    dp.add_argument("--result-path", default="")
    dp.add_argument("--phase-timeout-seconds", type=float, default=0.0, help="Kill a stuck l4-soak phase hook after this many seconds; 0 disables")
    dp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("find")
    dp.add_argument("query")
    dp.add_argument("--source", choices=["ax", "ocr", "som", "grid", "both", "all"], default="all")
    dp.add_argument("--limit", type=int, default=10)
    dp.add_argument("--ax", default=None, help="AX snapshot JSON path")
    dp.add_argument("--grid", default=None, help="Grid JSON path")
    dp.add_argument("--ocr", default=None, help="OCR JSON path")
    dp.add_argument("--som", default=None, help="SoM JSON path")
    dp.add_argument("--refresh-ax", action="store_true", help="Capture a fresh accessibility snapshot before searching")
    dp.add_argument("--refresh-som", action="store_true", help="Capture a fresh SoM snapshot before searching")
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("web-search")
    dp.add_argument("query")
    dp.add_argument("--browser", default="Safari")
    dp.add_argument("--engine", choices=["google", "duckduckgo", "ddg", "bing"], default="google")
    dp.add_argument("--execute", action="store_true", help="Actually run the desktop steps")
    dp.add_argument("--reviewed", action="store_true", help="Confirm side-effect steps were reviewed")
    dp.add_argument("--verify-after", action="store_true", help="Screenshot after side-effect steps and run step verification queries when present")
    dp.add_argument("--plan-only", action="store_true", help="Only print the generated plan")
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("find-click")
    dp.add_argument("query")
    dp.add_argument("--source", choices=["ax", "ocr", "som", "grid", "both", "all"], default="all")
    dp.add_argument("--execute", action="store_true", help="Actually click the matched target")
    dp.add_argument("--reviewed", action="store_true", help="Confirm side-effect steps were reviewed")
    dp.add_argument("--verify-after", action="store_true", help="Screenshot after side-effect steps")
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("run")
    dp.add_argument("plan")
    dp.add_argument("--execute", action="store_true", help="Actually run the desktop plan")
    dp.add_argument("--reviewed", action="store_true", help="Confirm side-effect steps were reviewed")
    dp.add_argument("--verify-after", action="store_true", help="Screenshot after side-effect steps and run step verification queries when present")
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("plan-click")
    dp.add_argument("query")
    dp.add_argument("--grid", default=None)
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("grid-click")
    dp.add_argument("cell")
    dp.add_argument("--grid", default=None)
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("som-click")
    dp.add_argument("mark")
    dp.add_argument("--som", default=None)
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("send-confirm", help="Type a message, press return, and confirm it appeared before continuing")
    dp.add_argument("text")
    dp.add_argument("--count", type=int, default=1)
    dp.add_argument("--execute", action="store_true", help="Actually type and submit the message")
    dp.add_argument("--reviewed", action="store_true", help="Confirm this send loop was reviewed")
    dp.add_argument("--no-confirm", action="store_true", help="Send without screenshot/OCR confirmation")
    dp.add_argument("--confirm-timeout", type=float, default=4.0)
    dp.add_argument("--poll-interval", type=float, default=0.5)
    dp.add_argument("--interval", type=float, default=0.12, help="Delay between confirmed sends")
    dp.add_argument("--max-count", type=int, default=100)
    dp.add_argument("--stop-file", default=None)
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("schema")
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("modes")
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("targets")
    dp.add_argument("--grid", default=None)
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("activate")
    dp.add_argument("app")
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("type")
    dp.add_argument("text")
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("hotkey")
    dp.add_argument("keys", nargs="+")
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("click")
    dp.add_argument("x", type=int)
    dp.add_argument("y", type=int)
    dp.set_defaults(func=cmd_desktop)

    dp = desktop_sub.add_parser("move")
    dp.add_argument("x", type=int)
    dp.add_argument("y", type=int)
    dp.set_defaults(func=cmd_desktop)

    p = sub.add_parser("desktop-agent", help="Fast local desktop takeover agent with trace and STOP-file fuse")
    add_project(p)
    p.add_argument("instruction")
    p.add_argument("--execute", action="store_true", help="Actually control the screen")
    p.add_argument("--reviewed", action="store_true", help="Confirm this direct takeover run was reviewed")
    p.add_argument("--browser", default="Safari")
    p.add_argument("--max-actions", type=int, default=12)
    p.add_argument("--delay", type=float, default=0.35, help="Delay between actions; normal human-speed default")
    p.add_argument("--verify-after", action="store_true", help="Screenshot after each side-effect action")
    p.add_argument("--stop-file", default=None, help="Abort before the next action when this file exists")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_desktop_agent)

    p = sub.add_parser("desktop-overnight", help="Bounded overnight desktop agent with observe-act-verify loop")
    add_project(p)
    p.add_argument("goal")
    p.add_argument("--execute", action="store_true", help="Actually run the overnight loop")
    p.add_argument("--reviewed", action="store_true", help="Confirm this long-running desktop run was reviewed")
    p.add_argument("--allow-actions", action="store_true", help="Allow desktop side effects after review")
    p.add_argument("--browser", default="Safari")
    p.add_argument("--max-rounds", type=int, default=20)
    p.add_argument("--max-minutes", type=float, default=480.0)
    p.add_argument("--max-actions", type=int, default=12)
    p.add_argument("--delay", type=float, default=30.0, help="Delay between rounds")
    p.add_argument("--stop-file", default=None, help="Abort before the next round when this file exists")
    p.add_argument("--require-action-approval", action="store_true", help="Require a stored approval before each desktop side-effect action")
    p.add_argument("--approval-id", default="", help="Approval id to resume one matching desktop side-effect action")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_desktop_overnight)

    p = sub.add_parser("desktop-daemon", help="Queue and run bounded local desktop daemon tasks")
    add_project(p)
    p.add_argument("--json", action="store_true")
    desktop_daemon_sub = p.add_subparsers(dest="desktop_daemon_command", required=True)

    def add_desktop_daemon_task_options(daemon_parser: argparse.ArgumentParser) -> None:
        daemon_parser.add_argument("--max-steps", type=int, default=20)
        daemon_parser.add_argument("--max-minutes", type=float, default=480.0)
        daemon_parser.add_argument("--delay", type=float, default=30.0)
        daemon_parser.add_argument("--stop-file", default=None, help="Abort before the next step when this file exists")
        daemon_parser.add_argument("--include-grid", action="store_true")
        daemon_parser.add_argument("--token-limit", type=int, default=240)
        daemon_parser.add_argument("--priority", type=int, default=100)
        daemon_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS)

    def add_desktop_daemon_run_options(daemon_parser: argparse.ArgumentParser) -> None:
        add_desktop_daemon_task_options(daemon_parser)
        daemon_parser.add_argument("--execute", action="store_true", help="Actually run queued desktop actions")
        daemon_parser.add_argument("--reviewed", action="store_true", help="Confirm this daemon run was reviewed")
        daemon_parser.add_argument("--allow-actions", action="store_true", help="Allow desktop side effects after review")
        daemon_parser.add_argument("--max-tasks", type=int, default=None, help="Maximum queued tasks to process; defaults to 1 when a goal is supplied")
        daemon_parser.add_argument("--watch", action="store_true", help="Keep waiting for queued tasks until STOP or time budget")
        daemon_parser.add_argument("--idle-sleep", type=float, default=30.0)
        daemon_parser.add_argument("--no-failure-pause", dest="failure_pause", action="store_false", default=True)
        add_runtime_queue_worker_options(daemon_parser)

    dp = desktop_daemon_sub.add_parser("run", help="Optionally enqueue one goal, then run the desktop daemon queue")
    dp.add_argument("goal", nargs="?")
    add_desktop_daemon_run_options(dp)
    dp.set_defaults(func=cmd_desktop_daemon)

    dp = desktop_daemon_sub.add_parser("enqueue", help="Queue a desktop daemon task without running it")
    dp.add_argument("goal")
    add_desktop_daemon_task_options(dp)
    dp.set_defaults(func=cmd_desktop_daemon)

    dp = desktop_daemon_sub.add_parser("status")
    dp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    dp.set_defaults(func=cmd_desktop_daemon)

    dp = desktop_daemon_sub.add_parser("stop")
    dp.add_argument("task_id", nargs="?")
    dp.add_argument("--all", action="store_true")
    dp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    dp.set_defaults(func=cmd_desktop_daemon)

    dp = desktop_daemon_sub.add_parser("resume")
    dp.add_argument("task_id")
    add_desktop_daemon_task_options(dp)
    dp.set_defaults(func=cmd_desktop_daemon)

    p = sub.add_parser("desktop-eval", help="Run and inspect desktop daemon L4/L5 evaluation suites")
    add_project(p)
    p.add_argument("--json", action="store_true")
    desktop_eval_sub = p.add_subparsers(dest="desktop_eval_command", required=True)

    ep = desktop_eval_sub.add_parser("run")
    ep.add_argument("--suite", default="suite_l4")
    ep.add_argument("--scenario", default="")
    ep.add_argument("--duration-minutes", type=float, default=60.0)
    ep.add_argument("--max-steps", type=int, default=100)
    ep.add_argument("--execute", action="store_true", help="Actually run desktop actions in scenarios")
    ep.add_argument("--reviewed", action="store_true", help="Confirm this eval run was reviewed")
    ep.add_argument("--allow-actions", action="store_true", help="Allow desktop side effects after review")
    ep.add_argument("--stop-file", default=None)
    ep.add_argument(
        "--scenario-timeout",
        type=float,
        default=0.0,
        help="Kill an individual eval scenario runner after this many seconds; 0 keeps injected runners inline",
    )
    ep.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    ep.set_defaults(func=cmd_desktop_eval)

    ep = desktop_eval_sub.add_parser("list")
    ep.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    ep.set_defaults(func=cmd_desktop_eval)

    ep = desktop_eval_sub.add_parser("show")
    ep.add_argument("path")
    ep.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    ep.set_defaults(func=cmd_desktop_eval)

    ep = desktop_eval_sub.add_parser("soak")
    ep.add_argument("--suite", default="suite_live")
    ep.add_argument("--hours", type=float, default=4.0)
    ep.add_argument("--interval", type=float, default=60.0)
    ep.add_argument("--max-cycles", type=int, default=0)
    ep.add_argument("--max-steps", type=int, default=100)
    ep.add_argument("--execute", action="store_true", help="Actually run reviewed live eval cycles")
    ep.add_argument("--reviewed", action="store_true", help="Confirm this soak run was reviewed")
    ep.add_argument("--allow-actions", action="store_true", help="Allow suite_live side effects after review")
    ep.add_argument("--no-guardian", action="store_true", help="Disable guardian checks between cycles")
    ep.add_argument("--require-evidence", action="store_true", help="Require persisted eval, query-events, and trajectory artifacts per cycle")
    ep.add_argument("--no-watchdog", action="store_true", help="Disable process watchdog around each eval cycle")
    ep.add_argument("--cycle-timeout", type=float, default=0.0, help="Kill an eval cycle after this many seconds; default follows cycle duration for built-in runner")
    ep.add_argument("--watchdog-interval", type=float, default=2.0, help="Concurrent watchdog check interval in seconds")
    ep.add_argument("--stop-file", default=None)
    ep.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    ep.set_defaults(func=cmd_desktop_eval)

    ep = desktop_eval_sub.add_parser("soak-latest")
    ep.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    ep.set_defaults(func=cmd_desktop_eval)

    ep = desktop_eval_sub.add_parser("soak-show")
    ep.add_argument("path")
    ep.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    ep.set_defaults(func=cmd_desktop_eval)

    ep = desktop_eval_sub.add_parser("soak-list")
    ep.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    ep.set_defaults(func=cmd_desktop_eval)

    p = sub.add_parser("files")
    add_project(p)
    p.add_argument("--json", action="store_true")
    files_sub = p.add_subparsers(dest="files_command", required=True)

    fp = files_sub.add_parser("read")
    fp.add_argument("path")
    fp.add_argument("--max-chars", type=int, default=8000)
    fp.set_defaults(func=cmd_files)

    fp = files_sub.add_parser("search")
    fp.add_argument("pattern")
    fp.add_argument("path", nargs="?", default=".")
    fp.add_argument("--glob", default=None)
    fp.add_argument("--ignore-case", action="store_true")
    fp.add_argument("--max-results", type=int, default=50)
    fp.set_defaults(func=cmd_files)

    fp = files_sub.add_parser("diff-replace")
    fp.add_argument("path")
    fp.add_argument("old")
    fp.add_argument("new")
    fp.add_argument("--expected-count", type=int, default=1)
    fp.set_defaults(func=cmd_files)

    fp = files_sub.add_parser("replace")
    fp.add_argument("path")
    fp.add_argument("old")
    fp.add_argument("new")
    fp.add_argument("--expected-count", type=int, default=1)
    fp.set_defaults(func=cmd_files)

    fp = files_sub.add_parser("diff-write")
    fp.add_argument("path")
    fp.add_argument("text")
    fp.set_defaults(func=cmd_files)

    fp = files_sub.add_parser("write")
    fp.add_argument("path")
    fp.add_argument("text")
    fp.set_defaults(func=cmd_files)

    p = sub.add_parser("memory")
    add_project(p)
    p.add_argument("--add", default=None)
    p.add_argument("--search", default=None)
    p.add_argument("--kind", default="note")
    p.add_argument("--kind-filter", action="store_true")
    p.add_argument("--source", default=None)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--extract-text", default=None, help="Extract long-term memory candidates from text")
    p.add_argument("--extract-report", default=None, help="Extract long-term memory candidates from a report file")
    p.add_argument("--extract-session", default=None, help="Extract long-term memory candidates from a session id")
    p.add_argument("--extract-tool-loop", default=None, help="Extract long-term memory candidates from a tool-loop JSON file")
    p.add_argument("--dry-run", action="store_true", help="Show memory candidates without storing them")
    p.add_argument("--propose-text", default=None, help="Queue extracted memories for human approval instead of writing directly")
    p.add_argument("--learn-runtime", action="store_true", help="Queue Hermes-style memory proposals from the latest query runtime")
    p.add_argument("--query-id", default=None, help="Runtime query id for --learn-runtime")
    p.add_argument("--proposals", action="store_true", help="List memory sidecar proposals")
    p.add_argument("--status", default=None, help="Filter memory proposals by pending/approved/denied")
    p.add_argument("--approve-proposal", default=None)
    p.add_argument("--deny-proposal", default=None)
    p.add_argument("--reason", default=None)
    p.add_argument("--min-confidence", type=float, default=0.75)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_memory)

    p = sub.add_parser("edit-loop")
    add_project(p)
    p.add_argument("--json", action="store_true")
    p.add_argument("--plan-json", default=None, help="Run a multi-file change-set plan JSON")
    p.add_argument("--old", default=None)
    p.add_argument("--new", dest="new_values", action="append")
    p.add_argument("--expected-count", type=int, default=1)
    p.add_argument("--before", default=None, help="Context that must appear immediately before the old text")
    p.add_argument("--after", default=None, help="Context that must appear immediately after the old text")
    p.add_argument("--max-attempts", type=int, default=3)
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--allow-risky-tests", action="store_true")
    p.add_argument("--keep-failed", action="store_true", help="Leave the last failed candidate applied")
    p.add_argument("path", nargs="?")
    p.add_argument("--test", nargs=argparse.REMAINDER, required=True)
    p.set_defaults(func=cmd_edit_loop)

    p = sub.add_parser("toolsets")
    p.add_argument("name", nargs="?")
    p.set_defaults(func=cmd_toolsets)

    p = sub.add_parser("sandbox")
    add_project(p)
    p.add_argument("--profile", default="project")
    p.add_argument("--show-profile", action="store_true")
    p.add_argument("--check-tool", default=None)
    p.add_argument("--explain-shell", default=None, help="Classify a shell command into permission subjects and risk levels")
    p.add_argument("--cwd", default=None, help="Working directory for --explain-shell path resolution")
    p.add_argument("--args-json", default="{}", help="Tool argument envelope for DSL checks such as external_directory")
    p.add_argument("--reason", default=None)
    p.add_argument("--approve", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_sandbox)

    p = sub.add_parser("plugins")
    add_project(p)
    p.add_argument("--json", action="store_true", help="Render plugin registry JSON")
    p.add_argument("--refresh", action="store_true", help="Write generated plugin registry state")
    p.add_argument("--trust-report", action="store_true", help="Render plugin trust and isolation recommendations")
    p.add_argument("--snapshot", action="store_true", help="Render plugin install snapshot JSON/text")
    p.add_argument("--write-snapshot", default=None, help="Write plugin install snapshot JSON to path")
    p.add_argument("--compare-snapshot", default=None, help="Compare current plugin install snapshot against a previous snapshot JSON")
    p.set_defaults(func=cmd_plugins)

    p = sub.add_parser("ecosystem")
    add_project(p)
    p.add_argument("--json", action="store_true", help="Render ecosystem catalog JSON")
    p.add_argument("--refresh", action="store_true", help="Write generated ecosystem catalog state")
    p.add_argument("--search", default="", help="Filter ecosystem entries by text")
    p.add_argument("--kind", default="", choices=["", "skill", "tool", "plugin", "mcp", "upstream"], help="Filter ecosystem entries by kind")
    p.add_argument("--limit", type=int, default=80)
    p.set_defaults(func=cmd_ecosystem)

    p = sub.add_parser("permissions")
    add_project(p)
    permissions_sub = p.add_subparsers(dest="permissions_command", required=True)
    pp = permissions_sub.add_parser("explain")
    pp.add_argument("--profile", default="build")
    pp.add_argument("--tool", required=True)
    pp.add_argument("--args-json", default="{}")
    pp.add_argument("--approve", action="store_true")
    pp.add_argument("--json", action="store_true")
    pp.set_defaults(func=cmd_permissions)
    pp = permissions_sub.add_parser("denials")
    pp.add_argument("--limit", type=int, default=20)
    pp.add_argument("--json", action="store_true")
    pp.set_defaults(func=cmd_permissions)

    p = sub.add_parser("diagnostics")
    add_project(p)
    diagnostics_sub = p.add_subparsers(dest="diagnostics_command", required=True)
    dp = diagnostics_sub.add_parser("refresh")
    dp.add_argument("--limit", type=int, default=500)
    dp.add_argument("--path", action="append")
    dp.add_argument("--json", action="store_true")
    dp.set_defaults(func=cmd_diagnostics)
    dp = diagnostics_sub.add_parser("list")
    dp.add_argument("--limit", type=int, default=500)
    dp.add_argument("--path", action="append")
    dp.add_argument("--json", action="store_true")
    dp.set_defaults(func=cmd_diagnostics)

    p = sub.add_parser("compact-budget")
    p.add_argument("--token-budget", type=int, default=80_000)
    p.add_argument("--threshold", type=float, default=0.72)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("message", nargs="+")
    p.set_defaults(func=cmd_compact_budget)

    p = sub.add_parser("diff-preview")
    add_project(p)
    p.add_argument("--diff", default=None, help="Unified diff text to preview")
    p.add_argument("--diff-file", default=None, help="Path to a unified diff file")
    p.add_argument("--review-id", default=None, help="Build preview from an isolation review")
    p.add_argument("--task", default=None)
    p.add_argument("--profile", default="build")
    p.add_argument("--test", nargs=argparse.REMAINDER)
    p.add_argument("--write", action="store_true")
    p.add_argument("--include-diff", action="store_true")
    p.add_argument("--fail-on-approval", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_diff_preview)

    p = sub.add_parser("apply-gate")
    add_project(p)
    apply_gate_sub = p.add_subparsers(dest="apply_gate_command", required=True)

    def add_apply_gate_args(gp: argparse.ArgumentParser) -> None:
        gp.add_argument("review_id")
        gp.add_argument("--preview-id", default=None)
        gp.add_argument("--expected-review-id", default=None, help="Block unless this exact recommended review id is being applied")
        gp.add_argument("--profile", default="build")
        gp.add_argument("--approve", action="store_true", help="Treat preview/test ASK permissions as explicitly approved")
        gp.add_argument("--allow-no-tests", action="store_true")
        gp.add_argument("--allow-diagnostic-errors", action="store_true")
        gp.add_argument("--allow-high-risk", action="store_true")
        gp.add_argument("--no-source-checks", action="store_true", help="Skip .quantagent/.continue source checks in apply gate")
        gp.add_argument("--run-source-check-commands", action="store_true", help="Run commands declared by matching source checks")
        gp.add_argument("--test", nargs=argparse.REMAINDER)
        gp.add_argument("--json", action="store_true")

    gp = apply_gate_sub.add_parser("evaluate")
    add_apply_gate_args(gp)
    gp.set_defaults(func=cmd_apply_gate)
    gp = apply_gate_sub.add_parser("apply")
    add_apply_gate_args(gp)
    gp.add_argument("--no-rollback", action="store_true", help="Keep applied review even if the post-apply test fails")
    gp.set_defaults(func=cmd_apply_gate)

    p = sub.add_parser("approval")
    add_project(p)
    approval_sub = p.add_subparsers(dest="approval_command", required=True)
    ap = approval_sub.add_parser("list")
    ap.add_argument("--status", default=None)
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--json", action="store_true")
    ap.set_defaults(func=cmd_approval)
    ap = approval_sub.add_parser("show")
    ap.add_argument("approval_id")
    ap.add_argument("--json", action="store_true")
    ap.set_defaults(func=cmd_approval)
    ap = approval_sub.add_parser("approve")
    ap.add_argument("approval_id")
    ap.add_argument("--allow-always", action="store_true")
    ap.add_argument("--reason", default=None)
    ap.set_defaults(func=cmd_approval)
    ap = approval_sub.add_parser("deny")
    ap.add_argument("approval_id")
    ap.add_argument("--reason", default=None)
    ap.set_defaults(func=cmd_approval)

    p = sub.add_parser("mcp")
    add_project(p)
    mcp_sub = p.add_subparsers(dest="mcp_command", required=True)
    mp = mcp_sub.add_parser("list")
    mp.add_argument("--json", action="store_true")
    mp.set_defaults(func=cmd_mcp)
    mp = mcp_sub.add_parser("tools")
    mp.add_argument("server", nargs="?")
    mp.add_argument("--json", action="store_true")
    mp.set_defaults(func=cmd_mcp)
    mp = mcp_sub.add_parser("schema-snapshot")
    mp.add_argument("server", nargs="?")
    mp.add_argument("--write", default=None, help="Write MCP schema snapshot JSON to path")
    mp.add_argument("--compare", default=None, help="Compare current MCP schema snapshot against a previous snapshot JSON")
    mp.add_argument("--json", action="store_true")
    mp.set_defaults(func=cmd_mcp)
    mp = mcp_sub.add_parser("call")
    mp.add_argument("server")
    mp.add_argument("tool")
    mp.add_argument("--args-json", default="{}")
    mp.add_argument("--approval-id", default=None)
    mp.add_argument("--approve", action="store_true", help="Treat ASK-level MCP calls as owner-approved")
    mp.add_argument("--agent-profile", default=None, help="Apply an agent permission matrix such as plan/build/audit")
    mp.add_argument("--json", action="store_true")
    mp.set_defaults(func=cmd_mcp)
    mp = mcp_sub.add_parser("status")
    mp.add_argument("--json", action="store_true")
    mp.set_defaults(func=cmd_mcp)
    mp = mcp_sub.add_parser("daemon-status")
    mp.add_argument("server", nargs="?")
    mp.add_argument("--json", action="store_true")
    mp.set_defaults(func=cmd_mcp)
    mp = mcp_sub.add_parser("daemon-start")
    mp.add_argument("server", nargs="?")
    mp.add_argument("--json", action="store_true")
    mp.set_defaults(func=cmd_mcp)
    mp = mcp_sub.add_parser("daemon-stop")
    mp.add_argument("server", nargs="?")
    mp.add_argument("--json", action="store_true")
    mp.set_defaults(func=cmd_mcp)
    mp = mcp_sub.add_parser("daemon-cleanup")
    mp.add_argument("--max-age-seconds", type=float, default=None)
    mp.set_defaults(func=cmd_mcp)
    mp = mcp_sub.add_parser("gateway-start")
    mp.add_argument("server", nargs="?")
    mp.add_argument("--no-discover", action="store_true")
    mp.add_argument("--json", action="store_true")
    mp.set_defaults(func=cmd_mcp)
    mp = mcp_sub.add_parser("gateway-stop")
    mp.add_argument("server", nargs="?")
    mp.add_argument("--json", action="store_true")
    mp.set_defaults(func=cmd_mcp)
    mp = mcp_sub.add_parser("gateway-status")
    mp.add_argument("--json", action="store_true")
    mp.set_defaults(func=cmd_mcp)
    mp = mcp_sub.add_parser("gateway-refresh")
    mp.add_argument("server", nargs="?")
    mp.add_argument("--no-discover", action="store_true")
    mp.add_argument("--json", action="store_true")
    mp.set_defaults(func=cmd_mcp)
    mp = mcp_sub.add_parser("gateway-health")
    mp.add_argument("--json", action="store_true")
    mp.set_defaults(func=cmd_mcp)
    mp = mcp_sub.add_parser("gateway-call")
    mp.add_argument("server")
    mp.add_argument("tool")
    mp.add_argument("--args-json", default="{}")
    mp.add_argument("--approval-id", default=None)
    mp.add_argument("--approve", action="store_true")
    mp.add_argument("--agent-profile", default=None)
    mp.add_argument("--json", action="store_true")
    mp.set_defaults(func=cmd_mcp)
    mp = mcp_sub.add_parser("cleanup")
    mp.set_defaults(func=cmd_mcp)

    p = sub.add_parser("subagent")
    add_project(p)
    subagent_sub = p.add_subparsers(dest="subagent_command", required=True)
    sp = subagent_sub.add_parser("start")
    sp.add_argument("task")
    sp.add_argument("--parent-task-id", default=None)
    sp.add_argument("--context-mode", default="fork", choices=["fork", "isolated"])
    sp.add_argument("--profile", default="build", help="Agent profile to pass into the child runtime")
    sp.add_argument("--permission-mode", default="", help="Child permission mode such as plan/build/auto/bypass")
    sp.add_argument("--model", default="")
    sp.add_argument("--effort", default="")
    sp.add_argument("--tool", action="append", default=[])
    sp.add_argument("--disallow-tool", action="append", default=[])
    sp.add_argument("--mcp-server", action="append", default=[])
    sp.add_argument("--hook", action="append", default=[])
    sp.add_argument("--skill", action="append", default=[])
    sp.add_argument("--foreground", action="store_true", help="Mark child as foreground instead of background")
    sp.add_argument("--title", default=None)
    sp.add_argument("--no-validation", action="store_true")
    sp.add_argument("--isolate-worktree", action="store_true", help="Run the child agent against an isolated worktree copy")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_subagent)
    sp = subagent_sub.add_parser("list")
    sp.add_argument("--refresh", action="store_true")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_subagent)
    sp = subagent_sub.add_parser("show")
    sp.add_argument("subagent_id")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_subagent)
    sp = subagent_sub.add_parser("stop")
    sp.add_argument("subagent_id")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_subagent)
    sp = subagent_sub.add_parser("bundle")
    sp.add_argument("--parent-task-id", default=None)
    sp.add_argument("--subagent-id", action="append")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_subagent)
    sp = subagent_sub.add_parser("bundles")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_subagent)
    sp = subagent_sub.add_parser("backends")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_subagent)

    p = sub.add_parser("edit")
    add_project(p)
    edit_sub = p.add_subparsers(dest="edit_command", required=True)
    ep = edit_sub.add_parser("plan")
    ep.add_argument("task")
    ep.add_argument("--path", action="append")
    ep.add_argument("--test", nargs=argparse.REMAINDER)
    ep.add_argument("--max-attempts", type=int, default=3)
    ep.add_argument("--out", default=None)
    ep.set_defaults(func=cmd_edit)
    ep = edit_sub.add_parser("run")
    ep.add_argument("plan_json")
    ep.add_argument("--apply", action="store_true", help="Apply an already reviewed plan")
    ep.add_argument("--timeout", type=int, default=120)
    ep.add_argument("--agent-profile", default=None, help="Apply an agent permission matrix before editing")
    ep.set_defaults(func=cmd_edit)
    ep = edit_sub.add_parser("auto")
    ep.add_argument("task")
    ep.add_argument("path")
    ep.add_argument("--old", required=True)
    ep.add_argument("--new", required=True)
    ep.add_argument("--expected-count", type=int, default=1)
    ep.add_argument("--test", nargs=argparse.REMAINDER)
    ep.add_argument("--max-rounds", type=int, default=2)
    ep.add_argument("--timeout", type=int, default=120)
    ep.add_argument("--apply", action="store_true", help="Apply after the generated diff has been reviewed")
    ep.add_argument("--reviewed", action="store_true", help="Confirm that the generated diff preview was reviewed")
    ep.add_argument("--agent-profile", default=None, help="Apply an agent permission matrix before editing")
    ep.add_argument("--json", action="store_true")
    ep.set_defaults(func=cmd_edit)
    ep = edit_sub.add_parser("repair")
    ep.add_argument("plan_json")
    ep.add_argument("--failure", default="")
    ep.add_argument("--failure-file", default=None)
    ep.add_argument("--model", default=None)
    ep.add_argument("--base-url", default=None)
    ep.add_argument("--isolated-loop", action="store_true", help="Run model repair candidates inside an isolated worktree until tests pass or retry limit is hit")
    ep.add_argument("--workers", type=int, default=1, help="Run multiple isolated repair workers and rank their review bundles")
    ep.add_argument("--max-rounds", type=int, default=3)
    ep.add_argument("--timeout", type=int, default=120)
    ep.add_argument("--agent-profile", default=None, help="Apply an agent permission matrix to worker diff previews")
    ep.add_argument("--json", action="store_true")
    ep.set_defaults(func=cmd_edit)

    p = sub.add_parser("repo-map")
    add_project(p)
    repo_map_sub = p.add_subparsers(dest="repo_map_command", required=True)
    rp = repo_map_sub.add_parser("build")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_repo_map)
    rp = repo_map_sub.add_parser("show")
    rp.add_argument("--max-files", type=int, default=80)
    rp.add_argument("--rebuild", action="store_true")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_repo_map)
    rp = repo_map_sub.add_parser("search")
    rp.add_argument("query")
    rp.add_argument("--limit", type=int, default=8)
    rp.add_argument("--rebuild", action="store_true")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_repo_map)
    rp = repo_map_sub.add_parser("related")
    rp.add_argument("path")
    rp.add_argument("--limit", type=int, default=8)
    rp.add_argument("--rebuild", action="store_true")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_repo_map)
    rp = repo_map_sub.add_parser("context")
    rp.add_argument("query")
    rp.add_argument("--budget-chars", type=int, default=6000)
    rp.add_argument("--rebuild", action="store_true")
    rp.set_defaults(func=cmd_repo_map)

    p = sub.add_parser("index")
    add_project(p)
    index_sub = p.add_subparsers(dest="index_command", required=True)
    ip = index_sub.add_parser("build")
    ip.set_defaults(func=cmd_index)
    ip = index_sub.add_parser("search")
    ip.add_argument("query")
    ip.add_argument("--limit", type=int, default=8)
    ip.add_argument("--rebuild", action="store_true")
    ip.add_argument("--json", action="store_true")
    ip.set_defaults(func=cmd_index)
    ip = index_sub.add_parser("related")
    ip.add_argument("path")
    ip.add_argument("--limit", type=int, default=8)
    ip.add_argument("--rebuild", action="store_true")
    ip.add_argument("--json", action="store_true")
    ip.set_defaults(func=cmd_index)
    ip = index_sub.add_parser("editor-diagnostics")
    ip.add_argument("--limit", type=int, default=200)
    ip.add_argument("--json", action="store_true")
    ip.set_defaults(func=cmd_index)
    ip = index_sub.add_parser("diagnose")
    ip.add_argument("--rebuild", action="store_true")
    ip.add_argument("--editor-diagnostics", action="store_true", help="Include lightweight syntax/TODO/import diagnostics")
    ip.add_argument("--json", action="store_true")
    ip.set_defaults(func=cmd_index)

    p = sub.add_parser("retrieval")
    add_project(p)
    retrieval_sub = p.add_subparsers(dest="retrieval_command", required=True)
    rp = retrieval_sub.add_parser("build")
    rp.add_argument("--rebuild-code-index", action="store_true")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_retrieval)
    rp = retrieval_sub.add_parser("ensure")
    rp.add_argument("--rebuild", action="store_true")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_retrieval)
    rp = retrieval_sub.add_parser("search")
    rp.add_argument("query")
    rp.add_argument("--limit", type=int, default=8)
    rp.add_argument("--seed-path", action="append", default=[])
    rp.add_argument("--rebuild", action="store_true")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_retrieval)
    rp = retrieval_sub.add_parser("related")
    rp.add_argument("path", nargs="+")
    rp.add_argument("--limit", type=int, default=8)
    rp.add_argument("--rebuild", action="store_true")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_retrieval)
    rp = retrieval_sub.add_parser("start")
    rp.add_argument("--rebuild", action="store_true")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_retrieval)
    rp = retrieval_sub.add_parser("stop")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_retrieval)
    rp = retrieval_sub.add_parser("status")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_retrieval)
    rp = retrieval_sub.add_parser("health")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_retrieval)

    p = sub.add_parser("eval")
    add_project(p)
    eval_sub = p.add_subparsers(dest="eval_command", required=True)
    ep = eval_sub.add_parser("list")
    ep.add_argument("--builtin", action="store_true")
    ep.add_argument("--builtin-code", action="store_true", help="Include the built-in programming-agent eval pack")
    ep.add_argument("--tag", action="append", default=[])
    ep.add_argument("--json", action="store_true")
    ep.set_defaults(func=cmd_eval)
    ep = eval_sub.add_parser("run")
    ep.add_argument("--builtin", action="store_true")
    ep.add_argument("--builtin-code", action="store_true", help="Include the built-in programming-agent eval pack")
    ep.add_argument("--tag", action="append", default=[])
    ep.add_argument("--json", action="store_true")
    ep.set_defaults(func=cmd_eval)
    ep = eval_sub.add_parser("once")
    ep.add_argument("--builtin", action="store_true")
    ep.add_argument("--builtin-code", action="store_true", help="Include the built-in programming-agent eval pack")
    ep.add_argument("--tag", action="append", default=[])
    ep.add_argument("--json", action="store_true")
    ep.set_defaults(func=cmd_eval)
    ep = eval_sub.add_parser("scorecard")
    ep.add_argument("--json", action="store_true")
    ep.set_defaults(func=cmd_eval)

    p = sub.add_parser("code-eval", help="Run local issue-to-patch programming fixtures")
    add_project(p)
    p.add_argument("--json", action="store_true")
    code_eval_sub = p.add_subparsers(dest="code_eval_command", required=True)
    cp = code_eval_sub.add_parser("list")
    cp.add_argument("--fixture", action="append", default=[], help="Only include this fixture id; repeatable")
    cp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    cp.set_defaults(func=cmd_code_eval)
    cp = code_eval_sub.add_parser("run")
    cp.add_argument("--all", action="store_true", help="Run all fixtures")
    cp.add_argument("--fixture", action="append", default=[], help="Only run this fixture id; repeatable")
    cp.add_argument("--no-oracle", action="store_true", help="Only verify initial failing state; do not apply oracle patch")
    cp.add_argument("--clean", action="store_true", help="Delete generated fixture workspaces after the run")
    cp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    cp.set_defaults(func=cmd_code_eval)
    cp = code_eval_sub.add_parser("solve")
    cp.add_argument("--all", action="store_true", help="Solve all fixtures")
    cp.add_argument("--fixture", action="append", default=[], help="Only solve this fixture id; repeatable")
    cp.add_argument("--model", default="", help="Model for the isolated repair loop")
    cp.add_argument("--base-url", default="", help="Model API base URL")
    cp.add_argument("--max-rounds", type=int, default=2)
    cp.add_argument("--clean", action="store_true", help="Delete generated fixture workspaces after the run")
    cp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    cp.set_defaults(func=cmd_code_eval)

    p = sub.add_parser("coding-bench", help="Benchmark an external coding agent against broken fixture workspaces")
    add_project(p)
    p.add_argument("--json", action="store_true")
    p.add_argument("--task-file", default="", help="JSON task file; defaults to built-in 30-task pack")
    p.add_argument("--limit", type=int, default=None, help="Limit tasks for a smoke run")
    coding_bench_sub = p.add_subparsers(dest="coding_bench_command", required=True)
    bp = coding_bench_sub.add_parser("list")
    bp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    bp.set_defaults(func=cmd_coding_bench)
    bp = coding_bench_sub.add_parser("run")
    agent_group = bp.add_mutually_exclusive_group(required=True)
    agent_group.add_argument("--agent-command", help="Shell command template. Placeholders: {workspace}, {instruction}, {task_id}, {attempt}, {failure_file}, {python}")
    agent_group.add_argument("--agent", choices=["openmako"], help="Deprecated fail-closed alias; use --agent-command")
    bp.add_argument("--repeats", type=int, default=1, help="Repeat the same task pack to measure run-to-run stability")
    bp.add_argument("--keep-workspaces", action="store_true", help="Preserve generated failing workspaces under .quantagent/coding_bench")
    bp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    bp.set_defaults(func=cmd_coding_bench)

    p = sub.add_parser("learning-effect", help="Compare no-learning and approved-learning command outcomes")
    add_project(p)
    p.add_argument("--json", action="store_true")
    learning_effect_sub = p.add_subparsers(dest="learning_effect_command", required=True)
    lp = learning_effect_sub.add_parser("run")
    lp.add_argument("--project", dest="learning_effect_project", default="", help="Quant project path")
    lp.add_argument("--task-file", default="", help="Learning-effect task JSON file")
    lp.add_argument("--tasks", dest="tasks_file", default="", help="Alias for --task-file")
    lp.add_argument("--bench-task-file", default="", help="CodingBench task JSON file for adapter mode")
    lp.add_argument("--limit", type=int, default=None, help="Limit CodingBench adapter tasks")
    lp.add_argument("--coding-bench", action="store_true", help="Use CodingBench task adapter")
    lp.add_argument("--no-learning-command", default="", help="Shell command template for the no-learning baseline")
    lp.add_argument("--approved-learning-command", default="", help="Shell command template for the approved-learning run")
    lp.add_argument("--agent-command", dest="agent_command_alias", default="", help="Compatibility alias for --approved-learning-command")
    lp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    lp.set_defaults(func=cmd_learning_effect)

    p = sub.add_parser("swarm", help="Run isolated worker candidates and produce a parent battle report")
    add_project(p)
    p.add_argument("--task", dest="task_option", default="", help="Task text; positional words are also accepted")
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--repair-plan", default=None, help="Patch plan JSON; when set, run concurrent isolated repair loops instead of command workers")
    p.add_argument("--failure", default="", help="Failure text for --repair-plan mode")
    p.add_argument("--failure-file", default=None, help="Read failure text from a file for --repair-plan mode")
    p.add_argument("--model", default=None, help="Model for --repair-plan repair workers")
    p.add_argument("--base-url", default=None, help="Model API base URL for --repair-plan repair workers")
    p.add_argument("--max-rounds", type=int, default=3, help="Max isolated repair rounds per worker in --repair-plan mode")
    p.add_argument("--worker-command", default=None, help="Command template for each worker; placeholders: {task}, {task_text}, {worker_id}, {worker_index}, {workspace}, {run_id}")
    p.add_argument("--no-default-worker", action="store_true", help="Skip the built-in agent-v3 worker command when --worker-command is omitted")
    p.add_argument("--test", default=None, help="Validation command template run inside each worker worktree")
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--sandbox-backend", default="auto", choices=["auto", "sandbox-exec", "worktree", "host"])
    p.add_argument("--network", action="store_true")
    p.add_argument("--allow-risky-worker", action="store_true", help="Allow guarded write commands inside isolated worker worktrees")
    p.add_argument("--allow-risky-test", action="store_true", help="Allow guarded validation commands inside isolated worker worktrees")
    p.add_argument("--agent-profile", default="build")
    p.add_argument("--json", action="store_true")
    p.add_argument("task", nargs="*")
    p.set_defaults(func=cmd_swarm)

    p = sub.add_parser("arbitrate")
    add_project(p)
    p.add_argument("review_id", nargs="*")
    p.add_argument("--agent-profile", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_arbitrate)

    p = sub.add_parser("lsp")
    add_project(p)
    lsp_sub = p.add_subparsers(dest="lsp_command", required=True)
    lp = lsp_sub.add_parser("status")
    lp.add_argument("--json", action="store_true")
    lp.set_defaults(func=cmd_lsp)
    lp = lsp_sub.add_parser("run")
    lp.add_argument("path", nargs="+")
    lp.add_argument("--timeout", type=float, default=5.0)
    lp.add_argument("--json", action="store_true")
    lp.set_defaults(func=cmd_lsp)
    lp = lsp_sub.add_parser("cache")
    lp.add_argument("--json", action="store_true")
    lp.set_defaults(func=cmd_lsp)

    p = sub.add_parser("embeddings")
    add_project(p)
    embeddings_sub = p.add_subparsers(dest="embeddings_command", required=True)

    def add_embedding_provider_args(ep: argparse.ArgumentParser) -> None:
        ep.add_argument("--provider", choices=["local", "openai", "sentence-transformers"], default="local")
        ep.add_argument("--model", default=None)
        ep.add_argument("--dimensions", type=int, default=64)
        ep.add_argument("--json", action="store_true")

    ep = embeddings_sub.add_parser("status")
    add_embedding_provider_args(ep)
    ep.set_defaults(func=cmd_embeddings)
    ep = embeddings_sub.add_parser("embed")
    add_embedding_provider_args(ep)
    ep.add_argument("text", nargs="*")
    ep.add_argument("--text-file", action="append", default=[])
    ep.set_defaults(func=cmd_embeddings)
    ep = embeddings_sub.add_parser("cache-path")
    ep.set_defaults(func=cmd_embeddings)

    p = sub.add_parser("mcp-daemon")
    add_project(p)
    mcp_daemon_sub = p.add_subparsers(dest="mcp_daemon_command", required=True)
    dp = mcp_daemon_sub.add_parser("start")
    dp.add_argument("--json", action="store_true")
    dp.set_defaults(func=cmd_mcp_daemon)
    dp = mcp_daemon_sub.add_parser("status")
    dp.add_argument("--json", action="store_true")
    dp.set_defaults(func=cmd_mcp_daemon)
    dp = mcp_daemon_sub.add_parser("stop")
    dp.add_argument("--json", action="store_true")
    dp.set_defaults(func=cmd_mcp_daemon)
    dp = mcp_daemon_sub.add_parser("restart")
    dp.add_argument("--json", action="store_true")
    dp.set_defaults(func=cmd_mcp_daemon)
    dp = mcp_daemon_sub.add_parser("recover")
    dp.add_argument("--json", action="store_true")
    dp.set_defaults(func=cmd_mcp_daemon)
    dp = mcp_daemon_sub.add_parser("catalog")
    dp.add_argument("--refresh", action="store_true")
    dp.set_defaults(func=cmd_mcp_daemon)
    dp = mcp_daemon_sub.add_parser("call")
    dp.add_argument("server")
    dp.add_argument("tool")
    dp.add_argument("--args-json", default="{}")
    dp.add_argument("--approval-id", default=None)
    dp.add_argument("--approve", action="store_true")
    dp.add_argument("--agent-profile", default=None)
    dp.set_defaults(func=cmd_mcp_daemon)
    dp = mcp_daemon_sub.add_parser("request")
    dp.add_argument("method")
    dp.add_argument("--params-json", default="{}")
    dp.add_argument("--timeout", type=float, default=3.0)
    dp.set_defaults(func=cmd_mcp_daemon)
    dp = mcp_daemon_sub.add_parser("serve")
    dp.set_defaults(func=cmd_mcp_daemon)

    p = sub.add_parser("checkpoint")
    add_project(p)
    checkpoint_sub = p.add_subparsers(dest="checkpoint_command", required=True)
    cp = checkpoint_sub.add_parser("create")
    cp.add_argument("path", nargs="+")
    cp.add_argument("--task-id", default=None)
    cp.add_argument("--plan-id", default=None)
    cp.add_argument("--reason", default=None)
    cp.add_argument("--json", action="store_true")
    cp.set_defaults(func=cmd_checkpoint)
    cp = checkpoint_sub.add_parser("list")
    cp.add_argument("--limit", type=int, default=20)
    cp.add_argument("--json", action="store_true")
    cp.set_defaults(func=cmd_checkpoint)
    cp = checkpoint_sub.add_parser("show")
    cp.add_argument("checkpoint_id")
    cp.add_argument("--include-text", action="store_true")
    cp.add_argument("--json", action="store_true")
    cp.set_defaults(func=cmd_checkpoint)
    cp = checkpoint_sub.add_parser("restore")
    cp.add_argument("checkpoint_id")
    cp.add_argument("--json", action="store_true")
    cp.set_defaults(func=cmd_checkpoint)

    p = sub.add_parser("transcript")
    add_project(p)
    transcript_sub = p.add_subparsers(dest="transcript_command", required=True)
    tp = transcript_sub.add_parser("list")
    tp.add_argument("--limit", type=int, default=30)
    tp.add_argument("--json", action="store_true")
    tp.set_defaults(func=cmd_transcript)

    p = sub.add_parser("agent-profile")
    add_project(p)
    agent_profile_sub = p.add_subparsers(dest="agent_profile_command", required=True)
    gp = agent_profile_sub.add_parser("list")
    gp.add_argument("--json", action="store_true")
    gp.set_defaults(func=cmd_agent_profile)
    gp = agent_profile_sub.add_parser("show")
    gp.add_argument("name")
    gp.add_argument("--json", action="store_true")
    gp.set_defaults(func=cmd_agent_profile)
    gp = agent_profile_sub.add_parser("check")
    gp.add_argument("name")
    gp.add_argument("tool")
    gp.add_argument("--args-json", default="{}")
    gp.add_argument("--reason", default=None)
    gp.add_argument("--approve", action="store_true")
    gp.add_argument("--json", action="store_true")
    gp.set_defaults(func=cmd_agent_profile)
    gp = agent_profile_sub.add_parser("instructions")
    gp.add_argument("--show", action="store_true")
    gp.add_argument("--json", action="store_true")
    gp.set_defaults(func=cmd_agent_profile)
    tp = transcript_sub.add_parser("show")
    tp.add_argument("invocation_id")
    tp.add_argument("--json", action="store_true")
    tp.set_defaults(func=cmd_transcript)

    p = sub.add_parser("tool-call-trace")
    add_project(p)
    trace_sub = p.add_subparsers(dest="trace_command", required=True)
    tp = trace_sub.add_parser("list")
    tp.add_argument("--limit", type=int, default=30)
    tp.add_argument("--json", action="store_true")
    tp.set_defaults(func=cmd_tool_call_trace)
    tp = trace_sub.add_parser("show")
    tp.add_argument("invocation_id")
    tp.add_argument("--json", action="store_true")
    tp.set_defaults(func=cmd_tool_call_trace)

    p = sub.add_parser("modes")
    add_project(p)
    modes_sub = p.add_subparsers(dest="modes_command", required=True)
    mp = modes_sub.add_parser("list")
    mp.add_argument("--json", action="store_true")
    mp.set_defaults(func=cmd_modes)
    mp = modes_sub.add_parser("show")
    mp.add_argument("name")
    mp.add_argument("--json", action="store_true")
    mp.set_defaults(func=cmd_modes)
    mp = modes_sub.add_parser("evaluate")
    mp.add_argument("name")
    mp.add_argument("tool")
    mp.add_argument("--approve", action="store_true")
    mp.add_argument("--json", action="store_true")
    mp.set_defaults(func=cmd_modes)
    mp = modes_sub.add_parser("tools")
    mp.add_argument("name")
    mp.add_argument("--json", action="store_true")
    mp.set_defaults(func=cmd_modes)
    mp = modes_sub.add_parser("lint")
    mp.add_argument("--json", action="store_true")
    mp.set_defaults(func=cmd_modes)

    p = sub.add_parser("resume")
    add_project(p)
    resume_sub = p.add_subparsers(dest="resume_command", required=True)
    rp = resume_sub.add_parser("last-failure")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_resume)
    rp = resume_sub.add_parser("task")
    rp.add_argument("task_id")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_resume)
    rp = resume_sub.add_parser("agent")
    rp.add_argument("subagent_id", nargs="?")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_resume)
    rp = resume_sub.add_parser("session")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_resume)
    rp = resume_sub.add_parser("compact")
    rp.add_argument("kind", choices=["session", "task", "agent"])
    rp.add_argument("source_id", nargs="?")
    rp.add_argument("--target-chars", type=int, default=2200)
    rp.add_argument("--auto", action="store_true", help="Mark the snapshot as automatically generated")
    rp.add_argument("--include-body", action="store_true")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_resume)
    rp = resume_sub.add_parser("list")
    rp.add_argument("--limit", type=int, default=20)
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_resume)
    rp = resume_sub.add_parser("show")
    rp.add_argument("snapshot_id")
    rp.add_argument("--include-body", action="store_true")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_resume)
    p = sub.add_parser("isolation")
    add_project(p)
    p.add_argument("--json", action="store_true")
    isolation_sub = p.add_subparsers(dest="isolation_command", required=True)
    ip = isolation_sub.add_parser("create")
    ip.add_argument("--reason", default=None)
    ip.add_argument("--include", action="append")
    ip.set_defaults(func=cmd_isolation)
    ip = isolation_sub.add_parser("list")
    ip.add_argument("--limit", type=int, default=20)
    ip.set_defaults(func=cmd_isolation)
    ip = isolation_sub.add_parser("show")
    ip.add_argument("worktree_id")
    ip.set_defaults(func=cmd_isolation)
    ip = isolation_sub.add_parser("run")
    ip.add_argument("--worktree-id", default=None)
    ip.add_argument("--timeout", type=int, default=120)
    ip.add_argument("--allow-risky", action="store_true")
    ip.add_argument("--reason", default=None)
    ip.add_argument("--sandbox-backend", default="auto", choices=["auto", "sandbox-exec", "worktree", "host"], help="Command sandbox backend for the isolated run")
    ip.add_argument("--network", action="store_true", help="Allow network when the selected sandbox backend can enforce that policy")
    ip.add_argument("command", nargs=argparse.REMAINDER)
    ip.set_defaults(func=cmd_isolation)
    ip = isolation_sub.add_parser("remove")
    ip.add_argument("worktree_id")
    ip.set_defaults(func=cmd_isolation)
    ip = isolation_sub.add_parser("review")
    ip.add_argument("worktree_id")
    ip.add_argument("--diff", action="store_true")
    ip.set_defaults(func=cmd_isolation)
    ip = isolation_sub.add_parser("show-review")
    ip.add_argument("review_id")
    ip.add_argument("--diff", action="store_true")
    ip.set_defaults(func=cmd_isolation)
    ip = isolation_sub.add_parser("apply-review")
    ip.add_argument("review_id")
    ip.add_argument("--reviewed", action="store_true", help="Required to merge isolated changes back into the source project")
    ip.set_defaults(func=cmd_isolation)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    subcommands = {
        "status",
        "watch",
        "agent-autopsy",
        "evidence-court",
        "hooks",
        "rules",
        "audit",
        "quant",
        "judge",
        "report",
        "context",
        "cheap",
        "architect",
        "pr",
        "runner",
        "query-events",
        "ux",
        "tui-model",
        "tools",
        "event-log",
        "tool-manifest",
        "policy-v2",
        "channel",
        "relay",
        "task-graph",
        "runtime",
        "skill-pipeline",
        "skills",
        "safety",
        "validate",
        "checks",
        "doctor",
        "onboard",
        "state",
        "todo",
        "review",
        "consensus",
        "loop",
        "model-test",
        "ask",
        "fix",
        "demo",
        "chat",
        "experiment",
        "registry",
        "run-p4",
        "run-next",
        "agent",
        "agent-supervisor",
        "agent-v2",
        "agent-v3",
        "goal-contract",
        "evidence",
        "answer-guard",
        "better-option",
        "headless",
        "mode-router",
        "agent-context",
        "agent-gateway",
        "session",
        "session-bus",
        "task",
        "tasks",
        "desktop",
        "desktop-agent",
        "desktop-overnight",
        "desktop-daemon",
        "desktop-eval",
        "files",
        "memory",
        "edit-loop",
        "toolsets",
        "sandbox",
        "plugins",
        "ecosystem",
        "permissions",
        "diagnostics",
        "compact-budget",
        "diff-preview",
        "apply-gate",
        "approval",
        "mcp",
        "subagent",
        "edit",
        "repo-map",
        "index",
        "retrieval",
        "eval",
        "code-eval",
        "coding-bench",
        "learning-effect",
        "swarm",
        "arbitrate",
        "lsp",
        "embeddings",
        "mcp-daemon",
        "checkpoint",
        "transcript",
        "tool-call-trace",
        "agent-profile",
        "modes",
        "resume",
        "isolation",
    }
    global_flags = {"--trust-workspace", "--no-trust-prompt"}
    leading_flags: list[str] = []
    while argv and argv[0] in global_flags:
        leading_flags.append(argv.pop(0))
    if not argv:
        argv = [*leading_flags, "chat"]
    elif argv[0].startswith("-") and argv[0] not in {"-h", "--help", "--version"}:
        argv = [*leading_flags, "chat", *argv]
    elif argv[0] not in subcommands and argv[0] not in {"-h", "--help", "--version"}:
        argv = [*leading_flags, "chat", "--once", " ".join(argv)]
    else:
        argv = [*leading_flags, *argv]
    parser = build_parser()
    args = parser.parse_args(argv)
    if _requires_workspace_trust(args):
        config = load_config(getattr(args, "project", None))
        trusted = ensure_workspace_trusted(
            config.project,
            assume_yes=bool(getattr(args, "trust_workspace", False)),
            disabled=bool(getattr(args, "no_trust_prompt", False)),
        )
        if not trusted:
            print("Exited before accessing workspace.", file=sys.stderr)
            return 130
    return args.func(args)


def _requires_workspace_trust(args: argparse.Namespace) -> bool:
    command = getattr(args, "command", "")
    if command in {"tools", "toolsets", "sandbox"}:
        return False
    if command == "skills" and not getattr(args, "project", None) and not getattr(args, "install", None):
        return False
    return hasattr(args, "project")


if __name__ == "__main__":
    raise SystemExit(main())
