from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from quantagent import patch_visa


class PatchVisaGateTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent patch visa gate ")

    def test_fake_proof_text_without_fact_id_is_rejected(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            receipt = _receipt_for_paths(project, ["a.py"])
            span_id = next(iter(receipt.authorized_spans))
            output = patch_visa.TaintedModelOutput(
                json.dumps(
                    {
                        "candidates": [
                            {
                                "edits": [
                                    {
                                        "path": "a.py",
                                        "old": "VALUE = 1",
                                        "new": "VALUE = 2",
                                        "proof": "valid because I said so",
                                        "visa_request": {
                                            "receipt_id": str(receipt.receipt_id),
                                            "authorized_span_id": str(span_id),
                                            "repair_pattern_id": patch_visa.DEFAULT_REPAIR_PATTERN,
                                        },
                                    }
                                ]
                            }
                        ]
                    }
                )
            )

            hunk = patch_visa.parse_hunk_proposals(output)[0]
            result = patch_visa.mint_patch_visa(hunk, receipt, patch_visa.build_current_snapshot(project, receipt))

        self.assertIsInstance(result, patch_visa.RejectReason)
        self.assertEqual(result.code, "missing_fact_ids")

    def test_nonexistent_fact_id_is_rejected(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            receipt = _receipt_for_paths(project, ["a.py"])
            hunk = _hunk(receipt, "a.py", "VALUE = 1", "VALUE = 2", fact_ids=(patch_visa.FactId("F404"),))

            result = patch_visa.mint_patch_visa(hunk, receipt, patch_visa.build_current_snapshot(project, receipt))

        self.assertIsInstance(result, patch_visa.RejectReason)
        self.assertEqual(result.code, "unknown_fact_id")

    def test_stale_receipt_is_rejected(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            receipt = _receipt_for_paths(project, ["a.py"])
            hunk = _hunk(receipt, "a.py", "VALUE = 1", "VALUE = 2", receipt_id=patch_visa.ReceiptId("old-receipt"))

            result = patch_visa.mint_patch_visa(hunk, receipt, patch_visa.build_current_snapshot(project, receipt))

        self.assertIsInstance(result, patch_visa.RejectReason)
        self.assertEqual(result.code, "stale_receipt")

    def test_test_hack_without_test_approval_is_rejected(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            tests = project / "tests"
            tests.mkdir()
            (tests / "test_x.py").write_text("assert value == 1\n", encoding="utf-8")
            receipt = _receipt_for_paths(project, ["tests/test_x.py"])
            hunk = _hunk(receipt, "tests/test_x.py", "assert value == 1", "assert value == 2")

            result = patch_visa.mint_patch_visa(hunk, receipt, patch_visa.build_current_snapshot(project, receipt))

        self.assertIsInstance(result, patch_visa.RejectReason)
        self.assertEqual(result.code, "test_change_without_approval")

    def test_span_smuggling_outside_authorized_span_is_rejected(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            source = "def target():\n    return 1\n\ndef other():\n    return 9\n"
            (project / "a.py").write_text(source, encoding="utf-8")
            receipt = _narrow_receipt(project, "a.py", start=1, end=2)
            hunk = _hunk(receipt, "a.py", "def other():\n    return 9", "def other():\n    return 2")

            result = patch_visa.mint_patch_visa(hunk, receipt, patch_visa.build_current_snapshot(project, receipt))

        self.assertIsInstance(result, patch_visa.RejectReason)
        self.assertEqual(result.code, "old_text_outside_span")

    def test_visa_reuse_for_different_hunk_is_rejected_by_closure(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            receipt = _receipt_for_paths(project, ["a.py"])
            snapshot = patch_visa.build_current_snapshot(project, receipt)
            hunk_a = _hunk(receipt, "a.py", "VALUE = 1", "VALUE = 2")
            hunk_b = _hunk(receipt, "a.py", "VALUE = 1", "VALUE = 3")
            visa_a = patch_visa.mint_patch_visa(hunk_a, receipt, snapshot)

            result = patch_visa.closure_check([patch_visa.VisaApprovedHunk(hunk_b, visa_a)], receipt, snapshot)

        self.assertIsInstance(visa_a, patch_visa.PatchVisa)
        self.assertIsInstance(result, patch_visa.ClosureReject)
        self.assertEqual(result.reason, "visa hunk hash mismatch")


def _receipt_for_paths(project: Path, paths: list[str]) -> patch_visa.EvidenceReceipt:
    return patch_visa.build_receipt_from_paths(project, paths, verified_facts=["failure_class=assertion"])


def _narrow_receipt(project: Path, path: str, *, start: int, end: int) -> patch_visa.EvidenceReceipt:
    text = (project / path).read_text(encoding="utf-8")
    lines = text.splitlines()
    body = "\n".join(lines[start - 1 : end])
    span = patch_visa.SpanReceipt(path=path, start=start, end=end, span_hash=hashlib.blake2b(body.encode("utf-8"), digest_size=16).hexdigest())
    span_id = patch_visa.SpanId("span-target")
    receipt = patch_visa.EvidenceReceipt(
        receipt_id=patch_visa.ReceiptId("receipt-target"),
        snapshot_hash="",
        verified_fact_ids=frozenset({patch_visa.FactId("fact-target")}),
        suspect_scopes=frozenset({path}),
        authorized_symbols={},
        authorized_spans={span_id: span},
        allowed_repair_patterns=frozenset({patch_visa.DEFAULT_REPAIR_PATTERN}),
        forbidden_shapes=frozenset(),
        clean=True,
    )
    snapshot = patch_visa.build_current_snapshot(project, receipt)
    return replace(receipt, snapshot_hash=snapshot.snapshot_hash)


def _hunk(
    receipt: patch_visa.EvidenceReceipt,
    path: str,
    old: str,
    new: str,
    *,
    receipt_id: patch_visa.ReceiptId | None = None,
    fact_ids: tuple[patch_visa.FactId, ...] | None = None,
) -> patch_visa.HunkProposal:
    return patch_visa.HunkProposal(
        path=path,
        old=old,
        new=new,
        visa_request=patch_visa.VisaRequest(
            receipt_id=receipt_id or receipt.receipt_id,
            fact_ids=fact_ids or tuple(sorted(receipt.verified_fact_ids, key=str)[:1]),
            authorized_span_id=next(iter(receipt.authorized_spans)),
            repair_pattern_id=patch_visa.DEFAULT_REPAIR_PATTERN,
        ),
    )


if __name__ == "__main__":
    unittest.main()
