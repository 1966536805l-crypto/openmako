from __future__ import annotations

import shlex
from dataclasses import asdict, dataclass
from pathlib import Path

from .branding import PRIMARY_CLI
from .chat_ui import choose_context_decision
from .context_pack import build_context_pack
from .repo_map import load_repo_map, repo_map_path


@dataclass(frozen=True)
class CheapPlan:
    project: str
    task: str
    model_calls: int
    context_mode: str
    reasons: tuple[str, ...]
    estimated_tokens: int
    token_budget: int
    token_pressure: float
    pressure_state: str
    repo_map_status: str
    repo_map_files: int
    free_first_commands: tuple[str, ...]
    paid_next_step: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        payload["free_first_commands"] = list(self.free_first_commands)
        return payload


def build_cheap_plan(project: str | Path, task: str | None = None) -> CheapPlan:
    project_path = Path(project).expanduser().resolve(strict=False)
    task_text = " ".join((task or "").split())
    decision = choose_context_decision(task_text or "status")
    pack = build_context_pack(project_path, task=task_text or None, token_budget=decision.token_budget)
    pressure = pack.estimated_tokens / max(1, pack.token_budget)
    state = _pressure_state(pressure)
    repo_status, repo_files = _repo_map_status(project_path)
    free_commands = _free_first_commands(project_path, task_text, repo_status)
    paid_next = _paid_next_step(project_path, task_text)
    return CheapPlan(
        project=str(project_path),
        task=task_text,
        model_calls=0,
        context_mode=decision.mode,
        reasons=decision.reasons,
        estimated_tokens=pack.estimated_tokens,
        token_budget=pack.token_budget,
        token_pressure=round(pressure, 4),
        pressure_state=state,
        repo_map_status=repo_status,
        repo_map_files=repo_files,
        free_first_commands=tuple(free_commands),
        paid_next_step=paid_next,
    )


def render_cheap_plan(plan: CheapPlan) -> str:
    lines = [
        "# Mako Cheap Plan",
        "",
        f"- project: {plan.project}",
        f"- task: {plan.task or '(none)'}",
        f"- model_calls: {plan.model_calls}",
        f"- context_mode: {plan.context_mode}",
        f"- estimated_tokens: {plan.estimated_tokens}/{plan.token_budget} ({round(plan.token_pressure * 100, 2)}%, {plan.pressure_state})",
        f"- repo_map: {plan.repo_map_status}" + (f" ({plan.repo_map_files} files)" if plan.repo_map_files else ""),
        f"- reason: {'; '.join(plan.reasons) if plan.reasons else 'default cheap-first route'}",
        "",
        "## Free First",
        "",
    ]
    lines.extend(f"{index}. `{command}`" for index, command in enumerate(plan.free_first_commands, start=1))
    lines.extend(
        [
            "",
            "## Paid Only If Needed",
            "",
            f"- `{plan.paid_next_step}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _pressure_state(pressure: float) -> str:
    if pressure >= 0.95:
        return "blocking"
    if pressure >= 0.90:
        return "compact-soon"
    if pressure >= 0.80:
        return "watch"
    return "cheap"


def _repo_map_status(project: Path) -> tuple[str, int]:
    path = repo_map_path(project)
    if not path.exists():
        return "missing", 0
    try:
        repo_map = load_repo_map(project)
    except (OSError, ValueError):
        return "unreadable", 0
    return "ready", len(repo_map.files)


def _free_first_commands(project: Path, task: str, repo_status: str) -> list[str]:
    project_arg = _quote(str(project))
    commands = [
        f"{PRIMARY_CLI} doctor --project {project_arg}",
    ]
    if task:
        task_arg = _quote(task)
        commands.append(f"{PRIMARY_CLI} context --project {project_arg} --task {task_arg}")
        if repo_status == "ready":
            commands.append(f"{PRIMARY_CLI} repo-map search --project {project_arg} {task_arg}")
        else:
            commands.append(f"{PRIMARY_CLI} repo-map build --project {project_arg}")
    else:
        commands.append(f"{PRIMARY_CLI} ux --project {project_arg} status --no-context-pack")
        commands.append(f"{PRIMARY_CLI} repo-map build --project {project_arg}")
    return commands


def _paid_next_step(project: Path, task: str) -> str:
    project_arg = _quote(str(project))
    if task:
        return f"{PRIMARY_CLI} chat --project {project_arg} --once {_quote(task)}"
    return f"{PRIMARY_CLI} chat --project {project_arg}"


def _quote(value: str) -> str:
    return shlex.quote(value)
