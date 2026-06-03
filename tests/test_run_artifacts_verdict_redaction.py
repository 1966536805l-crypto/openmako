from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.redaction import fold_log_lines, redact_for_llm
from quantagent.run_artifacts import check_spec_lock, create_run_spec, load_run_spec, write_run_result
from quantagent.verdict_gate import FAIL, INCONCLUSIVE, PASS, VerdictDecision, gate_verdicts, normalize_verdict


class RunArtifactsVerdictRedactionTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent run artifacts ")

    def test_run_spec_uses_stable_hash_and_per_run_dir(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            spec = {"data_hash": "abc", "params": {"x": 1}, "seed": 7}

            first = create_run_spec(project, "demo", spec, code_version="v1")
            second = create_run_spec(project, "demo", spec, code_version="v1")
            loaded = load_run_spec(project, first.run_id)

            self.assertEqual(first.run_id, second.run_id)
            self.assertTrue((Path(first.run_dir) / "spec.json").exists())
            self.assertTrue((Path(first.run_dir) / "logs").is_dir())
            self.assertEqual(loaded.spec_hash, first.spec_hash)

    def test_spec_lock_blocks_changed_spec_result(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            run = create_run_spec(project, "demo", {"data_hash": "abc", "params": {"x": 1}})

            stale = write_run_result(project, run.run_id, result={"pf": 2}, current_spec={"data_hash": "abc", "params": {"x": 2}})
            ok = check_spec_lock(project, run.run_id)

            self.assertFalse(stale.ok)
            self.assertTrue((Path(run.run_dir) / "stale.json").exists())
            self.assertTrue(ok.ok)

    def test_verdict_gate_blocks_fail_and_inconclusive(self) -> None:
        self.assertEqual(normalize_verdict("approve"), PASS)
        self.assertEqual(gate_verdicts([VerdictDecision(PASS, "ok")]).verdict, PASS)
        self.assertEqual(gate_verdicts([VerdictDecision(PASS, "ok"), VerdictDecision(INCONCLUSIVE, "missing evidence")]).verdict, INCONCLUSIVE)
        self.assertEqual(gate_verdicts([VerdictDecision(FAIL, "bad")]).verdict, FAIL)

    def test_pre_llm_redaction_summarizes_arrays_and_logs(self) -> None:
        redacted = redact_for_llm({"pnl": list(range(100)), "name": "demo"})
        groups = fold_log_lines("WARN item 1 failed\nWARN item 2 failed\nERROR boom 123\n")

        self.assertEqual(redacted["pnl"]["redacted"], "large_numeric_array")
        self.assertEqual(redacted["pnl"]["count"], 100)
        self.assertEqual(groups[0].severity, "error")
        self.assertTrue(any(group.count == 2 for group in groups))


if __name__ == "__main__":
    unittest.main()
