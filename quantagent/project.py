from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass
class ProjectSnapshot:
    project: Path
    claude_md: Path | None
    communication_dir: Path | None
    latest_messages: list[Path]
    baseline_files: list[Path]
    scripts: list[Path]


def is_chat_markdown(path: Path) -> bool:
    """Return True for generated chat transcripts/reports."""
    name = path.name
    return name == "CHAT_REVIEW_STREAM.md" or name.startswith("CHAT_REPORT_")


def is_obsolete_handoff_markdown(path: Path) -> bool:
    """Return True for handoff files superseded by later gates."""
    return path.name.startswith("40_CLAUDE")


def is_latest_markdown_source(path: Path) -> bool:
    name = path.name
    ignored_prefixes = ("QUANTAGENT_", "PROJECT_STATE_COMPACT")
    if name.startswith(ignored_prefixes):
        return False
    if is_chat_markdown(path) or is_obsolete_handoff_markdown(path):
        return False
    return True


def latest_markdown_files(directory: Path, limit: int = 100) -> list[Path]:
    if not directory.exists():
        return []
    files = [
        p
        for p in directory.glob("*.md")
        if p.is_file() and is_latest_markdown_source(p)
    ]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]


def is_home_project(project: Path) -> bool:
    try:
        return project.expanduser().resolve(strict=False) == Path.home().resolve(strict=False)
    except OSError:
        return project.expanduser() == Path.home()


def find_baseline_files(project: Path) -> list[Path]:
    if is_home_project(project):
        return []
    patterns = [
        "agent2_scenario_A_0p2_0p2_position_dedup.csv",
        "agent2_scenario_D_0p3_0p3_position_dedup.csv",
        "tick_data_request_*.csv",
    ]
    return _find_named_matches(project, patterns)


def find_project_scripts(project: Path) -> list[Path]:
    if is_home_project(project):
        return []
    names = [
        "p4_real_execution_framework.py",
        "p5_2025_decline_decomposition.py",
        "p5b_shallow_band_rolling_stability.py",
        "p6_account_equity_position_model.py",
    ]
    return _find_named_matches(project, names)


def _find_named_matches(project: Path, names_or_patterns: list[str]) -> list[Path]:
    found: list[Path] = []
    try:
        for root, dirs, files in os.walk(project):
            dirs[:] = [item for item in dirs if not _should_skip_walk_dir(Path(root) / item)]
            root_path = Path(root)
            for filename in files:
                if any(Path(filename).match(pattern) for pattern in names_or_patterns):
                    found.append(root_path / filename)
    except InterruptedError:
        pass
    return sorted(set(found))


def _should_skip_walk_dir(path: Path) -> bool:
    parts = path.parts
    if "Saved Application State" in parts:
        return True
    if path.name.endswith(".savedState"):
        return True
    return False


def snapshot_project(project: Path, communication_dir_name: str) -> ProjectSnapshot:
    comm = project / communication_dir_name
    claude_md = project / "CLAUDE.md"
    return ProjectSnapshot(
        project=project,
        claude_md=claude_md if claude_md.exists() else None,
        communication_dir=comm if comm.exists() else None,
        latest_messages=latest_markdown_files(comm),
        baseline_files=find_baseline_files(project),
        scripts=find_project_scripts(project),
    )


def read_text_preview(path: Path, max_chars: int = 2400) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"[read failed: {exc}]"
    return text[:max_chars]
