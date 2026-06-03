from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, Union

from .exception_audit import audit_suppressed_exception


Runner = Callable[[Sequence[str], Union[int, float]], subprocess.CompletedProcess[str]]
RISKY_TARGET_RE = re.compile(
    r"(pay|payment|invoice|buy|sell|trade|trading|order|password|credential|secret|token|otp|2fa|"
    r"支付|付款|发票|买入|卖出|交易|下单|密码|验证码)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PeekabooResult:
    action: str
    ok: bool
    status: str
    summary: str
    command: tuple[str, ...] = ()
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    path: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["command"] = list(self.command)
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False, indent=2)


def subprocess_runner(args: Sequence[str], timeout: int | float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), text=True, capture_output=True, timeout=timeout)


class PeekabooAdapter:
    def __init__(
        self,
        *,
        binary: str | Path = "peekaboo",
        runner: Runner | None = None,
        default_timeout: int | float = 20,
    ) -> None:
        self.binary = str(binary)
        self.runner = runner or subprocess_runner
        self.default_timeout = default_timeout

    def permissions_status(self, *, all_sources: bool = False, json_output: bool = True, timeout: int | float | None = None) -> PeekabooResult:
        args = [self.binary, "permissions", "status"]
        if all_sources:
            args.append("--all-sources")
        if json_output:
            args.append("--json")
        return self._invoke("permissions_status", args, timeout=timeout)

    def image(
        self,
        *,
        path: str | Path | None = None,
        mode: str | None = None,
        app: str | None = None,
        window_title: str | None = None,
        screen_index: int | None = None,
        region: str | Sequence[int | float] | None = None,
        retina: bool = False,
        image_format: str | None = None,
        analyze: str | None = None,
        json_output: bool = True,
        timeout: int | float | None = None,
    ) -> PeekabooResult:
        args = [self.binary, "image"]
        _append_target_flags(args, app=app, window_title=window_title)
        if mode:
            args.extend(["--mode", mode])
        if screen_index is not None:
            args.extend(["--screen-index", str(screen_index)])
        if region is not None:
            try:
                args.extend(["--region", _format_region(region)])
            except ValueError as exc:
                return _invalid_args_result("image", tuple(args), exc)
        if path is not None:
            args.extend(["--path", str(path)])
        if retina:
            args.append("--retina")
        if image_format:
            args.extend(["--format", image_format])
        if analyze:
            args.extend(["--analyze", analyze])
        if json_output:
            args.append("--json")
        return self._invoke("image", args, timeout=timeout)

    def screenshot(self, path: str | Path | None = None, **kwargs: Any) -> PeekabooResult:
        return self.image(path=path, **kwargs)

    def see(
        self,
        *,
        path: str | Path | None = None,
        app: str | None = None,
        window_title: str | None = None,
        mode: str | None = None,
        annotate: bool = False,
        menubar: bool = False,
        no_remote: bool = False,
        capture_engine: str | None = None,
        timeout_seconds: int | float | None = None,
        max_depth: int | None = None,
        max_elements: int | None = None,
        json_output: bool = True,
        timeout: int | float | None = None,
    ) -> PeekabooResult:
        args = [self.binary, "see"]
        _append_target_flags(args, app=app, window_title=window_title)
        if mode:
            args.extend(["--mode", mode])
        if annotate:
            args.append("--annotate")
        if path is not None:
            args.extend(["--path", str(path)])
        if menubar:
            args.append("--menubar")
        if no_remote:
            args.append("--no-remote")
        if capture_engine:
            args.extend(["--capture-engine", capture_engine])
        if timeout_seconds is not None:
            args.extend(["--timeout-seconds", str(timeout_seconds)])
        if max_depth is not None:
            args.extend(["--max-depth", str(max_depth)])
        if max_elements is not None:
            args.extend(["--max-elements", str(max_elements)])
        if json_output:
            args.append("--json")
        return self._invoke("see", args, timeout=timeout)

    def tokenize(self, **kwargs: Any) -> PeekabooResult:
        result = self.see(**kwargs)
        return _with_action(result, "tokenize")

    def click(
        self,
        *,
        x: int | float | None = None,
        y: int | float | None = None,
        coords: str | Sequence[int | float] | None = None,
        query: str | None = None,
        element_id: str | None = None,
        snapshot: str | None = None,
        app: str | None = None,
        window_title: str | None = None,
        wait_for_ms: int | None = None,
        global_coords: bool = False,
        double: bool = False,
        right: bool = False,
        no_auto_focus: bool = False,
        focus_background: bool = False,
        json_output: bool = True,
        timeout: int | float | None = None,
    ) -> PeekabooResult:
        args = [self.binary, "click"]
        if element_id:
            args.extend(["--on", element_id])
        elif query:
            args.append(query)
        try:
            point = _format_coords(coords, x=x, y=y)
        except ValueError as exc:
            return _invalid_args_result("click", tuple(args), exc)
        if point:
            args.extend(["--coords", point])
        if snapshot:
            args.extend(["--snapshot", snapshot])
        _append_target_flags(args, app=app, window_title=window_title)
        if wait_for_ms is not None:
            args.extend(["--wait-for", str(wait_for_ms)])
        if global_coords:
            args.append("--global-coords")
        if double:
            args.append("--double")
        if right:
            args.append("--right")
        if no_auto_focus:
            args.append("--no-auto-focus")
        if focus_background:
            args.append("--focus-background")
        if json_output:
            args.append("--json")
        return self._invoke("click", args, timeout=timeout)

    def type_text(
        self,
        text: str = "",
        *,
        app: str | None = None,
        window_title: str | None = None,
        snapshot: str | None = None,
        clear: bool = False,
        return_key: bool = False,
        tab: int | None = None,
        escape: bool = False,
        delete: bool = False,
        delay_ms: int | None = None,
        wpm: int | None = None,
        profile: str | None = None,
        json_output: bool = True,
        timeout: int | float | None = None,
    ) -> PeekabooResult:
        args = [self.binary, "type"]
        if text:
            args.append(text)
        _append_target_flags(args, app=app, window_title=window_title)
        if snapshot:
            args.extend(["--snapshot", snapshot])
        if clear:
            args.append("--clear")
        if return_key:
            args.append("--return")
        if tab is not None:
            args.extend(["--tab", str(tab)])
        if escape:
            args.append("--escape")
        if delete:
            args.append("--delete")
        if delay_ms is not None:
            args.extend(["--delay", str(delay_ms)])
        if wpm is not None:
            args.extend(["--wpm", str(wpm)])
        if profile:
            args.extend(["--profile", profile])
        if json_output:
            args.append("--json")
        return self._invoke("type", args, timeout=timeout)

    def press(
        self,
        keys: str | Sequence[str],
        *,
        count: int | None = None,
        delay_ms: int | None = None,
        hold_ms: int | None = None,
        app: str | None = None,
        window_title: str | None = None,
        snapshot: str | None = None,
        json_output: bool = True,
        timeout: int | float | None = None,
    ) -> PeekabooResult:
        key_list = _normalize_keys(keys, split_commas=False)
        if not key_list:
            return _invalid_args_result("press", (self.binary, "press"), ValueError("at least one key is required"))
        args = [self.binary, "press", *key_list]
        if count is not None:
            args.extend(["--count", str(count)])
        if delay_ms is not None:
            args.extend(["--delay", str(delay_ms)])
        if hold_ms is not None:
            args.extend(["--hold", str(hold_ms)])
        _append_target_flags(args, app=app, window_title=window_title)
        if snapshot:
            args.extend(["--snapshot", snapshot])
        if json_output:
            args.append("--json")
        return self._invoke("press", args, timeout=timeout)

    def hotkey(
        self,
        keys: str | Sequence[str],
        *,
        app: str | None = None,
        window_title: str | None = None,
        snapshot: str | None = None,
        hold_duration_ms: int | None = None,
        focus_background: bool = False,
        no_auto_focus: bool = False,
        json_output: bool = True,
        timeout: int | float | None = None,
    ) -> PeekabooResult:
        key_list = _normalize_keys(keys, split_commas=True)
        if not key_list:
            return _invalid_args_result("hotkey", (self.binary, "hotkey"), ValueError("at least one key is required"))
        key_arg = ",".join(key_list)
        args = [self.binary, "hotkey", "--keys", key_arg]
        _append_target_flags(args, app=app, window_title=window_title)
        if snapshot:
            args.extend(["--snapshot", snapshot])
        if hold_duration_ms is not None:
            args.extend(["--hold-duration", str(hold_duration_ms)])
        if focus_background:
            args.append("--focus-background")
        if no_auto_focus:
            args.append("--no-auto-focus")
        if json_output:
            args.append("--json")
        return self._invoke("hotkey", args, timeout=timeout)

    def _invoke(self, action: str, args: Sequence[str], *, timeout: int | float | None = None) -> PeekabooResult:
        command = tuple(str(item) for item in args)
        try:
            proc = self.runner(command, self.default_timeout if timeout is None else timeout)
        except FileNotFoundError as exc:
            return _exception_result(action, command, "not_found", f"peekaboo executable not found: {exc}", exc)
        except subprocess.TimeoutExpired as exc:
            stdout = _safe_text(getattr(exc, "stdout", ""))
            stderr = _safe_text(getattr(exc, "stderr", ""))
            return PeekabooResult(
                action=action,
                ok=False,
                status="timeout",
                summary=f"peekaboo command timed out after {exc.timeout}s",
                command=command,
                stdout=stdout,
                stderr=stderr,
                data={"error_type": type(exc).__name__, "timeout": exc.timeout},
            )
        except OSError as exc:
            return _exception_result(action, command, "runner_error", f"peekaboo runner failed: {exc}", exc)
        except Exception as exc:
            audit_suppressed_exception(
                "desktop_peekaboo.PeekabooAdapter._invoke",
                exc,
                data={"action": action, "command": list(command)},
            )
            return _exception_result(action, command, "runner_error", f"peekaboo runner failed: {exc}", exc)

        stdout = _safe_text(proc.stdout)
        stderr = _safe_text(proc.stderr)
        parsed, parse_error = _parse_json_output_tuple(stdout)
        path = extract_output_path(parsed, stdout, stderr)
        data: dict[str, Any] = {}
        if parsed is not None:
            data["json"] = parsed
        if parse_error:
            data["json_error"] = parse_error
        if path:
            data["path"] = path
        if stdout.strip():
            data["stdout"] = stdout.strip()
        if stderr.strip():
            data["stderr"] = stderr.strip()

        ok = proc.returncode == 0
        status = _status_from_payload(parsed, ok)
        summary = _summary_from_payload(parsed, stdout, stderr, proc.returncode, ok)
        return PeekabooResult(
            action=action,
            ok=ok,
            status=status,
            summary=summary,
            command=command,
            returncode=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            data=data,
            path=path,
        )


def default_adapter(**kwargs: Any) -> PeekabooAdapter:
    return PeekabooAdapter(**kwargs)


def capture(
    *,
    binary: str | Path = "peekaboo",
    runner: Runner | None = None,
    timeout: int | float = 20,
    **kwargs: Any,
) -> PeekabooResult:
    return PeekabooAdapter(binary=binary, runner=runner, default_timeout=timeout).image(timeout=timeout, **kwargs)


def click(
    *,
    binary: str | Path = "peekaboo",
    runner: Runner | None = None,
    timeout: int | float = 20,
    target_text: str | None = None,
    query: str | None = None,
    **kwargs: Any,
) -> PeekabooResult:
    label = target_text or query or ""
    if RISKY_TARGET_RE.search(label):
        return PeekabooResult(
            action="click",
            ok=False,
            status="blocked",
            summary=f"blocked risky Peekaboo click target: {label}",
            data={"target_text": label, "risk": "high"},
        )
    return PeekabooAdapter(binary=binary, runner=runner, default_timeout=timeout).click(query=query or target_text, timeout=timeout, **kwargs)


def parse_json_output(*args: str) -> Any:
    if len(args) == 1:
        return _parse_json_output_tuple(args[0])
    if len(args) == 2:
        command, text = args
        parsed, error = _parse_json_output_tuple(text)
        if error or parsed is None:
            return PeekabooResult(
                action="parse_json",
                ok=False,
                status="non_json",
                summary=f"non-json output from {command}: {error or 'empty output'}",
                command=(command,),
                stdout=text,
                data={"json_error": error or "empty output"},
            )
        return PeekabooResult(
            action="parse_json",
            ok=True,
            status=_status_from_payload(parsed, True),
            summary=_summary_from_payload(parsed, text, "", 0, True),
            command=(command,),
            stdout=text,
            data={"json": parsed},
            path=extract_output_path(parsed, text),
        )
    raise TypeError("parse_json_output expects text or command,text")


def _parse_json_output_tuple(text: str) -> tuple[dict[str, Any] | list[Any] | None, str]:
    stripped = (text or "").strip()
    if not stripped:
        return None, ""
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, (dict, list)):
            return parsed, ""
        return {"value": parsed}, ""
    except json.JSONDecodeError as first_error:
        candidate = _extract_balanced_json(stripped)
        if not candidate:
            return None, str(first_error)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as second_error:
            return None, str(second_error)
        if isinstance(parsed, (dict, list)):
            return parsed, ""
        return {"value": parsed}, ""


def extract_output_path(parsed: Any, *texts: str) -> str:
    for value in _walk_values(parsed):
        if isinstance(value, str) and _looks_like_path(value):
            return value
    for text in texts:
        found = _path_from_text(text)
        if found:
            return found
    return ""


def _append_target_flags(args: list[str], *, app: str | None = None, window_title: str | None = None) -> None:
    if app:
        args.extend(["--app", app])
    if window_title:
        args.extend(["--window-title", window_title])


def _format_region(region: str | Sequence[int | float]) -> str:
    if isinstance(region, str):
        return region.strip()
    values = list(region)
    if len(values) != 4:
        raise ValueError("region must have four values: x,y,width,height")
    return ",".join(_number_text(value) for value in values)


def _format_coords(coords: str | Sequence[int | float] | None, *, x: int | float | None, y: int | float | None) -> str:
    if coords is not None:
        if isinstance(coords, str):
            return coords.strip()
        values = list(coords)
        if len(values) != 2:
            raise ValueError("coords must have two values: x,y")
        return ",".join(_number_text(value) for value in values)
    if x is None and y is None:
        return ""
    if x is None or y is None:
        raise ValueError("x and y must be provided together")
    return f"{_number_text(x)},{_number_text(y)}"


def _number_text(value: int | float) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _normalize_keys(keys: str | Sequence[str], *, split_commas: bool) -> list[str]:
    if isinstance(keys, str):
        raw = re.split(r"[,\s]+", keys.strip()) if split_commas else keys.split()
    else:
        raw = []
        for key in keys:
            raw.extend(re.split(r"[,\s]+", str(key).strip()) if split_commas else [str(key).strip()])
    return [key.lower() for key in raw if key]


def _with_action(result: PeekabooResult, action: str) -> PeekabooResult:
    return PeekabooResult(
        action=action,
        ok=result.ok,
        status=result.status,
        summary=result.summary,
        command=result.command,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        data=result.data,
        path=result.path,
        timestamp=result.timestamp,
    )


def _exception_result(action: str, command: tuple[str, ...], status: str, summary: str, exc: BaseException) -> PeekabooResult:
    return PeekabooResult(
        action=action,
        ok=False,
        status=status,
        summary=summary,
        command=command,
        data={"error_type": type(exc).__name__, "error": str(exc)},
    )


def _invalid_args_result(action: str, command: tuple[str, ...], exc: ValueError) -> PeekabooResult:
    return PeekabooResult(
        action=action,
        ok=False,
        status="invalid_args",
        summary=str(exc),
        command=command,
        data={"error_type": type(exc).__name__, "error": str(exc)},
    )


def _safe_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _status_from_payload(parsed: Any, ok: bool) -> str:
    if isinstance(parsed, Mapping):
        for key in ("status", "state", "result"):
            value = parsed.get(key)
            if isinstance(value, str) and value:
                return value
        nested = parsed.get("data")
        if isinstance(nested, Mapping):
            value = nested.get("status")
            if isinstance(value, str) and value:
                return value
    return "ok" if ok else "failed"


def _summary_from_payload(parsed: Any, stdout: str, stderr: str, returncode: int, ok: bool) -> str:
    if isinstance(parsed, Mapping):
        for key in ("summary", "message", "error"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        nested = parsed.get("data")
        if isinstance(nested, Mapping):
            for key in ("summary", "message", "error"):
                value = nested.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    detail = stderr.strip() or stdout.strip()
    if detail:
        return _single_line(detail)
    return "peekaboo command completed" if ok else f"peekaboo command failed with exit {returncode}"


def _single_line(text: str, limit: int = 240) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "..."


def _walk_values(value: Any) -> list[Any]:
    seen: list[Any] = []

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            priority_keys = (
                "path",
                "image_path",
                "screenshot_path",
                "file",
                "filename",
                "url",
                "ui_map",
            )
            for key in priority_keys:
                if key in item:
                    visit(item[key])
            for key, nested in item.items():
                if key not in priority_keys:
                    visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)
        else:
            seen.append(item)

    visit(value)
    return seen


def _looks_like_path(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if text.startswith(("~", "/", "./", "../")):
        return True
    return bool(re.search(r"\.(png|jpg|jpeg|json|webp|heic|tiff?)$", text, re.IGNORECASE))


def _path_from_text(text: str) -> str:
    if not text:
        return ""
    quoted = re.search(r"['\"]((?:~|/|\.{1,2}/)[^'\"]+\.(?:png|jpg|jpeg|json|webp|heic|tiff?))['\"]", text, re.IGNORECASE)
    if quoted:
        return quoted.group(1)
    bare = re.search(r"((?:~|/|\.{1,2}/)[^\s,;:]+?\.(?:png|jpg|jpeg|json|webp|heic|tiff?))", text, re.IGNORECASE)
    return bare.group(1) if bare else ""


def _extract_balanced_json(text: str) -> str:
    starts = [index for index, char in enumerate(text) if char in "[{"]
    for start in starts:
        opener = text[start]
        closer = "}" if opener == "{" else "]"
        depth = 0
        in_string = False
        escape_next = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape_next:
                    escape_next = False
                elif char == "\\":
                    escape_next = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
    return ""


def shell_command(args: Sequence[str]) -> str:
    return shlex.join([str(arg) for arg in args])
