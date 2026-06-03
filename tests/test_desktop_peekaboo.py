from __future__ import annotations

import json
import subprocess
import unittest
from subprocess import TimeoutExpired

from quantagent.desktop_peekaboo import PeekabooAdapter, extract_output_path, parse_json_output, shell_command


def completed(args: tuple[str, ...], stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, returncode, stdout, stderr)


class FakeRunner:
    def __init__(self, response: subprocess.CompletedProcess[str] | BaseException | None = None) -> None:
        self.response = response
        self.calls: list[tuple[tuple[str, ...], int | float]] = []

    def __call__(self, args, timeout):
        command = tuple(args)
        self.calls.append((command, timeout))
        if isinstance(self.response, BaseException):
            raise self.response
        if self.response is not None:
            return self.response
        return completed(command, json.dumps({"ok": True, "status": "ok", "summary": "done"}))


class PeekabooAdapterTest(unittest.TestCase):
    def test_permissions_status_uses_injected_runner_and_json(self) -> None:
        runner = FakeRunner(completed(("peekaboo",), '{"ok":true,"status":"granted","data":{"screen_recording":true}}'))
        adapter = PeekabooAdapter(runner=runner, default_timeout=7)

        result = adapter.permissions_status(all_sources=True)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "granted")
        self.assertEqual(runner.calls[0], (("peekaboo", "permissions", "status", "--all-sources", "--json"), 7))
        self.assertEqual(result.data["json"]["data"]["screen_recording"], True)

    def test_image_and_see_parse_nested_paths(self) -> None:
        runner = FakeRunner(completed(("peekaboo",), '{"data":{"saved_files":[{"path":"/tmp/front.png"}],"snapshot_id":"snap-1"},"status":"ok"}'))
        adapter = PeekabooAdapter(runner=runner)

        image = adapter.image(path="/tmp/front.png", mode="screen", screen_index=0)
        see = adapter.see(app="Safari", path="/tmp/see.png", annotate=True)
        tokenize = adapter.tokenize(app="Safari")

        self.assertEqual(image.path, "/tmp/front.png")
        self.assertEqual(see.path, "/tmp/front.png")
        self.assertEqual(tokenize.action, "tokenize")
        self.assertEqual(runner.calls[0][0], ("peekaboo", "image", "--mode", "screen", "--screen-index", "0", "--path", "/tmp/front.png", "--json"))
        self.assertEqual(runner.calls[1][0], ("peekaboo", "see", "--app", "Safari", "--annotate", "--path", "/tmp/see.png", "--json"))

    def test_actions_build_current_peekaboo_commands(self) -> None:
        runner = FakeRunner()
        adapter = PeekabooAdapter(runner=runner)

        adapter.click(x=10, y=20, app="Safari", global_coords=True)
        adapter.click(element_id="B12", snapshot="snap-1", wait_for_ms=8000)
        adapter.type_text("hello", clear=True, tab=2, return_key=True)
        adapter.press(["tab", "return"], count=2, delay_ms=50)
        adapter.hotkey(["cmd", "shift", "t"], app="Safari", hold_duration_ms=75)

        commands = [call[0] for call in runner.calls]
        self.assertEqual(commands[0], ("peekaboo", "click", "--coords", "10,20", "--app", "Safari", "--global-coords", "--json"))
        self.assertEqual(commands[1], ("peekaboo", "click", "--on", "B12", "--snapshot", "snap-1", "--wait-for", "8000", "--json"))
        self.assertEqual(commands[2], ("peekaboo", "type", "hello", "--clear", "--return", "--tab", "2", "--json"))
        self.assertEqual(commands[3], ("peekaboo", "press", "tab", "return", "--count", "2", "--delay", "50", "--json"))
        self.assertEqual(commands[4], ("peekaboo", "hotkey", "--keys", "cmd,shift,t", "--app", "Safari", "--hold-duration", "75", "--json"))

    def test_nonzero_exit_is_structured_result_not_exception(self) -> None:
        runner = FakeRunner(completed(("peekaboo",), stdout='{"error":"permission denied","status":"denied"}', stderr="TCC denied", returncode=2))
        result = PeekabooAdapter(runner=runner).click(query="Allow")

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.summary, "permission denied")
        self.assertEqual(result.data["stderr"], "TCC denied")

    def test_runner_exceptions_are_structured_results(self) -> None:
        missing = PeekabooAdapter(runner=FakeRunner(FileNotFoundError("missing"))).see()
        timed_out = PeekabooAdapter(runner=FakeRunner(TimeoutExpired(cmd="peekaboo", timeout=3))).image()
        os_error = PeekabooAdapter(runner=FakeRunner(OSError("boom"))).press("escape")

        self.assertFalse(missing.ok)
        self.assertEqual(missing.status, "not_found")
        self.assertFalse(timed_out.ok)
        self.assertEqual(timed_out.status, "timeout")
        self.assertFalse(os_error.ok)
        self.assertEqual(os_error.status, "runner_error")

    def test_bad_json_keeps_success_and_path_fallback(self) -> None:
        runner = FakeRunner(completed(("peekaboo",), "Saved screenshot to /tmp/out.png\n{bad json", returncode=0))
        result = PeekabooAdapter(runner=runner).image()

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "ok")
        self.assertIn("json_error", result.data)
        self.assertEqual(result.path, "/tmp/out.png")

    def test_json_and_path_helpers_accept_wrapped_output_and_ui_map(self) -> None:
        parsed, error = parse_json_output('log prefix\n{"data":{"ui_map":"~/.peekaboo/snapshots/1/snapshot.json"}}\nlog suffix')

        self.assertFalse(error)
        self.assertEqual(extract_output_path(parsed), "~/.peekaboo/snapshots/1/snapshot.json")
        self.assertEqual(extract_output_path(None, 'wrote "./artifact/see.png"'), "./artifact/see.png")
        self.assertEqual(shell_command(["peekaboo", "type", "hello world"]), "peekaboo type 'hello world'")


if __name__ == "__main__":
    unittest.main()
