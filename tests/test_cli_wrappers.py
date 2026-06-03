from __future__ import annotations

import os
import subprocess
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


if __name__ == "__main__":
    unittest.main()
