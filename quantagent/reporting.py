from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .project import snapshot_project
from .quant_checks import audit_project


def build_status_report(project: Path) -> str:
    snapshot = snapshot_project(project, "AI_协作交接")
    lines = [
        "# Mako Status",
        "",
        f"- time: {datetime.now().isoformat(timespec='seconds')}",
        f"- project: {project}",
        f"- CLAUDE.md: {snapshot.claude_md or 'missing'}",
        f"- communication dir: {snapshot.communication_dir or 'missing'}",
        "",
        "## Latest Messages",
    ]
    lines.extend(f"- {p.name}" for p in snapshot.latest_messages[:10])
    lines.extend(["", "## Baselines"])
    lines.extend(f"- {p.name}" for p in snapshot.baseline_files)
    lines.extend(["", "## Scripts"])
    lines.extend(f"- {p.name}" for p in snapshot.scripts)
    return "\n".join(lines) + "\n"


def build_audit_report(project: Path) -> str:
    findings = audit_project(project)
    lines = ["# Mako Audit", "", f"- project: {project}", ""]
    if not findings:
        lines.append("No blocking findings from starter checks.")
    else:
        for finding in findings:
            path = f" ({finding.path})" if finding.path else ""
            lines.append(f"- [{finding.level}] {finding.title}{path}: {finding.detail}")
    return "\n".join(lines) + "\n"

