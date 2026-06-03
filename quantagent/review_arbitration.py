from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from .repair_scheduler import RepairReviewBundle, RepairSchedulerResult, RepairWorkerResult
from .structured_diff_preview import create_preview_from_isolation_review
from .worktree_isolation import load_isolation_review


@dataclass(frozen=True)
class RankedReview:
    review_id: str
    worker_id: str = ""
    ok: bool = False
    score: int = 0
    changed_paths: list[str] = field(default_factory=list)
    high_risk_paths: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    approval_required: bool = True
    source: str = "review_id"

    @property
    def diagnostic_error_count(self) -> int:
        return sum(1 for item in self.diagnostics if item.startswith("error:"))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["diagnostic_error_count"] = self.diagnostic_error_count
        return data


@dataclass(frozen=True)
class ArbitrationDecision:
    recommended_review_id: str
    ranked_reviews: list[RankedReview]
    risk_flags: list[str]
    approval_required: bool
    reasons: list[str]
    apply_gate_ready: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommended_review_id": self.recommended_review_id,
            "ranked_reviews": [review.to_dict() for review in self.ranked_reviews],
            "risk_flags": self.risk_flags,
            "approval_required": self.approval_required,
            "reasons": self.reasons,
            "apply_gate_ready": self.apply_gate_ready,
        }


def arbitrate_parent_reviews(
    *,
    project: str | Path | None = None,
    result: RepairSchedulerResult | None = None,
    bundle: RepairReviewBundle | None = None,
    workers: Sequence[RepairWorkerResult] = (),
    review_ids: Sequence[str] = (),
    profile: str = "build",
) -> ArbitrationDecision:
    """Rank parent-visible repair reviews and choose the best apply-gate candidate."""

    if result is not None:
        bundle = result.bundle
        workers = result.workers
    candidates = _dedupe_reviews(
        [
            *_reviews_from_workers(workers),
            *_reviews_from_bundle(bundle, known_workers=workers),
            *_reviews_from_ids(project, review_ids, profile=profile),
        ]
    )
    ranked = sorted(candidates, key=_ranking_key)
    if not ranked:
        return ArbitrationDecision(
            recommended_review_id="",
            ranked_reviews=[],
            risk_flags=["blocked:no_reviews"],
            approval_required=True,
            reasons=["blocked: no repair reviews are available for parent arbitration"],
            apply_gate_ready=False,
        )

    recommended = ranked[0]
    risk_flags = _risk_flags(ranked)
    approval_required = any(review.approval_required for review in ranked)
    reasons = _decision_reasons(recommended, ranked, risk_flags)
    return ArbitrationDecision(
        recommended_review_id=recommended.review_id,
        ranked_reviews=ranked,
        risk_flags=risk_flags,
        approval_required=approval_required,
        reasons=reasons,
        apply_gate_ready=bool(recommended.review_id),
    )


def render_arbitration_decision(decision: ArbitrationDecision, *, format: str = "markdown") -> str:
    if format == "json":
        return json.dumps(decision.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if format != "markdown":
        raise ValueError(f"unsupported arbitration render format: {format}")
    lines = [
        "# Parent Review Arbitration",
        "",
        f"- recommended_review_id: {decision.recommended_review_id or '-'}",
        f"- apply_gate_ready: {str(decision.apply_gate_ready).lower()}",
        f"- approval_required: {str(decision.approval_required).lower()}",
    ]
    if decision.risk_flags:
        lines.append(f"- risk_flags: {', '.join(decision.risk_flags)}")
    if decision.reasons:
        lines.extend(["", "## Reasons"])
        lines.extend(f"- {reason}" for reason in decision.reasons)
    lines.extend(["", "## Ranked Reviews"])
    if not decision.ranked_reviews:
        lines.append("- No review candidates.")
    for index, review in enumerate(decision.ranked_reviews, start=1):
        status = "ok" if review.ok else "unknown/fail"
        approval = " approval_required" if review.approval_required else ""
        worker = f" worker={review.worker_id}" if review.worker_id else ""
        lines.append(
            f"{index}. {review.review_id} [{status}] score={review.score}{worker}"
            f" errors={review.diagnostic_error_count} high_risk={len(review.high_risk_paths)}"
            f" paths={len(review.changed_paths)}{approval}"
        )
    return "\n".join(lines).rstrip() + "\n"


def _reviews_from_workers(workers: Sequence[RepairWorkerResult]) -> list[RankedReview]:
    return [
        RankedReview(
            review_id=worker.review_id,
            worker_id=worker.worker_id,
            ok=worker.ok,
            score=worker.score,
            changed_paths=sorted(set(worker.changed_paths)),
            high_risk_paths=sorted(set(worker.high_risk_paths)),
            diagnostics=list(worker.diagnostics),
            approval_required=worker.approval_required,
            source="worker",
        )
        for worker in workers
        if worker.review_id
    ]


def _reviews_from_bundle(bundle: RepairReviewBundle | None, *, known_workers: Sequence[RepairWorkerResult]) -> list[RankedReview]:
    if bundle is None:
        return []
    known = {worker.review_id for worker in known_workers if worker.review_id}
    shared_paths = sorted(set(bundle.changed_paths))
    return [
        RankedReview(
            review_id=review_id,
            ok=review_id == _recommended_review_id(bundle, known_workers),
            score=0,
            changed_paths=shared_paths,
            high_risk_paths=sorted(set(bundle.high_risk_paths)),
            approval_required=bundle.approval_required,
            source="bundle",
        )
        for review_id in bundle.review_ids
        if review_id and review_id not in known
    ]


def _reviews_from_ids(project: str | Path | None, review_ids: Sequence[str], *, profile: str) -> list[RankedReview]:
    reviews: list[RankedReview] = []
    for review_id in review_ids:
        if not review_id:
            continue
        if project is None:
            reviews.append(RankedReview(review_id=review_id, ok=True, score=50, approval_required=True))
            continue
        try:
            review = load_isolation_review(project, review_id)
            changed_paths = sorted(set([*review.changed_paths, *review.new_paths, *review.deleted_paths]))
            preview = create_preview_from_isolation_review(project, review, task=f"arbitrate {review.review_id}", profile=profile)
            high_risk_paths = [item.path for item in preview.files if item.risk == "high"]
            score = _score_review_id_candidate(changed_paths, preview.approval_required, high_risk_paths)
            reviews.append(
                RankedReview(
                    review_id=review.review_id,
                    ok=True,
                    score=score,
                    changed_paths=changed_paths,
                    high_risk_paths=sorted(set(high_risk_paths)),
                    approval_required=preview.approval_required,
                    source="review_id",
                )
            )
        except Exception as exc:
            reviews.append(
                RankedReview(
                    review_id=review_id,
                    ok=False,
                    score=0,
                    diagnostics=[f"error:review_load:{type(exc).__name__}:{exc}"],
                    approval_required=True,
                    source="review_id",
                )
            )
    return reviews


def _dedupe_reviews(reviews: Iterable[RankedReview]) -> list[RankedReview]:
    selected: dict[str, RankedReview] = {}
    for review in reviews:
        current = selected.get(review.review_id)
        if current is None or _ranking_key(review) < _ranking_key(current):
            selected[review.review_id] = review
    return list(selected.values())


def _ranking_key(review: RankedReview) -> tuple[int, int, int, int, int, int, str]:
    return (
        0 if review.ok else 1,
        -review.score,
        review.diagnostic_error_count,
        len(review.high_risk_paths),
        len(review.changed_paths),
        1 if review.approval_required else 0,
        review.review_id,
    )


def _risk_flags(reviews: Sequence[RankedReview]) -> list[str]:
    flags: list[str] = []
    if any(not review.ok for review in reviews):
        flags.append("worker_failures")
    if any(review.diagnostic_error_count for review in reviews):
        flags.append("diagnostic_errors")
    if any(review.high_risk_paths for review in reviews):
        flags.append("high_risk_paths")
    if any(review.approval_required for review in reviews):
        flags.append("approval_required")
    return flags


def _decision_reasons(recommended: RankedReview, ranked: Sequence[RankedReview], risk_flags: Sequence[str]) -> list[str]:
    reasons = [
        f"recommended {recommended.review_id} from {recommended.source} with score {recommended.score}",
        "ranking considered worker success, score, diagnostic errors, high-risk paths, changed path count, and approval requirement",
    ]
    if recommended.diagnostic_error_count:
        reasons.append(f"recommended review has {recommended.diagnostic_error_count} diagnostic error(s)")
    if recommended.high_risk_paths:
        reasons.append("recommended review touches high-risk paths: " + ", ".join(recommended.high_risk_paths))
    if recommended.approval_required:
        reasons.append("recommended review still requires explicit approval before apply")
    if len(ranked) > 1:
        reasons.append(f"ranked {len(ranked)} candidate reviews")
    if risk_flags:
        reasons.append("aggregated risk flags: " + ", ".join(risk_flags))
    return reasons


def _recommended_review_id(bundle: RepairReviewBundle, workers: Sequence[RepairWorkerResult]) -> str:
    for worker in workers:
        if worker.worker_id == bundle.recommended_worker:
            return worker.review_id
    return bundle.review_ids[0] if bundle.review_ids else ""


def _score_review_id_candidate(changed_paths: Sequence[str], approval_required: bool, high_risk_paths: Sequence[str]) -> int:
    score = 70
    score -= min(30, max(0, len(changed_paths) - 1) * 3)
    if approval_required:
        score -= 3
    score -= min(12, len(high_risk_paths) * 4)
    return score
