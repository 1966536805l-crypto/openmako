"""Test that AgentRunResult can be JSON serialized even with Path objects in observation data."""

import json
import tempfile
import unittest
from pathlib import Path

from quantagent.agent_loop_core import AgentLoopObservation, AgentLoopResult, _sanitize_for_json
from quantagent.agent_context_runtime import AgentRuntimeContext, RuntimeContextSection
from quantagent.mode_router import ModeRoute


class TestAgentResultJsonSerialization(unittest.TestCase):
    """Test JSON serialization of AgentRunResult with Path objects."""

    def test_sanitize_for_json_converts_path_to_str(self) -> None:
        """Test that _sanitize_for_json converts Path objects to strings."""
        # Test simple Path
        self.assertEqual(_sanitize_for_json(Path("/tmp/test")), "/tmp/test")

        # Test nested dict with Path
        data = {"file": Path("/tmp/test.py"), "count": 42}
        result = _sanitize_for_json(data)
        self.assertEqual(result["file"], "/tmp/test.py")
        self.assertEqual(result["count"], 42)

        # Test nested list with Path
        data_list = [Path("/tmp/a"), Path("/tmp/b"), "string"]
        result_list = _sanitize_for_json(data_list)
        self.assertEqual(result_list, ["/tmp/a", "/tmp/b", "string"])

        # Test deeply nested structure
        deep = {
            "level1": {
                "level2": {
                    "path": Path("/tmp/deep"),
                    "list": [Path("/tmp/item1"), {"nested_path": Path("/tmp/item2")}],
                }
            }
        }
        result_deep = _sanitize_for_json(deep)
        self.assertEqual(result_deep["level1"]["level2"]["path"], "/tmp/deep")
        self.assertEqual(result_deep["level1"]["level2"]["list"][0], "/tmp/item1")
        self.assertEqual(result_deep["level1"]["level2"]["list"][1]["nested_path"], "/tmp/item2")

    def test_agent_result_to_json_with_path_in_observation_data(self) -> None:
        """Test that AgentLoopResult.to_agent_result() handles Path objects in observation data."""
        # Create a minimal AgentLoopResult with Path in observation data
        route = ModeRoute(
            mode="build",
            profile="default",
            intent="build",
            confidence=1.0,
        )

        runtime_context = AgentRuntimeContext(
            task="test",
            mode="build",
            profile="default",
            route=route,
            mode_policy={},
            sections=(),
        )

        observation_with_path = AgentLoopObservation(
            step=1,
            name="test_step",
            kind="internal",
            ok=True,
            summary="test",
            mode="build",
            data={
                "file_path": Path("/tmp/test.py"),
                "nested": {"another_path": Path("/tmp/nested.py")},
                "count": 42,
            },
        )

        result = AgentLoopResult(
            task="test task",
            ok=True,
            summary="test summary",
            route=route,
            final_mode="build",
            plan=(),
            observations=(observation_with_path,),
            runtime_context=runtime_context,
            trajectory_path="/tmp/trajectory.jsonl",
            query_events_path="/tmp/events.jsonl",
        )

        # Convert to AgentRunResult and serialize to JSON
        agent_result = result.to_agent_result()
        json_str = agent_result.to_json()

        # Verify it's valid JSON
        parsed = json.loads(json_str)
        self.assertIsInstance(parsed, dict)

        # Verify Path objects were converted to strings
        tool_result_data = parsed["tool_results"][0]["data"]
        self.assertEqual(tool_result_data["file_path"], "/tmp/test.py")
        self.assertEqual(tool_result_data["nested"]["another_path"], "/tmp/nested.py")
        self.assertEqual(tool_result_data["count"], 42)


if __name__ == "__main__":
    unittest.main()
