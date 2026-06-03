from __future__ import annotations

import difflib
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from quantagent.code_index import CodeDiagnostic, editor_diagnostics
from quantagent.project_rules import ProjectRule, match_project_rules, render_project_rules


REVIEWABLE_SUFFIXES = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml"}
DEFAULT_MAX_DIFF_LINES = 400


@dataclass(frozen=True)
class ReviewFinding:
    severity: str
    title: str
    detail: str
    path: str | None = None
    line: int | None = None
    rule_source: str | None = None


@dataclass(frozen=True)
class DiffReviewReport:
    project: str
    paths: list[str]
    findings: list[ReviewFinding] = field(default_factory=list)
    included_rules: list[ProjectRule] = field(default_factory=list)
    diff: str = ""
    staged: bool = False
    git_available: bool = False
    diff_truncated: bool = False


def review_changed_files(
    project: str | Path,
    paths: Iterable[str | Path] | None = None,
    *,
    staged: bool = False,
    max_diff_lines: int = DEFAULT_MAX_DIFF_LINES,
) -> DiffReviewReport:
    project_path = Path(project).expanduser().resolve(strict=False)
    git_available = _is_git_repo(project_path)
    explicit_paths = list(paths) if paths is not None else None
    selected_paths = _selected_paths(project_path, explicit_paths, staged=staged, git_available=git_available)
    included_rules = match_project_rules(project_path, selected_paths)
    findings = _review_findings(project_path, selected_paths)
    diff, diff_truncated = _review_diff(project_path, selected_paths, staged=staged, git_available=git_available, max_lines=max_diff_lines)
    return DiffReviewReport(
        project=str(project_path),
        paths=selected_paths,
        findings=findings,
        included_rules=included_rules,
        diff=diff,
        staged=staged,
        git_available=git_available,
        diff_truncated=diff_truncated,
    )


def create_diff_review(
    project: str | Path,
    paths: Iterable[str | Path] | None = None,
    *,
    staged: bool = False,
    max_diff_lines: int = DEFAULT_MAX_DIFF_LINES,
) -> DiffReviewReport:
    return review_changed_files(project, paths, staged=staged, max_diff_lines=max_diff_lines)


def render_diff_review_report(report: DiffReviewReport, *, include_diff: bool = True) -> str:
    lines = ["# Changed File Review", "", "## Findings", ""]
    if report.findings:
        for finding in report.findings:
            location = _finding_location(finding)
            rule = f" ({finding.rule_source})" if finding.rule_source else ""
            lines.append(f"- [{finding.severity}] {finding.title}{location}{rule}: {finding.detail}")
    else:
        lines.append("- No findings.")

    lines.extend(["", "## Included Rules", ""])
    if report.included_rules:
        lines.append(render_project_rules(report.included_rules).rstrip())
    else:
        lines.append("No project rules matched.")

    lines.extend(["", "## Reviewed Paths", ""])
    if report.paths:
        lines.extend(f"- {path}" for path in report.paths)
    else:
        lines.append("- No changed paths found.")

    if include_diff:
        lines.extend(["", "## Diff", ""])
        if report.diff:
            suffix = " (trimmed)" if report.diff_truncated else ""
            lines.append(f"```diff{suffix}")
            lines.append(report.diff.rstrip())
            lines.append("```")
        else:
            lines.append("No diff available.")

    return "\n".join(lines).rstrip() + "\n"


def render_review_report(report: DiffReviewReport, *, include_diff: bool = True) -> str:
    return render_diff_review_report(report, include_diff=include_diff)


def _selected_paths(project: Path, paths: list[str | Path] | None, *, staged: bool, git_available: bool) -> list[str]:
    if paths is not None:
        return _normalize_selected_paths(project, paths)
    if git_available:
        return _git_changed_paths(project, staged=staged)
    return _all_reviewable_paths(project)


def _normalize_selected_paths(project: Path, paths: Iterable[str | Path]) -> list[str]:
    selected: set[str] = set()
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        target = path if path.is_absolute() else project / path
        target = target.resolve(strict=False)
        if not _inside_project(project, target):
            continue
        if target.is_dir():
            for child in _iter_reviewable_files(target, project):
                selected.add(_rel(project, child))
            continue
        selected.add(_rel(project, target))
    return sorted(selected)


def _all_reviewable_paths(project: Path) -> list[str]:
    return sorted(_rel(project, path) for path in _iter_reviewable_files(project, project))


def _iter_reviewable_files(root: Path, project: Path) -> list[Path]:
    return [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix.lower() in REVIEWABLE_SUFFIXES and not _skip(path, project)
    ]


def _review_findings(project: Path, paths: list[str]) -> list[ReviewFinding]:
    selected = set(paths)
    if not selected:
        return []

    diagnostics = editor_diagnostics(project, include_imports=False)
    findings = [_finding_from_diagnostic(item) for item in diagnostics if item.path in selected and item.code in _reviewed_diagnostic_codes()]
    return sorted(findings, key=_finding_sort_key)


def _reviewed_diagnostic_codes() -> set[str]:
    return {"todo_comment", "fixme_comment", "python_syntax_error"}


def _finding_from_diagnostic(diagnostic: CodeDiagnostic) -> ReviewFinding:
    titles = {
        "todo_comment": "TODO comment",
        "fixme_comment": "FIXME comment",
        "python_syntax_error": "Python syntax error",
    }
    return ReviewFinding(
        severity=diagnostic.level,
        title=titles.get(diagnostic.code, diagnostic.code.replace("_", " ").title()),
        detail=diagnostic.message,
        path=diagnostic.path,
        line=diagnostic.line,
    )


def _review_diff(project: Path, paths: list[str], *, staged: bool, git_available: bool, max_lines: int) -> tuple[str, bool]:
    if git_available:
        return _git_diff(project, paths, staged=staged, max_lines=max_lines)
    return _diff_against_empty(project, paths, max_lines=max_lines)


def _is_git_repo(project: Path) -> bool:
    if shutil.which("git") is None:
        return False
    result = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "--is-inside-work-tree"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _git_changed_paths(project: Path, *, staged: bool) -> list[str]:
    args = ["git", "-C", str(project), "diff", "--cached" if staged else "--name-only"]
    if staged:
        args.append("--name-only")
    args.append("--")
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    paths = {_normalize_rel(line) for line in result.stdout.splitlines() if _normalize_rel(line)}
    if not staged:
        paths.update(_git_untracked_paths(project))
    return sorted(paths)


def _git_untracked_paths(project: Path) -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(project), "ls-files", "--others", "--exclude-standard"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return set()
    return {_normalize_rel(line) for line in result.stdout.splitlines() if _normalize_rel(line)}


def _git_diff(project: Path, paths: list[str], *, staged: bool, max_lines: int) -> tuple[str, bool]:
    args = ["git", "-C", str(project), "diff"]
    if staged:
        args.append("--cached")
    args.append("--")
    args.extend(paths)
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        return "", False
    diff = result.stdout
    if not staged:
        untracked_paths = sorted(set(paths) & _git_untracked_paths(project))
        extra_diff, _truncated = _diff_against_empty(project, untracked_paths, max_lines=max_lines)
        if extra_diff:
            diff = diff.rstrip("\n") + ("\n" if diff else "") + extra_diff + "\n"
    return _trim_lines(diff, max_lines)


def _diff_against_empty(project: Path, paths: list[str], *, max_lines: int) -> tuple[str, bool]:
    chunks: list[str] = []
    for rel in paths:
        target = (project / rel).resolve(strict=False)
        if not _inside_project(project, target) or not target.is_file():
            continue
        text = target.read_text(encoding="utf-8", errors="replace")
        chunks.extend(
            difflib.unified_diff(
                [],
                text.splitlines(keepends=True),
                fromfile="/dev/null",
                tofile=f"b/{rel}",
                lineterm="\n",
            )
        )
    return _trim_lines("".join(chunks), max_lines)


def _trim_lines(text: str, max_lines: int) -> tuple[str, bool]:
    if not text:
        return "", False
    lines = text.splitlines()
    if len(lines) <= max(0, max_lines):
        return text.rstrip("\n"), False
    return "\n".join(lines[: max(0, max_lines)]) + "\n[diff trimmed]", True


def _finding_location(finding: ReviewFinding) -> str:
    if not finding.path:
        return ""
    if finding.line is None:
        return f" {finding.path}"
    return f" {finding.path}:{finding.line}"


def _finding_sort_key(finding: ReviewFinding) -> tuple[int, str, int, str]:
    severity_order = {"error": 0, "warn": 1, "warning": 1, "info": 2}
    return (severity_order.get(finding.severity, 3), finding.path or "", finding.line or 0, finding.title)


def _inside_project(project: Path, target: Path) -> bool:
    project_real = project.resolve(strict=False)
    target_real = target.resolve(strict=False)
    return target_real == project_real or project_real in target_real.parents


def _rel(project: Path, target: Path) -> str:
    try:
        return str(target.resolve(strict=False).relative_to(project.resolve(strict=False))).replace("\\", "/")
    except ValueError:
        return str(target).replace("\\", "/")


def _normalize_rel(path: str | Path) -> str:
    return str(path).replace("\\", "/").strip().strip("/")


def _skip(path: Path, project: Path) -> bool:
    rel = path.resolve(strict=False).relative_to(project.resolve(strict=False))
    skipped = {".git", ".quantagent", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}
    return any(part in skipped or part.startswith(".pytest_cache") for part in rel.parts)
