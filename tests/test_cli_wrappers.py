from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "agent_autopsy" / "agent_modified_test_failed"
DESPAIR_SMOKE_SUMMARY_REL = ".quantagent/despair_gate/test_smoke_summary.json"
DESPAIR_FAILURE_SUMMARY_REL = ".quantagent/despair_gate/test_failure_summary.json"
DESPAIR_CORRUPT_SUMMARY_REL = ".quantagent/despair_gate/test_corrupt_summary.json"


class CliWrapperTest(unittest.TestCase):
    def current_git_commit(self) -> str:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True).strip()

    def run_openmako(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["QUANTAGENT_SECRETS_FILE"] = "/dev/null"
        env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        return subprocess.run(
            [sys.executable, "-m", "quantagent.cli", *args],
            cwd=str(ROOT),
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )

    def run_despair_gate_smoke(self, *extra_args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHON"] = sys.executable
        env["QUANTAGENT_SECRETS_FILE"] = "/dev/null"
        env["OPENMAKO_DESPAIR_GATE_SUMMARY_JSON"] = DESPAIR_SMOKE_SUMMARY_REL
        env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        return subprocess.run(
            [
                "bash",
                "scripts/despair_gate.sh",
                *extra_args,
                "--skip-external-regression",
                "--skip-full-pytest",
                "--skip-public-gate",
                "--skip-desktop-gate",
            ],
            cwd=str(ROOT),
            env=env,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )

    def run_despair_gate_public_gate_failure_smoke(self) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHON"] = sys.executable
        env["QUANTAGENT_SECRETS_FILE"] = "/dev/null"
        env["OPENMAKO_DESPAIR_GATE_TEST_FAIL_SEGMENT"] = "public_gate"
        env["OPENMAKO_DESPAIR_GATE_SUMMARY_JSON"] = DESPAIR_FAILURE_SUMMARY_REL
        env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        return subprocess.run(
            [
                "bash",
                "scripts/despair_gate.sh",
                "--bench-limit",
                "1",
                "--skip-external-regression",
                "--skip-full-pytest",
                "--skip-desktop-gate",
            ],
            cwd=str(ROOT),
            env=env,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )

    def run_despair_gate_corrupt_summary_smoke(self) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHON"] = sys.executable
        env["QUANTAGENT_SECRETS_FILE"] = "/dev/null"
        env["OPENMAKO_DESPAIR_GATE_TEST_CORRUPT_SUMMARY"] = "missing_bench_fields"
        env["OPENMAKO_DESPAIR_GATE_SUMMARY_JSON"] = DESPAIR_CORRUPT_SUMMARY_REL
        env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        return subprocess.run(
            [
                "bash",
                "scripts/despair_gate.sh",
                "--bench-limit",
                "1",
                "--skip-external-regression",
                "--skip-full-pytest",
                "--skip-public-gate",
                "--skip-desktop-gate",
            ],
            cwd=str(ROOT),
            env=env,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )

    def run_remote_focused_ci_snapshot(
        self,
        runs: dict,
        remote_sha: str,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(runs, handle)
            handle.flush()
            env = os.environ.copy()
            env["OPENMAKO_FOCUSED_RUNS_JSON"] = handle.name
            env["OPENMAKO_REMOTE_MAIN_SHA"] = remote_sha
            return subprocess.run(
                ["bash", "scripts/remote_focused_ci_snapshot.sh"],
                cwd=str(ROOT),
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )

    def run_desktop_control_proof_card(self) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        return subprocess.run(
            ["bash", "scripts/desktop_control_proof_card.sh"],
            cwd=str(ROOT),
            env=env,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )

    def test_openmako_help_uses_real_cli(self) -> None:
        result = self.run_openmako("--help")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("agent-autopsy", result.stdout)

    def test_remote_focused_ci_snapshot_passes_only_matching_success_run(self) -> None:
        remote_sha = "a" * 40
        result = self.run_remote_focused_ci_snapshot(
            {
                "workflow_runs": [
                    {
                        "id": 123,
                        "head_sha": remote_sha,
                        "status": "completed",
                        "conclusion": "success",
                        "html_url": "https://github.com/example/actions/runs/123",
                    }
                ]
            },
            remote_sha,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"remote-main-sha={remote_sha}", result.stdout)
        self.assertIn("run-id=123", result.stdout)
        self.assertIn("status=completed conclusion=success", result.stdout)
        self.assertIn("not-proof=external review; endorsement; stars; reposts", result.stdout)
        self.assertIn("remote-focused-ci-snapshot: PASS", result.stdout)

    def test_remote_focused_ci_snapshot_rejects_stale_success_run(self) -> None:
        remote_sha = "b" * 40
        stale_sha = "c" * 40
        result = self.run_remote_focused_ci_snapshot(
            {
                "workflow_runs": [
                    {
                        "id": 456,
                        "head_sha": stale_sha,
                        "status": "completed",
                        "conclusion": "success",
                    }
                ]
            },
            remote_sha,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn(f"remote-main-sha={remote_sha}", result.stdout)
        self.assertIn(f"run-sha={stale_sha}", result.stdout)
        self.assertIn("latest focused run does not match remote main", result.stderr)

    def test_remote_focused_ci_snapshot_rejects_empty_run_list(self) -> None:
        remote_sha = "d" * 40
        result = self.run_remote_focused_ci_snapshot(
            {"workflow_runs": []},
            remote_sha,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn(f"remote-main-sha={remote_sha}", result.stdout)
        self.assertIn("manual-url=https://github.com/1966536805l-crypto/openmako/actions/workflows/focused.yml?query=branch%3Amain", result.stdout)
        self.assertIn("unavailable=no_focused_workflow_runs", result.stdout)
        self.assertIn("not-proof=external review; endorsement; stars; reposts", result.stdout)
        self.assertIn("no focused workflow runs found", result.stderr)

    def test_remote_focused_ci_snapshot_rejects_matching_in_progress_run(self) -> None:
        remote_sha = "d" * 40
        result = self.run_remote_focused_ci_snapshot(
            {
                "workflow_runs": [
                    {
                        "id": 789,
                        "head_sha": remote_sha,
                        "status": "in_progress",
                        "conclusion": None,
                    }
                ]
            },
            remote_sha,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn(f"remote-main-sha={remote_sha}", result.stdout)
        self.assertIn("run-id=789", result.stdout)
        self.assertIn("status=in_progress conclusion=None", result.stdout)
        self.assertIn("focused workflow is not completed/success", result.stderr)

    def test_remote_focused_ci_snapshot_rejects_missing_run_fields(self) -> None:
        remote_sha = "e" * 40
        result = self.run_remote_focused_ci_snapshot(
            {"workflow_runs": [{"id": 999}]},
            remote_sha,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn(f"remote-main-sha={remote_sha}", result.stdout)
        self.assertIn("run-id=999", result.stdout)
        self.assertIn("run-sha=None", result.stdout)
        self.assertIn("status=None conclusion=None", result.stdout)
        self.assertIn("latest focused run does not match remote main", result.stderr)

    def test_desktop_control_proof_card_surfaces_safety_rates_and_boundaries(self) -> None:
        result = self.run_desktop_control_proof_card()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("proof-command: bash scripts/desktop_control_local_gate.sh", result.stdout)
        self.assertIn("desktop-control-local-gate: status=dry_run", result.stdout)
        self.assertIn("desktop-control-local-gate: scenarios=8", result.stdout)
        self.assertIn("desktop-control-local-gate: level=L2", result.stdout)
        self.assertIn("desktop-control-local-gate: misoperation_rate=0.0", result.stdout)
        self.assertIn("desktop-control-local-gate: crash_rate=0.0", result.stdout)
        self.assertIn(
            "desktop-control-local-gate: not-proof=live desktop control, L4, L5, "
            "external endorsement, star or repost traction",
            result.stdout,
        )
        self.assertIn("openmako-desktop-control-proof-card: PASS", result.stdout)

    def test_despair_gate_smoke_uses_limited_real_cli_bench(self) -> None:
        result = self.run_despair_gate_smoke("--bench-limit", "1")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("despair-gate: coding-bench solved=1/1 success_rate=100.0", result.stdout)
        self.assertIn("despair-gate: skipping full repository pytest", result.stdout)
        self.assertIn("despair-gate: PASS", result.stdout)
        self.assertIn(f"despair-gate: summary={DESPAIR_SMOKE_SUMMARY_REL}", result.stdout)
        self.assertIn("not-proof=external review", result.stdout)
        summary = json.loads((ROOT / DESPAIR_SMOKE_SUMMARY_REL).read_text(encoding="utf-8"))
        self.assertEqual(summary["schema_version"], "despair-gate/v0.1")
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["coding_bench"]["solved"], 1)
        self.assertEqual(summary["coding_bench"]["total"], 1)
        self.assertIsInstance(summary["coding_bench"]["elapsed_seconds"], int)
        self.assertGreaterEqual(summary["coding_bench"]["elapsed_seconds"], 0)
        self.assertEqual(summary["invocation"]["git_commit"], self.current_git_commit())
        self.assertEqual(
            summary["invocation"]["argv"],
            [
                "--bench-limit",
                "1",
                "--skip-external-regression",
                "--skip-full-pytest",
                "--skip-public-gate",
                "--skip-desktop-gate",
            ],
        )
        self.assertEqual(summary["segments"]["full_pytest"], "skipped")
        self.assertEqual(summary["segment_elapsed_seconds"], {})
        self.assertIn("external review", summary["not_proof"])

    def test_despair_gate_smoke_summarizes_repeated_coding_bench(self) -> None:
        result = self.run_despair_gate_smoke("--bench-limit", "1", "--bench-repeats", "2")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("despair-gate: coding-bench solved=2/2 success_rate=100.0", result.stdout)
        self.assertIn("despair-gate: PASS", result.stdout)
        self.assertNotIn("success_rate=None", result.stdout)
        summary = json.loads((ROOT / DESPAIR_SMOKE_SUMMARY_REL).read_text(encoding="utf-8"))
        self.assertEqual(summary["coding_bench"]["repeats"], 2)
        self.assertEqual(summary["coding_bench"]["success_rate"], 100.0)

    def test_despair_gate_smoke_does_not_overwrite_default_summary(self) -> None:
        default_summary = ROOT / ".quantagent" / "despair_gate" / "last_summary.json"
        default_summary.parent.mkdir(parents=True, exist_ok=True)
        previous_summary = default_summary.read_text(encoding="utf-8") if default_summary.exists() else None

        def restore_default_summary() -> None:
            if previous_summary is None:
                default_summary.unlink(missing_ok=True)
            else:
                default_summary.write_text(previous_summary, encoding="utf-8")

        self.addCleanup(restore_default_summary)
        sentinel = {
            "schema_version": "despair-gate/v0.1",
            "status": "outer-running",
            "coding_bench": {"solved": 30, "total": 30, "limit": None},
            "segments": {"full_pytest": "running"},
        }
        default_summary.write_text(json.dumps(sentinel, sort_keys=True) + "\n", encoding="utf-8")

        result = self.run_despair_gate_smoke("--bench-limit", "1")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(default_summary.read_text(encoding="utf-8")), sentinel)
        smoke_summary = json.loads((ROOT / DESPAIR_SMOKE_SUMMARY_REL).read_text(encoding="utf-8"))
        self.assertEqual(smoke_summary["status"], "passed")
        self.assertEqual(smoke_summary["coding_bench"]["limit"], 1)

    def test_despair_gate_records_failed_segment_summary(self) -> None:
        result = self.run_despair_gate_public_gate_failure_smoke()

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("despair-gate: injecting test failure for segment=public_gate", result.stderr)
        self.assertIn(
            f"despair-gate: FAILED segment=public_gate summary={DESPAIR_FAILURE_SUMMARY_REL}",
            result.stderr,
        )
        summary = json.loads((ROOT / DESPAIR_FAILURE_SUMMARY_REL).read_text(encoding="utf-8"))
        self.assertEqual(summary["schema_version"], "despair-gate/v0.1")
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["segments"]["external_regression"], "skipped")
        self.assertEqual(summary["segments"]["full_pytest"], "skipped")
        self.assertEqual(summary["segments"]["public_gate"], "failed")
        self.assertEqual(summary["segments"]["desktop_gate"], "skipped")
        self.assertEqual(summary["failure"], {"segment": "public_gate", "exit_code": 1})
        self.assertIsInstance(summary["segment_elapsed_seconds"]["public_gate"], int)
        self.assertGreaterEqual(summary["segment_elapsed_seconds"]["public_gate"], 0)
        self.assertEqual(summary["coding_bench"]["solved"], 1)

    def test_despair_gate_rejects_corrupt_pass_summary(self) -> None:
        result = self.run_despair_gate_corrupt_summary_smoke()

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(
            "despair-gate: corrupting summary for test=missing_bench_fields",
            result.stderr,
        )
        self.assertIn("despair-gate: invalid summary fields=", result.stderr)
        self.assertIn("coding_bench.solved", result.stderr)
        self.assertIn("coding_bench.total", result.stderr)
        self.assertNotIn("despair-gate: PASS", result.stdout)
        summary = json.loads((ROOT / DESPAIR_CORRUPT_SUMMARY_REL).read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["failure"], {"segment": "unknown", "exit_code": 1})

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
        self.assertIn("- failed_at: query:post_tool shell (step 3)", result.stdout)
        self.assertIn("- evidence_items: 12", result.stdout)

    def test_openmako_evidence_court_bad_run_demo_reports_fail_verdict(self) -> None:
        result = self.run_openmako("--no-trust-prompt", "evidence-court", "demo", "bad-run")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# Evidence Court Report", result.stdout)
        self.assertIn("## Claim", result.stdout)
        self.assertIn("## Evidence", result.stdout)
        self.assertIn("## Scope Violations", result.stdout)
        self.assertIn("## Patch Shape", result.stdout)
        self.assertIn("- bucket: no_edits", result.stdout)
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
        self.assertIn("- bucket: mixed_test_source", result.stdout)
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

    def test_openmako_evidence_court_audit_json_flag_outputs_machine_readable_verdict(self) -> None:
        result = self.run_openmako(
            "--no-trust-prompt",
            "evidence-court",
            "audit",
            "--json",
            "examples/evidence_court/out_of_scope.json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema_version"], "evidence-court/v0.1")
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["failure_class"], "scope_violation")
        self.assertEqual(payload["finding_types"], ["scope_violation"])
        self.assertEqual(
            payload["patch_shape"],
            {
                "bucket": "mixed_test_source",
                "config_files": [],
                "edited_files": ["calculator.py", "tests/test_calculator.py"],
                "other_files": [],
                "source_files": ["calculator.py"],
                "test_files": ["tests/test_calculator.py"],
            },
        )
        self.assertEqual(payload["report"]["evidence"][0]["source"], "task")

    def test_openmako_evidence_court_audit_json_reports_patch_shape_without_changing_verdict(self) -> None:
        record = {
            "claimed_task": "Add regression test and implementation.",
            "files_edited": ["tests/test_api.py", "src/api.py", "README.md"],
            "commands_run": [{"command": "python3 -m pytest tests/test_api.py -q", "exit_code": 0}],
            "test_output": "1 passed in 0.02s",
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["patch_shape"]["bucket"], "mixed_test_source")
        self.assertEqual(payload["patch_shape"]["test_files"], ["tests/test_api.py"])
        self.assertEqual(payload["patch_shape"]["source_files"], ["src/api.py"])
        self.assertEqual(payload["patch_shape"]["config_files"], [])
        self.assertEqual(payload["patch_shape"]["other_files"], ["README.md"])
        self.assertFalse(payload["verifier_tamper_risk"]["verifier_tamper_risk"])

    def test_openmako_evidence_court_audit_json_flags_missing_agent_risk_evidence(self) -> None:
        record = {
            "claimed_task": "Audit an autonomous local agent risk claim.",
            "commands_run": [{"command": "python3 -m pytest tests/test_agent_risk.py -q", "exit_code": 0}],
            "test_output": "1 passed in 0.02s",
            "final_claim": "Live control and self-improvement are verified.",
            "agent_risk_ledger": {
                "live_control": True,
                "self_improved": True,
            },
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "SUSPICIOUS")
        self.assertEqual(payload["status"], "UNVERIFIED")
        self.assertEqual(payload["failure_class"], "missing_agent_risk_evidence")
        self.assertEqual(payload["failed_at"], "agent_risk_ledger")
        self.assertIn("missing_agent_risk_evidence", payload["finding_types"])
        self.assertEqual(payload["agent_risk_ledger"]["live_control"], True)
        self.assertEqual(payload["agent_risk_ledger"]["self_improved"], True)

    def test_openmako_evidence_court_audit_json_accepts_supported_agent_risk_ledger(self) -> None:
        record = {
            "claimed_task": "Audit an autonomous local agent risk claim.",
            "commands_run": [{"command": "python3 -m pytest tests/test_agent_risk.py -q", "exit_code": 0}],
            "test_output": "1 passed in 0.02s",
            "final_claim": "Live control and self-improvement are verified.",
            "agent_risk_ledger": {
                "live_control": True,
                "self_improved": True,
                "permission_evidence": ["operator-approved local gateway token scope"],
                "tool_call_evidence": ["tool invocation ledger captured shell and browser calls"],
                "skill_change_evidence": ["skills/agent-risk-review.md created from a reviewed run"],
            },
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["failure_class"], "")
        self.assertEqual(payload["agent_risk_ledger"]["permission_evidence"], ["operator-approved local gateway token scope"])

    def test_openmako_evidence_court_audit_json_preserves_extra_agent_risk_fields(self) -> None:
        record = {
            "claimed_task": "Audit an autonomous local agent risk claim.",
            "commands_run": [{"command": "python3 -m pytest tests/test_agent_risk.py -q", "exit_code": 0}],
            "test_output": "1 passed in 0.02s",
            "final_claim": "Agent risk metadata was preserved.",
            "agent_risk_ledger": {
                "risk_review_id": "risk-44",
                "policy_profile": "local-read-only",
            },
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["agent_risk_ledger"], record["agent_risk_ledger"])

    def test_openmako_evidence_court_rejects_malformed_extra_agent_risk_fields(self) -> None:
        record = {
            "claimed_task": "Audit an autonomous local agent risk claim.",
            "commands_run": [{"command": "python3 -m pytest tests/test_agent_risk.py -q", "exit_code": 0}],
            "test_output": "1 passed in 0.02s",
            "final_claim": "Agent risk metadata was preserved.",
            "agent_risk_ledger": {
                "risk_review_id": {"id": "risk-44"},
                "policy_profile": ["local-read-only"],
            },
        }
        for command in ("audit", "validate"):
            with self.subTest(command=command):
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(record, handle)
                    handle.flush()
                    result = self.run_openmako("--no-trust-prompt", "evidence-court", command, handle.name)

                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("agent_risk_ledger.risk_review_id must be a string", result.stderr)

    def test_openmako_evidence_court_audit_json_flags_test_only_success_claim(self) -> None:
        record = {
            "claimed_task": "Fix the API bug.",
            "files_read": ["src/api.py", "tests/test_api.py"],
            "files_edited": ["tests/test_api.py"],
            "commands_run": [{"command": "python3 -m pytest tests/test_api.py -q", "exit_code": 0}],
            "test_output": "1 passed in 0.02s",
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "SUSPICIOUS")
        self.assertEqual(payload["status"], "UNVERIFIED")
        self.assertEqual(payload["failure_class"], "verifier_tamper_risk")
        self.assertEqual(payload["failed_at"], "files_edited")
        self.assertEqual(payload["patch_shape"]["bucket"], "test_only")
        self.assertEqual(payload["verifier_tamper_risk"]["verifier_tamper_risk"], True)
        self.assertEqual(payload["verifier_tamper_risk"]["modified_paths"], ["tests/test_api.py"])
        self.assertEqual(
            payload["verifier_tamper_risk"]["reasons"],
            {"tests/test_api.py": "test_only_success_path"},
        )
        self.assertIn("verifier_tamper_risk", payload["finding_types"])

    def test_openmako_evidence_court_audit_json_reports_missing_edited_file_evidence(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "files_read": ["calculator.py"],
            "files_edited": [],
            "commands_run": [{"command": "python3 -m pytest tests/test_calculator.py -q", "exit_code": 0}],
            "test_output": "1 passed in 0.02s",
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "SUSPICIOUS")
        self.assertEqual(payload["status"], "UNVERIFIED")
        self.assertEqual(payload["failure_class"], "missing_edited_file_evidence")
        self.assertEqual(payload["patch_shape"]["bucket"], "no_edits")

    def test_openmako_evidence_court_audit_json_reports_missing_source_edit_evidence(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "files_read": ["calculator.py", "README.md"],
            "files_edited": ["README.md"],
            "commands_run": [{"command": "python3 -m pytest tests/test_calculator.py -q", "exit_code": 0}],
            "test_output": "1 passed in 0.02s",
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "SUSPICIOUS")
        self.assertEqual(payload["status"], "UNVERIFIED")
        self.assertEqual(payload["failure_class"], "missing_source_edit_evidence")
        self.assertEqual(payload["failed_at"], "files_edited")
        self.assertEqual(payload["patch_shape"]["bucket"], "other_only")

    def test_openmako_evidence_court_audit_does_not_count_non_validation_command_exit_code_as_test(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "files_read": ["calculator.py"],
            "files_edited": ["calculator.py"],
            "commands_run": [{"command": "python3 scripts/print_status.py", "exit_code": 0}],
            "test_output": "",
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "SUSPICIOUS")
        self.assertEqual(payload["status"], "UNVERIFIED")
        self.assertEqual(payload["failure_class"], "missing_test_evidence")
        self.assertEqual(payload["failed_at"], "final_claim")

    def test_openmako_evidence_court_audit_requires_validation_command_for_source_repair_claim(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "files_read": ["calculator.py"],
            "files_edited": ["calculator.py"],
            "commands_run": [{"command": "python3 scripts/print_status.py", "exit_code": 0}],
            "test_output": "1 passed in 0.02s",
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "SUSPICIOUS")
        self.assertEqual(payload["status"], "UNVERIFIED")
        self.assertEqual(payload["failure_class"], "missing_test_evidence")
        self.assertEqual(payload["failed_at"], "final_claim")

    def test_openmako_evidence_court_audit_does_not_count_orphan_test_output_as_source_repair_proof(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "files_read": ["calculator.py"],
            "files_edited": ["calculator.py"],
            "commands_run": [],
            "test_output": "1 passed in 0.02s",
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "SUSPICIOUS")
        self.assertEqual(payload["status"], "UNVERIFIED")
        self.assertEqual(payload["failure_class"], "missing_test_evidence")
        self.assertEqual(payload["failed_at"], "final_claim")

    def test_openmako_evidence_court_audit_failed_validation_exit_code_overrides_passing_text(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "files_read": ["calculator.py"],
            "files_edited": ["calculator.py"],
            "commands_run": [{"command": "python3 -m pytest tests/test_calculator.py -q", "exit_code": 1}],
            "test_output": "1 passed in 0.02s",
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["failure_class"], "post_edit_validation_failure")
        self.assertEqual(payload["failed_at"], "test_output")

    def test_openmako_evidence_court_audit_test_output_exit_code_overrides_pass_status(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "files_read": ["calculator.py"],
            "files_edited": ["calculator.py"],
            "commands_run": [{"command": "python3 -m pytest tests/test_calculator.py -q", "exit_code": 0}],
            "test_output": {"status": "passed", "exit_code": 1, "output": "1 passed in 0.02s"},
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["failure_class"], "post_edit_validation_failure")
        self.assertEqual(payload["failed_at"], "test_output")

    def test_openmako_evidence_court_audit_test_output_failure_text_overrides_pass_status(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "files_read": ["calculator.py"],
            "files_edited": ["calculator.py"],
            "commands_run": [{"command": "python3 -m pytest tests/test_calculator.py -q", "exit_code": 0}],
            "test_output": {"status": "passed", "output": "1 failed, 0 passed in 0.02s"},
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["failure_class"], "post_edit_validation_failure")
        self.assertEqual(payload["failed_at"], "test_output")

    def test_openmako_evidence_court_audit_pytest_failed_line_overrides_passed_count(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "files_read": ["calculator.py"],
            "files_edited": ["calculator.py"],
            "commands_run": [{"command": "python3 -m pytest tests/test_calculator.py -q", "exit_code": 0}],
            "test_output": (
                "FAILED tests/test_calculator.py::test_add - AssertionError: expected 2 got 1\n"
                "1 passed in 0.02s"
            ),
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["failure_class"], "post_edit_validation_failure")
        self.assertEqual(payload["failed_at"], "test_output")

    def test_openmako_evidence_court_audit_test_output_failure_summary_overrides_pass_output(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "files_read": ["calculator.py"],
            "files_edited": ["calculator.py"],
            "commands_run": [{"command": "python3 -m pytest tests/test_calculator.py -q", "exit_code": 0}],
            "test_output": {
                "status": "passed",
                "output": "1 passed in 0.02s",
                "summary": "1 failed, 0 passed in 0.02s",
            },
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["failure_class"], "post_edit_validation_failure")
        self.assertEqual(payload["failed_at"], "test_output")

    def test_openmako_evidence_court_audit_test_output_error_count_overrides_passed_count(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "files_read": ["calculator.py"],
            "files_edited": ["calculator.py"],
            "commands_run": [{"command": "python3 -m pytest tests/test_calculator.py -q", "exit_code": 0}],
            "test_output": "1 error, 0 failed, 3 passed in 0.03s",
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["failure_class"], "post_edit_validation_failure")
        self.assertEqual(payload["failed_at"], "test_output")

    def test_openmako_evidence_court_audit_test_output_failure_count_overrides_passed_count(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "files_read": ["calculator.py"],
            "files_edited": ["calculator.py"],
            "commands_run": [{"command": "python3 -m pytest tests/test_calculator.py -q", "exit_code": 0}],
            "test_output": "1 failure, 3 passed in 0.03s",
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["failure_class"], "post_edit_validation_failure")
        self.assertEqual(payload["failed_at"], "test_output")

    def test_openmako_evidence_court_audit_rejects_non_integer_command_exit_code(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "files_read": ["calculator.py"],
            "files_edited": ["calculator.py"],
            "commands_run": [{"command": "python3 -m pytest tests/test_calculator.py -q", "exit_code": "1"}],
            "test_output": "1 passed in 0.02s",
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("commands_run exit_code must be an integer", result.stderr)

    def test_openmako_evidence_court_audit_rejects_non_integer_test_output_exit_code(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "files_read": ["calculator.py"],
            "files_edited": ["calculator.py"],
            "commands_run": [{"command": "python3 -m pytest tests/test_calculator.py -q", "exit_code": 0}],
            "test_output": {"status": "passed", "exit_code": "1", "output": "1 passed in 0.02s"},
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("test_output exit_code must be an integer", result.stderr)

    def test_openmako_evidence_court_audit_rejects_non_string_test_output_status(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "files_read": ["calculator.py"],
            "files_edited": ["calculator.py"],
            "commands_run": [{"command": "python3 -m pytest tests/test_calculator.py -q", "exit_code": 0}],
            "test_output": {"status": True, "output": "1 passed in 0.02s"},
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("test_output status must be a string", result.stderr)

    def test_openmako_evidence_court_audit_rejects_non_string_test_output_text_fields(self) -> None:
        cases = (
            (["1 failed in 0.02s"], "test_output must be a string or object"),
            ({"status": "passed", "output": ["1 failed in 0.02s"]}, "test_output output must be a string"),
            ({"status": "passed", "summary": {"failed": 1}}, "test_output summary must be a string"),
        )
        for test_output, message in cases:
            with self.subTest(message=message):
                record = {
                    "claimed_task": "Fix calculator.py.",
                    "files_read": ["calculator.py"],
                    "files_edited": ["calculator.py"],
                    "commands_run": [{"command": "python3 -m pytest tests/test_calculator.py -q", "exit_code": 0}],
                    "test_output": test_output,
                    "final_claim": "Fixed and verified.",
                }
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(record, handle)
                    handle.flush()
                    result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn(message, result.stderr)

    def test_openmako_evidence_court_audit_rejects_boolean_exit_codes(self) -> None:
        cases = (
            (
                {
                    "commands_run": [
                        {"command": "python3 -m pytest tests/test_calculator.py -q", "exit_code": False}
                    ],
                    "test_output": "1 passed in 0.02s",
                },
                "commands_run exit_code must be an integer",
            ),
            (
                {
                    "commands_run": [{"command": "python3 -m pytest tests/test_calculator.py -q", "exit_code": 0}],
                    "test_output": {"status": "passed", "exit_code": False, "output": "1 passed in 0.02s"},
                },
                "test_output exit_code must be an integer",
            ),
        )
        for evidence, message in cases:
            with self.subTest(message=message):
                record = {
                    "claimed_task": "Fix calculator.py.",
                    "files_read": ["calculator.py"],
                    "files_edited": ["calculator.py"],
                    "final_claim": "Fixed and verified.",
                    **evidence,
                }
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(record, handle)
                    handle.flush()
                    result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn(message, result.stderr)

    def test_openmako_evidence_court_audit_json_allows_config_only_repair_evidence(self) -> None:
        record = {
            "claimed_task": "Fix project packaging metadata.",
            "files_read": ["pyproject.toml"],
            "files_edited": ["pyproject.toml"],
            "commands_run": [{"command": "python3 -m pytest tests/test_metadata.py -q", "exit_code": 0}],
            "test_output": "1 passed in 0.02s",
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["status"], "PASSED")
        self.assertEqual(payload["failure_class"], "")
        self.assertEqual(payload["patch_shape"]["bucket"], "config_only")
        self.assertEqual(payload["patch_shape"]["config_files"], ["pyproject.toml"])

    def test_openmako_evidence_court_audit_does_not_treat_fixture_as_fix_task(self) -> None:
        record = {
            "claimed_task": "Inspect fixture metadata.",
            "files_read": ["tests/fixtures/example.json"],
            "files_edited": [],
            "commands_run": [{"command": "python3 -m pytest tests/test_metadata.py -q", "exit_code": 0}],
            "test_output": "1 passed in 0.02s",
            "final_claim": "Fixture metadata verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["failure_class"], "")

    def test_openmako_evidence_court_audit_does_not_treat_update_status_as_patch_task(self) -> None:
        record = {
            "claimed_task": "Check update status for the benchmark run.",
            "files_read": ["reports/status.json"],
            "files_edited": [],
            "commands_run": [{"command": "python3 scripts/check_status.py", "exit_code": 0}],
            "test_output": "1 passed in 0.02s",
            "final_claim": "Update status check completed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["failure_class"], "")

    def test_openmako_evidence_court_audit_json_preserves_run_metrics(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "files_read": ["calculator.py"],
            "files_edited": ["calculator.py"],
            "commands_run": [{"command": "python3 -m pytest tests/test_calculator.py -q", "exit_code": 0}],
            "test_output": "1 passed in 0.02s",
            "run_metrics": {
                "duration_seconds": 1.4,
                "command_count": 1,
                "input_tokens": 1200,
                "output_tokens": 320,
                "estimated_cost_usd": 0.004,
                "missing_telemetry": ["actual_cost_usd"],
            },
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["run_metrics"], record["run_metrics"])
        metric_items = [item for item in payload["report"]["evidence"] if item["name"] == "run_metrics"]
        self.assertEqual(len(metric_items), 1)
        self.assertEqual(metric_items[0]["data"]["run_metrics"], record["run_metrics"])

    def test_openmako_evidence_court_audit_rejects_malformed_run_metrics(self) -> None:
        cases: tuple[tuple[str, dict[str, object], str], ...] = (
            ("duration-string", {"duration_seconds": "fast"}, "run_metrics.duration_seconds must be a number"),
            ("negative-duration", {"duration_seconds": -0.1}, "run_metrics.duration_seconds must be non-negative"),
            ("token-string", {"input_tokens": "many"}, "run_metrics.input_tokens must be an integer"),
            ("token-bool", {"output_tokens": False}, "run_metrics.output_tokens must be an integer"),
            ("negative-token", {"total_tokens": -1}, "run_metrics.total_tokens must be non-negative"),
            ("cost-string", {"estimated_cost_usd": "free"}, "run_metrics.estimated_cost_usd must be a number"),
            ("provider-list", {"provider": ["openai"]}, "run_metrics.provider must be a string"),
        )
        for case_name, run_metrics, message in cases:
            with self.subTest(case_name=case_name):
                record = {
                    "claimed_task": "Fix calculator.py.",
                    "files_read": ["calculator.py"],
                    "files_edited": ["calculator.py"],
                    "commands_run": [{"command": "python3 -m pytest tests/test_calculator.py -q", "exit_code": 0}],
                    "test_output": "1 passed in 0.02s",
                    "run_metrics": run_metrics,
                    "final_claim": "Fixed and verified.",
                }
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(record, handle)
                    handle.flush()
                    result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn(message, result.stderr)

    def test_openmako_evidence_court_audit_json_preserves_artifact_provenance(self) -> None:
        record = {
            "claimed_task": "Compare benchmark artifact outputs.",
            "files_read": ["bench/output.jsonl"],
            "files_edited": ["bench/output.swtbench.jsonl"],
            "commands_run": [{"command": "python3 scripts/compare_outputs.py", "exit_code": 0}],
            "test_output": "1 passed in 0.02s",
            "artifact_provenance": {
                "eval_rule_version": "swtbench-strip-model-patch/v2",
                "eval_rule_commit": "abc1234",
                "runner_version": "openhands-benchmark/2026-06-05",
                "runner_commit": "def5678",
                "input_hashes": {"output.jsonl": "sha256:111"},
                "output_hashes": {"output.swtbench.jsonl": "sha256:222"},
                "missing_provenance": ["container_digest"],
            },
            "final_claim": "Artifact comparison was preserved.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)
            text_result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["artifact_provenance"], record["artifact_provenance"])
        provenance_items = [
            item for item in payload["report"]["evidence"] if item["name"] == "artifact_provenance"
        ]
        self.assertEqual(len(provenance_items), 1)
        self.assertEqual(provenance_items[0]["data"]["artifact_provenance"], record["artifact_provenance"])
        self.assertEqual(text_result.returncode, 0, text_result.stderr)
        self.assertIn("## Artifact Provenance", text_result.stdout)
        self.assertIn("eval_rule_version=swtbench-strip-model-patch/v2", text_result.stdout)

    def test_openmako_evidence_court_audit_json_preserves_ledger_identity(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "files_read": ["calculator.py"],
            "files_edited": ["calculator.py"],
            "commands_run": [{"command": "python3 -m pytest tests/test_calculator.py -q", "exit_code": 0}],
            "test_output": "1 passed in 0.02s",
            "ledger_identity": {
                "session_id": "session-a",
                "task_id": "task-17",
                "parent_id": "parent-run",
                "tool_invocation_ids": ["read-1", "patch-1", "test-1"],
                "missing_identity": ["external_run_id"],
            },
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)
            text_result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["ledger_identity"], record["ledger_identity"])
        identity_items = [item for item in payload["report"]["evidence"] if item["name"] == "ledger_identity"]
        self.assertEqual(len(identity_items), 1)
        self.assertEqual(identity_items[0]["data"]["ledger_identity"], record["ledger_identity"])
        self.assertEqual(text_result.returncode, 0, text_result.stderr)
        self.assertIn("## Ledger Identity", text_result.stdout)
        self.assertIn("session_id=session-a", text_result.stdout)

    def test_openmako_evidence_court_audit_json_preserves_extra_ledger_identity_fields(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "files_read": ["calculator.py"],
            "files_edited": ["calculator.py"],
            "commands_run": [{"command": "python3 -m pytest tests/test_calculator.py -q", "exit_code": 0}],
            "test_output": "1 passed in 0.02s",
            "ledger_identity": {
                "session_id": "session-a",
                "run_id": "run-44",
                "trace_id": "trace-abc",
            },
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["ledger_identity"], record["ledger_identity"])

    def test_openmako_evidence_court_rejects_malformed_extra_ledger_identity_fields(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "files_read": ["calculator.py"],
            "files_edited": ["calculator.py"],
            "commands_run": [{"command": "python3 -m pytest tests/test_calculator.py -q", "exit_code": 0}],
            "test_output": "1 passed in 0.02s",
            "ledger_identity": {
                "session_id": "session-a",
                "run_id": {"id": "run-44"},
                "trace_id": ["trace-abc"],
            },
            "final_claim": "Fixed and verified.",
        }
        for command in ("audit", "validate"):
            with self.subTest(command=command):
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(record, handle)
                    handle.flush()
                    result = self.run_openmako("--no-trust-prompt", "evidence-court", command, handle.name)

                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("ledger_identity.run_id must be a string", result.stderr)

    def test_openmako_evidence_court_rejects_malformed_artifact_provenance_text_fields(self) -> None:
        record = {
            "claimed_task": "Compare benchmark artifact outputs.",
            "files_read": ["bench/output.jsonl"],
            "files_edited": ["bench/output.swtbench.jsonl"],
            "commands_run": [{"command": "python3 scripts/compare_outputs.py", "exit_code": 0}],
            "test_output": "1 passed in 0.02s",
            "artifact_provenance": {
                "eval_rule_version": {"version": "swtbench-strip-model-patch/v2"},
                "runner_commit": ["def5678"],
                "output_hashes": {"output.swtbench.jsonl": "sha256:222"},
            },
            "final_claim": "Artifact comparison was preserved.",
        }
        for command in ("audit", "validate"):
            with self.subTest(command=command):
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(record, handle)
                    handle.flush()
                    result = self.run_openmako("--no-trust-prompt", "evidence-court", command, handle.name)

                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("artifact_provenance.eval_rule_version must be a string", result.stderr)

    def test_openmako_evidence_court_rejects_malformed_artifact_hash_values(self) -> None:
        record = {
            "claimed_task": "Compare benchmark artifact outputs.",
            "files_read": ["bench/output.jsonl"],
            "files_edited": ["bench/output.swtbench.jsonl"],
            "commands_run": [{"command": "python3 scripts/compare_outputs.py", "exit_code": 0}],
            "test_output": "1 passed in 0.02s",
            "artifact_provenance": {
                "eval_rule_version": "swtbench-strip-model-patch/v2",
                "input_hashes": {"output.jsonl": {"sha256": "111"}},
                "output_hashes": {"output.swtbench.jsonl": ["sha256:222"]},
            },
            "final_claim": "Artifact comparison was preserved.",
        }
        for command in ("audit", "validate"):
            with self.subTest(command=command):
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(record, handle)
                    handle.flush()
                    result = self.run_openmako("--no-trust-prompt", "evidence-court", command, handle.name)

                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("artifact_provenance.input_hashes values must be strings", result.stderr)

    def test_openmako_evidence_court_artifact_provenance_fixture_is_auditable(self) -> None:
        result = self.run_openmako(
            "--no-trust-prompt",
            "evidence-court",
            "audit",
            "--ci",
            "--json",
            "examples/evidence_court/artifact_provenance.json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["artifact_provenance"]["eval_rule_version"], "swtbench-strip-model-patch/v2")
        self.assertEqual(
            payload["artifact_provenance"]["output_hashes"],
            {"output.swtbench.jsonl": "sha256:222"},
        )

    def test_openmako_evidence_court_swtbench_patch_artifact_fixture_is_auditable(self) -> None:
        result = self.run_openmako(
            "--no-trust-prompt",
            "evidence-court",
            "audit",
            "--ci",
            "--json",
            "examples/evidence_court/swtbench_patch_artifact.json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["patch_shape"]["bucket"], "mixed_test_source")
        self.assertEqual(payload["patch_shape"]["test_files"], ["tests/test_calculator.py"])
        self.assertEqual(payload["patch_shape"]["source_files"], ["src/calculator.py"])
        self.assertEqual(payload["patch_shape"]["other_files"], ["bench/output.swtbench.jsonl"])
        self.assertFalse(payload["verifier_tamper_risk"]["verifier_tamper_risk"])
        self.assertEqual(payload["artifact_provenance"]["eval_rule_version"], "swtbench-strip-model-patch/v2")
        self.assertEqual(
            payload["artifact_provenance"]["output_hashes"],
            {"output.swtbench.jsonl": "sha256:222"},
        )

    def test_openmako_evidence_court_config_only_repair_fixture_is_auditable(self) -> None:
        result = self.run_openmako(
            "--no-trust-prompt",
            "evidence-court",
            "audit",
            "--ci",
            "--json",
            "examples/evidence_court/config_only_repair.json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["status"], "PASSED")
        self.assertEqual(payload["failure_class"], "")
        self.assertEqual(payload["patch_shape"]["bucket"], "config_only")
        self.assertEqual(payload["patch_shape"]["config_files"], ["pyproject.toml"])

    def test_openmako_evidence_court_verifier_tamper_fixture_is_auditable(self) -> None:
        result = self.run_openmako(
            "--no-trust-prompt",
            "evidence-court",
            "audit",
            "--ci",
            "--json",
            "examples/evidence_court/verifier_tamper_risk.json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "SUSPICIOUS")
        self.assertEqual(payload["failure_class"], "verifier_tamper_risk")
        self.assertEqual(payload["verifier_tamper_risk"]["modified_paths"], ["benchmarks/verifier.py"])
        self.assertEqual(
            payload["verifier_tamper_risk"]["reasons"],
            {"benchmarks/verifier.py": "verifier_or_harness_path"},
        )

    def test_openmako_evidence_court_audit_ci_returns_nonzero_for_fail(self) -> None:
        result = self.run_openmako(
            "--no-trust-prompt",
            "evidence-court",
            "audit",
            "--ci",
            "--json",
            "examples/evidence_court/out_of_scope.json",
        )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema_version"], "evidence-court/v0.1")
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertEqual(result.stderr, "")

    def test_openmako_evidence_court_validate_accepts_supported_record(self) -> None:
        result = self.run_openmako(
            "--no-trust-prompt",
            "evidence-court",
            "validate",
            "examples/evidence_court/out_of_scope.json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "record accepted\n")

    def test_openmako_evidence_court_validate_json_reports_acceptance(self) -> None:
        result = self.run_openmako(
            "--no-trust-prompt",
            "evidence-court",
            "validate",
            "--json",
            "examples/evidence_court/out_of_scope.json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema_version"], "evidence-court/v0.1")
        self.assertEqual(payload["status"], "accepted")
        self.assertTrue(payload["record"].endswith("examples/evidence_court/out_of_scope.json"))

    def test_openmako_evidence_court_audit_json_reports_missing_tests(self) -> None:
        result = self.run_openmako(
            "--no-trust-prompt",
            "evidence-court",
            "audit",
            "examples/evidence_court/missing_tests.json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("- file_scope: PASS", result.stdout)
        self.assertIn("- failure_class: missing_test_evidence", result.stdout)
        self.assertIn("## Verdict: SUSPICIOUS", result.stdout)

    def test_openmako_evidence_court_audit_ci_allows_suspicious_for_review(self) -> None:
        result = self.run_openmako(
            "--no-trust-prompt",
            "evidence-court",
            "audit",
            "--ci",
            "examples/evidence_court/missing_tests.json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("## Verdict: SUSPICIOUS", result.stdout)

    def test_openmako_evidence_court_audit_ci_can_fail_on_suspicious(self) -> None:
        result = self.run_openmako(
            "--no-trust-prompt",
            "evidence-court",
            "audit",
            "--ci",
            "--fail-on",
            "suspicious",
            "--json",
            "examples/evidence_court/missing_tests.json",
        )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema_version"], "evidence-court/v0.1")
        self.assertEqual(payload["verdict"], "SUSPICIOUS")
        self.assertEqual(payload["failure_class"], "missing_test_evidence")

    def test_openmako_evidence_court_record_from_jsonl_builds_auditable_record(self) -> None:
        converted = self.run_openmako(
            "--no-trust-prompt",
            "evidence-court",
            "record",
            "from-jsonl",
            "examples/evidence_court/simple_events.jsonl",
        )

        self.assertEqual(converted.returncode, 0, converted.stderr)
        record = json.loads(converted.stdout)
        self.assertEqual(record["allowed_files"], ["calculator.py"])
        self.assertEqual(record["files_edited"], ["calculator.py", "tests/test_calculator.py"])
        self.assertEqual(record["test_output"], "1 passed in 0.02s")

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(audited.returncode, 0, audited.stderr)
        payload = json.loads(audited.stdout)
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertEqual(payload["failure_class"], "scope_violation")

    def test_openmako_evidence_court_record_from_jsonl_rejects_mixed_task_claims(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8") as handle:
            handle.write('{"kind":"task","claimed_task":"Fix calculator.py."}\n')
            handle.write('{"kind":"task","claimed_task":"Rewrite report.md."}\n')
            handle.flush()
            converted = self.run_openmako("--no-trust-prompt", "evidence-court", "record", "from-jsonl", handle.name)

        self.assertEqual(converted.returncode, 2)
        self.assertEqual(converted.stdout, "")
        self.assertIn("claimed_task values must not be mixed", converted.stderr)

    def test_openmako_evidence_court_record_from_jsonl_rejects_mixed_allowed_files(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8") as handle:
            handle.write('{"kind":"task","claimed_task":"Fix calculator.py.","allowed_files":["calculator.py"]}\n')
            handle.write(
                '{"kind":"task","claimed_task":"Fix calculator.py.",'
                '"allowed_files":["calculator.py","tests/test_calculator.py"]}\n'
            )
            handle.flush()
            converted = self.run_openmako("--no-trust-prompt", "evidence-court", "record", "from-jsonl", handle.name)

        self.assertEqual(converted.returncode, 2)
        self.assertEqual(converted.stdout, "")
        self.assertIn("allowed_files values must not be mixed", converted.stderr)

    def test_openmako_evidence_court_record_from_jsonl_deduplicates_file_evidence(self) -> None:
        source_hunk = (
            "--- a/calculator.py\n"
            "+++ b/calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def add(a, b): return a - b\n"
            "+def add(a, b): return a + b"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8") as handle:
            handle.write('{"kind":"task","claimed_task":"Fix calculator.py."}\n')
            handle.write('{"kind":"read","file":"calculator.py"}\n')
            handle.write('{"kind":"read","file":"calculator.py"}\n')
            handle.write(json.dumps({"kind": "edit", "file": "calculator.py", "diff_hunks": [source_hunk]}) + "\n")
            handle.write(json.dumps({"kind": "edit", "file": "calculator.py", "diff_hunks": [source_hunk]}) + "\n")
            handle.write(
                '{"kind":"command","command":"python3 -m pytest tests/test_calculator.py -q",'
                '"exit_code":0,"output":"1 passed in 0.02s"}\n'
            )
            handle.write('{"kind":"final_claim","text":"Fixed and verified."}\n')
            handle.flush()
            converted = self.run_openmako("--no-trust-prompt", "evidence-court", "record", "from-jsonl", handle.name)

        self.assertEqual(converted.returncode, 0, converted.stderr)
        record = json.loads(converted.stdout)
        self.assertEqual(record["files_read"], ["calculator.py"])
        self.assertEqual(record["files_edited"], ["calculator.py"])
        self.assertEqual(record["diff_hunks"], [source_hunk])

    def test_openmako_evidence_court_record_from_jsonl_keeps_validation_output_after_non_validation_command(
        self,
    ) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8") as handle:
            handle.write('{"kind":"task","claimed_task":"Fix calculator.py."}\n')
            handle.write(
                '{"kind":"command","command":"python3 -m pytest tests/test_calculator.py -q",'
                '"exit_code":0,"output":"1 passed in 0.02s"}\n'
            )
            handle.write(
                '{"kind":"command","command":"python3 scripts/format_report.py",'
                '"exit_code":0,"output":"formatted report.md"}\n'
            )
            handle.flush()
            converted = self.run_openmako("--no-trust-prompt", "evidence-court", "record", "from-jsonl", handle.name)

        self.assertEqual(converted.returncode, 0, converted.stderr)
        record = json.loads(converted.stdout)
        self.assertEqual(record["test_output"], "1 passed in 0.02s")

    def test_openmako_evidence_court_record_from_jsonl_preserves_ledger_identity(self) -> None:
        source_hunk = (
            "--- a/calculator.py\n"
            "+++ b/calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def add(a, b): return a - b\n"
            "+def add(a, b): return a + b"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "kind": "task",
                        "claimed_task": "Fix calculator.py.",
                        "session_id": "session-a",
                        "task_id": "task-17",
                        "ledger_identity": {"run_id": "run-44"},
                    }
                )
                + "\n"
            )
            handle.write(
                json.dumps(
                    {
                        "kind": "edit",
                        "file": "calculator.py",
                        "diff_hunks": [source_hunk],
                        "tool_invocation_ids": ["patch-1"],
                        "missing_identity": ["external_run_id"],
                    }
                )
                + "\n"
            )
            handle.write(
                json.dumps(
                    {
                        "kind": "command",
                        "command": "python3 -m pytest tests/test_calculator.py -q",
                        "exit_code": 0,
                        "output": "1 passed in 0.02s",
                        "invocation_id": "test-1",
                    }
                )
                + "\n"
            )
            handle.flush()
            converted = self.run_openmako("--no-trust-prompt", "evidence-court", "record", "from-jsonl", handle.name)

        self.assertEqual(converted.returncode, 0, converted.stderr)
        record = json.loads(converted.stdout)
        self.assertEqual(
            record["ledger_identity"],
            {
                "run_id": "run-44",
                "session_id": "session-a",
                "task_id": "task-17",
                "tool_invocation_ids": ["patch-1", "test-1"],
                "missing_identity": ["external_run_id"],
            },
        )

    def test_openmako_evidence_court_record_from_jsonl_rejects_malformed_command_output(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8") as handle:
            handle.write('{"kind":"task","claimed_task":"Fix calculator.py."}\n')
            handle.write(
                json.dumps(
                    {
                        "kind": "command",
                        "command": "python3 -m pytest tests/test_calculator.py -q",
                        "exit_code": 0,
                        "output": ["1 passed in 0.02s"],
                    }
                )
                + "\n"
            )
            handle.flush()
            converted = self.run_openmako("--no-trust-prompt", "evidence-court", "record", "from-jsonl", handle.name)

        self.assertEqual(converted.returncode, 2)
        self.assertEqual(converted.stdout, "")
        self.assertIn("command output output must be a string", converted.stderr)

    def test_openmako_evidence_court_record_from_jsonl_rejects_malformed_command_text(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8") as handle:
            handle.write('{"kind":"task","claimed_task":"Fix calculator.py."}\n')
            handle.write(json.dumps({"kind": "command", "command": ["pytest"], "exit_code": 0}) + "\n")
            handle.flush()
            converted = self.run_openmako("--no-trust-prompt", "evidence-court", "record", "from-jsonl", handle.name)

        self.assertEqual(converted.returncode, 2)
        self.assertEqual(converted.stdout, "")
        self.assertIn("command command must be a string", converted.stderr)

    def test_openmako_evidence_court_record_from_jsonl_rejects_malformed_direct_ledger_identity_list(
        self,
    ) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "kind": "task",
                        "claimed_task": "Fix calculator.py.",
                        "tool_invocation_ids": [{"id": "patch-1"}],
                    }
                )
                + "\n"
            )
            handle.flush()
            converted = self.run_openmako("--no-trust-prompt", "evidence-court", "record", "from-jsonl", handle.name)

        self.assertEqual(converted.returncode, 2)
        self.assertEqual(converted.stdout, "")
        self.assertIn("tool_invocation_ids must be an array of strings", converted.stderr)

    def test_openmako_evidence_court_record_from_jsonl_rejects_malformed_event_kind_text(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8") as handle:
            handle.write(json.dumps({"kind": {"event": "task"}, "claimed_task": "Fix calculator.py."}) + "\n")
            handle.flush()
            converted = self.run_openmako("--no-trust-prompt", "evidence-court", "record", "from-jsonl", handle.name)

        self.assertEqual(converted.returncode, 2)
        self.assertEqual(converted.stdout, "")
        self.assertIn("JSONL event at line 1.kind must be a string", converted.stderr)

    def test_openmako_evidence_court_record_from_jsonl_rejects_malformed_task_text(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8") as handle:
            handle.write(json.dumps({"kind": "task", "claimed_task": {"message": "Fix calculator.py."}}) + "\n")
            handle.flush()
            converted = self.run_openmako("--no-trust-prompt", "evidence-court", "record", "from-jsonl", handle.name)

        self.assertEqual(converted.returncode, 2)
        self.assertEqual(converted.stdout, "")
        self.assertIn("claimed_task claimed_task must be a string", converted.stderr)

    def test_openmako_evidence_court_record_from_jsonl_rejects_malformed_final_claim_text(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8") as handle:
            handle.write('{"kind":"task","claimed_task":"Fix calculator.py."}\n')
            handle.write(json.dumps({"kind": "final_claim", "text": {"message": "Fixed and verified."}}) + "\n")
            handle.flush()
            converted = self.run_openmako("--no-trust-prompt", "evidence-court", "record", "from-jsonl", handle.name)

        self.assertEqual(converted.returncode, 2)
        self.assertEqual(converted.stdout, "")
        self.assertIn("final_claim text must be a string", converted.stderr)

    def test_openmako_evidence_court_record_from_jsonl_rejects_mixed_final_claims(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8") as handle:
            handle.write('{"kind":"task","claimed_task":"Fix calculator.py."}\n')
            handle.write('{"kind":"final_claim","text":"Fixed and verified."}\n')
            handle.write('{"kind":"final_claim","text":"Skipped tests but looks done."}\n')
            handle.flush()
            converted = self.run_openmako("--no-trust-prompt", "evidence-court", "record", "from-jsonl", handle.name)

        self.assertEqual(converted.returncode, 2)
        self.assertEqual(converted.stdout, "")
        self.assertIn("final_claim values must not be mixed", converted.stderr)

    def test_openmako_evidence_court_record_from_jsonl_preserves_command_metrics(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8") as handle:
            handle.write('{"kind":"task","claimed_task":"Fix calculator.py.","allowed_files":["calculator.py"]}\n')
            handle.write('{"kind":"read","file":"calculator.py"}\n')
            handle.write('{"kind":"edit","file":"calculator.py"}\n')
            handle.write(
                '{"kind":"command","command":"python3 -m pytest tests/test_calculator.py -q",'
                '"exit_code":0,"output":"1 passed in 0.02s","duration_seconds":1.4,'
                '"input_tokens":1200,"output_tokens":320,"estimated_cost_usd":0.004,'
                '"missing_telemetry":["actual_cost_usd"]}\n'
            )
            handle.write('{"kind":"final_claim","text":"Fixed and verified."}\n')
            handle.flush()
            converted = self.run_openmako("--no-trust-prompt", "evidence-court", "record", "from-jsonl", handle.name)

        self.assertEqual(converted.returncode, 0, converted.stderr)
        record = json.loads(converted.stdout)
        self.assertEqual(
            record["run_metrics"],
            {
                "command_count": 1,
                "duration_seconds": 1.4,
                "estimated_cost_usd": 0.004,
                "input_tokens": 1200,
                "missing_telemetry": ["actual_cost_usd"],
                "output_tokens": 320,
            },
        )

    def test_openmako_evidence_court_record_from_jsonl_rejects_mixed_run_metric_provider_values(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8") as handle:
            handle.write('{"kind":"task","claimed_task":"Fix calculator.py."}\n')
            handle.write(
                '{"kind":"command","command":"python3 scripts/setup_fixture.py",'
                '"exit_code":0,"provider":"openai","model":"gpt-5"}\n'
            )
            handle.write(
                '{"kind":"command","command":"python3 -m pytest tests/test_calculator.py -q",'
                '"exit_code":0,"run_metrics":{"provider":"anthropic","model":"gpt-5"}}\n'
            )
            handle.flush()
            converted = self.run_openmako("--no-trust-prompt", "evidence-court", "record", "from-jsonl", handle.name)

        self.assertEqual(converted.returncode, 2)
        self.assertEqual(converted.stdout, "")
        self.assertIn("run_metrics.provider values must not be mixed", converted.stderr)

    def test_openmako_evidence_court_record_from_jsonl_rejects_mixed_run_metric_model_values(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8") as handle:
            handle.write('{"kind":"task","claimed_task":"Fix calculator.py."}\n')
            handle.write(
                '{"kind":"command","command":"python3 scripts/setup_fixture.py",'
                '"exit_code":0,"provider":"openai","model":"gpt-5"}\n'
            )
            handle.write(
                '{"kind":"command","command":"python3 -m pytest tests/test_calculator.py -q",'
                '"exit_code":0,"run_metrics":{"provider":"openai","model":"gpt-5-mini"}}\n'
            )
            handle.flush()
            converted = self.run_openmako("--no-trust-prompt", "evidence-court", "record", "from-jsonl", handle.name)

        self.assertEqual(converted.returncode, 2)
        self.assertEqual(converted.stdout, "")
        self.assertIn("run_metrics.model values must not be mixed", converted.stderr)

    def test_openmako_evidence_court_record_from_jsonl_preserves_artifact_provenance(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8") as handle:
            handle.write('{"kind":"task","claimed_task":"Compare benchmark artifacts."}\n')
            handle.write(
                '{"kind":"command","command":"python3 scripts/compare_outputs.py",'
                '"exit_code":0,"artifact_provenance":{"eval_rule_version":"swtbench-strip-model-patch/v2",'
                '"input_hashes":{"output.jsonl":"sha256:111"},"missing_provenance":["runner_commit"]}}\n'
            )
            handle.write(
                '{"kind":"command","command":"python3 scripts/hash_output.py","exit_code":0,'
                '"runner_commit":"def5678","output_hashes":{"output.swtbench.jsonl":"sha256:222"},'
                '"missing_provenance":["container_digest"]}\n'
            )
            handle.flush()
            converted = self.run_openmako("--no-trust-prompt", "evidence-court", "record", "from-jsonl", handle.name)

        self.assertEqual(converted.returncode, 0, converted.stderr)
        record = json.loads(converted.stdout)
        self.assertEqual(
            record["artifact_provenance"],
            {
                "eval_rule_version": "swtbench-strip-model-patch/v2",
                "input_hashes": {"output.jsonl": "sha256:111"},
                "missing_provenance": ["runner_commit", "container_digest"],
                "runner_commit": "def5678",
                "output_hashes": {"output.swtbench.jsonl": "sha256:222"},
            },
        )

    def test_openmako_evidence_court_record_from_jsonl_rejects_mixed_artifact_hash_values(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8") as handle:
            handle.write('{"kind":"task","claimed_task":"Compare benchmark artifacts."}\n')
            handle.write(
                '{"kind":"command","command":"python3 scripts/hash_input.py","exit_code":0,'
                '"input_hashes":{"output.jsonl":"sha256:111"}}\n'
            )
            handle.write(
                '{"kind":"command","command":"python3 scripts/hash_input_again.py","exit_code":0,'
                '"artifact_provenance":{"input_hashes":{"output.jsonl":"sha256:222"}}}\n'
            )
            handle.flush()
            converted = self.run_openmako("--no-trust-prompt", "evidence-court", "record", "from-jsonl", handle.name)

        self.assertEqual(converted.returncode, 2)
        self.assertEqual(converted.stdout, "")
        self.assertIn("artifact_provenance.input_hashes.output.jsonl values must not be mixed", converted.stderr)

    def test_openmako_evidence_court_record_from_jsonl_rejects_mixed_artifact_scalar_values(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8") as handle:
            handle.write('{"kind":"task","claimed_task":"Compare benchmark artifacts."}\n')
            handle.write(
                '{"kind":"command","command":"python3 scripts/compare_outputs.py","exit_code":0,'
                '"eval_rule_version":"swtbench-strip-model-patch/v1"}\n'
            )
            handle.write(
                '{"kind":"command","command":"python3 scripts/compare_outputs_again.py","exit_code":0,'
                '"artifact_provenance":{"eval_rule_version":"swtbench-strip-model-patch/v2"}}\n'
            )
            handle.flush()
            converted = self.run_openmako("--no-trust-prompt", "evidence-court", "record", "from-jsonl", handle.name)

        self.assertEqual(converted.returncode, 2)
        self.assertEqual(converted.stdout, "")
        self.assertIn("artifact_provenance.eval_rule_version values must not be mixed", converted.stderr)

    def test_openmako_evidence_court_record_from_swtbench_artifacts_is_auditable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_jsonl = tmp_path / "output.jsonl"
            swtbench_jsonl = tmp_path / "output.swtbench.jsonl"
            output_jsonl.write_text('{"instance_id":"a","patch":"test+source"}\n', encoding="utf-8")
            swtbench_jsonl.write_text('{"instance_id":"a","patch":"source-stripped"}\n', encoding="utf-8")

            converted = self.run_openmako(
                "--no-trust-prompt",
                "evidence-court",
                "record",
                "from-swtbench-artifacts",
                "--eval-rule-version",
                "swtbench-strip-model-patch/v2",
                "--runner-commit",
                "abc1234",
                "--test-file",
                "tests/test_calculator.py",
                "--source-file",
                "src/calculator.py",
                str(output_jsonl),
                str(swtbench_jsonl),
            )

            self.assertEqual(converted.returncode, 0, converted.stderr)
            record = json.loads(converted.stdout)
            self.assertEqual(record["source_agent"], "swtbench-artifacts")
            self.assertEqual(record["source_format"], "swtbench-artifacts/v0.1")
            self.assertEqual(record["files_read"], ["output.jsonl"])
            self.assertEqual(
                record["files_edited"],
                ["tests/test_calculator.py", "src/calculator.py", "output.swtbench.jsonl"],
            )
            provenance = record["artifact_provenance"]
            self.assertEqual(provenance["eval_rule_version"], "swtbench-strip-model-patch/v2")
            self.assertEqual(provenance["runner_commit"], "abc1234")
            self.assertEqual(
                provenance["input_hashes"]["output.jsonl"],
                "sha256:" + hashlib.sha256(output_jsonl.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                provenance["output_hashes"]["output.swtbench.jsonl"],
                "sha256:" + hashlib.sha256(swtbench_jsonl.read_bytes()).hexdigest(),
            )
            self.assertEqual(provenance["missing_provenance"], ["eval_rule_commit", "runner_version"])
            self.assertEqual(provenance["benchmark_score_validated"], False)
            self.assertEqual(provenance["runner_verified"], False)

            record_path = tmp_path / "record.json"
            record_path.write_text(converted.stdout, encoding="utf-8")
            audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", str(record_path))

        self.assertEqual(audited.returncode, 0, audited.stderr)
        payload = json.loads(audited.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["patch_shape"]["bucket"], "mixed_test_source")
        self.assertEqual(payload["artifact_provenance"]["runner_commit"], "abc1234")
        self.assertEqual(payload["artifact_provenance"]["benchmark_score_validated"], False)
        self.assertEqual(payload["artifact_provenance"]["runner_verified"], False)

    def test_openmako_evidence_court_record_from_swtbench_artifacts_requires_existing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            existing = tmp_path / "output.jsonl"
            missing = tmp_path / "missing.swtbench.jsonl"
            existing.write_text('{"instance_id":"a"}\n', encoding="utf-8")

            missing_input = self.run_openmako(
                "--no-trust-prompt",
                "evidence-court",
                "record",
                "from-swtbench-artifacts",
                str(tmp_path / "missing.jsonl"),
                str(existing),
            )
            missing_output = self.run_openmako(
                "--no-trust-prompt",
                "evidence-court",
                "record",
                "from-swtbench-artifacts",
                str(existing),
                str(missing),
            )

        self.assertEqual(missing_input.returncode, 2)
        self.assertIn("SWTBench input artifact not found", missing_input.stderr)
        self.assertEqual(missing_input.stdout, "")
        self.assertEqual(missing_output.returncode, 2)
        self.assertIn("SWTBench output artifact not found", missing_output.stderr)
        self.assertEqual(missing_output.stdout, "")

    def test_openmako_evidence_court_record_from_jsonl_output_file_is_auditable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "run.json"
            converted = self.run_openmako(
                "--no-trust-prompt",
                "evidence-court",
                "record",
                "from-jsonl",
                "--output",
                str(output),
                "examples/evidence_court/simple_events.jsonl",
            )

            self.assertEqual(converted.returncode, 0, converted.stderr)
            self.assertEqual(converted.stdout, "")
            self.assertTrue(output.exists())
            audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--ci", "--json", str(output))

        self.assertEqual(audited.returncode, 1)
        payload = json.loads(audited.stdout)
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertEqual(payload["failure_class"], "scope_violation")

    def test_openmako_evidence_court_record_from_codex_transcript_builds_auditable_record(self) -> None:
        transcript = {
            "claimed_task": "Fix calculator.py only. Do not edit tests.",
            "allowed_files": ["calculator.py"],
            "messages": [
                {
                    "role": "assistant",
                    "content": "Fixed and verified.",
                    "tool_calls": [
                        {"type": "read_file", "path": "calculator.py"},
                        {"type": "apply_patch", "files": ["calculator.py", "tests/test_calculator.py"]},
                        {
                            "type": "exec_command",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 0,
                            "output": "1 passed in 0.02s",
                            "duration_seconds": 1.5,
                            "tokens": {"input_tokens": 240, "output_tokens": 60},
                            "provider": "openai",
                            "model": "gpt-5",
                        },
                        {"type": "browser_snapshot", "url": "http://example.invalid"},
                    ],
                }
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(transcript, handle)
            handle.flush()
            converted = self.run_openmako(
                "--no-trust-prompt",
                "evidence-court",
                "record",
                "from-codex-transcript",
                handle.name,
            )

        self.assertEqual(converted.returncode, 0, converted.stderr)
        record = json.loads(converted.stdout)
        self.assertEqual(record["source_agent"], "codex")
        self.assertEqual(record["source_format"], "codex-transcript/v0.1")
        self.assertEqual(record["files_read"], ["calculator.py"])
        self.assertEqual(record["files_edited"], ["calculator.py", "tests/test_calculator.py"])
        self.assertEqual(record["commands_run"][0]["exit_code"], 0)
        self.assertEqual(record["test_output"], "1 passed in 0.02s")
        self.assertEqual(record["run_metrics"]["command_count"], 1)
        self.assertEqual(record["run_metrics"]["input_tokens"], 240)
        self.assertIn("messages[0].tool_calls[3]: browser_snapshot", record["adapter_report"]["unsupported"])

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(audited.returncode, 0, audited.stderr)
        payload = json.loads(audited.stdout)
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertEqual(payload["failure_class"], "scope_violation")

    def test_openmako_evidence_court_codex_transcript_aggregates_multi_command_metrics(self) -> None:
        transcript = {
            "claimed_task": "Fix calculator.py.",
            "allowed_files": ["calculator.py"],
            "messages": [
                {
                    "role": "assistant",
                    "content": "Fixed and verified.",
                    "tool_calls": [
                        {"type": "read_file", "path": "calculator.py"},
                        {
                            "type": "apply_patch",
                            "files": ["calculator.py"],
                            "diff_hunks": [
                                "--- a/calculator.py\n"
                                "+++ b/calculator.py\n"
                                "@@ -1,2 +1,2 @@\n"
                                "-def add(a, b): return a - b\n"
                                "+def add(a, b): return a + b"
                            ],
                        },
                        {
                            "type": "exec_command",
                            "command": "python3 scripts/setup_fixture.py",
                            "exit_code": 0,
                            "output": "setup ok",
                            "duration_seconds": 0.5,
                            "tokens": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
                            "estimated_cost_usd": 0.001,
                            "missing_telemetry": ["actual_cost_usd"],
                        },
                        {
                            "type": "exec_command",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 0,
                            "output": "1 passed in 0.02s",
                            "duration_seconds": 1.5,
                            "tokens": {"input_tokens": 200, "output_tokens": 40, "total_tokens": 240},
                            "estimated_cost_usd": 0.003,
                            "missing_telemetry": ["actual_cost_usd", "model"],
                        },
                    ],
                }
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(transcript, handle)
            handle.flush()
            converted = self.run_openmako(
                "--no-trust-prompt",
                "evidence-court",
                "record",
                "from-codex-transcript",
                handle.name,
            )

        self.assertEqual(converted.returncode, 0, converted.stderr)
        record = json.loads(converted.stdout)
        self.assertEqual(record["run_metrics"]["command_count"], 2)
        self.assertEqual(record["run_metrics"]["duration_seconds"], 2.0)
        self.assertEqual(record["run_metrics"]["input_tokens"], 300)
        self.assertEqual(record["run_metrics"]["output_tokens"], 60)
        self.assertEqual(record["run_metrics"]["total_tokens"], 360)
        self.assertEqual(record["run_metrics"]["estimated_cost_usd"], 0.004)
        self.assertEqual(record["run_metrics"]["missing_telemetry"], ["actual_cost_usd", "model"])

    def test_openmako_evidence_court_codex_transcript_preserves_ledger_identity(self) -> None:
        transcript = {
            "claimed_task": "Fix calculator.py.",
            "allowed_files": ["calculator.py"],
            "session_id": "session-a",
            "task_id": "task-17",
            "parent_id": "parent-run",
            "messages": [
                {
                    "role": "assistant",
                    "content": "Fixed and verified.",
                    "tool_calls": [
                        {
                            "type": "read_file",
                            "path": "calculator.py",
                            "session_id": "session-a",
                            "tool_invocation_id": "read-1",
                        },
                        {
                            "type": "apply_patch",
                            "files": ["calculator.py"],
                            "session_id": "session-a",
                            "tool_call_id": "patch-1",
                            "diff_hunks": [
                                "--- a/calculator.py\n"
                                "+++ b/calculator.py\n"
                                "@@ -1,2 +1,2 @@\n"
                                "-def add(a, b): return a - b\n"
                                "+def add(a, b): return a + b"
                            ],
                        },
                        {
                            "type": "exec_command",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 0,
                            "output": "1 passed in 0.02s",
                            "session_id": "session-a",
                            "invocation_id": "test-1",
                        },
                    ],
                }
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(transcript, handle)
            handle.flush()
            converted = self.run_openmako(
                "--no-trust-prompt",
                "evidence-court",
                "record",
                "from-codex-transcript",
                handle.name,
            )

        self.assertEqual(converted.returncode, 0, converted.stderr)
        record = json.loads(converted.stdout)
        self.assertEqual(
            record["ledger_identity"],
            {
                "session_id": "session-a",
                "task_id": "task-17",
                "parent_id": "parent-run",
                "tool_invocation_ids": ["read-1", "patch-1", "test-1"],
            },
        )

    def test_openmako_evidence_court_codex_transcript_preserves_nested_ledger_identity_extra_fields(self) -> None:
        transcript = {
            "claimed_task": "Fix calculator.py.",
            "allowed_files": ["calculator.py"],
            "ledger_identity": {
                "session_id": "session-a",
                "run_id": "run-44",
                "trace_id": "trace-abc",
            },
            "messages": [
                {
                    "role": "assistant",
                    "content": "Fixed and verified.",
                    "tool_calls": [
                        {
                            "type": "apply_patch",
                            "files": ["calculator.py"],
                            "session_id": "session-a",
                            "tool_invocation_id": "patch-1",
                            "diff": (
                                "--- a/calculator.py\n"
                                "+++ b/calculator.py\n"
                                "@@ -1,2 +1,2 @@\n"
                                "-def add(a, b): return a - b\n"
                                "+def add(a, b): return a + b"
                            ),
                        },
                        {
                            "type": "exec_command",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 0,
                            "output": "1 passed in 0.02s",
                        },
                    ],
                }
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(transcript, handle)
            handle.flush()
            converted = self.run_openmako(
                "--no-trust-prompt",
                "evidence-court",
                "record",
                "from-codex-transcript",
                handle.name,
            )

        self.assertEqual(converted.returncode, 0, converted.stderr)
        record = json.loads(converted.stdout)
        self.assertEqual(
            record["ledger_identity"],
            {
                "session_id": "session-a",
                "run_id": "run-44",
                "trace_id": "trace-abc",
                "tool_invocation_ids": ["patch-1"],
            },
        )

    def test_openmako_evidence_court_other_transcripts_aggregate_multi_command_metrics(self) -> None:
        source_hunk = (
            "--- a/calculator.py\n"
            "+++ b/calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def add(a, b): return a - b\n"
            "+def add(a, b): return a + b"
        )

        transcripts = {
            "claude": {
                "task": "Fix calculator.py.",
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Edit",
                                "input": {"file_path": "calculator.py", "diff": source_hunk},
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {
                                    "command": "python3 scripts/setup_fixture.py",
                                    "exit_code": 0,
                                    "stdout": "setup ok",
                                    "duration_seconds": 0.25,
                                    "tokens": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
                                    "estimated_cost_usd": 0.001,
                                    "missing_telemetry": ["actual_cost_usd"],
                                },
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {
                                    "command": "python3 -m pytest tests/test_calculator.py -q",
                                    "exit_code": 0,
                                    "stdout": "1 passed in 0.02s",
                                    "duration_seconds": 0.75,
                                    "tokens": {"input_tokens": 30, "output_tokens": 8, "total_tokens": 38},
                                    "estimated_cost_usd": 0.003,
                                    "missing_telemetry": ["actual_cost_usd", "model"],
                                },
                            },
                        ],
                    },
                    {"role": "assistant", "content": "Fixed and verified."},
                ],
            },
            "openhands": {
                "task": "Fix calculator.py.",
                "events": [
                    {"action": "edit", "path": "calculator.py", "diff": source_hunk},
                    {
                        "action": "run",
                        "command": "python3 scripts/setup_fixture.py",
                        "exit_code": 0,
                        "observation": "setup ok",
                        "duration_seconds": 0.25,
                        "tokens": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
                        "estimated_cost_usd": 0.001,
                        "missing_telemetry": ["actual_cost_usd"],
                    },
                    {
                        "action": "run",
                        "command": "python3 -m pytest tests/test_calculator.py -q",
                        "exit_code": 0,
                        "observation": "1 passed in 0.02s",
                        "duration_seconds": 0.75,
                        "tokens": {"input_tokens": 30, "output_tokens": 8, "total_tokens": 38},
                        "estimated_cost_usd": 0.003,
                        "missing_telemetry": ["actual_cost_usd", "model"],
                    },
                    {"action": "finish", "message": "Fixed and verified."},
                ],
            },
            "swe-agent": {
                "issue": "Fix calculator.py.",
                "steps": [
                    {"action": "edit", "path": "calculator.py", "patch": source_hunk},
                    {
                        "action": "run",
                        "command": "python3 scripts/setup_fixture.py",
                        "exit_code": 0,
                        "stdout": "setup ok",
                        "duration_seconds": 0.25,
                        "tokens": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
                        "estimated_cost_usd": 0.001,
                        "missing_telemetry": ["actual_cost_usd"],
                    },
                    {
                        "action": "test",
                        "command": "python3 -m pytest tests/test_calculator.py -q",
                        "exit_code": 0,
                        "stdout": "1 passed in 0.02s",
                        "duration_seconds": 0.75,
                        "tokens": {"input_tokens": 30, "output_tokens": 8, "total_tokens": 38},
                        "estimated_cost_usd": 0.003,
                        "missing_telemetry": ["actual_cost_usd", "model"],
                    },
                    {"action": "submit", "message": "Fixed and verified."},
                ],
            },
        }

        for adapter, transcript in transcripts.items():
            with self.subTest(adapter=adapter):
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 0, converted.stderr)
                record = json.loads(converted.stdout)
                self.assertEqual(record["run_metrics"]["command_count"], 2)
                self.assertEqual(record["run_metrics"]["duration_seconds"], 1.0)
                self.assertEqual(record["run_metrics"]["input_tokens"], 40)
                self.assertEqual(record["run_metrics"]["output_tokens"], 10)
                self.assertEqual(record["run_metrics"]["total_tokens"], 50)
                self.assertEqual(record["run_metrics"]["estimated_cost_usd"], 0.004)
                self.assertEqual(record["run_metrics"]["missing_telemetry"], ["actual_cost_usd", "model"])

    def test_openmako_evidence_court_transcript_adapters_deduplicate_file_evidence(self) -> None:
        source_hunk = (
            "--- a/calculator.py\n"
            "+++ b/calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def add(a, b): return a - b\n"
            "+def add(a, b): return a + b"
        )
        transcripts = {
            "codex": {
                "claimed_task": "Fix calculator.py.",
                "messages": [
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {"type": "read_file", "path": "calculator.py"},
                            {"type": "read_file", "path": "calculator.py"},
                            {"type": "apply_patch", "files": ["calculator.py"], "diff_hunks": [source_hunk]},
                            {"type": "apply_patch", "files": ["calculator.py"], "diff_hunks": [source_hunk]},
                            {
                                "type": "exec_command",
                                "command": "python3 -m pytest tests/test_calculator.py -q",
                                "exit_code": 0,
                                "output": "1 passed in 0.02s",
                            },
                        ],
                    },
                    {"role": "assistant", "content": "Fixed and verified."},
                ],
            },
            "claude": {
                "task": "Fix calculator.py.",
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "tool_use", "name": "Read", "input": {"file_path": "calculator.py"}},
                            {"type": "tool_use", "name": "Read", "input": {"file_path": "calculator.py"}},
                            {
                                "type": "tool_use",
                                "name": "Edit",
                                "input": {"file_path": "calculator.py", "diff": source_hunk},
                            },
                            {
                                "type": "tool_use",
                                "name": "Edit",
                                "input": {"file_path": "calculator.py", "diff": source_hunk},
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {
                                    "command": "python3 -m pytest tests/test_calculator.py -q",
                                    "exit_code": 0,
                                    "stdout": "1 passed in 0.02s",
                                },
                            },
                        ],
                    },
                    {"role": "assistant", "content": "Fixed and verified."},
                ],
            },
            "openhands": {
                "task": "Fix calculator.py.",
                "events": [
                    {"action": "read", "path": "calculator.py"},
                    {"action": "read", "path": "calculator.py"},
                    {"action": "edit", "path": "calculator.py", "diff": source_hunk},
                    {"action": "edit", "path": "calculator.py", "diff": source_hunk},
                    {
                        "action": "run",
                        "command": "python3 -m pytest tests/test_calculator.py -q",
                        "exit_code": 0,
                        "observation": "1 passed in 0.02s",
                    },
                    {"action": "finish", "message": "Fixed and verified."},
                ],
            },
            "swe-agent": {
                "issue": "Fix calculator.py.",
                "steps": [
                    {"action": "read", "path": "calculator.py"},
                    {"action": "read", "path": "calculator.py"},
                    {"action": "edit", "path": "calculator.py", "patch": source_hunk},
                    {"action": "edit", "path": "calculator.py", "patch": source_hunk},
                    {
                        "action": "test",
                        "command": "python3 -m pytest tests/test_calculator.py -q",
                        "exit_code": 0,
                        "stdout": "1 passed in 0.02s",
                    },
                    {"action": "submit", "message": "Fixed and verified."},
                ],
            },
        }

        for adapter, transcript in transcripts.items():
            with self.subTest(adapter=adapter):
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 0, converted.stderr)
                record = json.loads(converted.stdout)
                self.assertEqual(record["files_read"], ["calculator.py"])
                self.assertEqual(record["files_edited"], ["calculator.py"])
                self.assertEqual(record["diff_hunks"], [source_hunk])

    def test_openmako_evidence_court_record_from_codex_transcript_requires_diff_content_for_repair(self) -> None:
        transcript = {
            "claimed_task": "Fix calculator.py.",
            "allowed_files": ["calculator.py"],
            "messages": [
                {
                    "role": "assistant",
                    "content": "Fixed and verified.",
                    "tool_calls": [
                        {"type": "read_file", "path": "calculator.py"},
                        {"type": "apply_patch", "files": ["calculator.py"]},
                        {
                            "type": "exec_command",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 0,
                            "output": "1 passed in 0.02s",
                        },
                    ],
                }
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(transcript, handle)
            handle.flush()
            converted = self.run_openmako(
                "--no-trust-prompt",
                "evidence-court",
                "record",
                "from-codex-transcript",
                handle.name,
            )

        self.assertEqual(converted.returncode, 0, converted.stderr)
        record = json.loads(converted.stdout)
        self.assertNotIn("diff_hunks", record)

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(audited.returncode, 0, audited.stderr)
        payload = json.loads(audited.stdout)
        self.assertEqual(payload["verdict"], "SUSPICIOUS")
        self.assertEqual(payload["failure_class"], "missing_diff_content_evidence")

    def test_openmako_evidence_court_codex_transcript_mixed_source_test_diffs_are_not_tamper(self) -> None:
        transcript = {
            "claimed_task": "Fix calculator.py and update its focused test.",
            "allowed_files": ["calculator.py", "tests/test_calculator.py"],
            "messages": [
                {
                    "role": "assistant",
                    "content": "Fixed and verified.",
                    "tool_calls": [
                        {"type": "read_file", "path": "calculator.py"},
                        {
                            "type": "apply_patch",
                            "files": ["calculator.py", "tests/test_calculator.py"],
                            "diff_hunks": [
                                (
                                    "--- a/calculator.py\n"
                                    "+++ b/calculator.py\n"
                                    "@@ -1,2 +1,2 @@\n"
                                    "-def add(a, b): return a - b\n"
                                    "+def add(a, b): return a + b"
                                ),
                                (
                                    "--- a/tests/test_calculator.py\n"
                                    "+++ b/tests/test_calculator.py\n"
                                    "@@ -1,2 +1,2 @@\n"
                                    "-assert add(1, 2) == 0\n"
                                    "+assert add(1, 2) == 3"
                                ),
                            ],
                        },
                        {
                            "type": "exec_command",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 0,
                            "output": "1 passed in 0.02s",
                        },
                    ],
                }
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(transcript, handle)
            handle.flush()
            converted = self.run_openmako(
                "--no-trust-prompt",
                "evidence-court",
                "record",
                "from-codex-transcript",
                handle.name,
            )

        self.assertEqual(converted.returncode, 0, converted.stderr)
        record = json.loads(converted.stdout)
        self.assertEqual(len(record["diff_hunks"]), 2)
        self.assertIn("--- a/calculator.py", record["diff_hunks"][0])
        self.assertIn("--- a/tests/test_calculator.py", record["diff_hunks"][1])

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(audited.returncode, 0, audited.stderr)
        payload = json.loads(audited.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["patch_shape"]["bucket"], "mixed_test_source")
        self.assertEqual(payload["patch_shape"]["source_files"], ["calculator.py"])
        self.assertEqual(payload["patch_shape"]["test_files"], ["tests/test_calculator.py"])
        self.assertFalse(payload["verifier_tamper_risk"]["verifier_tamper_risk"])
        self.assertNotIn("verifier_tamper_risk", payload["finding_types"])

    def test_openmako_evidence_court_codex_transcript_deduplicates_repeated_diff_hunks(self) -> None:
        source_hunk = (
            "--- a/calculator.py\n"
            "+++ b/calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def add(a, b): return a - b\n"
            "+def add(a, b): return a + b"
        )
        test_hunk = (
            "--- a/tests/test_calculator.py\n"
            "+++ b/tests/test_calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-assert add(1, 2) == 0\n"
            "+assert add(1, 2) == 3"
        )
        transcript = {
            "claimed_task": "Fix calculator.py and update its focused test.",
            "allowed_files": ["calculator.py", "tests/test_calculator.py"],
            "messages": [
                {
                    "role": "assistant",
                    "content": "Fixed and verified.",
                    "tool_calls": [
                        {"type": "read_file", "path": "calculator.py"},
                        {
                            "type": "apply_patch",
                            "files": ["calculator.py", "tests/test_calculator.py"],
                            "diff_hunks": [source_hunk, test_hunk, source_hunk],
                            "diff": source_hunk,
                        },
                        {
                            "type": "exec_command",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 0,
                            "output": "1 passed in 0.02s",
                        },
                    ],
                }
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(transcript, handle)
            handle.flush()
            converted = self.run_openmako(
                "--no-trust-prompt",
                "evidence-court",
                "record",
                "from-codex-transcript",
                handle.name,
            )

        self.assertEqual(converted.returncode, 0, converted.stderr)
        record = json.loads(converted.stdout)
        self.assertEqual(record["diff_hunks"], [source_hunk, test_hunk])

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(audited.returncode, 0, audited.stderr)
        payload = json.loads(audited.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["patch_shape"]["bucket"], "mixed_test_source")
        self.assertFalse(payload["verifier_tamper_risk"]["verifier_tamper_risk"])

    def test_openmako_evidence_court_transcript_adapters_reject_malformed_diff_hunks(self) -> None:
        def transcript_for(adapter: str, bad_value: object) -> dict[str, object]:
            if adapter == "codex":
                return {
                    "claimed_task": "Fix calculator.py.",
                    "messages": [
                        {
                            "role": "assistant",
                            "content": "Fixed and verified.",
                            "tool_calls": [
                                {
                                    "type": "apply_patch",
                                    "files": ["calculator.py"],
                                    "diff_hunks": bad_value,
                                }
                            ],
                        }
                    ],
                }
            if adapter == "claude":
                return {
                    "task": "Fix calculator.py.",
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Edit",
                                    "input": {
                                        "file_path": "calculator.py",
                                        "diff_hunks": bad_value,
                                    },
                                }
                            ],
                        }
                    ],
                }
            if adapter == "openhands":
                return {
                    "task": "Fix calculator.py.",
                    "events": [
                        {
                            "action": "edit",
                            "path": "calculator.py",
                            "diff_hunks": bad_value,
                        }
                    ],
                }
            if adapter == "swe-agent":
                return {
                    "issue": "Fix calculator.py.",
                    "steps": [
                        {
                            "action": "edit",
                            "path": "calculator.py",
                            "diff_hunks": bad_value,
                        }
                    ],
                }
            raise AssertionError(f"unexpected adapter: {adapter}")

        cases: tuple[tuple[str, object, str], ...] = (
            ("not-array", "--- a/calculator.py", "diff_hunks must be an array"),
            ("non-string-entry", ["--- a/calculator.py", 42], "diff_hunks entries must be strings"),
        )
        for adapter in ("codex", "claude", "openhands", "swe-agent"):
            for case_name, bad_value, expected_error in cases:
                with self.subTest(adapter=adapter, case_name=case_name):
                    transcript = transcript_for(adapter, bad_value)
                    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                        json.dump(transcript, handle)
                        handle.flush()
                        converted = self.run_openmako(
                            "--no-trust-prompt",
                            "evidence-court",
                            "record",
                            f"from-{adapter}-transcript",
                            handle.name,
                        )

                    self.assertEqual(converted.returncode, 2)
                    self.assertEqual(converted.stdout, "")
                    self.assertIn(expected_error, converted.stderr)

    def test_openmako_evidence_court_transcript_adapters_reject_malformed_diff_text_fields(self) -> None:
        def transcript_for(adapter: str, field: str, bad_value: object) -> dict[str, object]:
            if adapter == "codex":
                return {
                    "claimed_task": "Fix calculator.py.",
                    "messages": [
                        {
                            "role": "assistant",
                            "content": "Fixed and verified.",
                            "tool_calls": [
                                {
                                    "type": "apply_patch",
                                    "files": ["calculator.py"],
                                    field: bad_value,
                                }
                            ],
                        }
                    ],
                }
            if adapter == "claude":
                return {
                    "task": "Fix calculator.py.",
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Edit",
                                    "input": {
                                        "file_path": "calculator.py",
                                        field: bad_value,
                                    },
                                }
                            ],
                        }
                    ],
                }
            if adapter == "openhands":
                return {
                    "task": "Fix calculator.py.",
                    "events": [
                        {
                            "action": "edit",
                            "path": "calculator.py",
                            field: bad_value,
                        }
                    ],
                }
            if adapter == "swe-agent":
                return {
                    "issue": "Fix calculator.py.",
                    "steps": [
                        {
                            "action": "edit",
                            "path": "calculator.py",
                            field: bad_value,
                        }
                    ],
                }
            raise AssertionError(f"unexpected adapter: {adapter}")

        cases: tuple[tuple[str, str], ...] = (
            ("codex", "diff"),
            ("claude", "patch"),
            ("openhands", "unified_diff"),
            ("swe-agent", "patch"),
        )
        for adapter, field in cases:
            with self.subTest(adapter=adapter, field=field):
                transcript = transcript_for(adapter, field, {"hunk": "--- a/calculator.py"})
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 2)
                self.assertEqual(converted.stdout, "")
                self.assertIn(f"{field} must be a string", converted.stderr)

    def test_openmako_evidence_court_transcript_adapters_reject_malformed_path_fields(self) -> None:
        def transcript_for(adapter: str, field: str, bad_value: object) -> dict[str, object]:
            if adapter == "codex":
                return {
                    "claimed_task": "Fix calculator.py.",
                    "messages": [
                        {
                            "role": "assistant",
                            "content": "Fixed and verified.",
                            "tool_calls": [
                                {
                                    "type": "apply_patch",
                                    field: bad_value,
                                }
                            ],
                        }
                    ],
                }
            if adapter == "claude":
                return {
                    "task": "Fix calculator.py.",
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Edit",
                                    "input": {
                                        field: bad_value,
                                    },
                                }
                            ],
                        }
                    ],
                }
            if adapter == "openhands":
                return {
                    "task": "Fix calculator.py.",
                    "events": [
                        {
                            "action": "edit",
                            field: bad_value,
                        }
                    ],
                }
            if adapter == "swe-agent":
                return {
                    "issue": "Fix calculator.py.",
                    "steps": [
                        {
                            "action": "edit",
                            field: bad_value,
                        }
                    ],
                }
            raise AssertionError(f"unexpected adapter: {adapter}")

        cases: tuple[tuple[str, str], ...] = (
            ("codex", "path"),
            ("claude", "file_path"),
            ("openhands", "path"),
            ("swe-agent", "path"),
        )
        for adapter, field in cases:
            with self.subTest(adapter=adapter, field=field):
                transcript = transcript_for(adapter, field, {"file": "calculator.py"})
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 2)
                self.assertEqual(converted.stdout, "")
                self.assertIn(f"{field} must be a string", converted.stderr)

    def test_openmako_evidence_court_transcript_adapters_ignore_empty_diff_strings(self) -> None:
        def transcript_for(adapter: str) -> dict[str, object]:
            if adapter == "codex":
                return {
                    "claimed_task": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "messages": [
                        {
                            "role": "assistant",
                            "content": "Fixed and verified.",
                            "tool_calls": [
                                {"type": "read_file", "path": "calculator.py"},
                                {
                                    "type": "apply_patch",
                                    "files": ["calculator.py"],
                                    "diff_hunks": ["  "],
                                    "diff": "\n\t",
                                },
                                {
                                    "type": "exec_command",
                                    "command": "python3 -m pytest tests/test_calculator.py -q",
                                    "exit_code": 0,
                                    "output": "1 passed in 0.02s",
                                },
                            ],
                        }
                    ],
                }
            if adapter == "claude":
                return {
                    "task": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": "I will patch and test calculator.py."},
                                {
                                    "type": "tool_use",
                                    "name": "Edit",
                                    "input": {
                                        "file_path": "calculator.py",
                                        "diff_hunks": ["  "],
                                        "patch": "\n\t",
                                    },
                                },
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {
                                        "command": "python3 -m pytest tests/test_calculator.py -q",
                                        "exit_code": 0,
                                        "stdout": "1 passed in 0.02s",
                                    },
                                },
                            ],
                        },
                        {"role": "assistant", "content": "Fixed and verified."},
                    ],
                }
            if adapter == "openhands":
                return {
                    "task": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "events": [
                        {"action": "read", "path": "calculator.py"},
                        {
                            "action": "edit",
                            "path": "calculator.py",
                            "diff_hunks": ["  "],
                            "unified_diff": "\n\t",
                        },
                        {
                            "action": "run",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 0,
                            "observation": "1 passed in 0.02s",
                        },
                        {"action": "finish", "message": "Fixed and verified."},
                    ],
                }
            if adapter == "swe-agent":
                return {
                    "issue": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "steps": [
                        {"action": "read", "path": "calculator.py"},
                        {
                            "action": "edit",
                            "path": "calculator.py",
                            "diff_hunks": ["  "],
                            "patch": "\n\t",
                        },
                        {
                            "action": "test",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 0,
                            "stdout": "1 passed in 0.02s",
                        },
                        {"action": "submit", "message": "Fixed and verified."},
                    ],
                }
            raise AssertionError(f"unexpected adapter: {adapter}")

        for adapter in ("codex", "claude", "openhands", "swe-agent"):
            with self.subTest(adapter=adapter):
                transcript = transcript_for(adapter)
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 0, converted.stderr)
                record = json.loads(converted.stdout)
                self.assertNotIn("diff_hunks", record)

                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(record, handle)
                    handle.flush()
                    audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

                self.assertEqual(audited.returncode, 0, audited.stderr)
                payload = json.loads(audited.stdout)
                self.assertEqual(payload["verdict"], "SUSPICIOUS")
                self.assertEqual(payload["failure_class"], "missing_diff_content_evidence")

    def test_openmako_evidence_court_transcript_adapters_fail_on_failed_test_commands(self) -> None:
        source_hunk = (
            "--- a/calculator.py\n"
            "+++ b/calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def add(a, b): return a - b\n"
            "+def add(a, b): return a + b"
        )

        def transcript_for(adapter: str) -> dict[str, object]:
            if adapter == "codex":
                return {
                    "claimed_task": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "messages": [
                        {
                            "role": "assistant",
                            "content": "Fixed and verified.",
                            "tool_calls": [
                                {"type": "read_file", "path": "calculator.py"},
                                {
                                    "type": "apply_patch",
                                    "files": ["calculator.py"],
                                    "diff_hunks": [source_hunk],
                                },
                                {
                                    "type": "exec_command",
                                    "command": "python3 -m pytest tests/test_calculator.py -q",
                                    "exit_code": 1,
                                    "output": "1 failed in 0.02s",
                                },
                            ],
                        }
                    ],
                }
            if adapter == "claude":
                return {
                    "task": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": "I will patch and test calculator.py."},
                                {
                                    "type": "tool_use",
                                    "name": "Edit",
                                    "input": {
                                        "file_path": "calculator.py",
                                        "diff_hunks": [source_hunk],
                                    },
                                },
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {
                                        "command": "python3 -m pytest tests/test_calculator.py -q",
                                        "exit_code": 1,
                                        "stdout": "1 failed in 0.02s",
                                    },
                                },
                            ],
                        },
                        {"role": "assistant", "content": "Fixed and verified."},
                    ],
                }
            if adapter == "openhands":
                return {
                    "task": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "events": [
                        {"action": "read", "path": "calculator.py"},
                        {
                            "action": "edit",
                            "path": "calculator.py",
                            "diff_hunks": [source_hunk],
                        },
                        {
                            "action": "run",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 1,
                            "observation": "1 failed in 0.02s",
                        },
                        {"action": "finish", "message": "Fixed and verified."},
                    ],
                }
            if adapter == "swe-agent":
                return {
                    "issue": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "steps": [
                        {"action": "read", "path": "calculator.py"},
                        {
                            "action": "edit",
                            "path": "calculator.py",
                            "diff_hunks": [source_hunk],
                        },
                        {
                            "action": "test",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 1,
                            "stdout": "1 failed in 0.02s",
                        },
                        {"action": "submit", "message": "Fixed and verified."},
                    ],
                }
            raise AssertionError(f"unexpected adapter: {adapter}")

        for adapter in ("codex", "claude", "openhands", "swe-agent"):
            with self.subTest(adapter=adapter):
                transcript = transcript_for(adapter)
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 0, converted.stderr)
                record = json.loads(converted.stdout)
                self.assertEqual(record["diff_hunks"], [source_hunk])
                self.assertEqual(record["commands_run"][0]["exit_code"], 1)

                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(record, handle)
                    handle.flush()
                    audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

                self.assertEqual(audited.returncode, 0, audited.stderr)
                payload = json.loads(audited.stdout)
                self.assertEqual(payload["verdict"], "FAIL")
                self.assertEqual(payload["failure_class"], "post_edit_validation_failure")
                self.assertEqual(payload["failed_at"], "test_output")

    def test_openmako_evidence_court_transcript_adapters_failed_exit_code_overrides_passing_text(self) -> None:
        source_hunk = (
            "--- a/calculator.py\n"
            "+++ b/calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def add(a, b): return a - b\n"
            "+def add(a, b): return a + b"
        )

        def transcript_for(adapter: str) -> dict[str, object]:
            if adapter == "codex":
                return {
                    "claimed_task": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "messages": [
                        {
                            "role": "assistant",
                            "content": "Fixed and verified.",
                            "tool_calls": [
                                {"type": "read_file", "path": "calculator.py"},
                                {
                                    "type": "apply_patch",
                                    "files": ["calculator.py"],
                                    "diff_hunks": [source_hunk],
                                },
                                {
                                    "type": "exec_command",
                                    "command": "python3 -m pytest tests/test_calculator.py -q",
                                    "exit_code": 1,
                                    "output": "1 passed in 0.02s",
                                },
                            ],
                        }
                    ],
                }
            if adapter == "claude":
                return {
                    "task": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Edit",
                                    "input": {
                                        "file_path": "calculator.py",
                                        "diff_hunks": [source_hunk],
                                    },
                                },
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {
                                        "command": "python3 -m pytest tests/test_calculator.py -q",
                                        "exit_code": 1,
                                        "stdout": "1 passed in 0.02s",
                                    },
                                },
                            ],
                        },
                        {"role": "assistant", "content": "Fixed and verified."},
                    ],
                }
            if adapter == "openhands":
                return {
                    "task": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "events": [
                        {"action": "read", "path": "calculator.py"},
                        {
                            "action": "edit",
                            "path": "calculator.py",
                            "diff_hunks": [source_hunk],
                        },
                        {
                            "action": "run",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 1,
                            "observation": "1 passed in 0.02s",
                        },
                        {"action": "finish", "message": "Fixed and verified."},
                    ],
                }
            if adapter == "swe-agent":
                return {
                    "issue": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "steps": [
                        {"action": "read", "path": "calculator.py"},
                        {
                            "action": "edit",
                            "path": "calculator.py",
                            "diff_hunks": [source_hunk],
                        },
                        {
                            "action": "test",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 1,
                            "stdout": "1 passed in 0.02s",
                        },
                        {"action": "submit", "message": "Fixed and verified."},
                    ],
                }
            raise AssertionError(f"unexpected adapter: {adapter}")

        for adapter in ("codex", "claude", "openhands", "swe-agent"):
            with self.subTest(adapter=adapter):
                transcript = transcript_for(adapter)
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 0, converted.stderr)
                record = json.loads(converted.stdout)
                self.assertEqual(record["diff_hunks"], [source_hunk])
                self.assertEqual(record["commands_run"][0]["exit_code"], 1)
                self.assertEqual(record["test_output"], "1 passed in 0.02s")

                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(record, handle)
                    handle.flush()
                    audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

                self.assertEqual(audited.returncode, 0, audited.stderr)
                payload = json.loads(audited.stdout)
                self.assertEqual(payload["verdict"], "FAIL")
                self.assertEqual(payload["failure_class"], "post_edit_validation_failure")
                self.assertEqual(payload["failed_at"], "test_output")

    def test_openmako_evidence_court_transcript_adapters_keep_validation_output_after_non_validation_command(
        self,
    ) -> None:
        source_hunk = (
            "--- a/calculator.py\n"
            "+++ b/calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def add(a, b): return a - b\n"
            "+def add(a, b): return a + b"
        )

        def transcript_for(adapter: str) -> dict[str, object]:
            if adapter == "codex":
                return {
                    "claimed_task": "Fix calculator.py.",
                    "messages": [
                        {
                            "role": "assistant",
                            "content": "Fixed and verified.",
                            "tool_calls": [
                                {"type": "apply_patch", "files": ["calculator.py"], "diff_hunks": [source_hunk]},
                                {
                                    "type": "exec_command",
                                    "command": "python3 -m pytest tests/test_calculator.py -q",
                                    "exit_code": 0,
                                    "output": "1 passed in 0.02s",
                                },
                                {
                                    "type": "exec_command",
                                    "command": "python3 scripts/format_report.py",
                                    "exit_code": 0,
                                    "output": "formatted report.md",
                                },
                            ],
                        }
                    ],
                }
            if adapter == "claude":
                return {
                    "task": "Fix calculator.py.",
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Edit",
                                    "input": {"file_path": "calculator.py", "diff_hunks": [source_hunk]},
                                },
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {
                                        "command": "python3 -m pytest tests/test_calculator.py -q",
                                        "exit_code": 0,
                                        "stdout": "1 passed in 0.02s",
                                    },
                                },
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {
                                        "command": "python3 scripts/format_report.py",
                                        "exit_code": 0,
                                        "stdout": "formatted report.md",
                                    },
                                },
                            ],
                        },
                        {"role": "assistant", "content": "Fixed and verified."},
                    ],
                }
            if adapter == "openhands":
                return {
                    "task": "Fix calculator.py.",
                    "events": [
                        {"action": "edit", "path": "calculator.py", "diff_hunks": [source_hunk]},
                        {
                            "action": "run",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 0,
                            "observation": "1 passed in 0.02s",
                        },
                        {
                            "action": "run",
                            "command": "python3 scripts/format_report.py",
                            "exit_code": 0,
                            "observation": "formatted report.md",
                        },
                        {"action": "finish", "message": "Fixed and verified."},
                    ],
                }
            if adapter == "swe-agent":
                return {
                    "issue": "Fix calculator.py.",
                    "steps": [
                        {"action": "edit", "path": "calculator.py", "diff_hunks": [source_hunk]},
                        {
                            "action": "test",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 0,
                            "stdout": "1 passed in 0.02s",
                        },
                        {
                            "action": "run",
                            "command": "python3 scripts/format_report.py",
                            "exit_code": 0,
                            "stdout": "formatted report.md",
                        },
                        {"action": "submit", "message": "Fixed and verified."},
                    ],
                }
            raise AssertionError(f"unexpected adapter: {adapter}")

        for adapter in ("codex", "claude", "openhands", "swe-agent"):
            with self.subTest(adapter=adapter):
                transcript = transcript_for(adapter)
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 0, converted.stderr)
                record = json.loads(converted.stdout)
                self.assertEqual(record["test_output"], "1 passed in 0.02s")

    def test_openmako_evidence_court_transcript_adapters_reject_malformed_command_exit_codes(self) -> None:
        def transcript_for(adapter: str, exit_code: object) -> dict[str, object]:
            if adapter == "codex":
                return {
                    "claimed_task": "Fix calculator.py.",
                    "messages": [
                        {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "type": "exec_command",
                                    "command": "python3 -m pytest tests/test_calculator.py -q",
                                    "exit_code": exit_code,
                                    "output": "1 passed in 0.02s",
                                }
                            ],
                        }
                    ],
                }
            if adapter == "claude":
                return {
                    "task": "Fix calculator.py.",
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {
                                        "command": "python3 -m pytest tests/test_calculator.py -q",
                                        "exit_code": exit_code,
                                        "stdout": "1 passed in 0.02s",
                                    },
                                }
                            ],
                        }
                    ],
                }
            if adapter == "openhands":
                return {
                    "task": "Fix calculator.py.",
                    "events": [
                        {
                            "action": "run",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": exit_code,
                            "observation": "1 passed in 0.02s",
                        }
                    ],
                }
            if adapter == "swe-agent":
                return {
                    "issue": "Fix calculator.py.",
                    "steps": [
                        {
                            "action": "test",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": exit_code,
                            "stdout": "1 passed in 0.02s",
                        }
                    ],
                }
            raise AssertionError(f"unexpected adapter: {adapter}")

        cases: tuple[tuple[str, object], ...] = (
            ("boolean", False),
            ("string", "0"),
        )
        for adapter in ("codex", "claude", "openhands", "swe-agent"):
            for case_name, exit_code in cases:
                with self.subTest(adapter=adapter, case_name=case_name):
                    transcript = transcript_for(adapter, exit_code)
                    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                        json.dump(transcript, handle)
                        handle.flush()
                        converted = self.run_openmako(
                            "--no-trust-prompt",
                            "evidence-court",
                            "record",
                            f"from-{adapter}-transcript",
                            handle.name,
                        )

                    self.assertEqual(converted.returncode, 2)
                    self.assertEqual(converted.stdout, "")
                    self.assertIn("exit_code must be an integer", converted.stderr)

    def test_openmako_evidence_court_transcript_adapters_reject_malformed_run_metrics(self) -> None:
        def transcript_for(adapter: str) -> dict[str, object]:
            if adapter == "codex":
                return {
                    "claimed_task": "Fix calculator.py.",
                    "messages": [
                        {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "type": "exec_command",
                                    "command": "python3 -m pytest tests/test_calculator.py -q",
                                    "exit_code": 0,
                                    "output": "1 passed in 0.02s",
                                    "duration_seconds": "fast",
                                }
                            ],
                        }
                    ],
                }
            if adapter == "claude":
                return {
                    "task": "Fix calculator.py.",
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {
                                        "command": "python3 -m pytest tests/test_calculator.py -q",
                                        "exit_code": 0,
                                        "stdout": "1 passed in 0.02s",
                                        "duration_seconds": "fast",
                                    },
                                }
                            ],
                        }
                    ],
                }
            if adapter == "openhands":
                return {
                    "task": "Fix calculator.py.",
                    "events": [
                        {
                            "action": "run",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 0,
                            "observation": "1 passed in 0.02s",
                            "duration_seconds": "fast",
                        }
                    ],
                }
            if adapter == "swe-agent":
                return {
                    "issue": "Fix calculator.py.",
                    "steps": [
                        {
                            "action": "test",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 0,
                            "stdout": "1 passed in 0.02s",
                            "duration_seconds": "fast",
                        }
                    ],
                }
            raise AssertionError(f"unexpected adapter: {adapter}")

        for adapter in ("codex", "claude", "openhands", "swe-agent"):
            with self.subTest(adapter=adapter):
                transcript = transcript_for(adapter)
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 2)
                self.assertEqual(converted.stdout, "")
                self.assertIn("run_metrics.duration_seconds must be a number", converted.stderr)

    def test_openmako_evidence_court_transcript_adapters_reject_malformed_command_output(self) -> None:
        def transcript_for(adapter: str) -> dict[str, object]:
            if adapter == "codex":
                return {
                    "claimed_task": "Fix calculator.py.",
                    "messages": [
                        {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "type": "exec_command",
                                    "command": "python3 -m pytest tests/test_calculator.py -q",
                                    "exit_code": 0,
                                    "output": ["1 passed in 0.02s"],
                                }
                            ],
                        }
                    ],
                }
            if adapter == "claude":
                return {
                    "task": "Fix calculator.py.",
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {
                                        "command": "python3 -m pytest tests/test_calculator.py -q",
                                        "exit_code": 0,
                                        "stdout": {"passed": 1},
                                    },
                                }
                            ],
                        }
                    ],
                }
            if adapter == "openhands":
                return {
                    "task": "Fix calculator.py.",
                    "events": [
                        {
                            "action": "run",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 0,
                            "observation": {"passed": 1},
                        }
                    ],
                }
            if adapter == "swe-agent":
                return {
                    "issue": "Fix calculator.py.",
                    "steps": [
                        {
                            "action": "test",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 0,
                            "stderr": ["1 passed in 0.02s"],
                        }
                    ],
                }
            raise AssertionError(f"unexpected adapter: {adapter}")

        for adapter in ("codex", "claude", "openhands", "swe-agent"):
            with self.subTest(adapter=adapter):
                transcript = transcript_for(adapter)
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 2)
                self.assertEqual(converted.stdout, "")
                self.assertIn("command output", converted.stderr)
                self.assertIn("must be a string", converted.stderr)

    def test_openmako_evidence_court_transcript_adapters_reject_malformed_command_text(self) -> None:
        def transcript_for(adapter: str) -> dict[str, object]:
            if adapter == "codex":
                return {
                    "claimed_task": "Fix calculator.py.",
                    "messages": [
                        {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "type": "exec_command",
                                    "command": ["python3", "-m", "pytest"],
                                    "exit_code": 0,
                                    "output": "1 passed in 0.02s",
                                }
                            ],
                        }
                    ],
                }
            if adapter == "claude":
                return {
                    "task": "Fix calculator.py.",
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {
                                        "command": {"argv": ["pytest"]},
                                        "exit_code": 0,
                                        "stdout": "1 passed in 0.02s",
                                    },
                                }
                            ],
                        }
                    ],
                }
            if adapter == "openhands":
                return {
                    "task": "Fix calculator.py.",
                    "events": [
                        {
                            "action": "run",
                            "command": ["pytest"],
                            "exit_code": 0,
                            "observation": "1 passed in 0.02s",
                        }
                    ],
                }
            if adapter == "swe-agent":
                return {
                    "issue": "Fix calculator.py.",
                    "steps": [
                        {
                            "action": "test",
                            "command": {"argv": ["pytest"]},
                            "exit_code": 0,
                            "stdout": "1 passed in 0.02s",
                        }
                    ],
                }
            raise AssertionError(f"unexpected adapter: {adapter}")

        for adapter in ("codex", "claude", "openhands", "swe-agent"):
            with self.subTest(adapter=adapter):
                transcript = transcript_for(adapter)
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 2)
                self.assertEqual(converted.stdout, "")
                self.assertIn("command command must be a string", converted.stderr)

    def test_openmako_evidence_court_transcript_adapters_reject_malformed_top_level_claim_text(self) -> None:
        def transcript_for(adapter: str, field: str, bad_value: object) -> dict[str, object]:
            if adapter == "codex":
                transcript: dict[str, object] = {"messages": []}
            elif adapter == "claude":
                transcript = {"messages": []}
            elif adapter == "openhands":
                transcript = {"events": []}
            elif adapter == "swe-agent":
                transcript = {"steps": []}
            else:
                raise AssertionError(f"unexpected adapter: {adapter}")
            transcript[field] = bad_value
            return transcript

        cases: tuple[tuple[str, str, object, str], ...] = (
            ("codex", "claimed_task", {"message": "Fix calculator.py."}, "claimed_task claimed_task must be a string"),
            ("codex", "final_claim", ["Fixed and verified."], "final_claim final_claim must be a string"),
            ("claude", "task", {"message": "Fix calculator.py."}, "claimed_task task must be a string"),
            ("claude", "final_claim", ["Fixed and verified."], "final_claim final_claim must be a string"),
            ("openhands", "task", {"message": "Fix calculator.py."}, "claimed_task task must be a string"),
            ("openhands", "final_claim", ["Fixed and verified."], "final_claim final_claim must be a string"),
            ("swe-agent", "issue", {"message": "Fix calculator.py."}, "claimed_task issue must be a string"),
            ("swe-agent", "final_claim", ["Fixed and verified."], "final_claim final_claim must be a string"),
        )
        for adapter, field, bad_value, expected_error in cases:
            with self.subTest(adapter=adapter, field=field):
                transcript = transcript_for(adapter, field, bad_value)
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 2)
                self.assertEqual(converted.stdout, "")
                self.assertIn(expected_error, converted.stderr)

    def test_openmako_evidence_court_transcript_adapters_reject_malformed_event_claim_text(self) -> None:
        cases: tuple[tuple[str, dict[str, object], str], ...] = (
            (
                "openhands",
                {"events": [{"action": "task", "message": {"text": "Fix calculator.py."}}]},
                "claimed_task message must be a string",
            ),
            (
                "openhands",
                {"events": [{"action": "finish", "message": {"text": "Fixed and verified."}}]},
                "final_claim message must be a string",
            ),
            (
                "swe-agent",
                {"steps": [{"action": "issue", "message": {"text": "Fix calculator.py."}}]},
                "claimed_task message must be a string",
            ),
            (
                "swe-agent",
                {"steps": [{"action": "submit", "message": {"text": "Fixed and verified."}}]},
                "final_claim message must be a string",
            ),
        )
        for adapter, transcript, expected_error in cases:
            with self.subTest(adapter=adapter, expected_error=expected_error):
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 2)
                self.assertEqual(converted.stdout, "")
                self.assertIn(expected_error, converted.stderr)

    def test_openmako_evidence_court_transcript_adapters_reject_malformed_event_allowed_files(self) -> None:
        cases: tuple[tuple[str, dict[str, object], str], ...] = (
            (
                "openhands",
                {"events": [{"action": "task", "allowed_files": "calculator.py"}]},
                "events[0].allowed_files must be an array",
            ),
            (
                "swe-agent",
                {"steps": [{"action": "issue", "allowed_files": "calculator.py"}]},
                "steps[0].allowed_files must be an array",
            ),
        )
        for adapter, transcript, expected_error in cases:
            with self.subTest(adapter=adapter, expected_error=expected_error):
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 2)
                self.assertEqual(converted.stdout, "")
                self.assertIn(expected_error, converted.stderr)

    def test_openmako_evidence_court_transcript_adapters_reject_malformed_message_content_text(self) -> None:
        cases: tuple[tuple[str, dict[str, object], str], ...] = (
            (
                "codex",
                {"messages": [{"role": "user", "content": [{"type": "text", "text": {"value": "Fix it."}}]}]},
                "messages[0].content[0].text must be a string",
            ),
            (
                "codex",
                {"messages": [{"role": "assistant", "content": [{"type": "text", "text": ["Fixed."]}]}]},
                "messages[0].content[0].text must be a string",
            ),
            (
                "claude",
                {"messages": [{"role": "user", "content": [{"type": "text", "text": {"value": "Fix it."}}]}]},
                "messages[0].content[0].text must be a string",
            ),
            (
                "claude",
                {"messages": [{"role": "assistant", "content": [{"type": "text", "text": ["Fixed."]}]}]},
                "messages[0].content[0].text must be a string",
            ),
        )
        for adapter, transcript, expected_error in cases:
            with self.subTest(adapter=adapter, expected_error=expected_error):
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 2)
                self.assertEqual(converted.stdout, "")
                self.assertIn(expected_error, converted.stderr)

    def test_openmako_evidence_court_transcript_adapters_reject_malformed_message_role_text(self) -> None:
        cases: tuple[tuple[str, dict[str, object], str], ...] = (
            (
                "codex",
                {"messages": [{"role": {"name": "user"}, "content": "Fix calculator.py."}]},
                "messages[0].role must be a string",
            ),
            (
                "claude",
                {"messages": [{"role": ["assistant"], "content": "Fixed and verified."}]},
                "messages[0].role must be a string",
            ),
        )
        for adapter, transcript, expected_error in cases:
            with self.subTest(adapter=adapter, expected_error=expected_error):
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 2)
                self.assertEqual(converted.stdout, "")
                self.assertIn(expected_error, converted.stderr)

    def test_openmako_evidence_court_transcript_adapters_reject_malformed_event_kind_text(self) -> None:
        cases: tuple[tuple[str, dict[str, object], str], ...] = (
            (
                "codex",
                {"messages": [{"role": "assistant", "tool_calls": [{"type": {"tool": "apply_patch"}}]}]},
                "messages[0].tool_calls[0].type must be a string",
            ),
            (
                "claude",
                {"messages": [{"role": "assistant", "content": [{"type": "tool_use", "name": {"tool": "Edit"}}]}]},
                "messages[0].content[0].name must be a string",
            ),
            (
                "claude",
                {"messages": [{"role": "assistant", "content": [{"type": {"kind": "tool_use"}, "name": "Edit"}]}]},
                "messages[0].content[0].type must be a string",
            ),
            (
                "openhands",
                {"events": [{"action": {"kind": "edit"}, "path": "calculator.py"}]},
                "events[0].action must be a string",
            ),
            (
                "swe-agent",
                {"steps": [{"action": {"kind": "edit"}, "path": "calculator.py"}]},
                "steps[0].action must be a string",
            ),
        )
        for adapter, transcript, expected_error in cases:
            with self.subTest(adapter=adapter, expected_error=expected_error):
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 2)
                self.assertEqual(converted.stdout, "")
                self.assertIn(expected_error, converted.stderr)

    def test_openmako_evidence_court_transcript_adapters_reject_malformed_tool_payload_containers(self) -> None:
        cases: tuple[tuple[str, dict[str, object], str], ...] = (
            (
                "codex",
                {"messages": [{"role": "assistant", "tool_calls": [{"type": "apply_patch", "arguments": ["bad"]}]}]},
                "messages[0].tool_calls[0].arguments must be an object or JSON object string",
            ),
            (
                "codex",
                {"messages": [{"role": "assistant", "tool_calls": [{"type": "apply_patch", "params": "[1]"}]}]},
                "messages[0].tool_calls[0].params must be an object or JSON object string",
            ),
            (
                "claude",
                {"messages": [{"role": "assistant", "content": [{"type": "tool_use", "name": "Edit", "input": ["bad"]}]}]},
                "messages[0].content[0].input must be an object or JSON object string",
            ),
            (
                "claude",
                {"messages": [{"role": "assistant", "content": [{"type": "tool_use", "name": "Edit", "input": "not json"}]}]},
                "messages[0].content[0].input must be an object or JSON object string",
            ),
        )
        for adapter, transcript, expected_error in cases:
            with self.subTest(adapter=adapter, expected_error=expected_error):
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 2)
                self.assertEqual(converted.stdout, "")
                self.assertIn(expected_error, converted.stderr)

    def test_openmako_evidence_court_transcript_adapters_reject_mixed_session_evidence(self) -> None:
        source_hunk = (
            "--- a/calculator.py\n"
            "+++ b/calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def add(a, b): return a - b\n"
            "+def add(a, b): return a + b"
        )

        def transcript_for(adapter: str) -> dict[str, object]:
            if adapter == "codex":
                return {
                    "claimed_task": "Fix calculator.py.",
                    "messages": [
                        {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "type": "apply_patch",
                                    "session_id": "session-a",
                                    "files": ["calculator.py"],
                                    "diff_hunks": [source_hunk],
                                },
                                {
                                    "type": "exec_command",
                                    "session_id": "session-b",
                                    "command": "python3 -m pytest tests/test_calculator.py -q",
                                    "exit_code": 0,
                                    "output": "1 passed in 0.02s",
                                },
                            ],
                        },
                        {"role": "assistant", "content": "Fixed and verified."},
                    ],
                }
            if adapter == "claude":
                return {
                    "task": "Fix calculator.py.",
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Edit",
                                    "input": {
                                        "session_id": "session-a",
                                        "file_path": "calculator.py",
                                        "diff_hunks": [source_hunk],
                                    },
                                },
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {
                                        "session_id": "session-b",
                                        "command": "python3 -m pytest tests/test_calculator.py -q",
                                        "exit_code": 0,
                                        "stdout": "1 passed in 0.02s",
                                    },
                                },
                            ],
                        },
                        {"role": "assistant", "content": "Fixed and verified."},
                    ],
                }
            if adapter == "openhands":
                return {
                    "task": "Fix calculator.py.",
                    "events": [
                        {
                            "action": "edit",
                            "session_id": "session-a",
                            "path": "calculator.py",
                            "diff_hunks": [source_hunk],
                        },
                        {
                            "action": "run",
                            "session_id": "session-b",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 0,
                            "observation": "1 passed in 0.02s",
                        },
                        {"action": "finish", "message": "Fixed and verified."},
                    ],
                }
            if adapter == "swe-agent":
                return {
                    "issue": "Fix calculator.py.",
                    "steps": [
                        {
                            "action": "edit",
                            "session_id": "session-a",
                            "path": "calculator.py",
                            "diff_hunks": [source_hunk],
                        },
                        {
                            "action": "test",
                            "session_id": "session-b",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 0,
                            "stdout": "1 passed in 0.02s",
                        },
                        {"action": "submit", "message": "Fixed and verified."},
                    ],
                }
            raise AssertionError(f"unexpected adapter: {adapter}")

        for adapter in ("codex", "claude", "openhands", "swe-agent"):
            with self.subTest(adapter=adapter):
                transcript = transcript_for(adapter)
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 2)
                self.assertEqual(converted.stdout, "")
                self.assertIn("session_id", converted.stderr)
                self.assertIn("must not be mixed", converted.stderr)

    def test_openmako_evidence_court_transcript_adapters_reject_mixed_extra_ledger_identity(self) -> None:
        source_hunk = (
            "--- a/calculator.py\n"
            "+++ b/calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def add(a, b): return a - b\n"
            "+def add(a, b): return a + b"
        )

        def transcript_for(adapter: str) -> dict[str, object]:
            if adapter == "codex":
                return {
                    "claimed_task": "Fix calculator.py.",
                    "ledger_identity": {"run_id": "run-a"},
                    "messages": [
                        {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "type": "apply_patch",
                                    "files": ["calculator.py"],
                                    "diff_hunks": [source_hunk],
                                    "ledger_identity": {"run_id": "run-b"},
                                }
                            ],
                        },
                    ],
                }
            if adapter == "claude":
                return {
                    "task": "Fix calculator.py.",
                    "ledger_identity": {"run_id": "run-a"},
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Edit",
                                    "input": {
                                        "file_path": "calculator.py",
                                        "diff_hunks": [source_hunk],
                                        "ledger_identity": {"run_id": "run-b"},
                                    },
                                }
                            ],
                        }
                    ],
                }
            if adapter == "openhands":
                return {
                    "task": "Fix calculator.py.",
                    "ledger_identity": {"run_id": "run-a"},
                    "events": [
                        {
                            "action": "edit",
                            "path": "calculator.py",
                            "diff_hunks": [source_hunk],
                            "ledger_identity": {"run_id": "run-b"},
                        }
                    ],
                }
            if adapter == "swe-agent":
                return {
                    "issue": "Fix calculator.py.",
                    "ledger_identity": {"run_id": "run-a"},
                    "steps": [
                        {
                            "action": "edit",
                            "path": "calculator.py",
                            "diff_hunks": [source_hunk],
                            "ledger_identity": {"run_id": "run-b"},
                        }
                    ],
                }
            raise AssertionError(f"unexpected adapter: {adapter}")

        for adapter in ("codex", "claude", "openhands", "swe-agent"):
            with self.subTest(adapter=adapter):
                transcript = transcript_for(adapter)
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 2)
                self.assertEqual(converted.stdout, "")
                self.assertIn("ledger_identity.run_id", converted.stderr)
                self.assertIn("must not be mixed", converted.stderr)

    def test_openmako_evidence_court_transcript_adapters_reject_malformed_extra_ledger_identity_fields(self) -> None:
        source_hunk = (
            "--- a/calculator.py\n"
            "+++ b/calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def add(a, b): return a - b\n"
            "+def add(a, b): return a + b"
        )

        def transcript_for(adapter: str) -> dict[str, object]:
            root = {
                "ledger_identity": {"run_id": {"id": "run-a"}},
            }
            if adapter == "codex":
                return {
                    "claimed_task": "Fix calculator.py.",
                    **root,
                    "messages": [
                        {
                            "role": "assistant",
                            "tool_calls": [
                                {"type": "apply_patch", "files": ["calculator.py"], "diff_hunks": [source_hunk]}
                            ],
                        },
                    ],
                }
            if adapter == "claude":
                return {
                    "task": "Fix calculator.py.",
                    **root,
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Edit",
                                    "input": {"file_path": "calculator.py", "diff_hunks": [source_hunk]},
                                }
                            ],
                        }
                    ],
                }
            if adapter == "openhands":
                return {
                    "task": "Fix calculator.py.",
                    **root,
                    "events": [{"action": "edit", "path": "calculator.py", "diff_hunks": [source_hunk]}],
                }
            if adapter == "swe-agent":
                return {
                    "issue": "Fix calculator.py.",
                    **root,
                    "steps": [{"action": "edit", "path": "calculator.py", "diff_hunks": [source_hunk]}],
                }
            raise AssertionError(f"unexpected adapter: {adapter}")

        for adapter in ("codex", "claude", "openhands", "swe-agent"):
            with self.subTest(adapter=adapter):
                transcript = transcript_for(adapter)
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 2)
                self.assertEqual(converted.stdout, "")
                self.assertIn("ledger_identity.run_id must be a string", converted.stderr)

    def test_openmako_evidence_court_transcript_adapters_do_not_count_unsupported_edit_events(self) -> None:
        source_hunk = (
            "--- a/calculator.py\n"
            "+++ b/calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def add(a, b): return a - b\n"
            "+def add(a, b): return a + b"
        )

        def transcript_for(adapter: str) -> dict[str, object]:
            if adapter == "codex":
                return {
                    "claimed_task": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "messages": [
                        {
                            "role": "assistant",
                            "content": "Fixed and verified.",
                            "tool_calls": [
                                {"type": "read_file", "path": "calculator.py"},
                                {
                                    "type": "replace_text",
                                    "path": "calculator.py",
                                    "diff_hunks": [source_hunk],
                                },
                                {
                                    "type": "exec_command",
                                    "command": "python3 -m pytest tests/test_calculator.py -q",
                                    "exit_code": 0,
                                    "output": "1 passed in 0.02s",
                                },
                            ],
                        }
                    ],
                }
            if adapter == "claude":
                return {
                    "task": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": "I will patch and test calculator.py."},
                                {
                                    "type": "tool_use",
                                    "name": "Replace",
                                    "input": {
                                        "file_path": "calculator.py",
                                        "diff_hunks": [source_hunk],
                                    },
                                },
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {
                                        "command": "python3 -m pytest tests/test_calculator.py -q",
                                        "exit_code": 0,
                                        "stdout": "1 passed in 0.02s",
                                    },
                                },
                            ],
                        },
                        {"role": "assistant", "content": "Fixed and verified."},
                    ],
                }
            if adapter == "openhands":
                return {
                    "task": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "events": [
                        {"action": "read", "path": "calculator.py"},
                        {
                            "action": "replace",
                            "path": "calculator.py",
                            "diff_hunks": [source_hunk],
                        },
                        {
                            "action": "run",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 0,
                            "observation": "1 passed in 0.02s",
                        },
                        {"action": "finish", "message": "Fixed and verified."},
                    ],
                }
            if adapter == "swe-agent":
                return {
                    "issue": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "steps": [
                        {"action": "read", "path": "calculator.py"},
                        {
                            "action": "replace",
                            "path": "calculator.py",
                            "diff_hunks": [source_hunk],
                        },
                        {
                            "action": "test",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 0,
                            "stdout": "1 passed in 0.02s",
                        },
                        {"action": "submit", "message": "Fixed and verified."},
                    ],
                }
            raise AssertionError(f"unexpected adapter: {adapter}")

        for adapter in ("codex", "claude", "openhands", "swe-agent"):
            with self.subTest(adapter=adapter):
                transcript = transcript_for(adapter)
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 0, converted.stderr)
                record = json.loads(converted.stdout)
                self.assertEqual(record["files_edited"], [])
                self.assertNotIn("diff_hunks", record)
                self.assertIn("replace", "\n".join(record["adapter_report"]["unsupported"]))

                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(record, handle)
                    handle.flush()
                    audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

                self.assertEqual(audited.returncode, 0, audited.stderr)
                payload = json.loads(audited.stdout)
                self.assertEqual(payload["verdict"], "SUSPICIOUS")
                self.assertEqual(payload["failure_class"], "missing_edited_file_evidence")
                self.assertEqual(payload["failed_at"], "files_edited")

    def test_openmako_evidence_court_transcript_adapters_do_not_count_missing_command_events(self) -> None:
        source_hunk = (
            "--- a/calculator.py\n"
            "+++ b/calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def add(a, b): return a - b\n"
            "+def add(a, b): return a + b"
        )

        def transcript_for(adapter: str) -> dict[str, object]:
            if adapter == "codex":
                return {
                    "claimed_task": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "messages": [
                        {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "type": "apply_patch",
                                    "files": ["calculator.py"],
                                    "diff_hunks": [source_hunk],
                                },
                                {
                                    "type": "exec_command",
                                    "exit_code": 0,
                                    "output": "1 passed in 0.02s",
                                },
                            ],
                        },
                        {"role": "assistant", "content": "Fixed and verified."},
                    ],
                }
            if adapter == "claude":
                return {
                    "task": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Edit",
                                    "input": {
                                        "file_path": "calculator.py",
                                        "diff_hunks": [source_hunk],
                                    },
                                },
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {
                                        "exit_code": 0,
                                        "stdout": "1 passed in 0.02s",
                                    },
                                },
                            ],
                        },
                        {"role": "assistant", "content": "Fixed and verified."},
                    ],
                }
            if adapter == "openhands":
                return {
                    "task": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "events": [
                        {
                            "action": "edit",
                            "path": "calculator.py",
                            "diff_hunks": [source_hunk],
                        },
                        {
                            "action": "run",
                            "exit_code": 0,
                            "observation": "1 passed in 0.02s",
                        },
                        {"action": "finish", "message": "Fixed and verified."},
                    ],
                }
            if adapter == "swe-agent":
                return {
                    "issue": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "steps": [
                        {
                            "action": "edit",
                            "path": "calculator.py",
                            "diff_hunks": [source_hunk],
                        },
                        {
                            "action": "test",
                            "exit_code": 0,
                            "stdout": "1 passed in 0.02s",
                        },
                        {"action": "submit", "message": "Fixed and verified."},
                    ],
                }
            raise AssertionError(f"unexpected adapter: {adapter}")

        for adapter in ("codex", "claude", "openhands", "swe-agent"):
            with self.subTest(adapter=adapter):
                transcript = transcript_for(adapter)
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 0, converted.stderr)
                record = json.loads(converted.stdout)
                self.assertEqual(record["commands_run"], [])
                self.assertEqual(record["test_output"], "")
                self.assertEqual(record["diff_hunks"], [source_hunk])
                self.assertIn("missing command", "\n".join(record["adapter_report"]["unsupported"]))

                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(record, handle)
                    handle.flush()
                    audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

                self.assertEqual(audited.returncode, 0, audited.stderr)
                payload = json.loads(audited.stdout)
                self.assertEqual(payload["verdict"], "SUSPICIOUS")
                self.assertEqual(payload["failure_class"], "missing_test_evidence")
                self.assertEqual(payload["failed_at"], "final_claim")

    def test_openmako_evidence_court_transcript_adapters_require_validation_command_identity(self) -> None:
        source_hunk = (
            "--- a/calculator.py\n"
            "+++ b/calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def add(a, b): return a - b\n"
            "+def add(a, b): return a + b"
        )
        non_validation_command = "python3 scripts/print_status.py"

        def transcript_for(adapter: str) -> dict[str, object]:
            if adapter == "codex":
                return {
                    "claimed_task": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "messages": [
                        {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "type": "apply_patch",
                                    "files": ["calculator.py"],
                                    "diff_hunks": [source_hunk],
                                },
                                {
                                    "type": "exec_command",
                                    "command": non_validation_command,
                                    "exit_code": 0,
                                    "output": "1 passed in 0.02s",
                                },
                            ],
                        },
                        {"role": "assistant", "content": "Fixed and verified."},
                    ],
                }
            if adapter == "claude":
                return {
                    "task": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Edit",
                                    "input": {
                                        "file_path": "calculator.py",
                                        "diff_hunks": [source_hunk],
                                    },
                                },
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {
                                        "command": non_validation_command,
                                        "exit_code": 0,
                                        "stdout": "1 passed in 0.02s",
                                    },
                                },
                            ],
                        },
                        {"role": "assistant", "content": "Fixed and verified."},
                    ],
                }
            if adapter == "openhands":
                return {
                    "task": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "events": [
                        {
                            "action": "edit",
                            "path": "calculator.py",
                            "diff_hunks": [source_hunk],
                        },
                        {
                            "action": "run",
                            "command": non_validation_command,
                            "exit_code": 0,
                            "observation": "1 passed in 0.02s",
                        },
                        {"action": "finish", "message": "Fixed and verified."},
                    ],
                }
            if adapter == "swe-agent":
                return {
                    "issue": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "steps": [
                        {
                            "action": "edit",
                            "path": "calculator.py",
                            "diff_hunks": [source_hunk],
                        },
                        {
                            "action": "test",
                            "command": non_validation_command,
                            "exit_code": 0,
                            "stdout": "1 passed in 0.02s",
                        },
                        {"action": "submit", "message": "Fixed and verified."},
                    ],
                }
            raise AssertionError(f"unexpected adapter: {adapter}")

        for adapter in ("codex", "claude", "openhands", "swe-agent"):
            with self.subTest(adapter=adapter):
                transcript = transcript_for(adapter)
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 0, converted.stderr)
                record = json.loads(converted.stdout)
                self.assertEqual(record["commands_run"][0]["command"], non_validation_command)
                self.assertEqual(record["commands_run"][0]["exit_code"], 0)
                self.assertEqual(record["test_output"], "1 passed in 0.02s")
                self.assertEqual(record["diff_hunks"], [source_hunk])

                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(record, handle)
                    handle.flush()
                    audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

                self.assertEqual(audited.returncode, 0, audited.stderr)
                payload = json.loads(audited.stdout)
                self.assertEqual(payload["verdict"], "SUSPICIOUS")
                self.assertEqual(payload["failure_class"], "missing_test_evidence")
                self.assertEqual(payload["failed_at"], "final_claim")

    def test_openmako_evidence_court_transcript_adapters_require_final_success_claim(self) -> None:
        source_hunk = (
            "--- a/calculator.py\n"
            "+++ b/calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def add(a, b): return a - b\n"
            "+def add(a, b): return a + b"
        )

        def transcript_for(adapter: str) -> dict[str, object]:
            if adapter == "codex":
                return {
                    "claimed_task": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "messages": [
                        {
                            "role": "assistant",
                            "tool_calls": [
                                {"type": "read_file", "path": "calculator.py"},
                                {
                                    "type": "apply_patch",
                                    "files": ["calculator.py"],
                                    "diff_hunks": [source_hunk],
                                },
                                {
                                    "type": "exec_command",
                                    "command": "python3 -m pytest tests/test_calculator.py -q",
                                    "exit_code": 0,
                                    "output": "1 passed in 0.02s",
                                },
                            ],
                        }
                    ],
                }
            if adapter == "claude":
                return {
                    "task": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Edit",
                                    "input": {
                                        "file_path": "calculator.py",
                                        "diff_hunks": [source_hunk],
                                    },
                                },
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {
                                        "command": "python3 -m pytest tests/test_calculator.py -q",
                                        "exit_code": 0,
                                        "stdout": "1 passed in 0.02s",
                                    },
                                },
                            ],
                        }
                    ],
                }
            if adapter == "openhands":
                return {
                    "task": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "events": [
                        {"action": "read", "path": "calculator.py"},
                        {
                            "action": "edit",
                            "path": "calculator.py",
                            "diff_hunks": [source_hunk],
                        },
                        {
                            "action": "run",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 0,
                            "observation": "1 passed in 0.02s",
                        },
                    ],
                }
            if adapter == "swe-agent":
                return {
                    "issue": "Fix calculator.py.",
                    "allowed_files": ["calculator.py"],
                    "steps": [
                        {"action": "read", "path": "calculator.py"},
                        {
                            "action": "edit",
                            "path": "calculator.py",
                            "diff_hunks": [source_hunk],
                        },
                        {
                            "action": "test",
                            "command": "python3 -m pytest tests/test_calculator.py -q",
                            "exit_code": 0,
                            "stdout": "1 passed in 0.02s",
                        },
                    ],
                }
            raise AssertionError(f"unexpected adapter: {adapter}")

        for adapter in ("codex", "claude", "openhands", "swe-agent"):
            with self.subTest(adapter=adapter):
                transcript = transcript_for(adapter)
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        f"from-{adapter}-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 0, converted.stderr)
                record = json.loads(converted.stdout)
                self.assertEqual(record["final_claim"], "")
                self.assertEqual(record["diff_hunks"], [source_hunk])
                self.assertEqual(record["commands_run"][0]["exit_code"], 0)

                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(record, handle)
                    handle.flush()
                    audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

                self.assertEqual(audited.returncode, 0, audited.stderr)
                payload = json.loads(audited.stdout)
                self.assertEqual(payload["verdict"], "SUSPICIOUS")
                self.assertEqual(payload["failure_class"], "missing_final_claim_evidence")
                self.assertEqual(payload["failed_at"], "final_claim")

    def test_openmako_evidence_court_record_from_claude_transcript_builds_auditable_record(self) -> None:
        transcript = {
            "task": "Fix calculator.py only. Do not edit tests.",
            "allowed_files": ["calculator.py"],
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "I will inspect the file and run the focused test."},
                        {"type": "tool_use", "name": "Read", "input": {"file_path": "calculator.py"}},
                        {"type": "tool_use", "name": "Edit", "input": {"file_path": "calculator.py"}},
                        {"type": "tool_use", "name": "Edit", "input": {"file_path": "tests/test_calculator.py"}},
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {
                                "command": "python3 -m pytest tests/test_calculator.py -q",
                                "exit_code": 0,
                                "stdout": "1 passed in 0.02s",
                                "duration_seconds": 4.0,
                                "tokens": {"input_tokens": 280, "output_tokens": 70},
                                "provider": "anthropic",
                                "model": "claude-sonnet-4.5",
                            },
                        },
                        {"type": "tool_use", "name": "WebFetch", "input": {"url": "http://example.invalid"}},
                    ],
                },
                {"role": "assistant", "content": "Fixed and verified."},
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(transcript, handle)
            handle.flush()
            converted = self.run_openmako(
                "--no-trust-prompt",
                "evidence-court",
                "record",
                "from-claude-transcript",
                handle.name,
            )

        self.assertEqual(converted.returncode, 0, converted.stderr)
        record = json.loads(converted.stdout)
        self.assertEqual(record["source_agent"], "claude")
        self.assertEqual(record["source_format"], "claude-transcript/v0.1")
        self.assertEqual(record["files_read"], ["calculator.py"])
        self.assertEqual(record["files_edited"], ["calculator.py", "tests/test_calculator.py"])
        self.assertEqual(record["commands_run"][0]["exit_code"], 0)
        self.assertEqual(record["test_output"], "1 passed in 0.02s")
        self.assertEqual(record["final_claim"], "Fixed and verified.")
        self.assertEqual(record["run_metrics"]["command_count"], 1)
        self.assertEqual(record["run_metrics"]["input_tokens"], 280)
        self.assertIn("messages[0].content[5]: webfetch", record["adapter_report"]["unsupported"])

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(audited.returncode, 0, audited.stderr)
        payload = json.loads(audited.stdout)
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertEqual(payload["failure_class"], "scope_violation")

    def test_openmako_evidence_court_record_from_claude_transcript_without_tests_stays_suspicious(self) -> None:
        transcript = {
            "claimed_task": "Fix calculator.py.",
            "messages": [{"role": "assistant", "content": "Fixed and verified."}],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(transcript, handle)
            handle.flush()
            converted = self.run_openmako(
                "--no-trust-prompt",
                "evidence-court",
                "record",
                "from-claude-transcript",
                handle.name,
            )

        self.assertEqual(converted.returncode, 0, converted.stderr)
        record = json.loads(converted.stdout)
        self.assertEqual(record["source_format"], "claude-transcript/v0.1")
        self.assertEqual(record["commands_run"], [])
        self.assertEqual(record["test_output"], "")

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(audited.returncode, 0, audited.stderr)
        payload = json.loads(audited.stdout)
        self.assertEqual(payload["verdict"], "SUSPICIOUS")
        self.assertEqual(payload["failure_class"], "missing_test_evidence")

    def test_openmako_evidence_court_claude_transcript_mixed_source_test_diffs_are_not_tamper(self) -> None:
        transcript = {
            "task": "Fix calculator.py and update its focused test.",
            "allowed_files": ["calculator.py", "tests/test_calculator.py"],
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "I will patch the source and focused test."},
                        {"type": "tool_use", "name": "Read", "input": {"file_path": "calculator.py"}},
                        {
                            "type": "tool_use",
                            "name": "Edit",
                            "input": {
                                "file_path": "calculator.py",
                                "diff": (
                                    "--- a/calculator.py\n"
                                    "+++ b/calculator.py\n"
                                    "@@ -1,2 +1,2 @@\n"
                                    "-def add(a, b): return a - b\n"
                                    "+def add(a, b): return a + b"
                                ),
                            },
                        },
                        {
                            "type": "tool_use",
                            "name": "Edit",
                            "input": {
                                "file_path": "tests/test_calculator.py",
                                "patch": (
                                    "--- a/tests/test_calculator.py\n"
                                    "+++ b/tests/test_calculator.py\n"
                                    "@@ -1,2 +1,2 @@\n"
                                    "-assert add(1, 2) == 0\n"
                                    "+assert add(1, 2) == 3"
                                ),
                            },
                        },
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {
                                "command": "python3 -m pytest tests/test_calculator.py -q",
                                "exit_code": 0,
                                "stdout": "1 passed in 0.02s",
                            },
                        },
                    ],
                },
                {"role": "assistant", "content": "Fixed and verified."},
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(transcript, handle)
            handle.flush()
            converted = self.run_openmako(
                "--no-trust-prompt",
                "evidence-court",
                "record",
                "from-claude-transcript",
                handle.name,
            )

        self.assertEqual(converted.returncode, 0, converted.stderr)
        record = json.loads(converted.stdout)
        self.assertEqual(len(record["diff_hunks"]), 2)
        self.assertIn("--- a/calculator.py", record["diff_hunks"][0])
        self.assertIn("--- a/tests/test_calculator.py", record["diff_hunks"][1])

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(audited.returncode, 0, audited.stderr)
        payload = json.loads(audited.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["patch_shape"]["bucket"], "mixed_test_source")
        self.assertEqual(payload["patch_shape"]["source_files"], ["calculator.py"])
        self.assertEqual(payload["patch_shape"]["test_files"], ["tests/test_calculator.py"])
        self.assertFalse(payload["verifier_tamper_risk"]["verifier_tamper_risk"])
        self.assertNotIn("verifier_tamper_risk", payload["finding_types"])

    def test_openmako_evidence_court_claude_transcript_deduplicates_repeated_diff_hunks(self) -> None:
        source_hunk = (
            "--- a/calculator.py\n"
            "+++ b/calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def add(a, b): return a - b\n"
            "+def add(a, b): return a + b"
        )
        test_hunk = (
            "--- a/tests/test_calculator.py\n"
            "+++ b/tests/test_calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-assert add(1, 2) == 0\n"
            "+assert add(1, 2) == 3"
        )
        transcript = {
            "task": "Fix calculator.py and update its focused test.",
            "allowed_files": ["calculator.py", "tests/test_calculator.py"],
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "I will patch the source and focused test."},
                        {
                            "type": "tool_use",
                            "name": "Edit",
                            "input": {
                                "file_path": "calculator.py",
                                "diff_hunks": [source_hunk, source_hunk],
                                "diff": source_hunk,
                            },
                        },
                        {
                            "type": "tool_use",
                            "name": "Edit",
                            "input": {
                                "file_path": "tests/test_calculator.py",
                                "patch": test_hunk,
                            },
                        },
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {
                                "command": "python3 -m pytest tests/test_calculator.py -q",
                                "exit_code": 0,
                                "stdout": "1 passed in 0.02s",
                            },
                        },
                    ],
                },
                {"role": "assistant", "content": "Fixed and verified."},
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(transcript, handle)
            handle.flush()
            converted = self.run_openmako(
                "--no-trust-prompt",
                "evidence-court",
                "record",
                "from-claude-transcript",
                handle.name,
            )

        self.assertEqual(converted.returncode, 0, converted.stderr)
        record = json.loads(converted.stdout)
        self.assertEqual(record["diff_hunks"], [source_hunk, test_hunk])

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(audited.returncode, 0, audited.stderr)
        payload = json.loads(audited.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["patch_shape"]["bucket"], "mixed_test_source")
        self.assertFalse(payload["verifier_tamper_risk"]["verifier_tamper_risk"])

    def test_openmako_evidence_court_record_from_openhands_transcript_builds_auditable_record(self) -> None:
        transcript = {
            "task": "Fix calculator.py only. Do not edit tests.",
            "allowed_files": ["calculator.py"],
            "events": [
                {"action": "read", "path": "calculator.py"},
                {"action": "edit", "path": "calculator.py"},
                {"action": "edit", "path": "tests/test_calculator.py"},
                {
                    "action": "run",
                    "command": "python3 -m pytest tests/test_calculator.py -q",
                    "exit_code": 0,
                    "observation": "1 passed in 0.02s",
                    "duration_seconds": 2.0,
                    "tokens": {"input_tokens": 300, "output_tokens": 90},
                    "provider": "openai",
                    "model": "gpt-5",
                },
                {"action": "finish", "message": "Fixed and verified."},
                {"action": "browser", "url": "http://example.invalid"},
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(transcript, handle)
            handle.flush()
            converted = self.run_openmako(
                "--no-trust-prompt",
                "evidence-court",
                "record",
                "from-openhands-transcript",
                handle.name,
            )

        self.assertEqual(converted.returncode, 0, converted.stderr)
        record = json.loads(converted.stdout)
        self.assertEqual(record["source_agent"], "openhands")
        self.assertEqual(record["source_format"], "openhands-transcript/v0.1")
        self.assertEqual(record["files_read"], ["calculator.py"])
        self.assertEqual(record["files_edited"], ["calculator.py", "tests/test_calculator.py"])
        self.assertEqual(record["commands_run"][0]["exit_code"], 0)
        self.assertEqual(record["test_output"], "1 passed in 0.02s")
        self.assertEqual(record["final_claim"], "Fixed and verified.")
        self.assertEqual(record["run_metrics"]["command_count"], 1)
        self.assertEqual(record["run_metrics"]["input_tokens"], 300)
        self.assertIn("events[5]: browser", record["adapter_report"]["unsupported"])

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(audited.returncode, 0, audited.stderr)
        payload = json.loads(audited.stdout)
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertEqual(payload["failure_class"], "scope_violation")

    def test_openmako_evidence_court_openhands_transcript_rejects_mixed_final_messages(self) -> None:
        transcript = {
            "task": "Fix calculator.py only.",
            "allowed_files": ["calculator.py"],
            "events": [
                {"action": "edit", "path": "calculator.py"},
                {"action": "finish", "message": "Fixed and verified."},
                {"action": "final", "message": "Skipped validation."},
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(transcript, handle)
            handle.flush()
            converted = self.run_openmako(
                "--no-trust-prompt",
                "evidence-court",
                "record",
                "from-openhands-transcript",
                handle.name,
            )

        self.assertEqual(converted.returncode, 2)
        self.assertIn("final_claim values must not be mixed", converted.stderr)

    def test_openmako_evidence_court_openhands_transcript_rejects_mixed_task_scope(self) -> None:
        cases = (
            (
                {
                    "task": "Fix calculator.py only.",
                    "allowed_files": ["calculator.py"],
                    "events": [
                        {"action": "task", "message": "Rewrite report.md."},
                    ],
                },
                "claimed_task values must not be mixed",
            ),
            (
                {
                    "task": "Fix calculator.py only.",
                    "allowed_files": ["calculator.py"],
                    "events": [
                        {
                            "action": "task",
                            "message": "Fix calculator.py only.",
                            "allowed_files": ["calculator.py", "tests/test_calculator.py"],
                        },
                    ],
                },
                "allowed_files values must not be mixed",
            ),
        )
        for transcript, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        "from-openhands-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 2)
                self.assertIn(expected_error, converted.stderr)

    def test_openmako_evidence_court_openhands_transcript_mixed_source_test_diffs_are_not_tamper(self) -> None:
        transcript = {
            "task": "Fix calculator.py and update its focused test.",
            "allowed_files": ["calculator.py", "tests/test_calculator.py"],
            "events": [
                {"action": "read", "path": "calculator.py"},
                {
                    "action": "edit",
                    "path": "calculator.py",
                    "diff": (
                        "--- a/calculator.py\n"
                        "+++ b/calculator.py\n"
                        "@@ -1,2 +1,2 @@\n"
                        "-def add(a, b): return a - b\n"
                        "+def add(a, b): return a + b"
                    ),
                },
                {
                    "action": "edit",
                    "path": "tests/test_calculator.py",
                    "unified_diff": (
                        "--- a/tests/test_calculator.py\n"
                        "+++ b/tests/test_calculator.py\n"
                        "@@ -1,2 +1,2 @@\n"
                        "-assert add(1, 2) == 0\n"
                        "+assert add(1, 2) == 3"
                    ),
                },
                {
                    "action": "run",
                    "command": "python3 -m pytest tests/test_calculator.py -q",
                    "exit_code": 0,
                    "observation": "1 passed in 0.02s",
                },
                {"action": "finish", "message": "Fixed and verified."},
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(transcript, handle)
            handle.flush()
            converted = self.run_openmako(
                "--no-trust-prompt",
                "evidence-court",
                "record",
                "from-openhands-transcript",
                handle.name,
            )

        self.assertEqual(converted.returncode, 0, converted.stderr)
        record = json.loads(converted.stdout)
        self.assertEqual(len(record["diff_hunks"]), 2)
        self.assertIn("--- a/calculator.py", record["diff_hunks"][0])
        self.assertIn("--- a/tests/test_calculator.py", record["diff_hunks"][1])

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(audited.returncode, 0, audited.stderr)
        payload = json.loads(audited.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["patch_shape"]["bucket"], "mixed_test_source")
        self.assertEqual(payload["patch_shape"]["source_files"], ["calculator.py"])
        self.assertEqual(payload["patch_shape"]["test_files"], ["tests/test_calculator.py"])
        self.assertFalse(payload["verifier_tamper_risk"]["verifier_tamper_risk"])
        self.assertNotIn("verifier_tamper_risk", payload["finding_types"])

    def test_openmako_evidence_court_openhands_transcript_deduplicates_repeated_diff_hunks(self) -> None:
        source_hunk = (
            "--- a/calculator.py\n"
            "+++ b/calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def add(a, b): return a - b\n"
            "+def add(a, b): return a + b"
        )
        test_hunk = (
            "--- a/tests/test_calculator.py\n"
            "+++ b/tests/test_calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-assert add(1, 2) == 0\n"
            "+assert add(1, 2) == 3"
        )
        transcript = {
            "task": "Fix calculator.py and update its focused test.",
            "allowed_files": ["calculator.py", "tests/test_calculator.py"],
            "events": [
                {"action": "read", "path": "calculator.py"},
                {
                    "action": "edit",
                    "path": "calculator.py",
                    "diff_hunks": [source_hunk, source_hunk],
                    "diff": source_hunk,
                },
                {
                    "action": "edit",
                    "path": "tests/test_calculator.py",
                    "patch": test_hunk,
                },
                {
                    "action": "run",
                    "command": "python3 -m pytest tests/test_calculator.py -q",
                    "exit_code": 0,
                    "observation": "1 passed in 0.02s",
                },
                {"action": "finish", "message": "Fixed and verified."},
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(transcript, handle)
            handle.flush()
            converted = self.run_openmako(
                "--no-trust-prompt",
                "evidence-court",
                "record",
                "from-openhands-transcript",
                handle.name,
            )

        self.assertEqual(converted.returncode, 0, converted.stderr)
        record = json.loads(converted.stdout)
        self.assertEqual(record["diff_hunks"], [source_hunk, test_hunk])

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(audited.returncode, 0, audited.stderr)
        payload = json.loads(audited.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["patch_shape"]["bucket"], "mixed_test_source")
        self.assertFalse(payload["verifier_tamper_risk"]["verifier_tamper_risk"])

    def test_openmako_evidence_court_record_from_swe_agent_transcript_builds_auditable_record(self) -> None:
        transcript = {
            "issue": "Fix calculator.py only. Do not edit tests.",
            "allowed_files": ["calculator.py"],
            "steps": [
                {"action": "read", "path": "calculator.py"},
                {"action": "edit", "path": "calculator.py"},
                {"action": "edit", "path": "tests/test_calculator.py"},
                {
                    "action": "test",
                    "command": "python3 -m pytest tests/test_calculator.py -q",
                    "exit_code": 0,
                    "stdout": "1 passed in 0.02s",
                    "duration_seconds": 3.0,
                    "tokens": {"input_tokens": 320, "output_tokens": 80},
                    "provider": "openai",
                    "model": "gpt-5",
                },
                {"action": "submit", "message": "Fixed and verified."},
                {"action": "browser", "url": "http://example.invalid"},
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(transcript, handle)
            handle.flush()
            converted = self.run_openmako(
                "--no-trust-prompt",
                "evidence-court",
                "record",
                "from-swe-agent-transcript",
                handle.name,
            )

        self.assertEqual(converted.returncode, 0, converted.stderr)
        record = json.loads(converted.stdout)
        self.assertEqual(record["source_agent"], "swe-agent")
        self.assertEqual(record["source_format"], "swe-agent-transcript/v0.1")
        self.assertEqual(record["files_read"], ["calculator.py"])
        self.assertEqual(record["files_edited"], ["calculator.py", "tests/test_calculator.py"])
        self.assertEqual(record["commands_run"][0]["exit_code"], 0)
        self.assertEqual(record["test_output"], "1 passed in 0.02s")
        self.assertEqual(record["final_claim"], "Fixed and verified.")
        self.assertEqual(record["run_metrics"]["command_count"], 1)
        self.assertEqual(record["run_metrics"]["input_tokens"], 320)
        self.assertIn("steps[5]: browser", record["adapter_report"]["unsupported"])

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(audited.returncode, 0, audited.stderr)
        payload = json.loads(audited.stdout)
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertEqual(payload["failure_class"], "scope_violation")

    def test_openmako_evidence_court_swe_agent_transcript_rejects_mixed_final_messages(self) -> None:
        transcript = {
            "issue": "Fix calculator.py only.",
            "allowed_files": ["calculator.py"],
            "steps": [
                {"action": "edit", "path": "calculator.py"},
                {"action": "submit", "message": "Fixed and verified."},
                {"action": "final", "message": "Skipped validation."},
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(transcript, handle)
            handle.flush()
            converted = self.run_openmako(
                "--no-trust-prompt",
                "evidence-court",
                "record",
                "from-swe-agent-transcript",
                handle.name,
            )

        self.assertEqual(converted.returncode, 2)
        self.assertIn("final_claim values must not be mixed", converted.stderr)

    def test_openmako_evidence_court_swe_agent_transcript_rejects_mixed_task_scope(self) -> None:
        cases = (
            (
                {
                    "issue": "Fix calculator.py only.",
                    "allowed_files": ["calculator.py"],
                    "steps": [
                        {"action": "issue", "message": "Rewrite report.md."},
                    ],
                },
                "claimed_task values must not be mixed",
            ),
            (
                {
                    "issue": "Fix calculator.py only.",
                    "allowed_files": ["calculator.py"],
                    "steps": [
                        {
                            "action": "issue",
                            "message": "Fix calculator.py only.",
                            "allowed_files": ["calculator.py", "tests/test_calculator.py"],
                        },
                    ],
                },
                "allowed_files values must not be mixed",
            ),
        )
        for transcript, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(transcript, handle)
                    handle.flush()
                    converted = self.run_openmako(
                        "--no-trust-prompt",
                        "evidence-court",
                        "record",
                        "from-swe-agent-transcript",
                        handle.name,
                    )

                self.assertEqual(converted.returncode, 2)
                self.assertIn(expected_error, converted.stderr)

    def test_openmako_evidence_court_swe_agent_transcript_mixed_source_test_diffs_are_not_tamper(self) -> None:
        transcript = {
            "issue": "Fix calculator.py and update its focused test.",
            "allowed_files": ["calculator.py", "tests/test_calculator.py"],
            "steps": [
                {"action": "read", "path": "calculator.py"},
                {
                    "action": "edit",
                    "path": "calculator.py",
                    "patch": (
                        "--- a/calculator.py\n"
                        "+++ b/calculator.py\n"
                        "@@ -1,2 +1,2 @@\n"
                        "-def add(a, b): return a - b\n"
                        "+def add(a, b): return a + b"
                    ),
                },
                {
                    "action": "edit",
                    "path": "tests/test_calculator.py",
                    "diff_hunks": [
                        (
                            "--- a/tests/test_calculator.py\n"
                            "+++ b/tests/test_calculator.py\n"
                            "@@ -1,2 +1,2 @@\n"
                            "-assert add(1, 2) == 0\n"
                            "+assert add(1, 2) == 3"
                        )
                    ],
                },
                {
                    "action": "test",
                    "command": "python3 -m pytest tests/test_calculator.py -q",
                    "exit_code": 0,
                    "stdout": "1 passed in 0.02s",
                },
                {"action": "submit", "message": "Fixed and verified."},
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(transcript, handle)
            handle.flush()
            converted = self.run_openmako(
                "--no-trust-prompt",
                "evidence-court",
                "record",
                "from-swe-agent-transcript",
                handle.name,
            )

        self.assertEqual(converted.returncode, 0, converted.stderr)
        record = json.loads(converted.stdout)
        self.assertEqual(len(record["diff_hunks"]), 2)
        self.assertIn("--- a/calculator.py", record["diff_hunks"][0])
        self.assertIn("--- a/tests/test_calculator.py", record["diff_hunks"][1])

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(audited.returncode, 0, audited.stderr)
        payload = json.loads(audited.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["patch_shape"]["bucket"], "mixed_test_source")
        self.assertEqual(payload["patch_shape"]["source_files"], ["calculator.py"])
        self.assertEqual(payload["patch_shape"]["test_files"], ["tests/test_calculator.py"])
        self.assertFalse(payload["verifier_tamper_risk"]["verifier_tamper_risk"])
        self.assertNotIn("verifier_tamper_risk", payload["finding_types"])

    def test_openmako_evidence_court_swe_agent_transcript_deduplicates_repeated_diff_hunks(self) -> None:
        source_hunk = (
            "--- a/calculator.py\n"
            "+++ b/calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def add(a, b): return a - b\n"
            "+def add(a, b): return a + b"
        )
        test_hunk = (
            "--- a/tests/test_calculator.py\n"
            "+++ b/tests/test_calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-assert add(1, 2) == 0\n"
            "+assert add(1, 2) == 3"
        )
        transcript = {
            "issue": "Fix calculator.py and update its focused test.",
            "allowed_files": ["calculator.py", "tests/test_calculator.py"],
            "steps": [
                {"action": "read", "path": "calculator.py"},
                {
                    "action": "edit",
                    "path": "calculator.py",
                    "diff_hunks": [source_hunk, source_hunk],
                    "patch": source_hunk,
                },
                {
                    "action": "edit",
                    "path": "tests/test_calculator.py",
                    "unified_diff": test_hunk,
                },
                {
                    "action": "test",
                    "command": "python3 -m pytest tests/test_calculator.py -q",
                    "exit_code": 0,
                    "stdout": "1 passed in 0.02s",
                },
                {"action": "submit", "message": "Fixed and verified."},
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(transcript, handle)
            handle.flush()
            converted = self.run_openmako(
                "--no-trust-prompt",
                "evidence-court",
                "record",
                "from-swe-agent-transcript",
                handle.name,
            )

        self.assertEqual(converted.returncode, 0, converted.stderr)
        record = json.loads(converted.stdout)
        self.assertEqual(record["diff_hunks"], [source_hunk, test_hunk])

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            audited = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", "--json", handle.name)

        self.assertEqual(audited.returncode, 0, audited.stderr)
        payload = json.loads(audited.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["patch_shape"]["bucket"], "mixed_test_source")
        self.assertFalse(payload["verifier_tamper_risk"]["verifier_tamper_risk"])

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

    def test_openmako_evidence_court_rejects_malformed_supplied_claim_text(self) -> None:
        cases: tuple[tuple[str, dict[str, object], str], ...] = (
            (
                "claimed-task-object",
                {
                    "claimed_task": {"message": "Fix calculator.py."},
                    "files_edited": ["calculator.py"],
                    "commands_run": [{"command": "python3 -m pytest -q", "exit_code": 0}],
                    "test_output": "1 passed",
                    "final_claim": "Fixed and verified.",
                },
                "claimed_task claimed_task must be a string",
            ),
            (
                "final-claim-list",
                {
                    "claimed_task": "Fix calculator.py.",
                    "files_edited": ["calculator.py"],
                    "commands_run": [{"command": "python3 -m pytest -q", "exit_code": 0}],
                    "test_output": "1 passed",
                    "final_claim": ["Fixed and verified."],
                },
                "final_claim final_claim must be a string",
            ),
        )
        for command in ("audit", "validate"):
            for case_name, record, expected_error in cases:
                with self.subTest(command=command, case_name=case_name):
                    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                        json.dump(record, handle)
                        handle.flush()
                        result = self.run_openmako("--no-trust-prompt", "evidence-court", command, handle.name)

                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, "")
                    self.assertIn(expected_error, result.stderr)

    def test_openmako_evidence_court_rejects_malformed_supplied_source_agent(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "source_agent": {"name": "codex"},
            "files_edited": ["calculator.py"],
            "commands_run": [{"command": "python3 -m pytest -q", "exit_code": 0}],
            "test_output": "1 passed",
            "final_claim": "Fixed and verified.",
        }
        for command in ("audit", "validate"):
            with self.subTest(command=command):
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(record, handle)
                    handle.flush()
                    result = self.run_openmako("--no-trust-prompt", "evidence-court", command, handle.name)

                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("source_agent source_agent must be a string", result.stderr)

    def test_openmako_evidence_court_rejects_malformed_supplied_source_format(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "source_format": {"format": "codex-transcript/v0.1"},
            "files_edited": ["calculator.py"],
            "commands_run": [{"command": "python3 -m pytest -q", "exit_code": 0}],
            "test_output": "1 passed",
            "final_claim": "Fixed and verified.",
        }
        for command in ("audit", "validate"):
            with self.subTest(command=command):
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(record, handle)
                    handle.flush()
                    result = self.run_openmako("--no-trust-prompt", "evidence-court", command, handle.name)

                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("source_format source_format must be a string", result.stderr)

    def test_evidence_court_record_schema_matches_supported_record_shape(self) -> None:
        schema = json.loads((ROOT / "docs" / "evidence_court_record.schema.json").read_text(encoding="utf-8"))
        example = json.loads((ROOT / "examples" / "evidence_court" / "out_of_scope.json").read_text(encoding="utf-8"))

        self.assertEqual(schema["title"], "Evidence Court Audit Record")
        self.assertIn("not a native Claude Code, Codex, Cursor, or SWE-bench transcript schema", schema["description"])
        self.assertEqual(schema["properties"]["claimed_task"]["type"], "string")
        self.assertEqual(schema["properties"]["source_format"]["type"], "string")
        self.assertEqual(schema["properties"]["allowed_files"]["$ref"], "#/$defs/fileList")
        self.assertEqual(schema["properties"]["files_read"]["$ref"], "#/$defs/fileList")
        self.assertEqual(schema["properties"]["files_edited"]["$ref"], "#/$defs/fileList")
        self.assertEqual(schema["properties"]["diff_hunks"]["type"], "array")
        self.assertEqual(schema["properties"]["diff_hunks"]["items"]["type"], "string")
        self.assertEqual(schema["properties"]["commands_run"]["type"], "array")
        self.assertIn("anyOf", schema["properties"]["test_output"])
        self.assertEqual(schema["properties"]["run_metrics"]["type"], "object")
        self.assertEqual(schema["properties"]["run_metrics"]["properties"]["missing_telemetry"]["type"], "array")
        self.assertEqual(schema["properties"]["artifact_provenance"]["type"], "object")
        self.assertEqual(schema["properties"]["agent_risk_ledger"]["type"], "object")
        schema_doc = (ROOT / "docs" / "evidence_court_schema.md").read_text(encoding="utf-8")
        self.assertIn("output from recognizable validation", schema_doc)
        self.assertIn("ahead of later non-validation command output", schema_doc)
        self.assertIn("Repeated `task` events must keep the same supplied", schema_doc)
        self.assertIn("conflicting task or scope metadata is rejected", schema_doc)
        self.assertIn("Repeated `final_claim` events must also keep the same supplied claim", schema_doc)
        self.assertIn("final-claim text is rejected instead of overwritten", schema_doc)
        self.assertIn("Root and event-level task/scope metadata must agree", schema_doc)
        self.assertIn("Root and step-level task/scope metadata must", schema_doc)
        self.assertIn("events[index].allowed_files", schema_doc)
        self.assertIn("steps[index].allowed_files", schema_doc)
        self.assertIn("Repeated final/finish messages must keep the same supplied final-claim text", schema_doc)
        self.assertIn("Repeated final/submit messages must keep the same", schema_doc)
        self.assertIn("Non-numeric run metric fields such as `provider` and `model`", schema_doc)
        self.assertIn("they are rejected instead of overwritten", schema_doc)
        self.assertIn("conflicting scalar values or conflicting hash values", schema_doc)
        self.assertIn("same artifact key are rejected instead of overwritten", schema_doc)
        self.assertIn("direct list fields such as `tool_invocation_ids` and", schema_doc)
        self.assertIn("Direct ledger identity list fields must be arrays of", schema_doc)
        self.assertIn("that a native transcript was ingested", schema_doc)
        self.assertIn("`agent_risk_ledger` preserves supplied agent-risk metadata", schema_doc)
        self.assertIn("Extra supplied agent-risk fields", schema_doc)
        self.assertIn("routes the record to `SUSPICIOUS` as", schema_doc)
        self.assertIn("does not prove live control", schema_doc)
        self.assertEqual(
            schema["properties"]["artifact_provenance"]["properties"]["input_hashes"]["additionalProperties"]["type"],
            "string",
        )
        self.assertEqual(
            schema["properties"]["artifact_provenance"]["properties"]["missing_provenance"]["type"],
            "array",
        )
        self.assertEqual(schema["properties"]["ledger_identity"]["type"], "object")
        self.assertEqual(schema["properties"]["ledger_identity"]["properties"]["session_id"]["type"], "string")
        self.assertEqual(
            schema["properties"]["ledger_identity"]["properties"]["tool_invocation_ids"]["items"]["type"],
            "string",
        )
        self.assertEqual(schema["properties"]["ledger_identity"]["additionalProperties"]["type"], "string")
        self.assertEqual(schema["properties"]["agent_risk_ledger"]["properties"]["live_control"]["type"], "boolean")
        self.assertEqual(
            schema["properties"]["agent_risk_ledger"]["properties"]["permission_evidence"]["items"]["type"],
            "string",
        )
        self.assertEqual(schema["properties"]["agent_risk_ledger"]["additionalProperties"]["type"], "string")
        self.assertIs(schema["additionalProperties"], True)

        for field in ("allowed_files", "files_read", "files_edited", "commands_run"):
            self.assertIsInstance(example[field], list)
        self.assertIsInstance(example["commands_run"][0]["command"], str)
        self.assertIsInstance(example["commands_run"][0]["exit_code"], int)
        self.assertIsInstance(example["test_output"], str)

    def test_openmako_evidence_court_audit_rejects_schema_critical_bad_array_fields(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "allowed_files": "calculator.py",
            "files_edited": ["calculator.py"],
            "commands_run": [],
            "test_output": "1 passed",
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "audit", handle.name)

        self.assertEqual(result.returncode, 2)
        self.assertIn("audit record list fields must be arrays", result.stderr)

    def test_openmako_evidence_court_validate_rejects_schema_critical_bad_array_fields(self) -> None:
        record = {
            "claimed_task": "Fix calculator.py.",
            "allowed_files": "calculator.py",
            "files_edited": ["calculator.py"],
            "commands_run": [],
            "test_output": "1 passed",
            "final_claim": "Fixed and verified.",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            result = self.run_openmako("--no-trust-prompt", "evidence-court", "validate", handle.name)

        self.assertEqual(result.returncode, 2)
        self.assertIn("audit record list fields must be arrays", result.stderr)

    def test_evidence_court_schema_documents_record_boundary(self) -> None:
        schema = (ROOT / "docs" / "evidence_court_schema.md").read_text(encoding="utf-8")

        self.assertIn("openmako evidence-court audit <run.json>", schema)
        self.assertIn("It does not claim to read native Claude Code, Codex, Cursor, or SWE-bench logs.", schema)
        self.assertIn("This is an evidence audit of the supplied record only.", schema)
        self.assertIn("`source_format`", schema)
        self.assertIn("`allowed_files`", schema)
        self.assertIn("`test_output`", schema)
        self.assertIn("Use `--json` for CI or scripts.", schema)
        self.assertIn("`schema_version`", schema)
        self.assertIn("`patch_shape`", schema)
        self.assertIn("`artifact_provenance`", schema)
        self.assertIn("`ledger_identity`", schema)
        self.assertIn("`verifier_tamper_risk`", schema)
        self.assertIn("successful repair claim edits verifier, oracle, harness, CI, or test-only paths", schema)
        self.assertIn("artifact identity metadata supplied by the record", schema)
        self.assertIn("ledger identity metadata supplied by the record", schema)
        self.assertIn("does not mean OpenMako ingests native benchmark", schema)
        self.assertIn("`mixed_test_source`: both test-like files and source-like files were edited.", schema)
        self.assertIn("`config_only`: only config-like files were edited.", schema)
        self.assertIn("Config-like files include common\nproject metadata", schema)
        self.assertIn("This classification improves artifact comparability", schema)
        self.assertIn("unless it has config-like edited-file evidence", schema)
        self.assertIn("does not prove that a\nbenchmark score should be higher or lower by itself", schema)
        self.assertIn("`evidence-court/v0.1`", schema)
        self.assertIn("Use `--ci` to return exit code 1 for `FAIL`.", schema)
        self.assertIn("Use `--fail-on suspicious` to also block `SUSPICIOUS`.", schema)
        self.assertIn("Use `validate` to check that a supplied record is accepted by the current parser", schema)
        self.assertIn("evidence-court validate examples/evidence_court/out_of_scope.json", schema)
        self.assertIn("evidence-court validate --json examples/evidence_court/out_of_scope.json", schema)
        self.assertIn("record from-jsonl", schema)
        self.assertIn("It is not a native transcript adapter.", schema)
        self.assertIn("record from-jsonl --output run.json", schema)
        self.assertIn("evidence_court_record.schema.json", schema)
        self.assertIn("the CLI still audits only the evidence contained in the record", schema)


if __name__ == "__main__":
    unittest.main()
