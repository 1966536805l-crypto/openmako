from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quantagent.hermes_trajectory_format import (
    build_hermes_trajectory_entry,
    export_hermes_jsonl,
    export_hermes_jsonl_from_paths,
    read_hermes_jsonl,
)
from quantagent.hook_events import QueryEvent, append_query_event


class HermesTrajectoryFormatTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent hermes trajectory ")

    def test_successful_export_marks_completed_true(self) -> None:
        entry = build_hermes_trajectory_entry(
            [
                {"role": "system", "content": "system contract"},
                {"role": "user", "content": "run evidence check"},
                {"role": "assistant", "content": "done", "reasoning": "checked required files"},
            ],
            model="gpt-test",
            completed=True,
            timestamp="2026-05-26T00:00:00Z",
            metadata={"query_id": "qa-ok"},
        )

        self.assertTrue(entry["completed"])
        self.assertEqual(entry["model"], "gpt-test")
        self.assertEqual([item["from"] for item in entry["conversations"]], ["system", "human", "gpt"])
        self.assertIn("<think>\nchecked required files\n</think>", entry["conversations"][2]["value"])
        self.assertEqual(entry["metadata"]["query_id"], "qa-ok")

    def test_failed_query_events_mark_completed_false(self) -> None:
        events = [
            QueryEvent(kind="query_start", query_id="qa-fail", summary="start", data={"task": "blocked task"}),
            QueryEvent(kind="post_model", query_id="qa-fail", summary="auth failed", ok=False, data={"model": "gpt-test"}),
            QueryEvent(kind="stop_failure", query_id="qa-fail", summary="missing key", ok=False, data={"failure_class": "auth"}),
        ]

        entry = build_hermes_trajectory_entry(query_events=events)

        self.assertFalse(entry["completed"])
        self.assertEqual(entry["model"], "gpt-test")
        self.assertEqual(entry["metadata"]["query_id"], "qa-fail")
        self.assertEqual(entry["metadata"]["failure_class"], "auth")
        self.assertEqual(entry["conversations"][0], {"from": "human", "value": "blocked task"})

    def test_multi_tool_call_and_tool_response_are_xml_wrapped(self) -> None:
        entry = build_hermes_trajectory_entry(
            [
                {"role": "user", "content": "inspect repo"},
                {
                    "role": "assistant",
                    "content": "I will inspect.",
                    "tool_calls": [
                        {"id": "call-1", "function": {"name": "read_file", "arguments": '{"path":"a.py"}'}},
                        {"id": "call-2", "function": {"name": "run_tests", "arguments": {"target": "tests"}}},
                    ],
                },
                {"role": "tool", "tool_call_id": "call-1", "name": "read_file", "content": '{"lines":10}', "ok": True},
                {"role": "tool", "tool_call_id": "call-2", "name": "run_tests", "content": "passed", "ok": True},
            ],
            completed=True,
        )

        assistant_value = entry["conversations"][1]["value"]
        self.assertEqual(assistant_value.count("<tool_call>"), 2)
        self.assertIn('"name": "read_file"', assistant_value)
        self.assertIn('"path": "a.py"', assistant_value)
        self.assertEqual(entry["conversations"][2]["from"], "tool")
        self.assertEqual(entry["conversations"][3]["from"], "tool")
        self.assertIn("<tool_response>", entry["conversations"][2]["value"])
        self.assertIn('"lines": 10', entry["conversations"][2]["value"])
        self.assertIn('"content": "passed"', entry["conversations"][3]["value"])

    def test_empty_reasoning_does_not_create_think_block(self) -> None:
        entry = build_hermes_trajectory_entry(
            [{"role": "assistant", "content": "visible answer", "reasoning": "   "}],
            completed=True,
        )

        self.assertEqual(entry["conversations"][0]["value"], "visible answer")
        self.assertNotIn("<think>", entry["conversations"][0]["value"])

    def test_jsonl_roundtrip_preserves_entry(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "hermes.jsonl"
            entry = export_hermes_jsonl(
                path,
                messages=[{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}],
                model="gpt-test",
                completed=True,
                timestamp="2026-05-26T00:00:00Z",
                metadata={"source": "unit"},
            )

            loaded = read_hermes_jsonl(path)
            raw = json.loads(path.read_text(encoding="utf-8").strip())

            self.assertEqual(loaded, [entry])
            self.assertEqual(raw["conversations"][0]["from"], "human")
            self.assertTrue(raw["completed"])

    def test_path_export_reads_query_events_jsonl(self) -> None:
        with self.make_project() as tmp:
            query_path = Path(tmp) / "query_events.jsonl"
            out_path = Path(tmp) / "export.jsonl"
            append_query_event(query_path, QueryEvent(kind="query_start", query_id="qa-path", data={"task": "path task"}))
            append_query_event(query_path, QueryEvent(kind="pre_tool", query_id="qa-path", name="status", data={"args": {"verbose": True}}))
            append_query_event(query_path, QueryEvent(kind="post_tool", query_id="qa-path", name="status", summary="ok", ok=True))
            append_query_event(query_path, QueryEvent(kind="stop", query_id="qa-path", summary="done", ok=True))

            entry = export_hermes_jsonl_from_paths(out_path, query_events_path=query_path)

            self.assertTrue(entry["completed"])
            self.assertEqual(entry["metadata"]["query_id"], "qa-path")
            self.assertIn("<tool_call>", entry["conversations"][1]["value"])
            self.assertIn("<tool_response>", entry["conversations"][2]["value"])


if __name__ == "__main__":
    unittest.main()
