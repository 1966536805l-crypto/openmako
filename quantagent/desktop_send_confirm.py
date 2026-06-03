from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from .desktop_agent import default_stop_file
from .desktop_control import DesktopResult, desktop_dir, hotkey, screenshot, type_text
from .desktop_workflow import load_ocr_blocks, ocr_image
from .exception_audit import audit_suppressed_exception
from .gui_patterns import classify_gui_action


SendFunc = Callable[[str], Sequence[DesktopResult]]
ConfirmFunc = Callable[[Path, str, int, float, float], "DesktopSendConfirmation"]


@dataclass(frozen=True)
class DesktopSendConfirmation:
    ok: bool
    status: str
    summary: str
    observed_count: int = 0
    expected_count: int = 0
    data: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DesktopSendAttempt:
    index: int
    ok: bool
    status: str
    summary: str
    send_results: tuple[DesktopResult, ...] = ()
    confirmation: DesktopSendConfirmation | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "ok": self.ok,
            "status": self.status,
            "summary": self.summary,
            "send_results": [asdict(result) for result in self.send_results],
            "confirmation": self.confirmation.to_payload() if self.confirmation else None,
        }


@dataclass(frozen=True)
class DesktopSendConfirmResult:
    ok: bool
    status: str
    summary: str
    text: str
    requested_count: int
    confirmed_count: int
    attempts: tuple[DesktopSendAttempt, ...] = ()
    log_path: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "summary": self.summary,
            "text": self.text,
            "requested_count": self.requested_count,
            "confirmed_count": self.confirmed_count,
            "attempts": [attempt.to_payload() for attempt in self.attempts],
            "log_path": self.log_path,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False, indent=2)


def run_desktop_send_confirm(
    project: str | Path,
    text: str,
    *,
    count: int = 1,
    execute: bool = False,
    reviewed: bool = False,
    confirm: bool = True,
    confirm_timeout: float = 4.0,
    poll_interval: float = 0.5,
    interval: float = 0.12,
    max_count: int = 100,
    stop_file: str | Path | None = None,
    sender: SendFunc | None = None,
    confirmer: ConfirmFunc | None = None,
) -> DesktopSendConfirmResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    message = str(text)
    requested_count = int(count)
    bounded_timeout = max(0.1, min(float(confirm_timeout), 60.0))
    bounded_poll = max(0.05, min(float(poll_interval), bounded_timeout))
    bounded_interval = max(0.0, min(float(interval), 10.0))
    stop_path = _resolve_stop_file(project_path, stop_file)

    if not message:
        return _write_result(project_path, DesktopSendConfirmResult(False, "blocked", "send-confirm text cannot be empty", message, requested_count, 0))
    if requested_count < 1:
        return _write_result(project_path, DesktopSendConfirmResult(False, "blocked", "send-confirm count must be >= 1", message, requested_count, 0))
    if requested_count > max_count:
        return _write_result(project_path, DesktopSendConfirmResult(False, "blocked", f"send-confirm count {requested_count} exceeds max_count {max_count}", message, requested_count, 0))
    safety, reason = classify_gui_action("type", text=message)
    if safety == "deny":
        return _write_result(project_path, DesktopSendConfirmResult(False, "blocked", reason, message, requested_count, 0))
    if not execute:
        return _write_result(project_path, DesktopSendConfirmResult(True, "preview", f"dry-run preview: would send {requested_count} confirmed message(s)", message, requested_count, 0))
    if not reviewed:
        return _write_result(project_path, DesktopSendConfirmResult(False, "blocked", "send-confirm requires --reviewed before desktop side effects", message, requested_count, 0))
    if stop_path.exists():
        return _write_result(project_path, DesktopSendConfirmResult(False, "stopped", f"STOP file present before send-confirm: {stop_path}", message, requested_count, 0))

    send_once = sender or _default_sender
    confirm_once = confirmer or _confirm_ocr_count
    baseline = 0
    if confirm:
        baseline_result = confirm_once(project_path, message, 0, bounded_timeout, bounded_poll)
        if not baseline_result.ok:
            attempt = DesktopSendAttempt(0, False, "confirm_failed", f"baseline confirmation failed: {baseline_result.summary}", confirmation=baseline_result)
            return _write_result(project_path, DesktopSendConfirmResult(False, "confirm_failed", attempt.summary, message, requested_count, 0, (attempt,)))
        baseline = max(0, int(baseline_result.observed_count))

    attempts: list[DesktopSendAttempt] = []
    confirmed = 0
    for index in range(1, requested_count + 1):
        if stop_path.exists():
            summary = f"STOP file present before send-confirm attempt {index}: {stop_path}"
            attempts.append(DesktopSendAttempt(index, False, "stopped", summary))
            return _write_result(project_path, DesktopSendConfirmResult(False, "stopped", summary, message, requested_count, confirmed, tuple(attempts)))
        try:
            send_results = tuple(send_once(message))
        except Exception as exc:
            summary = f"send-confirm sender exception at attempt {index}: {type(exc).__name__}: {exc}"
            attempts.append(DesktopSendAttempt(index, False, "send_failed", summary))
            return _write_result(project_path, DesktopSendConfirmResult(False, "send_failed", summary, message, requested_count, confirmed, tuple(attempts)))
        failed_send = next((result for result in send_results if not result.ok), None)
        if failed_send is not None:
            summary = f"send-confirm attempt {index} failed: {failed_send.summary}"
            attempts.append(DesktopSendAttempt(index, False, "send_failed", summary, send_results))
            return _write_result(project_path, DesktopSendConfirmResult(False, "send_failed", summary, message, requested_count, confirmed, tuple(attempts)))

        confirmation = None
        if confirm:
            expected_count = baseline + index
            confirmation = confirm_once(project_path, message, expected_count, bounded_timeout, bounded_poll)
            if not confirmation.ok:
                summary = f"send-confirm attempt {index} was not confirmed: {confirmation.summary}"
                attempts.append(DesktopSendAttempt(index, False, "confirm_failed", summary, send_results, confirmation))
                return _write_result(project_path, DesktopSendConfirmResult(False, "confirm_failed", summary, message, requested_count, confirmed, tuple(attempts)))
        confirmed += 1
        attempts.append(DesktopSendAttempt(index, True, "confirmed" if confirm else "sent", f"sent attempt {index}", send_results, confirmation))
        if index < requested_count and bounded_interval > 0:
            time.sleep(bounded_interval)

    return _write_result(project_path, DesktopSendConfirmResult(True, "confirmed" if confirm else "sent", f"sent and confirmed {confirmed}/{requested_count} message(s)", message, requested_count, confirmed, tuple(attempts)))


def render_desktop_send_confirm_result(result: DesktopSendConfirmResult) -> str:
    lines = [
        "# Desktop Send Confirm",
        "",
        f"Status: {result.status}",
        f"OK: {str(result.ok).lower()}",
        result.summary,
        f"Requested: {result.requested_count}",
        f"Confirmed: {result.confirmed_count}",
        f"Log: {result.log_path or '-'}",
    ]
    if result.attempts:
        lines.extend(["", "Attempts:"])
        for attempt in result.attempts:
            lines.append(f"- {attempt.index}: {attempt.status} - {attempt.summary}")
    return "\n".join(lines).rstrip() + "\n"


def _default_sender(text: str) -> tuple[DesktopResult, DesktopResult]:
    typed = type_text(text)
    if not typed.ok:
        return (typed,)
    submitted = hotkey(["return"])
    return typed, submitted


def _confirm_ocr_count(project: Path, text: str, expected_count: int, timeout: float, poll_interval: float) -> DesktopSendConfirmation:
    deadline = time.monotonic() + timeout
    last = DesktopSendConfirmation(False, "not_observed", "confirmation not attempted", expected_count=expected_count)
    attempt = 0
    while True:
        attempt += 1
        observed = _observe_text_count(project, text, attempt)
        if observed.ok and observed.observed_count >= expected_count:
            return DesktopSendConfirmation(
                True,
                "confirmed",
                f"observed {observed.observed_count} occurrence(s), expected >= {expected_count}",
                observed.observed_count,
                expected_count,
                observed.data,
            )
        last = observed
        if time.monotonic() >= deadline:
            break
        time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
    return DesktopSendConfirmation(
        False,
        "not_confirmed",
        f"observed {last.observed_count} occurrence(s), expected >= {expected_count}: {last.summary}",
        last.observed_count,
        expected_count,
        last.data,
    )


def _observe_text_count(project: Path, text: str, attempt: int) -> DesktopSendConfirmation:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    shot = screenshot(project, name=f"send_confirm_{stamp}_{attempt:02d}.png")
    if not shot.ok:
        return DesktopSendConfirmation(False, "screenshot_failed", shot.summary, data={"screenshot": asdict(shot)})
    image_path = str(shot.data.get("path") or "")
    ocr = ocr_image(project, image_path=image_path, name=f"send_confirm_ocr_{stamp}_{attempt:02d}.json")
    if not ocr.ok:
        return DesktopSendConfirmation(False, "ocr_failed", ocr.summary, data={"screenshot": asdict(shot), "ocr": asdict(ocr)})
    ocr_path = Path(str(ocr.data.get("path") or ""))
    try:
        blocks = load_ocr_blocks(ocr_path)
    except Exception as exc:
        audit_suppressed_exception(
            "desktop_send_confirm._observe_text_count.load_ocr_blocks",
            exc,
            project=project,
            data={"ocr_path": str(ocr_path), "attempt": attempt},
        )
        return DesktopSendConfirmation(False, "ocr_load_failed", f"OCR load failed: {type(exc).__name__}: {exc}", data={"screenshot": asdict(shot), "ocr": asdict(ocr)})
    observed = _count_text_occurrences((block.text for block in blocks), text)
    return DesktopSendConfirmation(
        True,
        "observed",
        f"observed {observed} occurrence(s)",
        observed_count=observed,
        data={"screenshot": asdict(shot), "ocr": asdict(ocr), "blocks": len(blocks)},
    )


def _count_text_occurrences(values: Sequence[str] | Any, needle: str) -> int:
    expected = _normalize_text(needle)
    if not expected:
        return 0
    count = 0
    for value in values:
        haystack = _normalize_text(str(value))
        if not haystack:
            continue
        if len(expected) <= 3:
            count += haystack.count(expected)
        elif expected in haystack:
            count += 1
    return count


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _resolve_stop_file(project: Path, stop_file: str | Path | None) -> Path:
    path = Path(stop_file).expanduser() if stop_file else default_stop_file(project)
    if not path.is_absolute():
        path = project / path
    return path


def _write_result(project: Path, result: DesktopSendConfirmResult) -> DesktopSendConfirmResult:
    directory = desktop_dir(project) / "send_confirm"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    payload = result.to_payload()
    payload["log_path"] = str(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return DesktopSendConfirmResult(
        result.ok,
        result.status,
        result.summary,
        result.text,
        result.requested_count,
        result.confirmed_count,
        result.attempts,
        str(path),
    )
