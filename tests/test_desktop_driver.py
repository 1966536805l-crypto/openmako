from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from quantagent.desktop_control import DesktopResult
from quantagent.desktop_driver import (
    DesktopDriverUnavailable,
    PeekabooDesktopDriver,
    get_desktop_driver,
    resolve_desktop_driver,
)


class DesktopDriverTest(unittest.TestCase):
    def test_builtin_selection_does_not_probe_external_runner(self) -> None:
        calls: list[list[str]] = []

        def runner(args: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, "unused", "")

        resolution = resolve_desktop_driver("builtin", runner=runner)

        self.assertTrue(resolution.ok)
        self.assertEqual(resolution.name, "builtin")
        self.assertEqual(calls, [])
        self.assertEqual(resolution.to_result().data["status"], "available")

    def test_peekaboo_selection_fails_closed_when_executable_is_missing(self) -> None:
        def missing_runner(args: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
            raise FileNotFoundError(args[0])

        resolution = resolve_desktop_driver("peekaboo", runner=missing_runner)

        self.assertFalse(resolution.ok)
        self.assertIsNone(resolution.driver)
        self.assertIsNotNone(resolution.diagnostic)
        self.assertEqual(resolution.diagnostic.status, "executable_not_found")
        self.assertIn("peekaboo driver unavailable", resolution.diagnostic.summary)
        self.assertEqual(resolution.to_result().data["data"]["executable"], "peekaboo")

    def test_peekaboo_selection_exposes_probe_diagnostics_on_nonzero_exit(self) -> None:
        def failing_runner(args: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args, 2, "", "permission denied")

        resolution = resolve_desktop_driver("peekaboo", runner=failing_runner)

        self.assertFalse(resolution.ok)
        self.assertEqual(resolution.diagnostic.status, "probe_failed")
        self.assertIn("permission denied", resolution.diagnostic.summary)
        self.assertEqual(resolution.diagnostic.data["returncode"], 2)

    def test_peekaboo_selection_accepts_injected_runner_success(self) -> None:
        calls: list[tuple[list[str], float]] = []

        def runner(args: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
            calls.append((args, timeout))
            return subprocess.CompletedProcess(args, 0, "peekaboo 1.2.3", "")

        resolution = resolve_desktop_driver("peekaboo", runner=runner)

        self.assertTrue(resolution.ok)
        self.assertIsNotNone(resolution.driver)
        self.assertEqual(resolution.name, "peekaboo")
        self.assertEqual(calls, [(["peekaboo", "--version"], 5.0)])
        self.assertEqual(resolution.diagnostic.data["stdout"], "peekaboo 1.2.3")

    def test_peekaboo_driver_execute_uses_adapter_without_custom_action_runner(self) -> None:
        calls: list[tuple[tuple[str, ...], float]] = []

        def runner(args, *, timeout: float) -> subprocess.CompletedProcess[str]:
            command = tuple(args)
            calls.append((command, timeout))
            return subprocess.CompletedProcess(command, 0, '{"status":"ok","summary":"clicked"}', "")

        driver = PeekabooDesktopDriver(runner=runner)

        with tempfile.TemporaryDirectory() as tmp:
            result = driver.execute(Path(tmp), "click", {"x": 1, "y": 2})

        self.assertTrue(result.ok)
        self.assertEqual(result.summary, "clicked")
        self.assertEqual(result.data["driver"], "peekaboo")
        self.assertEqual(calls[0], (("peekaboo", "--version"), 5.0))
        self.assertEqual(calls[1], (("peekaboo", "click", "--coords", "1,2", "--global-coords", "--json"), 20.0))

    def test_peekaboo_driver_screenshot_generates_project_path(self) -> None:
        calls: list[tuple[str, ...]] = []

        def runner(args, *, timeout: float) -> subprocess.CompletedProcess[str]:
            command = tuple(args)
            calls.append(command)
            if command == ("peekaboo", "--version"):
                return subprocess.CompletedProcess(command, 0, "peekaboo 1.2.3", "")
            return subprocess.CompletedProcess(command, 0, '{"status":"ok","path":"/tmp/shot.png"}', "")

        driver = PeekabooDesktopDriver(runner=runner)

        with tempfile.TemporaryDirectory() as tmp:
            result = driver.execute(Path(tmp), "screenshot", {"name": "shot.png"})

        self.assertTrue(result.ok)
        self.assertEqual(result.data["path"], "/tmp/shot.png")
        self.assertTrue(str(Path(tmp) / ".quantagent" / "desktop" / "shot.png") in calls[1])

    def test_peekaboo_driver_execute_fails_closed_when_probe_fails(self) -> None:
        def runner(args: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
            raise FileNotFoundError(args[0])

        driver = PeekabooDesktopDriver(runner=runner)

        with tempfile.TemporaryDirectory() as tmp:
            result = driver.execute(Path(tmp), "click", {"x": 1, "y": 2})

        self.assertFalse(result.ok)
        self.assertEqual(result.data["driver"], "peekaboo")
        self.assertEqual(result.data["diagnostic"]["status"], "executable_not_found")

    def test_peekaboo_action_runner_is_injected_for_tests(self) -> None:
        def probe_runner(args: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args, 0, "ok", "")

        def action_runner(project: Path, action: str, args: dict[str, object]) -> DesktopResult:
            return DesktopResult(action, True, f"{action} via injected runner", {"project": str(project), "args": args})

        driver = PeekabooDesktopDriver(runner=probe_runner, action_runner=action_runner)

        with tempfile.TemporaryDirectory() as tmp:
            result = driver.execute(Path(tmp), "click", {"x": 1, "y": 2})

        self.assertTrue(result.ok)
        self.assertEqual(result.summary, "click via injected runner")
        self.assertEqual(result.data["args"], {"x": 1, "y": 2})

    def test_unknown_driver_and_get_driver_error_are_diagnostic(self) -> None:
        resolution = resolve_desktop_driver("bogus")

        self.assertFalse(resolution.ok)
        self.assertEqual(resolution.diagnostic.status, "unknown_driver")
        with self.assertRaises(DesktopDriverUnavailable) as raised:
            get_desktop_driver("bogus")
        self.assertEqual(raised.exception.diagnostic.status, "unknown_driver")


if __name__ == "__main__":
    unittest.main()
