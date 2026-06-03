from __future__ import annotations

import json
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence, Union


LearningRunner = Callable[["LearningEffectTask", bool], "LearningTaskResult | Mapping[str, Any]"]
CommandTemplate = Union[str, Sequence[str]]


@dataclass(frozen=True)
class LearningEffectTask:
    id: str
    instruction: str
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "instruction": self.instruction, "tags": list(self.tags)}


@dataclass(frozen=True)
class LearningTaskResult:
    task_id: str
    solved: bool
    steps: int
    failure_class: str = ""
    evidence: tuple[str, ...] = ()
    invalid_reason: str = ""

    @property
    def valid(self) -> bool:
        return not self.invalid_reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "solved": self.solved,
            "steps": self.steps,
            "failure_class": self.failure_class,
            "evidence": list(self.evidence),
            "invalid_reason": self.invalid_reason,
        }


@dataclass(frozen=True)
class LearningTaskComparison:
    task_id: str
    no_learning: LearningTaskResult
    approved_learning: LearningTaskResult
    score_delta: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "no_learning": self.no_learning.to_dict(),
            "approved_learning": self.approved_learning.to_dict(),
            "score_delta": self.score_delta,
        }


@dataclass(frozen=True)
class LearningEffectReport:
    status: str
    total: int
    solved: dict[str, int]
    steps: dict[str, int]
    failure_class: dict[str, str]
    score_delta: float
    comparisons: tuple[LearningTaskComparison, ...]
    gap: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "total": self.total,
            "solved": dict(self.solved),
            "steps": dict(self.steps),
            "failure_class": dict(self.failure_class),
            "score_delta": self.score_delta,
            "gap": self.gap,
            "comparisons": [comparison.to_dict() for comparison in self.comparisons],
        }


@dataclass(frozen=True)
class LearningEffectCommandRunner:
    no_learning_command: CommandTemplate
    approved_learning_command: CommandTemplate
    task_file: str = ""
    project: str = ""
    python: str = sys.executable
    timeout_seconds: float = 120.0

    def __call__(self, task: LearningEffectTask, approved_learning: bool) -> LearningTaskResult:
        mode = "approved-learning" if approved_learning else "no-learning"
        template = self.approved_learning_command if approved_learning else self.no_learning_command
        command = _format_command_template(
            template,
            task=task,
            mode=mode,
            learning_enabled=approved_learning,
            project=self.project,
            task_file=self.task_file,
            python=self.python,
        )
        return _run_learning_command(command, task_id=task.id, timeout_seconds=self.timeout_seconds)


def load_learning_effect_tasks(task_file: str | Path) -> tuple[LearningEffectTask, ...]:
    path = Path(task_file)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid learning effect task JSON: {exc.msg}") from exc
    if isinstance(payload, Mapping):
        payload = payload.get("tasks")
    if not isinstance(payload, list):
        raise ValueError("learning effect task file must be a list or object with tasks list")
    return tuple(_normalize_task(task) for task in payload)


def create_learning_command_runner(
    *,
    no_learning_command: CommandTemplate,
    approved_learning_command: CommandTemplate,
    task_file: str | Path = "",
    project: str | Path = "",
    python: str | Path = sys.executable,
    timeout_seconds: float = 120.0,
) -> LearningEffectCommandRunner:
    return LearningEffectCommandRunner(
        no_learning_command=no_learning_command,
        approved_learning_command=approved_learning_command,
        task_file=str(task_file),
        project=str(project),
        python=str(python),
        timeout_seconds=timeout_seconds,
    )


def run_learning_effect_command_regression(
    *,
    task_file: str | Path,
    no_learning_command: CommandTemplate,
    approved_learning_command: CommandTemplate,
    project: str | Path = "",
    python: str | Path = sys.executable,
    timeout_seconds: float = 120.0,
) -> LearningEffectReport:
    tasks = load_learning_effect_tasks(task_file)
    runner = create_learning_command_runner(
        no_learning_command=no_learning_command,
        approved_learning_command=approved_learning_command,
        task_file=task_file,
        project=project,
        python=python,
        timeout_seconds=timeout_seconds,
    )
    return run_learning_effect_regression(tasks, runner)


def run_learning_effect_regression(
    tasks: Iterable[LearningEffectTask | Mapping[str, Any]],
    runner: LearningRunner,
) -> LearningEffectReport:
    normalized_tasks = tuple(_normalize_task(task) for task in tasks)
    if not normalized_tasks:
        return _failed_report("invalid_sample: no tasks supplied")
    duplicate = _first_duplicate(task.id for task in normalized_tasks)
    if duplicate:
        return _failed_report(f"invalid_sample: duplicate task id {duplicate}")

    comparisons: list[LearningTaskComparison] = []
    invalid_reasons: list[str] = []
    for task in normalized_tasks:
        no_learning = _normalize_result(runner(task, False), task_id=task.id)
        approved = _normalize_result(runner(task, True), task_id=task.id)
        no_learning_invalid = _invalid_result_reasons(no_learning, task_id=task.id, mode="no-learning")
        approved_invalid = _invalid_result_reasons(approved, task_id=task.id, mode="approved-learning")
        if _only_cache_or_docs_improved(no_learning, approved):
            approved_invalid.append("approved-learning improvement is cache/documentation-only")
        if no_learning_invalid:
            invalid_reasons.extend(f"{task.id}: {reason}" for reason in no_learning_invalid)
            no_learning = _invalidate_result(no_learning, "; ".join(no_learning_invalid))
        if approved_invalid:
            invalid_reasons.extend(f"{task.id}: {reason}" for reason in approved_invalid)
            approved = _invalidate_result(approved, "; ".join(approved_invalid))
        comparisons.append(
            LearningTaskComparison(
                task_id=task.id,
                no_learning=no_learning,
                approved_learning=approved,
                score_delta=round(_score(approved) - _score(no_learning), 4),
            )
        )

    report = _build_report(comparisons)
    if invalid_reasons:
        return _replace_status(report, "fail", "invalid_sample: " + "; ".join(invalid_reasons[:3]))
    if report.score_delta <= 0:
        return _replace_status(report, "fail", "no approved-learning improvement over no-learning baseline")
    return _replace_status(report, "pass", "")


def render_learning_effect_json(report: LearningEffectReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _normalize_task(task: LearningEffectTask | Mapping[str, Any]) -> LearningEffectTask:
    if isinstance(task, LearningEffectTask):
        if not task.id.strip():
            raise ValueError("learning effect task id is required")
        if not task.instruction.strip():
            raise ValueError(f"learning effect task {task.id} instruction is required")
        return task
    task_id = str(task.get("id") or "").strip()
    instruction = str(task.get("instruction") or "").strip()
    if not task_id:
        raise ValueError("learning effect task id is required")
    if not instruction:
        raise ValueError(f"learning effect task {task_id} instruction is required")
    return LearningEffectTask(task_id, instruction, tuple(str(tag) for tag in task.get("tags", ())))


def _normalize_result(result: LearningTaskResult | Mapping[str, Any], *, task_id: str) -> LearningTaskResult:
    if isinstance(result, LearningTaskResult):
        return result
    if not isinstance(result, Mapping):
        raise TypeError("learning runner must return LearningTaskResult or mapping")
    evidence = result.get("evidence") or ()
    if isinstance(evidence, str):
        evidence_items = (evidence,)
    else:
        evidence_items = tuple(str(item) for item in evidence if str(item).strip())
    return LearningTaskResult(
        task_id=str(result.get("task_id") or task_id),
        solved=bool(result.get("solved")),
        steps=max(0, int(result.get("steps") or 0)),
        failure_class=str(result.get("failure_class") or ""),
        evidence=evidence_items,
        invalid_reason=str(result.get("invalid_reason") or ""),
    )


def _format_command_template(
    template: CommandTemplate,
    *,
    task: LearningEffectTask,
    mode: str,
    learning_enabled: bool,
    project: str,
    task_file: str,
    python: str,
) -> str | list[str]:
    raw_values = {
        "task_id": task.id,
        "instruction": task.instruction,
        "mode": mode,
        "learning_enabled": "true" if learning_enabled else "false",
        "project": project,
        "task_file": task_file,
        "python": python,
    }
    if isinstance(template, str):
        values = {key: shlex.quote(value) for key, value in raw_values.items()}
        return _replace_command_placeholders(template, values)
    return [_replace_command_placeholders(str(item), raw_values) for item in template]


def _replace_command_placeholders(value: str, replacements: Mapping[str, str]) -> str:
    rendered = value
    for key, replacement in replacements.items():
        rendered = rendered.replace("{" + key + "}", replacement)
    return rendered


def _run_learning_command(command: str | Sequence[str], *, task_id: str, timeout_seconds: float) -> LearningTaskResult:
    try:
        completed = subprocess.run(
            command,
            check=False,
            shell=isinstance(command, str),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return LearningTaskResult(
            task_id=task_id,
            solved=False,
            steps=0,
            failure_class="timeout",
            evidence=_command_evidence(exc.stdout, exc.stderr),
            invalid_reason=f"command_timeout: exceeded {timeout_seconds:g}s",
        )

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    if completed.returncode != 0:
        return LearningTaskResult(
            task_id=task_id,
            solved=False,
            steps=0,
            failure_class="command_failed",
            evidence=_command_evidence(stdout, stderr),
            invalid_reason=f"command_failed: exit code {completed.returncode}",
        )

    parsed = _parse_command_output(stdout, task_id=task_id)
    if parsed is not None:
        return parsed
    return LearningTaskResult(
        task_id=task_id,
        solved=False,
        steps=0,
        failure_class="text_output",
        evidence=_command_evidence(stdout, stderr),
    )


def _parse_command_output(stdout: str, *, task_id: str) -> LearningTaskResult | None:
    if not stdout:
        return LearningTaskResult(
            task_id=task_id,
            solved=False,
            steps=0,
            failure_class="empty_output",
            invalid_reason="empty_command_output",
        )
    if stdout[0] not in "{[":
        return None
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return LearningTaskResult(
            task_id=task_id,
            solved=False,
            steps=0,
            failure_class="invalid_json",
            evidence=(stdout[:500],),
            invalid_reason=f"invalid_json_output: {exc.msg}",
        )
    if not isinstance(payload, Mapping):
        return LearningTaskResult(
            task_id=task_id,
            solved=False,
            steps=0,
            failure_class="invalid_json",
            invalid_reason="invalid_json_output: expected object",
        )
    try:
        return _normalize_result(payload, task_id=task_id)
    except (TypeError, ValueError) as exc:
        return LearningTaskResult(
            task_id=task_id,
            solved=False,
            steps=0,
            failure_class="invalid_json",
            invalid_reason=f"invalid_json_output: {exc}",
        )


def _command_evidence(stdout: object, stderr: object) -> tuple[str, ...]:
    evidence: list[str] = []
    if stdout:
        evidence.append(f"stdout: {str(stdout).strip()[:500]}")
    if stderr:
        evidence.append(f"stderr: {str(stderr).strip()[:500]}")
    return tuple(evidence)


def _build_report(comparisons: list[LearningTaskComparison]) -> LearningEffectReport:
    no_results = [item.no_learning for item in comparisons]
    approved_results = [item.approved_learning for item in comparisons]
    return LearningEffectReport(
        status="fail",
        total=len(comparisons),
        solved={
            "no_learning": sum(1 for item in no_results if item.valid and item.solved),
            "approved_learning": sum(1 for item in approved_results if item.valid and item.solved),
        },
        steps={
            "no_learning": sum(item.steps for item in no_results),
            "approved_learning": sum(item.steps for item in approved_results),
        },
        failure_class={
            "no_learning": _failure_summary(no_results),
            "approved_learning": _failure_summary(approved_results),
        },
        score_delta=round(sum(item.score_delta for item in comparisons), 4),
        comparisons=tuple(comparisons),
    )


def _score(result: LearningTaskResult) -> float:
    if not result.valid:
        return -100.0
    solved_score = 100.0 if result.solved else 0.0
    failure_penalty = 0.0 if result.solved else 25.0
    step_penalty = min(result.steps, 100) * 0.5
    return solved_score - failure_penalty - step_penalty


def _only_cache_or_docs_improved(no_learning: LearningTaskResult, approved: LearningTaskResult) -> bool:
    if _score(approved) <= _score(no_learning):
        return False
    if not approved.evidence:
        return False
    joined = " ".join(approved.evidence).lower()
    cache_doc_tokens = ("cache", "cached", "documentation", "docs", "document")
    execution_tokens = ("test", "pytest", "verification", "validator", "runtime", "execution", "solved")
    return any(token in joined for token in cache_doc_tokens) and not any(token in joined for token in execution_tokens)


def _invalid_result_reasons(result: LearningTaskResult, *, task_id: str, mode: str) -> list[str]:
    reasons: list[str] = []
    if result.task_id != task_id:
        reasons.append(f"{mode} result task_id mismatch")
    if not result.evidence:
        reasons.append(f"{mode} missing task evidence")
    if not result.valid:
        reasons.append(f"{mode} invalid: {result.invalid_reason}")
    return reasons


def _invalidate_result(result: LearningTaskResult, reason: str) -> LearningTaskResult:
    invalid_reason = result.invalid_reason
    if invalid_reason:
        extra_reasons = tuple(
            item for item in reason.split("; ") if invalid_reason not in item and item not in invalid_reason
        )
        if extra_reasons:
            invalid_reason = f"{invalid_reason}; {'; '.join(extra_reasons)}"
    elif not invalid_reason:
        invalid_reason = reason
    return LearningTaskResult(
        task_id=result.task_id,
        solved=False,
        steps=result.steps,
        failure_class=result.failure_class or "invalid_result",
        evidence=result.evidence,
        invalid_reason=invalid_reason,
    )


def _failure_summary(results: list[LearningTaskResult]) -> str:
    failures = sorted({item.failure_class for item in results if not item.solved and item.failure_class})
    return ",".join(failures)


def _replace_status(report: LearningEffectReport, status: str, gap: str) -> LearningEffectReport:
    payload = asdict(report)
    payload["status"] = status
    payload["gap"] = gap
    payload["comparisons"] = report.comparisons
    return LearningEffectReport(**payload)


def _failed_report(gap: str) -> LearningEffectReport:
    return LearningEffectReport(
        status="fail",
        total=0,
        solved={"no_learning": 0, "approved_learning": 0},
        steps={"no_learning": 0, "approved_learning": 0},
        failure_class={"no_learning": "", "approved_learning": ""},
        score_delta=0.0,
        comparisons=(),
        gap=gap,
    )


def _first_duplicate(values: Iterable[str]) -> str:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            return value
        seen.add(value)
    return ""
