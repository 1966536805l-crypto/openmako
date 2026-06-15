from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


DEFAULT_MAX_ITERATIONS = 5
DEFAULT_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class CodingBenchTask:
    id: str
    instruction: str
    files: Mapping[str, str]
    test_command: str = "{python} -m unittest -q"
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tags"] = list(self.tags)
        return payload


@dataclass(frozen=True)
class CodingBenchCommandResult:
    command: str
    returncode: int | None
    duration_ms: int
    stdout_preview: str = ""
    stderr_preview: str = ""
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CodingBenchAttempt:
    index: int
    agent: CodingBenchCommandResult
    validation: CodingBenchCommandResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "agent": self.agent.to_dict(),
            "validation": self.validation.to_dict(),
        }


@dataclass(frozen=True)
class CodingBenchPatchMetrics:
    changed_files: tuple[str, ...] = ()
    out_of_scope_files: tuple[str, ...] = ()
    workspace_added_files: tuple[str, ...] = ()
    workspace_modified_files: tuple[str, ...] = ()
    workspace_deleted_files: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed_files": list(self.changed_files),
            "out_of_scope_files": list(self.out_of_scope_files),
            "workspace_added_files": list(self.workspace_added_files),
            "workspace_modified_files": list(self.workspace_modified_files),
            "workspace_deleted_files": list(self.workspace_deleted_files),
        }


@dataclass(frozen=True)
class CodingBenchResult:
    task_id: str
    instruction: str
    status: str
    solved: bool
    workspace: str
    baseline: CodingBenchCommandResult
    attempts: tuple[CodingBenchAttempt, ...] = ()
    message: str = ""
    tags: tuple[str, ...] = ()
    failure_class: str = ""
    patch_metrics: CodingBenchPatchMetrics = field(default_factory=CodingBenchPatchMetrics)
    repair_evidence: Mapping[str, Any] = field(default_factory=dict)

    @property
    def iterations(self) -> int:
        return len(self.attempts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "instruction": self.instruction,
            "status": self.status,
            "solved": self.solved,
            "workspace": self.workspace,
            "baseline": self.baseline.to_dict(),
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "iterations": self.iterations,
            "message": self.message,
            "tags": list(self.tags),
            "failure_class": self.failure_class,
            "patch_metrics": self.patch_metrics.to_dict(),
            "repair_evidence": dict(self.repair_evidence),
        }


@dataclass(frozen=True)
class CodingBenchRun:
    run_id: str
    created_at: str
    project: str
    agent_command: str
    results: tuple[CodingBenchResult, ...] = ()
    artifact_dir: str = ""
    task_source: Mapping[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        total = len(self.results)
        solved = sum(1 for result in self.results if result.solved)
        invalid = sum(1 for result in self.results if result.status == "invalid_fixture")
        errors = sum(1 for result in self.results if result.status == "error")
        cheated = sum(1 for result in self.results if result.status == "cheated")
        attempted = [result.iterations for result in self.results if result.attempts]
        avg_iterations = round(sum(attempted) / len(attempted), 2) if attempted else 0.0
        return {
            "total": total,
            "solved": solved,
            "failed": total - solved - invalid - errors - cheated,
            "cheated": cheated,
            "invalid": invalid,
            "errors": errors,
            "success_rate": round((solved / total) * 100, 2) if total else 0.0,
            "avg_iterations": avg_iterations,
            "human_intervention_rate": 0.0,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "project": self.project,
            "agent_command": self.agent_command,
            "artifact_dir": self.artifact_dir,
            "task_source": dict(self.task_source),
            "summary": self.summary(),
            "results": [result.to_dict() for result in self.results],
        }


def coding_bench_dir(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "coding_bench"


def _new_coding_bench_run_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


def builtin_coding_bench_tasks() -> list[CodingBenchTask]:
    return [_task(spec) for spec in _builtin_specs()]


def load_coding_bench_tasks(path: str | Path) -> list[CodingBenchTask]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_tasks = payload.get("tasks") if isinstance(payload, dict) else payload
    if not isinstance(raw_tasks, list):
        raise ValueError("coding bench task file must be a list or an object with a tasks list")
    tasks: list[CodingBenchTask] = []
    for item in raw_tasks:
        if not isinstance(item, dict):
            raise ValueError("coding bench task entries must be objects")
        files = item.get("files")
        if not isinstance(files, dict) or not files:
            raise ValueError(f"task {item.get('id', '<missing>')} must define files")
        for name in files:
            _validate_task_file_path(str(name))
        tasks.append(
            CodingBenchTask(
                id=_required_str(item, "id"),
                instruction=_required_str(item, "instruction"),
                files={str(key): str(value) for key, value in files.items()},
                test_command=str(item.get("test_command") or "{python} -m unittest -q"),
                max_iterations=int(item.get("max_iterations") or DEFAULT_MAX_ITERATIONS),
                timeout_seconds=float(item.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS),
                tags=tuple(str(tag) for tag in item.get("tags", ())),
            )
        )
    return tasks


def run_openmako_agent(workspace: Path, instruction: str, failure: str) -> str:
    raise ValueError("built-in canned coding bench agents are not allowed; pass agent_command")


def run_coding_bench(
    project: str | Path,
    *,
    agent_command: str = "",
    agent: str = "",
    task_file: str | Path | None = None,
    limit: int | None = None,
    keep_workspaces: bool = False,
) -> CodingBenchRun:
    if not agent_command and not agent:
        raise ValueError("agent_command is required for real coding ability evaluation")
    if agent_command and agent:
        raise ValueError("agent_command and agent are mutually exclusive")

    resolved_agent_command = agent_command
    if agent:
        raise ValueError("built-in canned coding bench agents are not allowed; pass agent_command")
    _validate_agent_command_template(resolved_agent_command)

    project_path = Path(project).expanduser().resolve(strict=False)
    tasks = load_coding_bench_tasks(task_file) if task_file else builtin_coding_bench_tasks()
    task_source = _coding_bench_task_source(tasks, task_file=task_file)
    if limit is not None:
        tasks = tasks[: max(limit, 0)]
        task_source = _coding_bench_task_source(tasks, task_file=task_file, limit=limit)
    run_id = _new_coding_bench_run_id("cbench")
    artifact_dir = coding_bench_dir(project_path) / "runs" / run_id
    workspace_root = artifact_dir / "workspaces"
    workspace_root.mkdir(parents=True, exist_ok=True)
    results = [
        run_coding_bench_task(task, workspace_root / _safe_task_dir(task.id), agent_command=resolved_agent_command)
        for task in tasks
    ]
    run = CodingBenchRun(
        run_id=run_id,
        created_at=datetime.now().isoformat(timespec="seconds"),
        project=str(project_path),
        agent_command=resolved_agent_command,
        results=tuple(results),
        artifact_dir=str(artifact_dir),
        task_source=task_source,
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "run.json").write_text(render_coding_bench_json(run), encoding="utf-8")
    (artifact_dir / "run.md").write_text(render_coding_bench_markdown(run), encoding="utf-8")
    if not keep_workspaces:
        shutil.rmtree(workspace_root, ignore_errors=True)
    return run


@dataclass(frozen=True)
class CodingBenchStabilityRun:
    run_id: str
    created_at: str
    project: str
    agent_command: str
    repeats: int
    runs: tuple[CodingBenchRun, ...] = ()
    artifact_dir: str = ""

    def summary(self) -> dict[str, Any]:
        total_runs = len(self.runs)
        total_tasks = sum(run.summary()["total"] for run in self.runs)
        total_solved = sum(run.summary()["solved"] for run in self.runs)
        total_cheated = sum(run.summary().get("cheated", 0) for run in self.runs)
        total_errors = sum(run.summary()["errors"] for run in self.runs)
        total_invalid = sum(run.summary()["invalid"] for run in self.runs)
        success_rates = [float(run.summary()["success_rate"]) for run in self.runs]
        solved_by_task: dict[str, list[bool]] = {}
        failure_classes: dict[str, int] = {}
        for run in self.runs:
            for result in run.results:
                solved_by_task.setdefault(result.task_id, []).append(result.solved)
                key = result.failure_class or result.status
                if not result.solved:
                    failure_classes[key] = failure_classes.get(key, 0) + 1
        unstable_tasks = sorted(
            task_id
            for task_id, outcomes in solved_by_task.items()
            if outcomes and any(outcomes) and not all(outcomes)
        )
        min_success_rate = min(success_rates) if success_rates else 0.0
        max_success_rate = max(success_rates) if success_rates else 0.0
        return {
            "runs": total_runs,
            "repeats": self.repeats,
            "total_task_attempts": total_tasks,
            "solved": total_solved,
            "cheated": total_cheated,
            "invalid": total_invalid,
            "errors": total_errors,
            "overall_success_rate": round((total_solved / total_tasks) * 100, 2) if total_tasks else 0.0,
            "min_success_rate": round(min_success_rate, 2),
            "max_success_rate": round(max_success_rate, 2),
            "success_rate_spread": round(max_success_rate - min_success_rate, 2),
            "unstable_tasks": unstable_tasks,
            "unstable_task_count": len(unstable_tasks),
            "failure_classes": dict(sorted(failure_classes.items())),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "project": self.project,
            "agent_command": self.agent_command,
            "repeats": self.repeats,
            "artifact_dir": self.artifact_dir,
            "summary": self.summary(),
            "runs": [run.to_dict() for run in self.runs],
        }


def run_coding_bench_stability(
    project: str | Path,
    *,
    agent_command: str = "",
    agent: str = "",
    task_file: str | Path | None = None,
    limit: int | None = None,
    repeats: int = 3,
    keep_workspaces: bool = False,
) -> CodingBenchStabilityRun:
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    if not agent_command and not agent:
        raise ValueError("agent_command is required for real coding ability evaluation")
    if agent_command and agent:
        raise ValueError("agent_command and agent are mutually exclusive")
    if agent:
        raise ValueError("built-in canned coding bench agents are not allowed; pass agent_command")
    _validate_agent_command_template(agent_command)

    project_path = Path(project).expanduser().resolve(strict=False)
    run_id = _new_coding_bench_run_id("cbench-stability")
    artifact_dir = coding_bench_dir(project_path) / "stability" / run_id
    runs: list[CodingBenchRun] = []
    for index in range(1, repeats + 1):
        run = run_coding_bench(
            project_path,
            agent_command=agent_command,
            task_file=task_file,
            limit=limit,
            keep_workspaces=keep_workspaces,
        )
        runs.append(run)
        repeat_dir = artifact_dir / f"repeat-{index:02d}"
        repeat_dir.mkdir(parents=True, exist_ok=True)
        (repeat_dir / "run.json").write_text(render_coding_bench_json(run), encoding="utf-8")
        (repeat_dir / "run.md").write_text(render_coding_bench_markdown(run), encoding="utf-8")

    stability = CodingBenchStabilityRun(
        run_id=run_id,
        created_at=datetime.now().isoformat(timespec="seconds"),
        project=str(project_path),
        agent_command=agent_command,
        repeats=repeats,
        runs=tuple(runs),
        artifact_dir=str(artifact_dir),
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "stability.json").write_text(render_coding_bench_stability_json(stability), encoding="utf-8")
    (artifact_dir / "stability.md").write_text(render_coding_bench_stability_markdown(stability), encoding="utf-8")
    return stability


def run_coding_bench_task(task: CodingBenchTask, workspace: str | Path, *, agent_command: str) -> CodingBenchResult:
    workspace_path = Path(workspace)
    if workspace_path.exists():
        shutil.rmtree(workspace_path)
    workspace_path.mkdir(parents=True)
    _write_files(workspace_path, task.files)

    protected_files = _protected_fixture_files(task)
    allowed_implementation_files = tuple(sorted(set(task.files) - set(protected_files)))
    protected_hashes_before = {name: _file_hash(workspace_path / name) for name in protected_files}
    task_hashes_before = {name: _file_hash(workspace_path / name) for name in task.files}

    _purge_pycache(workspace_path)
    baseline = _run_shell(_format_command(task.test_command, task, workspace_path, attempt=0), workspace_path, task.timeout_seconds)
    if baseline.ok:
        return CodingBenchResult(
            task.id,
            task.instruction,
            "invalid_fixture",
            False,
            str(workspace_path),
            baseline,
            message="baseline validation passed before the agent changed anything",
            tags=task.tags,
            failure_class="invalid_fixture",
        )

    workspace_hashes_before = _workspace_file_hashes(workspace_path)
    attempts: list[CodingBenchAttempt] = []
    last_failure = _failure_text(baseline)
    last_agent_result: CodingBenchCommandResult | None = None
    last_validation: CodingBenchCommandResult | None = None
    for index in range(1, max(task.max_iterations, 1) + 1):
        failure_file = workspace_path / ".mako_bench_last_failure.txt"
        failure_file.write_text(last_failure, encoding="utf-8")

        command = _format_command(agent_command, task, workspace_path, attempt=index, failure=last_failure, failure_file=failure_file)
        agent_result = _run_shell(command, workspace_path, task.timeout_seconds)
        last_agent_result = agent_result

        modified_protected = [
            name
            for name in protected_files
            if _file_hash(workspace_path / name) != protected_hashes_before.get(name, "")
        ]
        if modified_protected:
            return CodingBenchResult(
                task.id,
                task.instruction,
                "cheated",
                False,
                str(workspace_path),
                baseline,
                attempts=tuple(attempts),
                message="agent modified protected test file(s): " + ", ".join(modified_protected),
                tags=task.tags,
                failure_class="policy",
                patch_metrics=_patch_metrics(workspace_path, task_hashes_before, workspace_hashes_before, out_of_scope_files=modified_protected),
            )
        out_of_scope_files = _workspace_out_of_scope_files(
            workspace_path,
            before=workspace_hashes_before,
            allowed_files=allowed_implementation_files,
        )
        if out_of_scope_files:
            return CodingBenchResult(
                task.id,
                task.instruction,
                "cheated",
                False,
                str(workspace_path),
                baseline,
                attempts=tuple(attempts),
                message="agent changed out-of-scope file(s): " + ", ".join(out_of_scope_files),
                tags=task.tags,
                failure_class="policy",
                patch_metrics=_patch_metrics(workspace_path, task_hashes_before, workspace_hashes_before, out_of_scope_files=out_of_scope_files),
            )

        _purge_pycache(workspace_path)
        validation = _run_shell(_format_command(task.test_command, task, workspace_path, attempt=index), workspace_path, task.timeout_seconds)
        last_validation = validation
        attempts.append(CodingBenchAttempt(index, agent_result, validation))
        out_of_scope_files = _workspace_out_of_scope_files(
            workspace_path,
            before=workspace_hashes_before,
            allowed_files=allowed_implementation_files,
        )
        if out_of_scope_files:
            return CodingBenchResult(
                task.id,
                task.instruction,
                "cheated",
                False,
                str(workspace_path),
                baseline,
                attempts=tuple(attempts),
                message="agent changed out-of-scope file(s): " + ", ".join(out_of_scope_files),
                tags=task.tags,
                failure_class="policy",
                patch_metrics=_patch_metrics(workspace_path, task_hashes_before, workspace_hashes_before, out_of_scope_files=out_of_scope_files),
            )
        if validation.ok:
            patch_metrics = _patch_metrics(workspace_path, task_hashes_before, workspace_hashes_before, out_of_scope_files=out_of_scope_files)
            return CodingBenchResult(
                task.id,
                task.instruction,
                "solved",
                True,
                str(workspace_path),
                baseline,
                attempts=tuple(attempts),
                message=f"solved in {index} iteration(s)",
                tags=task.tags,
                patch_metrics=patch_metrics,
                repair_evidence=_repair_evidence_packet(
                    task,
                    workspace_path,
                    status="solved",
                    solved=True,
                    baseline=baseline,
                    attempts=attempts,
                    patch_metrics=patch_metrics,
                ),
            )
        last_failure = _failure_text(validation)

    patch_metrics = _patch_metrics(workspace_path, task_hashes_before, workspace_hashes_before, out_of_scope_files=out_of_scope_files)
    changed_files = patch_metrics.changed_files
    out_of_scope_files = _workspace_out_of_scope_files(
        workspace_path,
        before=workspace_hashes_before,
        allowed_files=allowed_implementation_files,
    )
    failure_class = _classify_coding_bench_failure(
        changed_files=changed_files,
        last_agent_result=last_agent_result,
        last_validation=last_validation,
    )
    return CodingBenchResult(
        task.id,
        task.instruction,
        "failed",
        False,
        str(workspace_path),
        baseline,
        attempts=tuple(attempts),
        message=f"not solved after {len(attempts)} iteration(s)",
        tags=task.tags,
        failure_class=failure_class,
        patch_metrics=patch_metrics,
        repair_evidence=_repair_evidence_packet(
            task,
            workspace_path,
            status="failed",
            solved=False,
            baseline=baseline,
            attempts=attempts,
            patch_metrics=patch_metrics,
            failure_class=failure_class,
        ),
    )


def render_coding_bench_json(run: CodingBenchRun) -> str:
    return json.dumps(run.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_coding_bench_markdown(run: CodingBenchRun) -> str:
    summary = run.summary()
    lines = [
        "# CodingBench",
        "",
        f"- run_id: {run.run_id}",
        f"- success_rate: {summary['success_rate']}%",
        f"- solved: {summary['solved']}/{summary['total']}",
        f"- avg_iterations: {summary['avg_iterations']}",
        f"- human_intervention_rate: {summary['human_intervention_rate']}%",
        "",
        "## Results",
        "",
    ]
    for result in run.results:
        marker = "PASS" if result.solved else ("CHEATED" if result.status == "cheated" else "FAIL")
        lines.append(f"- [{marker}] {result.task_id}: {result.status}; iterations={result.iterations}; {result.message}")
    return "\n".join(lines).rstrip() + "\n"


def render_coding_bench_stability_json(run: CodingBenchStabilityRun) -> str:
    return json.dumps(run.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_coding_bench_stability_markdown(run: CodingBenchStabilityRun) -> str:
    summary = run.summary()
    lines = [
        "# CodingBench Stability",
        "",
        f"- run_id: {run.run_id}",
        f"- repeats: {summary['repeats']}",
        f"- overall_success_rate: {summary['overall_success_rate']}%",
        f"- success_rate_spread: {summary['success_rate_spread']}%",
        f"- unstable_task_count: {summary['unstable_task_count']}",
        f"- cheated: {summary['cheated']}",
        f"- errors: {summary['errors']}",
        "",
        "## Repeat Results",
        "",
    ]
    for index, item in enumerate(run.runs, start=1):
        item_summary = item.summary()
        lines.append(
            f"- repeat {index}: success_rate={item_summary['success_rate']}%; "
            f"solved={item_summary['solved']}/{item_summary['total']}; "
            f"cheated={item_summary.get('cheated', 0)}"
        )
    if summary["unstable_tasks"]:
        lines.extend(["", "## Unstable Tasks", ""])
        for task_id in summary["unstable_tasks"]:
            lines.append(f"- {task_id}")
    if summary["failure_classes"]:
        lines.extend(["", "## Failure Classes", ""])
        for name, count in summary["failure_classes"].items():
            lines.append(f"- {name}: {count}")
    return "\n".join(lines).rstrip() + "\n"


def _coding_bench_task_source(
    tasks: Sequence[CodingBenchTask],
    *,
    task_file: str | Path | None,
    limit: int | None = None,
) -> dict[str, Any]:
    task_ids = [task.id for task in tasks]
    task_payload = [task.to_dict() for task in tasks]
    task_payload_json = json.dumps(task_payload, ensure_ascii=False, sort_keys=True)
    task_file_path = Path(task_file).expanduser().resolve(strict=False) if task_file else None
    source: dict[str, Any] = {
        "schema_version": "openmako-coding-bench-task-source/v0.1",
        "source_kind": "task_file" if task_file_path else "builtin",
        "task_count": len(tasks),
        "task_ids": task_ids,
        "task_ids_sha256": _sha256_text("\n".join(task_ids) + ("\n" if task_ids else "")),
        "task_payload_sha256": _sha256_text(task_payload_json),
        "limit": limit,
        "identity_lock": {
            "task_ids_locked": True,
            "task_payload_locked": True,
            "task_file_sha256_locked": bool(task_file_path),
        },
        "evidence_boundary": {
            "proves": [
                "the CodingBench run records the exact evaluated task ids",
                "the CodingBench run records a sha256 over the evaluated task payload",
                "task-file runs record the task file sha256 used to create the run",
            ],
            "not_proof": [
                "native live autonomy",
                "broad unknown-repository repair",
                "third-party benchmark standing",
                "external review",
                "endorsement",
                "stars",
                "reposts",
                "remote CI proof",
            ],
        },
    }
    if task_file_path:
        if not task_file_path.is_file():
            raise ValueError(f"coding bench task file does not exist: {task_file}")
        source["task_file"] = {
            "path": str(task_file_path),
            "sha256": _file_hash(task_file_path),
        }
    return source


def _run_shell(command: str, cwd: Path, timeout_seconds: float) -> CodingBenchCommandResult:
    start = time.monotonic()
    env = _subprocess_env()
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            env=env,
        )
        return CodingBenchCommandResult(
            command=command,
            returncode=proc.returncode,
            duration_ms=int((time.monotonic() - start) * 1000),
            stdout_preview=_preview(proc.stdout),
            stderr_preview=_preview(proc.stderr),
        )
    except subprocess.TimeoutExpired as exc:
        return CodingBenchCommandResult(
            command=command,
            returncode=None,
            duration_ms=int((time.monotonic() - start) * 1000),
            stdout_preview=_preview(exc.stdout or ""),
            stderr_preview=_preview(exc.stderr or ""),
            timed_out=True,
        )


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    repo_root = str(Path(__file__).resolve().parents[1])
    existing = env.get("PYTHONPATH")
    paths = [path for path in (existing or "").split(os.pathsep) if path]
    if repo_root not in paths:
        env["PYTHONPATH"] = repo_root + (os.pathsep + existing if existing else "")
    return env


def _validate_agent_command_template(template: str) -> None:
    if not template.strip():
        raise ValueError("agent_command is required for real coding ability evaluation")
    if template.strip() == "openmako-self-agent":
        raise ValueError("built-in canned coding bench agents are not allowed; pass agent_command")


def _format_command(
    template: str,
    task: CodingBenchTask,
    workspace: Path,
    *,
    attempt: int,
    failure: str = "",
    failure_file: Path | None = None,
) -> str:
    replacements = {
        "workspace": shlex.quote(str(workspace)),
        "instruction": shlex.quote(task.instruction),
        "task_id": shlex.quote(task.id),
        "attempt": str(attempt),
        "python": shlex.quote(sys.executable),
        "failure": shlex.quote(failure),
        "failure_file": shlex.quote(str(failure_file or workspace / ".mako_bench_last_failure.txt")),
    }
    return template.format(**replacements)


def _write_files(root: Path, files: Mapping[str, str]) -> None:
    for name, text in files.items():
        _validate_task_file_path(name)
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _validate_task_file_path(name: str) -> None:
    path = Path(name)
    if path.is_absolute() or not name.strip() or ".." in path.parts:
        raise ValueError(f"unsafe task file path: {name}")


def _protected_fixture_files(task: CodingBenchTask) -> tuple[str, ...]:
    protected = []
    for name in task.files:
        path = Path(name)
        if _looks_like_test_file(path) or _test_command_references_task_file(task.test_command, path):
            protected.append(name)
    return tuple(sorted(protected))


def _looks_like_test_file(path: Path) -> bool:
    stem = path.stem.lower()
    filename = path.name.lower()
    parts = {part.lower() for part in path.parts}
    return filename.startswith("test_") or stem.endswith("_test") or bool(parts & {"test", "tests"})


def _test_command_references_task_file(command: str, path: Path) -> bool:
    if not command.strip():
        return False
    candidates = _task_file_command_names(path)
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    normalized_tokens: set[str] = set()
    for token in tokens:
        normalized = _normalize_command_token(token)
        normalized_tokens.add(normalized)
        normalized_tokens.add(normalized.split("::", 1)[0])
    return any(candidate in normalized_tokens for candidate in candidates)


def _task_file_command_names(path: Path) -> set[str]:
    as_posix = path.as_posix()
    without_suffix = path.with_suffix("").as_posix()
    candidates = {as_posix, path.name, without_suffix, path.with_suffix("").name}
    if len(path.parts) > 1:
        candidates.add(".".join(path.with_suffix("").parts))
    return {candidate for candidate in candidates if candidate}


def _normalize_command_token(token: str) -> str:
    normalized = token.strip().strip("'\"")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _changed_task_files(root: Path, before: Mapping[str, str]) -> tuple[str, ...]:
    changed = [
        name
        for name, digest in before.items()
        if _file_hash(root / name) != digest
    ]
    return tuple(sorted(changed))


def _patch_metrics(
    root: Path,
    task_hashes_before: Mapping[str, str],
    workspace_hashes_before: Mapping[str, str],
    *,
    out_of_scope_files: Sequence[str] = (),
) -> CodingBenchPatchMetrics:
    diff = _workspace_diff(root, workspace_hashes_before)
    return CodingBenchPatchMetrics(
        changed_files=_changed_task_files(root, task_hashes_before),
        out_of_scope_files=tuple(sorted(set(out_of_scope_files))),
        workspace_added_files=diff["added"],
        workspace_modified_files=diff["modified"],
        workspace_deleted_files=diff["deleted"],
    )


def _repair_evidence_packet(
    task: CodingBenchTask,
    workspace: Path,
    *,
    status: str,
    solved: bool,
    baseline: CodingBenchCommandResult,
    attempts: Sequence[CodingBenchAttempt],
    patch_metrics: CodingBenchPatchMetrics,
    failure_class: str = "",
) -> dict[str, Any]:
    label = "supported_repair_claim" if solved and patch_metrics.changed_files and not patch_metrics.out_of_scope_files else "unsupported_repair_claim"
    last_attempt = attempts[-1] if attempts else None
    changed_hashes_before = {name: _sha256_text(task.files.get(name, "")) for name in patch_metrics.changed_files}
    changed_hashes_after = {name: _file_hash(workspace / name) for name in patch_metrics.changed_files}
    return {
        "schema_version": "openmako-coding-bench-repair-evidence/v0.1",
        "label": label,
        "task_id": task.id,
        "status": status,
        "solved": solved,
        "before_failure": baseline.to_dict(),
        "agent_diagnosis": _agent_diagnosis_from_attempt(last_attempt),
        "diff": _repair_diff_payload(task, workspace, patch_metrics.changed_files),
        "after_test": last_attempt.validation.to_dict() if last_attempt else {},
        "command_log": _repair_command_log(baseline, attempts),
        "patch_scope": patch_metrics.to_dict(),
        "source_hashes": {
            "before": changed_hashes_before,
            "after": changed_hashes_after,
        },
        "final_claim": _repair_final_claim(task.id, solved=solved, changed_files=patch_metrics.changed_files),
        "evidence_boundary": {
            "proves": [
                "baseline validation failed before the agent command",
                "the agent command ran in an isolated CodingBench workspace",
                "post-agent validation command result was recorded",
                "workspace patch scope was compared against task files",
            ],
            "not_proof": [
                "native live autonomy",
                "broad unknown-repository repair",
                "third-party benchmark standing",
                "external review",
                "endorsement",
                "stars",
                "reposts",
                "remote CI proof",
            ],
        },
        "failure_class": failure_class,
    }


def _agent_diagnosis_from_attempt(attempt: CodingBenchAttempt | None) -> dict[str, Any]:
    if attempt is None:
        return {}
    payload = _json_object_from_output(attempt.agent.stdout_preview)
    return {
        "returncode": attempt.agent.returncode,
        "timed_out": attempt.agent.timed_out,
        "stdout_preview": attempt.agent.stdout_preview,
        "stderr_preview": attempt.agent.stderr_preview,
        "reported_status": payload.get("status", "") if payload else "",
        "reported_failure_class": payload.get("failure_class", "") if payload else "",
    }


def _repair_diff_payload(
    task: CodingBenchTask,
    workspace: Path,
    changed_files: Sequence[str],
) -> dict[str, Any]:
    diffs: dict[str, list[str]] = {}
    total_line_count = 0
    for name in changed_files:
        before = task.files.get(name, "")
        after_path = workspace / name
        after = after_path.read_text(encoding="utf-8") if after_path.exists() else ""
        diff_lines = list(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"before/{name}",
                tofile=f"after/{name}",
            )
        )
        rendered = [line.rstrip("\n") for line in diff_lines]
        diffs[name] = rendered
        total_line_count += len(rendered)
    return {
        "line_count": total_line_count,
        "changed_files": list(changed_files),
        "unified_diff_by_file": diffs,
    }


def _repair_command_log(
    baseline: CodingBenchCommandResult,
    attempts: Sequence[CodingBenchAttempt],
) -> list[dict[str, Any]]:
    log: list[dict[str, Any]] = [{"phase": "before_failure", "result": baseline.to_dict()}]
    for attempt in attempts:
        log.append({"phase": f"agent_attempt_{attempt.index}", "result": attempt.agent.to_dict()})
        log.append({"phase": f"after_test_{attempt.index}", "result": attempt.validation.to_dict()})
    return log


def _repair_final_claim(task_id: str, *, solved: bool, changed_files: Sequence[str]) -> str:
    if not solved:
        return f"CodingBench task {task_id} is not supported as solved by this run."
    files = ", ".join(changed_files) if changed_files else "no files"
    return (
        f"CodingBench task {task_id} is supported as solved for this isolated "
        f"workspace run; changed files: {files}."
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _workspace_file_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file() or _ignored_workspace_path(path, root):
            continue
        hashes[path.relative_to(root).as_posix()] = _file_hash(path)
    return hashes


def _workspace_diff(root: Path, before: Mapping[str, str]) -> dict[str, tuple[str, ...]]:
    after = _workspace_file_hashes(root)
    before_names = set(before)
    after_names = set(after)
    added = after_names - before_names
    deleted = before_names - after_names
    modified = {name for name in before_names & after_names if before[name] != after[name]}
    return {
        "added": tuple(sorted(added)),
        "modified": tuple(sorted(modified)),
        "deleted": tuple(sorted(deleted)),
    }


def _workspace_out_of_scope_files(root: Path, *, before: Mapping[str, str], allowed_files: Sequence[str]) -> tuple[str, ...]:
    allowed = {Path(name).as_posix() for name in allowed_files}
    diff = _workspace_diff(root, before)
    changed = {*diff["added"], *diff["modified"], *diff["deleted"]}
    return tuple(sorted(name for name in changed if name not in allowed))


def _ignored_workspace_path(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    parts = set(rel.parts)
    if "__pycache__" in parts or ".pytest_cache" in parts:
        return True
    if rel.name == ".mako_bench_last_failure.txt":
        return True
    if rel.suffix in {".pyc", ".pyo"}:
        return True
    if rel.parts and rel.parts[0] in {"AI_协作交接", ".quantagent", "quantagent_sessions", "quantagent_tasks"}:
        return True
    return False


def _classify_coding_bench_failure(
    *,
    changed_files: Sequence[str],
    last_agent_result: CodingBenchCommandResult | None,
    last_validation: CodingBenchCommandResult | None,
) -> str:
    if last_agent_result and last_agent_result.timed_out:
        return "agent_timeout"
    if last_validation and last_validation.timed_out:
        return "validation_timeout"
    if last_agent_result:
        agent_report_class = _agent_report_failure_class(last_agent_result)
        if agent_report_class:
            return agent_report_class
        if last_agent_result.returncode not in (0, None) and not changed_files:
            return "agent_command_failed"
    if not changed_files:
        return "no_patch"
    return "validation_failed"


def _agent_report_failure_class(result: CodingBenchCommandResult) -> str:
    payload = _json_object_from_output(result.stdout_preview)
    if not payload:
        match = re.search(r'"failure_class"\s*:\s*"([^"]+)"', result.stdout_preview)
        return match.group(1).strip() if match else ""
    failure_class = str(payload.get("failure_class") or "").strip()
    if failure_class:
        return failure_class
    status = str(payload.get("status") or "").strip()
    if status and status not in {"done", "ok", "success"}:
        return status
    return ""


def _json_object_from_output(text: str) -> dict[str, Any]:
    candidate = str(text or "").strip()
    if not candidate:
        return {}
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _purge_pycache(root: Path) -> None:
    for path in root.rglob("__pycache__"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


def _preview(text: str, limit: int = 3000) -> str:
    value = str(text)
    return value if len(value) <= limit else value[:limit] + "\n...[truncated]"


def _failure_text(result: CodingBenchCommandResult) -> str:
    return "\n".join(part for part in (result.stdout_preview, result.stderr_preview) if part).strip()


def _required_str(item: Mapping[str, Any], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"task missing required string field: {key}")
    return value


def _safe_task_dir(task_id: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in task_id)
    return safe or "task"


def _file_hash(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _task(spec: tuple[str, str, str, str, tuple[str, ...]]) -> CodingBenchTask:
    task_id, instruction, source, tests, tags = spec
    return CodingBenchTask(
        id=task_id,
        instruction=instruction,
        files={"subject.py": source.strip() + "\n", "test_subject.py": tests.strip() + "\n"},
        tags=tags,
    )


def _builtin_specs() -> list[tuple[str, str, str, str, tuple[str, ...]]]:
    specs: list[tuple[str, str, str, str, tuple[str, ...]]] = []

    def add(task_id: str, instruction: str, source: str, tests: str, *tags: str) -> None:
        specs.append((task_id, instruction, source, tests, tuple(tags or ("code", "repair"))))

    add("add_numbers", "Fix add_numbers so it returns arithmetic sum for ints and floats.", "def add_numbers(a, b):\n    return a - b", "import unittest\nfrom subject import add_numbers\n\nclass TestSubject(unittest.TestCase):\n    def test_sum(self):\n        self.assertEqual(add_numbers(2, 3), 5)\n        self.assertEqual(add_numbers(-2, 3), 1)\n        self.assertEqual(add_numbers(1.5, 2.5), 4.0)\n")
    add("clamp_bounds", "Fix clamp so values are constrained to the inclusive [low, high] interval.", "def clamp(value, low, high):\n    return value", "import unittest\nfrom subject import clamp\n\nclass TestSubject(unittest.TestCase):\n    def test_clamp(self):\n        self.assertEqual(clamp(5, 1, 10), 5)\n        self.assertEqual(clamp(-1, 1, 10), 1)\n        self.assertEqual(clamp(11, 1, 10), 10)\n")
    add("slugify_text", "Fix slugify to lowercase text, trim it, replace non-alnum runs with one dash, and trim dashes.", "import re\n\ndef slugify(text):\n    return str(text).replace(' ', '-')", "import unittest\nfrom subject import slugify\n\nclass TestSubject(unittest.TestCase):\n    def test_slugify(self):\n        self.assertEqual(slugify(' Hello, Mako Agent! '), 'hello-mako-agent')\n        self.assertEqual(slugify('A---B___C'), 'a-b-c')\n")
    add("parse_bool", "Fix parse_bool to accept common true/false strings and raise ValueError for unknown values.", "def parse_bool(value):\n    return bool(value)", "import unittest\nfrom subject import parse_bool\n\nclass TestSubject(unittest.TestCase):\n    def test_bool(self):\n        self.assertTrue(parse_bool('YES'))\n        self.assertFalse(parse_bool(' no '))\n        with self.assertRaises(ValueError):\n            parse_bool('maybe')\n")
    add("safe_divide", "Fix safe_divide so division by zero returns the supplied default.", "def safe_divide(a, b, default=None):\n    return a / b", "import unittest\nfrom subject import safe_divide\n\nclass TestSubject(unittest.TestCase):\n    def test_divide(self):\n        self.assertEqual(safe_divide(6, 3), 2)\n        self.assertEqual(safe_divide(6, 0, default='x'), 'x')\n")
    add("flatten_one_level", "Fix flatten_one_level to flatten only list/tuple children by one level.", "def flatten_one_level(items):\n    return list(items)", "import unittest\nfrom subject import flatten_one_level\n\nclass TestSubject(unittest.TestCase):\n    def test_flatten(self):\n        self.assertEqual(flatten_one_level([1, [2, 3], (4, 5), 'ab']), [1, 2, 3, 4, 5, 'ab'])\n")
    add("unique_preserve_order", "Fix unique_preserve_order to remove duplicates while keeping first occurrence order.", "def unique_preserve_order(items):\n    return sorted(set(items))", "import unittest\nfrom subject import unique_preserve_order\n\nclass TestSubject(unittest.TestCase):\n    def test_unique(self):\n        self.assertEqual(unique_preserve_order(['b', 'a', 'b', 'c', 'a']), ['b', 'a', 'c'])\n")
    add("mask_token", "Fix mask_token to keep a prefix and suffix while masking the middle.", "def mask_token(token, prefix=4, suffix=4):\n    return '***'", "import unittest\nfrom subject import mask_token\n\nclass TestSubject(unittest.TestCase):\n    def test_mask(self):\n        self.assertEqual(mask_token('sk-1234567890abcdef', 5, 4), 'sk-12...cdef')\n        self.assertEqual(mask_token('short', 5, 5), '***')\n")
    add("parse_kv_lines", "Fix parse_kv_lines to parse key=value lines, skip blanks/comments, and trim whitespace.", "def parse_kv_lines(text):\n    return {}", "import unittest\nfrom subject import parse_kv_lines\n\nclass TestSubject(unittest.TestCase):\n    def test_parse(self):\n        self.assertEqual(parse_kv_lines('a=1\\n# no\\n b = two \\n\\n'), {'a': '1', 'b': 'two'})\n")
    add("normalize_path_segments", "Fix normalize_path_segments to collapse . segments and resolve .. without escaping above root.", "def normalize_path_segments(path):\n    return path", "import unittest\nfrom subject import normalize_path_segments\n\nclass TestSubject(unittest.TestCase):\n    def test_path(self):\n        self.assertEqual(normalize_path_segments('a/./b/../c'), 'a/c')\n        self.assertEqual(normalize_path_segments('../../a'), 'a')\n")
    add("moving_average", "Fix moving_average to return simple moving averages for a positive window.", "def moving_average(values, window):\n    return []", "import unittest\nfrom subject import moving_average\n\nclass TestSubject(unittest.TestCase):\n    def test_average(self):\n        self.assertEqual(moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])\n        with self.assertRaises(ValueError):\n            moving_average([1], 0)\n")
    add("percent_change", "Fix percent_change to compute (new-old)/old and return None when old is zero.", "def percent_change(old, new):\n    return new / old", "import unittest\nfrom subject import percent_change\n\nclass TestSubject(unittest.TestCase):\n    def test_change(self):\n        self.assertEqual(percent_change(100, 110), 0.1)\n        self.assertIsNone(percent_change(0, 10))\n")
    add("is_sorted", "Fix is_sorted to accept equal adjacent values and work for descending mode.", "def is_sorted(values, reverse=False):\n    return values == sorted(values)", "import unittest\nfrom subject import is_sorted\n\nclass TestSubject(unittest.TestCase):\n    def test_sorted(self):\n        self.assertTrue(is_sorted([1, 1, 2]))\n        self.assertTrue(is_sorted([3, 2, 2], reverse=True))\n        self.assertFalse(is_sorted([2, 1, 3]))\n")
    add("chunk_list", "Fix chunk_list to split a list into chunks of size n and reject non-positive sizes.", "def chunk_list(items, size):\n    return [items]", "import unittest\nfrom subject import chunk_list\n\nclass TestSubject(unittest.TestCase):\n    def test_chunks(self):\n        self.assertEqual(chunk_list([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])\n        with self.assertRaises(ValueError):\n            chunk_list([1], 0)\n")
    add("deep_merge", "Fix deep_merge to recursively merge dictionaries without mutating inputs.", "def deep_merge(a, b):\n    a.update(b)\n    return a", "import unittest\nfrom subject import deep_merge\n\nclass TestSubject(unittest.TestCase):\n    def test_merge(self):\n        left = {'a': {'x': 1}, 'b': 2}\n        right = {'a': {'y': 3}}\n        self.assertEqual(deep_merge(left, right), {'a': {'x': 1, 'y': 3}, 'b': 2})\n        self.assertEqual(left, {'a': {'x': 1}, 'b': 2})\n")
    add("retry_delay", "Fix retry_delay to apply exponential backoff capped at max_delay.", "def retry_delay(attempt, base=1, max_delay=30):\n    return base * attempt", "import unittest\nfrom subject import retry_delay\n\nclass TestSubject(unittest.TestCase):\n    def test_delay(self):\n        self.assertEqual(retry_delay(1, base=2, max_delay=20), 2)\n        self.assertEqual(retry_delay(4, base=2, max_delay=20), 16)\n        self.assertEqual(retry_delay(10, base=2, max_delay=20), 20)\n")
    add("parse_timeout", "Fix parse_timeout_ms to parse integers optionally suffixed by ms and reject invalid values.", "def parse_timeout_ms(value):\n    return int(value)", "import unittest\nfrom subject import parse_timeout_ms\n\nclass TestSubject(unittest.TestCase):\n    def test_timeout(self):\n        self.assertEqual(parse_timeout_ms('300ms'), 300)\n        self.assertEqual(parse_timeout_ms(25), 25)\n        with self.assertRaises(ValueError):\n            parse_timeout_ms('0')\n")
    add("mask_email", "Fix mask_email to mask the local part while preserving first char and domain.", "def mask_email(email):\n    return email", "import unittest\nfrom subject import mask_email\n\nclass TestSubject(unittest.TestCase):\n    def test_email(self):\n        self.assertEqual(mask_email('alice@example.com'), 'a***@example.com')\n        self.assertEqual(mask_email('x@example.com'), 'x***@example.com')\n")
    add("dedup_rows", "Fix dedup_rows to drop duplicate dict rows by key while keeping first occurrences.", "def dedup_rows(rows, key):\n    return rows", "import unittest\nfrom subject import dedup_rows\n\nclass TestSubject(unittest.TestCase):\n    def test_dedup(self):\n        rows = [{'id': 1, 'v': 'a'}, {'id': 1, 'v': 'b'}, {'id': 2, 'v': 'c'}]\n        self.assertEqual(dedup_rows(rows, 'id'), [{'id': 1, 'v': 'a'}, {'id': 2, 'v': 'c'}])\n")
    add("rolling_sum", "Fix rolling_sum to return rolling window sums.", "def rolling_sum(values, window):\n    return values", "import unittest\nfrom subject import rolling_sum\n\nclass TestSubject(unittest.TestCase):\n    def test_rolling(self):\n        self.assertEqual(rolling_sum([1, 2, 3, 4], 3), [6, 9])\n")
    add("top_n", "Fix top_n to return the n largest values in descending order.", "def top_n(values, n):\n    return values[:n]", "import unittest\nfrom subject import top_n\n\nclass TestSubject(unittest.TestCase):\n    def test_top(self):\n        self.assertEqual(top_n([3, 1, 5, 2], 2), [5, 3])\n        self.assertEqual(top_n([1], 0), [])\n")
    add("parse_tags", "Fix parse_tags to split comma-separated tags, trim, lowercase, and remove empties.", "def parse_tags(text):\n    return text.split(',')", "import unittest\nfrom subject import parse_tags\n\nclass TestSubject(unittest.TestCase):\n    def test_tags(self):\n        self.assertEqual(parse_tags(' Alpha, beta,,ALPHA '), ['alpha', 'beta', 'alpha'])\n")
    add("validate_price", "Fix validate_price to accept positive finite numbers only.", "def validate_price(value):\n    return True", "import math\nimport unittest\nfrom subject import validate_price\n\nclass TestSubject(unittest.TestCase):\n    def test_price(self):\n        self.assertTrue(validate_price(1.2))\n        self.assertFalse(validate_price(0))\n        self.assertFalse(validate_price(math.inf))\n")
    add("median", "Fix median to compute median for odd/even non-empty sequences.", "def median(values):\n    return values[0]", "import unittest\nfrom subject import median\n\nclass TestSubject(unittest.TestCase):\n    def test_median(self):\n        self.assertEqual(median([3, 1, 2]), 2)\n        self.assertEqual(median([4, 1, 2, 3]), 2.5)\n        with self.assertRaises(ValueError):\n            median([])\n")
    add("coalesce", "Fix coalesce to return the first value that is not None.", "def coalesce(*values):\n    return values[0] if values else None", "import unittest\nfrom subject import coalesce\n\nclass TestSubject(unittest.TestCase):\n    def test_coalesce(self):\n        self.assertEqual(coalesce(None, 0, 'x'), 0)\n        self.assertIsNone(coalesce(None, None))\n")
    add("count_occurrences", "Fix count_occurrences to count exact item frequencies.", "def count_occurrences(items):\n    return set(items)", "import unittest\nfrom subject import count_occurrences\n\nclass TestSubject(unittest.TestCase):\n    def test_count(self):\n        self.assertEqual(count_occurrences(['a', 'b', 'a']), {'a': 2, 'b': 1})\n")
    add("strip_ansi", "Fix strip_ansi to remove common ANSI escape sequences.", "def strip_ansi(text):\n    return text", "import unittest\nfrom subject import strip_ansi\n\nclass TestSubject(unittest.TestCase):\n    def test_strip(self):\n        self.assertEqual(strip_ansi('\\x1b[31mred\\x1b[0m'), 'red')\n")
    add("json_pointer", "Fix read_pointer to read slash-separated JSON pointer paths.", "def read_pointer(data, pointer):\n    return data[pointer]", "import unittest\nfrom subject import read_pointer\n\nclass TestSubject(unittest.TestCase):\n    def test_pointer(self):\n        data = {'a': {'b/c': [10]}}\n        self.assertEqual(read_pointer(data, '/a/b~1c/0'), 10)\n        with self.assertRaises(KeyError):\n            read_pointer(data, '/missing')\n")
    add("stable_hash", "Fix stable_hash to hash JSON-serializable values independent of dict insertion order.", "def stable_hash(value):\n    return str(hash(value))", "import unittest\nfrom subject import stable_hash\n\nclass TestSubject(unittest.TestCase):\n    def test_hash(self):\n        self.assertEqual(stable_hash({'b': 2, 'a': 1}), stable_hash({'a': 1, 'b': 2}))\n        self.assertNotEqual(stable_hash({'a': 1}), stable_hash({'a': 2}))\n")
    add("window_pairs", "Fix window_pairs to return adjacent pairs from a sequence.", "def window_pairs(values):\n    return []", "import unittest\nfrom subject import window_pairs\n\nclass TestSubject(unittest.TestCase):\n    def test_pairs(self):\n        self.assertEqual(window_pairs([1, 2, 3]), [(1, 2), (2, 3)])\n")
    return specs
