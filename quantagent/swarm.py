from __future__ import annotations

import json
import shlex
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Sequence

from .edit_loop import PatchPlan
from .query_runtime import QueryRuntime
from .repair_scheduler import RepairWorkerResult, run_multi_worker_repair
from .review_arbitration import ArbitrationDecision, arbitrate_parent_reviews
from .structured_diff_preview import create_preview_from_isolation_review
from .worktree_isolation import (
    IsolatedRunResult,
    create_isolated_worktree,
    create_isolation_review,
    run_in_isolated_worktree,
)


DEFAULT_SWARM_WORKER_COMMAND = (
    "python3 -m quantagent.cli --no-trust-prompt agent-v3 --project . "
    "--no-validate --stop-on-failure {task}"
)


@dataclass(frozen=True)
class SwarmCommandResult:
    command: list[str] = field(default_factory=list)
    ok: bool = True
    returncode: int = 0
    duration_ms: int = 0
    stdout_preview: str = ""
    stderr_preview: str = ""
    blocked: bool = False
    reason: str = ""
    sandbox_backend: str = ""
    network_policy: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SwarmWorkerBundle:
    run_id: str
    worker_id: str
    worker_index: int
    ok: bool
    summary: str
    score: int
    recommendation: str
    worktree_id: str = ""
    workspace_path: str = ""
    review_id: str = ""
    changed_paths: list[str] = field(default_factory=list)
    new_paths: list[str] = field(default_factory=list)
    deleted_paths: list[str] = field(default_factory=list)
    high_risk_paths: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    approval_required: bool = False
    rounds: int = 0
    preview_id: str = ""
    preview_path: str = ""
    diagnostics: list[str] = field(default_factory=list)
    worker_command: SwarmCommandResult | None = None
    tests: list[SwarmCommandResult] = field(default_factory=list)
    failure_reason: str = ""
    bundle_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.worker_command is not None:
            data["worker_command"] = self.worker_command.to_dict()
        data["tests"] = [test.to_dict() for test in self.tests]
        return data


@dataclass(frozen=True)
class SwarmRun:
    run_id: str
    project: str
    task: str
    ok: bool
    workers: list[SwarmWorkerBundle]
    arbitration: ArbitrationDecision
    mode: str = "command"
    winner_worker_id: str = ""
    winner_review_id: str = ""
    run_dir: str = ""
    battle_report_path: str = ""
    scheduler_result_path: str = ""
    arbitration_path: str = ""
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "project": self.project,
            "task": self.task,
            "ok": self.ok,
            "mode": self.mode,
            "summary": self.summary,
            "workers": [worker.to_dict() for worker in self.workers],
            "arbitration": self.arbitration.to_dict(),
            "winner_worker_id": self.winner_worker_id,
            "winner_review_id": self.winner_review_id,
            "run_dir": self.run_dir,
            "battle_report_path": self.battle_report_path,
            "scheduler_result_path": self.scheduler_result_path,
            "arbitration_path": self.arbitration_path,
        }


ClientFactory = Callable[[str], Any]


def run_swarm(
    project: str | Path,
    task: str,
    *,
    workers: int = 3,
    worker_command: str | Sequence[str] | None = None,
    test_command: str | Sequence[str] | None = None,
    timeout: int = 120,
    sandbox_backend: str = "auto",
    network: bool = False,
    allow_risky_worker: bool = False,
    allow_risky_test: bool = False,
    agent_profile: str = "build",
    use_default_worker: bool = True,
) -> SwarmRun:
    project_path = Path(project).expanduser().resolve(strict=False)
    run_id = "swarm-" + uuid.uuid4().hex[:12]
    run_dir = swarm_run_dir(project_path, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    worker_count = max(1, int(workers or 1))
    worker_template = worker_command
    if worker_template is None and use_default_worker:
        worker_template = DEFAULT_SWARM_WORKER_COMMAND

    runtime = QueryRuntime(project_path)
    runtime.emit(
        "swarm_start",
        f"swarm started: {task}",
        ok=True,
        data={
            "run_id": run_id,
            "workers": worker_count,
            "test_command": test_command,
            "worker_command": worker_template,
        },
    )

    bundles: list[SwarmWorkerBundle] = []
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = {
            pool.submit(
                _run_worker,
                project_path,
                run_id,
                task,
                worker_id=f"worker-{index}",
                worker_index=index,
                run_dir=run_dir,
                worker_command=worker_template,
                test_command=test_command,
                timeout=timeout,
                sandbox_backend=sandbox_backend,
                network=network,
                allow_risky_worker=allow_risky_worker,
                allow_risky_test=allow_risky_test,
                agent_profile=agent_profile,
            ): index
            for index in range(1, worker_count + 1)
        }
        for future in as_completed(futures):
            try:
                bundles.append(future.result())
            except Exception as exc:  # pragma: no cover - worker boundary defense
                index = futures[future]
                bundles.append(
                    SwarmWorkerBundle(
                        run_id=run_id,
                        worker_id=f"worker-{index}",
                        worker_index=index,
                        ok=False,
                        summary=f"{type(exc).__name__}: {exc}",
                        score=0,
                        recommendation="discard",
                        failure_reason=f"{type(exc).__name__}: {exc}",
                    )
                )

    ranked_bundles = sorted(bundles, key=_bundle_sort_key)
    repair_workers = [_repair_worker_from_bundle(bundle) for bundle in ranked_bundles if bundle.review_id]
    arbitration = arbitrate_parent_reviews(project=project_path, workers=repair_workers, profile=agent_profile)
    winner_review_id = arbitration.recommended_review_id
    winner_worker_id = _worker_id_for_review(ranked_bundles, winner_review_id)
    ok = any(worker.ok for worker in ranked_bundles)
    run = SwarmRun(
        run_id=run_id,
        project=str(project_path),
        task=task,
        ok=ok,
        workers=ranked_bundles,
        arbitration=arbitration,
        mode="command",
        winner_worker_id=winner_worker_id,
        winner_review_id=winner_review_id,
        run_dir=str(run_dir),
        battle_report_path=str(run_dir / "battle_report.md"),
        arbitration_path=str(run_dir / "arbitration.json"),
        summary=f"{sum(1 for worker in ranked_bundles if worker.ok)}/{len(ranked_bundles)} worker candidate(s) passed",
    )
    report = render_swarm_battle_report(run, duration_ms=round((time.monotonic() - started) * 1000))
    Path(run.battle_report_path).write_text(report, encoding="utf-8")
    Path(run.arbitration_path).write_text(json.dumps(arbitration.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (run_dir / "swarm_run.json").write_text(json.dumps(run.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    runtime.emit(
        "swarm_stop",
        f"swarm finished: winner={winner_worker_id or '-'}",
        ok=ok,
        data={
            "run_id": run_id,
            "winner_worker_id": winner_worker_id,
            "winner_review_id": winner_review_id,
            "battle_report_path": run.battle_report_path,
        },
    )
    return run


def run_repair_swarm(
    project: str | Path,
    plan: PatchPlan,
    failure_output: str,
    *,
    workers: int = 3,
    max_rounds: int = 3,
    model: str = "",
    base_url: str | None = None,
    timeout: int = 120,
    client_factory: ClientFactory | None = None,
    agent_profile: str = "build",
) -> SwarmRun:
    """Run concurrent isolated repair loops and return the parent-ranked review."""
    project_path = Path(project).expanduser().resolve(strict=False)
    run_id = "swarm-" + uuid.uuid4().hex[:12]
    run_dir = swarm_run_dir(project_path, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    worker_count = max(1, int(workers or 1))
    runtime = QueryRuntime(project_path)
    runtime.emit(
        "swarm_start",
        f"repair swarm started: {plan.task}",
        ok=True,
        data={
            "run_id": run_id,
            "mode": "repair_loop",
            "workers": worker_count,
            "max_rounds": max_rounds,
            "model": model,
        },
    )
    started = time.monotonic()
    scheduler_result = run_multi_worker_repair(
        project_path,
        plan,
        failure_output,
        workers=worker_count,
        max_rounds=max_rounds,
        model=model,
        base_url=base_url,
        timeout=timeout,
        client_factory=client_factory,
        profile=agent_profile,
    )
    ranked_bundles = [
        _swarm_bundle_from_repair_worker(run_id, worker, worker_index=index)
        for index, worker in enumerate(scheduler_result.workers, start=1)
    ]
    persisted_bundles: list[SwarmWorkerBundle] = []
    for bundle in ranked_bundles:
        bundle_path = run_dir / f"{bundle.worker_id}_bundle.json"
        persisted = replace(bundle, bundle_path=str(bundle_path))
        bundle_path.write_text(json.dumps(persisted.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        persisted_bundles.append(persisted)
    arbitration = arbitrate_parent_reviews(project=project_path, result=scheduler_result, profile=agent_profile)
    winner_review_id = arbitration.recommended_review_id
    winner_worker_id = _worker_id_for_review(persisted_bundles, winner_review_id) or scheduler_result.bundle.recommended_worker
    ok = scheduler_result.ok and arbitration.apply_gate_ready
    run = SwarmRun(
        run_id=run_id,
        project=str(project_path),
        task=plan.task,
        ok=ok,
        workers=persisted_bundles,
        arbitration=arbitration,
        mode="repair_loop",
        winner_worker_id=winner_worker_id,
        winner_review_id=winner_review_id,
        run_dir=str(run_dir),
        battle_report_path=str(run_dir / "battle_report.md"),
        scheduler_result_path=str(run_dir / "repair_scheduler.json"),
        arbitration_path=str(run_dir / "arbitration.json"),
        summary=scheduler_result.summary,
    )
    Path(run.scheduler_result_path).write_text(json.dumps(scheduler_result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    Path(run.arbitration_path).write_text(json.dumps(arbitration.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = render_swarm_battle_report(run, duration_ms=round((time.monotonic() - started) * 1000))
    Path(run.battle_report_path).write_text(report, encoding="utf-8")
    (run_dir / "swarm_run.json").write_text(json.dumps(run.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    runtime.emit(
        "swarm_stop",
        f"repair swarm finished: winner={winner_worker_id or '-'}",
        ok=ok,
        data={
            "run_id": run_id,
            "mode": "repair_loop",
            "winner_worker_id": winner_worker_id,
            "winner_review_id": winner_review_id,
            "battle_report_path": run.battle_report_path,
        },
    )
    return run


def render_swarm_run(run: SwarmRun) -> str:
    return Path(run.battle_report_path).read_text(encoding="utf-8") if run.battle_report_path and Path(run.battle_report_path).exists() else render_swarm_battle_report(run)


def render_swarm_battle_report(run: SwarmRun, *, duration_ms: int = 0) -> str:
    lines = [
        "# OpenMako Swarm Battle Report",
        "",
        f"- run_id: {run.run_id}",
        f"- mode: {run.mode}",
        f"- task: {run.task}",
        f"- workers: {len(run.workers)}",
        f"- ok: {str(run.ok).lower()}",
        f"- winner_worker: {run.winner_worker_id or '-'}",
        f"- winner_review: {run.winner_review_id or '-'}",
    ]
    if run.summary:
        lines.append(f"- summary: {run.summary}")
    if duration_ms:
        lines.append(f"- duration_ms: {duration_ms}")
    lines.extend(["", "## Ranking", ""])
    if not run.workers:
        lines.append("- No workers ran.")
    for index, worker in enumerate(run.workers, start=1):
        mark = "ok" if worker.ok else "fail"
        paths = len(worker.changed_paths) + len(worker.new_paths) + len(worker.deleted_paths)
        review = worker.review_id or "-"
        lines.append(
            f"{index}. {worker.worker_id} [{mark}] score={worker.score} review={review} "
            f"paths={paths} recommendation={worker.recommendation}: {worker.summary}"
        )
        if worker.preview_id:
            lines.append(f"   - preview: {worker.preview_id}")
        if worker.rounds:
            lines.append(f"   - rounds: {worker.rounds}")
        if worker.failure_reason:
            lines.append(f"   - failure: {worker.failure_reason}")
        if worker.high_risk_paths:
            lines.append(f"   - high_risk: {', '.join(worker.high_risk_paths)}")
        if worker.diagnostics:
            lines.append(f"   - diagnostics: {' | '.join(worker.diagnostics[:3])}")
        if worker.tests:
            tests = ", ".join("ok" if test.ok else f"fail({test.returncode})" for test in worker.tests)
            lines.append(f"   - tests: {tests}")
    lines.extend(["", "## Parent Arbitration", ""])
    lines.append(f"- recommended_review_id: {run.arbitration.recommended_review_id or '-'}")
    lines.append(f"- apply_gate_ready: {str(run.arbitration.apply_gate_ready).lower()}")
    lines.append(f"- approval_required: {str(run.arbitration.approval_required).lower()}")
    if run.arbitration.risk_flags:
        lines.append(f"- risk_flags: {', '.join(run.arbitration.risk_flags)}")
    if run.arbitration.reasons:
        lines.extend(["", "## Reasons", ""])
        lines.extend(f"- {reason}" for reason in run.arbitration.reasons)
    lines.extend(["", "## Merge Recommendation", ""])
    if run.winner_review_id:
        lines.append(f"Recommended: inspect/apply `{run.winner_review_id}` after review gate approval.")
    else:
        lines.append("Recommended: do not merge; no review candidate survived.")
    return "\n".join(lines).rstrip() + "\n"


def swarm_root(project: str | Path) -> Path:
    project_path = Path(project).expanduser().resolve(strict=False)
    base = project_path / "AI_协作交接"
    if not base.exists():
        base = project_path / ".quantagent"
    return base / "quantagent_swarms"


def swarm_run_dir(project: str | Path, run_id: str) -> Path:
    return swarm_root(project) / run_id


def _run_worker(
    project: Path,
    run_id: str,
    task: str,
    *,
    worker_id: str,
    worker_index: int,
    run_dir: Path,
    worker_command: str | Sequence[str] | None,
    test_command: str | Sequence[str] | None,
    timeout: int,
    sandbox_backend: str,
    network: bool,
    allow_risky_worker: bool,
    allow_risky_test: bool,
    agent_profile: str,
) -> SwarmWorkerBundle:
    worktree = create_isolated_worktree(project, reason=f"swarm {run_id} {worker_id}: {task}")
    workspace = Path(worktree.workspace_path)
    worker_args = _prepare_command(worker_command, task=task, run_id=run_id, worker_id=worker_id, worker_index=worker_index, workspace=str(workspace))
    test_args = _prepare_command(test_command, task=task, run_id=run_id, worker_id=worker_id, worker_index=worker_index, workspace=str(workspace))
    worker_result: SwarmCommandResult | None = None
    if worker_args:
        worker_result = _run_command_result(
            project,
            worker_args,
            worktree_id=worktree.worktree_id,
            timeout=timeout,
            sandbox_backend=sandbox_backend,
            network=network,
            allow_risky=allow_risky_worker,
        )
    tests: list[SwarmCommandResult] = []
    if test_args:
        tests.append(
            _run_command_result(
                project,
                test_args,
                worktree_id=worktree.worktree_id,
                timeout=timeout,
                sandbox_backend=sandbox_backend,
                network=network,
                allow_risky=allow_risky_test,
            )
        )
    review = create_isolation_review(project, worktree.worktree_id)
    changed_paths = sorted(set(review.changed_paths))
    new_paths = sorted(set(review.new_paths))
    deleted_paths = sorted(set(review.deleted_paths))
    preview = create_preview_from_isolation_review(project, review, task=task, test_command=test_args, profile=agent_profile)
    high_risk_paths = sorted({item.path for item in preview.files if item.risk == "high"})
    ok = (worker_result.ok if worker_result is not None else True) and all(test.ok for test in tests)
    failure_reason = _failure_reason(worker_result, tests)
    score = _score_worker_bundle(
        ok=ok,
        worker_result=worker_result,
        tests=tests,
        changed_count=len(changed_paths) + len(new_paths) + len(deleted_paths),
        high_risk_count=len(high_risk_paths),
        approval_required=preview.approval_required,
    )
    recommendation = _recommendation(ok, review_id=review.review_id, changed_count=len(changed_paths) + len(new_paths) + len(deleted_paths))
    summary = _worker_summary(ok, worker_result, tests, changed_count=len(changed_paths) + len(new_paths) + len(deleted_paths))
    bundle = SwarmWorkerBundle(
        run_id=run_id,
        worker_id=worker_id,
        worker_index=worker_index,
        ok=ok,
        summary=summary,
        score=score,
        recommendation=recommendation,
        worktree_id=worktree.worktree_id,
        workspace_path=str(workspace),
        review_id=review.review_id,
        changed_paths=changed_paths,
        new_paths=new_paths,
        deleted_paths=deleted_paths,
        high_risk_paths=high_risk_paths,
        risks=list(preview.risks),
        approval_required=preview.approval_required,
        preview_id=preview.preview_id,
        rounds=1 if worker_result else 0,
        worker_command=worker_result,
        tests=tests,
        failure_reason=failure_reason,
    )
    bundle_path = run_dir / f"{worker_id}_bundle.json"
    persisted = replace(bundle, bundle_path=str(bundle_path))
    bundle_path.write_text(json.dumps(persisted.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return persisted


def _run_command_result(
    project: Path,
    command: Sequence[str],
    *,
    worktree_id: str,
    timeout: int,
    sandbox_backend: str,
    network: bool,
    allow_risky: bool,
) -> SwarmCommandResult:
    result = run_in_isolated_worktree(
        project,
        command,
        worktree_id=worktree_id,
        timeout=timeout,
        allow_risky=allow_risky,
        sandbox_backend=sandbox_backend,
        network=network,
    )
    return _command_result_from_isolated(command, result)


def _prepare_command(
    command: str | Sequence[str] | None,
    *,
    task: str,
    run_id: str,
    worker_id: str,
    worker_index: int,
    workspace: str,
) -> list[str]:
    if command is None:
        return []
    values = _CommandFormatValues(
        {
            "task": shlex.quote(task),
            "task_text": task,
            "run_id": run_id,
            "worker_id": worker_id,
            "worker_index": str(worker_index),
            "workspace": workspace,
        }
    )
    if isinstance(command, str):
        rendered = command.format_map(values).strip()
        return shlex.split(rendered) if rendered else []
    return [str(item).format_map(values) for item in command if str(item)]


class _CommandFormatValues(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _command_result_from_isolated(command: Sequence[str], result: IsolatedRunResult) -> SwarmCommandResult:
    return SwarmCommandResult(
        command=[str(item) for item in command],
        ok=result.ok,
        returncode=result.returncode,
        duration_ms=result.duration_ms,
        stdout_preview=result.stdout_preview,
        stderr_preview=result.stderr_preview,
        blocked=result.blocked,
        reason=result.reason,
        sandbox_backend=result.sandbox_backend,
        network_policy=result.network_policy,
    )


def _score_worker_bundle(
    *,
    ok: bool,
    worker_result: SwarmCommandResult | None,
    tests: Sequence[SwarmCommandResult],
    changed_count: int,
    high_risk_count: int,
    approval_required: bool,
) -> int:
    score = 0
    if tests:
        score += 40 if all(test.ok for test in tests) else 0
    elif ok:
        score += 10
    if changed_count == 0:
        score += 8
    elif changed_count <= 2:
        score += 20
    elif changed_count <= 5:
        score += 15
    else:
        score += 8
    if high_risk_count == 0:
        score += 15
    else:
        score += max(0, 15 - min(15, high_risk_count * 5))
    score += 10
    if not ((worker_result and worker_result.blocked) or any(test.blocked for test in tests)):
        score += 10
    if _total_duration_ms(worker_result, tests) <= 120_000:
        score += 5
    if not ok:
        score = min(score, 45)
    if approval_required:
        score -= 3
    return max(0, min(100, score))


def _total_duration_ms(worker_result: SwarmCommandResult | None, tests: Sequence[SwarmCommandResult]) -> int:
    return (worker_result.duration_ms if worker_result else 0) + sum(test.duration_ms for test in tests)


def _failure_reason(worker_result: SwarmCommandResult | None, tests: Sequence[SwarmCommandResult]) -> str:
    if worker_result is not None and not worker_result.ok:
        return worker_result.reason or worker_result.stderr_preview or f"worker command exited {worker_result.returncode}"
    for test in tests:
        if not test.ok:
            return test.reason or test.stderr_preview or f"test exited {test.returncode}"
    return ""


def _worker_summary(ok: bool, worker_result: SwarmCommandResult | None, tests: Sequence[SwarmCommandResult], *, changed_count: int) -> str:
    command_state = "worker command skipped" if worker_result is None else ("worker command passed" if worker_result.ok else "worker command failed")
    test_state = "no tests" if not tests else ("tests passed" if all(test.ok for test in tests) else "tests failed")
    state = "candidate ok" if ok else "candidate failed"
    return f"{state}; {command_state}; {test_state}; changed_paths={changed_count}"


def _recommendation(ok: bool, *, review_id: str, changed_count: int) -> str:
    if not ok:
        return "discard"
    if not review_id or changed_count == 0:
        return "inspect"
    return "merge_candidate"


def _bundle_sort_key(bundle: SwarmWorkerBundle) -> tuple[int, int, int, str]:
    changed_count = len(bundle.changed_paths) + len(bundle.new_paths) + len(bundle.deleted_paths)
    return (-bundle.score, 0 if bundle.ok else 1, changed_count, bundle.worker_id)


def _repair_worker_from_bundle(bundle: SwarmWorkerBundle) -> RepairWorkerResult:
    return RepairWorkerResult(
        worker_id=bundle.worker_id,
        ok=bundle.ok,
        summary=bundle.summary,
        review_id=bundle.review_id,
        worktree_id=bundle.worktree_id,
        changed_paths=sorted(set([*bundle.changed_paths, *bundle.new_paths, *bundle.deleted_paths])),
        rounds=bundle.rounds or (1 if bundle.worker_command else 0),
        score=bundle.score,
        error=bundle.failure_reason,
        preview_id=bundle.preview_id,
        preview_path=bundle.preview_path,
        approval_required=bundle.approval_required,
        high_risk_paths=bundle.high_risk_paths,
        diagnostics=bundle.diagnostics,
    )


def _swarm_bundle_from_repair_worker(run_id: str, worker: RepairWorkerResult, *, worker_index: int) -> SwarmWorkerBundle:
    return SwarmWorkerBundle(
        run_id=run_id,
        worker_id=worker.worker_id,
        worker_index=worker_index,
        ok=worker.ok,
        summary=worker.summary,
        score=worker.score,
        recommendation="merge_candidate" if worker.ok and worker.review_id else "discard",
        worktree_id=worker.worktree_id,
        review_id=worker.review_id,
        changed_paths=sorted(set(worker.changed_paths)),
        high_risk_paths=sorted(set(worker.high_risk_paths)),
        approval_required=worker.approval_required,
        rounds=worker.rounds,
        preview_id=worker.preview_id,
        preview_path=worker.preview_path,
        diagnostics=list(worker.diagnostics),
        failure_reason=worker.error,
    )


def _worker_id_for_review(workers: Sequence[SwarmWorkerBundle], review_id: str) -> str:
    if not review_id:
        return ""
    for worker in workers:
        if worker.review_id == review_id:
            return worker.worker_id
    return ""
