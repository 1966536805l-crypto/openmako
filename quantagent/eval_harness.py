from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import hashlib
import json
import os
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


PASS = "pass"
FAIL = "fail"
ERROR = "error"
SHELL = "shell"
DEFAULT_PREVIEW_CHARS = 4000
DEFAULT_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class EvalCase:
    id: str
    name: str
    type: str = SHELL
    command: str = ""
    expected_returncode: int = 0
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    weight: int = 1
    cwd: str = ""
    tags: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvalCase":
        case_id = str(payload.get("id") or payload.get("name") or "").strip()
        if not case_id:
            raise ValueError("eval case requires id or name")
        case_type = str(payload.get("type", SHELL))
        if case_type != SHELL:
            raise ValueError(f"unsupported eval case type: {case_type}")
        command = str(payload.get("command") or "")
        if not command:
            raise ValueError(f"eval case {case_id!r} requires command")
        env_payload = payload.get("env") or {}
        if not isinstance(env_payload, dict):
            raise ValueError(f"eval case {case_id!r} env must be an object")
        tags_payload = payload.get("tags") or []
        if not isinstance(tags_payload, list):
            raise ValueError(f"eval case {case_id!r} tags must be a list")
        return cls(
            id=case_id,
            name=str(payload.get("name") or case_id),
            type=case_type,
            command=command,
            expected_returncode=int(payload.get("expected_returncode", 0)),
            timeout_seconds=float(payload.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)),
            weight=int(payload.get("weight", 1)),
            cwd=str(payload.get("cwd") or ""),
            tags=[str(tag) for tag in tags_payload],
            env={str(key): str(value) for key, value in env_payload.items()},
        )


@dataclass(frozen=True)
class EvalResult:
    case_id: str
    name: str
    type: str
    classification: str
    score: int
    max_score: int
    returncode: int | None = None
    stdout_preview: str = ""
    stderr_preview: str = ""
    duration_ms: int = 0
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvalRun:
    run_id: str
    project: str
    started_at: str
    finished_at: str
    results: list[EvalResult]
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["summary"] = score_eval_run(self)
        return payload

    def to_json(self) -> str:
        return render_eval_json(self)


def evals_dir(project: Path) -> Path:
    return project / ".quantagent" / "evals"


def load_eval_cases(project: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    root = evals_dir(project)
    if not root.exists():
        return cases
    for path in sorted(root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in _case_payloads(payload, path):
            cases.append(EvalCase.from_dict(item))
    return cases


def builtin_smoke_eval_cases() -> list[EvalCase]:
    return [
        EvalCase(
            id="py_compile_quantagent",
            name="py_compile quantagent package",
            command="python3 -m py_compile quantagent/__init__.py",
            tags=["builtin", "smoke"],
        ),
        EvalCase(
            id="qagent_doctor_help",
            name="mako doctor command is reachable",
            command="python3 -m quantagent.cli doctor --help",
            tags=["builtin", "smoke"],
        ),
    ]


def builtin_code_eval_cases() -> list[EvalCase]:
    return [
        EvalCase(
            id="code_py_compile_edit_loop",
            name="edit loop imports cleanly",
            command="python3 -m py_compile quantagent/edit_loop.py",
            tags=["builtin", "code", "compile", "edit"],
        ),
        EvalCase(
            id="code_py_compile_apply_gate",
            name="apply gate imports cleanly",
            command="python3 -m py_compile quantagent/apply_gate.py",
            tags=["builtin", "code", "compile", "apply"],
        ),
        EvalCase(
            id="code_py_compile_worktree",
            name="worktree isolation imports cleanly",
            command="python3 -m py_compile quantagent/worktree_isolation.py",
            tags=["builtin", "code", "compile", "isolation"],
        ),
        EvalCase(
            id="code_py_compile_code_index",
            name="code index imports cleanly",
            command="python3 -m py_compile quantagent/code_index.py",
            tags=["builtin", "code", "compile", "context"],
        ),
        EvalCase(
            id="code_py_compile_retrieval",
            name="retrieval daemon imports cleanly",
            command="python3 -m py_compile quantagent/retrieval_daemon.py",
            tags=["builtin", "code", "compile", "retrieval"],
        ),
        EvalCase(
            id="code_py_compile_supervisor",
            name="agent supervisor imports cleanly",
            command="python3 -m py_compile quantagent/agent_supervisor.py quantagent/swarm.py",
            tags=["builtin", "code", "compile", "orchestration"],
        ),
        EvalCase(
            id="code_eval_harness_contract",
            name="eval harness contract",
            command="python3 -m unittest tests.test_eval_harness.EvalHarnessTest.test_builtin_smoke_cases_are_shell_cases",
            tags=["builtin", "code", "eval"],
        ),
        EvalCase(
            id="code_index_symbol_search",
            name="code index symbol search",
            command="python3 -m unittest tests.test_code_index_checkpoint.CodeIndexCheckpointTest.test_bm25_code_index_finds_symbols",
            tags=["builtin", "code", "context"],
        ),
        EvalCase(
            id="code_index_dependency_graph",
            name="code index dependency graph",
            command="python3 -m unittest tests.test_code_index_checkpoint.CodeIndexCheckpointTest.test_dependency_graph_lists_imports_by_file",
            tags=["builtin", "code", "context"],
        ),
        EvalCase(
            id="code_index_diagnostics",
            name="editor diagnostics classify repair signals",
            command="python3 -m unittest tests.test_code_index_checkpoint.CodeIndexCheckpointTest.test_editor_diagnostics_detects_syntax_todo_and_unresolved_import",
            tags=["builtin", "code", "diagnostics"],
        ),
        EvalCase(
            id="code_retrieval_search",
            name="retrieval search returns relevant files",
            command="python3 -m unittest tests.test_retrieval_daemon.RetrievalDaemonTest.test_retrieval_search_returns_relevant_file_with_reasons",
            tags=["builtin", "code", "retrieval"],
        ),
        EvalCase(
            id="code_edit_retry",
            name="edit loop retries candidates until tests pass",
            command="python3 -m unittest tests.test_edit_loop.EditLoopTest.test_retries_candidates_until_test_passes",
            timeout_seconds=90,
            tags=["builtin", "code", "edit", "repair"],
        ),
        EvalCase(
            id="code_change_set_multi_file",
            name="change set applies multi-file candidate",
            command="python3 -m unittest tests.test_edit_loop.EditLoopTest.test_change_set_applies_multiple_files_and_keeps_passing_candidate",
            timeout_seconds=90,
            tags=["builtin", "code", "edit", "multi-file"],
        ),
        EvalCase(
            id="code_patch_plan_context",
            name="patch plan includes repo context",
            command="python3 -m unittest tests.test_edit_loop.EditLoopTest.test_patch_plan_includes_repo_map_context",
            timeout_seconds=90,
            tags=["builtin", "code", "planning", "context"],
        ),
        EvalCase(
            id="code_unified_diff_apply",
            name="unified diff preview and apply",
            command="python3 -m unittest tests.test_edit_loop.EditLoopTest.test_unified_diff_preview_and_apply",
            timeout_seconds=90,
            tags=["builtin", "code", "diff", "apply"],
        ),
        EvalCase(
            id="code_auto_patch_gate",
            name="auto patch requires review before apply",
            command="python3 -m unittest tests.test_edit_loop.EditLoopTest.test_auto_patch_requires_review_before_apply",
            timeout_seconds=90,
            tags=["builtin", "code", "apply", "safety"],
        ),
        EvalCase(
            id="code_isolated_repair_review",
            name="isolated repair loop creates review",
            command="python3 -m unittest tests.test_edit_loop.EditLoopTest.test_isolated_repair_loop_applies_candidate_in_copy_and_creates_review",
            timeout_seconds=120,
            tags=["builtin", "code", "repair", "isolation"],
        ),
        EvalCase(
            id="code_worktree_copy",
            name="isolated worktree copies project files",
            command="python3 -m unittest tests.test_worktree_isolation.WorktreeIsolationTest.test_create_isolated_worktree_copies_project_files",
            timeout_seconds=90,
            tags=["builtin", "code", "isolation"],
        ),
        EvalCase(
            id="code_worktree_no_source_mutation",
            name="isolated run does not mutate source project",
            command="python3 -m unittest tests.test_worktree_isolation.WorktreeIsolationTest.test_isolated_run_does_not_modify_source_project",
            timeout_seconds=90,
            tags=["builtin", "code", "isolation", "safety"],
        ),
        EvalCase(
            id="code_worktree_review",
            name="isolation review detects changed paths",
            command="python3 -m unittest tests.test_worktree_isolation.WorktreeIsolationTest.test_review_detects_changes_and_apply_requires_reviewed_flag",
            timeout_seconds=90,
            tags=["builtin", "code", "isolation", "review"],
        ),
        EvalCase(
            id="code_apply_gate_blocks_preview",
            name="apply gate blocks unapproved preview",
            command="python3 -m unittest tests.test_apply_gate.ApplyGateTest.test_evaluate_blocks_preview_that_requires_unapproved_apply",
            timeout_seconds=90,
            tags=["builtin", "code", "apply", "safety"],
        ),
        EvalCase(
            id="code_apply_gate_checkpoint",
            name="apply gate creates checkpoint after passing tests",
            command="python3 -m unittest tests.test_apply_gate.ApplyGateTest.test_apply_approved_review_with_passing_tests_creates_checkpoint",
            timeout_seconds=90,
            tags=["builtin", "code", "apply", "checkpoint"],
        ),
        EvalCase(
            id="code_apply_gate_rollback",
            name="apply gate rolls back failed post-test",
            command="python3 -m unittest tests.test_apply_gate.ApplyGateTest.test_post_apply_test_failure_rolls_back_project_file",
            timeout_seconds=90,
            tags=["builtin", "code", "apply", "rollback"],
        ),
        EvalCase(
            id="code_supervisor_build_plan",
            name="supervisor routes build tasks to isolated coder",
            command="python3 -m unittest tests.test_agent_supervisor.AgentSupervisorTest.test_build_plan_uses_isolated_coder_for_build_tasks",
            tags=["builtin", "code", "orchestration"],
        ),
        EvalCase(
            id="code_swarm_repair_arbitration",
            name="repair swarm ranks isolated repair loops",
            command="python3 -m unittest tests.test_swarm.SwarmTest.test_repair_swarm_runs_parent_ranked_isolated_repair_loops",
            timeout_seconds=180,
            tags=["builtin", "code", "repair", "orchestration"],
        ),
        EvalCase(
            id="code_tool_execution_checkpoint",
            name="path tool creates checkpoint and transcript",
            command="python3 -m unittest tests.test_tool_execution.ToolExecutionTest.test_path_tool_creates_checkpoint_and_transcript",
            timeout_seconds=90,
            tags=["builtin", "code", "tools", "checkpoint"],
        ),
    ]


def run_eval_case(project: Path, case: EvalCase, *, preview_chars: int = DEFAULT_PREVIEW_CHARS) -> EvalResult:
    if case.type != SHELL:
        return EvalResult(
            case_id=case.id,
            name=case.name,
            type=case.type,
            classification=ERROR,
            score=0,
            max_score=case.weight,
            message=f"unsupported eval case type: {case.type}",
        )

    started = time.monotonic()
    cwd = _case_cwd(project, case)
    env = os.environ.copy()
    env.update(case.env)
    try:
        completed = subprocess.run(
            case.command,
            cwd=cwd,
            env=env,
            shell=True,
            text=True,
            capture_output=True,
            timeout=case.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return EvalResult(
            case_id=case.id,
            name=case.name,
            type=case.type,
            classification=ERROR,
            score=0,
            max_score=case.weight,
            returncode=None,
            stdout_preview=_preview(exc.stdout, preview_chars),
            stderr_preview=_preview(exc.stderr, preview_chars),
            duration_ms=_elapsed_ms(started),
            message=f"timeout after {case.timeout_seconds:g}s",
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:179", exc)
        return EvalResult(
            case_id=case.id,
            name=case.name,
            type=case.type,
            classification=ERROR,
            score=0,
            max_score=case.weight,
            duration_ms=_elapsed_ms(started),
            message=f"{type(exc).__name__}: {exc}",
        )

    ok = completed.returncode == case.expected_returncode
    return EvalResult(
        case_id=case.id,
        name=case.name,
        type=case.type,
        classification=PASS if ok else FAIL,
        score=case.weight if ok else 0,
        max_score=case.weight,
        returncode=completed.returncode,
        stdout_preview=_preview(completed.stdout, preview_chars),
        stderr_preview=_preview(completed.stderr, preview_chars),
        duration_ms=_elapsed_ms(started),
        message="ok" if ok else f"expected returncode {case.expected_returncode}, got {completed.returncode}",
    )


def run_eval_cases(project: Path, cases: list[EvalCase]) -> EvalRun:
    if not cases:
        raise ValueError("no eval cases selected")
    run_id = uuid.uuid4().hex
    started = datetime.now().isoformat(timespec="seconds")
    started_monotonic = time.monotonic()
    results = [run_eval_case(project, case) for case in cases]
    finished = datetime.now().isoformat(timespec="seconds")
    return EvalRun(
        run_id=run_id,
        project=str(project),
        started_at=started,
        finished_at=finished,
        results=results,
        duration_ms=_elapsed_ms(started_monotonic),
    )


def score_eval_run(run: EvalRun) -> dict[str, Any]:
    max_score = sum(result.max_score for result in run.results)
    score = sum(result.score for result in run.results)
    total = len(run.results)
    passed = sum(1 for result in run.results if result.classification == PASS)
    failed = sum(1 for result in run.results if result.classification == FAIL)
    errors = sum(1 for result in run.results if result.classification == ERROR)
    percent = round(score / max_score * 100) if max_score > 0 else 0
    return {
        "score": score,
        "max_score": max_score,
        "percent": percent,
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
    }


def render_eval_json(run: EvalRun) -> str:
    return json.dumps(run.to_dict(), ensure_ascii=False, indent=2)


def render_eval_markdown(run: EvalRun) -> str:
    summary = score_eval_run(run)
    lines = [
        "# Mako Eval Run",
        "",
        f"- project: {run.project}",
        f"- run_id: {run.run_id}",
        f"- score: {summary['score']}/{summary['max_score']} ({summary['percent']}/100)",
        f"- cases: {summary['total']} total, {summary['passed']} passed, {summary['failed']} failed, {summary['errors']} errors",
        f"- duration_ms: {run.duration_ms}",
        "",
        "## Results",
        "",
    ]
    for result in run.results:
        lines.append(
            f"- [{result.classification}] {result.case_id} (+{result.score}/{result.max_score}, "
            f"exit={result.returncode}, {result.duration_ms}ms): {result.message}"
        )
        if result.stdout_preview:
            lines.append(f"  stdout: {_one_line(result.stdout_preview)}")
        if result.stderr_preview:
            lines.append(f"  stderr: {_one_line(result.stderr_preview)}")
    return "\n".join(lines) + "\n"


def _case_payloads(payload: Any, path: Path) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("cases"), list):
        items = payload["cases"]
    elif isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = [payload]
    else:
        raise ValueError(f"{path} must contain an eval case object, list, or cases object")
    if not all(isinstance(item, dict) for item in items):
        raise ValueError(f"{path} contains a non-object eval case")
    return items


def _case_cwd(project: Path, case: EvalCase) -> Path:
    if not case.cwd:
        return project
    cwd = Path(case.cwd)
    if cwd.is_absolute():
        return cwd
    return project / cwd


def _elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


def _preview(value: str | bytes | None, limit: int) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...<truncated>"


def _one_line(value: str) -> str:
    return value.replace("\r", "\\r").replace("\n", "\\n")[:500]


def build_eval_snapshot(project: Path) -> dict[str, Any]:
    """Build snapshot of project state for eval reproducibility."""
    snapshot: dict[str, Any] = {}

    # OpenMako git state
    openmako: dict[str, Any] = {}
    try:
        git_dir = project / ".git"
        if git_dir.exists():
            # Get HEAD revision
            head_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=project,
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            if head_result.returncode == 0:
                openmako["revision"] = head_result.stdout.strip()

            # Check if dirty
            status_result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=project,
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            if status_result.returncode == 0:
                is_dirty = bool(status_result.stdout.strip())
                openmako["status"] = "dirty" if is_dirty else "clean"

                # Hash dirty diff for reproducibility
                if is_dirty:
                    diff_result = subprocess.run(
                        ["git", "diff", "HEAD"],
                        cwd=project,
                        capture_output=True,
                        text=True,
                        timeout=10.0,
                    )
                    untracked_result = subprocess.run(
                        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
                        cwd=project,
                        capture_output=True,
                        text=True,
                        timeout=10.0,
                    )

                    # Read untracked file contents (using -z for null-separated paths)
                    untracked_content = []
                    for line in untracked_result.stdout.split("\0"):
                        if line:
                            try:
                                file_path = project / line
                                if file_path.is_file():
                                    content = file_path.read_bytes()
                                    content_hash = hashlib.sha256(content).hexdigest()
                                    untracked_content.append(f"{line}:{content_hash}:{len(content)}")
                            except (OSError, IOError):
                                pass

                    # Combine diff and untracked file hashes
                    combined = diff_result.stdout + "\n" + "\n".join(untracked_content)
                    dirty_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()
                    openmako["dirty_diff_sha256"] = dirty_hash
    except (subprocess.TimeoutExpired, OSError):
        pass

    snapshot["openmako"] = openmako
    return snapshot


def build_eval_gap_report(run: EvalRun) -> dict[str, Any]:
    """Build gap report from eval run results."""
    summary = score_eval_run(run)

    status = "pass" if summary["failed"] == 0 and summary["errors"] == 0 else "gap"

    # Collect failed case evidence
    failed_cases = [r for r in run.results if r.classification in (FAIL, ERROR)]
    next_action_parts = []

    if failed_cases:
        next_action_parts.append("Fix failed cases:")
        for result in failed_cases:
            next_action_parts.append(f"  - {result.case_id}: {result.message}")
            if result.stderr_preview and "AUTOPSY_EVIDENCE" in result.stderr_preview:
                # Extract autopsy evidence
                for line in result.stderr_preview.split("\n"):
                    if "AUTOPSY_EVIDENCE" in line:
                        next_action_parts.append(f"    Evidence: {line.strip()}")

    return {
        "status": status,
        "score": summary["score"],
        "max_score": summary["max_score"],
        "failed": summary["failed"],
        "errors": summary["errors"],
        "next_action": "\n".join(next_action_parts) if next_action_parts else "All cases passed",
    }


def eval_ledger_path(project: Path) -> Path:
    """Return path to eval ledger file."""
    return evals_dir(project) / "ledger.jsonl"


def append_eval_ledger(run: EvalRun) -> Path:
    path = eval_ledger_path(Path(run.project))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.open("a", encoding="utf-8").write(json.dumps(run.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    return path


def latest_eval_ledger_row(project: Path) -> dict[str, Any]:
    path = eval_ledger_path(project)
    if not path.exists():
        raise FileNotFoundError(f"eval ledger not found: {path}")
    rows = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise ValueError(f"eval ledger has no rows: {path}")
    payload = json.loads(rows[-1])
    if not isinstance(payload, dict):
        raise ValueError(f"eval ledger row must be an object: {path}")
    return payload


def build_eval_scorecard(row: dict[str, Any]) -> dict[str, Any]:
    summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
    score = int(summary.get("score") or 0)
    max_score = int(summary.get("max_score") or 0)
    percent = int(summary.get("percent") or 0)
    failed = int(summary.get("failed") or 0)
    errors = int(summary.get("errors") or 0)
    status = "pass" if failed == 0 and errors == 0 and score == max_score else "gap"
    benchmark_id = str(row.get("run_id") or "")
    return {
        "source": "ledger",
        "benchmark_id": benchmark_id,
        "status": status,
        "score": score,
        "max_score": max_score,
        "percent": percent,
        "badge": f"benchmark:{status} {score}/{max_score} ({percent}/100)",
    }


def render_eval_gap_report(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Eval Gap Report",
            "",
            f"- status: {report['status']}",
            f"- score: {report['score']}/{report['max_score']}",
            f"- failed: {report['failed']}",
            f"- errors: {report['errors']}",
            f"- next_action: {str(report['next_action']).replace(chr(10), ' ')}",
        ]
    ) + "\n"


def render_eval_scorecard(scorecard: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Eval Scorecard",
            "",
            f"- {scorecard['badge']}",
            f"- benchmark_id: {scorecard['benchmark_id']}",
            f"- source: {scorecard['source']}",
        ]
    ) + "\n"
