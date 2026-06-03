from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import json
import re
import subprocess
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .task_state import task_dir


@dataclass(frozen=True)
class PullRequestPlan:
    pr_id: str
    title: str
    task: str
    branch: str
    base_branch: str
    created_at: str
    test_commands: list[list[str]] = field(default_factory=list)
    changed_paths: list[str] = field(default_factory=list)
    checklist: list[str] = field(default_factory=list)
    artifact_path: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def pr_plan_dir(project: str | Path) -> Path:
    return task_dir(Path(project).expanduser().resolve(strict=False)) / "pr_plans"


def create_pr_plan(
    project: str | Path,
    task: str,
    *,
    title: str = "",
    base_branch: str = "",
    branch: str = "",
    tests: Iterable[Iterable[str]] = (),
) -> PullRequestPlan:
    project_path = Path(project).expanduser().resolve(strict=False)
    task_text = task.strip()
    if not task_text:
        raise ValueError("PR task is empty")
    current_base = base_branch or _git_branch(project_path) or "main"
    selected_title = title or _title(task_text)
    selected_branch = branch or "mako/" + _slug(selected_title)
    pr_id = "prplan-" + datetime.now().strftime("%Y%m%d%H%M%S")
    plan = PullRequestPlan(
        pr_id=pr_id,
        title=selected_title,
        task=task_text,
        branch=selected_branch,
        base_branch=current_base,
        created_at=datetime.now().isoformat(timespec="seconds"),
        test_commands=[list(map(str, command)) for command in tests if list(command)] or _default_tests(project_path),
        changed_paths=_git_changed_paths(project_path),
        checklist=[
            "Create or switch to the planned branch.",
            "Apply edits in an isolated or reviewable workflow.",
            "Run listed test commands.",
            "Open PR with task, changed paths, test output, and residual risks.",
            "Continue from review comments by updating the same PR plan.",
        ],
    )
    path = write_pr_plan(project_path, plan)
    return replace(plan, artifact_path=str(path))


def write_pr_plan(project: str | Path, plan: PullRequestPlan) -> Path:
    directory = pr_plan_dir(project)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{plan.pr_id}.json"
    path.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_pr_plan(project: str | Path, pr_id: str) -> PullRequestPlan:
    path = pr_plan_dir(project) / f"{pr_id}.json"
    return PullRequestPlan(**json.loads(path.read_text(encoding="utf-8")))


def list_pr_plans(project: str | Path, *, limit: int = 20) -> list[PullRequestPlan]:
    directory = pr_plan_dir(project)
    if not directory.exists():
        return []
    plans: list[PullRequestPlan] = []
    for path in sorted(directory.glob("prplan-*.json"), reverse=True):
        try:
            plans.append(load_pr_plan(project, path.stem))
        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:94", exc)
            continue
        if len(plans) >= limit:
            break
    return plans


def render_pr_plan(plan: PullRequestPlan) -> str:
    lines = [
        f"# PR Plan {plan.pr_id}",
        "",
        f"- title: {plan.title}",
        f"- branch: {plan.branch}",
        f"- base_branch: {plan.base_branch}",
        f"- created_at: {plan.created_at}",
        f"- artifact: {plan.artifact_path or '-'}",
        "",
        "## Task",
        "",
        plan.task,
        "",
        "## Changed Paths",
        "",
    ]
    lines.extend(f"- {path}" for path in plan.changed_paths) if plan.changed_paths else lines.append("- No git changes detected yet.")
    lines.extend(["", "## Tests", ""])
    lines.extend("- " + " ".join(command) for command in plan.test_commands) if plan.test_commands else lines.append("- No tests detected.")
    lines.extend(["", "## Checklist", ""])
    lines.extend(f"- [ ] {item}" for item in plan.checklist)
    return "\n".join(lines).rstrip() + "\n"


def _git_branch(project: Path) -> str:
    result = subprocess.run(["git", "-C", str(project), "branch", "--show-current"], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def _git_changed_paths(project: Path) -> list[str]:
    result = subprocess.run(["git", "-C", str(project), "diff", "--name-only"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return []
    return sorted(line.strip() for line in result.stdout.splitlines() if line.strip())


def _default_tests(project: Path) -> list[list[str]]:
    if (project / "tests").exists():
        return [["python3", "-m", "unittest", "discover", "-s", "tests"]]
    if (project / "package.json").exists():
        return [["npm", "test"]]
    return []


def _title(task: str) -> str:
    compact = " ".join(task.split())
    return compact[:72] or "Mako change"


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", text.lower()).strip("-")
    return slug[:48] or "change"
