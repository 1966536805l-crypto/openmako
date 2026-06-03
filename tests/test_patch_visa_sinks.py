from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from quantagent import patch_visa
from quantagent.edit_loop import create_patch_plan, run_isolated_repair_loop, run_patch_plan
from quantagent.model_client import ModelResponse


class PatchVisaSinkTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent patch visa sinks ")

    def test_run_patch_plan_rejects_direct_hunk_proposal(self) -> None:
        hunk = patch_visa.HunkProposal(
            path="a.py",
            old="VALUE = 1",
            new="VALUE = 2",
            visa_request=patch_visa.VisaRequest(patch_visa.ReceiptId("r"), (patch_visa.FactId("f"),)),
        )

        with self.make_project() as tmp:
            with self.assertRaises(TypeError):
                run_patch_plan(Path(tmp), hunk)  # type: ignore[arg-type]

    def test_rejected_hunk_body_does_not_enter_retry_prompt(self) -> None:
        class FakeClient:
            configured = True

            def __init__(self) -> None:
                self.calls = 0
                self.prompts: list[str] = []

            def complete(self, request):
                self.calls += 1
                self.prompts.append(request.prompt)
                return ModelResponse(
                    model=request.model,
                    ok=True,
                    text=json.dumps(
                        {
                            "candidates": [
                                {
                                    "name": "outside-scope",
                                    "summary": "outside scope",
                                    "edits": [
                                        {
                                            "path": "secret.py",
                                            "old": "SECRET_REJECTED_OLD",
                                            "new": "SECRET_REJECTED_NEW",
                                        }
                                    ],
                                }
                            ]
                        }
                    ),
                    provider="fake",
                )

        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            (project / "secret.py").write_text("SECRET_REJECTED_OLD\n", encoding="utf-8")
            plan = create_patch_plan(project, "fix value", paths=["a.py"], test_command=["grep", "-q", "VALUE = 2", "a.py"])
            client = FakeClient()

            result = run_isolated_repair_loop(project, plan, "AssertionError: expected VALUE = 2", model="fake-model", client=client, max_rounds=2)

        self.assertFalse(result.ok)
        self.assertEqual(client.calls, 2)
        self.assertNotIn("SECRET_REJECTED_OLD", client.prompts[1])
        self.assertNotIn("SECRET_REJECTED_NEW", client.prompts[1])
        self.assertIn("rejected_hunks=", client.prompts[1])

    def test_visa_chain_repairs_real_unittest_red_green_failure(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
            tests = project / "tests"
            tests.mkdir()
            (tests / "test_calculator.py").write_text(
                "import unittest\n"
                "from calculator import add\n\n"
                "class CalculatorTest(unittest.TestCase):\n"
                "    def test_adds_numbers(self):\n"
                "        self.assertEqual(add(2, 3), 5)\n",
                encoding="utf-8",
            )
            pre = subprocess.run(
                ["python3", "-B", "-m", "unittest", "discover", "-s", "tests"],
                cwd=project,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(pre.returncode, 0, pre.stdout + pre.stderr)

            receipt = patch_visa.build_receipt_from_spans(
                project,
                [("calculator.py", 1, 2)],
                verified_facts=["failure_class=assertion", "python_file=calculator.py"],
                suspect_symbols=["calculator.py:add"],
            )
            fact_id = next(iter(sorted(receipt.verified_fact_ids, key=str)))
            span_id = next(iter(receipt.authorized_spans))
            symbol_id = next(iter(receipt.authorized_symbols))
            output = patch_visa.TaintedModelOutput(
                json.dumps(
                    {
                        "hunks": [
                            {
                                "path": "calculator.py",
                                "old": "    return a - b",
                                "new": "    return a + b",
                                "visa_request": {
                                    "receipt_id": str(receipt.receipt_id),
                                    "fact_ids": [str(fact_id)],
                                    "suspect_symbol_id": str(symbol_id),
                                    "authorized_span_id": str(span_id),
                                    "repair_pattern_id": patch_visa.DEFAULT_REPAIR_PATTERN,
                                },
                            }
                        ]
                    }
                )
            )

            hunks = patch_visa.parse_hunk_proposals(output)
            snapshot = patch_visa.build_current_snapshot(project, receipt)
            visa_results = [patch_visa.mint_patch_visa(hunk, receipt, snapshot) for hunk in hunks]
            approved, audit = patch_visa.filter_hunks(hunks, visa_results)
            candidate = patch_visa.closure_check(
                approved,
                receipt,
                snapshot,
                task="fix calculator add",
                test_command=["python3", "-B", "-m", "unittest", "discover", "-s", "tests", "-p", "test_calculator.py"],
                allow_risky_tests=True,
                audit=audit,
            )

            self.assertIsInstance(candidate, patch_visa.ChangeSetCandidate)
            result = run_patch_plan(project, candidate, apply=True)
            post = subprocess.run(
                ["python3", "-B", "-m", "unittest", "discover", "-s", "tests"],
                cwd=project,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertTrue(result.ok, result.summary)
            self.assertEqual(post.returncode, 0, post.stdout + post.stderr)
            self.assertEqual((project / "calculator.py").read_text(encoding="utf-8"), "def add(a, b):\n    return a + b\n")


if __name__ == "__main__":
    unittest.main()
