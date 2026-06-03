"""Extreme code generator - end-to-end integration.

Integrates all components:
1. ExtremeContextBuilder - builds rich context (0 AI calls)
2. ExtremePlanner - generates code with AI + caching
3. DeterministicVerifier - validates code (0 AI calls)
4. SmartFixer - fixes errors (deterministic-first, AI fallback)
5. IncrementalLearner - learns from successes

Target: <$0.05 per task, 80%+ success rate on first try.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quantagent.extreme_context import ExtremeContextBuilder, TaskContext
from quantagent.extreme_planner import ExtremePlanner
from quantagent.extreme_verifier import DeterministicVerifier, VerificationReport
from quantagent.extreme_fixer import SmartFixer, FixResult
from quantagent.extreme_learner import CaseMatch, IncrementalLearner
from quantagent.model_client import ModelClient


@dataclass
class GenerationMetrics:
    """Metrics for a single code generation task."""

    task: str
    success: bool
    total_cost_usd: float = 0.0
    total_duration_ms: int = 0

    # Phase costs
    context_duration_ms: int = 0
    planning_cost_usd: float = 0.0
    planning_duration_ms: int = 0
    verification_duration_ms: int = 0
    fixing_cost_usd: float = 0.0
    fixing_duration_ms: int = 0

    # Attempt counts
    fix_attempts: int = 0
    deterministic_fixes: int = 0
    ai_fixes: int = 0

    # Results
    files_created: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    verification_errors: list[str] = field(default_factory=list)
    final_error: str = ""

    # Learning
    learned_from_cache: bool = False
    added_to_cache: bool = False
    cache_case_ids: list[str] = field(default_factory=list)
    adopted_case_ids: list[str] = field(default_factory=list)
    rejected_case_ids: list[str] = field(default_factory=list)
    learning_feedback: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "success": self.success,
            "total_cost_usd": round(self.total_cost_usd, 4),
            "total_duration_ms": self.total_duration_ms,
            "context_duration_ms": self.context_duration_ms,
            "planning_cost_usd": round(self.planning_cost_usd, 4),
            "planning_duration_ms": self.planning_duration_ms,
            "verification_duration_ms": self.verification_duration_ms,
            "fixing_cost_usd": round(self.fixing_cost_usd, 4),
            "fixing_duration_ms": self.fixing_duration_ms,
            "fix_attempts": self.fix_attempts,
            "deterministic_fixes": self.deterministic_fixes,
            "ai_fixes": self.ai_fixes,
            "files_created": self.files_created,
            "files_modified": self.files_modified,
            "verification_errors": self.verification_errors,
            "final_error": self.final_error,
            "learned_from_cache": self.learned_from_cache,
            "added_to_cache": self.added_to_cache,
            "cache_case_ids": self.cache_case_ids,
            "adopted_case_ids": self.adopted_case_ids,
            "rejected_case_ids": self.rejected_case_ids,
            "learning_feedback": self.learning_feedback,
        }


@dataclass
class GenerationResult:
    """Result of code generation."""

    ok: bool
    task: str
    metrics: GenerationMetrics
    operations: list[dict[str, Any]] = field(default_factory=list)
    verification_report: dict[str, Any] | None = None
    fix_results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "task": self.task,
            "metrics": self.metrics.to_dict(),
            "operations": self.operations,
            "verification_report": self.verification_report,
            "fix_results": self.fix_results,
        }


class ExtremeCodeGenerator:
    """End-to-end code generator with all components integrated.

    Flow:
    1. Build context (local, 0 AI calls)
    2. Check learner cache for similar tasks
    3. Generate code with AI (with prompt caching)
    4. Verify code (local, 0 AI calls)
    5. Fix errors if needed (deterministic-first, AI fallback)
    6. Add success to learner cache

    Cost target: <$0.05 per task
    Success target: 80%+ on first try
    """

    def __init__(
        self,
        project_root: str | Path,
        *,
        model_client: ModelClient | None = None,
        enable_verification: bool = True,
        enable_fixing: bool = True,
        enable_learning: bool = True,
        max_fix_attempts: int = 3,
        max_cost_per_task_usd: float = 0.05,
    ):
        """Initialize code generator.

        Args:
            project_root: Project root directory
            model_client: Model client for AI calls (default: creates new)
            enable_verification: Enable verification phase
            enable_fixing: Enable fixing phase
            enable_learning: Enable learning/caching
            max_fix_attempts: Maximum fix attempts per file
            max_cost_per_task_usd: Maximum cost per task
        """
        self.project_root = Path(project_root).resolve()
        self.model_client = model_client or ModelClient()
        self.enable_verification = enable_verification
        self.enable_fixing = enable_fixing
        self.enable_learning = enable_learning
        self.max_fix_attempts = max_fix_attempts
        self.max_cost_per_task_usd = max_cost_per_task_usd

        # Initialize components
        self.context_builder = ExtremeContextBuilder(self.project_root)
        self.planner = ExtremePlanner(self.project_root, model_client=self.model_client)
        self.verifier = DeterministicVerifier(
            self.project_root,
            enable_mypy=True,
            enable_ruff=True,
            enable_bandit=True,
            enable_tests=False,  # Don't run tests during generation
        )
        self.fixer = SmartFixer(
            model_client=self.model_client,
            enable_ai=True,
            max_ai_cost_usd=max_cost_per_task_usd * 0.5,  # Reserve half budget for fixing
        )
        self.learner = IncrementalLearner(self.project_root) if enable_learning else None

    def _subprocess_env(self) -> dict[str, str]:
        env = os.environ.copy()
        root = str(self.project_root)
        for key in ("PYTHONPATH", "MYPYPATH"):
            existing = env.get(key)
            env[key] = root if not existing else os.pathsep.join((root, existing))
        return env

    def _project_path_arg(self, file_path: Path) -> str:
        try:
            return str(file_path.resolve().relative_to(self.project_root))
        except ValueError:
            return str(file_path)

    def _fix_verification_command(
        self,
        file_path: Path,
        file_errors: list[str],
    ) -> tuple[list[str], Path | None, dict[str, str] | None]:
        if any(error.lower().startswith("mypy:") for error in file_errors):
            return (
                [sys.executable, "-m", "mypy", "--no-error-summary", self._project_path_arg(file_path)],
                self.project_root,
                self._subprocess_env(),
            )
        return ([sys.executable, "-m", "py_compile", str(file_path)], None, None)

    def generate(self, task: str) -> GenerationResult:
        """Generate code for a task.

        Args:
            task: Natural language task description

        Returns:
            GenerationResult with metrics and status
        """
        metrics = GenerationMetrics(task=task, success=False)
        start_time = time.perf_counter()

        try:
            # Phase 1: Build context (0 AI calls)
            context_start = time.perf_counter()
            context = self.context_builder.build_context(task)
            metrics.context_duration_ms = int((time.perf_counter() - context_start) * 1000)

            # Phase 2: Check learner cache
            similar_cases: list[CaseMatch] = []
            adopted_matches: list[CaseMatch] = []
            rejected_matches: list[CaseMatch] = []
            planner_task = task
            if self.learner:
                similar_cases = self.learner.find_similar(task, limit=3, min_score=0.8)
                if similar_cases:
                    metrics.learned_from_cache = True
                    metrics.cache_case_ids = [match.case.case_id for match in similar_cases]
                    adopted_matches = [
                        match for match in similar_cases
                        if self.learner.is_adoptable(match.case)
                    ][:2]
                    rejected_matches = [
                        match for match in similar_cases
                        if match.case.case_id not in {item.case.case_id for item in adopted_matches}
                    ]
                    metrics.adopted_case_ids = [match.case.case_id for match in adopted_matches]
                    metrics.rejected_case_ids = [match.case.case_id for match in rejected_matches]
                    planner_task = self._task_with_learning_guidance(task, adopted_matches)

                    for match in rejected_matches:
                        if self.learner.record_feedback(
                            match.case.case_id,
                            "rejected",
                            task=task,
                            reason="case feedback made it non-adoptable",
                            metadata={"similarity": match.score},
                        ):
                            metrics.learning_feedback.append({
                                "case_id": match.case.case_id,
                                "outcome": "rejected",
                            })

            # Phase 3: Generate code with AI
            planning_start = time.perf_counter()
            plan_result = self.planner.plan(planner_task)
            metrics.planning_duration_ms = int((time.perf_counter() - planning_start) * 1000)

            if not plan_result["ok"]:
                metrics.final_error = plan_result.get("error", "Planning failed")
                metrics.total_duration_ms = int((time.perf_counter() - start_time) * 1000)
                self._record_learning_feedback(
                    adopted_matches,
                    "failure",
                    task,
                    metrics,
                    reason="planner failed",
                )
                return GenerationResult(
                    ok=False,
                    task=task,
                    metrics=metrics,
                )

            operations = plan_result["operations"]

            # Estimate planning cost (rough estimate based on tokens)
            # TODO: Get actual cost from model_client
            metrics.planning_cost_usd = 0.02  # Placeholder

            # Phase 4: Write files
            written_files = []
            for op in operations:
                if op["op"] == "write_text":
                    file_path = self.project_root / op["path"]
                    file_path.parent.mkdir(parents=True, exist_ok=True)

                    if file_path.exists():
                        metrics.files_modified.append(op["path"])
                    else:
                        metrics.files_created.append(op["path"])

                    file_path.write_text(op["text"], encoding="utf-8")
                    written_files.append(file_path)

            # Phase 5: Verify code (0 AI calls)
            verification_report = None
            if self.enable_verification and written_files:
                verification_start = time.perf_counter()
                verification_report = self.verifier.verify_project(
                    paths=written_files,
                )
                metrics.verification_duration_ms = int((time.perf_counter() - verification_start) * 1000)

                if not verification_report.ok:
                    metrics.verification_errors = [
                        f"{check.check_name}: {err}"
                        for check in verification_report.checks
                        for err in check.errors
                    ]

            # Phase 6: Fix errors if needed
            fix_results = []
            if self.enable_fixing and verification_report and not verification_report.ok:
                fixing_start = time.perf_counter()

                for file_path in written_files:
                    # Get errors for this file
                    file_errors = [
                        err for err in metrics.verification_errors
                        if file_path.name in err
                    ]

                    if not file_errors:
                        continue

                    # Try to fix
                    for attempt in range(self.max_fix_attempts):
                        if metrics.total_cost_usd >= self.max_cost_per_task_usd:
                            break

                        error_text = "\n".join(file_errors)
                        verify_command, verify_cwd, verify_env = self._fix_verification_command(
                            file_path,
                            file_errors,
                        )
                        fix_result = self.fixer.fix_file(
                            file_path,
                            error_text,
                            verify_command=verify_command,
                            verify_cwd=verify_cwd,
                            verify_env=verify_env,
                        )

                        fix_results.append({
                            "file": str(file_path),
                            "attempt": attempt + 1,
                            "ok": fix_result.ok,
                            "cost_usd": fix_result.total_cost_usd,
                            "duration_ms": fix_result.total_duration_ms,
                            "deterministic": fix_result.deterministic_success,
                        })

                        metrics.fix_attempts += 1
                        metrics.fixing_cost_usd += fix_result.total_cost_usd

                        if fix_result.deterministic_success:
                            metrics.deterministic_fixes += 1
                        if fix_result.ai_invoked:
                            metrics.ai_fixes += 1

                        if fix_result.ok:
                            break

                metrics.fixing_duration_ms = int((time.perf_counter() - fixing_start) * 1000)

                # Re-verify after fixes
                if fix_results:
                    verification_report = self.verifier.verify_project(paths=written_files)

            # Phase 7: Update metrics
            metrics.total_cost_usd = metrics.planning_cost_usd + metrics.fixing_cost_usd
            metrics.total_duration_ms = int((time.perf_counter() - start_time) * 1000)

            # Determine success
            if verification_report:
                metrics.success = verification_report.ok
            else:
                metrics.success = True  # No verification, but do not cache as verified success

            feedback_outcome = "adopted" if metrics.success else "failure"
            self._record_learning_feedback(
                adopted_matches,
                feedback_outcome,
                task,
                metrics,
                reason="verification passed" if metrics.success else "verification failed",
            )

            # Phase 8: Learn from verifier-passed success only
            if verification_report and verification_report.ok and self.learner:
                solution = json.dumps({
                    "operations": operations,
                    "files": metrics.files_created + metrics.files_modified,
                    "learning": {
                        "adopted_case_ids": metrics.adopted_case_ids,
                    },
                })
                added_case = self.learner.add_case(
                    task=task,
                    solution=solution,
                    context={
                        "cost_usd": metrics.total_cost_usd,
                        "verifier_passed": True,
                        "adopted_case_ids": metrics.adopted_case_ids,
                    },
                    verifier_passed=True,
                )
                self.learner.save()
                metrics.added_to_cache = added_case is not None

            return GenerationResult(
                ok=metrics.success,
                task=task,
                metrics=metrics,
                operations=operations,
                verification_report=verification_report.to_dict() if verification_report else None,
                fix_results=fix_results,
            )

        except Exception as e:
            metrics.final_error = str(e)
            metrics.total_duration_ms = int((time.perf_counter() - start_time) * 1000)
            return GenerationResult(
                ok=False,
                task=task,
                metrics=metrics,
            )

    def _task_with_learning_guidance(self, task: str, matches: list[CaseMatch]) -> str:
        """Attach verified cache guidance to the planner task."""
        if not matches:
            return task

        lines = [
            task,
            "",
            "# Verified Prior Successes To Reuse",
            "Use these verifier-passed cases as planning constraints when applicable.",
        ]
        for idx, match in enumerate(matches, start=1):
            case = match.case
            lines.extend([
                f"## Case {idx}: {case.case_id}",
                f"- Similarity: {match.score:.3f}",
                f"- Prior task: {case.task}",
                f"- Reusable patterns: {', '.join(case.patterns) if case.patterns else '(none recorded)'}",
                "- Prior verified solution metadata:",
                case.solution[:1200],
            ])

        return "\n".join(lines)

    def _record_learning_feedback(
        self,
        matches: list[CaseMatch],
        outcome: str,
        task: str,
        metrics: GenerationMetrics,
        *,
        reason: str,
    ) -> None:
        if not self.learner or not matches:
            return

        for match in matches:
            recorded = self.learner.record_feedback(
                match.case.case_id,
                outcome,
                task=task,
                reason=reason,
                metadata={"similarity": match.score},
            )
            if recorded:
                metrics.learning_feedback.append({
                    "case_id": match.case.case_id,
                    "outcome": outcome,
                })
        self.learner.save()

    def generate_batch(self, tasks: list[str]) -> list[GenerationResult]:
        """Generate code for multiple tasks.

        Args:
            tasks: List of task descriptions

        Returns:
            List of GenerationResult
        """
        results = []
        for task in tasks:
            result = self.generate(task)
            results.append(result)
        return results

    def get_stats(self) -> dict[str, Any]:
        """Get generator statistics.

        Returns:
            Statistics dict
        """
        stats = {
            "project_root": str(self.project_root),
            "enable_verification": self.enable_verification,
            "enable_fixing": self.enable_fixing,
            "enable_learning": self.enable_learning,
            "max_fix_attempts": self.max_fix_attempts,
            "max_cost_per_task_usd": self.max_cost_per_task_usd,
        }

        if self.learner:
            learner_stats = self.learner.get_stats()
            stats["learner"] = learner_stats.to_dict()

        return stats


def generate_code(
    project_root: str | Path,
    task: str,
    *,
    max_cost_usd: float = 0.05,
) -> dict[str, Any]:
    """Convenience function to generate code for a single task.

    Args:
        project_root: Project root directory
        task: Task description
        max_cost_usd: Maximum cost per task

    Returns:
        Generation result as dict
    """
    generator = ExtremeCodeGenerator(
        project_root,
        max_cost_per_task_usd=max_cost_usd,
    )
    result = generator.generate(task)
    return result.to_dict()
