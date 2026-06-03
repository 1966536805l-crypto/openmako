from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from quantagent.cli import main
from quantagent.mcp_runtime import MCP_MANAGER


class Phase3SnapshotCliTest(unittest.TestCase):
    def run_cli(self, args: list[str]) -> tuple[int, str]:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["--no-trust-prompt", *args])
        return code, stdout.getvalue()

    def write_mcp_server(self, project: Path) -> Path:
        script = project / "fake_mcp.py"
        script.write_text(
            textwrap.dedent(
                """
                import json, sys
                for line in sys.stdin:
                    request = json.loads(line)
                    method = request.get("method")
                    if method == "notifications/initialized":
                        continue
                    if method == "initialize":
                        result = {"serverInfo": {"name": "fake"}}
                    elif method == "tools/list":
                        result = {"tools": [{"name": "echo", "description": "Echo", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}}]}
                    else:
                        result = {}
                    print(json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": result}), flush=True)
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return script

    def test_plugins_cli_writes_install_snapshot_and_detects_diff(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase3 plugin snapshot ") as tmp:
            project = Path(tmp)
            plugin = project / ".quantagent" / "plugins" / "demo"
            plugin.mkdir(parents=True)
            manifest = plugin / "quantagent.plugin.json"
            manifest.write_text('{"id":"demo","name":"Demo","version":"0.1.0"}\n', encoding="utf-8")
            snapshot_path = project / "plugin-snapshot.json"

            write_code, write_output = self.run_cli(["plugins", "--project", tmp, "--snapshot", "--write-snapshot", str(snapshot_path), "--json"])
            written = json.loads(write_output)
            manifest.write_text('{"id":"demo","name":"Demo","version":"0.2.0"}\n', encoding="utf-8")
            diff_code, diff_output = self.run_cli(["plugins", "--project", tmp, "--compare-snapshot", str(snapshot_path), "--json"])
            diff = json.loads(diff_output)
            snapshot_exists = snapshot_path.exists()

        self.assertEqual(write_code, 0)
        self.assertTrue(snapshot_exists)
        self.assertEqual(written["schema"], "quantagent.plugin_install_snapshot.v1")
        self.assertEqual(diff_code, 1)
        self.assertTrue(diff["has_drift"])
        self.assertEqual(diff["changed"], ["demo"])

    def test_mcp_cli_writes_schema_snapshot_and_detects_drift(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase3 mcp snapshot ") as tmp:
            project = Path(tmp)
            snapshot_path = project / "mcp-schema.json"
            write_code, write_output = self.run_cli(["mcp", "--project", tmp, "schema-snapshot", "--write", str(snapshot_path), "--json"])
            written = json.loads(write_output)

            script = self.write_mcp_server(project)
            config_dir = project / ".quantagent"
            config_dir.mkdir(exist_ok=True)
            (config_dir / "mcp_servers.json").write_text(
                json.dumps({"mcp_servers": {"fake": {"command": sys.executable, "args": [str(script)], "timeout": 3, "permissions": {"*": "allow"}}}}),
                encoding="utf-8",
            )
            try:
                diff_code, diff_output = self.run_cli(["mcp", "--project", tmp, "schema-snapshot", "--compare", str(snapshot_path), "--json"])
            finally:
                MCP_MANAGER.stop(project)
            diff = json.loads(diff_output)
            snapshot_exists = snapshot_path.exists()

        self.assertEqual(write_code, 0)
        self.assertTrue(snapshot_exists)
        self.assertEqual(written["schema"], "quantagent.mcp_schema_snapshot.v1")
        self.assertEqual(diff_code, 1)
        self.assertTrue(diff["has_drift"])
        self.assertEqual(diff["added"], ["fake/echo"])


if __name__ == "__main__":
    unittest.main()
