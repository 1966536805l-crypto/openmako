from __future__ import annotations

import subprocess
import shlex
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .ansi_strip import strip_ansi
from .guards import command_risk
from .safety import ALLOW, DENY, SafetyPolicy, assess_command
from .tool_output import maybe_persist_tool_output


@dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    blocked: bool = False
    reason: str = ""


def _bounded_output(cwd: Path, command: str, stream: str, content: str) -> str:
    if not content:
        return content
    content = strip_ansi(content)
    output_id = hashlib.sha256(f"{stream}\0{command}".encode("utf-8", errors="replace")).hexdigest()[:16]
    return maybe_persist_tool_output(cwd, content, f"command_{stream}", output_id)


def run_command(
    command: str,
    cwd: Path,
    timeout: int = 120,
    allow_risky: bool = False,
    policy: SafetyPolicy | None = None,
) -> CommandResult:
    """Run a user-facing shell command after policy approval.

    This remains a compatibility wrapper for command strings. New internal
    tools should use run_command_args so arguments never pass through a shell.
    """
    decision = assess_command(command, cwd=cwd, policy=policy)
    legacy_risks = command_risk(command)
    if decision.action != ALLOW or legacy_risks:
        return CommandResult(
            command=command,
            returncode=126,
            stdout="",
            stderr="",
            blocked=True,
            reason=(
                f"{decision.render()}"
                + ("" if not legacy_risks else "; legacy: " + ", ".join(legacy_risks))
                + "; user-facing shell only executes low-risk or guarded-write commands"
            ),
        )
    proc = subprocess.run(
        command,
        cwd=str(cwd),
        shell=True,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    return CommandResult(
        command,
        proc.returncode,
        _bounded_output(cwd, command, "stdout", proc.stdout),
        _bounded_output(cwd, command, "stderr", proc.stderr),
    )


def run_command_args(
    args: Sequence[str | Path],
    cwd: Path,
    timeout: int = 120,
    allow_risky: bool = False,
    policy: SafetyPolicy | None = None,
) -> CommandResult:
    """Run an internal tool command with an argv list and shell=False."""
    argv = [str(arg) for arg in args]
    command = shlex.join(argv)
    decision = assess_command(command, cwd=cwd, policy=policy)
    legacy_risks = command_risk(command)
    if decision.action == DENY or ((decision.action != ALLOW or legacy_risks) and not allow_risky):
        return CommandResult(
            command=command,
            returncode=126,
            stdout="",
            stderr="",
            blocked=True,
            reason=f"{decision.render()}" + ("" if not legacy_risks else "; legacy: " + ", ".join(legacy_risks)),
        )
    proc = subprocess.run(
        argv,
        cwd=str(cwd),
        shell=False,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    return CommandResult(
        command,
        proc.returncode,
        _bounded_output(cwd, command, "stdout", proc.stdout),
        _bounded_output(cwd, command, "stderr", proc.stderr),
    )


def py_compile(path: Path) -> CommandResult:
    return run_command_args(["python3", "-m", "py_compile", path], cwd=path.parent)
