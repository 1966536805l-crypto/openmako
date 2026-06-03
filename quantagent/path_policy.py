from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from quantagent.safety import ALLOW, ASK, DENY, RAW_DATA_MARKERS


PathOperation = Literal["read", "write"]


@dataclass(frozen=True)
class PathPolicyDecision:
    action: str
    level: str
    reasons: tuple[str, ...]
    path: Path

    @property
    def allowed(self) -> bool:
        return self.action == ALLOW

    def render(self) -> str:
        suffix = "" if not self.reasons else ": " + "; ".join(self.reasons)
        return f"{self.action.upper()} {self.level} {self.path}{suffix}"


def _real(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _inside(path: Path, parent: Path) -> bool:
    path_real = _real(path)
    parent_real = _real(parent)
    return path_real == parent_real or parent_real in path_real.parents


def _looks_like_raw_data(path_text: str) -> bool:
    lowered = path_text.lower()
    return any(marker.lower() in lowered for marker in RAW_DATA_MARKERS)


def resolve_project_path(project: str | Path, path: str | Path) -> Path:
    """Resolve a project-relative path and require canonical project containment."""
    project_real = _real(Path(project))
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = project_real / target
    target_real = _real(target)
    if not _inside(target_real, project_real):
        raise ValueError(f"path escapes project: {path}")
    return target_real


def assess_project_path(
    project: str | Path,
    path: str | Path,
    operation: PathOperation = "read",
    communication_dir_name: str = "AI_协作交接",
) -> PathPolicyDecision:
    """Classify a read/write path operation against Mako project policy."""
    if operation not in {"read", "write"}:
        raise ValueError(f"unsupported path operation: {operation}")

    project_real = _real(Path(project))
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = project_real / target
    target_real = _real(target)

    if not _inside(target_real, project_real):
        return PathPolicyDecision(
            DENY,
            "L4_PROJECT_ESCAPE",
            ("path escapes configured quant project",),
            target_real,
        )

    if operation == "read":
        return PathPolicyDecision(
            ALLOW,
            "L0_PROJECT_READ",
            ("path is inside configured quant project",),
            target_real,
        )

    relative = target_real.relative_to(project_real)
    communication_dir = project_real / communication_dir_name
    writable_dirs = (
        communication_dir,
        communication_dir / "quantagent_results",
        project_real / ".quantagent",
    )
    if _looks_like_raw_data(str(relative)):
        return PathPolicyDecision(
            DENY,
            "L4_RAW_DATA_PROTECTED",
            ("raw/tick data path is read-only by default",),
            target_real,
        )
    if any(_inside(target_real, directory) for directory in writable_dirs):
        return PathPolicyDecision(
            ALLOW,
            "L1_PROJECT_OUTPUT",
            ("Mako output path",),
            target_real,
        )
    return PathPolicyDecision(
        ASK,
        "L2_PROJECT_WRITE",
        ("project source/data write needs explicit intent",),
        target_real,
    )
