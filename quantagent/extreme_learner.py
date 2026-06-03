"""Incremental learner with success case caching and semantic retrieval.

Caches successful task executions with embeddings for semantic search.
Enables pattern extraction and reuse across similar tasks.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

from quantagent.embedding_provider import (
    EmbeddingCache,
    EmbeddingProvider,
    LocalHashEmbeddingProvider,
    embed_batch,
    EmbeddingJob,
    text_sha256,
)


CACHE_EXPIRY_DAYS = 30
CACHE_EXPIRY_MS = CACHE_EXPIRY_DAYS * 24 * 60 * 60 * 1000


@dataclass(frozen=True)
class SuccessCase:
    """A successful task execution case."""

    case_id: str
    task: str
    task_sha256: str
    solution: str
    context: dict[str, Any] = field(default_factory=dict)
    patterns: list[str] = field(default_factory=list)
    verifier_passed: bool = True
    feedback: dict[str, int] = field(default_factory=dict)
    created_at_ms: int = 0
    last_used_ms: int = 0
    use_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CaseMatch:
    """A matched success case with similarity score."""

    case: SuccessCase
    score: float
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case": self.case.to_dict(),
            "score": self.score,
            "reason": self.reason,
        }


@dataclass
class CacheStats:
    """Cache statistics for observability."""

    total_cases: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    expired_cases: int = 0
    avg_similarity: float = 0.0
    adopted_feedback: int = 0
    rejected_feedback: int = 0
    failure_feedback: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "expired_cases": self.expired_cases,
            "hit_rate": round(self.hit_rate, 3),
            "avg_similarity": round(self.avg_similarity, 3),
            "adopted_feedback": self.adopted_feedback,
            "rejected_feedback": self.rejected_feedback,
            "failure_feedback": self.failure_feedback,
        }


class IncrementalLearner:
    """Incremental learner with success case caching and semantic search."""

    def __init__(
        self,
        project: str | Path,
        provider: EmbeddingProvider | None = None,
        expiry_days: int = CACHE_EXPIRY_DAYS,
    ):
        self.project = Path(project).expanduser().resolve(strict=False)
        self.provider = provider or LocalHashEmbeddingProvider()
        self.expiry_ms = expiry_days * 24 * 60 * 60 * 1000
        self.cache_path = self._get_cache_path()
        self.embedding_cache = EmbeddingCache(self.project)
        self._cases: dict[str, SuccessCase] = {}
        self._stats = CacheStats()
        self.load()

    def _get_cache_path(self) -> Path:
        return self.project / ".quantagent" / "extreme_cache" / "success_cases.json"

    def load(self) -> None:
        """Load success cases from disk."""
        if not self.cache_path.exists():
            self._cases = {}
            return

        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            cases: dict[str, SuccessCase] = {}
            now_ms = _now_ms()

            for case_id, item in payload.get("cases", {}).items():
                if not isinstance(item, dict):
                    continue

                case = _case_from_dict(item)

                if not case.verifier_passed:
                    continue

                # Skip expired cases
                if self.expiry_ms > 0 and (now_ms - case.created_at_ms) > self.expiry_ms:
                    self._stats.expired_cases += 1
                    continue

                cases[str(case_id)] = case

            self._cases = cases
            self._stats.total_cases = len(cases)
            stats = payload.get("stats", {})
            if isinstance(stats, dict):
                self._stats.adopted_feedback = _safe_int(stats.get("adopted_feedback"))
                self._stats.rejected_feedback = _safe_int(stats.get("rejected_feedback"))
                self._stats.failure_feedback = _safe_int(stats.get("failure_feedback"))

        except Exception:
            self._cases = {}

    def save(self) -> Path:
        """Save success cases to disk."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated_at_ms": _now_ms(),
            "expiry_days": self.expiry_ms // (24 * 60 * 60 * 1000),
            "stats": self._stats.to_dict(),
            "cases": {case_id: case.to_dict() for case_id, case in sorted(self._cases.items())},
        }
        self.cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return self.cache_path

    def add_case(
        self,
        task: str,
        solution: str,
        context: dict[str, Any] | None = None,
        patterns: list[str] | None = None,
        verifier_passed: bool = True,
    ) -> SuccessCase | None:
        """Add a successful case to the cache."""
        if not verifier_passed:
            return None

        task_sha = text_sha256(task)
        case_id = f"case-{task_sha[:16]}-{_now_ms()}"
        now_ms = _now_ms()

        case = SuccessCase(
            case_id=case_id,
            task=task,
            task_sha256=task_sha,
            solution=solution,
            context=context or {},
            patterns=patterns or [],
            verifier_passed=True,
            feedback={},
            created_at_ms=now_ms,
            last_used_ms=now_ms,
            use_count=0,
        )

        self._cases[case_id] = case
        self._stats.total_cases = len(self._cases)
        return case

    def find_similar(
        self,
        task: str,
        limit: int = 5,
        min_score: float = 0.5,
    ) -> list[CaseMatch]:
        """Find similar success cases using semantic search."""
        if not self._cases:
            self._stats.cache_misses += 1
            return []

        # Embed query task
        query_job = EmbeddingJob("query", task)
        query_batch = embed_batch(
            self.project,
            self.provider,
            [query_job],
            cache=self.embedding_cache,
            save_cache=True,
        )

        if not query_batch.records:
            self._stats.cache_misses += 1
            return []

        query_vector = query_batch.records[0].vector

        # Embed all cached cases
        case_jobs = [
            EmbeddingJob(case.case_id, case.task)
            for case in self._cases.values()
        ]

        case_batch = embed_batch(
            self.project,
            self.provider,
            case_jobs,
            cache=self.embedding_cache,
            save_cache=True,
        )

        # Compute similarities
        matches: list[CaseMatch] = []
        similarities: list[float] = []

        for record in case_batch.records:
            case = self._cases.get(record.job_id)
            if not case:
                continue

            score = _cosine_similarity(query_vector, record.vector)
            similarities.append(score)

            if score >= min_score:
                matches.append(CaseMatch(
                    case=case,
                    score=score,
                    reason=f"semantic similarity: {score:.3f}",
                ))

        # Sort by score descending
        matches.sort(key=lambda m: m.score, reverse=True)
        top_matches = matches[:limit]

        # Update stats
        if top_matches:
            self._stats.cache_hits += 1
            if similarities:
                self._stats.avg_similarity = sum(similarities) / len(similarities)
        else:
            self._stats.cache_misses += 1

        # Update use counts
        for match in top_matches:
            case = match.case
            updated = SuccessCase(
                case_id=case.case_id,
                task=case.task,
                task_sha256=case.task_sha256,
                solution=case.solution,
                context=case.context,
                patterns=case.patterns,
                verifier_passed=case.verifier_passed,
                feedback=case.feedback,
                created_at_ms=case.created_at_ms,
                last_used_ms=_now_ms(),
                use_count=case.use_count + 1,
            )
            self._cases[case.case_id] = updated

        return top_matches

    def record_feedback(
        self,
        case_id: str,
        outcome: str,
        *,
        task: str = "",
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Record whether a retrieved case was adopted, rejected, or failed."""
        if outcome not in {"adopted", "rejected", "failure"}:
            raise ValueError("outcome must be one of: adopted, rejected, failure")

        case = self._cases.get(case_id)
        if not case:
            return False

        feedback = dict(case.feedback)
        feedback[outcome] = int(feedback.get(outcome, 0) or 0) + 1
        feedback["total"] = int(feedback.get("total", 0) or 0) + 1

        last_feedback = {
            "outcome": outcome,
            "task_sha256": text_sha256(task) if task else "",
            "reason": reason,
            "metadata": metadata or {},
            "recorded_at_ms": _now_ms(),
        }

        context = dict(case.context)
        context["last_feedback"] = last_feedback

        updated = SuccessCase(
            case_id=case.case_id,
            task=case.task,
            task_sha256=case.task_sha256,
            solution=case.solution,
            context=context,
            patterns=case.patterns,
            verifier_passed=case.verifier_passed,
            feedback=feedback,
            created_at_ms=case.created_at_ms,
            last_used_ms=_now_ms(),
            use_count=case.use_count,
        )
        self._cases[case_id] = updated

        if outcome == "adopted":
            self._stats.adopted_feedback += 1
        elif outcome == "rejected":
            self._stats.rejected_feedback += 1
        else:
            self._stats.failure_feedback += 1

        return True

    def is_adoptable(self, case: SuccessCase) -> bool:
        """Return whether feedback permits using this success case for planning."""
        if not case.verifier_passed:
            return False
        failures = int(case.feedback.get("failure", 0) or 0)
        adopted = int(case.feedback.get("adopted", 0) or 0)
        return failures <= adopted

    def extract_patterns(self, cases: Sequence[SuccessCase]) -> list[str]:
        """Extract common patterns from multiple success cases."""
        if not cases:
            return []

        # Collect all patterns
        all_patterns: list[str] = []
        for case in cases:
            all_patterns.extend(case.patterns)

        # Count pattern frequency
        pattern_counts: dict[str, int] = {}
        for pattern in all_patterns:
            pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1

        # Return patterns that appear in multiple cases
        common_patterns = [
            pattern
            for pattern, count in pattern_counts.items()
            if count >= 2
        ]

        return sorted(common_patterns, key=lambda p: pattern_counts[p], reverse=True)

    def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        return self._stats

    def clear_expired(self) -> int:
        """Remove expired cases and return count removed."""
        if self.expiry_ms <= 0:
            return 0

        now_ms = _now_ms()
        expired_ids = [
            case_id
            for case_id, case in self._cases.items()
            if (now_ms - case.created_at_ms) > self.expiry_ms
        ]

        for case_id in expired_ids:
            del self._cases[case_id]

        self._stats.expired_cases += len(expired_ids)
        self._stats.total_cases = len(self._cases)

        return len(expired_ids)

    def __len__(self) -> int:
        return len(self._cases)


def _cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(vec_a) != len(vec_b):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot_product / (norm_a * norm_b)


def _case_from_dict(item: dict[str, Any]) -> SuccessCase:
    """Reconstruct SuccessCase from dict."""

    return SuccessCase(
        case_id=str(item.get("case_id") or ""),
        task=str(item.get("task") or ""),
        task_sha256=str(item.get("task_sha256") or ""),
        solution=str(item.get("solution") or ""),
        context=dict(item.get("context", {})) if isinstance(item.get("context"), dict) else {},
        patterns=list(item.get("patterns", [])) if isinstance(item.get("patterns"), list) else [],
        verifier_passed=bool(item.get("verifier_passed", True)),
        feedback=dict(item.get("feedback", {})) if isinstance(item.get("feedback"), dict) else {},
        created_at_ms=_safe_int(item.get("created_at_ms")),
        last_used_ms=_safe_int(item.get("last_used_ms")),
        use_count=_safe_int(item.get("use_count")),
    )


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value) if value else default
    except (ValueError, TypeError):
        return default


def _now_ms() -> int:
    """Get current time in milliseconds."""
    return int(time.time() * 1000)
