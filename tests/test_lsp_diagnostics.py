from __future__ import annotations

import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from quantagent.lsp_diagnostics import (
    LspServerConfig,
    load_lsp_snapshot,
    lsp_cache_path,
    lsp_server_status,
    render_lsp_json,
    render_lsp_markdown,
    run_lsp_diagnostics,
)


FAKE_SERVER = r'''
from __future__ import annotations

import json
import os
import sys


def read_message():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        name, _, value = line.decode("ascii").partition(":")
        headers[name.lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if not length:
        return None
    return json.loads(sys.stdin.buffer.read(length).decode("utf-8"))


def send(payload):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    sys.stdout.buffer.flush()


events_path = os.environ["FAKE_LSP_EVENTS"]
while True:
    message = read_message()
    if message is None:
        break
    method = message.get("method")
    if "id" in message:
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": message["id"], "result": {"capabilities": {"textDocumentSync": 1}}})
        elif method == "shutdown":
            send({"jsonrpc": "2.0", "id": message["id"], "result": None})
        else:
            send({"jsonrpc": "2.0", "id": message["id"], "result": None})
    if method in ("textDocument/didOpen", "textDocument/didChange"):
        with open(events_path, "a", encoding="utf-8") as handle:
            handle.write(method + "\n")
        params = message.get("params") or {}
        text_document = params.get("textDocument") or {}
        uri = text_document.get("uri") or (params.get("textDocument") or {}).get("uri")
        send({
            "jsonrpc": "2.0",
            "method": "textDocument/publishDiagnostics",
            "params": {
                "uri": uri,
                "diagnostics": [{
                    "range": {
                        "start": {"line": 1, "character": 2},
                        "end": {"line": 1, "character": 7}
                    },
                    "severity": 1,
                    "source": "fake-lsp",
                    "code": "E_FAKE",
                    "message": "simulated diagnostic from fake server"
                }]
            }
        })
    if method == "exit":
        break
'''


class LspDiagnosticsTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent lsp ")

    def write_fake_server(self, project: Path) -> Path:
        server = project / "fake_lsp_server.py"
        server.write_text(textwrap.dedent(FAKE_SERVER), encoding="utf-8")
        return server

    def test_fake_lsp_collects_diagnostics_for_open_and_change_and_writes_cache(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            source = project / "sample.py"
            source.write_text("x = 1\nbad_call(\n", encoding="utf-8")
            events = project / "events.txt"
            server = self.write_fake_server(project)
            old_events = os.environ.get("FAKE_LSP_EVENTS")
            os.environ["FAKE_LSP_EVENTS"] = str(events)
            try:
                config = LspServerConfig(
                    name="fake",
                    command=(sys.executable, str(server)),
                    language_id="python",
                    file_extensions=(".py",),
                )

                snapshot = run_lsp_diagnostics(project, [source], config=config, timeout=3.0)
            finally:
                if old_events is None:
                    os.environ.pop("FAKE_LSP_EVENTS", None)
                else:
                    os.environ["FAKE_LSP_EVENTS"] = old_events

            self.assertTrue(snapshot.status.available)
            self.assertEqual(snapshot.server, "fake")
            self.assertGreaterEqual(len(snapshot.diagnostics), 1)
            diagnostic = snapshot.diagnostics[0]
            self.assertEqual(diagnostic.source, "fake-lsp")
            self.assertEqual(diagnostic.code, "E_FAKE")
            self.assertEqual(diagnostic.line, 2)
            self.assertEqual(diagnostic.character, 3)
            self.assertIn("simulated diagnostic", diagnostic.message)
            self.assertTrue(lsp_cache_path(project).exists())
            self.assertIn("textDocument/didOpen", events.read_text(encoding="utf-8"))
            self.assertIn("textDocument/didChange", events.read_text(encoding="utf-8"))

            markdown = render_lsp_markdown(snapshot)
            self.assertIn("# LSP Diagnostics", markdown)
            self.assertIn("fake-lsp E_FAKE", markdown)
            payload = json.loads(render_lsp_json(snapshot))
            self.assertEqual(payload["diagnostics"][0]["source"], "fake-lsp")

    def test_cache_load_round_trips_snapshot(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            source = project / "sample.py"
            source.write_text("x = 1\n", encoding="utf-8")
            events = project / "events.txt"
            server = self.write_fake_server(project)
            old_events = os.environ.get("FAKE_LSP_EVENTS")
            os.environ["FAKE_LSP_EVENTS"] = str(events)
            try:
                snapshot = run_lsp_diagnostics(
                    project,
                    [source],
                    config=LspServerConfig("fake", (sys.executable, str(server)), "python", (".py",)),
                    timeout=3.0,
                )
            finally:
                if old_events is None:
                    os.environ.pop("FAKE_LSP_EVENTS", None)
                else:
                    os.environ["FAKE_LSP_EVENTS"] = old_events

            loaded = load_lsp_snapshot(project)

            self.assertEqual(loaded.snapshot_id, snapshot.snapshot_id)
            self.assertEqual(loaded.status.name, "fake")
            self.assertEqual(loaded.diagnostics[0].message, snapshot.diagnostics[0].message)

    def test_missing_executable_returns_unavailable_status_without_crashing(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            config = LspServerConfig(
                name="missing",
                command=("definitely-not-a-real-lsp-executable-quantagent", "--stdio"),
                language_id="python",
            )

            status = lsp_server_status(config)
            snapshot = run_lsp_diagnostics(project, [], config=config)

            self.assertFalse(status.available)
            self.assertIn("missing executable", status.reason)
            self.assertFalse(snapshot.status.available)
            self.assertEqual(snapshot.diagnostics, ())
            self.assertTrue(lsp_cache_path(project).exists())


if __name__ == "__main__":
    unittest.main()
