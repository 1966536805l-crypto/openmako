from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .task_state import task_dir


@dataclass(frozen=True)
class RemoteRunnerSpec:
    runner_id: str
    task: str
    created_at: str
    setup_commands: list[list[str]] = field(default_factory=list)
    run_commands: list[list[str]] = field(default_factory=list)
    network_allowlist: list[str] = field(default_factory=list)
    secrets_required: list[str] = field(default_factory=list)
    timeout_minutes: int = 30
    artifact_path: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def remote_runner_dir(project: str | Path) -> Path:
    return task_dir(Path(project).expanduser().resolve(strict=False)) / "remote_runners"


def create_remote_runner_spec(
    project: str | Path,
    task: str,
    *,
    setup_commands: Iterable[Iterable[str]] = (),
    run_commands: Iterable[Iterable[str]] = (),
    network_allowlist: Iterable[str] = (),
    secrets_required: Iterable[str] = (),
    timeout_minutes: int = 30,
) -> RemoteRunnerSpec:
    project_path = Path(project).expanduser().resolve(strict=False)
    runner_id = "runner-" + datetime.now().strftime("%Y%m%d%H%M%S")
    spec = RemoteRunnerSpec(
        runner_id=runner_id,
        task=task.strip(),
        created_at=datetime.now().isoformat(timespec="seconds"),
        setup_commands=[list(map(str, command)) for command in setup_commands if list(command)],
        run_commands=[list(map(str, command)) for command in run_commands if list(command)] or _default_run_commands(project_path),
        network_allowlist=[str(item) for item in network_allowlist],
        secrets_required=[str(item) for item in secrets_required],
        timeout_minutes=max(1, int(timeout_minutes)),
    )
    path = write_remote_runner_spec(project_path, spec)
    return replace(spec, artifact_path=str(path))


def write_remote_runner_spec(project: str | Path, spec: RemoteRunnerSpec) -> Path:
    directory = remote_runner_dir(project)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{spec.runner_id}.json"
    path.write_text(json.dumps(spec.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_remote_runner_spec(project: str | Path, runner_id: str) -> RemoteRunnerSpec:
    path = remote_runner_dir(project) / f"{runner_id}.json"
    return RemoteRunnerSpec(**json.loads(path.read_text(encoding="utf-8")))


def list_remote_runner_specs(project: str | Path, *, limit: int = 20) -> list[RemoteRunnerSpec]:
    directory = remote_runner_dir(project)
    if not directory.exists():
        return []
    specs: list[RemoteRunnerSpec] = []
    for path in sorted(directory.glob("runner-*.json"), reverse=True):
        try:
            specs.append(load_remote_runner_spec(project, path.stem))
        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:79", exc)
            continue
        if len(specs) >= limit:
            break
    return specs


def render_remote_runner_spec(spec: RemoteRunnerSpec) -> str:
    lines = [
        f"# Remote Runner Spec {spec.runner_id}",
        "",
        f"- task: {spec.task or '-'}",
        f"- timeout_minutes: {spec.timeout_minutes}",
        f"- artifact: {spec.artifact_path or '-'}",
        "",
        "## Network Allowlist",
        "",
    ]
    lines.extend(f"- {item}" for item in spec.network_allowlist) if spec.network_allowlist else lines.append("- none")
    lines.extend(["", "## Secrets Required", ""])
    lines.extend(f"- {item}" for item in spec.secrets_required) if spec.secrets_required else lines.append("- none")
    lines.extend(["", "## Setup Commands", ""])
    lines.extend("- " + " ".join(command) for command in spec.setup_commands) if spec.setup_commands else lines.append("- none")
    lines.extend(["", "## Run Commands", ""])
    lines.extend("- " + " ".join(command) for command in spec.run_commands) if spec.run_commands else lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def _default_run_commands(project: Path) -> list[list[str]]:
    if (project / "tests").exists():
        return [["python3", "-m", "unittest", "discover", "-s", "tests"]]
    if (project / "package.json").exists():
        return [["npm", "test"]]
    return []
