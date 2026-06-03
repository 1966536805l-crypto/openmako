from __future__ import annotations

import json
import os
import sys
import tempfile
import textwrap
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

from quantagent.approvals import approve, list_approvals
from quantagent.channel_gateway import handle_channel_message
from quantagent.control_plane_policy import ADMIN_SCOPE, READ_SCOPE, authorize_method
from quantagent.mcp_runtime import (
    MCP_MANAGER,
    apply_mcp_argument_guards,
    build_mcp_schema_snapshot,
    call_mcp_tool,
    call_mcp_tools_concurrently,
    cleanup_mcp_lease_registry,
    detect_mcp_schema_drift,
    list_mcp_catalog,
    load_mcp_servers,
    McpCatalog,
    McpTool,
    mcp_lease_dir,
    mcp_lease_registry_path,
    open_mcp_session,
    redact_mcp_error,
    resolve_mcp_permission,
    start_mcp_daemon_state,
    status_mcp_daemon_state,
    stop_mcp_daemon_state,
)
from quantagent.plugin_runtime import (
    build_plugin_install_snapshot,
    build_plugin_registry,
    check_plugin_compat,
    compare_plugin_install_snapshots,
    load_manifest,
    plugin_execution_decision,
    resolve_plugin_tool_permission,
)
from quantagent.query_runtime import load_query_events
from quantagent.runtime_store import list_tool_invocations
from quantagent.sessions import acquire_session_lock


class McpRuntimeTest(unittest.TestCase):
    def tearDown(self) -> None:
        MCP_MANAGER.close_all()

    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent mcp ")

    def write_fake_server(self, project: Path) -> Path:
        script = project / "fake_mcp.py"
        script.write_text(
            textwrap.dedent(
                """
                import json, sys
                for line in sys.stdin:
                    request = json.loads(line)
                    method = request.get("method")
                    params = request.get("params") or {}
                    if method == "notifications/initialized":
                        continue
                    if method == "initialize":
                        result = {"serverInfo": {"name": "fake"}}
                    elif method == "tools/list":
                        result = {"tools": [
                            {"name": "echo", "description": "Echo text", "inputSchema": {"type": "object"}},
                            {"name": "danger_delete", "description": "Delete things", "inputSchema": {"type": "object"}}
                        ]}
                    elif method == "tools/call":
                        args = params.get("arguments") or {}
                        result = {"content": [{"type": "text", "text": args}]}
                    else:
                        print(json.dumps({"id": request.get("id"), "error": {"message": "bad method"}}), flush=True)
                        continue
                    print(json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": result}), flush=True)
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return script

    def write_noisy_fake_server(self, project: Path) -> Path:
        script = project / "noisy_fake_mcp.py"
        script.write_text(
            textwrap.dedent(
                """
                import json, sys
                for line in sys.stdin:
                    request = json.loads(line)
                    method = request.get("method")
                    params = request.get("params") or {}
                    if method == "notifications/initialized":
                        continue
                    print(json.dumps({"jsonrpc": "2.0", "method": "notifications/progress", "params": {"message": "ignore me"}}), flush=True)
                    if method == "initialize":
                        result = {"serverInfo": {"name": "noisy"}}
                    elif method == "tools/list":
                        result = {"tools": [{"name": "echo", "description": "Echo text", "inputSchema": {"type": "object"}}]}
                    elif method == "tools/call":
                        args = params.get("arguments") or {}
                        result = {"content": [{"type": "text", "text": args.get("text", "")}]}
                    else:
                        print(json.dumps({"id": request.get("id"), "error": {"message": "bad method"}}), flush=True)
                        continue
                    print(json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": result}), flush=True)
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
            json.dumps({"mcp_servers": {"fake": {"command": sys.executable, "args": [str(script)], "timeout": 3, "permissions": {"*": "allow"}}}}),
            encoding="utf-8",
        )

    def test_loads_dict_config(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = self.write_fake_server(project)
            self.write_config(project, script)

            servers = load_mcp_servers(project)

            self.assertEqual(len(servers), 1)
            self.assertEqual(servers[0].name, "fake")
            self.assertEqual(servers[0].argv[0], sys.executable)

    def test_splits_string_command_with_quoted_args(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            config_dir = project / ".quantagent"
            config_dir.mkdir()
            (config_dir / "mcp_servers.json").write_text(
                json.dumps({"mcp_servers": {"fake": {"command": 'python3 "fake server.py"', "args": ["--stdio"]}}}),
                encoding="utf-8",
            )

            servers = load_mcp_servers(project)

            self.assertEqual(servers[0].command, "python3")
            self.assertEqual(servers[0].args, ["fake server.py", "--stdio"])

    def test_loads_http_transport_config(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            config_dir = project / ".quantagent"
            config_dir.mkdir()
            (config_dir / "mcp_servers.json").write_text(
                json.dumps({"mcp_servers": {"remote": {"transport": "http", "url": "http://127.0.0.1:9999/mcp", "headers": {"X-Test": "1"}, "auth_profile": "corp"}}}),
                encoding="utf-8",
            )

            servers = load_mcp_servers(project)

            self.assertEqual(servers[0].transport, "http")
            self.assertEqual(servers[0].url, "http://127.0.0.1:9999/mcp")
            self.assertEqual(servers[0].headers["X-Test"], "1")
            self.assertEqual(servers[0].auth_profile, "corp")

    def test_loads_list_config_for_backward_compatibility(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = self.write_fake_server(project)
            config_dir = project / ".quantagent"
            config_dir.mkdir()
            (config_dir / "mcp_servers.json").write_text(
                json.dumps({"servers": [{"name": "fake", "command": [sys.executable, str(script)], "enabled": True}]}),
                encoding="utf-8",
            )

            servers = load_mcp_servers(project)

            self.assertEqual(len(servers), 1)
            self.assertEqual(servers[0].args, [str(script)])

    def test_catalog_lists_fake_tools(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = self.write_fake_server(project)
            self.write_config(project, script)

            catalog = list_mcp_catalog(project)

            self.assertFalse(catalog.errors)
            self.assertEqual([(tool.server, tool.name) for tool in catalog.tools], [("fake", "echo"), ("fake", "danger_delete")])

    def test_call_records_invocation(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = self.write_fake_server(project)
            self.write_config(project, script)

            result = call_mcp_tool(project, "fake", "echo", {"text": "hello"})
            invocations = list_tool_invocations(project)

            self.assertTrue(result.ok, result.error)
            self.assertEqual(result.result["content"][0]["text"]["text"], "hello")
            self.assertEqual(invocations[0].tool, "mcp:fake:echo")
            self.assertEqual(invocations[0].status, "ok")

    def test_stdio_request_waits_for_matching_response_id_after_notification(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = self.write_noisy_fake_server(project)
            self.write_config(project, script)

            result = call_mcp_tool(project, "fake", "echo", {"text": "hello"})

            self.assertTrue(result.ok, result.error)
            self.assertEqual(result.result["content"][0]["text"], "hello")

    def test_permissions_hide_denied_tools_from_catalog(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = self.write_fake_server(project)
            config_dir = project / ".quantagent"
            config_dir.mkdir()
            (config_dir / "mcp_servers.json").write_text(
                json.dumps(
                    {
                        "mcp_servers": {
                            "fake": {
                                "command": sys.executable,
                                "args": [str(script)],
                                "permissions": {"echo": "allow", "danger_*": "deny"},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            catalog = list_mcp_catalog(project)

            self.assertEqual([tool.name for tool in catalog.tools], ["echo"])
            self.assertEqual(catalog.tools[0].policy_action, "allow")

    def test_permission_resolution_uses_last_matching_wildcard(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = self.write_fake_server(project)
            config_dir = project / ".quantagent"
            config_dir.mkdir()
            (config_dir / "mcp_servers.json").write_text(
                json.dumps({"mcp_servers": {"fake": {"command": sys.executable, "args": [str(script)], "permissions": {"*": "ask", "echo": "allow"}}}}),
                encoding="utf-8",
            )
            config = load_mcp_servers(project)[0]

            self.assertEqual(resolve_mcp_permission(config, "echo").action, "allow")
            self.assertEqual(resolve_mcp_permission(config, "unknown").action, "ask")

    def test_ask_permission_creates_resumable_approval(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = self.write_fake_server(project)
            config_dir = project / ".quantagent"
            config_dir.mkdir()
            (config_dir / "mcp_servers.json").write_text(
                json.dumps({"mcp_servers": {"fake": {"command": sys.executable, "args": [str(script)], "permissions": {"echo": "ask"}}}}),
                encoding="utf-8",
            )

            blocked = call_mcp_tool(project, "fake", "echo", {"text": "hello"})
            approval = list_approvals(project)[0]
            approve(project, approval.approval_id)
            resumed = call_mcp_tool(project, "fake", "echo", {"text": "hello"}, approval_id=approval.approval_id)

            self.assertFalse(blocked.ok)
            self.assertEqual(blocked.approval_id, approval.approval_id)
            self.assertTrue(resumed.ok, resumed.error)
            self.assertEqual(resumed.result["content"][0]["text"]["text"], "hello")

    def test_argument_guards_default_force_and_must_equal(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = self.write_fake_server(project)
            config_dir = project / ".quantagent"
            config_dir.mkdir()
            (config_dir / "mcp_servers.json").write_text(
                json.dumps(
                    {
                        "mcp_servers": {
                            "fake": {
                                "command": sys.executable,
                                "args": [str(script)],
                                "guards": {"echo": {"defaults": {"limit": 5}, "force": {"mode": "safe"}, "must_equal": {"mode": "safe"}}},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = load_mcp_servers(project)[0]

            guarded = apply_mcp_argument_guards(config, "echo", {"text": "hello"})

            self.assertEqual(guarded["limit"], 5)
            self.assertEqual(guarded["mode"], "safe")

    def test_argument_guard_denies_secret_fields_before_call(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = self.write_fake_server(project)
            config_dir = project / ".quantagent"
            config_dir.mkdir()
            (config_dir / "mcp_servers.json").write_text(
                json.dumps(
                    {
                        "mcp_servers": {
                            "fake": {
                                "command": sys.executable,
                                "args": [str(script)],
                                "permissions": {"echo": "allow"},
                                "guards": {"echo": {"deny_fields": ["password"]}},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = call_mcp_tool(project, "fake", "echo", {"password": "secret"})

            self.assertFalse(result.ok)
            self.assertIn("denied by guard", result.error)

    def test_call_unknown_server_fails_redacted(self) -> None:
        with self.make_project() as tmp:
            result = call_mcp_tool(Path(tmp), "missing", "echo", {"api_key": "sk-secretsecretsecret"})

            self.assertFalse(result.ok)
            self.assertIn("MCP server not found", result.error)

    def test_secret_redaction_patterns(self) -> None:
        text = "Bearer abc123 token=sk-liveeeeeeeeeee password: hunter2"

        redacted = redact_mcp_error(text)

        self.assertNotIn("abc123", redacted)
        self.assertNotIn("sk-liveeeeeeeeeee", redacted)
        self.assertNotIn("hunter2", redacted)

    def test_long_lived_session_reuses_server_for_initialize_list_and_call(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            counter = project / "counter.txt"
            script = project / "loop_mcp.py"
            script.write_text(
                textwrap.dedent(
                    f"""
                    import json, pathlib, sys
                    counter = pathlib.Path({str(counter)!r})
                    counter.write_text(str(int(counter.read_text() or '0') + 1) if counter.exists() else '1')
                    for line in sys.stdin:
                        request = json.loads(line)
                        method = request.get("method")
                        if method == "notifications/initialized":
                            continue
                        if method == "initialize":
                            result = {{"serverInfo": {{"name": "fake"}}}}
                        elif method == "tools/list":
                            result = {{"tools": [{{"name": "echo", "description": "Echo"}}]}}
                        elif method == "tools/call":
                            result = {{"content": [{{"type": "text", "text": request.get("params", {{}}).get("arguments", {{}})}}]}}
                        else:
                            print(json.dumps({{"id": request.get("id"), "error": {{"message": "bad method"}}}}), flush=True)
                            continue
                        print(json.dumps({{"jsonrpc": "2.0", "id": request.get("id"), "result": result}}), flush=True)
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            config_dir = project / ".quantagent"
            config_dir.mkdir()
            (config_dir / "mcp_servers.json").write_text(
                json.dumps({"mcp_servers": {"fake": {"command": sys.executable, "args": [str(script)], "timeout": 3, "idle_ttl": 0.01}}}),
                encoding="utf-8",
            )

            with open_mcp_session(project, "fake") as session:
                self.assertEqual(session.initialize()["result"]["serverInfo"]["name"], "fake")
                self.assertEqual(session.tools_list()[0]["name"], "echo")
                self.assertEqual(session.tools_call("echo", {"text": "hello"})["content"][0]["text"]["text"], "hello")
                self.assertEqual(counter.read_text(encoding="utf-8"), "1")
                session.last_used_at = 0
                self.assertTrue(session.cleanup_idle(now=1))

    def test_catalog_and_call_main_path_requires_initialized_session(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = project / "strict_init_mcp.py"
            script.write_text(
                textwrap.dedent(
                    """
                    import json, sys
                    initialized = False
                    for line in sys.stdin:
                        request = json.loads(line)
                        method = request.get("method")
                        if method == "initialize":
                            initialized = True
                            result = {"serverInfo": {"name": "strict"}}
                        elif method == "notifications/initialized":
                            continue
                        elif not initialized:
                            print(json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "error": {"message": "not initialized"}}), flush=True)
                            continue
                        elif method == "tools/list":
                            result = {"tools": [{"name": "echo", "description": "Echo"}]}
                        elif method == "tools/call":
                            result = {"content": [{"type": "text", "text": request.get("params", {}).get("arguments", {})}]}
                        else:
                            result = {}
                        print(json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": result}), flush=True)
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            config_dir = project / ".quantagent"
            config_dir.mkdir()
            (config_dir / "mcp_servers.json").write_text(
                json.dumps({"mcp_servers": {"strict": {"command": sys.executable, "args": [str(script)], "timeout": 3, "permissions": {"echo": "allow"}}}}),
                encoding="utf-8",
            )

            catalog = list_mcp_catalog(project)
            result = call_mcp_tool(project, "strict", "echo", {"text": "ok"})

            self.assertFalse(catalog.errors)
            self.assertEqual(catalog.tools[0].name, "echo")
            self.assertTrue(result.ok, result.error)
            self.assertEqual(result.result["content"][0]["text"]["text"], "ok")

    def test_manager_reuses_stdio_session_across_catalog_and_call(self) -> None:
        MCP_MANAGER.close_all()
        with self.make_project() as tmp:
            project = Path(tmp)
            counter = project / "counter.txt"
            script = self.write_fake_server(project)
            config_dir = project / ".quantagent"
            config_dir.mkdir()
            (config_dir / "mcp_servers.json").write_text(
                json.dumps({"mcp_servers": {"fake": {"command": sys.executable, "args": [str(script)], "timeout": 3, "idle_ttl": 60, "permissions": {"echo": "allow"}}}}),
                encoding="utf-8",
            )
            script.write_text(
                "import json, pathlib, sys\n"
                f"counter = pathlib.Path({str(counter)!r})\n"
                "counter.write_text(str(int(counter.read_text() or '0') + 1) if counter.exists() else '1')\n"
                + script.read_text(encoding="utf-8").split("for line in sys.stdin:", 1)[1].join(["for line in sys.stdin:", ""]),
                encoding="utf-8",
            )

            catalog = list_mcp_catalog(project)
            result = call_mcp_tool(project, "fake", "echo", {"text": "ok"})
            status = MCP_MANAGER.status()

            self.assertFalse(catalog.errors)
            self.assertTrue(result.ok, result.error)
            self.assertEqual(counter.read_text(encoding="utf-8"), "1")
            self.assertEqual(status.sessions, 1)
            lease = mcp_lease_dir(project) / "lease-fake.json"
            self.assertTrue(lease.exists())
        MCP_MANAGER.close_all()

    def test_daemon_state_registry_tracks_stdio_lease_status_and_cleanup(self) -> None:
        MCP_MANAGER.close_all()
        with self.make_project() as tmp:
            project = Path(tmp)
            script = self.write_fake_server(project)
            self.write_config(project, script)

            started = start_mcp_daemon_state(project, server="fake")
            lease = started.leases[0]
            registry = json.loads(mcp_lease_registry_path(project).read_text(encoding="utf-8"))

            self.assertIn("external MCP daemon", started.note)
            self.assertEqual(lease.server, "fake")
            self.assertEqual(lease.transport, "stdio")
            self.assertEqual(lease.status, "active")
            self.assertIsInstance(lease.pid, int)
            self.assertEqual(registry["leases"][0]["lease_id"], "lease-fake")

            stopped = stop_mcp_daemon_state(project, server="fake")
            removed = cleanup_mcp_lease_registry(project)
            current = status_mcp_daemon_state(project)

            self.assertEqual(stopped.leases[0].status, "stopped")
            self.assertEqual(removed, 1)
            self.assertEqual(current.leases, [])

    def test_daemon_state_records_http_lease_without_header_secrets(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            config_dir = project / ".quantagent"
            config_dir.mkdir()
            (config_dir / "mcp_servers.json").write_text(
                json.dumps(
                    {
                        "mcp_servers": {
                            "remote": {
                                "transport": "http",
                                "url": "http://127.0.0.1:9999/mcp?token=supersecret-token",
                                "headers": {
                                    "Authorization": "Bearer supersecret-bearer",
                                    "X-Api-Key": "sk-supersecretsecret",
                                },
                                "auth_profile": "corp",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            state = start_mcp_daemon_state(project, server="remote")
            registry_text = mcp_lease_registry_path(project).read_text(encoding="utf-8")
            lease = state.leases[0]

            self.assertEqual(lease.transport, "http")
            self.assertEqual(lease.status, "active")
            self.assertIn("token=[redacted]", lease.endpoint)
            self.assertEqual(lease.header_names, ["Authorization", "X-Api-Key"])
            self.assertNotIn("supersecret-token", registry_text)
            self.assertNotIn("supersecret-bearer", registry_text)
            self.assertNotIn("sk-supersecretsecret", registry_text)

    def test_http_transport_catalog_and_call(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(length).decode("utf-8"))
                method = request.get("method")
                if method == "initialize":
                    result = {"serverInfo": {"name": "http"}}
                elif method == "tools/list":
                    result = {"tools": [{"name": "echo", "description": "HTTP echo"}]}
                elif method == "tools/call":
                    result = {"content": [{"type": "text", "text": request.get("params", {}).get("arguments", {})}]}
                else:
                    result = {}
                body = json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": result}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.make_project() as tmp:
                project = Path(tmp)
                config_dir = project / ".quantagent"
                config_dir.mkdir()
                (config_dir / "mcp_servers.json").write_text(
                    json.dumps({"mcp_servers": {"remote": {"transport": "http", "url": f"http://127.0.0.1:{server.server_port}/mcp", "permissions": {"echo": "allow"}}}}),
                    encoding="utf-8",
                )

                catalog = list_mcp_catalog(project)
                result = call_mcp_tool(project, "remote", "echo", {"text": "hello"})

                self.assertFalse(catalog.errors)
                self.assertEqual(catalog.tools[0].name, "echo")
                self.assertTrue(result.ok, result.error)
                self.assertEqual(result.result["content"][0]["text"]["text"], "hello")
                leases = status_mcp_daemon_state(project, server="remote").leases
                self.assertEqual(leases[0].transport, "http")
                self.assertEqual(leases[0].status, "active")
                self.assertIn(str(server.server_port), leases[0].endpoint)
        finally:
            server.shutdown()
            server.server_close()

    def test_env_whitelist_limits_inherited_environment(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = project / "env_mcp.py"
            script.write_text(
                "import json, os, sys\n"
                "for line in sys.stdin:\n"
                "    request = json.loads(line)\n"
                "    method = request.get('method')\n"
                "    if method == 'notifications/initialized':\n"
                "        continue\n"
                "    if method == 'initialize':\n"
                "        result = {'serverInfo': {'name': 'env'}}\n"
                "    else:\n"
                "        result = {'tools': [{'name': os.environ.get('QA_VISIBLE', 'missing'), 'description': os.environ.get('QA_HIDDEN', 'hidden-missing')}]}\n"
                "    print(json.dumps({'jsonrpc': '2.0', 'id': request.get('id'), 'result': result}), flush=True)\n",
                encoding="utf-8",
            )
            config_dir = project / ".quantagent"
            config_dir.mkdir()
            (config_dir / "mcp_servers.json").write_text(
                json.dumps({"mcp_servers": {"fake": {"command": sys.executable, "args": [str(script)], "env": {"QA_VISIBLE": "yes"}, "env_whitelist": ["PATH"]}}}),
                encoding="utf-8",
            )

            catalog = list_mcp_catalog(project)

            self.assertEqual(catalog.tools[0].name, "yes")
            self.assertEqual(catalog.tools[0].description, "hidden-missing")

    def test_mcp_runtime_filters_explicit_secret_config_env(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = project / "env_mcp.py"
            script.write_text(
                "import json, os, sys\n"
                "for line in sys.stdin:\n"
                "    request = json.loads(line)\n"
                "    method = request.get('method')\n"
                "    if method == 'notifications/initialized':\n"
                "        continue\n"
                "    if method == 'initialize':\n"
                "        result = {'serverInfo': {'name': 'env'}}\n"
                "    else:\n"
                "        result = {'tools': [{'name': os.environ.get('OPENAI_API_KEY', 'missing'), 'description': os.environ.get('GITHUB_TOKEN', 'hidden-missing')}]}\n"
                "    print(json.dumps({'jsonrpc': '2.0', 'id': request.get('id'), 'result': result}), flush=True)\n",
                encoding="utf-8",
            )
            config_dir = project / ".quantagent"
            config_dir.mkdir()
            (config_dir / "mcp_servers.json").write_text(
                json.dumps({"mcp_servers": {"fake": {"command": sys.executable, "args": [str(script)], "env": {"OPENAI_API_KEY": "explicit-secret"}}}}),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"GITHUB_TOKEN": "parent-secret"}, clear=False):
                catalog = list_mcp_catalog(project)

            self.assertEqual(catalog.tools[0].name, "missing")
            self.assertEqual(catalog.tools[0].description, "hidden-missing")

    def test_mcp_runtime_filters_whitelisted_parent_secret_env(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = project / "env_mcp.py"
            script.write_text(
                "import json, os, sys\n"
                "for line in sys.stdin:\n"
                "    request = json.loads(line)\n"
                "    method = request.get('method')\n"
                "    if method == 'notifications/initialized':\n"
                "        continue\n"
                "    if method == 'initialize':\n"
                "        result = {'serverInfo': {'name': 'env'}}\n"
                "    else:\n"
                "        result = {'tools': [{'name': os.environ.get('OPENAI_API_KEY', 'missing'), 'description': os.environ.get('GITHUB_TOKEN', 'hidden-missing')}]}\n"
                "    print(json.dumps({'jsonrpc': '2.0', 'id': request.get('id'), 'result': result}), flush=True)\n",
                encoding="utf-8",
            )
            config_dir = project / ".quantagent"
            config_dir.mkdir()
            (config_dir / "mcp_servers.json").write_text(
                json.dumps({"mcp_servers": {"fake": {"command": sys.executable, "args": [str(script)], "env_whitelist": ["OPENAI_API_KEY"]}}}),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"OPENAI_API_KEY": "parent-secret", "GITHUB_TOKEN": "parent-hidden"}, clear=False):
                catalog = list_mcp_catalog(project)

            self.assertEqual(catalog.tools[0].name, "missing")
            self.assertEqual(catalog.tools[0].description, "hidden-missing")

    def test_mcp_runtime_rejects_null_byte_config_env_without_startup_failure(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = project / "env_mcp.py"
            script.write_text(
                "import json, os, sys\n"
                "for line in sys.stdin:\n"
                "    request = json.loads(line)\n"
                "    method = request.get('method')\n"
                "    if method == 'notifications/initialized':\n"
                "        continue\n"
                "    if method == 'initialize':\n"
                "        result = {'serverInfo': {'name': 'env'}}\n"
                "    else:\n"
                "        result = {'tools': [{'name': os.environ.get('SAFE_OK', 'missing'), 'description': os.environ.get('SAFE_NULL', 'null-missing')}]}\n"
                "    print(json.dumps({'jsonrpc': '2.0', 'id': request.get('id'), 'result': result}), flush=True)\n",
                encoding="utf-8",
            )
            config_dir = project / ".quantagent"
            config_dir.mkdir()
            (config_dir / "mcp_servers.json").write_text(
                json.dumps({"mcp_servers": {"fake": {"command": sys.executable, "args": [str(script)], "env": {"SAFE_OK": "ok", "SAFE_NULL": "abc\0def"}}}}),
                encoding="utf-8",
            )

            catalog = list_mcp_catalog(project)

            self.assertEqual(catalog.tools[0].name, "ok")
            self.assertEqual(catalog.tools[0].description, "null-missing")

    def test_phase3_channel_method_and_session_boundaries_fail_closed(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            executed: list[dict[str, object]] = []

            channel_result = handle_channel_message(
                project,
                channel="slack",
                sender=" ",
                text="/status",
                executor=lambda payload: executed.append(payload),
                allow_execute=True,
            )
            unknown_method = authorize_method("unknown.method", {ADMIN_SCOPE})
            read_method = authorize_method("config.get", {READ_SCOPE})
            held = acquire_session_lock(project, "sess-a", "owner-a", ttl_seconds=30)
            crossed = acquire_session_lock(project, "sess-a", "owner-b", ttl_seconds=30)

            self.assertFalse(channel_result.allowed)
            self.assertEqual(channel_result.status, "pairing_required")
            self.assertEqual(executed, [])
            self.assertFalse(unknown_method.allowed)
            self.assertEqual(unknown_method.reason, "unknown_method")
            self.assertTrue(read_method.allowed)
            self.assertIsNotNone(held)
            self.assertIsNone(crossed)

    def test_mcp_without_permissions_defaults_to_ask_and_blocks_call(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = self.write_fake_server(project)
            config_dir = project / ".quantagent"
            config_dir.mkdir()
            (config_dir / "mcp_servers.json").write_text(
                json.dumps({"mcp_servers": {"fake": {"command": sys.executable, "args": [str(script)], "timeout": 3}}}),
                encoding="utf-8",
            )

            catalog = list_mcp_catalog(project)
            result = call_mcp_tool(project, "fake", "echo", {"text": "hello"})

            self.assertEqual(catalog.tools[0].policy_action, "ask")
            self.assertFalse(result.ok)
            self.assertEqual(list_approvals(project)[0].tool, "mcp:fake:echo")

    def test_mcp_redacts_secret_args_query_runtime_and_invocation_preview(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = self.write_fake_server(project)
            self.write_config(project, script)
            secret_key = "sk-phase3secretsecret"

            result = call_mcp_tool(
                project,
                "fake",
                "echo",
                {
                    "api_key": secret_key,
                    "nested": {"password": "hunter2"},
                    "text": "Bearer secretbearer",
                },
            )
            invocation = list_tool_invocations(project)[0]
            event_text = "\n".join(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) for event in load_query_events(project))
            persisted = invocation.args_json + invocation.output_preview + event_text

            self.assertTrue(result.ok, result.error)
            self.assertNotIn(secret_key, persisted)
            self.assertNotIn("hunter2", persisted)
            self.assertNotIn("secretbearer", persisted)
            self.assertIn("[redacted]", persisted)

    def test_mcp_session_id_boundary_rejects_malformed_scope(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = self.write_fake_server(project)
            self.write_config(project, script)

            result = call_mcp_tool(project, "fake", "echo", {"text": "hello"}, session_id="../other")

            self.assertFalse(result.ok)
            self.assertIn("invalid MCP session id", result.error)

    def test_multi_mcp_concurrent_calls_isolate_failures_and_attribute_results(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = self.write_fake_server(project)
            config_dir = project / ".quantagent"
            config_dir.mkdir()
            server_cfg = {"command": sys.executable, "args": [str(script)], "timeout": 3, "permissions": {"echo": "allow"}}
            (config_dir / "mcp_servers.json").write_text(
                json.dumps({"mcp_servers": {"fake": server_cfg, "other": server_cfg}}),
                encoding="utf-8",
            )

            results = call_mcp_tools_concurrently(
                project,
                [
                    {"server": "fake", "tool": "echo", "arguments": {"text": "a"}, "session_id": "s1"},
                    {"server": "missing", "tool": "echo", "arguments": {"text": "b"}, "session_id": "s2"},
                    {"server": "other", "tool": "echo", "arguments": {"text": "c"}, "session_id": "s3"},
                ],
            )

            self.assertEqual([result.server for result in results], ["fake", "missing", "other"])
            self.assertTrue(results[0].ok, results[0].error)
            self.assertFalse(results[1].ok)
            self.assertIn("MCP server not found", results[1].error)
            self.assertTrue(results[2].ok, results[2].error)
            self.assertTrue(results[0].invocation_id.startswith("mcp-inv-"))
            self.assertTrue(results[2].invocation_id.startswith("mcp-inv-"))
            self.assertEqual(results[0].result["content"][0]["text"]["text"], "a")
            self.assertEqual(results[2].result["content"][0]["text"]["text"], "c")

    def test_mcp_schema_snapshot_detects_added_removed_and_changed_tools(self) -> None:
        before = build_mcp_schema_snapshot(
            McpCatalog(
                servers=[],
                tools=[
                    McpTool("fake", "echo", input_schema={"type": "object", "properties": {"text": {"type": "string"}}}),
                    McpTool("fake", "gone", input_schema={"type": "object"}),
                ],
            )
        )
        after = build_mcp_schema_snapshot(
            McpCatalog(
                servers=[],
                tools=[
                    McpTool("fake", "echo", input_schema={"type": "object", "properties": {"text": {"type": "integer"}}}),
                    McpTool("fake", "new", input_schema={"type": "object"}),
                ],
            )
        )

        drift = detect_mcp_schema_drift(before, after)

        self.assertTrue(drift.has_drift)
        self.assertEqual(drift.added, ("fake/new",))
        self.assertEqual(drift.removed, ("fake/gone",))
        self.assertEqual(drift.changed, ("fake/echo",))

    def test_plugin_permissions_snapshot_and_compat_fail_closed(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            plugin = project / ".quantagent" / "plugins" / "demo"
            plugin.mkdir(parents=True)
            manifest_path = plugin / "quantagent.plugin.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "id": "demo",
                        "name": "Demo",
                        "version": "0.1.0",
                        "tools": [{"name": "demo.read", "risk": "low"}, {"name": "demo.write", "risk": "high"}],
                        "tool_permissions": {"*": "allow", "demo.write": "deny"},
                        "compatibility": {"quantagent": ">=0.1.0"},
                    }
                ),
                encoding="utf-8",
            )
            incompatible = project / ".quantagent" / "plugins" / "badcompat"
            incompatible.mkdir(parents=True)
            (incompatible / "quantagent.plugin.json").write_text(
                '{"id":"badcompat","name":"Bad Compat","version":"0.1.0","compatibility":{"quantagent":">=99.0.0"}}\n',
                encoding="utf-8",
            )

            manifest = load_manifest(manifest_path, allowed_root=plugin.parent)
            registry_before = build_plugin_registry(project)
            snapshot_before = build_plugin_install_snapshot(registry_before)
            extra = project / ".quantagent" / "plugins" / "extra"
            extra.mkdir(parents=True)
            (extra / "quantagent.plugin.json").write_text('{"id":"extra","name":"Extra","version":"0.1.0"}\n', encoding="utf-8")
            manifest_path.write_text(
                json.dumps(
                    {
                        "id": "demo",
                        "name": "Demo",
                        "version": "0.2.0",
                        "tools": [{"name": "demo.read", "risk": "low"}, {"name": "demo.write", "risk": "high"}],
                        "tool_permissions": {"*": "allow", "demo.write": "deny"},
                        "compatibility": {"quantagent": ">=0.1.0"},
                    }
                ),
                encoding="utf-8",
            )
            registry_after = build_plugin_registry(project)
            snapshot_after = build_plugin_install_snapshot(registry_after)
            diff = compare_plugin_install_snapshots(snapshot_before, snapshot_after)

            self.assertEqual(resolve_plugin_tool_permission(manifest, "demo.missing").action, "deny")
            self.assertEqual(resolve_plugin_tool_permission(manifest, "demo.write").action, "deny")
            self.assertTrue(plugin_execution_decision(manifest, isolation="worktree", owner_approved=True, tool="demo.read").allowed)
            self.assertEqual(plugin_execution_decision(manifest, isolation="worktree", owner_approved=True, tool="demo.write").action, "deny")
            self.assertTrue(check_plugin_compat(manifest).allowed)
            self.assertTrue(any("does not satisfy" in diagnostic.message for diagnostic in registry_before.diagnostics))
            self.assertIn("extra", diff["added"])
            self.assertIn("demo", diff["changed"])


if __name__ == "__main__":
    unittest.main()
