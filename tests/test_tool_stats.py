from __future__ import annotations

import json
import unittest

from quantagent.hook_events import QueryEvent
from quantagent.runtime_store import ToolInvocationRecord
from quantagent.tool_stats import build_tool_stats
from quantagent.trajectory import TrajectoryEvent


class ToolStatsTest(unittest.TestCase):
    def test_zero_fill_known_tools(self) -> None:
        stats = build_tool_stats(known_tools=["status", "shell"])

        self.assertEqual(stats["tool_stats"], {"shell": {"count": 0, "failure": 0, "success": 0}, "status": {"count": 0, "failure": 0, "success": 0}})
        self.assertEqual(stats["tool_error_counts"], {"shell": 0, "status": 0})
        json.dumps(stats, sort_keys=True)

    def test_unknown_tool_is_retained(self) -> None:
        stats = build_tool_stats(
            query_events=[{"kind": "post_tool", "name": "custom.fetch", "ok": True}],
            known_tools=["status"],
        )

        self.assertEqual(stats["tool_stats"]["custom.fetch"], {"count": 1, "failure": 0, "success": 1})
        self.assertEqual(stats["tool_stats"]["status"], {"count": 0, "failure": 0, "success": 0})
        self.assertEqual(stats["tool_error_counts"], {"custom.fetch": 0, "status": 0})

    def test_failed_count_from_tool_invocations(self) -> None:
        invocations = [
            ToolInvocationRecord("inv-1", "shell", "ok", 1),
            ToolInvocationRecord("inv-2", "shell", "failed", 2, error_kind="returncode"),
            ToolInvocationRecord("inv-3", "status", "blocked", 3),
        ]

        stats = build_tool_stats(tool_invocations=invocations, known_tools=["shell", "status"])

        self.assertEqual(stats["tool_stats"]["shell"], {"count": 2, "failure": 1, "success": 1})
        self.assertEqual(stats["tool_stats"]["status"], {"count": 1, "failure": 1, "success": 0})
        self.assertEqual(stats["tool_error_counts"], {"shell": 1, "status": 1})

    def test_mixed_bool_status_and_error_fields(self) -> None:
        events = [
            QueryEvent(kind="pre_tool", query_id="qa", name="status", step=1),
            QueryEvent(kind="post_tool", query_id="qa", name="status", step=1, ok=True),
            QueryEvent(kind="post_tool", query_id="qa", name="shell", step=2, ok=False),
            {"kind": "post_tool", "name": "audit", "status": "success"},
            {"kind": "post_tool", "name": "review", "status": "timeout"},
            {"kind": "post_tool", "name": "context", "error": "boom"},
        ]

        stats = build_tool_stats(query_events=events, known_tools=["audit", "context", "review", "shell", "status"])

        self.assertEqual(stats["tool_stats"]["audit"], {"count": 1, "failure": 0, "success": 1})
        self.assertEqual(stats["tool_stats"]["context"], {"count": 1, "failure": 1, "success": 0})
        self.assertEqual(stats["tool_stats"]["review"], {"count": 1, "failure": 1, "success": 0})
        self.assertEqual(stats["tool_stats"]["shell"], {"count": 1, "failure": 1, "success": 0})
        self.assertEqual(stats["tool_stats"]["status"], {"count": 1, "failure": 0, "success": 1})
        self.assertEqual(stats["tool_error_counts"], {"audit": 0, "context": 1, "review": 1, "shell": 1, "status": 0})

    def test_empty_input(self) -> None:
        stats = build_tool_stats(trajectory=[], query_events=[], tool_invocations=[], known_tools=[])

        self.assertEqual(stats, {"tool_stats": {}, "tool_error_counts": {}})

    def test_trajectory_meta_tool_counts(self) -> None:
        trajectory = [
            TrajectoryEvent(kind="action", content="run", ok=True, meta={"tool": "file_read"}),
            TrajectoryEvent(kind="observation", content="denied", ok=False, meta={"tool_name": "file_write"}),
        ]

        stats = build_tool_stats(trajectory=trajectory, known_tools=["file_read", "file_write"])

        self.assertEqual(stats["tool_stats"]["file_read"], {"count": 1, "failure": 0, "success": 1})
        self.assertEqual(stats["tool_stats"]["file_write"], {"count": 1, "failure": 1, "success": 0})
        self.assertEqual(stats["tool_error_counts"], {"file_read": 0, "file_write": 1})


if __name__ == "__main__":
    unittest.main()
