from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import json
import os
import shlex
import subprocess
import time
from html import escape
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Sequence

from .branding import PRODUCT_NAME


@dataclass
class DesktopResult:
    action: str
    ok: bool
    summary: str
    data: dict[str, object] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


SWIFT_HELPER = r'''
import Foundation
import ApplicationServices

func fail(_ message: String) -> Never {
    fputs(message + "\n", stderr)
    exit(2)
}

let args = CommandLine.arguments
if args.count < 2 {
    fail("usage: quantagent_cgevent click X Y | move X Y")
}

func number(_ index: Int) -> Double {
    if args.count <= index { fail("missing numeric argument") }
    guard let value = Double(args[index]) else { fail("invalid numeric argument: \(args[index])") }
    return value
}

func mouse(_ type: CGEventType, _ x: Double, _ y: Double) {
    let point = CGPoint(x: x, y: y)
    guard let event = CGEvent(mouseEventSource: nil, mouseType: type, mouseCursorPosition: point, mouseButton: .left) else {
        fail("failed to create mouse event")
    }
    event.post(tap: .cghidEventTap)
}

let command = args[1]
if command == "click" {
    let x = number(2)
    let y = number(3)
    mouse(.mouseMoved, x, y)
    usleep(20_000)
    mouse(.leftMouseDown, x, y)
    usleep(35_000)
    mouse(.leftMouseUp, x, y)
    print("clicked \(Int(x)),\(Int(y))")
} else if command == "move" {
    let x = number(2)
    let y = number(3)
    mouse(.mouseMoved, x, y)
    print("moved \(Int(x)),\(Int(y))")
} else {
    fail("unknown command: \(command)")
}
'''


KEY_CODES = {
    "return": 36,
    "enter": 36,
    "tab": 48,
    "space": 49,
    "delete": 51,
    "backspace": 51,
    "escape": 53,
    "esc": 53,
    "left": 123,
    "right": 124,
    "down": 125,
    "up": 126,
}

MODIFIERS = {
    "cmd": "command down",
    "command": "command down",
    "shift": "shift down",
    "option": "option down",
    "alt": "option down",
    "ctrl": "control down",
    "control": "control down",
}

FAST_SCREENSHOT_DIAGNOSTICS_ENV = "OPENMAKO_DESKTOP_FAST_DIAGNOSTICS"


def desktop_dir(project: Path) -> Path:
    base = project / "AI_协作交接"
    return (base if base.exists() else project / ".quantagent") / "desktop"


def helper_dir(project: Path) -> Path:
    return project / ".quantagent" / "bin"


def _run(args: Sequence[str | Path], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(arg) for arg in args], text=True, capture_output=True, timeout=timeout)


def _osascript(script: str, timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return _run(["osascript", "-e", script], timeout=timeout)


def _result(action: str, proc: subprocess.CompletedProcess[str], summary: str, data: dict[str, object] | None = None) -> DesktopResult:
    ok = proc.returncode == 0
    detail = summary if ok else (proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}")
    payload = dict(data or {})
    if proc.stdout.strip():
        payload["stdout"] = proc.stdout.strip()
    if proc.stderr.strip():
        payload["stderr"] = proc.stderr.strip()
    return DesktopResult(action=action, ok=ok, summary=detail, data=payload)


def frontmost_app() -> DesktopResult:
    script = 'tell application "System Events" to get name of first application process whose frontmost is true'
    proc = _osascript(script)
    return _result("frontmost", proc, proc.stdout.strip() or "frontmost app read")


def front_window() -> DesktopResult:
    script = (
        'tell application "System Events"\n'
        '  set appName to name of first application process whose frontmost is true\n'
        '  tell process appName\n'
        '    if exists window 1 then\n'
        '      set winName to name of window 1\n'
        '      set winPos to position of window 1\n'
        '      set winSize to size of window 1\n'
        '      return appName & "|" & winName & "|" & (item 1 of winPos as text) & "," & (item 2 of winPos as text) & "|" & (item 1 of winSize as text) & "," & (item 2 of winSize as text)\n'
        '    else\n'
        '      return appName & "|NO_WINDOW||"\n'
        '    end if\n'
        '  end tell\n'
        'end tell'
    )
    proc = _osascript(script)
    return _result("window", proc, proc.stdout.strip() or "front window read")


def screenshot(project: Path, name: str | None = None) -> DesktopResult:
    directory = desktop_dir(project)
    directory.mkdir(parents=True, exist_ok=True)
    filename = name or f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    path = directory / filename
    attempts: list[dict[str, object]] = []
    commands: list[list[str | Path]] = [
        ["screencapture", "-x", path],
        ["screencapture", "-x", "-m", path],
    ]
    for command_index, command in enumerate(commands):
        tries = 2 if command_index == 0 else 1
        for attempt in range(1, tries + 1):
            if path.exists():
                path.unlink(missing_ok=True)
            proc = _run(command, timeout=20)
            detail = _proc_detail(proc)
            attempts.append(
                {
                    "command": " ".join(shlex.quote(str(part)) for part in command),
                    "attempt": attempt,
                    "returncode": proc.returncode,
                    "detail": detail,
                }
            )
            if proc.returncode == 0 and path.exists() and path.stat().st_size > 0:
                payload = {"path": str(path), "attempts": attempts}
                if proc.stdout.strip():
                    payload["stdout"] = proc.stdout.strip()
                if proc.stderr.strip():
                    payload["stderr"] = proc.stderr.strip()
                return DesktopResult("screenshot", True, f"screenshot: {path}", payload)
            if command_index == 0 and attempt == 1:
                time.sleep(0.3)

    diagnostics = _screenshot_diagnostics()
    failure = attempts[-1]["detail"] if attempts else "screenshot failed"
    permission_hint = _screenshot_permission_hint(failure, attempts, diagnostics)
    if permission_hint:
        diagnostics["permission_hint"] = permission_hint
    summary = f"{failure}; diagnostics: {_format_screenshot_diagnostics(diagnostics)}"
    if permission_hint:
        summary = f"{summary}; probable_cause={permission_hint['probable_cause']}; next_action={permission_hint['next_action']}"
    return DesktopResult(
        "screenshot",
        False,
        summary,
        {"path": str(path), "attempts": attempts, "diagnostics": diagnostics},
    )


def _proc_detail(proc: subprocess.CompletedProcess[str]) -> str:
    return proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"


def _screenshot_diagnostics(*, fast: bool | None = None) -> dict[str, object]:
    fast = _fast_screenshot_diagnostics_enabled() if fast is None else fast
    diagnostics: dict[str, object] = {"fast": fast}
    front = frontmost_app()
    diagnostics["frontmost_app"] = _diagnostic_result(front)
    window = front_window()
    diagnostics["front_window"] = _diagnostic_result(window)
    console = _run(["stat", "-f", "%Su", "/dev/console"], timeout=5)
    diagnostics["console_user"] = _proc_detail(console) if console.returncode != 0 else console.stdout.strip()
    if fast:
        diagnostics["display_available"] = "skipped"
        diagnostics["display_probe"] = "skipped_fast_diagnostics"
    else:
        displays = _run(["system_profiler", "SPDisplaysDataType"], timeout=20)
        diagnostics["display_available"] = displays.returncode == 0 and "Resolution:" in displays.stdout
    return diagnostics


def _fast_screenshot_diagnostics_enabled() -> bool:
    return os.environ.get(FAST_SCREENSHOT_DIAGNOSTICS_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _diagnostic_result(result: DesktopResult) -> dict[str, object]:
    return {"ok": result.ok, "summary": result.summary, "data": result.data}


def _format_screenshot_diagnostics(diagnostics: dict[str, object]) -> str:
    front = diagnostics.get("frontmost_app")
    window = diagnostics.get("front_window")
    user = diagnostics.get("console_user")
    display = diagnostics.get("display_available")
    front_summary = front.get("summary") if isinstance(front, dict) else front
    window_summary = window.get("summary") if isinstance(window, dict) else window
    return f"frontmost={front_summary}; window={window_summary}; console_user={user}; display_available={display}"


def _screenshot_permission_hint(
    failure: str,
    attempts: list[dict[str, object]],
    diagnostics: dict[str, object],
) -> dict[str, str] | None:
    attempt_text = " ".join(str(attempt.get("detail") or "") for attempt in attempts).lower()
    display_available = diagnostics.get("display_available")
    display_error = "could not create image from display" in (failure.lower() + " " + attempt_text)
    if display_error and display_available is True:
        front = diagnostics.get("frontmost_app")
        front_summary = front.get("summary") if isinstance(front, dict) else ""
        runner = str(front_summary or "the shell runner")
        return {
            "probable_cause": f"macOS Screen Recording permission is missing for {runner}/Python/screencapture",
            "next_action": "Grant Screen Recording to the terminal app running mako, then restart that terminal session.",
            "settings_url": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
        }
    if display_error and display_available == "skipped":
        return {
            "probable_cause": "macOS Screen Recording permission may be missing, or display capture may be unavailable",
            "next_action": f"Unset {FAST_SCREENSHOT_DIAGNOSTICS_ENV} for a full display probe, or grant Screen Recording to the terminal app running mako.",
            "settings_url": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
        }
    window = diagnostics.get("front_window")
    window_summary = str(window.get("summary") if isinstance(window, dict) else window)
    if "-25211" in window_summary or "不允许辅助访问" in window_summary or "assistive access" in window_summary.lower():
        return {
            "probable_cause": "macOS Accessibility permission is missing for the terminal app running mako",
            "next_action": "Grant Accessibility to the terminal app running mako, then restart that terminal session.",
            "settings_url": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        }
    return None


def _image_size(path: Path) -> tuple[int, int]:
    proc = _run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", path], timeout=10)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "sips failed")
    width = height = 0
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("pixelWidth:"):
            width = int(line.split(":", 1)[1].strip())
        elif line.startswith("pixelHeight:"):
            height = int(line.split(":", 1)[1].strip())
    if width <= 0 or height <= 0:
        raise RuntimeError("could not read screenshot dimensions")
    return width, height


def _cell_name(row: int, col: int) -> str:
    letters = ""
    value = col
    while True:
        letters = chr(ord("A") + (value % 26)) + letters
        value = value // 26 - 1
        if value < 0:
            break
    return f"{letters}{row + 1:02d}"


def screenshot_grid(project: Path, cols: int = 12, rows: int = 8, name: str | None = None) -> DesktopResult:
    cols = max(2, min(cols, 32))
    rows = max(2, min(rows, 32))
    shot = screenshot(project, name=name or f"grid_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    if not shot.ok:
        return shot
    image_path = Path(str(shot.data["path"]))
    try:
        width, height = _image_size(image_path)
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:201", exc)
        return DesktopResult("grid", False, f"grid failed: {exc}", {"image_path": str(image_path)})

    cell_w = width / cols
    cell_h = height / rows
    cells: list[dict[str, object]] = []
    for row in range(rows):
        for col in range(cols):
            x1 = round(col * cell_w)
            y1 = round(row * cell_h)
            x2 = round((col + 1) * cell_w)
            y2 = round((row + 1) * cell_h)
            cells.append(
                {
                    "id": _cell_name(row, col),
                    "row": row + 1,
                    "col": col + 1,
                    "x": round((x1 + x2) / 2),
                    "y": round((y1 + y2) / 2),
                    "bounds": [x1, y1, x2, y2],
                }
            )

    stem = image_path.with_suffix("")
    json_path = stem.with_suffix(".grid.json")
    html_path = stem.with_suffix(".grid.html")
    json_path.write_text(
        json.dumps(
            {
                "image_path": str(image_path),
                "width": width,
                "height": height,
                "cols": cols,
                "rows": rows,
                "cells": cells,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    html_path.write_text(_grid_html(image_path, width, height, cols, rows, cells), encoding="utf-8")
    return DesktopResult(
        "grid",
        True,
        f"grid: {html_path}",
        {"image_path": str(image_path), "grid_json": str(json_path), "grid_html": str(html_path), "cols": cols, "rows": rows},
    )


def _grid_html(image_path: Path, width: int, height: int, cols: int, rows: int, cells: list[dict[str, object]]) -> str:
    cell_divs = []
    for cell in cells:
        x1, y1, x2, y2 = cell["bounds"]  # type: ignore[index]
        cell_divs.append(
            (
                f'<div class="cell" style="left:{x1}px;top:{y1}px;'
                f'width:{x2 - x1}px;height:{y2 - y1}px;">'
                f'<span>{escape(str(cell["id"]))}</span></div>'
            )
        )
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{PRODUCT_NAME} Desktop Grid</title>
<style>
body {{ margin: 0; background: #111; color: #eee; font-family: -apple-system, BlinkMacSystemFont, sans-serif; }}
.wrap {{ position: relative; width: {width}px; height: {height}px; }}
img {{ position: absolute; left: 0; top: 0; width: {width}px; height: {height}px; }}
.cell {{ position: absolute; box-sizing: border-box; border: 1px solid rgba(255, 190, 80, .72); }}
.cell span {{ background: rgba(0,0,0,.72); color: #ffdf9a; font: 12px/1.2 ui-monospace, SFMono-Regular, Menlo, monospace; padding: 1px 3px; }}
.bar {{ padding: 8px 10px; background: #202020; position: sticky; top: 0; z-index: 2; }}
</style>
</head>
<body>
<div class="bar">{PRODUCT_NAME} grid {cols}x{rows}. Use cell centers from the .grid.json file for clicks.</div>
<div class="wrap">
<img src="{escape(image_path.name)}" alt="screenshot">
{''.join(cell_divs)}
</div>
</body>
</html>
"""


def latest_grid(project: Path) -> Path | None:
    directory = desktop_dir(project)
    if not directory.exists():
        return None
    grids = sorted(directory.glob("*.grid.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    return grids[0] if grids else None


def click_grid_cell(project: Path, cell_id: str, grid_path: str | None = None) -> DesktopResult:
    path = Path(grid_path).expanduser() if grid_path else latest_grid(project)
    if not path:
        return DesktopResult("grid-click", False, "no grid file found; run `mako desktop grid` first")
    if not path.is_absolute():
        path = desktop_dir(project) / path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:304", exc)
        return DesktopResult("grid-click", False, f"could not read grid: {exc}", {"grid_json": str(path)})
    wanted = cell_id.upper()
    for cell in data.get("cells", []):
        if str(cell.get("id", "")).upper() == wanted:
            return pointer(project, "click", int(cell["x"]), int(cell["y"]))
    return DesktopResult("grid-click", False, f"cell not found: {cell_id}", {"grid_json": str(path)})


def activate_app(name: str) -> DesktopResult:
    script = f'tell application {json.dumps(name)} to activate'
    proc = _osascript(script)
    return _result("activate", proc, f"activated {name}", {"app": name})


def type_text(text: str) -> DesktopResult:
    script = f'tell application "System Events" to keystroke {json.dumps(text)}'
    proc = _osascript(script, timeout=20)
    return _result("type", proc, f"typed {len(text)} chars", {"chars": len(text)})


def hotkey(keys: Sequence[str]) -> DesktopResult:
    if not keys:
        return DesktopResult("hotkey", False, "no keys provided")
    normalized = [key.lower() for key in keys]
    key = normalized[-1]
    modifiers = [MODIFIERS[item] for item in normalized[:-1] if item in MODIFIERS]
    using = "" if not modifiers else " using {" + ", ".join(modifiers) + "}"
    if len(key) == 1:
        script = f'tell application "System Events" to keystroke {json.dumps(key)}{using}'
    elif key in KEY_CODES:
        script = f'tell application "System Events" to key code {KEY_CODES[key]}{using}'
    else:
        return DesktopResult("hotkey", False, f"unknown key: {key}")
    proc = _osascript(script)
    return _result("hotkey", proc, "hotkey: " + "+".join(keys), {"keys": list(keys)})


def ensure_helper(project: Path) -> Path:
    directory = helper_dir(project)
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "quantagent_cgevent.swift"
    binary = directory / "quantagent_cgevent"
    if binary.exists():
        return binary
    source.write_text(SWIFT_HELPER.strip() + "\n", encoding="utf-8")
    proc = _run(["swiftc", source, "-o", binary], timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "swiftc failed")
    return binary


def pointer(project: Path, action: str, x: int, y: int) -> DesktopResult:
    if action not in {"click", "move"}:
        return DesktopResult("pointer", False, f"unsupported pointer action: {action}")
    try:
        helper = ensure_helper(project)
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:361", exc)
        return DesktopResult("pointer", False, f"failed to build pointer helper: {exc}")
    proc = _run([helper, action, str(x), str(y)], timeout=10)
    return _result("pointer", proc, f"{action} {x},{y}", {"command": shlex.join([str(helper), action, str(x), str(y)])})
