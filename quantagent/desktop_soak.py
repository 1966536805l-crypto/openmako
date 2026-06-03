from __future__ import annotations

import json
import inspect
import multiprocessing as mp
import os
import queue
import time
import uuid
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from .desktop_eval import BLOCKED, FAILURE, STOPPED, SUCCESS, TIMEOUT, run_desktop_eval
from .desktop_guardian import inspect_desktop_guardian


@dataclass(frozen=True)
class DesktopSoakCycle:
    cycle: int
    eval_run_id: str
    status: str
    ok: bool
    summary: str
    json_path: str = ""
    report_path: str = ""
    guardian_status: str = ""
    guardian_ok: bool = True
    guardian_summary: str = ""
    duration_ms: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)
    evidence_ok: bool = True
    evidence_findings: tuple[str, ...] = ()
    watchdog_status: str = ""
    watchdog_summary: str = ""
    watchdog_checks: int = 0
    watchdog_killed: bool = False

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DesktopSoakResult:
    ok: bool
    status: str
    summary: str
    run_id: str
    report_path: str
    json_path: str
    metrics: dict[str, Any]
    cycles: tuple[DesktopSoakCycle, ...]
    project: str = ""
    suite: str = ""
    started_at: str = ""
    finished_at: str = ""
    stop_file: str = ""
    state_path: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "summary": self.summary,
            "run_id": self.run_id,
            "report_path": self.report_path,
            "json_path": self.json_path,
            "metrics": dict(self.metrics),
            "cycles": [cycle.to_payload() for cycle in self.cycles],
            "project": self.project,
            "suite": self.suite,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "stop_file": self.stop_file,
            "state_path": self.state_path,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False, indent=2)


EvalRunner = Callable[..., Any]
GuardianRunner = Callable[..., Any]


def run_desktop_soak(
    project: str | Path,
    *,
    suite: str = "suite_live",
    hours: float = 4.0,
    interval_seconds: float = 60.0,
    max_cycles: int = 0,
    max_steps: int = 100,
    execute: bool = False,
    reviewed: bool = False,
    allow_actions: bool = False,
    guardian: bool = True,
    require_evidence: bool = False,
    watchdog: bool = True,
    cycle_timeout_seconds: float = 0.0,
    watchdog_interval_seconds: float = 2.0,
    stop_file: str | Path | None = None,
    run_eval: EvalRunner = run_desktop_eval,
    inspect_guardian: GuardianRunner = inspect_desktop_guardian,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> DesktopSoakResult:
    project_path = Path(project).expanduser()
    run_dir = project_path / ".quantagent" / "desktop" / "soak"
    run_dir.mkdir(parents=True, exist_ok=True)
    run_id = "soak_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    json_path = run_dir / f"{run_id}.json"
    report_path = run_dir / f"{run_id}.md"
    state_path = run_dir / "latest_state.json"
    stop_path = _resolve_path(project_path, stop_file, run_dir / "STOP")
    started_at = datetime.now().isoformat(timespec="seconds")
    started = float(now())
    cycles: list[DesktopSoakCycle] = []
    seen_eval_run_ids: set[str] = set()
    status = SUCCESS
    summary = ""
    bounded_hours = max(0.0, float(hours))
    bounded_interval = max(0.0, min(float(interval_seconds), 3600.0))
    bounded_max_cycles = max(0, int(max_cycles))
    bounded_max_steps = max(1, min(int(max_steps), 100000))
    deadline = started + bounded_hours * 3600.0

    if suite != "suite_live":
        status = BLOCKED
        summary = "desktop soak only allows suite_live until non-live suites have safe-action contracts"
        return _finish_soak(
            project_path,
            suite,
            run_id,
            json_path,
            report_path,
            state_path,
            stop_path,
            started_at,
            started,
            float(now()),
            status,
            summary,
            cycles,
        )

    missing = _missing_execution_gates(execute=execute, reviewed=reviewed, allow_actions=allow_actions)
    if missing:
        status = BLOCKED
        summary = "desktop soak execution blocked; requires " + ", ".join(missing)
        return _finish_soak(
            project_path,
            suite,
            run_id,
            json_path,
            report_path,
            state_path,
            stop_path,
            started_at,
            started,
            float(now()),
            status,
            summary,
            cycles,
        )

    while True:
        current = float(now())
        if stop_path.exists():
            status = STOPPED
            summary = f"STOP file present: {stop_path}"
            break
        if bounded_max_cycles and len(cycles) >= bounded_max_cycles:
            summary = f"desktop soak max_cycles reached: {len(cycles)}"
            break
        if bounded_hours > 0 and current >= deadline:
            summary = f"desktop soak duration reached: {bounded_hours:.2f}h"
            break
        if bounded_hours <= 0 and not bounded_max_cycles:
            status = TIMEOUT
            summary = "desktop soak has no duration or max_cycles budget"
            break
        if bounded_hours > 0 and cycles:
            remaining_seconds = max(0.0, deadline - current)
            if remaining_seconds < _minimum_tail_cycle_seconds(float(cycle_timeout_seconds)):
                if remaining_seconds > 0:
                    sleep(remaining_seconds)
                summary = f"desktop soak duration reached: {bounded_hours:.2f}h"
                break

        cycle_started = float(now())
        remaining_minutes = max(0.1, (deadline - cycle_started) / 60.0) if bounded_hours > 0 else 60.0
        eval_kwargs = {
            "suite": suite,
            "duration_minutes": min(60.0, remaining_minutes),
            "max_steps": bounded_max_steps,
            "execute": True,
            "reviewed": True,
            "allow_actions": True,
            "stop_file": stop_path,
        }
        eval_payload, watchdog_payload = _run_eval_cycle(
            project_path,
            run_eval,
            eval_kwargs,
            watchdog=bool(watchdog),
            cycle_timeout_seconds=float(cycle_timeout_seconds),
            watchdog_interval_seconds=float(watchdog_interval_seconds),
            stop_path=stop_path,
            guardian=guardian,
            inspect_guardian=inspect_guardian,
        )
        evidence = _inspect_cycle_evidence(project_path, eval_payload, suite=suite, seen_eval_run_ids=seen_eval_run_ids) if require_evidence else {"ok": True, "findings": (), "paths": {}}
        evidence_paths = evidence.get("paths") if isinstance(evidence.get("paths"), Mapping) else {}
        guardian_payload: dict[str, Any] = {}
        if guardian and watchdog_payload.get("guardian"):
            guardian_payload = _payload(watchdog_payload.get("guardian"))
        elif guardian:
            guardian_payload = _payload(_inspect_cycle_guardian(inspect_guardian, project_path, stop_path, evidence_paths))

        cycle = DesktopSoakCycle(
            cycle=len(cycles) + 1,
            eval_run_id=str(eval_payload.get("run_id") or ""),
            status=str(eval_payload.get("status") or FAILURE),
            ok=bool(eval_payload.get("ok")),
            summary=str(eval_payload.get("summary") or ""),
            json_path=str(eval_payload.get("json_path") or ""),
            report_path=str(eval_payload.get("report_path") or ""),
            guardian_status=str(guardian_payload.get("status") or ""),
            guardian_ok=bool(guardian_payload.get("ok", True)),
            guardian_summary=str(guardian_payload.get("summary") or ""),
            duration_ms=max(0, round((float(now()) - cycle_started) * 1000)),
            metrics=_payload(eval_payload.get("metrics") or {}),
            evidence_ok=bool(evidence.get("ok", True)),
            evidence_findings=tuple(str(item) for item in evidence.get("findings", ()) if str(item)),
            watchdog_status=str(watchdog_payload.get("status") or ""),
            watchdog_summary=str(watchdog_payload.get("summary") or ""),
            watchdog_checks=max(0, int(watchdog_payload.get("checks", 0) or 0)),
            watchdog_killed=bool(watchdog_payload.get("killed", False)),
        )
        cycles.append(cycle)
        _write_state(state_path, status="running", run_id=run_id, suite=suite, cycles=cycles, stop_file=stop_path)

        if not cycle.ok:
            status = _failure_status(cycle.status)
            summary = f"desktop soak stopped after eval failure in cycle {cycle.cycle}: {cycle.summary}"
            break
        if require_evidence and not cycle.evidence_ok:
            status = BLOCKED
            summary = f"desktop soak evidence failed in cycle {cycle.cycle} ({cycle.eval_run_id or '<missing>'}): {', '.join(cycle.evidence_findings)}"
            break
        if guardian and not cycle.guardian_ok:
            status = STOPPED if cycle.guardian_status == STOPPED else FAILURE
            summary = f"desktop soak guardian stopped cycle {cycle.cycle}: {cycle.guardian_summary}"
            break

        if bounded_interval > 0:
            sleep_for = bounded_interval
            if bounded_hours > 0:
                sleep_for = min(sleep_for, max(0.0, deadline - float(now())))
            if sleep_for > 0:
                sleep(sleep_for)

    if not summary:
        summary = f"desktop soak completed: cycles={len(cycles)}"
    finished = float(now())
    return _finish_soak(
        project_path,
        suite,
        run_id,
        json_path,
        report_path,
        state_path,
        stop_path,
        started_at,
        started,
        finished,
        status,
        summary,
        cycles,
    )


def render_desktop_soak_result(result: DesktopSoakResult) -> str:
    gates = result.metrics.get("level_gates") if isinstance(result.metrics.get("level_gates"), Mapping) else {}
    failed_gates = [str(key) for key, value in gates.items() if value is False]
    lines = [
        "# Desktop Soak Run",
        "",
        f"- run_id: {result.run_id}",
        f"- status: {result.status}",
        f"- ok: {str(result.ok).lower()}",
        f"- project: {result.project}",
        f"- suite: {result.suite}",
        f"- cycles: {result.metrics.get('runs', 0)}",
        f"- long_run_hours: {result.metrics.get('long_run_hours', 0):.3f}",
        f"- success_rate: {result.metrics.get('success_rate', 0):.3f}",
        f"- guardian_stops: {result.metrics.get('guardian_stops', 0)}",
        f"- evidence_failures: {result.metrics.get('evidence_failures', 0)}",
        f"- watchdog_kills: {result.metrics.get('watchdog_kills', 0)}",
        f"- level: {result.metrics.get('level', '-')}",
        f"- score: {result.metrics.get('score', '-')}",
        f"- stop_file: {result.stop_file}",
        f"- failed_gates: {', '.join(failed_gates) if failed_gates else 'none'}",
        "",
        "## Cycles",
        "",
    ]
    if not result.cycles:
        lines.append("- none")
    else:
        for cycle in result.cycles:
            guardian = f", guardian={cycle.guardian_status}" if cycle.guardian_status else ""
            evidence = "" if cycle.evidence_ok else f", evidence={'; '.join(cycle.evidence_findings)}"
            watchdog_text = f", watchdog={cycle.watchdog_status}" if cycle.watchdog_status and cycle.watchdog_status != "ok" else ""
            lines.append(f"- [{cycle.status}] cycle {cycle.cycle}: {cycle.summary}{guardian}{evidence}{watchdog_text}")
    reasons = result.metrics.get("level_reasons")
    if isinstance(reasons, list) and reasons:
        lines.extend(["", "## Level Reasons", ""])
        lines.extend(f"- {reason}" for reason in reasons)
    return "\n".join(lines).rstrip() + "\n"


def load_desktop_soak_run(path: str | Path) -> DesktopSoakResult:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return _result_from_payload(payload)


def list_desktop_soak_runs(project: str | Path) -> list[DesktopSoakResult]:
    root = _soak_dir(Path(project).expanduser().resolve(strict=False))
    return [load_desktop_soak_run(path) for path in sorted(root.glob("soak_*.json")) if path.name != "latest_state.json"]


def latest_desktop_soak_run(project: str | Path) -> DesktopSoakResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    root = _soak_dir(project_path)
    state_path = root / "latest_state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(state, Mapping):
            run_id = str(state.get("run_id") or "")
            json_path = root / f"{run_id}.json" if run_id else Path()
            if run_id and json_path.exists():
                return load_desktop_soak_run(json_path)
            return _running_result_from_state(project_path, root, state_path, state)
    runs = list_desktop_soak_runs(project_path)
    if not runs:
        raise FileNotFoundError(f"no desktop soak runs found in {root}")
    return runs[-1]


def _finish_soak(
    project: Path,
    suite: str,
    run_id: str,
    json_path: Path,
    report_path: Path,
    state_path: Path,
    stop_path: Path,
    started_at: str,
    started: float,
    finished: float,
    status: str,
    summary: str,
    cycles: list[DesktopSoakCycle],
) -> DesktopSoakResult:
    finished_at = datetime.now().isoformat(timespec="seconds")
    metrics = _metrics(cycles, elapsed_seconds=max(0.0, finished - started))
    result = DesktopSoakResult(
        ok=status == SUCCESS,
        status=status,
        summary=summary,
        run_id=run_id,
        report_path=str(report_path),
        json_path=str(json_path),
        metrics=metrics,
        cycles=tuple(cycles),
        project=str(project),
        suite=suite,
        started_at=started_at,
        finished_at=finished_at,
        stop_file=str(stop_path),
        state_path=str(state_path),
    )
    _write_state(state_path, status=status, run_id=run_id, suite=suite, cycles=cycles, stop_file=stop_path, summary=summary)
    json_path.write_text(result.to_json() + "\n", encoding="utf-8")
    report_path.write_text(render_desktop_soak_result(result), encoding="utf-8")
    return result


def _running_result_from_state(project: Path, root: Path, state_path: Path, state: Mapping[str, Any]) -> DesktopSoakResult:
    run_id = str(state.get("run_id") or "running")
    cycles = max(0, _to_int(state.get("cycles"), 0))
    stop_file = str(state.get("stop_file") or root / "STOP")
    status = str(state.get("status") or "running")
    summary = str(state.get("summary") or "desktop soak still running")
    started_at, elapsed_seconds = _elapsed_from_run_id(run_id)
    metrics: dict[str, Any] = {
        "runs": cycles,
        "total": 0,
        "total_tasks": 0,
        "successful_tasks": 0,
        SUCCESS: 0,
        FAILURE: 0,
        BLOCKED: 0,
        STOPPED: 0,
        TIMEOUT: 0,
        "guardian_checks": cycles,
        "guardian_stops": 0,
        "evidence_failures": int(state.get("evidence_failures", 0) or 0),
        "evidence_ok": False,
        "watchdog_checks": int(state.get("watchdog_checks", 0) or 0),
        "watchdog_kills": int(state.get("watchdog_kills", 0) or 0),
        "watchdog_timeouts": int(state.get("watchdog_timeouts", 0) or 0),
        "success_rate": 0.0,
        "misoperations": 0,
        "misoperation_rate": 0.0,
        "crashes": 0,
        "crash_rate": 0.0,
        "long_run_seconds": elapsed_seconds,
        "long_run_minutes": elapsed_seconds / 60.0,
        "long_run_hours": elapsed_seconds / 3600.0,
        "autopsy_coverage": 1.0,
        "recovery_rate": 1.0,
        "score": 0,
        "level": "running",
        "last_eval_run_id": str(state.get("last_eval_run_id") or ""),
    }
    return DesktopSoakResult(
        ok=status in {SUCCESS, "running"},
        status=status,
        summary=summary,
        run_id=run_id,
        report_path=str(root / f"{run_id}.md"),
        json_path=str(root / f"{run_id}.json"),
        metrics=metrics,
        cycles=(),
        project=str(project),
        suite=str(state.get("suite") or "suite_live"),
        started_at=started_at,
        finished_at=str(state.get("heartbeat_at") or ""),
        stop_file=stop_file,
        state_path=str(state_path),
    )


def _metrics(cycles: list[DesktopSoakCycle], *, elapsed_seconds: float) -> dict[str, Any]:
    total_tasks = sum(_metric_int(cycle.metrics, "total") for cycle in cycles)
    success = sum(_metric_int(cycle.metrics, SUCCESS) for cycle in cycles)
    failure = sum(_metric_int(cycle.metrics, FAILURE) for cycle in cycles)
    blocked = sum(_metric_int(cycle.metrics, BLOCKED) for cycle in cycles)
    stopped = sum(_metric_int(cycle.metrics, STOPPED) for cycle in cycles)
    timeout = sum(_metric_int(cycle.metrics, TIMEOUT) for cycle in cycles)
    steps = sum(_metric_int(cycle.metrics, "steps") for cycle in cycles)
    recovery_attempts = sum(_metric_int(cycle.metrics, "recovery_attempts") for cycle in cycles)
    recovery_successes = sum(_metric_int(cycle.metrics, "recovery_successes") for cycle in cycles)
    autopsies = sum(_metric_int(cycle.metrics, "autopsies") for cycle in cycles)
    misoperations = sum(_metric_int(cycle.metrics, "misoperations") for cycle in cycles)
    crashes = sum(_metric_int(cycle.metrics, "crashes") for cycle in cycles)
    evidence_failures = sum(1 for cycle in cycles if not cycle.evidence_ok)
    watchdog_checks = sum(max(0, int(cycle.watchdog_checks)) for cycle in cycles)
    watchdog_kills = sum(1 for cycle in cycles if cycle.watchdog_killed)
    watchdog_timeouts = sum(1 for cycle in cycles if cycle.watchdog_status == TIMEOUT)
    non_success = max(0, total_tasks - success)
    metrics: dict[str, Any] = {
        "runs": len(cycles),
        "total": total_tasks,
        "total_tasks": total_tasks,
        "successful_tasks": success,
        SUCCESS: success,
        FAILURE: failure,
        BLOCKED: blocked,
        STOPPED: stopped,
        TIMEOUT: timeout,
        "failures": non_success,
        "steps": steps,
        "recovery_attempts": recovery_attempts,
        "recovery_successes": recovery_successes,
        "manual_interventions": sum(_metric_int(cycle.metrics, "manual_interventions") for cycle in cycles),
        "autopsies": autopsies,
        "misoperations": misoperations,
        "crashes": crashes,
        "duration_ms": round(elapsed_seconds * 1000),
        "long_run_seconds": elapsed_seconds,
        "long_run_minutes": elapsed_seconds / 60.0,
        "long_run_hours": elapsed_seconds / 3600.0,
        "guardian_checks": sum(1 for cycle in cycles if cycle.guardian_status),
        "guardian_stops": sum(1 for cycle in cycles if cycle.guardian_status and not cycle.guardian_ok),
        "evidence_failures": evidence_failures,
        "evidence_ok": evidence_failures == 0,
        "watchdog_checks": watchdog_checks,
        "watchdog_kills": watchdog_kills,
        "watchdog_timeouts": watchdog_timeouts,
    }
    metrics["success_rate"] = success / total_tasks if total_tasks > 0 else 0.0
    metrics["misoperation_rate"] = misoperations / max(1, steps)
    metrics["crash_rate"] = crashes / max(1, len(cycles))
    metrics["autopsy_coverage"] = 1.0 if non_success <= 0 else autopsies / non_success
    metrics["recovery_rate"] = 1.0 if recovery_attempts <= 0 else recovery_successes / recovery_attempts
    try:
        from .desktop_level_score import score_desktop_level

        score = score_desktop_level(metrics)
        metrics["score"] = score.score
        metrics["level"] = score.level
        metrics["level_reasons"] = list(score.reasons)
        metrics["level_gates"] = score.gates
    except ImportError:
        metrics["score"] = 0
        metrics["level"] = "unknown"
    return metrics


def _write_state(
    path: Path,
    *,
    status: str,
    run_id: str,
    suite: str,
    cycles: list[DesktopSoakCycle],
    stop_file: Path,
    summary: str = "",
) -> None:
    payload = {
        "status": status,
        "run_id": run_id,
        "suite": suite,
        "summary": summary,
        "heartbeat_at": datetime.now().isoformat(timespec="seconds"),
        "cycles": len(cycles),
        "last_eval_run_id": cycles[-1].eval_run_id if cycles else "",
        "evidence_failures": sum(1 for cycle in cycles if not cycle.evidence_ok),
        "watchdog_checks": sum(max(0, int(cycle.watchdog_checks)) for cycle in cycles),
        "watchdog_kills": sum(1 for cycle in cycles if cycle.watchdog_killed),
        "watchdog_timeouts": sum(1 for cycle in cycles if cycle.watchdog_status == TIMEOUT),
        "stop_file": str(stop_file),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _missing_execution_gates(*, execute: bool, reviewed: bool, allow_actions: bool) -> list[str]:
    missing: list[str] = []
    if not execute:
        missing.append("--execute")
    if not reviewed:
        missing.append("--reviewed")
    if not allow_actions:
        missing.append("--allow-actions")
    return missing


def _failure_status(status: str) -> str:
    normalized = str(status or "").lower()
    if normalized in {BLOCKED, STOPPED, TIMEOUT, FAILURE}:
        return normalized
    return FAILURE


def _minimum_tail_cycle_seconds(cycle_timeout_seconds: float) -> float:
    timeout = max(0.0, float(cycle_timeout_seconds))
    if timeout > 0:
        return max(1.0, min(timeout, 3600.0))
    return 120.0


def _run_eval_cycle(
    project: Path,
    run_eval: EvalRunner,
    eval_kwargs: Mapping[str, Any],
    *,
    watchdog: bool,
    cycle_timeout_seconds: float,
    watchdog_interval_seconds: float,
    stop_path: Path,
    guardian: bool,
    inspect_guardian: GuardianRunner,
) -> tuple[dict[str, Any], dict[str, Any]]:
    implicit_default_watchdog = run_eval is run_desktop_eval
    timeout = _cycle_timeout_seconds(eval_kwargs, cycle_timeout_seconds, watchdog and implicit_default_watchdog)
    use_process = watchdog and (cycle_timeout_seconds > 0 or implicit_default_watchdog)
    if not use_process:
        return _payload(run_eval(project, **dict(eval_kwargs))), {"ok": True, "status": "inline", "summary": "eval ran inline", "checks": 0}

    ctx = _multiprocessing_context()
    result_queue: Any = ctx.Queue(maxsize=1)
    process = ctx.Process(target=_eval_worker, args=(run_eval, str(project), _json_safe_mapping(dict(eval_kwargs)), result_queue))
    process.start()
    deadline = time.monotonic() + timeout if timeout > 0 else 0.0
    interval = max(0.02, min(float(watchdog_interval_seconds or 0.0), 30.0))
    checks = 0
    guardian_payload: dict[str, Any] = {}
    while process.is_alive():
        process.join(timeout=interval)
        if not process.is_alive():
            break
        checks += 1
        if stop_path.exists():
            _terminate_process(process)
            return (
                _watchdog_eval_payload(STOPPED, f"STOP file present while eval was running: {stop_path}"),
                {"ok": False, "status": STOPPED, "summary": f"STOP file present: {stop_path}", "checks": checks, "killed": True},
            )
        if deadline and time.monotonic() >= deadline:
            _terminate_process(process)
            return (
                _watchdog_eval_payload(TIMEOUT, f"desktop soak eval timed out after {timeout:.2f}s"),
                {"ok": False, "status": TIMEOUT, "summary": f"eval timed out after {timeout:.2f}s", "checks": checks, "killed": True},
            )
        if guardian:
            guardian_payload = _payload(_inspect_cycle_guardian(inspect_guardian, project, stop_path, {}))
            if not bool(guardian_payload.get("ok", True)):
                status = STOPPED if str(guardian_payload.get("status") or "") == STOPPED else FAILURE
                summary = str(guardian_payload.get("summary") or "guardian stopped running eval")
                _terminate_process(process)
                return (
                    _watchdog_eval_payload(status, f"desktop soak watchdog stopped eval: {summary}"),
                    {"ok": False, "status": status, "summary": summary, "checks": checks, "killed": True, "guardian": guardian_payload},
                )

    process.join(timeout=1)
    try:
        item = result_queue.get_nowait()
    except queue.Empty:
        if process.exitcode not in (0, None):
            return (
                _watchdog_eval_payload(FAILURE, f"desktop soak eval process exited with code {process.exitcode}"),
                {"ok": False, "status": FAILURE, "summary": f"eval process exited with code {process.exitcode}", "checks": checks, "killed": False},
            )
        return _watchdog_eval_payload(FAILURE, "desktop soak eval process returned no result"), {"ok": False, "status": FAILURE, "summary": "eval process returned no result", "checks": checks, "killed": False}
    payload = item.get("payload") if isinstance(item, Mapping) else {}
    if not isinstance(payload, Mapping):
        payload = {"ok": False, "status": FAILURE, "summary": "eval process returned invalid payload"}
    watchdog_payload = {"ok": bool(item.get("ok", False)) if isinstance(item, Mapping) else False, "status": "ok", "summary": "eval completed under watchdog", "checks": checks, "killed": False}
    return _payload(payload), watchdog_payload


def _eval_worker(run_eval: EvalRunner, project: str, eval_kwargs: dict[str, Any], result_queue: Any) -> None:
    try:
        kwargs = dict(eval_kwargs)
        if kwargs.get("stop_file"):
            kwargs["stop_file"] = Path(str(kwargs["stop_file"]))
        result_queue.put({"ok": True, "payload": _payload(run_eval(Path(project), **kwargs))})
    except BaseException as exc:  # noqa: BLE001 - child process must serialize failure.
        result_queue.put({"ok": False, "payload": {"ok": False, "status": FAILURE, "summary": f"{type(exc).__name__}: {exc}", "error_type": type(exc).__name__}})


def _cycle_timeout_seconds(eval_kwargs: Mapping[str, Any], explicit: float, watchdog: bool) -> float:
    if explicit > 0:
        return max(0.05, float(explicit))
    if not watchdog:
        return 0.0
    try:
        duration = float(eval_kwargs.get("duration_minutes", 0.0) or 0.0) * 60.0
    except (TypeError, ValueError):
        duration = 0.0
    return duration + 30.0 if duration > 0 else 0.0


def _watchdog_eval_payload(status: str, summary: str) -> dict[str, Any]:
    return {"ok": False, "status": status, "summary": summary, "run_id": "watchdog-" + uuid.uuid4().hex[:8], "metrics": {"total": 1, status: 1, "steps": 0}}


def _multiprocessing_context() -> Any:
    methods = mp.get_all_start_methods()
    if "fork" in methods and os.name != "nt":
        return mp.get_context("fork")
    return mp.get_context()


def _terminate_process(process: Any) -> None:
    if not process.is_alive():
        return
    process.terminate()
    process.join(timeout=1)
    if process.is_alive() and hasattr(process, "kill"):
        process.kill()
        process.join(timeout=1)


def _json_safe_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_safe(item) for key, item in value.items()}


def _inspect_cycle_guardian(
    inspect_guardian: GuardianRunner,
    project: Path,
    stop_path: Path,
    evidence_paths: Mapping[str, Any],
) -> Any:
    state_path = evidence_paths.get("state_path") or stop_path.parent / "cycle_guardian_state.json"
    kwargs = {
        "stop_file": stop_path,
        "state_path": state_path,
        "query_events_path": evidence_paths.get("query_events_path") or None,
        "trajectory_path": evidence_paths.get("trajectory_path") or None,
    }
    try:
        params = inspect.signature(inspect_guardian).parameters
    except (TypeError, ValueError):
        return inspect_guardian(project)
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()):
        return inspect_guardian(project, **kwargs)
    accepted = {name: value for name, value in kwargs.items() if name in params}
    return inspect_guardian(project, **accepted)


def _inspect_cycle_evidence(
    project: Path,
    eval_payload: Mapping[str, Any],
    *,
    suite: str,
    seen_eval_run_ids: set[str],
) -> dict[str, Any]:
    findings: list[str] = []
    paths: dict[str, str] = {}
    run_id = str(eval_payload.get("run_id") or "").strip()
    if not run_id:
        findings.append("missing eval_run_id")
    elif run_id in seen_eval_run_ids:
        findings.append(f"duplicate eval_run_id: {run_id}")
    else:
        seen_eval_run_ids.add(run_id)

    json_path_text = str(eval_payload.get("json_path") or "").strip()
    if not json_path_text:
        findings.append("missing eval json_path")
        eval_json: dict[str, Any] = {}
    else:
        json_path = _resolve_path(project, json_path_text, Path(json_path_text))
        paths["json_path"] = str(json_path)
        if not json_path.exists() or json_path.stat().st_size <= 0:
            findings.append(f"eval json missing or empty: {json_path}")
            eval_json = {}
        else:
            try:
                loaded = json.loads(json_path.read_text(encoding="utf-8"))
                eval_json = loaded if isinstance(loaded, dict) else {}
                if not isinstance(loaded, dict):
                    findings.append(f"eval json is not an object: {json_path}")
            except (OSError, json.JSONDecodeError) as exc:
                findings.append(f"eval json unreadable: {type(exc).__name__}: {json_path}")
                eval_json = {}

    if eval_json:
        json_run_id = str(eval_json.get("run_id") or "").strip()
        if run_id and json_run_id and json_run_id != run_id:
            findings.append(f"eval json run_id mismatch: {json_run_id} != {run_id}")
        json_suite = str(eval_json.get("suite") or "").strip()
        if json_suite and json_suite != suite:
            findings.append(f"eval json suite mismatch: {json_suite} != {suite}")
        if "ok" in eval_json and bool(eval_json.get("ok")) != bool(eval_payload.get("ok")):
            findings.append("eval json ok mismatch")
        json_status = str(eval_json.get("status") or "").strip()
        payload_status = str(eval_payload.get("status") or "").strip()
        if json_status and payload_status and json_status != payload_status:
            findings.append(f"eval json status mismatch: {json_status} != {payload_status}")

    report_path_text = str(eval_payload.get("report_path") or eval_json.get("report_path") or "").strip()
    if report_path_text:
        report_path = _resolve_path(project, report_path_text, Path(report_path_text))
        paths["report_path"] = str(report_path)
        if not report_path.exists() or report_path.stat().st_size <= 0:
            findings.append(f"eval report missing or empty: {report_path}")

    state_value = str(eval_payload.get("state_path") or eval_json.get("state_path") or "").strip()
    if state_value:
        state_path = _resolve_path(project, state_value, Path(state_value))
        paths["state_path"] = str(state_path)
        if not state_path.exists() or state_path.stat().st_size <= 0:
            findings.append(f"state_path missing or empty: {state_path}")

    for key in ("query_events_path", "trajectory_path"):
        value = str(eval_payload.get(key) or eval_json.get(key) or "").strip()
        if not value:
            findings.append(f"missing {key}")
            continue
        path = _resolve_path(project, value, Path(value))
        paths[key] = str(path)
        if not path.exists() or path.stat().st_size <= 0:
            findings.append(f"{key} missing or empty: {path}")

    return {"ok": not findings, "findings": tuple(findings), "paths": paths}


def _metric_int(metrics: Mapping[str, Any], key: str) -> int:
    try:
        return max(0, int(metrics.get(key, 0) or 0))
    except (TypeError, ValueError):
        return 0


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _elapsed_from_run_id(run_id: str) -> tuple[str, float]:
    parts = str(run_id or "").split("_")
    if len(parts) < 3 or parts[0] != "soak":
        return "", 0.0
    stamp = "_".join(parts[1:3])
    try:
        started = datetime.strptime(stamp, "%Y%m%d_%H%M%S")
    except ValueError:
        return "", 0.0
    elapsed = max(0.0, (datetime.now() - started).total_seconds())
    return started.isoformat(timespec="seconds"), elapsed


def _soak_dir(project: Path) -> Path:
    directory = project / ".quantagent" / "desktop" / "soak"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _result_from_payload(payload: Mapping[str, Any]) -> DesktopSoakResult:
    cycles = tuple(DesktopSoakCycle(**dict(item)) for item in payload.get("cycles", ()))
    return DesktopSoakResult(
        ok=bool(payload.get("ok")),
        status=str(payload.get("status") or FAILURE),
        summary=str(payload.get("summary") or ""),
        run_id=str(payload.get("run_id") or ""),
        report_path=str(payload.get("report_path") or ""),
        json_path=str(payload.get("json_path") or ""),
        metrics=_payload(payload.get("metrics", {})),
        cycles=cycles,
        project=str(payload.get("project") or ""),
        suite=str(payload.get("suite") or ""),
        started_at=str(payload.get("started_at") or ""),
        finished_at=str(payload.get("finished_at") or ""),
        stop_file=str(payload.get("stop_file") or ""),
        state_path=str(payload.get("state_path") or ""),
    )


def _resolve_path(project: Path, value: str | Path | None, default: Path) -> Path:
    path = Path(value).expanduser() if value is not None else default
    if not path.is_absolute():
        path = project / path
    return path


def _payload(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if is_dataclass(value):
        return _payload(asdict(value))
    if hasattr(value, "to_payload"):
        return _payload(value.to_payload())
    if hasattr(value, "to_dict"):
        return _payload(value.to_dict())
    if hasattr(value, "__dict__"):
        return {str(key): _json_safe(item) for key, item in vars(value).items() if not key.startswith("_")}
    return {"value": _json_safe(value)}


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if hasattr(value, "to_payload"):
        return _json_safe(value.to_payload())
    return str(value)
