from __future__ import annotations

import asyncio
import unittest

from quantagent.mcp_tool_manager import (
    MakoMcpTool,
    MakoMcpToolManager,
    MakoToolError,
    function_parameters_schema,
    validate_tool_name,
)
from quantagent.tool_manifest_v2 import ToolManifestV2, ToolPermissionSpec, ToolPromptSpec, validate_tool_manifests


def add(a: int, b: int = 1) -> int:
    """Add two integers."""
    return a + b


async def echo(text: str) -> str:
    return text


class McpToolManagerTest(unittest.TestCase):
    def test_validate_tool_name_matches_mcp_rules(self) -> None:
        self.assertTrue(validate_tool_name("desktop.find-click").is_valid)
        self.assertFalse(validate_tool_name("bad name").is_valid)
        self.assertFalse(validate_tool_name("").is_valid)
        self.assertFalse(validate_tool_name("x" * 129).is_valid)

    def test_function_parameters_schema_from_annotations(self) -> None:
        schema = function_parameters_schema(add)

        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["required"], ["a"])
        self.assertEqual(schema["properties"]["a"]["type"], "integer")
        self.assertEqual(schema["properties"]["b"]["default"], 1)
        self.assertFalse(schema["additionalProperties"])

    def test_tool_runs_with_argument_validation(self) -> None:
        tool = MakoMcpTool.from_function(add)

        self.assertEqual(asyncio.run(tool.run({"a": 2})), 3)
        with self.assertRaises(MakoToolError):
            asyncio.run(tool.run({}))
        with self.assertRaises(MakoToolError):
            asyncio.run(tool.run({"a": "2"}))

    def test_tool_manager_registers_and_calls_sync_and_async_tools(self) -> None:
        manager = MakoMcpToolManager(warn_on_duplicate_tools=False)
        first = manager.add_tool(add)
        duplicate = manager.add_tool(add)
        manager.add_tool(echo)

        self.assertIs(first, duplicate)
        self.assertEqual([tool.name for tool in manager.list_tools()], ["add", "echo"])
        self.assertEqual(asyncio.run(manager.call_tool("add", {"a": 4, "b": 5})), 9)
        self.assertEqual(asyncio.run(manager.call_tool("echo", {"text": "ok"})), "ok")
        with self.assertRaises(MakoToolError):
            asyncio.run(manager.call_tool("missing", {}))
        manager.remove_tool("echo")
        self.assertIsNone(manager.get_tool("echo"))

    def test_tool_manifest_uses_mcp_name_validation(self) -> None:
        bad = ToolManifestV2(
            name="bad tool",
            description="bad",
            source="test",
            prompt=ToolPromptSpec("bad"),
            permission=ToolPermissionSpec(mode="allow", risk="low"),
        )

        diagnostics = validate_tool_manifests([bad])

        self.assertTrue(any(item.level == "error" and "invalid characters" in item.message for item in diagnostics))


if __name__ == "__main__":
    unittest.main()
