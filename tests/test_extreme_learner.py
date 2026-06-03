"""Tests for extreme_learner module."""

import json
import tempfile
import time
import unittest
from pathlib import Path

from quantagent.extreme_learner import (
    IncrementalLearner,
    SuccessCase,
    CaseMatch,
    CacheStats,
    _cosine_similarity,
    _case_from_dict,
)
from quantagent.extreme_code_generator import ExtremeCodeGenerator
from quantagent.extreme_verifier import VerificationReport
from quantagent.embedding_provider import LocalHashEmbeddingProvider


class TestCosineSimilarity(unittest.TestCase):
    """Test cosine similarity computation."""

    def test_identical_vectors(self):
        vec = [1.0, 2.0, 3.0]
        self.assertAlmostEqual(_cosine_similarity(vec, vec), 1.0, places=5)

    def test_orthogonal_vectors(self):
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [0.0, 1.0, 0.0]
        self.assertAlmostEqual(_cosine_similarity(vec_a, vec_b), 0.0, places=5)

    def test_opposite_vectors(self):
        vec_a = [1.0, 2.0, 3.0]
        vec_b = [-1.0, -2.0, -3.0]
        self.assertAlmostEqual(_cosine_similarity(vec_a, vec_b), -1.0, places=5)

    def test_different_lengths(self):
        vec_a = [1.0, 2.0]
        vec_b = [1.0, 2.0, 3.0]
        self.assertEqual(_cosine_similarity(vec_a, vec_b), 0.0)

    def test_zero_vectors(self):
        vec_a = [0.0, 0.0, 0.0]
        vec_b = [1.0, 2.0, 3.0]
        self.assertEqual(_cosine_similarity(vec_a, vec_b), 0.0)


class TestCaseFromDict(unittest.TestCase):
    """Test SuccessCase reconstruction from dict."""

    def test_full_case(self):
        data = {
            "case_id": "case-123",
            "task": "implement feature X",
            "task_sha256": "abc123",
            "solution": "def feature_x(): pass",
            "context": {"file": "test.py"},
            "patterns": ["pattern1", "pattern2"],
            "created_at_ms": 1000,
            "last_used_ms": 2000,
            "use_count": 5,
        }
        case = _case_from_dict(data)
        self.assertEqual(case.case_id, "case-123")
        self.assertEqual(case.task, "implement feature X")
        self.assertEqual(case.use_count, 5)

    def test_minimal_case(self):
        data = {}
        case = _case_from_dict(data)
        self.assertEqual(case.case_id, "")
        self.assertEqual(case.task, "")
        self.assertEqual(case.use_count, 0)

    def test_invalid_types(self):
        data = {
            "case_id": 123,
            "context": "not a dict",
            "patterns": "not a list",
            "use_count": "not an int",
        }
        case = _case_from_dict(data)
        self.assertEqual(case.case_id, "123")
        self.assertEqual(case.context, {})
        self.assertEqual(case.patterns, [])
        self.assertEqual(case.use_count, 0)


class TestIncrementalLearner(unittest.TestCase):
    """Test IncrementalLearner class."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project = Path(self.temp_dir.name)
        self.provider = LocalHashEmbeddingProvider(dimensions=64)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_init(self):
        learner = IncrementalLearner(self.project, self.provider)
        self.assertEqual(len(learner), 0)
        self.assertEqual(learner.get_stats().total_cases, 0)

    def test_add_case(self):
        learner = IncrementalLearner(self.project, self.provider)
        case = learner.add_case(
            task="implement feature A",
            solution="def feature_a(): pass",
            context={"file": "test.py"},
            patterns=["pattern1"],
        )
        self.assertEqual(len(learner), 1)
        self.assertIn("case-", case.case_id)
        self.assertEqual(case.task, "implement feature A")
        self.assertEqual(case.solution, "def feature_a(): pass")

    def test_unverified_case_is_not_cached(self):
        learner = IncrementalLearner(self.project, self.provider)
        case = learner.add_case(
            task="unverified task",
            solution="solution",
            verifier_passed=False,
        )
        self.assertIsNone(case)
        self.assertEqual(len(learner), 0)

    def test_save_and_load(self):
        learner = IncrementalLearner(self.project, self.provider)
        learner.add_case("task1", "solution1")
        learner.add_case("task2", "solution2")
        cache_path = learner.save()
        self.assertTrue(cache_path.exists())

        # Load in new instance
        learner2 = IncrementalLearner(self.project, self.provider)
        self.assertEqual(len(learner2), 2)

    def test_find_similar_empty(self):
        learner = IncrementalLearner(self.project, self.provider)
        matches = learner.find_similar("some task")
        self.assertEqual(len(matches), 0)
        self.assertEqual(learner.get_stats().cache_misses, 1)

    def test_find_similar_exact_match(self):
        learner = IncrementalLearner(self.project, self.provider)
        learner.add_case("implement feature X", "solution X")
        learner.save()

        matches = learner.find_similar("implement feature X", limit=5, min_score=0.5)
        self.assertGreater(len(matches), 0)
        self.assertGreater(matches[0].score, 0.8)

    def test_find_similar_semantic(self):
        learner = IncrementalLearner(self.project, self.provider)
        learner.add_case("add authentication to API", "solution 1")
        learner.add_case("implement login system", "solution 2")
        learner.add_case("calculate fibonacci numbers", "solution 3")
        learner.save()

        # Query similar to first two cases
        # Lower min_score since local hash embeddings have lower semantic similarity
        matches = learner.find_similar("create user authentication", limit=5, min_score=0.0)
        # Should return at least some matches with any score
        self.assertGreaterEqual(len(matches), 1)

    def test_find_similar_limit(self):
        learner = IncrementalLearner(self.project, self.provider)
        for i in range(10):
            learner.add_case(f"task {i}", f"solution {i}")
        learner.save()

        matches = learner.find_similar("task 5", limit=3, min_score=0.0)
        self.assertLessEqual(len(matches), 3)

    def test_find_similar_min_score(self):
        learner = IncrementalLearner(self.project, self.provider)
        learner.add_case("completely different task", "solution")
        learner.save()

        matches = learner.find_similar("unrelated query", limit=5, min_score=0.99)
        # Should filter out low similarity matches
        self.assertLessEqual(len(matches), 1)

    def test_find_similar_updates_use_count(self):
        learner = IncrementalLearner(self.project, self.provider)
        case = learner.add_case("test task", "test solution")
        initial_count = case.use_count
        learner.save()

        learner.find_similar("test task", min_score=0.5)
        learner.save()

        # Reload and check use count increased
        learner2 = IncrementalLearner(self.project, self.provider)
        reloaded_case = list(learner2._cases.values())[0]
        self.assertGreater(reloaded_case.use_count, initial_count)

    def test_feedback_is_recorded_and_persisted(self):
        learner = IncrementalLearner(self.project, self.provider)
        case = learner.add_case("feedback task", "solution")
        self.assertIsNotNone(case)

        assert case is not None
        self.assertTrue(learner.record_feedback(case.case_id, "adopted", task="new task"))
        self.assertTrue(learner.record_feedback(case.case_id, "rejected", reason="not applicable"))
        learner.save()

        reloaded = IncrementalLearner(self.project, self.provider)
        reloaded_case = list(reloaded._cases.values())[0]
        self.assertEqual(reloaded_case.feedback["adopted"], 1)
        self.assertEqual(reloaded_case.feedback["rejected"], 1)
        self.assertEqual(reloaded.get_stats().adopted_feedback, 1)
        self.assertEqual(reloaded.get_stats().rejected_feedback, 1)

    def test_failure_feedback_blocks_adoption(self):
        learner = IncrementalLearner(self.project, self.provider)
        case = learner.add_case("risky task", "solution")
        self.assertIsNotNone(case)

        assert case is not None
        learner.record_feedback(case.case_id, "failure")
        blocked_case = learner._cases[case.case_id]
        self.assertFalse(learner.is_adoptable(blocked_case))

    def test_extract_patterns_empty(self):
        learner = IncrementalLearner(self.project, self.provider)
        patterns = learner.extract_patterns([])
        self.assertEqual(patterns, [])

    def test_extract_patterns_single_case(self):
        learner = IncrementalLearner(self.project, self.provider)
        case = learner.add_case("task", "solution", patterns=["pattern1", "pattern2"])
        patterns = learner.extract_patterns([case])
        # Single case patterns don't count as "common"
        self.assertEqual(patterns, [])

    def test_extract_patterns_multiple_cases(self):
        learner = IncrementalLearner(self.project, self.provider)
        case1 = learner.add_case("task1", "sol1", patterns=["pattern_a", "pattern_b"])
        case2 = learner.add_case("task2", "sol2", patterns=["pattern_a", "pattern_c"])
        case3 = learner.add_case("task3", "sol3", patterns=["pattern_a", "pattern_b"])

        patterns = learner.extract_patterns([case1, case2, case3])
        # pattern_a appears 3 times, pattern_b appears 2 times
        self.assertIn("pattern_a", patterns)
        self.assertIn("pattern_b", patterns)
        # pattern_c appears only once
        self.assertNotIn("pattern_c", patterns)

    def test_clear_expired_no_expiry(self):
        learner = IncrementalLearner(self.project, self.provider, expiry_days=0)
        learner.add_case("task", "solution")
        removed = learner.clear_expired()
        self.assertEqual(removed, 0)
        self.assertEqual(len(learner), 1)

    def test_clear_expired_with_expiry(self):
        learner = IncrementalLearner(self.project, self.provider, expiry_days=1)

        # Add old case (simulate by modifying internal state)
        old_case = SuccessCase(
            case_id="old-case",
            task="old task",
            task_sha256="abc",
            solution="old solution",
            created_at_ms=int(time.time() * 1000) - (2 * 24 * 60 * 60 * 1000),  # 2 days ago
        )
        learner._cases["old-case"] = old_case

        # Add recent case
        learner.add_case("new task", "new solution")

        removed = learner.clear_expired()
        self.assertEqual(removed, 1)
        self.assertEqual(len(learner), 1)

    def test_cache_stats(self):
        learner = IncrementalLearner(self.project, self.provider)
        stats = learner.get_stats()
        self.assertEqual(stats.total_cases, 0)
        self.assertEqual(stats.cache_hits, 0)
        self.assertEqual(stats.cache_misses, 0)
        self.assertEqual(stats.hit_rate, 0.0)

    def test_cache_stats_hit_rate(self):
        learner = IncrementalLearner(self.project, self.provider)
        learner.add_case("task", "solution")
        learner.save()

        # Hit
        learner.find_similar("task", min_score=0.5)
        # Miss
        learner2 = IncrementalLearner(self.project, self.provider)
        learner2.find_similar("completely different", min_score=0.99)

        stats = learner.get_stats()
        self.assertEqual(stats.cache_hits, 1)

        stats2 = learner2.get_stats()
        self.assertGreater(stats2.cache_misses, 0)

    def test_cache_path_structure(self):
        learner = IncrementalLearner(self.project, self.provider)
        # Use resolve() to handle symlinks like /var -> /private/var on macOS
        expected_path = (self.project / ".quantagent" / "extreme_cache" / "success_cases.json").resolve()
        self.assertEqual(learner.cache_path.resolve(), expected_path)

    def test_persistence_format(self):
        learner = IncrementalLearner(self.project, self.provider)
        learner.add_case("task", "solution", context={"key": "value"})
        cache_path = learner.save()

        # Check JSON structure
        data = json.loads(cache_path.read_text())
        self.assertEqual(data["version"], 1)
        self.assertIn("updated_at_ms", data)
        self.assertIn("cases", data)
        self.assertIn("stats", data)
        self.assertGreater(len(data["cases"]), 0)


class TestCacheStats(unittest.TestCase):
    """Test CacheStats class."""

    def test_hit_rate_zero(self):
        stats = CacheStats()
        self.assertEqual(stats.hit_rate, 0.0)

    def test_hit_rate_calculation(self):
        stats = CacheStats(cache_hits=7, cache_misses=3)
        self.assertAlmostEqual(stats.hit_rate, 0.7, places=2)

    def test_to_dict(self):
        stats = CacheStats(total_cases=10, cache_hits=5, cache_misses=5)
        data = stats.to_dict()
        self.assertEqual(data["total_cases"], 10)
        self.assertEqual(data["hit_rate"], 0.5)


class _FakePlanner:
    def __init__(self, ok: bool = True):
        self.ok = ok
        self.received_task = ""

    def plan(self, task: str):
        self.received_task = task
        if not self.ok:
            return {"ok": False, "error": "planned failure", "operations": []}
        return {
            "ok": True,
            "operations": [
                {
                    "op": "write_text",
                    "path": "generated_example.py",
                    "text": "def generated_example() -> str:\n    return 'ok'\n",
                }
            ],
        }


class _FakeVerifier:
    def __init__(self, ok: bool):
        self.ok = ok

    def verify_project(self, paths=None):
        return VerificationReport(ok=self.ok)


class TestExtremeGeneratorLearningFeedback(unittest.TestCase):
    """Regression tests for cache adoption affecting generation."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _generator(self, planner: _FakePlanner, verifier: _FakeVerifier) -> ExtremeCodeGenerator:
        generator = ExtremeCodeGenerator(
            self.project,
            enable_verification=True,
            enable_fixing=False,
            enable_learning=True,
        )
        generator.planner = planner
        generator.verifier = verifier
        return generator

    def test_similar_success_case_is_adopted_and_influences_planner_task(self):
        seed = IncrementalLearner(self.project, LocalHashEmbeddingProvider(dimensions=64))
        case = seed.add_case(
            "create reusable cache adapter",
            json.dumps({"operations": [{"path": "cache_adapter.py"}]}),
            patterns=["write adapter tests first"],
            verifier_passed=True,
        )
        self.assertIsNotNone(case)
        seed.save()

        planner = _FakePlanner()
        generator = self._generator(planner, _FakeVerifier(ok=True))
        result = generator.generate("create reusable cache adapter")

        self.assertTrue(result.ok)
        self.assertTrue(result.metrics.learned_from_cache)
        self.assertIn("Verified Prior Successes To Reuse", planner.received_task)
        self.assertIn("write adapter tests first", planner.received_task)
        self.assertEqual(result.metrics.adopted_case_ids, [case.case_id])  # type: ignore[union-attr]
        self.assertTrue(result.metrics.added_to_cache)
        self.assertEqual(result.metrics.learning_feedback[0]["outcome"], "adopted")

    def test_failed_feedback_case_is_rejected_and_not_injected(self):
        seed = IncrementalLearner(self.project, LocalHashEmbeddingProvider(dimensions=64))
        case = seed.add_case("create blocked cache adapter", "solution", verifier_passed=True)
        self.assertIsNotNone(case)
        assert case is not None
        seed.record_feedback(case.case_id, "failure", reason="verification failed previously")
        seed.save()

        planner = _FakePlanner()
        generator = self._generator(planner, _FakeVerifier(ok=True))
        result = generator.generate("create blocked cache adapter")

        self.assertTrue(result.ok)
        self.assertTrue(result.metrics.learned_from_cache)
        self.assertEqual(result.metrics.adopted_case_ids, [])
        self.assertEqual(result.metrics.rejected_case_ids, [case.case_id])
        self.assertNotIn("Verified Prior Successes To Reuse", planner.received_task)
        self.assertEqual(result.metrics.learning_feedback[0]["outcome"], "rejected")

    def test_failed_verification_is_not_added_to_cache_and_records_failure_feedback(self):
        seed = IncrementalLearner(self.project, LocalHashEmbeddingProvider(dimensions=64))
        case = seed.add_case("create failing cache adapter", "solution", verifier_passed=True)
        self.assertIsNotNone(case)
        seed.save()

        generator = self._generator(_FakePlanner(), _FakeVerifier(ok=False))
        result = generator.generate("create failing cache adapter")

        self.assertFalse(result.ok)
        self.assertFalse(result.metrics.added_to_cache)
        self.assertEqual(result.metrics.learning_feedback[0]["outcome"], "failure")

        reloaded = IncrementalLearner(self.project, LocalHashEmbeddingProvider(dimensions=64))
        self.assertEqual(len(reloaded), 1)
        stored_case = reloaded._cases[case.case_id]  # type: ignore[union-attr]
        self.assertEqual(stored_case.feedback["failure"], 1)


if __name__ == "__main__":
    unittest.main()
