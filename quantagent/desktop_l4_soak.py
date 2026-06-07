from __future__ import annotations

import inspect
import json
import multiprocessing as mp
import os
import queue
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .desktop_control import desktop_dir
from .desktop_daemon_policy import authorize_daemon_action, classify_goal_risk
from .exception_audit import audit_suppressed_exception
from .desktop_intelligence import build_desktop_tokenization
from .trajectory import record_action, record_observation, record_step


Hook = Callable[..., Any]

SUCCESS = "success"
RUNNING = "running"
STOPPED = "stopped"
PAUSED = "paused"
BLOCKED = "blocked"
TIMEOUT = "timeout"
VERIFY_FAILED = "verify_failed"

PERMISSION_MARKERS = (
    "permission_required",
    "permission denied",
    "permission is missing",
    "screen recording",
    "accessibility",
    "assistive access",
    "not authorized",
    "could not create image from display",
    "-25211",
)


@dataclass
class DesktopL4SoakConfig:
    project: str | Path
    cycles: int | None = None
    max_cycles: int = 3
    dry_run: bool = True
    execute: bool = False
    reviewed: bool = False
    allow_actions: bool = False
    interval_seconds: float = 0.0
    stop_file: str | Path = ""
    goal: str = ""
    same_action_limit: int = 3
    loop_threshold: int | None = None
    observe: Hook | None = None
    screenshot: Hook | None = None
    decide: Hook | None = None
    preflight: Hook | None = None
    execute_action: Hook | None = None
    verify: Hook | None = None
    act: Hook | None = None
    action: Hook | None = None
    driver: Any = None
    runner: Any = None
    phase_timeout_seconds: float = 0.0
    trajectory_path: str | Path = ""
    heartbeat_path: str | Path = ""
    status_path: str | Path = ""
    result_path: str | Path = ""
    sleep: Callable[[float], None] | None = None


@dataclass(frozen=True)
class DesktopL4SoakResult:
    status: str
    ok: bool
    summary: str
    metrics: dict[str, Any]
    trajectory_path: str
    heartbeat_path: str
    status_path: str
    result_path: str
    json_path: str
    stop_path: str
    findings: list[dict[str, Any]] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "ok": self.ok,
            "summary": self.summary,
            "metrics": dict(self.metrics),
            "trajectory_path": self.trajectory_path,
            "heartbeat_path": self.heartbeat_path,
            "status_path": self.status_path,
            "result_path": self.result_path,
            "json_path": self.json_path,
            "stop_path": self.stop_path,
            "findings": [_json_safe_dict(finding) for finding in self.findings],
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_payload()

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False, indent=2, sort_keys=True)


@dataclass
class _CycleContext:
    project: Path
    cycle: int
    goal: str
    dry_run: bool
    stop_path: Path
    trajectory_path: Path
    heartbeat_path: Path
    metrics: dict[str, Any]
    observation: dict[str, Any] = field(default_factory=dict)
    screenshot: dict[str, Any] = field(default_factory=dict)
    decision: dict[str, Any] = field(default_factory=dict)


def run_desktop_l4_soak(config: DesktopL4SoakConfig | Mapping[str, Any] | str | Path) -> DesktopL4SoakResult:
    cfg = _coerce_config(config)
    project = Path(cfg.project).expanduser().resolve(strict=False)
    run_dir = desktop_dir(project) / "l4_soak"
    run_dir.mkdir(parents=True, exist_ok=True)
    trajectory_path = _resolve_path(project, cfg.trajectory_path or "", run_dir / "trajectory.jsonl")
    heartbeat_path = _resolve_path(project, cfg.heartbeat_path or "", run_dir / "heartbeat.json")
    status_path = _resolve_path(project, cfg.status_path or "", run_dir / "status.json")
    result_path = _resolve_path(project, cfg.result_path or "", run_dir / "result.json")
    stop_path = _resolve_path(project, cfg.stop_file or "", run_dir / "STOP")
    cycles_value = cfg.cycles if cfg.cycles is not None else cfg.max_cycles
    cycles = max(0, int(cycles_value))
    same_action_limit = max(2, int(cfg.loop_threshold or cfg.same_action_limit))
    sleep = cfg.sleep or time.sleep
    findings: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {
        "cycles": 0,
        "cycles_requested": cycles,
        "cycles_started": 0,
        "cycles_completed": 0,
        "observations": 0,
        "screenshots": 0,
        "decisions": 0,
        "actions_executed": 0,
        "dry_run_actions": 0,
        "verifications": 0,
        "verification_failures": 0,
        "blocked_actions": 0,
        "blocked_goals": 0,
        "permission_failures": 0,
        "screenshot_failures": 0,
        "phase_timeouts": 0,
        "watchdog_checks": 0,
        "watchdog_kills": 0,
        "watchdog_timeouts": 0,
        "stop_checks": 0,
        "repeat_stops": 0,
        "loop_stops": 0,
        "dry_run": bool(cfg.dry_run),
        "trajectory_path": str(trajectory_path),
        "heartbeat_path": str(heartbeat_path),
        "status_path": str(status_path),
        "result_path": str(result_path),
        "stop_path": str(stop_path),
    }

    action_tail: list[str] = []
    status = RUNNING
    started_at = _utc_timestamp()
    record_step(
        trajectory_path,
        "desktop-l4-soak started",
        ok=True,
        dry_run=bool(cfg.dry_run),
        cycles=cycles,
        stop_file=str(stop_path),
        goal=cfg.goal,
    )

    missing_gates = _missing_live_gates(cfg)
    if missing_gates:
        finding = _finding(
            "execution_gate_missing",
            "desktop-l4-soak live execution blocked; requires " + ", ".join(missing_gates),
            severity="block",
            data={"missing": missing_gates},
        )
        findings.append(finding)
        record_step(trajectory_path, finding["summary"], ok=False, missing=missing_gates)
        return _finish(BLOCKED, metrics, trajectory_path, heartbeat_path, status_path, result_path, stop_path, findings, started_at, cycle=0)

    goal_risk = classify_goal_risk(cfg.goal)
    if goal_risk.blocked:
        metrics["blocked_goals"] = 1
        finding = _finding("high_risk_goal", goal_risk.reason, severity="block", data=goal_risk.to_payload())
        findings.append(finding)
        record_step(trajectory_path, finding["summary"], ok=False, risk=goal_risk.to_payload())
        status = BLOCKED
        return _finish(status, metrics, trajectory_path, heartbeat_path, status_path, result_path, stop_path, findings, started_at, cycle=0)

    _write_heartbeat(heartbeat_path, status, metrics, trajectory_path, stop_path, findings, started_at=started_at, cycle=0)
    _write_status(status_path, status, metrics, trajectory_path, heartbeat_path, stop_path, findings, started_at=started_at, cycle=0, summary="desktop-l4-soak running")

    for cycle in range(1, cycles + 1):
        metrics["stop_checks"] += 1
        if stop_path.exists():
            status = STOPPED
            finding = _finding("stop_present", f"STOP file present before observe: {stop_path}", severity="stop", data={"cycle": cycle})
            findings.append(finding)
            record_step(trajectory_path, finding["summary"], step=cycle, ok=False, stop_file=str(stop_path))
            break

        metrics["cycles_started"] += 1
        context = _CycleContext(project, cycle, cfg.goal, bool(cfg.dry_run), stop_path, trajectory_path, heartbeat_path, metrics)
        _write_heartbeat(heartbeat_path, RUNNING, metrics, trajectory_path, stop_path, findings, started_at=started_at, cycle=cycle)
        _write_status(status_path, RUNNING, metrics, trajectory_path, heartbeat_path, stop_path, findings, started_at=started_at, cycle=cycle, summary=f"cycle {cycle} running")

        screenshot = _invoke_phase(
            _resolve_hook(cfg, "screenshot"),
            context,
            default_status="ok",
            default_summary="dry-run screenshot",
            phase="screenshot",
            timeout_seconds=float(cfg.phase_timeout_seconds),
            stop_path=stop_path,
        )
        context.screenshot = screenshot
        metrics["screenshots"] += 1
        record_observation(trajectory_path, f"cycle {cycle} screenshot: {screenshot['summary']}", step=cycle, ok=screenshot["ok"], phase="screenshot", data=screenshot)
        if not screenshot["ok"]:
            status = _failure_status(screenshot, screenshot_failure=True)
            _record_failure(findings, metrics, "screenshot_failed", screenshot, cycle=cycle, screenshot_failure=True)
            break

        observation = _invoke_phase(
            _resolve_hook(cfg, "observe"),
            context,
            default_status="ok",
            default_summary="dry-run observation",
            phase="observe",
            timeout_seconds=float(cfg.phase_timeout_seconds),
            stop_path=stop_path,
        )
        context.observation = observation
        metrics["observations"] += 1
        record_observation(trajectory_path, f"cycle {cycle} observe: {observation['summary']}", step=cycle, ok=observation["ok"], phase="observe", data=observation)
        if not observation["ok"]:
            status = _failure_status(observation)
            _record_failure(findings, metrics, "observe_failed", observation, cycle=cycle)
            break

        decision = _invoke_decision(
            _resolve_hook(cfg, "decide"),
            context,
            observation,
            screenshot,
            phase="decide",
            timeout_seconds=float(cfg.phase_timeout_seconds),
            stop_path=stop_path,
        )
        context.decision = decision
        metrics["decisions"] += 1
        record_action(trajectory_path, f"cycle {cycle} decide: {decision['summary']}", step=cycle, ok=decision["ok"], phase="decide", decision=decision)
        if not decision["ok"] and str(decision.get("status") or "").lower() == TIMEOUT:
            status = TIMEOUT
            _record_failure(findings, metrics, "decision_timeout", decision, cycle=cycle)
            break
        if not decision["ok"] or str(decision.get("status") or "").lower() == BLOCKED:
            status = BLOCKED
            findings.append(_finding("decision_blocked", decision["summary"], severity="block", data={"cycle": cycle, "decision": decision}))
            metrics["blocked_actions"] += 1
            break

        preflight = _invoke_preflight(
            _resolve_hook(cfg, "preflight"),
            context,
            decision,
            phase="preflight",
            timeout_seconds=float(cfg.phase_timeout_seconds),
            stop_path=stop_path,
        )
        record_action(trajectory_path, f"cycle {cycle} preflight: {preflight['summary']}", step=cycle, ok=preflight["allowed"], phase="preflight", preflight=preflight)
        if str(preflight.get("status") or "").lower() == TIMEOUT:
            status = TIMEOUT
            _record_failure(findings, metrics, "preflight_timeout", preflight, cycle=cycle)
            break
        if not preflight["allowed"]:
            status = BLOCKED
            findings.append(_finding("preflight_blocked", preflight["summary"], severity="block", data={"cycle": cycle, "preflight": preflight, "decision": decision}))
            metrics["blocked_actions"] += 1
            break

        policy, policy_error = _authorize_decision(
            decision,
            goal=cfg.goal,
            execute=bool(cfg.execute or cfg.dry_run),
            reviewed=bool(cfg.reviewed or cfg.dry_run),
            allow_actions=bool(cfg.allow_actions or cfg.dry_run),
        )
        if policy_error:
            status = BLOCKED
            findings.append(_finding("unsupported_action", policy_error, severity="block", data={"cycle": cycle, "decision": decision}))
            metrics["blocked_actions"] += 1
            record_action(trajectory_path, f"cycle {cycle} blocked: {policy_error}", step=cycle, ok=False, phase="policy", decision=decision)
            break
        if policy is not None and policy.status == BLOCKED:
            status = BLOCKED
            findings.append(_finding("high_risk_action", policy.reason, severity="block", data={"cycle": cycle, "policy": policy.to_payload()}))
            metrics["blocked_actions"] += 1
            record_action(trajectory_path, f"cycle {cycle} blocked: {policy.reason}", step=cycle, ok=False, phase="policy", policy=policy.to_payload())
            break

        action_key = _action_key(decision)
        if action_key:
            action_tail.append(action_key)
            if _same_action_repeat(action_tail, same_action_limit):
                status = STOPPED
                metrics["repeat_stops"] += 1
                metrics["loop_stops"] += 1
                finding = _finding(
                    "same_action_repeat",
                    f"same desktop action repeated {same_action_limit} time(s): {action_key}",
                    severity="stop",
                    data={"cycle": cycle, "action": action_key, "count": same_action_limit},
                )
                findings.append(finding)
                record_action(trajectory_path, finding["summary"], step=cycle, ok=False, phase="repeat_guard", decision=decision)
                break

        if stop_path.exists():
            status = STOPPED
            finding = _finding("stop_present_before_action", f"STOP file present before action: {stop_path}", severity="stop", data={"cycle": cycle})
            findings.append(finding)
            record_step(trajectory_path, finding["summary"], step=cycle, ok=False, stop_file=str(stop_path))
            break

        if cfg.dry_run:
            action_result = {"ok": True, "status": "dry_run", "summary": "dry-run no-op action", "decision": decision}
            metrics["dry_run_actions"] += 1
        else:
            action_result = _invoke_phase(
                _resolve_hook(cfg, "act"),
                context,
                decision,
                default_status="ok",
                default_summary="action completed",
                phase="act",
                timeout_seconds=float(cfg.phase_timeout_seconds),
                stop_path=stop_path,
            )
            metrics["actions_executed"] += 1
        action_payload = _normalize_phase(action_result, default_status="ok", default_summary="action completed")
        record_action(trajectory_path, f"cycle {cycle} action: {action_payload['summary']}", step=cycle, ok=action_payload["ok"], phase="act", result=action_payload)
        if not action_payload["ok"]:
            status = _failure_status(action_payload)
            _record_failure(findings, metrics, "action_failed", action_payload, cycle=cycle)
            break

        verify = _invoke_phase(
            _resolve_hook(cfg, "verify"),
            context,
            decision,
            action_payload,
            default_status="ok",
            default_summary="verification passed",
            phase="verify",
            timeout_seconds=float(cfg.phase_timeout_seconds),
            stop_path=stop_path,
        )
        metrics["verifications"] += 1
        record_observation(trajectory_path, f"cycle {cycle} verify: {verify['summary']}", step=cycle, ok=verify["ok"], phase="verify", data=verify)
        if not verify["ok"]:
            if str(verify.get("status") or "").lower() == TIMEOUT:
                status = TIMEOUT
                _record_failure(findings, metrics, "verify_timeout", verify, cycle=cycle)
                break
            status = VERIFY_FAILED
            metrics["verification_failures"] += 1
            findings.append(_finding("verify_failed", verify["summary"], severity="stop", data={"cycle": cycle, "verify": verify, "decision": decision}))
            break

        metrics["cycles_completed"] += 1
        metrics["cycles"] = metrics["cycles_started"]
        _write_heartbeat(heartbeat_path, RUNNING, metrics, trajectory_path, stop_path, findings, started_at=started_at, cycle=cycle)
        _write_status(status_path, RUNNING, metrics, trajectory_path, heartbeat_path, stop_path, findings, started_at=started_at, cycle=cycle, summary=f"cycle {cycle} completed")
        if cycle < cycles and float(cfg.interval_seconds) > 0:
            sleep(max(0.0, float(cfg.interval_seconds)))

    if status == RUNNING:
        status = SUCCESS
    return _finish(status, metrics, trajectory_path, heartbeat_path, status_path, result_path, stop_path, findings, started_at, cycle=metrics["cycles_started"])


def _finish(
    status: str,
    metrics: dict[str, Any],
    trajectory_path: Path,
    heartbeat_path: Path,
    status_path: Path,
    result_path: Path,
    stop_path: Path,
    findings: list[dict[str, Any]],
    started_at: str,
    *,
    cycle: int,
) -> DesktopL4SoakResult:
    ok = status == SUCCESS
    metrics["cycles"] = max(int(metrics.get("cycles", 0) or 0), int(metrics.get("cycles_started", 0) or 0))
    metrics["loop_stops"] = int(metrics.get("loop_stops", metrics.get("repeat_stops", 0)) or 0)
    metrics["ok"] = ok
    metrics["status"] = status
    metrics["trajectory_path"] = str(trajectory_path)
    metrics["heartbeat_path"] = str(heartbeat_path)
    metrics["status_path"] = str(status_path)
    metrics["result_path"] = str(result_path)
    metrics["stop_path"] = str(stop_path)
    summary = str(findings[-1].get("summary") or "") if findings and status != SUCCESS else ""
    if not summary:
        summary = f"desktop-l4-soak {status}: cycles={metrics['cycles']}"
    record_step(trajectory_path, f"desktop-l4-soak finished: {status}", step=cycle or None, ok=ok, status=status, findings=findings)
    _write_heartbeat(heartbeat_path, status, metrics, trajectory_path, stop_path, findings, started_at=started_at, cycle=cycle)
    _write_status(status_path, status, metrics, trajectory_path, heartbeat_path, stop_path, findings, started_at=started_at, cycle=cycle, summary=summary)
    result = DesktopL4SoakResult(
        status=status,
        ok=ok,
        summary=summary,
        metrics=dict(metrics),
        trajectory_path=str(trajectory_path),
        heartbeat_path=str(heartbeat_path),
        status_path=str(status_path),
        result_path=str(result_path),
        json_path=str(result_path),
        stop_path=str(stop_path),
        findings=list(findings),
    )
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(result.to_json() + "\n", encoding="utf-8")
    return result


def _coerce_config(config: DesktopL4SoakConfig | Mapping[str, Any] | str | Path) -> DesktopL4SoakConfig:
    if isinstance(config, DesktopL4SoakConfig):
        return config
    if isinstance(config, Mapping):
        return DesktopL4SoakConfig(**dict(config))
    return DesktopL4SoakConfig(project=config)


def _missing_live_gates(config: DesktopL4SoakConfig) -> list[str]:
    if config.dry_run:
        return []
    missing: list[str] = []
    if not config.execute:
        missing.append("--execute")
    if not config.reviewed:
        missing.append("--reviewed")
    if not config.allow_actions:
        missing.append("--allow-actions")
    return missing


def _resolve_hook(config: DesktopL4SoakConfig, name: str) -> Hook:
    if name == "act":
        explicit = config.act or config.execute_action or config.action
    else:
        explicit = getattr(config, name)
    if explicit is not None:
        return explicit
    for owner in (config.runner, config.driver):
        hook = getattr(owner, name, None) if owner is not None else None
        if callable(hook):
            return hook
    if name == "observe":
        return _default_observe if config.dry_run else _real_observe
    if name == "screenshot":
        return _default_screenshot if config.dry_run else _real_screenshot
    if name == "decide":
        return _default_decide if config.dry_run else _real_decide
    if name == "preflight":
        return _default_preflight if config.dry_run else _real_preflight
    if name == "verify":
        return _default_verify if config.dry_run else _real_verify
    return _default_act if config.dry_run else _real_act


def _default_observe(context: _CycleContext) -> dict[str, Any]:
    return {"ok": True, "status": "ok", "summary": "dry-run observation", "data": {"cycle": context.cycle}}


def _default_screenshot(context: _CycleContext) -> dict[str, Any]:
    return {"ok": True, "status": "ok", "summary": "dry-run screenshot", "data": {"cycle": context.cycle, "path": ""}}


def _default_decide(context: _CycleContext, *_args: Any) -> dict[str, Any]:
    return {"ok": True, "status": "ok", "action": "noop", "args": {}, "summary": "dry-run no-op decision"}


def _default_act(context: _CycleContext, decision: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"ok": True, "status": "ok", "summary": "no-op action", "decision": _json_safe(decision or {})}


def _default_preflight(context: _CycleContext, decision: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"ok": True, "allowed": True, "status": "allowed", "summary": "preflight allowed", "decision": _json_safe(decision or {})}


def _real_preflight(context: _CycleContext, decision: Mapping[str, Any] | None = None) -> dict[str, Any]:
    payload = decision or context.decision
    action = str(payload.get("action") or "").strip().lower()
    args = payload.get("args") if isinstance(payload.get("args"), Mapping) else {}
    if action in {"click", "move", "type", "hotkey", "grid-click", "som-click"}:
        target_id = str(payload.get("target_id") or args.get("target_id") or "")
        target_hash = str(args.get("target_hash") or "")
        observation_id = str(args.get("observation_id") or "")
        current_observation_id = str(context.observation.get("observation_id") or "")
        if not target_id or not target_hash or not observation_id:
            return {
                "ok": False,
                "allowed": False,
                "status": BLOCKED,
                "summary": f"target action {action} missing observation fence",
                "decision": _json_safe(payload),
            }
        if current_observation_id and observation_id != current_observation_id:
            return {
                "ok": False,
                "allowed": False,
                "status": BLOCKED,
                "summary": f"observation fence mismatch before action: expected {current_observation_id}, got {observation_id}",
                "decision": _json_safe(payload),
            }
        current_target = _refresh_target_fence(context, target_id)
        if not current_target["ok"]:
            return {
                "ok": False,
                "allowed": False,
                "status": BLOCKED,
                "summary": current_target["summary"],
                "decision": _json_safe(payload),
                "target_refresh": current_target,
            }
        current_hash = str(current_target.get("target_hash") or "")
        if current_hash != target_hash:
            return {
                "ok": False,
                "allowed": False,
                "status": BLOCKED,
                "summary": f"target changed before action: {target_id}",
                "decision": _json_safe(payload),
                "target_refresh": current_target,
            }
        return {
            "ok": True,
            "allowed": True,
            "status": "allowed",
            "summary": f"preflight allowed after target refresh: {target_id}",
            "decision": _json_safe(payload),
            "target_refresh": current_target,
        }
    return {"ok": True, "allowed": True, "status": "allowed", "summary": "preflight allowed", "decision": _json_safe(payload)}


def _refresh_target_fence(context: _CycleContext, target_id: str) -> dict[str, Any]:
    try:
        tokenized = build_desktop_tokenization(context.project, name=f"l4_preflight_{context.cycle:04d}", **_target_refresh_kwargs(target_id))
    except Exception as exc:  # noqa: BLE001 - live desktop refresh must fail closed.
        audit_suppressed_exception(f"{__name__}:_refresh_target_fence", exc, project=context.project, target_id=target_id)
        return {"ok": False, "summary": f"target refresh failed: {type(exc).__name__}: {exc}", "error_type": type(exc).__name__}
    payload = tokenized.to_payload() if hasattr(tokenized, "to_payload") else _payload(tokenized)
    if not bool(payload.get("ok")):
        return {"ok": False, "summary": f"target refresh failed: {payload.get('summary') or payload.get('status') or 'unknown'}", "tokenization": _json_safe_dict(payload)}
    token = _find_token_payload(payload, target_id)
    if token is None:
        return {"ok": False, "summary": f"target missing before action: {target_id}", "tokenization": _json_safe_dict(payload)}
    raw = token.get("raw") if isinstance(token.get("raw"), Mapping) else {}
    if str(raw.get("recovered_from") or "") == "cached_ax":
        return {"ok": False, "summary": f"target refresh used cached AX fallback: {target_id}", "tokenization": _json_safe_dict(payload)}
    return {
        "ok": True,
        "summary": f"target refresh matched {target_id}",
        "target_id": target_id,
        "target_hash": str(token.get("target_hash") or ""),
        "observation_id": str(payload.get("observation_id") or ""),
        "screen_hash": str(payload.get("screen_hash") or ""),
        "mode": "ax_only" if _is_ax_target(target_id) else "full",
    }


def _target_refresh_kwargs(target_id: str) -> dict[str, Any]:
    if _is_ax_target(target_id):
        return {
            "include_ax": True,
            "include_ocr": False,
            "include_som": False,
            "include_grid": False,
            "skip_screenshot_if_ax_only": True,
        }
    return {
        "include_ax": True,
        "include_ocr": True,
        "include_som": True,
        "include_grid": False,
    }


def _is_ax_target(target_id: str) -> bool:
    return target_id.strip().upper().startswith("AX")


def _find_token_payload(tokenization: Mapping[str, Any], target_id: str) -> dict[str, Any] | None:
    tokens = tokenization.get("tokens") if isinstance(tokenization.get("tokens"), list) else []
    for token in tokens:
        if isinstance(token, Mapping) and str(token.get("token_id") or "") == target_id:
            return dict(token)
    return None


def _default_verify(context: _CycleContext, decision: Mapping[str, Any] | None = None, action_result: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"ok": True, "status": "ok", "summary": "dry-run verification passed", "decision": _json_safe(decision or {}), "action_result": _json_safe(action_result or {})}


def _real_screenshot(context: _CycleContext) -> dict[str, Any]:
    from .desktop_control import screenshot

    result = screenshot(context.project, name=f"l4_soak_cycle_{context.cycle:04d}.png")
    return result.to_payload() if hasattr(result, "to_payload") else asdict(result)


def _real_observe(context: _CycleContext) -> dict[str, Any]:
    from .desktop_intelligence import build_desktop_tokenization

    image_path = ""
    data = context.screenshot.get("data")
    if isinstance(data, Mapping):
        image_path = str(data.get("path") or "")
    tokenized = build_desktop_tokenization(context.project, image_path=image_path or None)
    return tokenized.to_payload()


def _real_decide(context: _CycleContext, observation: Mapping[str, Any] | None = None, *_args: Any) -> dict[str, Any]:
    from .desktop_intelligence import decide_desktop_action

    decision = decide_desktop_action(context.goal or "observe current desktop state", observation or context.observation)
    return decision.to_payload()


def _real_act(context: _CycleContext, decision: Mapping[str, Any] | None = None) -> dict[str, Any]:
    from .desktop_workflow import DesktopStep, _execute_step

    payload = decision or context.decision
    action = str(payload.get("action") or "")
    args = payload.get("args") if isinstance(payload.get("args"), Mapping) else {}
    if not action:
        return {"ok": True, "status": "hold", "summary": "no desktop action requested"}
    result = _execute_step(context.project, DesktopStep(action, dict(args), str(payload.get("summary") or action)))
    return result.to_payload() if hasattr(result, "to_payload") else asdict(result)


def _real_verify(context: _CycleContext, decision: Mapping[str, Any] | None = None, action_result: Mapping[str, Any] | None = None) -> dict[str, Any]:
    from .desktop_intelligence import build_desktop_tokenization

    action = str((decision or {}).get("action") or "").strip().lower()
    if action in {"", "noop", "wait", "observe", "screenshot", "stop"}:
        return {"ok": True, "status": "ok", "summary": f"no post-action progress required for {action or 'hold'}"}
    current = build_desktop_tokenization(context.project)
    current_payload = current.to_payload()
    if _observation_progressed(context.observation, current_payload):
        return {"ok": True, "status": "ok", "summary": "desktop state changed after action", "observation": current_payload}
    return {
        "ok": False,
        "status": VERIFY_FAILED,
        "summary": f"no visible desktop progress after {action}",
        "observation": current_payload,
    }


def _invoke(func: Hook, *args: Any) -> Any:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return func(*args)
    if any(parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in signature.parameters.values()):
        return func(*args)
    positional = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
    ]
    if not positional:
        return func()
    return func(*args[: len(positional)])


def _invoke_phase(
    func: Hook,
    *args: Any,
    default_status: str,
    default_summary: str,
    phase: str = "phase",
    timeout_seconds: float = 0.0,
    stop_path: Path | None = None,
) -> dict[str, Any]:
    try:
        value = _invoke_with_watchdog(func, args, phase=phase, timeout_seconds=timeout_seconds, stop_path=stop_path)
    except Exception as exc:  # noqa: BLE001 - injected desktop hooks must fail closed.
        value = {"ok": False, "status": "error", "summary": f"{type(exc).__name__}: {exc}", "error_type": type(exc).__name__}
    return _normalize_phase(value, default_status=default_status, default_summary=default_summary)


def _invoke_decision(
    func: Hook,
    *args: Any,
    phase: str = "decide",
    timeout_seconds: float = 0.0,
    stop_path: Path | None = None,
) -> dict[str, Any]:
    try:
        return _normalize_decision(_invoke_with_watchdog(func, args, phase=phase, timeout_seconds=timeout_seconds, stop_path=stop_path))
    except Exception as exc:  # noqa: BLE001 - injected deciders must fail closed.
        audit_suppressed_exception(f"{__name__}:_invoke_decision", exc)
        return {"ok": False, "status": "blocked", "action": "noop", "args": {}, "summary": f"{type(exc).__name__}: {exc}", "error_type": type(exc).__name__}


def _invoke_preflight(
    func: Hook,
    *args: Any,
    phase: str = "preflight",
    timeout_seconds: float = 0.0,
    stop_path: Path | None = None,
) -> dict[str, Any]:
    try:
        return _normalize_preflight(_invoke_with_watchdog(func, args, phase=phase, timeout_seconds=timeout_seconds, stop_path=stop_path))
    except Exception as exc:  # noqa: BLE001 - injected preflight hooks must fail closed.
        audit_suppressed_exception(f"{__name__}:_invoke_preflight", exc)
        return {"ok": False, "allowed": False, "status": "blocked", "summary": f"{type(exc).__name__}: {exc}", "error_type": type(exc).__name__}


def _invoke_with_watchdog(
    func: Hook,
    args: tuple[Any, ...],
    *,
    phase: str,
    timeout_seconds: float,
    stop_path: Path | None,
) -> Any:
    if timeout_seconds <= 0:
        return _invoke(func, *args)
    timeout = max(0.05, float(timeout_seconds))
    ctx = _multiprocessing_context()
    result_queue: Any = ctx.Queue(maxsize=1)
    process = ctx.Process(target=_hook_worker, args=(func, args, result_queue))
    process.start()
    deadline = time.monotonic() + timeout
    checks = 0
    while process.is_alive():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _terminate_process(process)
            if stop_path is not None:
                _write_watchdog_stop(stop_path, f"desktop-l4-soak {phase} watchdog timeout")
            return _watchdog_phase_payload(TIMEOUT, f"desktop-l4-soak {phase} timed out after {timeout:.2f}s", phase, timeout, checks)
        process.join(timeout=max(0.01, min(0.05, remaining)))
        if process.is_alive():
            checks += 1
            if stop_path is not None and stop_path.exists():
                _terminate_process(process)
                return _watchdog_phase_payload(STOPPED, f"STOP file present while {phase} was running: {stop_path}", phase, timeout, checks)

    process.join(timeout=1)
    try:
        item = result_queue.get_nowait()
    except queue.Empty:
        if process.exitcode not in (0, None):
            return {
                "ok": False,
                "status": "error",
                "summary": f"desktop-l4-soak {phase} process exited with code {process.exitcode}",
                "error_type": "ProcessExit",
                "watchdog_checks": checks,
            }
        return {
            "ok": False,
            "status": "error",
            "summary": f"desktop-l4-soak {phase} process returned no result",
            "error_type": "MissingHookResult",
            "watchdog_checks": checks,
        }
    if not isinstance(item, Mapping):
        return {
            "ok": False,
            "status": "error",
            "summary": f"desktop-l4-soak {phase} process returned invalid result",
            "error_type": "InvalidHookResult",
            "watchdog_checks": checks,
        }
    if not bool(item.get("ok", False)):
        return {
            "ok": False,
            "status": "error",
            "summary": str(item.get("summary") or f"desktop-l4-soak {phase} failed"),
            "error_type": str(item.get("error_type") or "HookError"),
            "watchdog_checks": checks,
        }
    value = item.get("value")
    if isinstance(value, Mapping):
        payload = dict(value)
        payload["watchdog_checks"] = checks
        payload["watchdog_timeout_seconds"] = timeout
        return payload
    return value


def _hook_worker(func: Hook, args: tuple[Any, ...], result_queue: Any) -> None:
    try:
        result_queue.put({"ok": True, "value": _json_safe(_invoke(func, *args))})
    except BaseException as exc:  # noqa: BLE001 - child process must serialize hook failures.
        result_queue.put({"ok": False, "summary": f"{type(exc).__name__}: {exc}", "error_type": type(exc).__name__})


def _watchdog_phase_payload(status: str, summary: str, phase: str, timeout_seconds: float, checks: int) -> dict[str, Any]:
    return {
        "ok": False,
        "status": status,
        "summary": summary,
        "phase": phase,
        "watchdog_killed": True,
        "watchdog_status": status,
        "watchdog_checks": checks,
        "watchdog_timeout_seconds": timeout_seconds,
    }


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


def _write_watchdog_stop(path: Path, reason: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(reason.rstrip() + "\n", encoding="utf-8")


def _normalize_phase(value: Any, *, default_status: str, default_summary: str) -> dict[str, Any]:
    payload = _payload(value)
    status = str(payload.get("status") or default_status)
    summary = str(payload.get("summary") or payload.get("reason") or default_summary)
    ok = bool(payload.get("ok", status.lower() not in {"failed", "failure", "blocked", "error", "permission_required", "verify_failed", "stale_target"}))
    normalized = _json_safe_dict(payload)
    normalized.update({"ok": ok, "status": status, "summary": summary})
    return normalized


def _normalize_decision(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        payload: dict[str, Any] = {"action": value}
    else:
        payload = _payload(value)
    action = str(payload.get("action") or payload.get("name") or "noop").strip() or "noop"
    args = payload.get("args") if isinstance(payload.get("args"), Mapping) else {}
    status = str(payload.get("status") or "ok")
    summary = str(payload.get("summary") or payload.get("reason") or f"action {action}")
    ok = bool(payload.get("ok", status.lower() not in {"failed", "failure", "blocked", "error"}))
    normalized = _json_safe_dict(payload)
    normalized.update({"ok": ok, "status": status, "summary": summary, "action": action, "args": _json_safe_dict(args)})
    for key, item in payload.items():
        if key not in {"ok", "status", "summary", "reason", "action", "name", "args"} and key not in normalized["args"]:
            normalized["args"][str(key)] = _json_safe(item)
    return normalized


def _normalize_preflight(value: Any) -> dict[str, Any]:
    payload = _normalize_phase(value, default_status="allowed", default_summary="preflight allowed")
    allowed = bool(payload.get("allowed", payload.get("ok", True)))
    payload["allowed"] = allowed
    payload["ok"] = bool(payload.get("ok", allowed)) and allowed
    return payload


def _authorize_decision(
    decision: Mapping[str, Any],
    *,
    goal: str,
    execute: bool,
    reviewed: bool,
    allow_actions: bool,
) -> tuple[Any | None, str]:
    action = str(decision.get("action") or "noop")
    args = decision.get("args") if isinstance(decision.get("args"), Mapping) else {}
    policy_input = {"action": action, "args": dict(args)}
    try:
        return authorize_daemon_action(policy_input, goal=goal, execute=execute, reviewed=reviewed, allow_actions=allow_actions), ""
    except ValueError as exc:
        risk = classify_goal_risk(json.dumps(policy_input, ensure_ascii=False, sort_keys=True, default=str))
        if risk.blocked:
            return type("_BlockedPolicy", (), {"status": BLOCKED, "reason": risk.reason, "to_payload": lambda self: {"status": BLOCKED, "reason": risk.reason, "risk": risk.to_payload()}})(), ""
        return None, str(exc)


def _failure_status(payload: Mapping[str, Any], *, screenshot_failure: bool = False) -> str:
    if str(payload.get("status") or "").lower() == TIMEOUT:
        return TIMEOUT
    if _is_permission_failure(payload):
        return PAUSED
    return STOPPED if screenshot_failure else STOPPED


def _record_failure(
    findings: list[dict[str, Any]],
    metrics: dict[str, Any],
    code: str,
    payload: Mapping[str, Any],
    *,
    cycle: int,
    screenshot_failure: bool = False,
) -> None:
    if screenshot_failure:
        metrics["screenshot_failures"] += 1
    metrics["watchdog_checks"] = int(metrics.get("watchdog_checks", 0) or 0) + max(0, int(payload.get("watchdog_checks", 0) or 0))
    if payload.get("watchdog_killed"):
        metrics["watchdog_kills"] = int(metrics.get("watchdog_kills", 0) or 0) + 1
        code = "phase_timeout" if str(payload.get("status") or "").lower() == TIMEOUT else code
    if str(payload.get("status") or "").lower() == TIMEOUT:
        metrics["phase_timeouts"] = int(metrics.get("phase_timeouts", 0) or 0) + 1
        metrics["watchdog_timeouts"] = int(metrics.get("watchdog_timeouts", 0) or 0) + 1
    if _is_permission_failure(payload):
        metrics["permission_failures"] += 1
        code = "permission_failure"
    findings.append(_finding(code, str(payload.get("summary") or payload.get("status") or code), severity="stop", data={"cycle": cycle, "payload": _json_safe_dict(payload)}))


def _is_permission_failure(payload: Mapping[str, Any]) -> bool:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).lower()
    return any(marker in text for marker in PERMISSION_MARKERS)


def _same_action_repeat(action_tail: list[str], limit: int) -> bool:
    if len(action_tail) < limit:
        return False
    tail = action_tail[-limit:]
    return len(set(tail)) == 1


def _action_key(decision: Mapping[str, Any]) -> str:
    action = str(decision.get("action") or "").strip()
    if not action or action.lower() in {"noop", "none", "hold", "wait", "observe", "screenshot", "stop"}:
        return ""
    args = decision.get("args") if isinstance(decision.get("args"), Mapping) else {}
    return action + ":" + json.dumps(_json_safe_dict(args), ensure_ascii=False, sort_keys=True, default=str)


def _observation_progressed(previous: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    previous_hash = str(previous.get("screen_hash") or "")
    current_hash = str(current.get("screen_hash") or "")
    if previous_hash and current_hash and previous_hash != current_hash:
        return True
    previous_tokens = previous.get("tokens") if isinstance(previous.get("tokens"), list) else []
    current_tokens = current.get("tokens") if isinstance(current.get("tokens"), list) else []
    return json.dumps(previous_tokens, ensure_ascii=False, sort_keys=True, default=str) != json.dumps(current_tokens, ensure_ascii=False, sort_keys=True, default=str)


def _finding(code: str, summary: str, *, severity: str, data: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "severity": severity, "summary": summary, "data": _json_safe_dict(data or {})}


def _write_heartbeat(
    path: Path,
    status: str,
    metrics: Mapping[str, Any],
    trajectory_path: Path,
    stop_path: Path,
    findings: list[dict[str, Any]],
    *,
    started_at: str,
    cycle: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "ok": status == SUCCESS,
        "cycle": cycle,
        "started_at": started_at,
        "updated_at": _utc_timestamp(),
        "trajectory_path": str(trajectory_path),
        "stop_path": str(stop_path),
        "metrics": _json_safe_dict(metrics),
        "findings": [_json_safe_dict(finding) for finding in findings],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_status(
    path: Path,
    status: str,
    metrics: Mapping[str, Any],
    trajectory_path: Path,
    heartbeat_path: Path,
    stop_path: Path,
    findings: list[dict[str, Any]],
    *,
    started_at: str,
    cycle: int,
    summary: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "ok": status == SUCCESS,
        "summary": summary,
        "cycle": cycle,
        "started_at": started_at,
        "updated_at": _utc_timestamp(),
        "trajectory_path": str(trajectory_path),
        "heartbeat_path": str(heartbeat_path),
        "stop_path": str(stop_path),
        "metrics": _json_safe_dict(metrics),
        "findings": [_json_safe_dict(finding) for finding in findings],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _resolve_path(project: Path, value: str | Path, default: Path) -> Path:
    raw = str(value)
    path = Path(value).expanduser() if raw else default
    return path if path.is_absolute() else project / path


def _payload(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_payload") and callable(value.to_payload):
        payload = value.to_payload()
        if isinstance(payload, Mapping):
            return dict(payload)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        payload = value.to_dict()
        if isinstance(payload, Mapping):
            return dict(payload)
    if hasattr(value, "__dict__"):
        return {key: item for key, item in vars(value).items() if not str(key).startswith("_")}
    return {"value": value}


def _json_safe_dict(data: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_safe(value) for key, value in sorted(data.items(), key=lambda item: str(item[0]))}


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _json_safe_dict(value)
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if is_dataclass(value):
        return _json_safe(asdict(value))
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True)
        return value
    except TypeError:
        return str(value)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
