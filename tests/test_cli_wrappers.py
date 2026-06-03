from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "agent_autopsy" / "agent_modified_test_failed"


class CliWrapperTest(unittest.TestCase):
    def run_openmako(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["QUANTAGENT_SECRETS_FILE"] = "/dev/null"
        return subprocess.run(
            [str(ROOT / "bin" / "openmako"), *args],
            cwd=str(ROOT),
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )

    def test_openmako_help_uses_real_cli(self) -> None:
        result = self.run_openmako("--help")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("agent-autopsy", result.stdout)

    def test_openmako_bad_run_demo_reports_failed_verification(self) -> None:
        result = self.run_openmako(
            "--no-trust-prompt",
            "agent-autopsy",
            "--project",
            str(FIXTURE),
            "--trajectory",
            str(FIXTURE / "trajectory.jsonl"),
            "--query-events",
            str(FIXTURE / "query_events.jsonl"),
            "--failure-file",
            str(FIXTURE / "failure.txt"),
            "--source-agent",
            "codex",
            "--title",
            "wrapper smoke",
            "--command",
            "python3 -m unittest",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("- status: FAILED", result.stdout)
        self.assertIn("- failure_class: verification_failed", result.stdout)
        self.assertIn("- evidence_items: 12", result.stdout)

    def test_openmako_evidence_court_bad_run_demo_reports_fail_verdict(self) -> None:
        result = self.run_openmako("--no-trust-prompt", "evidence-court", "demo", "bad-run")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# Evidence Court Report", result.stdout)
        self.assertIn("## Claim", result.stdout)
        self.assertIn("## Evidence", result.stdout)
        self.assertIn("## Scope Violations", result.stdout)
        self.assertIn("## Test Verification", result.stdout)
        self.assertIn("## Suspicious Behavior", result.stdout)
        self.assertIn("## Verdict: FAIL", result.stdout)
        self.assertIn("post-edit validation failed", result.stdout)

    def test_openmako_evidence_court_missing_tests_demo_reports_suspicious_verdict(self) -> None:
        result = self.run_openmako("--no-trust-prompt", "evidence-court", "demo", "missing-tests")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# Evidence Court Report", result.stdout)
        self.assertIn("## Verdict: SUSPICIOUS", result.stdout)
        self.assertIn("- failure_class: missing_test_evidence", result.stdout)
        self.assertIn("no command or test-output evidence was supplied", result.stdout)

    def test_openmako_evidence_court_out_of_scope_demo_reports_fail_verdict(self) -> None:
        result = self.run_openmako("--no-trust-prompt", "evidence-court", "demo", "out-of-scope")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# Evidence Court Report", result.stdout)
        self.assertIn("- file_scope: FAIL", result.stdout)
        self.assertIn("tests/test_calculator.py", result.stdout)
        self.assertIn("## Verdict: FAIL", result.stdout)
        self.assertIn("crossed the claimed patch scope", result.stdout)

    def test_openmako_evidence_court_audit_json_reports_scope_violation(self) -> None:
        result = self.run_openmako(
            "--no-trust-prompt",
            "evidence-court",
            "audit",
            "examples/evidence_court/out_of_scope.json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("- claimed_task: Fix calculator.py only. Do not edit tests.", result.stdout)
        self.assertIn("- file_scope: FAIL", result.stdout)
        self.assertIn("tests/test_calculator.py", result.stdout)
        self.assertIn("- test_output: 1 passed in 0.02s", result.stdout)
        self.assertIn("## Verdict: FAIL", result.stdout)

    def test_openmako_evidence_court_audit_json_reports_missing_tests(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "files_read": ["calculator.py"],
            "files_edited": ["calculator.py"],
            "commands_run": [],
            "test_output": "",
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("- file_scope: PASS", result.stdout)
        self.assertIn("- failure_class: missing_test_evidence", result.stdout)
        self.assertIn("## Verdict: SUSPICIOUS", result.stdout)

    def test_openmako_evidence_court_audit_does_not_misread_zero_failed_summary(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "files_read": ["calculator.py"],
            "files_edited": ["calculator.py"],
            "commands_run": ["python3 -m pytest -q"],
            "test_output": "0 failed, 3 passed in 0.03s",
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("- file_scope: PASS", result.stdout)
        self.assertIn("- failure_class: unknown", result.stdout)
        self.assertIn("## Verdict: PASS", result.stdout)

    def test_openmako_evidence_court_audit_rejects_non_object_json(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            handle.write("[]")
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", handle.name)

        self.assertEqual(result.returncode, 2)
        self.assertIn("audit record must be a JSON object", result.stderr)


if __name__ == "__main__":
    unittest.main()
