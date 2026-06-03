from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import json
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .code_index import search_code_index
from .context_providers import ContextProviderRequest, gather_context_providers, render_context_provider_results
from .project_rules import match_project_rules
from .task_state import task_dir


@dataclass(frozen=True)
class ArchitectStep:
    title: str
    detail: str
    owner: str = "editor"
    files: list[str] = field(default_factory=list)
    risk: str = "medium"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ArchitectPlan:
    plan_id: str
    task: str
    created_at: str
    context_refs: list[str]
    files: list[str]
    steps: list[ArchitectStep]
    risks: list[str]
    test_commands: list[list[str]]
    editor_contract: str
    artifact_path: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def architect_dir(project: str | Path) -> Path:
    return task_dir(Path(project).expanduser().resolve(strict=False)) / "architect_plans"


def create_architect_plan(
    project: str | Path,
    task: str,
    *,
    paths: Iterable[str] = (),
    tests: Iterable[Iterable[str]] = (),
    context_refs: Iterable[str] = (),
) -> ArchitectPlan:
    project_path = Path(project).expanduser().resolve(strict=False)
    task_text = task.strip()
    if not task_text:
        raise ValueError("architect task is empty")
    selected_paths = _select_paths(project_path, task_text, paths)
    refs = list(context_refs) or _default_context_refs(selected_paths)
    rules = match_project_rules(project_path, selected_paths)
    steps = _plan_steps(task_text, selected_paths)
    risks = _risks(task_text, selected_paths, rules)
    commands = [list(map(str, command)) for command in tests if list(command)] or _default_tests(project_path)
    plan_id = "arch-" + datetime.now().strftime("%Y%m%d%H%M%S")
    plan = ArchitectPlan(
        plan_id=plan_id,
        task=task_text,
        created_at=datetime.now().isoformat(timespec="seconds"),
        context_refs=refs,
        files=selected_paths,
        steps=steps,
        risks=risks,
        test_commands=commands,
        editor_contract=(
            "Editor may change only the listed files unless it first updates this plan; "
            "must show diff, run tests, classify failures, and leave source untouched when using isolated review."
        ),
    )
    path = write_architect_plan(project_path, plan)
    return replace(plan, artifact_path=str(path))


def write_architect_plan(project: str | Path, plan: ArchitectPlan) -> Path:
    directory = architect_dir(project)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{plan.plan_id}.json"
    path.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_architect_plan(project: str | Path, plan_id: str) -> ArchitectPlan:
    path = architect_dir(project) / f"{plan_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    steps = [ArchitectStep(**item) for item in payload.get("steps", [])]
    payload["steps"] = steps
    return ArchitectPlan(**payload)


def list_architect_plans(project: str | Path, *, limit: int = 20) -> list[ArchitectPlan]:
    directory = architect_dir(project)
    if not directory.exists():
        return []
    plans: list[ArchitectPlan] = []
    for path in sorted(directory.glob("arch-*.json"), reverse=True):
        try:
            plans.append(load_architect_plan(project, path.stem))
        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:110", exc)
            continue
        if len(plans) >= limit:
            break
    return plans


def render_architect_plan(project: str | Path, plan: ArchitectPlan, *, include_context: bool = False) -> str:
    lines = [
        f"# Architect Plan {plan.plan_id}",
        "",
        f"- task: {plan.task}",
        f"- created_at: {plan.created_at}",
        f"- files: {len(plan.files)}",
        f"- artifact: {plan.artifact_path or '-'}",
        "",
        "## Editor Contract",
        "",
        plan.editor_contract,
        "",
        "## Files",
        "",
    ]
    lines.extend(f"- {path}" for path in plan.files) if plan.files else lines.append("- No files selected yet.")
    lines.extend(["", "## Steps", ""])
    for index, step in enumerate(plan.steps, start=1):
        files = f" files={', '.join(step.files)}" if step.files else ""
        lines.append(f"{index}. [{step.owner}/{step.risk}]{files} {step.title}: {step.detail}")
    lines.extend(["", "## Risks", ""])
    lines.extend(f"- {risk}" for risk in plan.risks) if plan.risks else lines.append("- No specific risks identified.")
    lines.extend(["", "## Tests", ""])
    lines.extend("- " + " ".join(command) for command in plan.test_commands) if plan.test_commands else lines.append("- No tests detected.")
    if include_context:
        refs = [ContextProviderRequest(ref.lstrip("@").split(":", 1)[0], ref.split(":", 1)[1] if ":" in ref else "") for ref in plan.context_refs]
        lines.extend(["", "## Context", "", render_context_provider_results(gather_context_providers(project, refs)).rstrip()])
    return "\n".join(lines).rstrip() + "\n"


def _select_paths(project: Path, task: str, paths: Iterable[str]) -> list[str]:
    explicit = [str(path).strip().strip("/") for path in paths if str(path).strip()]
    if explicit:
        return sorted(dict.fromkeys(explicit))
    hits = search_code_index(project, task, limit=8, rebuild=False)
    selected = [hit.path for hit in hits]
    return sorted(dict.fromkeys(selected))


def _default_context_refs(paths: list[str]) -> list[str]:
    refs = ["@repo-map", "@problems", "@rules"]
    refs.extend(f"@file:{path}" for path in paths[:4])
    return refs


def _plan_steps(task: str, paths: list[str]) -> list[ArchitectStep]:
    key = _short_task(task)
    steps = [
        ArchitectStep("Confirm scope", f"Verify intended behavior and constraints for {key}.", "architect", paths[:3], "low"),
        ArchitectStep("Apply minimal edit", "Use exact diff-first edits; avoid unrelated refactors.", "editor", paths[:5], "medium"),
        ArchitectStep("Run verification", "Run detected tests or supplied commands; classify any failure before retry.", "editor", paths[:5], "medium"),
        ArchitectStep("Review bundle", "Summarize changed files, risks, test output, and follow-up work.", "reviewer", paths[:5], "low"),
    ]
    if re.search(r"\b(api|auth|permission|sandbox|security|mcp)\b", task, re.I):
        steps.insert(1, ArchitectStep("Security pass", "Check permission, secret, and trust boundaries before editing.", "architect", paths[:5], "high"))
    return steps


def _risks(task: str, paths: list[str], rules: list[object]) -> list[str]:
    risks = []
    if not paths:
        risks.append("No target files selected; editor must inspect before modifying.")
    if len(paths) > 6:
        risks.append("Wide file scope; prefer isolated worktree and review bundle.")
    if rules:
        risks.append(f"{len(rules)} project rule(s) apply; editor must respect them.")
    if re.search(r"\b(delete|migration|schema|auth|secret|sandbox|network|daemon)\b", task, re.I):
        risks.append("Task touches high-risk runtime/security behavior.")
    return risks


def _default_tests(project: Path) -> list[list[str]]:
    if (project / "tests").exists():
        return [["python3", "-m", "unittest", "discover", "-s", "tests"]]
    if (project / "package.json").exists():
        return [["npm", "test"]]
    return []


def _short_task(task: str) -> str:
    compact = " ".join(task.split())
    return compact[:80] + ("..." if len(compact) > 80 else "")
