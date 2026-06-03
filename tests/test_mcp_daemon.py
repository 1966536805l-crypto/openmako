from __future__ import annotations

import json
import socket
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path

from quantagent.mcp_daemon import (
    McpDaemon,
    daemon_call,
    daemon_catalog,
    load_mcp_daemon_calls,
    load_mcp_daemon_state,
    mcp_daemon_catalog_cache_path,
    mcp_daemon_pid_path,
    mcp_daemon_socket_path,
    mcp_daemon_state_path,
    recover_mcp_daemon,
    request_mcp_daemon,
    restart_mcp_daemon,
    start_mcp_daemon,
    status_mcp_daemon,
    stop_mcp_daemon,
)
from quantagent.mcp_runtime import MCP_MANAGER


class McpDaemonTest(unittest.TestCase):
    def tearDown(self) -> None:
        MCP_MANAGER.close_all()

    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent mcp daemon ")

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
                            {{"name": "echo", "description": "Echo text", "inputSchema": {{"type": "object"}}}}
                        ]}}
                    elif method == "tools/call":
                        if error_on_call:
                            print(json.dumps({{"jsonrpc": "2.0", "id": request.get("id"), "error": {{"message": "api_key=sk-liveeeeeeeeeee password: hunter2"}}}}), flush=True)
                            continue
                        args = params.get("arguments") or {{}}
                        result = {{"content": [{{"type": "text", "text": args}}]}}
                    else:
                        print(json.dumps({{"jsonrpc": "2.0", "id": request.get("id"), "error": {{"message": "bad method"}}}}), flush=True)
                        continue
                    print(json.dumps({{"jsonrpc": "2.0", "id": request.get("id"), "result": result}}), flush=True)
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return script

    def write_config(self, project: Path, script: Path) -> None:
        config_dir = project / ".quantagent"
        config_dir.mkdir(exist_ok=True)
        (config_dir / "mcp_servers.json").write_text(
            json.dumps(
                {
                    "mcp_servers": {
                        "fake": {
                            "command": sys.executable,
                            "args": [str(script)],
                            "timeout": 3,
                            "permissions": {"echo": "allow"},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

    def test_start_status_stop_restart_and_recover_persist_state_files(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = self.write_fake_server(project)
            self.write_config(project, script)

            started = start_mcp_daemon(project)
            status = status_mcp_daemon(project)
            restarted = restart_mcp_daemon(project)
            recovered = recover_mcp_daemon(project)
            stopped = stop_mcp_daemon(project)
            loaded = load_mcp_daemon_state(project)

            self.assertEqual(started.status, "running")
            self.assertIsInstance(started.pid, int)
            self.assertEqual(status.status, "running")
            self.assertEqual(restarted.daemon_id, started.daemon_id)
            self.assertEqual(recovered.status, "running")
            self.assertTrue(mcp_daemon_state_path(project).exists())
            self.assertTrue(mcp_daemon_pid_path(project).exists() is False)
            self.assertEqual(stopped.status, "stopped")
            self.assertIsNone(stopped.pid)
            self.assertEqual(loaded.status, "stopped")

    def test_socket_request_status_and_shutdown(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = self.write_fake_server(project)
            self.write_config(project, script)
            daemon = McpDaemon(project)
            thread = threading.Thread(target=daemon.serve_forever, daemon=True)
            thread.start()
            self.wait_for_socket(mcp_daemon_socket_path(project))

            response = request_mcp_daemon(project, "status")
            shutdown = request_mcp_daemon(project, "shutdown")
            thread.join(timeout=3)

            self.assertTrue(response.ok, response.error)
            self.assertEqual(response.result["status"], "running")
            self.assertTrue(shutdown.ok, shutdown.error)
            self.assertEqual(shutdown.result["status"], "stopped")
            self.assertFalse(thread.is_alive())

    def test_catalog_cache_persists_and_recover_reads_cached_state(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = self.write_fake_server(project)
            self.write_config(project, script)
            start_mcp_daemon(project)

            catalog = daemon_catalog(project, refresh=True)
            cached = daemon_catalog(project)
            recovered = recover_mcp_daemon(project)
            loaded = json.loads(mcp_daemon_catalog_cache_path(project).read_text(encoding="utf-8"))

            self.assertEqual([(tool["server"], tool["name"]) for tool in catalog["tools"]], [("fake", "echo")])
            self.assertEqual(cached["cached_at_ms"], catalog["cached_at_ms"])
            self.assertEqual(loaded["tools"][0]["name"], "echo")
            self.assertEqual(recovered.catalog_tools, 1)
            self.assertGreater(recovered.catalog_cached_at_ms, 0)

    def test_call_records_and_secret_redaction(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = self.write_fake_server(project, error_on_call=True)
            self.write_config(project, script)
            start_mcp_daemon(project)

            result = daemon_call(project, server="fake", tool="echo", arguments={"password": "hunter2", "api_key": "sk-liveeeeeeeeeee"})
            calls = load_mcp_daemon_calls(project)
            raw = Path(status_mcp_daemon(project).calls_file).read_text(encoding="utf-8")

            self.assertFalse(result["ok"])
            self.assertIn("[redacted]", result["error"])
            self.assertEqual(len(calls), 1)
            self.assertFalse(calls[0].ok)
            self.assertIn("[redacted]", calls[0].error + calls[0].args_preview)
            self.assertNotIn("hunter2", result["error"] + calls[0].error + calls[0].args_preview + raw)
            self.assertNotIn("sk-liveeeeeeeeeee", result["error"] + calls[0].error + calls[0].args_preview + raw)

    def wait_for_socket(self, path: Path) -> None:
        deadline = time.time() + 3
        while time.time() < deadline:
            if path.exists():
                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    client.connect(str(path))
                    client.close()
                    return
                except OSError:
                    client.close()
            time.sleep(0.02)
        self.fail(f"socket did not start: {path}")


if __name__ == "__main__":
    unittest.main()
