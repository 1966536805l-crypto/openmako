from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
import subprocess
import time

from .desktop_control import DesktopResult, activate_app, desktop_dir, hotkey, pointer, screenshot, type_text
from .exception_audit import audit_suppressed_exception


class DesktopCommandRunner(Protocol):
    def __call__(self, args: Sequence[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
        ...


class DesktopActionRunner(Protocol):
    def __call__(self, project: Path, action: str, args: Mapping[str, Any]) -> DesktopResult:
        ...


class DesktopDriver(Protocol):
    name: str

    def probe(self) -> "DesktopDriverDiagnostic":
        ...

    def execute(self, project: Path, action: str, args: Mapping[str, Any] | None = None) -> DesktopResult:
        ...


@dataclass(frozen=True)
class DesktopDriverDiagnostic:
    driver: str
    ok: bool
    status: str
    summary: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_result(self, *, action: str = "desktop-driver") -> DesktopResult:
        return DesktopResult(action, self.ok, self.summary, self.to_dict())


@dataclass(frozen=True)
class DesktopDriverResolution:
    requested: str
    ok: bool
    driver: DesktopDriver | None = None
    diagnostic: DesktopDriverDiagnostic | None = None

    @property
    def name(self) -> str:
        return self.driver.name if self.driver is not None else self.requested

    def to_result(self) -> DesktopResult:
        if self.diagnostic is not None:
            return self.diagnostic.to_result()
        return DesktopResult("desktop-driver", self.ok, f"desktop driver selected: {self.name}", {"driver": self.name})


def default_command_runner(args: Sequence[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(arg) for arg in args], text=True, capture_output=True, timeout=timeout)


def resolve_desktop_driver(
    name: str | None = None,
    *,
    runner: DesktopCommandRunner | None = None,
    require_available: bool = True,
    peekaboo_executable: str = "peekaboo",
    peekaboo_action_runner: DesktopActionRunner | None = None,
) -> DesktopDriverResolution:
    selected = normalize_driver_name(name)
    if selected == "builtin":
        driver = BuiltinDesktopDriver()
        return DesktopDriverResolution(selected, True, driver, driver.probe())
    if selected == "peekaboo":
        driver = PeekabooDesktopDriver(
            runner=runner,
            executable=peekaboo_executable,
            action_runner=peekaboo_action_runner,
        )
        diagnostic = driver.probe()
        if require_available and not diagnostic.ok:
            return DesktopDriverResolution(selected, False, None, diagnostic)
        return DesktopDriverResolution(selected, diagnostic.ok or not require_available, driver, diagnostic)
    diagnostic = DesktopDriverDiagnostic(
        selected,
        False,
        "unknown_driver",
        f"unknown desktop driver: {selected}; expected builtin or peekaboo",
        {"requested": name, "supported": ["builtin", "peekaboo"]},
    )
    return DesktopDriverResolution(selected, False, None, diagnostic)


def get_desktop_driver(name: str | None = None, **kwargs: Any) -> DesktopDriver:
    resolution = resolve_desktop_driver(name, **kwargs)
    if resolution.driver is None:
        diagnostic = resolution.diagnostic or DesktopDriverDiagnostic(
            normalize_driver_name(name),
            False,
            "unavailable",
            "desktop driver unavailable",
        )
        raise DesktopDriverUnavailable(diagnostic)
    return resolution.driver


def normalize_driver_name(name: str | None) -> str:
    value = (name or "builtin").strip().lower()
    if value in {"", "default", "native", "local"}:
        return "builtin"
    return value


class DesktopDriverUnavailable(RuntimeError):
    def __init__(self, diagnostic: DesktopDriverDiagnostic) -> None:
        super().__init__(diagnostic.summary)
        self.diagnostic = diagnostic


class BuiltinDesktopDriver:
    name = "builtin"

    def probe(self) -> DesktopDriverDiagnostic:
        return DesktopDriverDiagnostic(
            self.name,
            True,
            "available",
            "builtin desktop driver selected",
            {"side_effects": "only when execute() is called"},
        )

    def execute(self, project: Path, action: str, args: Mapping[str, Any] | None = None) -> DesktopResult:
        payload = dict(args or {})
        if action == "activate":
            return activate_app(str(payload.get("app") or ""))
        if action == "screenshot":
            return screenshot(project, name=_optional_str(payload.get("name")))
        if action == "click":
            return pointer(project, "click", int(payload.get("x") or 0), int(payload.get("y") or 0))
        if action == "move":
            return pointer(project, "move", int(payload.get("x") or 0), int(payload.get("y") or 0))
        if action == "type":
            return type_text(str(payload.get("text") or ""))
        if action == "hotkey":
            keys = payload.get("keys") or []
            if isinstance(keys, str):
                keys = [part for part in keys.replace("+", " ").replace(",", " ").split() if part]
            return hotkey([str(key) for key in keys])
        if action == "wait":
            seconds = max(0.0, min(float(payload.get("seconds") or 1.0), 10.0))
            time.sleep(seconds)
            return DesktopResult("wait", True, f"waited {seconds:g}s", {"seconds": seconds})
        return DesktopResult(action or "desktop", False, f"unsupported builtin desktop action: {action}", {"driver": self.name})


class PeekabooDesktopDriver:
    name = "peekaboo"

    def __init__(
        self,
        *,
        runner: DesktopCommandRunner | None = None,
        executable: str = "peekaboo",
        probe_args: Sequence[str] = ("--version",),
        probe_timeout: float = 5.0,
        action_runner: DesktopActionRunner | None = None,
    ) -> None:
        self.runner = runner or default_command_runner
        self.executable = executable
        self.probe_args = tuple(probe_args)
        self.probe_timeout = probe_timeout
        self.action_runner = action_runner
        self._probe: DesktopDriverDiagnostic | None = None

    def probe(self) -> DesktopDriverDiagnostic:
        if self._probe is not None:
            return self._probe
        command = [self.executable, *self.probe_args]
        try:
            proc = self.runner(command, timeout=self.probe_timeout)
        except FileNotFoundError as exc:
            diagnostic = self._unavailable("executable_not_found", f"peekaboo driver unavailable: {exc}", command)
        except subprocess.TimeoutExpired as exc:
            diagnostic = self._unavailable("probe_timeout", f"peekaboo driver probe timed out after {exc.timeout:g}s", command)
        except OSError as exc:
            diagnostic = self._unavailable("probe_error", f"peekaboo driver probe failed: {exc}", command)
        else:
            stdout = (proc.stdout or "").strip()
            stderr = (proc.stderr or "").strip()
            data = {"command": command, "returncode": proc.returncode}
            if stdout:
                data["stdout"] = stdout
            if stderr:
                data["stderr"] = stderr
            if proc.returncode == 0:
                diagnostic = DesktopDriverDiagnostic(
                    self.name,
                    True,
                    "available",
                    "peekaboo desktop driver available",
                    data,
                )
            else:
                detail = stderr or stdout or f"exit {proc.returncode}"
                diagnostic = DesktopDriverDiagnostic(
                    self.name,
                    False,
                    "probe_failed",
                    f"peekaboo driver unavailable: {detail}",
                    data,
                )
        self._probe = diagnostic
        return diagnostic

    def execute(self, project: Path, action: str, args: Mapping[str, Any] | None = None) -> DesktopResult:
        diagnostic = self.probe()
        if not diagnostic.ok:
            return DesktopResult(
                action or "desktop",
                False,
                diagnostic.summary,
                {"driver": self.name, "diagnostic": diagnostic.to_dict()},
            )
        payload = dict(args or {})
        if self.action_runner is not None:
            return self.action_runner(project, action, payload)
        return self._execute_with_adapter(project, action, payload)

    def _execute_with_adapter(self, project: Path, action: str, args: Mapping[str, Any]) -> DesktopResult:
        try:
            from .desktop_peekaboo import PeekabooAdapter, PeekabooResult
        except ImportError as exc:
            audit_suppressed_exception(
                "desktop_driver.PeekabooDesktopDriver._execute_with_adapter.import",
                exc,
                project=project,
                data={"driver": self.name, "action": action},
            )
            return DesktopResult(
                action or "desktop",
                False,
                f"peekaboo adapter unavailable: {type(exc).__name__}: {exc}",
                {"driver": self.name, "status": "adapter_unavailable", "error_type": type(exc).__name__},
            )

        adapter = PeekabooAdapter(binary=self.executable, runner=self._adapter_runner)
        selected = (action or "desktop").strip().lower()
        result: PeekabooResult
        if selected in {"screenshot", "image"}:
            result = adapter.image(
                path=_peekaboo_image_path(project, args),
                mode=_optional_str(args.get("mode")) or "screen",
                app=_optional_str(args.get("app")),
                window_title=_optional_str(args.get("window_title")),
                retina=bool(args.get("retina", False)),
            )
        elif selected in {"see", "tokenize"}:
            result = adapter.see(
                path=_optional_str(args.get("path")),
                app=_optional_str(args.get("app")),
                window_title=_optional_str(args.get("window_title")),
                mode=_optional_str(args.get("mode")),
                annotate=bool(args.get("annotate", False)),
                max_depth=_optional_int(args.get("max_depth")),
                max_elements=_optional_int(args.get("max_elements")),
            )
        elif selected == "click":
            result = adapter.click(
                x=_optional_float(args.get("x")),
                y=_optional_float(args.get("y")),
                coords=args.get("coords"),  # type: ignore[arg-type]
                query=_optional_str(args.get("query") or args.get("target_text")),
                element_id=_optional_str(args.get("element_id") or args.get("peekaboo_id")),
                snapshot=_optional_str(args.get("snapshot")),
                app=_optional_str(args.get("app")),
                window_title=_optional_str(args.get("window_title")),
                global_coords=bool(args.get("global_coords", True)),
            )
        elif selected == "type":
            result = adapter.type_text(
                str(args.get("text") or ""),
                app=_optional_str(args.get("app")),
                window_title=_optional_str(args.get("window_title")),
                snapshot=_optional_str(args.get("snapshot")),
                clear=bool(args.get("clear", False)),
                return_key=bool(args.get("return_key", False)),
            )
        elif selected == "hotkey":
            result = adapter.hotkey(args.get("keys") or ())
        elif selected == "press":
            result = adapter.press(args.get("keys") or args.get("key") or ())
        elif selected == "activate":
            builtin = activate_app(str(args.get("app") or ""))
            return DesktopResult(builtin.action, builtin.ok, builtin.summary, {"driver": self.name, "fallback": "builtin_activate", **builtin.data})
        elif selected == "wait":
            seconds = max(0.0, min(float(args.get("seconds") or 1.0), 10.0))
            time.sleep(seconds)
            return DesktopResult("wait", True, f"waited {seconds:g}s", {"driver": self.name, "seconds": seconds})
        else:
            return DesktopResult(selected, False, f"unsupported peekaboo desktop action: {selected}", {"driver": self.name})
        return _peekaboo_to_desktop_result(selected, result)

    def _adapter_runner(self, args: Sequence[str], timeout: int | float) -> subprocess.CompletedProcess[str]:
        return self.runner(args, timeout=float(timeout))

    def _unavailable(self, status: str, summary: str, command: Sequence[str]) -> DesktopDriverDiagnostic:
        return DesktopDriverDiagnostic(
            self.name,
            False,
            status,
            summary,
            {"command": list(command), "executable": self.executable},
        )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _peekaboo_image_path(project: Path, args: Mapping[str, Any]) -> str:
    explicit = _optional_str(args.get("path"))
    if explicit:
        return explicit
    directory = desktop_dir(project)
    directory.mkdir(parents=True, exist_ok=True)
    name = _optional_str(args.get("name")) or f"peekaboo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    return str(directory / name)


def _peekaboo_to_desktop_result(action: str, result: Any) -> DesktopResult:
    data = {"driver": "peekaboo", "peekaboo": result.to_payload()}
    if result.path:
        data["path"] = result.path
    return DesktopResult(action, bool(result.ok), str(result.summary), data)
