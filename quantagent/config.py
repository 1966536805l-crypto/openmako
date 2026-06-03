from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgentConfig:
    project: Path
    communication_dir_name: str = "AI_协作交接"
    primary_model: str = "gpt-5.5"
    review_model: str = "gpt-5.5"

    @property
    def communication_dir(self) -> Path:
        return self.project / self.communication_dir_name


def load_config(project: str | None = None) -> AgentConfig:
    selected = project or os.environ.get("QUANTAGENT_PROJECT")
    default_project = Path.cwd()
    return AgentConfig(
        project=Path(selected).expanduser() if selected else default_project,
        primary_model=os.environ.get("QUANTAGENT_MODEL", "gpt-5.5"),
        review_model=os.environ.get("QUANTAGENT_REVIEW_MODEL", "gpt-5.5"),
    )
