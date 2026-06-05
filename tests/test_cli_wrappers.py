from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "agent_autopsy" / "agent_modified_test_failed"


class CliWrapperTest(unittest.TestCase):
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
        self.assertIn("- failure_class: assertion", result.stdout)
        self.assertIn("- evidence_items: 1", result.stdout)

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
        self.assertEqual(payload["report"]["evidence"][0]["source"], "task")

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

    def test_evidence_court_record_schema_matches_supported_record_shape(self) -> None:
        schema = json.loads((ROOT / "docs" / "evidence_court_record.schema.json").read_text(encoding="utf-8"))
        example = json.loads((ROOT / "examples" / "evidence_court" / "out_of_scope.json").read_text(encoding="utf-8"))

        self.assertEqual(schema["title"], "Evidence Court Audit Record")
        self.assertIn("not a native Claude Code, Codex, Cursor, or SWE-bench transcript schema", schema["description"])
        self.assertEqual(schema["properties"]["claimed_task"]["type"], "string")
        self.assertEqual(schema["properties"]["allowed_files"]["$ref"], "#/$defs/fileList")
        self.assertEqual(schema["properties"]["files_read"]["$ref"], "#/$defs/fileList")
        self.assertEqual(schema["properties"]["files_edited"]["$ref"], "#/$defs/fileList")
        self.assertEqual(schema["properties"]["commands_run"]["type"], "array")
        self.assertIn("anyOf", schema["properties"]["test_output"])
        self.assertEqual(schema["properties"]["run_metrics"]["type"], "object")
        self.assertEqual(schema["properties"]["run_metrics"]["properties"]["missing_telemetry"]["type"], "array")
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
        self.assertIn("`allowed_files`", schema)
        self.assertIn("`test_output`", schema)
        self.assertIn("Use `--json` for CI or scripts.", schema)
        self.assertIn("`schema_version`", schema)
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
