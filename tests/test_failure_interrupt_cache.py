from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.failure_interrupt_cache import (
    DiagnosisAsset,
    build_failure_interrupt,
    find_diagnosis_asset,
    record_diagnosis_asset,
    recheck_diagnosis_asset,
)


class FailureInterruptCacheTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent failure interrupt ")

    def test_signature_uses_relative_frame_and_function_span(self) -> None:
        source = "def calc():\n    return 1\n"
        with self.make_project() as tmp_a, self.make_project() as tmp_b:
            project_a = Path(tmp_a)
            project_b = Path(tmp_b)
            (project_a / "a.py").write_text(source, encoding="utf-8")
            (project_b / "a.py").write_text(source, encoding="utf-8")
            failure_a = f'File "{project_a / "a.py"}", line 2, in calc\nAssertionError: 1 != 2\n'
            failure_b = f'File "{project_b / "a.py"}", line 2, in calc\nAssertionError: 1 != 2\n'

            interrupt_a = build_failure_interrupt(project_a, failure_a, failure_class="assertion", planned_paths=["a.py"])
            interrupt_b = build_failure_interrupt(project_b, failure_b, failure_class="assertion", planned_paths=["a.py"])

        self.assertEqual(interrupt_a.signature, interrupt_b.signature)
        self.assertEqual(interrupt_a.frames[0].path, "a.py")
        self.assertEqual(interrupt_a.source_spans[0].kind, "function")
        self.assertEqual(interrupt_a.source_spans[0].name, "calc")

    def test_diagnosis_asset_round_trips_without_applyable_patch(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("def calc():\n    return 1\n", encoding="utf-8")
            failure = f'File "{project / "a.py"}", line 2, in calc\nAssertionError: 1 != 2\n'

            recorded = record_diagnosis_asset(
                project,
                project,
                failure,
                failure_class="assertion",
                planned_paths=["a.py"],
                evidence_facts=["failing test expects calc == 2"],
                suspect_symbols=["a.py:calc"],
                successful_fix_pattern="stale test expectation",
                validation_result={
                    "targeted_test": {"ok": True, "command": "python3 -m unittest tests.test_calc"},
                    "full_test": {"ok": True, "command": "python3 -m unittest discover -s tests"},
                },
            )
            hit_interrupt, asset = find_diagnosis_asset(project, project, failure, failure_class="assertion", planned_paths=["a.py"])

        self.assertIsNotNone(asset)
        assert asset is not None
        self.assertEqual(recorded.signature, hit_interrupt.signature)
        self.assertEqual(asset.failure_signature, recorded.signature)
        self.assertEqual(asset.successful_fix_pattern, "stale test expectation")
        self.assertIn("failing test expects calc == 2", asset.evidence_facts)
        self.assertIn("a.py:calc", asset.suspect_symbols)
        for key in ("suspect_span_hash", "stack_trace_hash", "lock_hash", "recent_diff_hash", "runtime_info"):
            self.assertIn(key, asset.invalidation_keys)
        self.assertNotIn("candidate", asset.to_dict())
        self.assertNotIn("edits", asset.to_dict())
        self.assertNotIn("unified_diff", asset.to_dict())

    def test_source_span_change_invalidates_diagnosis_asset(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("def calc():\n    return 1\n", encoding="utf-8")
            failure = f'File "{project / "a.py"}", line 2, in calc\nAssertionError: 1 != 2\n'

            recorded = record_diagnosis_asset(
                project,
                project,
                failure,
                failure_class="assertion",
                planned_paths=["a.py"],
                evidence_facts=["old fact"],
                suspect_symbols=["a.py:calc"],
                successful_fix_pattern="schema/caller field mismatch",
                validation_result={"targeted_test": {"ok": True}, "full_test": {"ok": True}},
            )
            hit_interrupt, hit = find_diagnosis_asset(project, project, failure, failure_class="assertion", planned_paths=["a.py"])
            (project / "a.py").write_text("def calc():\n    return 9\n", encoding="utf-8")
            changed_interrupt, changed_hit = find_diagnosis_asset(project, project, failure, failure_class="assertion", planned_paths=["a.py"])

        self.assertEqual(recorded.signature, hit_interrupt.signature)
        self.assertIsNotNone(hit)
        self.assertNotEqual(recorded.signature, changed_interrupt.signature)
        self.assertIsNone(changed_hit)

    def test_recheck_validates_supported_evidence(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("def calc():\n    return 1\n", encoding="utf-8")
            asset = DiagnosisAsset(
                failure_signature="sig",
                invalidation_keys={},
                failure_class="assertion",
                evidence_facts=("failure_class=assertion", "python_file=a.py", "context_paths=a.py"),
                suspect_symbols=("a.py:calc",),
                successful_fix_pattern="stale test expectation",
                validation_result={"full_test": {"ok": True}},
            )

            result = recheck_diagnosis_asset(
                asset,
                {
                    "project": str(project),
                    "failure_class": "assertion",
                    "facts": ["failure_class=assertion", "python_file=a.py", "context_paths=a.py", "full_test_command=python3 -m py_compile a.py"],
                    "context_paths": ["a.py"],
                    "full_test_command": ["python3", "-m", "py_compile", "a.py"],
                    "full_test_command_available": True,
                    "full_test_command_blocked": False,
                },
            )

        self.assertEqual(result.status, "VALID")
        self.assertIn("python_file=a.py", result.matched_facts)
        self.assertIsNotNone(result.receipt)
        assert result.receipt is not None
        self.assertEqual(result.receipt.status, "VALID")
        self.assertIn("python_file=a.py", result.receipt.allowed_payload["evidence_facts"])
        self.assertFalse(result.contradicted_facts)

    def test_recheck_missing_suspect_file_is_contradicted(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            asset = DiagnosisAsset(
                failure_signature="sig",
                invalidation_keys={},
                failure_class="assertion",
                evidence_facts=("failure_class=assertion",),
                suspect_symbols=("missing.py:calc",),
                successful_fix_pattern="wrong import path",
            )

            result = recheck_diagnosis_asset(
                asset,
                {"project": str(project), "failure_class": "assertion", "facts": ["failure_class=assertion"], "context_paths": []},
            )

        self.assertEqual(result.status, "CONTRADICTED")
        self.assertIsNotNone(result.receipt)
        assert result.receipt is not None
        self.assertEqual(result.receipt.allowed_payload, {})
        self.assertIn("missing.py:calc", result.receipt.blocked_payload["suspect_symbols"])
        self.assertTrue(any("missing.py:calc" in item for item in result.contradicted_facts))

    def test_recheck_missing_suspect_function_is_contradicted(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("def other():\n    return 1\n", encoding="utf-8")
            asset = DiagnosisAsset(
                failure_signature="sig",
                invalidation_keys={},
                failure_class="assertion",
                evidence_facts=("failure_class=assertion",),
                suspect_symbols=("a.py:calc",),
                successful_fix_pattern="wrong function",
            )

            result = recheck_diagnosis_asset(asset, {"project": str(project), "failure_class": "assertion", "facts": ["failure_class=assertion"]})

        self.assertEqual(result.status, "CONTRADICTED")
        self.assertTrue(any(check.fact_type == "SUSPECT_SYMBOL_EXISTS" and check.status == "CONTRADICTED" for check in result.checks))

    def test_recheck_failure_class_mismatch_is_contradicted(self) -> None:
        asset = DiagnosisAsset(
            failure_signature="sig",
            invalidation_keys={},
            failure_class="assertion",
            evidence_facts=("failure_class=assertion",),
            successful_fix_pattern="missing await",
        )

        result = recheck_diagnosis_asset(asset, {"project": ".", "failure_class": "import", "facts": ["failure_class=import"]})

        self.assertEqual(result.status, "CONTRADICTED")
        self.assertTrue(any("failure_class=assertion" in item for item in result.contradicted_facts))

    def test_recheck_missing_core_context_path_is_contradicted(self) -> None:
        asset = DiagnosisAsset(
            failure_signature="sig",
            invalidation_keys={},
            evidence_facts=("context_paths=missing.py",),
            successful_fix_pattern="path moved",
        )

        result = recheck_diagnosis_asset(asset, {"project": ".", "facts": [], "context_paths": ["missing.py"]})

        self.assertEqual(result.status, "CONTRADICTED")
        self.assertTrue(any(check.fact_type == "CONTEXT_PATH_EXISTS" and check.status == "CONTRADICTED" for check in result.checks))

    def test_recheck_weakened_allows_fix_pattern_but_blocks_evidence_facts(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            asset = DiagnosisAsset(
                failure_signature="sig",
                invalidation_keys={},
                evidence_facts=("python_file=a.py", "imports[a.py]=old_dep"),
                successful_fix_pattern="schema/caller field mismatch",
            )

            result = recheck_diagnosis_asset(asset, {"project": str(project), "facts": []})

        self.assertEqual(result.status, "WEAKENED")
        assert result.receipt is not None
        self.assertEqual(result.receipt.allowed_payload, {"successful_fix_pattern": "schema/caller field mismatch"})
        self.assertIn("python_file=a.py", result.receipt.blocked_payload["evidence_facts"])
        self.assertIn("imports[a.py]=old_dep", result.receipt.blocked_payload["evidence_facts"])

    def test_recheck_full_test_passed_missing_current_command_is_contradicted(self) -> None:
        asset = DiagnosisAsset(
            failure_signature="sig",
            invalidation_keys={},
            evidence_facts=("full_test=passed",),
            successful_fix_pattern="validated once",
            validation_result={"full_test": {"ok": True, "command": "python3 -m unittest"}},
        )

        result = recheck_diagnosis_asset(asset, {"project": ".", "facts": [], "full_test_command": []})

        self.assertEqual(result.status, "CONTRADICTED")
        self.assertEqual(result.receipt.allowed_payload if result.receipt else {}, {})

    def test_recheck_unverified_without_supported_facts(self) -> None:
        asset = DiagnosisAsset(
            failure_signature="sig",
            invalidation_keys={},
            evidence_facts=("free form old clue",),
            successful_fix_pattern="mock return shape mismatch",
        )

        result = recheck_diagnosis_asset(asset, {"project": ".", "facts": []})

        self.assertEqual(result.status, "UNVERIFIED")
        self.assertIsNotNone(result.receipt)
        assert result.receipt is not None
        self.assertEqual(result.receipt.allowed_payload, {})
        self.assertIn("free form old clue", result.receipt.blocked_payload["evidence_facts"])
        self.assertFalse(result.matched_facts)


if __name__ == "__main__":
    unittest.main()
