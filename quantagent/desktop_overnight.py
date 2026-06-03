from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .agent_autopsy import build_agent_autopsy, write_agent_autopsy
from .desktop_agent import build_desktop_agent_plan, default_stop_file
from .desktop_control import DesktopResult, desktop_dir
from .desktop_workflow import DesktopPlan, DesktopStep, _execute_step, ensure_desktop_step_approval
from .query_runtime import QueryRuntime
from .trajectory import read_events, record_action, record_observation


CONTROL_ACTIONS = {"activate", "open", "click", "grid-click", "som-click", "move", "type", "hotkey"}
HIGH_RISK_RE = re.compile(
    r"(转账|付款|支付|下单|买入|卖出|交易|提现|充值|购买|银行卡|密码|验证码|身份证|"
    r"发消息|发送消息|删除|格式化|rm\s+-rf|"
    r"\b(pay|purchase|transfer|trade|buy|sell|delete|format|password|otp|2fa)\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OvernightDecision:
    round: int
    phase: str
    action: str
    summary: str
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DesktopOvernightResult:
    ok: bool
    status: str
    summary: str
    goal: str
    plan: DesktopPlan
    decisions: tuple[OvernightDecision, ...]
    results: tuple[DesktopResult, ...]
    query_events_path: str
    trajectory_path: str
    stop_file: str
    state_path: str
    autopsy_path: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "summary": self.summary,
            "goal": self.goal,
            "plan": self.plan.to_payload(),
            "decisions": [decision.to_payload() for decision in self.decisions],
            "results": [asdict(result) for result in self.results],
            "query_events_path": self.query_events_path,
            "trajectory_path": self.trajectory_path,
            "stop_file": self.stop_file,
            "state_path": self.state_path,
            "autopsy_path": self.autopsy_path,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False, indent=2)


def desktop_overnight_dir(project: str | Path) -> Path:
    directory = desktop_dir(Path(project)) / "overnight"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def build_desktop_overnight_plan(goal: str, *, browser: str = "Safari", max_actions: int = 12) -> DesktopPlan:
    base = build_desktop_agent_plan(goal, browser=browser, max_actions=max_actions)
    action_steps = tuple(step for step in base.steps if step.action != "screenshot")
    steps = (DesktopStep("screenshot", {}, "observe screen before deciding", requires_review=False),) + action_steps
    return DesktopPlan(
        f"overnight desktop: {' '.join(goal.strip().split())}",
        steps,
        safety_note=(
            "Long-running desktop control. Requires --execute --reviewed, STOP-file fuse, "
            "bounded rounds/minutes, high-risk goal block, and --allow-actions for desktop side effects."
        ),
    )


def run_desktop_overnight(
    project: str | Path,
    goal: str,
    *,
    execute: bool = False,
    reviewed: bool = False,
    allow_actions: bool = False,
    browser: str = "Safari",
    max_rounds: int = 20,
    max_minutes: float = 480.0,
    delay: float = 30.0,
    max_actions: int = 12,
    stop_file: str | Path | None = None,
    require_action_approval: bool = False,
    approval_id: str | None = None,
) -> DesktopOvernightResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    run_dir = desktop_overnight_dir(project_path)
    query_events_path = run_dir / "query_events.jsonl"
    trajectory_path = run_dir / "trajectory.jsonl"
    state_path = run_dir / "latest_state.json"
    stop_path = Path(stop_file).expanduser() if stop_file else default_stop_file(project_path)
    if not stop_path.is_absolute():
        stop_path = project_path / stop_path

    bounded_rounds = max(1, min(int(max_rounds), 10000))
    bounded_minutes = max(0.1, min(float(max_minutes), 720.0))
    bounded_delay = max(0.0, min(float(delay), 3600.0))
    plan = build_desktop_overnight_plan(goal, browser=browser, max_actions=max_actions)
    runtime = QueryRuntime(project_path, event_path=query_events_path)
    runtime.start(
        goal,
        mode="desktop_overnight",
        data={
            "execute": execute,
            "reviewed": reviewed,
            "allow_actions": allow_actions,
            "max_rounds": bounded_rounds,
            "max_minutes": bounded_minutes,
            "delay": bounded_delay,
            "stop_file": str(stop_path),
            "require_action_approval": require_action_approval,
            "approval_id": approval_id or "",
        },
    )

    risk = _high_risk_reason(goal)
    if risk:
        return _finish(
            project_path,
            run_dir,
            runtime,
            goal,
            plan,
            (),
            (),
            query_events_path,
            trajectory_path,
            stop_path,
            state_path,
            ok=False,
            status="blocked",
            summary=f"overnight desktop agent blocked high-risk goal: {risk}",
            failure_class="high_risk_goal",
        )

    if not execute:
        return _finish(
            project_path,
            run_dir,
            runtime,
            goal,
            plan,
            (),
            (),
            query_events_path,
            trajectory_path,
            stop_path,
            state_path,
            ok=True,
            status="preview",
            summary=f"dry-run overnight preview: {bounded_rounds} round(s), {len(plan.steps)} planned step template(s)",
        )

    if not reviewed:
        return _finish(
            project_path,
            run_dir,
            runtime,
            goal,
            plan,
            (),
            (),
            query_events_path,
            trajectory_path,
            stop_path,
            state_path,
            ok=False,
            status="blocked",
            summary="overnight desktop control requires --reviewed",
            failure_class="review_required",
        )

    action_steps = [step for step in plan.steps if step.action != "screenshot"]
    control_steps = [step for step in action_steps if step.action in CONTROL_ACTIONS]
    if control_steps and not allow_actions:
        return _finish(
            project_path,
            run_dir,
            runtime,
            goal,
            plan,
            (),
            (),
            query_events_path,
            trajectory_path,
            stop_path,
            state_path,
            ok=False,
            status="blocked",
            summary="overnight desktop side effects require --allow-actions",
            failure_class="allow_actions_required",
        )

    decisions: list[OvernightDecision] = []
    results: list[DesktopResult] = []
    deadline = time.monotonic() + bounded_minutes * 60.0
    action_index = 0
    step_counter = _next_trajectory_step(trajectory_path) - 1

    for round_no in range(1, bounded_rounds + 1):
        if stop_path.exists():
            return _finish(
                project_path,
                run_dir,
                runtime,
                goal,
                plan,
                tuple(decisions),
                tuple(results),
                query_events_path,
                trajectory_path,
                stop_path,
                state_path,
                ok=False,
                status="stopped",
                summary=f"STOP file present before overnight round {round_no}: {stop_path}",
                failure_class="stopped",
            )
        if time.monotonic() > deadline:
            return _finish(
                project_path,
                run_dir,
                runtime,
                goal,
                plan,
                tuple(decisions),
                tuple(results),
                query_events_path,
                trajectory_path,
                stop_path,
                state_path,
                ok=True,
                status="time_budget_exhausted",
                summary=f"overnight time budget exhausted after {round_no - 1} round(s)",
            )

        observe = DesktopStep("screenshot", {}, f"overnight observe round {round_no}", requires_review=False)
        step_counter += 1
        observed = _run_step(
            project_path,
            runtime,
            trajectory_path,
            step_counter,
            round_no,
            "observe",
            observe,
            goal=goal,
            require_action_approval=require_action_approval,
            approval_id=approval_id,
        )
        results.append(observed)
        decisions.append(OvernightDecision(round_no, "observe", "screenshot", observed.summary, observed.ok, observed.data))
        _write_state(state_path, goal, plan, decisions, results, stop_path)
        if not observed.ok:
            return _finish(
                project_path,
                run_dir,
                runtime,
                goal,
                plan,
                tuple(decisions),
                tuple(results),
                query_events_path,
                trajectory_path,
                stop_path,
                state_path,
                ok=False,
                status="failed",
                summary=f"overnight observe failed at round {round_no}: {observed.summary}",
                failure_class="desktop_observe_failed",
            )

        if action_index < len(action_steps):
            action = action_steps[action_index]
            action_index += 1
            step_counter += 1
            acted = _run_step(
                project_path,
                runtime,
                trajectory_path,
                step_counter,
                round_no,
                "act",
                action,
                goal=goal,
                require_action_approval=require_action_approval,
                approval_id=approval_id,
            )
            results.append(acted)
            decisions.append(OvernightDecision(round_no, "act", action.action, acted.summary, acted.ok, acted.data))
            _write_state(state_path, goal, plan, decisions, results, stop_path)
            if not acted.ok:
                status = "blocked" if acted.data.get("failure_class") == "approval_required" else "failed"
                summary = (
                    f"overnight action blocked at round {round_no}: {acted.summary}"
                    if status == "blocked"
                    else f"overnight action failed at round {round_no}: {acted.summary}"
                )
                return _finish(
                    project_path,
                    run_dir,
                    runtime,
                    goal,
                    plan,
                    tuple(decisions),
                    tuple(results),
                    query_events_path,
                    trajectory_path,
                    stop_path,
                    state_path,
                    ok=False,
                    status=status,
                    summary=summary,
                    failure_class=str(acted.data.get("failure_class") or "desktop_action_failed"),
                )
            if action.action in CONTROL_ACTIONS:
                verify = DesktopStep("screenshot", {}, f"verify after round {round_no} action", requires_review=False)
                step_counter += 1
                verified = _run_step(
                    project_path,
                    runtime,
                    trajectory_path,
                    step_counter,
                    round_no,
                    "verify",
                    verify,
                    goal=goal,
                    require_action_approval=require_action_approval,
                    approval_id=approval_id,
                )
                results.append(verified)
                decisions.append(OvernightDecision(round_no, "verify", "screenshot", verified.summary, verified.ok, verified.data))
                _write_state(state_path, goal, plan, decisions, results, stop_path)
                if not verified.ok:
                    return _finish(
                        project_path,
                        run_dir,
                        runtime,
                        goal,
                        plan,
                        tuple(decisions),
                        tuple(results),
                        query_events_path,
                        trajectory_path,
                        stop_path,
                        state_path,
                        ok=False,
                        status="verify_failed",
                        summary=f"overnight verification failed at round {round_no}: {verified.summary}",
                        failure_class="verify_failed",
                    )
        else:
            summary = "no remaining planned action; observing only"
            decisions.append(OvernightDecision(round_no, "decide", "hold", summary, True))
            _write_state(state_path, goal, plan, decisions, results, stop_path)

        if round_no < bounded_rounds and bounded_delay > 0:
            time.sleep(bounded_delay)

    return _finish(
        project_path,
        run_dir,
        runtime,
        goal,
        plan,
        tuple(decisions),
        tuple(results),
        query_events_path,
        trajectory_path,
        stop_path,
        state_path,
        ok=True,
        status="completed",
        summary=f"overnight desktop agent completed {bounded_rounds} round(s)",
    )


def render_desktop_overnight_result(result: DesktopOvernightResult) -> str:
    lines = [
        "# Desktop Overnight Agent",
        "",
        f"Status: {result.status}",
        f"OK: {str(result.ok).lower()}",
        result.summary,
        f"Stop file: {result.stop_file}",
        f"State: {result.state_path}",
        f"Query events: {result.query_events_path}",
        f"Trajectory: {result.trajectory_path}",
        "",
        "Plan:",
    ]
    for index, step in enumerate(result.plan.steps, start=1):
        lines.append(f"{index}. {step.action} {json.dumps(step.args, ensure_ascii=False)}")
    if result.decisions:
        lines.extend(["", "Decisions:"])
        for decision in result.decisions[-20:]:
            lines.append(f"- round {decision.round} {decision.phase}/{decision.action}: {'ok' if decision.ok else 'fail'} - {decision.summary}")
    return "\n".join(lines).rstrip() + "\n"


def _next_trajectory_step(trajectory_path: Path) -> int:
    if not trajectory_path.exists():
        return 1
    existing_steps = [event.step for event in read_events(trajectory_path) if event.step is not None]
    return (max(existing_steps) + 1) if existing_steps else 1


def _run_step(
    project: Path,
    runtime: QueryRuntime,
    trajectory_path: Path,
    step_number: int,
    round_no: int,
    phase: str,
    step: DesktopStep,
    *,
    goal: str,
    require_action_approval: bool,
    approval_id: str | None,
) -> DesktopResult:
    runtime.pre_tool("desktop_overnight", step=step_number, args={"round": round_no, "phase": phase, "action": step.action, "args": step.args})
    record_action(
        trajectory_path,
        f"desktop-overnight round {round_no} {phase}: {step.action}",
        step=step_number,
        ok=None,
        round=round_no,
        phase=phase,
        action=step.action,
        args=step.args,
    )
    if require_action_approval and step.action in CONTROL_ACTIONS:
        approval = ensure_desktop_step_approval(project, step, goal=goal, approval_id=approval_id)
        if not approval.allowed:
            data = {
                "failure_class": "approval_required",
                "approval_id": approval.approval_id,
                "approval_status": approval.approval.status if approval.approval else "",
            }
            result = DesktopResult(step.action, False, approval.summary, data)
        else:
            result = _execute_step(project, step)
    else:
        result = _execute_step(project, step)
    runtime.post_tool(
        "desktop_overnight",
        step=step_number,
        ok=result.ok,
        summary=result.summary,
        data={"round": round_no, "phase": phase, "action": step.action, "result": result.data},
    )
    record_observation(
        trajectory_path,
        f"{phase}/{step.action}: {result.summary}",
        step=step_number,
        ok=result.ok,
        round=round_no,
        phase=phase,
        action=step.action,
        result=result.data,
    )
    return result


def _finish(
    project: Path,
    run_dir: Path,
    runtime: QueryRuntime,
    goal: str,
    plan: DesktopPlan,
    decisions: tuple[OvernightDecision, ...],
    results: tuple[DesktopResult, ...],
    query_events_path: Path,
    trajectory_path: Path,
    stop_path: Path,
    state_path: Path,
    *,
    ok: bool,
    status: str,
    summary: str,
    failure_class: str = "",
) -> DesktopOvernightResult:
    _write_state(state_path, goal, plan, list(decisions), list(results), stop_path, status=status, summary=summary)
    autopsy = ""
    if ok:
        runtime.stop("desktop overnight completed", ok=True)
    else:
        runtime.stop("desktop overnight failed", ok=False, failure_class=failure_class or status)
        autopsy = _write_failure_autopsy(project, run_dir, goal, plan, summary, query_events_path, trajectory_path, status)
    return DesktopOvernightResult(
        ok,
        status,
        summary,
        goal,
        plan,
        decisions,
        results,
        str(query_events_path),
        str(trajectory_path),
        str(stop_path),
        str(state_path),
        autopsy,
    )


def _write_state(
    path: Path,
    goal: str,
    plan: DesktopPlan,
    decisions: list[OvernightDecision],
    results: list[DesktopResult],
    stop_path: Path,
    *,
    status: str = "running",
    summary: str = "",
) -> None:
    path.write_text(
        json.dumps(
            {
                "status": status,
                "summary": summary,
                "goal": goal,
                "stop_file": str(stop_path),
                "plan": plan.to_payload(),
                "decisions": [decision.to_payload() for decision in decisions[-200:]],
                "results": [asdict(result) for result in results[-200:]],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_failure_autopsy(
    project: Path,
    run_dir: Path,
    goal: str,
    plan: DesktopPlan,
    summary: str,
    query_events_path: Path,
    trajectory_path: Path,
    status: str,
) -> str:
    report = build_agent_autopsy(
        project,
        trajectory_path=trajectory_path,
        query_events_path=query_events_path,
        failure_text=summary,
        source_agent="desktop_overnight",
        title=f"Desktop Overnight Autopsy: {status}",
        command=plan.objective or goal,
    )
    return str(write_agent_autopsy(report, run_dir / "latest_autopsy.md"))


def _high_risk_reason(goal: str) -> str:
    match = HIGH_RISK_RE.search(goal)
    return match.group(0) if match else ""
