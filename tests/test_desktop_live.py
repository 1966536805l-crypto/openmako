from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from quantagent.approvals import ensure_approval_for_policy
from quantagent.cli import main
from quantagent.desktop_control import DesktopResult, desktop_dir
from quantagent.desktop_live import build_desktop_live_state, render_desktop_live_html, render_desktop_live_json, render_desktop_live_state, write_desktop_live_html
from quantagent.runtime_store import record_tool_invocation
from quantagent.tool_execution import execute_tool


class DesktopLiveTest(unittest.TestCase):
    def test_live_state_reads_artifacts_approvals_and_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            directory = desktop_dir(project)
            directory.mkdir(parents=True)
            (directory / "som_demo.json").write_text(
                json.dumps(
                    {
                        "image_path": "shot.png",
                        "targets": [{"mark_id": "M001", "source": "ocr", "label": "Run"}],
                        "errors": [],
                    }
                ),
                encoding="utf-8",
            )
            (directory / "run_demo.json").write_text(
                json.dumps({"status": "preview", "ok": True, "results": []}),
                encoding="utf-8",
            )
            approval = ensure_approval_for_policy(
                project,
                tool="desktop.click",
                args={"x": 10, "y": 20},
                policy={"action": "ask", "profile": "project", "tool": "desktop.click"},
                reason="screen click",
            )
            record_tool_invocation(
                project,
                invocation_id="inv-desktop",
                tool="desktop.som",
                status="ok",
                args={},
                policy={"action": "allow"},
                approval_id=None,
                summary="SoM created",
                duration_ms=7,
            )

            state = build_desktop_live_state(project, limit=5)
            rendered = render_desktop_live_state(state, color=False)

            self.assertEqual(state.status, "blocked")
            self.assertEqual(state.approvals[0].approval_id, approval.approval_id)
            self.assertTrue(any(item.kind == "som" for item in state.artifacts))
            self.assertEqual(state.tools[0].tool, "desktop.som")
            self.assertIn("Mako Desktop Live", rendered)
            self.assertIn("SoM targets=1", rendered)
            self.assertIn("Pending Approvals", rendered)

    def test_live_json_and_cli_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            payload = json.loads(render_desktop_live_json(build_desktop_live_state(project)))
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(["--no-trust-prompt", "desktop", "--project", str(project), "live", "--once", "--no-color"])

            self.assertEqual(payload["status"], "idle")
            self.assertEqual(rc, 0)
            self.assertIn("Operator Commands", stdout.getvalue())

    def test_live_html_renderer_and_cli_export_static_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            state = build_desktop_live_state(project)
            html = render_desktop_live_html(state)
            out_path = write_desktop_live_html(state)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(["--no-trust-prompt", "desktop", "--project", str(project), "live", "--html-out", "panel.html"])
            cli_path = Path(stdout.getvalue().strip())

            self.assertIn("<!doctype html>", html)
            self.assertIn("Desktop Live", html)
            self.assertTrue(out_path.exists())
            self.assertEqual(rc, 0)
            self.assertTrue(cli_path.exists())
            self.assertIn("Desktop Live", cli_path.read_text(encoding="utf-8"))

    def test_live_probe_reports_permissions_and_network_without_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            front = DesktopResult("frontmost", True, "Terminal")
            window = DesktopResult("window", False, "System Events got an error: assistive access is not allowed (-25211)")
            shot = DesktopResult(
                "screenshot",
                False,
                "could not create image from display; probable_cause=macOS Screen Recording permission is missing",
                {"diagnostics": {"display_available": True}},
            )
            ax = DesktopResult("ax", False, "AX snapshot failed: assistive access is not allowed")
            with patch("quantagent.desktop_live.frontmost_app", return_value=front), patch(
                "quantagent.desktop_live.front_window",
                return_value=window,
            ), patch("quantagent.desktop_live.screenshot", return_value=shot), patch("quantagent.desktop_live.ax_snapshot", return_value=ax), patch(
                "quantagent.desktop_live.urlopen",
                side_effect=URLError("offline"),
            ):
                state = build_desktop_live_state(project, probe=True, probe_network_url="https://example.invalid")

        statuses = {probe.name: probe.status for probe in state.readiness}
        self.assertEqual(state.status, "blocked")
        self.assertEqual(statuses["frontmost_app"], "ok")
        self.assertEqual(statuses["front_window"], "permission_required")
        self.assertEqual(statuses["screenshot_permission"], "permission_required")
        self.assertEqual(statuses["accessibility_snapshot"], "permission_required")
        self.assertEqual(statuses["network"], "network_failed")

    def test_live_probe_cli_json_exposes_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            with patch("quantagent.desktop_live.frontmost_app", return_value=DesktopResult("frontmost", True, "Terminal")), patch(
                "quantagent.desktop_live.front_window",
                return_value=DesktopResult("window", True, "Terminal|Window|0,0|100,100"),
            ), patch("quantagent.desktop_live.screenshot", return_value=DesktopResult("screenshot", True, "screenshot ok")), patch(
                "quantagent.desktop_live.ax_snapshot",
                return_value=DesktopResult("ax", True, "ax ok", {"elements": 1}),
            ):
                with contextlib.redirect_stdout(stdout):
                    rc = main(["--no-trust-prompt", "desktop", "--project", tmp, "--json", "live", "--probe", "--once"])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(rc, 0)
        self.assertEqual(payload["status"], "active")
        self.assertEqual({item["name"] for item in payload["readiness"]}, {"frontmost_app", "front_window", "screenshot_permission", "accessibility_snapshot"})

    def test_agent_tool_executor_can_read_live_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = execute_tool(Path(tmp), "desktop.live", {"limit": 3})

            self.assertTrue(result.ok)
            self.assertEqual(result.name, "desktop.live")
            self.assertIn(result.data["status"], {"idle", "active", "warn", "blocked"})


if __name__ == "__main__":
    unittest.main()
