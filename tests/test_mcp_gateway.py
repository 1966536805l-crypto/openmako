from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from quantagent.mcp_gateway import (
    gateway_call_tool,
    gateway_calls_path,
    gateway_health,
    gateway_state_path,
    load_gateway_calls,
    load_mcp_gateway,
    render_mcp_gateway,
    start_mcp_gateway,
    stop_mcp_gateway,
)
from quantagent.mcp_runtime import MCP_MANAGER, mcp_lease_registry_path
from quantagent.runtime_store import list_tool_invocations


class McpGatewayTest(unittest.TestCase):
    def tearDown(self) -> None:
        MCP_MANAGER.close_all()

    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent mcp gateway ")

    def write_fake_server(self, project: Path, *, error_on_call: bool = False) -> Path:
        script = project / "fake_mcp.py"
        script.write_text(
            textwrap.dedent(
                f"""
                import json, sys
                error_on_call = {str(error_on_call)}
                for line in sys.stdin:
                    request = json.loads(line)
                    method = request.get("method")
                    params = request.get("params") or {{}}
                    if method == "notifications/initialized":
                        continue
                    if method == "initialize":
                        result = {{"serverInfo": {{"name": "fake"}}}}
                    elif method == "tools/list":
                        result = {{"tools": [
                            {{"name": "echo", "description": "Echo text", "inputSchema": {{"type": "object"}}}},
                            {{"name": "danger_delete", "description": "Delete things", "inputSchema": {{"type": "object"}}}}
                        ]}}
                    elif method == "tools/call":
                        args = params.get("arguments") or {{}}
                        if error_on_call:
                            print(json.dumps({{"jsonrpc": "2.0", "id": request.get("id"), "error": {{"message": "token=sk-liveeeeeeeeeee password: hunter2"}}}}), flush=True)
                            continue
                        result = {{"content": [{{"type": "text", "text": args}}]}}
                    else:
                        result = {{}}
                    print(json.dumps({{"jsonrpc": "2.0", "id": request.get("id"), "result": result}}), flush=True)
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return script

    def write_config(self, project: Path, script: Path) -> None:
        config_dir = project / ".quantagent"
        config_dir.mkdir()
        (config_dir / "mcp_servers.json").write_text(
            json.dumps(
                {
                    "mcp_servers": {
                        "fake": {
                            "command": sys.executable,
                            "args": [str(script)],
                            "timeout": 3,
                            "permissions": {"echo": "allow", "danger_*": "deny"},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

    def test_gateway_start_persists_leases_tool_catalog_and_health(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = self.write_fake_server(project)
            self.write_config(project, script)

            state = start_mcp_gateway(project)
            loaded = load_mcp_gateway(project)
            health = gateway_health(project)
            rendered = render_mcp_gateway(state)

            self.assertEqual(state.status, "running")
            self.assertEqual(loaded.gateway_id, state.gateway_id)
            self.assertTrue(gateway_state_path(project).exists())
            self.assertTrue(mcp_lease_registry_path(project).exists())
            self.assertEqual([(tool.server, tool.name) for tool in state.tools], [("fake", "echo")])
            self.assertEqual(state.tools[0].policy_action, "allow")
            self.assertEqual(state.servers[0].status, "active")
            self.assertEqual(state.servers[0].tools, 1)
            self.assertEqual(state.servers[0].leases, 1)
            self.assertEqual(state.leases[0].server, "fake")
            self.assertEqual(state.leases[0].status, "active")
            self.assertTrue(health.ok, health.errors)
            self.assertEqual(health.tools, 1)
            self.assertIn("fake/echo", rendered)

    def test_gateway_call_records_result_and_runtime_invocation(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = self.write_fake_server(project)
            self.write_config(project, script)
            start_mcp_gateway(project)

            record = gateway_call_tool(project, "fake", "echo", {"text": "hello"})
            calls = load_gateway_calls(project)
            state = load_mcp_gateway(project)
            invocations = list_tool_invocations(project)

            self.assertTrue(record.ok, record.error)
            self.assertTrue(record.call_id.startswith("gw-call-"))
            self.assertTrue(record.invocation_id.startswith("mcp-inv-"))
            self.assertIn('"text": "hello"', record.result_preview)
            self.assertEqual(calls[-1].call_id, record.call_id)
            self.assertEqual(state.recent_calls[-1].call_id, record.call_id)
            self.assertTrue(gateway_calls_path(project).exists())
            self.assertEqual(invocations[0].tool, "mcp:fake:echo")
            self.assertEqual(invocations[0].status, "ok")

    def test_gateway_call_record_redacts_errors_and_argument_previews(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = self.write_fake_server(project, error_on_call=True)
            self.write_config(project, script)
            start_mcp_gateway(project)

            record = gateway_call_tool(project, "fake", "echo", {"password": "hunter2", "api_key": "sk-liveeeeeeeeeee"})
            raw_calls = gateway_calls_path(project).read_text(encoding="utf-8")
            rendered = render_mcp_gateway(load_mcp_gateway(project))

            self.assertFalse(record.ok)
            self.assertIn("[redacted]", record.error)
            self.assertIn("[redacted]", record.args_preview)
            self.assertNotIn("hunter2", record.error + record.args_preview + raw_calls + rendered)
            self.assertNotIn("sk-liveeeeeeeeeee", record.error + record.args_preview + raw_calls + rendered)

    def test_gateway_stop_marks_state_and_leases_stopped(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = self.write_fake_server(project)
            self.write_config(project, script)
            started = start_mcp_gateway(project)

            stopped = stop_mcp_gateway(project)

            self.assertEqual(stopped.gateway_id, started.gateway_id)
            self.assertEqual(stopped.status, "stopped")
            self.assertEqual(stopped.servers[0].status, "active")
            self.assertEqual(stopped.leases[0].status, "stopped")


if __name__ == "__main__":
    unittest.main()
