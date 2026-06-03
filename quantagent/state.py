from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .project import read_text_preview, snapshot_project


@dataclass
class ProjectState:
    project: str
    updated_at: str
    stage: str
    hard_rules: list[str]
    baselines: list[str]
    latest_messages: list[str]
    scripts: list[str]
    known_conclusions: list[str] = field(default_factory=list)


def infer_stage(latest_messages: list[Path]) -> str:
    names = " ".join(path.name for path in latest_messages)
    if "PRE_TICK" in names or "P4" in names:
        return "pre_tick_p4_ready"
    if "P5" in names:
        return "p5_decline_analysis"
    if "P6" in names:
        return "p6_position_model"
    return "unknown"


def build_project_state(project: Path) -> ProjectState:
    snapshot = snapshot_project(project, "AI_协作交接")
    return ProjectState(
        project=str(project),
        updated_at=datetime.now().isoformat(timespec="seconds"),
        stage=infer_stage(snapshot.latest_messages),
        hard_rules=[
            "Use *_dedup.csv baselines only.",
            "Do not use original 1253-trade polluted samples for conclusions.",
            "09:25 is signal time; entry is 09:30 continuous auction.",
            "Real execution and tick capacity outrank parameter optimization.",
            "Any PF improvement must be audited for data leakage and sample pollution.",
        ],
        baselines=[str(p) for p in snapshot.baseline_files],
        latest_messages=[str(p) for p in snapshot.latest_messages[:10]],
        scripts=[str(p) for p in snapshot.scripts],
        known_conclusions=[
            "Time hard limits were harmful in prior tests.",
            "Primary threshold candidate is t1_auction_return <= -9%.",
            "(-9,-8] is diagnostic only until proven otherwise.",
            "P4 real 09:30 execution validation waits for tick data.",
        ],
    )


def render_project_state_markdown(state: ProjectState) -> str:
    lines = [
        "# PROJECT_STATE_COMPACT",
        "",
        f"- updated_at: {state.updated_at}",
        f"- stage: {state.stage}",
        f"- project: {state.project}",
        "",
        "## Hard Rules",
    ]
    lines.extend(f"- {item}" for item in state.hard_rules)
    lines.extend(["", "## Known Conclusions"])
    lines.extend(f"- {item}" for item in state.known_conclusions)
    lines.extend(["", "## Baselines"])
    lines.extend(f"- {Path(item).name}" for item in state.baselines)
    lines.extend(["", "## Latest Messages"])
    lines.extend(f"- {Path(item).name}" for item in state.latest_messages)
    lines.extend(["", "## Scripts"])
    lines.extend(f"- {Path(item).name}" for item in state.scripts)
    return "\n".join(lines) + "\n"


def write_project_state(project: Path) -> tuple[Path, Path]:
    state = build_project_state(project)
    comm = project / "AI_协作交接"
    out_dir = comm if comm.exists() else project
    md_path = out_dir / "PROJECT_STATE_COMPACT.md"
    json_path = out_dir / "PROJECT_STATE_COMPACT.json"
    md_path.write_text(render_project_state_markdown(state), encoding="utf-8")
    json_path.write_text(json.dumps(asdict(state), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return md_path, json_path


def state_preview(project: Path) -> str:
    md_path = (project / "AI_协作交接" / "PROJECT_STATE_COMPACT.md")
    if md_path.exists():
        return read_text_preview(md_path, max_chars=2000)
    state = build_project_state(project)
    return render_project_state_markdown(state)

