from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agent_autopsy import build_agent_autopsy, write_agent_autopsy
from .desktop_control import DesktopResult, desktop_dir
from .desktop_workflow import DesktopPlan, DesktopRun, DesktopStep, _execute_step, plan_open_target, plan_web_search
from .query_runtime import QueryRuntime
from .trajectory import record_action, record_observation


URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
COORD_RE = re.compile(r"(?:click|点击|点)\s*[:：]?\s*(\d{1,5})\s*[,， ]\s*(\d{1,5})", re.IGNORECASE)
HOTKEY_RE = re.compile(r"(?:hotkey|快捷键|按)\s+([a-z0-9+,\- ]{1,80})", re.IGNORECASE)
TYPE_RE = re.compile(r"(?:type|输入)\s+(.+)", re.IGNORECASE)
SEARCH_RE = re.compile(r"(?:search|搜索|搜)\s+(.+)", re.IGNORECASE)
OPEN_APP_RE = re.compile(r"(?:open|打开|启动)\s+([A-Za-z][A-Za-z0-9 ._-]{1,60})", re.IGNORECASE)


@dataclass(frozen=True)
class DesktopAgentResult:
    run: DesktopRun
    query_events_path: str
    trajectory_path: str
    stop_file: str
    autopsy_path: str = ""

    @property
    def ok(self) -> bool:
        return self.run.ok

    def to_payload(self) -> dict[str, Any]:
        payload = self.run.to_payload()
        payload["query_events_path"] = self.query_events_path
        payload["trajectory_path"] = self.trajectory_path
        payload["stop_file"] = self.stop_file
        payload["autopsy_path"] = self.autopsy_path
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False, indent=2)


def desktop_agent_dir(project: str | Path) -> Path:
    directory = desktop_dir(Path(project)) / "agent"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def default_stop_file(project: str | Path) -> Path:
    return desktop_agent_dir(project) / "STOP"


def build_desktop_agent_plan(instruction: str, *, browser: str = "Safari", max_actions: int = 12) -> DesktopPlan:
    text = " ".join(instruction.strip().split())
    if not text:
        return DesktopPlan("desktop agent: empty instruction", ())

    target_browser = _browser_from_text(text, default=browser)
    operations: list[tuple[int, int, tuple[DesktopStep, ...]]] = []
    sequence = 0
    url_match = URL_RE.search(text)
    search_match = SEARCH_RE.search(text)
    search_query = _search_query(text)
    app_match = OPEN_APP_RE.search(text)
    app = _open_app(text)
    coord = COORD_RE.search(text)
    type_match = TYPE_RE.search(text)
    typed = _type_text(text)
    hotkey_match = HOTKEY_RE.search(text)
    hotkey = _hotkey_keys(text)

    if url_match:
        operations.append(
            (
                url_match.start(),
                sequence,
                plan_open_target(Path("."), url_match.group(0), kind="url", browser=target_browser).steps,
            )
        )
        sequence += 1
    elif search_match and search_query:
        operations.append((search_match.start(), sequence, plan_web_search(search_query, browser=target_browser).steps))
        sequence += 1
    elif app_match and app:
        operations.append((app_match.start(), sequence, plan_open_target(Path("."), app, kind="app").steps))
        sequence += 1

    if coord:
        operations.append(
            (
                coord.start(),
                sequence,
                (
                    DesktopStep(
                        "click",
                        {"x": int(coord.group(1)), "y": int(coord.group(2))},
                        "direct coordinate click",
                    ),
                ),
            )
        )
        sequence += 1
    if type_match and typed:
        operations.append((type_match.start(), sequence, (DesktopStep("type", {"text": typed}, "type requested text"),)))
        sequence += 1
    if hotkey_match and hotkey:
        operations.append(
            (
                hotkey_match.start(),
                sequence,
                (DesktopStep("hotkey", {"keys": hotkey}, "press requested hotkey"),),
            )
        )
        sequence += 1

    steps = [
        step
        for _, _, planned_steps in sorted(operations, key=lambda item: (item[0], item[1]))
        for step in planned_steps
    ]
    if not steps or (_wants_screenshot(text) and steps[-1].action != "screenshot"):
        steps.append(DesktopStep("screenshot", {}, "capture current screen", requires_review=False))

    limited = tuple(steps[: max(1, max_actions)])
    return DesktopPlan(
        f"desktop agent: {text}",
        limited,
        safety_note="Direct screen takeover. Dry-run unless --execute --reviewed; STOP file aborts before each action.",
    )


def run_desktop_agent(
    project: str | Path,
    instruction: str,
    *,
    execute: bool = False,
    reviewed: bool = False,
    browser: str = "Safari",
    max_actions: int = 12,
    delay: float = 0.35,
    verify_after: bool = False,
    stop_file: str | Path | None = None,
) -> DesktopAgentResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    run_dir = desktop_agent_dir(project_path)
    query_events_path = run_dir / "query_events.jsonl"
    trajectory_path = run_dir / "trajectory.jsonl"
    stop_path = Path(stop_file).expanduser() if stop_file else default_stop_file(project_path)
    if not stop_path.is_absolute():
        stop_path = project_path / stop_path
    plan = build_desktop_agent_plan(instruction, browser=browser, max_actions=max_actions)
    runtime = QueryRuntime(project_path, event_path=query_events_path)
    runtime.start(instruction, mode="desktop_agent", data={"execute": execute, "reviewed": reviewed, "stop_file": str(stop_path)})

    if not execute:
        run = DesktopRun(True, "preview", f"dry-run preview: {len(plan.steps)} takeover step(s)", plan)
        runtime.stop("desktop agent preview", ok=True)
        _write_desktop_agent_plan(run_dir, plan)
        return DesktopAgentResult(run, str(query_events_path), str(trajectory_path), str(stop_path))

    if not reviewed:
        run = DesktopRun(False, "blocked", "direct screen takeover requires --reviewed", plan)
        runtime.stop("desktop agent blocked: missing review", ok=False, failure_class="review_required")
        _write_desktop_agent_plan(run_dir, plan)
        autopsy = _write_failure_autopsy(project_path, run_dir, run, query_events_path, trajectory_path)
        return DesktopAgentResult(run, str(query_events_path), str(trajectory_path), str(stop_path), autopsy)

    results: list[DesktopResult] = []
    bounded_delay = max(0.05, min(float(delay), 5.0))
    for index, step in enumerate(plan.steps[: max(1, max_actions)], start=1):
        if stop_path.exists():
            stopped = DesktopRun(False, "stopped", f"STOP file present before step {index}: {stop_path}", plan, tuple(results))
            runtime.stop("desktop agent stopped by STOP file", ok=False, failure_class="stopped")
            _write_desktop_agent_plan(run_dir, plan)
            autopsy = _write_failure_autopsy(project_path, run_dir, stopped, query_events_path, trajectory_path)
            return DesktopAgentResult(stopped, str(query_events_path), str(trajectory_path), str(stop_path), autopsy)

        runtime.pre_tool("desktop_agent", step=index, args={"action": step.action, "args": step.args})
        record_action(
            trajectory_path,
            f"desktop-agent step {index}: {step.action}",
            step=index,
            ok=None,
            action=step.action,
            args=step.args,
        )
        result = _execute_step(project_path, step)
        results.append(result)
        runtime.post_tool(
            "desktop_agent",
            step=index,
            ok=result.ok,
            summary=result.summary,
            data={"action": step.action, "result": result.data},
        )
        record_observation(
            trajectory_path,
            f"{step.action}: {result.summary}",
            step=index,
            ok=result.ok,
            action=step.action,
            result=result.data,
        )
        if not result.ok:
            failed = DesktopRun(False, "failed", f"step {index} {step.action} failed: {result.summary}", plan, tuple(results))
            runtime.stop("desktop agent failed", ok=False, failure_class="desktop_action_failed")
            _write_desktop_agent_plan(run_dir, plan)
            autopsy = _write_failure_autopsy(project_path, run_dir, failed, query_events_path, trajectory_path)
            return DesktopAgentResult(failed, str(query_events_path), str(trajectory_path), str(stop_path), autopsy)
        if verify_after and step.side_effect:
            verify = _execute_step(project_path, DesktopStep("screenshot", {}, "verify after action", requires_review=False))
            results.append(verify)
            if not verify.ok:
                failed = DesktopRun(False, "verify_failed", verify.summary, plan, tuple(results))
                runtime.stop("desktop agent verification failed", ok=False, failure_class="verify_failed")
                _write_desktop_agent_plan(run_dir, plan)
                autopsy = _write_failure_autopsy(project_path, run_dir, failed, query_events_path, trajectory_path)
                return DesktopAgentResult(failed, str(query_events_path), str(trajectory_path), str(stop_path), autopsy)
        time.sleep(bounded_delay)

    run = DesktopRun(True, "executed", f"executed {len(results)} desktop takeover result(s)", plan, tuple(results))
    runtime.stop("desktop agent completed", ok=True)
    _write_desktop_agent_plan(run_dir, plan)
    return DesktopAgentResult(run, str(query_events_path), str(trajectory_path), str(stop_path))


def render_desktop_agent_result(result: DesktopAgentResult) -> str:
    lines = [
        "# Desktop Agent",
        "",
        f"Status: {result.run.status}",
        f"OK: {str(result.ok).lower()}",
        result.run.summary,
        f"Stop file: {result.stop_file}",
        f"Query events: {result.query_events_path}",
        f"Trajectory: {result.trajectory_path}",
        "",
        "Steps:",
    ]
    for index, step in enumerate(result.run.plan.steps, start=1):
        lines.append(f"{index}. {step.action} {json.dumps(step.args, ensure_ascii=False)}")
    if result.run.results:
        lines.extend(["", "Results:"])
        for item in result.run.results:
            lines.append(f"- {item.action}: {'ok' if item.ok else 'fail'} - {item.summary}")
    return "\n".join(lines).rstrip() + "\n"


def _write_desktop_agent_plan(run_dir: Path, plan: DesktopPlan) -> None:
    (run_dir / "latest_plan.json").write_text(plan.to_json() + "\n", encoding="utf-8")


def _write_failure_autopsy(project: Path, run_dir: Path, run: DesktopRun, query_events_path: Path, trajectory_path: Path) -> str:
    report = build_agent_autopsy(
        project,
        trajectory_path=trajectory_path,
        query_events_path=query_events_path,
        failure_text=run.summary,
        source_agent="desktop_agent",
        title=f"Desktop Agent Autopsy: {run.status}",
        command=run.plan.objective,
    )
    return str(write_agent_autopsy(report, run_dir / "latest_autopsy.md"))


def _search_query(text: str) -> str:
    match = SEARCH_RE.search(text)
    if not match:
        return ""
    query = match.group(1).strip()
    query = URL_RE.sub("", query).strip(" ：:，,。.")
    return _strip_followup_commands(query)


def _open_app(text: str) -> str:
    match = OPEN_APP_RE.search(text)
    if not match:
        return ""
    app = match.group(1).strip(" ：:，,。.")
    if app.lower().startswith(("http", "search", "搜索", "搜")):
        return ""
    return app


def _browser_from_text(text: str, *, default: str) -> str:
    lowered = text.lower()
    if "chrome" in lowered or "谷歌浏览器" in text:
        return "Google Chrome"
    if "edge" in lowered or "微软浏览器" in text:
        return "Microsoft Edge"
    if "safari" in lowered:
        return "Safari"
    return default


def _type_text(text: str) -> str:
    match = TYPE_RE.search(text)
    if not match:
        return ""
    return _strip_followup_commands(match.group(1))


def _strip_followup_commands(text: str) -> str:
    value = str(text or "").strip()
    value = re.split(
        r"\s*(?:并|然后|再|and|then)\s*"
        r"(?=(?:截图|截屏|screenshot|等待|wait|按|hotkey|快捷键|type|输入|click|点击|点|search|搜索|搜|open|打开|启动)(?:\s|[:：]|\d|$))",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return value.strip(" ：:，,。.")


def _hotkey_keys(text: str) -> list[str]:
    match = HOTKEY_RE.search(text)
    if not match:
        return []
    return [part for part in re.split(r"[+, ]+", match.group(1).strip()) if part]


def _wants_screenshot(text: str) -> bool:
    lowered = text.lower()
    return "screenshot" in lowered or "截图" in text or "截屏" in text
