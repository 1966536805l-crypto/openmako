from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import uuid
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .diagnostic_registry import diagnostics_for_paths, refresh_diagnostic_registry
from .edit_loop import PatchPlan, RepairLoopResult, run_isolated_repair_loop
from .structured_diff_preview import create_preview_from_isolation_review, save_structured_diff_preview


@dataclass(frozen=True)
class RepairWorkerResult:
    worker_id: str
    ok: bool
    summary: str
    review_id: str = ""
    worktree_id: str = ""
    changed_paths: list[str] = field(default_factory=list)
    rounds: int = 0
    score: int = 0
    error: str = ""
    preview_id: str = ""
    preview_path: str = ""
    approval_required: bool = False
    high_risk_paths: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RepairReviewBundle:
    bundle_id: str
    worker_ids: list[str]
    review_ids: list[str]
    changed_paths: list[str]
    terminal_outcomes: dict[str, str]
    recommended_worker: str = ""
    preview_ids: list[str] = field(default_factory=list)
    approval_required: bool = False
    high_risk_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RepairSchedulerResult:
    ok: bool
    summary: str
    workers: list[RepairWorkerResult]
    bundle: RepairReviewBundle

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "summary": self.summary,
            "workers": [worker.to_dict() for worker in self.workers],
            "bundle": self.bundle.to_dict(),
        }


ClientFactory = Callable[[str], Any]


def run_multi_worker_repair(
    project: str | Path,
    plan: PatchPlan,
    failure_output: str,
    *,
    workers: int = 2,
    max_rounds: int = 3,
    model: str = "",
    base_url: str | None = None,
    timeout: int = 120,
    client_factory: ClientFactory | None = None,
    profile: str = "build",
    write_previews: bool = True,
    diagnostics_limit: int = 200,
) -> RepairSchedulerResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    worker_count = max(1, workers)
    worker_ids = [f"worker-{index}" for index in range(1, worker_count + 1)]
    results: list[RepairWorkerResult] = []
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = {
            pool.submit(
                _run_worker,
                project_path,
                plan,
                _worker_failure_context(failure_output, worker_id),
                worker_id=worker_id,
                max_rounds=max_rounds,
                model=model,
                base_url=base_url,
                timeout=timeout,
                client=client_factory(worker_id) if client_factory else None,
                profile=profile,
                write_previews=write_previews,
                diagnostics_limit=diagnostics_limit,
            ): worker_id
            for worker_id in worker_ids
        }
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:  # pragma: no cover - defensive worker boundary
                worker_id = futures[future]
                results.append(RepairWorkerResult(worker_id, False, f"{type(exc).__name__}: {exc}", error=type(exc).__name__))
    ranked = sorted(results, key=_worker_sort_key)
    bundle = _bundle_from_workers(ranked)
    ok = any(worker.ok for worker in ranked)
    recommended = bundle.recommended_worker or (ranked[0].worker_id if ranked else "")
    summary = f"{sum(1 for worker in ranked if worker.ok)}/{len(ranked)} repair worker(s) passed"
    if recommended:
        summary += f"; recommended={recommended}"
    return RepairSchedulerResult(ok, summary, ranked, bundle)


def render_repair_scheduler_result(result: RepairSchedulerResult) -> str:
    lines = [
        "# Multi-Worker Repair Result",
        "",
        f"- ok: {str(result.ok).lower()}",
        f"- summary: {result.summary}",
        f"- recommended_worker: {result.bundle.recommended_worker or '-'}",
        "",
        "## Workers",
    ]
    for worker in result.workers:
        mark = "ok" if worker.ok else "fail"
        paths = f" paths={','.join(worker.changed_paths)}" if worker.changed_paths else ""
        preview = f" preview={worker.preview_id}" if worker.preview_id else ""
        approval = " approval_required" if worker.approval_required else ""
        lines.append(f"- [{mark}] {worker.worker_id} score={worker.score} rounds={worker.rounds} review={worker.review_id or '-'}{preview}{approval}{paths}: {worker.summary}")
        if worker.high_risk_paths:
            lines.append(f"  high_risk: {', '.join(worker.high_risk_paths)}")
        if worker.diagnostics:
            lines.append(f"  diagnostics: {' | '.join(worker.diagnostics[:3])}")
    if result.bundle.review_ids:
        lines.extend(["", "## Review Bundle"])
        lines.append(f"- bundle_id: {result.bundle.bundle_id}")
        lines.append(f"- reviews: {', '.join(result.bundle.review_ids)}")
        if result.bundle.preview_ids:
            lines.append(f"- previews: {', '.join(result.bundle.preview_ids)}")
        lines.append(f"- approval_required: {str(result.bundle.approval_required).lower()}")
        if result.bundle.high_risk_paths:
            lines.append(f"- high_risk_paths: {', '.join(result.bundle.high_risk_paths)}")
        lines.append(f"- changed_paths: {', '.join(result.bundle.changed_paths) if result.bundle.changed_paths else '-'}")
    return "\n".join(lines) + "\n"


def _run_worker(
    project: Path,
    plan: PatchPlan,
    failure_output: str,
    *,
    worker_id: str,
    max_rounds: int,
    model: str,
    base_url: str | None,
    timeout: int,
    client: Any | None,
    profile: str,
    write_previews: bool,
    diagnostics_limit: int,
) -> RepairWorkerResult:
    for attempt in range(3):
        try:
            result = run_isolated_repair_loop(
                project,
                plan,
                failure_output,
                max_rounds=max_rounds,
                model=model,
                base_url=base_url,
                client=client,
                timeout=timeout,
            )
            return _worker_result(worker_id, result, plan=plan, profile=profile, write_preview=write_previews, diagnostics_limit=diagnostics_limit)
        except Exception as exc:  # pragma: no cover - defensive worker boundary
            if "database is locked" in str(exc).lower() and attempt < 2:
                time.sleep(0.15 * (attempt + 1))
                continue
            return RepairWorkerResult(worker_id, False, f"{type(exc).__name__}: {exc}", error=type(exc).__name__)
    return RepairWorkerResult(worker_id, False, "worker retry loop exhausted", error="retry_exhausted")


def _worker_result(
    worker_id: str,
    result: RepairLoopResult,
    *,
    plan: PatchPlan,
    profile: str,
    write_preview: bool,
    diagnostics_limit: int,
) -> RepairWorkerResult:
    review = result.review
    changed_paths = sorted(set([*(review.changed_paths if review else []), *(review.new_paths if review else []), *(review.deleted_paths if review else [])]))
    preview_id = ""
    preview_path = ""
    approval_required = False
    high_risk_paths: list[str] = []
    if review is not None:
        preview = create_preview_from_isolation_review(
            result.worktree.project,
            review,
            task=plan.task,
            test_command=plan.test_command,
            profile=profile,
        )
        preview_id = preview.preview_id
        approval_required = preview.approval_required
        high_risk_paths = [item.path for item in preview.files if item.risk == "high"]
        if write_preview:
            preview_path = str(save_structured_diff_preview(result.worktree.project, preview))
    diagnostics = _worker_diagnostics(result, changed_paths, limit=diagnostics_limit)
    score = _score_worker(result.ok, changed_paths, len(result.rounds), approval_required=approval_required, high_risk_paths=high_risk_paths, diagnostics=diagnostics)
    return RepairWorkerResult(
        worker_id=worker_id,
        ok=result.ok,
        summary=result.summary,
        review_id=review.review_id if review else "",
        worktree_id=result.worktree.worktree_id,
        changed_paths=changed_paths,
        rounds=len(result.rounds),
        score=score,
        preview_id=preview_id,
        preview_path=preview_path,
        approval_required=approval_required,
        high_risk_paths=high_risk_paths,
        diagnostics=diagnostics,
    )


def _score_worker(
    ok: bool,
    changed_paths: list[str],
    rounds: int,
    *,
    approval_required: bool = False,
    high_risk_paths: list[str] | None = None,
    diagnostics: list[str] | None = None,
) -> int:
    score = 100 if ok else 20
    score -= min(30, max(0, rounds - 1) * 5)
    score -= min(30, max(0, len(changed_paths) - 1) * 3)
    if approval_required:
        score -= 3
    score -= min(12, len(high_risk_paths or []) * 4)
    score -= min(10, len([item for item in diagnostics or [] if item.startswith("error:")]) * 5)
    return score


def _worker_sort_key(worker: RepairWorkerResult) -> tuple[int, int, int, str]:
    return (-worker.score, 0 if worker.ok else 1, len(worker.changed_paths), worker.worker_id)


def _bundle_from_workers(workers: list[RepairWorkerResult]) -> RepairReviewBundle:
    review_ids = [worker.review_id for worker in workers if worker.review_id]
    preview_ids = [worker.preview_id for worker in workers if worker.preview_id]
    changed_paths: list[str] = []
    high_risk_paths: list[str] = []
    for worker in workers:
        changed_paths.extend(worker.changed_paths)
        high_risk_paths.extend(worker.high_risk_paths)
    recommended = next((worker.worker_id for worker in workers if worker.ok), workers[0].worker_id if workers else "")
    return RepairReviewBundle(
        bundle_id="repair-bundle-" + uuid.uuid4().hex[:12],
        worker_ids=[worker.worker_id for worker in workers],
        review_ids=review_ids,
        changed_paths=sorted(set(changed_paths)),
        terminal_outcomes={worker.worker_id: "ok" if worker.ok else "failed" for worker in workers},
        recommended_worker=recommended,
        preview_ids=preview_ids,
        approval_required=any(worker.approval_required for worker in workers),
        high_risk_paths=sorted(set(high_risk_paths)),
    )


def _worker_failure_context(failure_output: str, worker_id: str) -> str:
    return f"{failure_output}\n\nWorker perspective: {worker_id}. Produce an independent minimal repair candidate."


def _worker_diagnostics(result: RepairLoopResult, changed_paths: list[str], *, limit: int) -> list[str]:
    diagnostics: list[str] = []
    workspace = Path(result.worktree.workspace_path)
    try:
        snapshot = refresh_diagnostic_registry(workspace, limit=limit)
        selected = diagnostics_for_paths(snapshot, changed_paths)
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:296", exc)
        return [f"warn:diagnostics_unavailable:{type(exc).__name__}"]
    for item in selected[:12]:
        location = item.path
        if item.line is not None:
            location += f":{item.line}"
        diagnostics.append(f"{item.level}:{item.code}:{location}:{item.message}")
    return diagnostics
