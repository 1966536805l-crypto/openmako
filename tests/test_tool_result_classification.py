from __future__ import annotations

import json
import unittest

from quantagent.evidence_ledger import evidence_from_tool_result, find_evidence
from quantagent.tool_result_classification import (
    FILE_MUTATING_TOOL_NAMES,
    file_mutation_result_landed,
)


class ToolResultClassificationTest(unittest.TestCase):
    def test_write_file_requires_bytes_written(self) -> None:
        self.assertTrue(file_mutation_result_landed("write_file", json.dumps({"bytes_written": 12})))
        self.assertTrue(file_mutation_result_landed("write_file", json.dumps({"bytes_written": 0})))

        self.assertFalse(file_mutation_result_landed("write_file", json.dumps({"path": "a.py"})))
        self.assertFalse(file_mutation_result_landed("write_file", json.dumps({"bytes_written": None})))
        self.assertFalse(file_mutation_result_landed("write_file", json.dumps({"bytes_written": "12"})))
        self.assertFalse(file_mutation_result_landed("write_file", json.dumps({"bytes_written": -1})))
        self.assertFalse(file_mutation_result_landed("write_file", json.dumps({"bytes_written": True})))

    def test_patch_requires_strict_success_true(self) -> None:
        self.assertTrue(file_mutation_result_landed("patch", json.dumps({"success": True})))

        self.assertFalse(file_mutation_result_landed("patch", json.dumps({"success": False})))
        self.assertFalse(file_mutation_result_landed("patch", json.dumps({"success": "true"})))

    def test_error_payload_never_counts_as_landed(self) -> None:
        self.assertFalse(
            file_mutation_result_landed(
                "write_file",
                json.dumps({"bytes_written": 12, "error": "permission denied"}),
            )
        )
        self.assertFalse(
            file_mutation_result_landed(
                "patch",
                json.dumps({"success": True, "error": "rejected"}),
            )
        )

    def test_ignores_non_mutating_tools_and_malformed_payloads(self) -> None:
        self.assertEqual(FILE_MUTATING_TOOL_NAMES, frozenset({"write_file", "patch"}))
        self.assertFalse(file_mutation_result_landed("read_file", json.dumps({"bytes_written": 12})))
        self.assertFalse(file_mutation_result_landed("write_file", {"bytes_written": 12}))
        self.assertFalse(file_mutation_result_landed("write_file", "[1, 2, 3]"))
        self.assertFalse(file_mutation_result_landed("patch", "not json"))

    def test_evidence_ledger_records_classified_mutation_payloads(self) -> None:
        records = evidence_from_tool_result(
            "write_file",
            "write completed",
            {"result": json.dumps({"bytes_written": 12})},
        )
        landed = next(record for record in records if record.claim == "write_file.mutation_landed")

        self.assertEqual(landed.value, "true")
        self.assertFalse(landed.verified)
        self.assertEqual(landed.source, "tool_result.classifier")
        self.assertEqual(find_evidence(".", "write_file.mutation_landed", records=[landed]), [])

        failed = evidence_from_tool_result(
            "patch",
            "patch failed",
            {"raw_result": json.dumps({"success": True, "error": "rejected"})},
        )
        blocked = next(record for record in failed if record.claim == "patch.mutation_landed")

        self.assertEqual(blocked.value, "false")
        self.assertFalse(blocked.verified)


if __name__ == "__main__":
    unittest.main()
