from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from .desktop_agent import default_stop_file
from .desktop_control import desktop_dir
from .desktop_daemon_policy import classify_goal_risk
from .hook_events import read_query_events
from .trajectory import read_events


STOP_STATUSES = frozenset({"running", "paused", "blocked", "failed", "verify_failed", "stale_target", "network_failed"})
TERMINAL_STATUSES = frozenset({"completed", "done", "stopped", "skipped", "no_match", "step_budget_exhausted", "dry_run"})
FAILURE_MARKERS = (
    "permission_required",
    "permission is missing",
    "screen recording",
    "accessibility",
    "assistive access",
    "辅助访问",
    "could not create image from display",
    "-25211",
)
NETWORK_MARKERS = (
    "network_failed",
    "network failure",
    "network token fetch failed",
    "err_internet_disconnected",
    "err_name_not_resolved",
    "offline",
    "urlerror",
    "connectionerror",
)


@dataclass(frozen=True)
class GuardianFinding:
    code: str
    severity: str
    summary: str
    stop: bool = True
    data: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DesktopGuardianResult:
    ok: bool
    status: str
    summary: str
    findings: tuple[GuardianFinding, ...]
    wrote_stop: bool
    stop_file: str
    state_path: str
    query_events_path: str
    trajectory_path: str
    guardian_state_path: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "summary": self.summary,
            "findings": [finding.to_payload() for finding in self.findings],
            "wrote_stop": self.wrote_stop,
            "stop_file": self.stop_file,
            "state_path": self.state_path,
            "query_events_path": self.query_events_path,
            "trajectory_path": self.trajectory_path,
            "guardian_state_path": self.guardian_state_path,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False, indent=2, sort_keys=True)


def run_desktop_guardian(
    project: str | Path,
    *,
    watch: bool = False,
    interval: float = 2.0,
    max_minutes: float = 0.0,
    max_event_age_seconds: float = 180.0,
    same_action_limit: int = 3,
    state_path: str | Path | None = None,
    query_events_path: str | Path | None = None,
    trajectory_path: str | Path | None = None,
    stop_file: str | Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
) -> DesktopGuardianResult:
    """Watch desktop daemon artifacts and write STOP when external invariants fail."""

    project_path = Path(project).expanduser().resolve(strict=False)
    deadline = now() + max(0.0, float(max_minutes)) * 60.0 if watch and max_minutes > 0 else 0.0
    bounded_interval = max(0.1, min(float(interval), 30.0))
    result = inspect_desktop_guardian(
        project_path,
        max_event_age_seconds=max_event_age_seconds,
        same_action_limit=same_action_limit,
        state_path=state_path,
        query_events_path=query_events_path,
        trajectory_path=trajectory_path,
        stop_file=stop_file,
        now=now,
    )
    while watch and result.ok and not result.findings:
        if deadline and now() >= deadline:
            return _finish_result(
                project_path,
                status="watch_timeout",
                summary="guardian watch budget exhausted without stop findings",
                findings=(),
                wrote_stop=False,
                paths=_resolve_paths(project_path, state_path, query_events_path, trajectory_path, stop_file, {}),
            )
        sleep(bounded_interval)
        result = inspect_desktop_guardian(
            project_path,
            max_event_age_seconds=max_event_age_seconds,
            same_action_limit=same_action_limit,
            state_path=state_path,
            query_events_path=query_events_path,
            trajectory_path=trajectory_path,
            stop_file=stop_file,
            now=now,
        )
    return result


def inspect_desktop_guardian(
    project: str | Path,
    *,
    max_event_age_seconds: float = 180.0,
    same_action_limit: int = 3,
    state_path: str | Path | None = None,
    query_events_path: str | Path | None = None,
    trajectory_path: str | Path | None = None,
    stop_file: str | Path | None = None,
    now: Callable[[], float] = time.time,
) -> DesktopGuardianResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    raw_state, state_error, state_file = _load_state(project_path, state_path)
    paths = _resolve_paths(project_path, state_file, query_events_path, trajectory_path, stop_file, raw_state)
    findings: list[GuardianFinding] = []

    if state_error:
        findings.append(GuardianFinding("state_unreadable", "stop", state_error, data={"state_path": str(paths.state_path)}))
    elif not raw_state:
        return _finish_result(project_path, status="idle", summary="guardian found no desktop daemon state", findings=(), wrote_stop=False, paths=paths)

    status = str(raw_state.get("status") or "").strip()
    state_text = _state_text(raw_state)
    if paths.stop_file.exists():
        findings.append(GuardianFinding("stop_present", "warn", f"STOP file already present: {paths.stop_file}", stop=False))
        return _finish_result(project_path, status="stopped", summary=f"STOP file already present: {paths.stop_file}", findings=tuple(findings), wrote_stop=False, paths=paths)

    if status in {"failed", "verify_failed", "blocked", "stale_target"}:
        findings.append(GuardianFinding("daemon_failure_status", "stop", f"daemon status requires operator pause: {status}", data={"status": status}))

    risk = classify_goal_risk(str(raw_state.get("goal") or ""))
    if risk.blocked or "high-risk" in state_text.lower():
        findings.append(GuardianFinding("high_risk_detected", "stop", risk.reason or "high-risk desktop state detected", data={"matched": risk.matched, "category": risk.category}))

    if _contains_marker(state_text, FAILURE_MARKERS):
        findings.append(GuardianFinding("permission_required", "stop", "desktop permission failure detected", data={"markers": _matched_markers(state_text, FAILURE_MARKERS)}))

    if _contains_marker(state_text, NETWORK_MARKERS):
        findings.append(GuardianFinding("network_failed", "stop", "desktop network failure detected", data={"markers": _matched_markers(state_text, NETWORK_MARKERS)}))

    records = list(raw_state.get("records") or []) if isinstance(raw_state.get("records") or [], list) else []
    repeated = _same_action_repeat(records, limit=max(2, int(same_action_limit))) if status not in TERMINAL_STATUSES else {}
    if repeated:
        findings.append(GuardianFinding("same_action_repeat", "stop", f"same desktop action repeated {repeated['count']} time(s): {repeated['action']}", data=repeated))

    if records and status not in TERMINAL_STATUSES:
        findings.extend(_ledger_findings(paths.query_events_path, paths.trajectory_path))

    if status in STOP_STATUSES:
        event_age = _last_event_age(paths, now=now)
        if event_age is not None and event_age > max(1.0, float(max_event_age_seconds)):
            findings.append(
                GuardianFinding(
                    "stale_heartbeat",
                    "stop",
                    f"desktop daemon heartbeat stale for {event_age:.1f}s",
                    data={"age_seconds": round(event_age, 3), "max_event_age_seconds": max_event_age_seconds},
                )
            )

    stop_findings = tuple(finding for finding in findings if finding.stop)
    wrote_stop = False
    if stop_findings:
        _write_stop(paths.stop_file, stop_findings)
        wrote_stop = True
    status_out = "stopped" if stop_findings else "warn" if findings else "ok"
    summary = _summary(findings, status_out)
    return _finish_result(project_path, status=status_out, summary=summary, findings=tuple(findings), wrote_stop=wrote_stop, paths=paths)


def render_desktop_guardian_result(result: DesktopGuardianResult) -> str:
    lines = [
        "# Desktop Guardian",
        "",
        f"Status: {result.status}",
        f"OK: {str(result.ok).lower()}",
        result.summary,
        f"STOP: {result.stop_file}",
        f"State: {result.state_path}",
        f"Query events: {result.query_events_path}",
        f"Trajectory: {result.trajectory_path}",
        "",
        "Findings:",
    ]
    if result.findings:
        lines.extend(f"- {item.code}/{item.severity}: {item.summary}" for item in result.findings)
    else:
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


@dataclass(frozen=True)
class _GuardianPaths:
    state_path: Path
    query_events_path: Path
    trajectory_path: Path
    stop_file: Path
    guardian_state_path: Path


def _load_state(project: Path, explicit: str | Path | None) -> tuple[dict[str, Any], str, Path | None]:
    path = _resolve_state_path(project, explicit)
    if path is None or not path.exists():
        return {}, "", path
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, f"desktop daemon state unreadable: {type(exc).__name__}: {exc}", path
    if not isinstance(payload, dict):
        return {}, "desktop daemon state must be a JSON object", path
    return payload, "", path


def _resolve_state_path(project: Path, explicit: str | Path | None) -> Path | None:
    if explicit is not None:
        return _resolve_project_path(project, explicit)
    candidates = (
        desktop_dir(project) / "intelligence" / "daemon" / "latest_state.json",
        desktop_dir(project) / "night_daemon" / "latest_state.json",
        desktop_dir(project) / "overnight" / "latest_state.json",
    )
    return next((path for path in candidates if path.exists()), candidates[0])


def _resolve_paths(
    project: Path,
    state_path: str | Path | None,
    query_events_path: str | Path | None,
    trajectory_path: str | Path | None,
    stop_file: str | Path | None,
    state: dict[str, Any],
) -> _GuardianPaths:
    state_resolved = _resolve_state_path(project, state_path) or (desktop_dir(project) / "intelligence" / "daemon" / "latest_state.json")
    base = state_resolved.parent
    query_resolved = _resolve_project_path(project, query_events_path) if query_events_path is not None else base / "query_events.jsonl"
    trajectory_resolved = _resolve_project_path(project, trajectory_path) if trajectory_path is not None else base / "trajectory.jsonl"
    raw_stop = stop_file if stop_file is not None else state.get("stop_file") or default_stop_file(project)
    stop_resolved = _resolve_project_path(project, raw_stop)
    guardian_state = desktop_dir(project) / "guardian" / "latest_state.json"
    return _GuardianPaths(state_resolved, query_resolved, trajectory_resolved, stop_resolved, guardian_state)


def _resolve_project_path(project: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else project / path


def _finish_result(
    project: Path,
    *,
    status: str,
    summary: str,
    findings: Sequence[GuardianFinding],
    wrote_stop: bool,
    paths: _GuardianPaths,
) -> DesktopGuardianResult:
    result = DesktopGuardianResult(
        ok=status in {"ok", "idle", "watch_timeout", "warn"} and not wrote_stop,
        status=status,
        summary=summary,
        findings=tuple(findings),
        wrote_stop=wrote_stop,
        stop_file=str(paths.stop_file),
        state_path=str(paths.state_path),
        query_events_path=str(paths.query_events_path),
        trajectory_path=str(paths.trajectory_path),
        guardian_state_path=str(paths.guardian_state_path),
    )
    paths.guardian_state_path.parent.mkdir(parents=True, exist_ok=True)
    paths.guardian_state_path.write_text(result.to_json() + "\n", encoding="utf-8")
    return result


def _write_stop(path: Path, findings: Sequence[GuardianFinding]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["desktop guardian stop", f"created_at={datetime.now().isoformat(timespec='seconds')}"]
    lines.extend(f"{finding.code}: {finding.summary}" for finding in findings)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _state_text(state: dict[str, Any]) -> str:
    return json.dumps(state, ensure_ascii=False, sort_keys=True, default=str)


def _contains_marker(text: str, markers: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers)


def _matched_markers(text: str, markers: Iterable[str]) -> list[str]:
    lowered = text.lower()
    return [marker for marker in markers if marker.lower() in lowered]


def _same_action_repeat(records: Any, *, limit: int) -> dict[str, Any]:
    if not isinstance(records, Sequence):
        return {}
    keys = [_action_key(record) for record in records]
    keys = [key for key in keys if key]
    if len(keys) < limit:
        return {}
    tail = keys[-limit:]
    if len(set(tail)) != 1:
        return {}
    return {"action": tail[0], "count": limit}


def _action_key(record: Any) -> str:
    if not isinstance(record, dict):
        return ""
    phase = str(record.get("phase") or "")
    if phase not in {"act", "decide"}:
        return ""
    data = record.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    if phase == "decide":
        action = str(data.get("action") or "")
        args = data.get("args") or {}
    else:
        action = str(data.get("action") or data.get("name") or "")
        args = data.get("args") or data.get("data") or {}
    if not action:
        return ""
    return action + ":" + json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)


def _ledger_findings(query_events_path: Path, trajectory_path: Path) -> list[GuardianFinding]:
    findings: list[GuardianFinding] = []
    try:
        query_events = read_query_events(query_events_path)
    except (OSError, ValueError) as exc:
        findings.append(GuardianFinding("query_events_unreadable", "stop", f"query events unreadable: {type(exc).__name__}: {exc}", data={"path": str(query_events_path)}))
    else:
        if not query_events:
            findings.append(GuardianFinding("query_events_missing", "stop", "desktop state has records but query events are missing", data={"path": str(query_events_path)}))
    try:
        trajectory_events = read_events(trajectory_path)
    except (OSError, ValueError) as exc:
        findings.append(GuardianFinding("trajectory_unreadable", "stop", f"trajectory unreadable: {type(exc).__name__}: {exc}", data={"path": str(trajectory_path)}))
    else:
        if not trajectory_events:
            findings.append(GuardianFinding("trajectory_missing", "stop", "desktop state has records but trajectory is missing", data={"path": str(trajectory_path)}))
    return findings


def _last_event_age(paths: _GuardianPaths, *, now: Callable[[], float]) -> float | None:
    mtimes = []
    for path in (paths.state_path, paths.query_events_path, paths.trajectory_path):
        try:
            if path.exists():
                mtimes.append(path.stat().st_mtime)
        except OSError:
            continue
    if not mtimes:
        return None
    return max(0.0, now() - max(mtimes))


def _summary(findings: Sequence[GuardianFinding], status: str) -> str:
    if not findings:
        return "guardian checks passed"
    stop_count = sum(1 for finding in findings if finding.stop)
    if stop_count:
        return f"guardian wrote STOP after {stop_count} stop finding(s): " + ", ".join(finding.code for finding in findings if finding.stop)
    return f"guardian found {len(findings)} warning(s): " + ", ".join(finding.code for finding in findings)
