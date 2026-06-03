from __future__ import annotations

import shlex
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol

from .query_runtime import QueryRuntime
from .trajectory import record_action, record_observation


@dataclass(frozen=True)
class AgentBackendStep:
    step_id: str
    kind: str
    summary: str
    command_template: tuple[str, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["command_template"] = list(self.command_template)
        return payload


@dataclass(frozen=True)
class AgentBackendStepResult:
    step_id: str
    backend_id: str
    ok: bool
    exit_code: int
    command: tuple[str, ...]
    output: str
    failure_class: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["command"] = list(self.command)
        return payload


@dataclass(frozen=True)
class AgentBackendRunResult:
    backend_id: str
    status: str
    task: str
    trajectory_path: str
    query_events_path: str
    steps: tuple[AgentBackendStepResult, ...]
    failure_class: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "PASSED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_id": self.backend_id,
            "status": self.status,
            "task": self.task,
            "trajectory_path": self.trajectory_path,
            "query_events_path": self.query_events_path,
            "failure_class": self.failure_class,
            "steps": [step.to_dict() for step in self.steps],
        }


class AgentBackend(Protocol):
    backend_id: str

    def plan(self, task: str) -> list[AgentBackendStep]:
        ...

    def run_step(
        self,
        step: AgentBackendStep,
        workspace: str | Path,
        *,
        runtime: QueryRuntime,
        trajectory_path: str | Path,
        step_number: int,
        task: str,
        timeout: int,
    ) -> AgentBackendStepResult:
        ...

    def stream_events(self) -> Iterable[dict[str, Any]]:
        ...

    def stop(self) -> None:
        ...


class CommandAgentBackend:
    def __init__(
        self,
        backend_id: str,
        command_template: Iterable[str],
        *,
        step_summary: str = "",
    ) -> None:
        self.backend_id = _normalize_backend_id(backend_id)
        self.command_template = tuple(str(part) for part in command_template)
        if not self.command_template:
            raise ValueError("agent backend command_template is empty")
        self.step_summary = step_summary or f"run {self.backend_id}"
        self._events: list[dict[str, Any]] = []
        self._stopped = False

    def plan(self, task: str) -> list[AgentBackendStep]:
        return [
            AgentBackendStep(
                step_id="run",
                kind="command",
                summary=self.step_summary,
                command_template=self.command_template,
                data={"backend_id": self.backend_id, "task_preview": _preview(task, 160)},
            )
        ]

    def run_step(
        self,
        step: AgentBackendStep,
        workspace: str | Path,
        *,
        runtime: QueryRuntime,
        trajectory_path: str | Path,
        step_number: int,
        task: str,
        timeout: int,
    ) -> AgentBackendStepResult:
        workspace_path = Path(workspace).expanduser().resolve(strict=False)
        command = self.render_command(step, task=task, workspace=workspace_path)
        command_text = shlex.join(command)
        runtime.pre_tool(
            self.backend_id,
            step=step_number,
            args={"command": list(command), "step_id": step.step_id, "backend_id": self.backend_id},
        )
        record_action(
            trajectory_path,
            f"{self.backend_id} executing: {command_text}",
            step=step_number,
            ok=None,
            command=list(command),
            backend_id=self.backend_id,
            step_id=step.step_id,
        )

        try:
            completed = subprocess.run(
                command,
                cwd=str(workspace_path),
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            exit_code = int(completed.returncode)
            output = _bounded_output(completed.stdout, completed.stderr)
        except FileNotFoundError as exc:
            exit_code = 127
            output = f"command not found: {command[0]} ({exc})"
        except subprocess.TimeoutExpired as exc:
            exit_code = 124
            output = f"command timed out after {timeout}s\n{_bounded_output(exc.stdout, exc.stderr)}".strip()

        ok = exit_code == 0
        failure_class = "" if ok else classify_backend_failure(exit_code, output)
        summary = f"{self.backend_id} exited {exit_code}\n{output}".strip()
        runtime.post_tool(
            self.backend_id,
            step=step_number,
            ok=ok,
            summary=summary,
            data={
                "backend_id": self.backend_id,
                "command": list(command),
                "exit_code": exit_code,
                "failure_class": failure_class,
            },
        )
        record_observation(
            trajectory_path,
            summary,
            step=step_number,
            ok=ok,
            command=list(command),
            backend_id=self.backend_id,
            exit_code=exit_code,
            failure_class=failure_class,
        )
        result = AgentBackendStepResult(
            step_id=step.step_id,
            backend_id=self.backend_id,
            ok=ok,
            exit_code=exit_code,
            command=tuple(command),
            output=output,
            failure_class=failure_class,
        )
        self._events.append(result.to_dict())
        return result

    def render_command(self, step: AgentBackendStep, *, task: str, workspace: str | Path) -> list[str]:
        workspace_text = str(Path(workspace).expanduser().resolve(strict=False))
        return [part.replace("{task}", task).replace("{workspace}", workspace_text) for part in step.command_template]

    def stream_events(self) -> Iterable[dict[str, Any]]:
        return tuple(self._events)

    def stop(self) -> None:
        self._stopped = True


class LocalShellStubBackend(CommandAgentBackend):
    def __init__(self, command_template: Iterable[str]) -> None:
        super().__init__("local_shell_stub", command_template, step_summary="run local shell stub")


class CodexWrapperBackend(CommandAgentBackend):
    def __init__(self, command_template: Iterable[str] | None = None) -> None:
        super().__init__(
            "codex_wrapper",
            command_template
            or (
                "codex",
                "exec",
                "--skip-git-repo-check",
                "-C",
                "{workspace}",
                "{task}",
            ),
            step_summary="run Codex CLI in non-interactive exec mode",
        )

    @property
    def available(self) -> bool:
        return shutil.which(self.command_template[0]) is not None


def run_agent_backend_once(
    project: str | Path,
    backend: AgentBackend,
    task: str,
    *,
    timeout: int = 600,
) -> AgentBackendRunResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    output_dir = project_path / ".quantagent" / "agent_backends" / _run_id(backend.backend_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    query_events_path = output_dir / "query_events.jsonl"
    trajectory_path = output_dir / "trajectory.jsonl"
    runtime = QueryRuntime(project_path, event_path=query_events_path)
    runtime.start(task, mode=f"agent_backend:{backend.backend_id}", data={"backend_id": backend.backend_id})

    results: list[AgentBackendStepResult] = []
    failure_class = ""
    for index, step in enumerate(backend.plan(task), start=1):
        result = backend.run_step(
            step,
            project_path,
            runtime=runtime,
            trajectory_path=trajectory_path,
            step_number=index,
            task=task,
            timeout=timeout,
        )
        results.append(result)
        if not result.ok:
            failure_class = result.failure_class or "agent_backend_failed"
            break

    ok = all(result.ok for result in results)
    runtime.stop(
        f"agent backend {backend.backend_id} {'passed' if ok else 'failed'}",
        ok=ok,
        failure_class="" if ok else failure_class,
    )
    return AgentBackendRunResult(
        backend_id=backend.backend_id,
        status="PASSED" if ok else "FAILED",
        task=task,
        trajectory_path=str(trajectory_path),
        query_events_path=str(query_events_path),
        steps=tuple(results),
        failure_class="" if ok else failure_class,
    )


def classify_backend_failure(exit_code: int, output: str) -> str:
    lowered = output.lower()
    if exit_code == 124 or "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    if exit_code == 127 or "command not found" in lowered:
        return "command_not_found"
    if "assertionerror" in lowered or "assertion failed" in lowered:
        return "assertion"
    if "permission" in lowered or "policy_blocked" in lowered or "approval" in lowered:
        return "policy_blocked"
    if "importerror" in lowered or "modulenotfounderror" in lowered:
        return "import"
    if "syntaxerror" in lowered:
        return "syntax"
    if "test" in lowered and ("failed" in lowered or "failure" in lowered):
        return "verification_failed"
    return "agent_backend_failed"


def _normalize_backend_id(value: str) -> str:
    normalized = str(value).strip().replace("-", "_")
    if not normalized:
        raise ValueError("agent backend id is empty")
    return normalized


def _run_id(backend_id: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{_normalize_backend_id(backend_id)}_{timestamp}"


def _bounded_output(stdout: str | bytes | None, stderr: str | bytes | None, *, max_chars: int = 8000) -> str:
    stdout_text = _decode_process_text(stdout)
    stderr_text = _decode_process_text(stderr)
    return _preview(f"stdout:\n{stdout_text}\nstderr:\n{stderr_text}", max_chars)


def _decode_process_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _preview(text: str, max_chars: int) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max(0, max_chars - 1)].rstrip() + "..."
