from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from quantagent.coding_bench import (
    CodingBenchResult,
    CodingBenchRun,
    builtin_coding_bench_tasks,
    load_coding_bench_tasks,
    run_coding_bench,
)
from quantagent.learning_effect import (
    LearningEffectReport,
    LearningEffectTask,
    LearningRunner,
    LearningTaskResult,
    run_learning_effect_regression,
)


INVALID_CODING_BENCH_STATUSES = frozenset({"cheated", "invalid_fixture"})


@dataclass(frozen=True)
class LearningEffectCodingBenchReport:
    no_learning_run: CodingBenchRun
    approved_learning_run: CodingBenchRun
    learning_effect: LearningEffectReport

    def to_dict(self) -> dict[str, object]:
        return {
            "no_learning_run": self.no_learning_run.to_dict(),
            "approved_learning_run": self.approved_learning_run.to_dict(),
            "learning_effect": self.learning_effect.to_dict(),
        }


def coding_bench_result_to_learning_task_result(result: CodingBenchResult) -> LearningTaskResult:
    invalid_reason = ""
    if result.status in INVALID_CODING_BENCH_STATUSES:
        invalid_reason = f"coding_bench:{result.status}"
    return LearningTaskResult(
        task_id=result.task_id,
        solved=result.solved and not invalid_reason,
        steps=max(0, result.iterations),
        failure_class=result.failure_class or ("" if result.solved else result.status),
        evidence=_result_evidence(result),
        invalid_reason=invalid_reason,
    )


def make_learning_effect_coding_bench_runner(
    no_learning_run: CodingBenchRun,
    approved_learning_run: CodingBenchRun,
) -> LearningRunner:
    no_learning_results = _results_by_task(no_learning_run)
    approved_results = _results_by_task(approved_learning_run)

    def runner(task: LearningEffectTask, approved_learning: bool) -> LearningTaskResult:
        result_map = approved_results if approved_learning else no_learning_results
        result = result_map.get(task.id)
        if result is None:
            mode = "approved-learning" if approved_learning else "no-learning"
            return LearningTaskResult(
                task_id=task.id,
                solved=False,
                steps=0,
                failure_class="missing_result",
                invalid_reason=f"{mode} CodingBench result missing",
            )
        return coding_bench_result_to_learning_task_result(result)

    return runner


def run_learning_effect_coding_bench(
    project: str | Path,
    *,
    no_learning_agent_command: str,
    approved_learning_agent_command: str,
    task_file: str | Path | None = None,
    limit: int | None = None,
    keep_workspaces: bool = False,
) -> LearningEffectCodingBenchReport:
    _validate_real_agent_command(no_learning_agent_command, "no_learning_agent_command")
    _validate_real_agent_command(approved_learning_agent_command, "approved_learning_agent_command")

    no_learning_run = run_coding_bench(
        project,
        agent_command=no_learning_agent_command,
        task_file=task_file,
        limit=limit,
        keep_workspaces=keep_workspaces,
    )
    approved_learning_run = run_coding_bench(
        project,
        agent_command=approved_learning_agent_command,
        task_file=task_file,
        limit=limit,
        keep_workspaces=keep_workspaces,
    )
    tasks = _learning_tasks(task_file=task_file, limit=limit)
    runner = make_learning_effect_coding_bench_runner(no_learning_run, approved_learning_run)
    return LearningEffectCodingBenchReport(
        no_learning_run=no_learning_run,
        approved_learning_run=approved_learning_run,
        learning_effect=run_learning_effect_regression(tasks, runner),
    )


def _learning_tasks(*, task_file: str | Path | None, limit: int | None) -> tuple[LearningEffectTask, ...]:
    coding_tasks = load_coding_bench_tasks(task_file) if task_file else builtin_coding_bench_tasks()
    if limit is not None:
        coding_tasks = coding_tasks[: max(limit, 0)]
    return tuple(LearningEffectTask(task.id, task.instruction, task.tags) for task in coding_tasks)


def _results_by_task(run: CodingBenchRun) -> Mapping[str, CodingBenchResult]:
    results: dict[str, CodingBenchResult] = {}
    for result in run.results:
        results[result.task_id] = result
    return results


def _validate_real_agent_command(command: str, field: str) -> None:
    if not command or not command.strip():
        raise ValueError(f"{field} is required for real CodingBench learning-effect comparison")
    if command.strip() == "openmako-self-agent":
        raise ValueError(f"{field} cannot use built-in canned CodingBench agents")


def _result_evidence(result: CodingBenchResult) -> tuple[str, ...]:
    evidence = [
        f"coding_bench status={result.status}",
        f"iterations={result.iterations}",
    ]
    if result.message:
        evidence.append(result.message)
    if result.baseline.returncode is not None:
        evidence.append(f"baseline_returncode={result.baseline.returncode}")
    if result.attempts:
        last_attempt = result.attempts[-1]
        evidence.append(f"last_validation_returncode={last_attempt.validation.returncode}")
        if last_attempt.validation.timed_out:
            evidence.append("last_validation_timed_out=true")
    if result.patch_metrics.out_of_scope_files:
        evidence.append("out_of_scope_files=" + ",".join(result.patch_metrics.out_of_scope_files))
    return tuple(evidence)
