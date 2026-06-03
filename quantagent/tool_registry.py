from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .tools import CommandResult, run_command, run_command_args


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    risk: str


TOOLS = {
    "status": ToolSpec("status", "Read project state and recent handoff files", "low"),
    "audit": ToolSpec("audit", "Run quant-specific static checks", "low"),
    "context": ToolSpec("context", "Build compact model context from project memory", "low"),
    "state": ToolSpec("state", "Write compressed PROJECT_STATE files", "low"),
    "todo": ToolSpec("todo", "Maintain P-stage research todo board", "low"),
    "hooks": ToolSpec("hooks", "Run communication directory change hooks", "low"),
    "safety": ToolSpec("safety", "Classify commands and quant claims before acting", "low"),
    "review": ToolSpec("review", "Create dual-model audit request", "low"),
    "consensus": ToolSpec("consensus", "Create/check three-pass ChatGPT consistency gates", "medium"),
    "model-test": ToolSpec("model-test", "Test OpenAI-compatible Chat Completions connectivity", "medium"),
    "ask": ToolSpec("ask", "Ask the configured model with compact quant project context", "medium"),
    "chat": ToolSpec("chat", "Open an orange terminal chat interface with project context", "medium"),
    "run-next": ToolSpec("run-next", "Run the safe auto loop with researcher/auditor/data_engineer roles", "medium"),
    "loop": ToolSpec("loop", "Run one deterministic agent loop pass", "medium"),
    "experiment": ToolSpec("experiment", "Run standardized quant experiments and register outputs", "medium"),
    "registry": ToolSpec("registry", "List structured experiment results", "low"),
    "quant_auditor": ToolSpec("quant_auditor", "Deep audit CSV/result files for quant-specific failure modes", "medium"),
    "py_compile": ToolSpec("py_compile", "Compile a Python script", "low"),
    "run_p4_help": ToolSpec("run_p4_help", "Probe P4 real execution framework CLI", "low"),
    "shell": ToolSpec("shell", "Run guarded shell command", "medium"),
    "desktop.live": ToolSpec("desktop.live", "Render the local desktop live status panel", "low"),
    "desktop.open": ToolSpec("desktop.open", "Plan or run a reviewed local open action for apps, URLs, paths, searches, or Terminal", "high"),
    "desktop.shot": ToolSpec("desktop.shot", "Capture a local desktop screenshot", "medium"),
    "desktop.grid": ToolSpec("desktop.grid", "Capture a screenshot with grid targets for reviewed clicks", "medium"),
    "desktop.ax": ToolSpec("desktop.ax", "Capture a local accessibility element snapshot", "medium"),
    "desktop.ocr": ToolSpec("desktop.ocr", "Run local OCR over a screenshot or image", "medium"),
    "desktop.som": ToolSpec("desktop.som", "Capture a Set-of-Marks target map from screenshot, AX, OCR, and optional grid", "medium"),
    "desktop.tokenize": ToolSpec("desktop.tokenize", "Merge screenshot, AX, OCR, SoM, and grid state into desktop tokens", "medium"),
    "desktop.decide": ToolSpec("desktop.decide", "Choose one deterministic desktop action from a goal and desktop tokens", "medium"),
    "desktop.daemon": ToolSpec("desktop.daemon", "Run a bounded observe-tokenize-decide-act-verify desktop loop", "high"),
    "desktop.eval": ToolSpec("desktop.eval", "Run desktop daemon L4/L5 evaluation suites and score autonomy readiness", "high"),
    "desktop.night": ToolSpec("desktop.night", "Run the Night Daemon for long-running reviewed desktop work", "high"),
    "desktop.night.enqueue": ToolSpec("desktop.night.enqueue", "Enqueue a Night Daemon desktop task for later execution", "medium"),
    "desktop.night.status": ToolSpec("desktop.night.status", "Read Night Daemon state, queue, and latest run status", "medium"),
    "desktop.night.stop": ToolSpec("desktop.night.stop", "Stop a running Night Daemon loop through its control plane", "medium"),
    "desktop.night.resume": ToolSpec("desktop.night.resume", "Resume a reviewed Night Daemon loop from saved daemon state", "high"),
    "desktop.find": ToolSpec("desktop.find", "Search desktop AX/OCR/SoM/grid targets by text", "medium"),
    "desktop.web-search": ToolSpec("desktop.web-search", "Plan or run a reviewed browser search through the local desktop", "high"),
    "desktop.find-click": ToolSpec("desktop.find-click", "Plan or run a reviewed click on a matched desktop target", "high"),
    "desktop.run": ToolSpec("desktop.run", "Run a reviewed desktop action plan", "high"),
    "desktop.som-click": ToolSpec("desktop.som-click", "Click a reviewed Set-of-Marks target", "high"),
    "desktop.click": ToolSpec("desktop.click", "Click a reviewed local desktop coordinate", "high"),
    "desktop.type": ToolSpec("desktop.type", "Type reviewed text into the local desktop focus", "high"),
    "desktop.hotkey": ToolSpec("desktop.hotkey", "Send a reviewed local desktop keyboard shortcut", "high"),
}


def list_tools() -> list[ToolSpec]:
    return list(TOOLS.values())


def run_registered_tool(name: str, project: Path, argument: str = "") -> CommandResult:
    if name == "py_compile":
        target = Path(argument)
        if not target.is_absolute():
            target = project / target
        return run_command_args(["python3", "-m", "py_compile", target], cwd=project)
    if name == "run_p4_help":
        script = next(project.glob("**/p4_real_execution_framework.py"), None)
        if not script:
            return CommandResult(name, 2, "", "p4_real_execution_framework.py not found")
        return run_command_args(["python3", script, "--help"], cwd=script.parent, timeout=60)
    if name == "shell":
        return run_command(argument, cwd=project)
    return CommandResult(name, 2, "", f"unknown tool: {name}")
