from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import json
import difflib
import os
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from .guards import command_risk
from .query_runtime import QueryRuntime
from .safety import ALLOW, DENY, SafetyPolicy, assess_command
from .tools import CommandResult, run_command_args


EXCLUDED_PARTS = {
    ".git",
    ".quantagent",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "quantagent_tasks",
    "quantagent_sessions",
}

SANDBOX_AUTO = "auto"
SANDBOX_EXEC = "sandbox-exec"
SANDBOX_WORKTREE = "worktree"
SANDBOX_HOST = "host"


@dataclass(frozen=True)
class SandboxCapability:
    backend: str
    available: bool
    reason: str = ""
    executable: str = ""
    write_scope: str = ""
    network_policy: str = "not_enforced"
    supports_filesystem_scope: bool = False
    supports_network_policy: bool = False
    fallback_backend: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IsolatedWorktree:
    worktree_id: str
    project: str
    workspace_path: str
    created_at: str
    reason: str = ""
    status: str = "ready"
    copied_files: int = 0
    excluded: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IsolatedRunResult:
    ok: bool
    worktree: IsolatedWorktree
    command: str
    returncode: int
    executed_command: str = ""
    stdout_preview: str = ""
    stderr_preview: str = ""
    blocked: bool = False
    reason: str = ""
    duration_ms: int = 0
    sandbox_backend: str = SANDBOX_WORKTREE
    sandbox_available: bool = True
    network: bool = False
    network_policy: str = "not_enforced"
    sandbox_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IsolationReview:
    review_id: str
    worktree_id: str
    project: str
    workspace_path: str
    created_at: str
    changed_paths: list[str] = field(default_factory=list)
    new_paths: list[str] = field(default_factory=list)
    deleted_paths: list[str] = field(default_factory=list)
    unified_diff: str = ""
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def isolation_root(project: str | Path) -> Path:
    project_path = Path(project).expanduser().resolve(strict=False)
    legacy = project_path / ".quantagent" / "quantagent_isolated_worktrees"
    if legacy.exists():
        return legacy
    base = project_path / "AI_协作交接"
    if not base.exists():
        base = project_path / ".quantagent"
    return base / "quantagent_isolated_worktrees"


def create_isolated_worktree(
    project: str | Path,
    *,
    reason: str = "",
    include: Sequence[str | Path] = (),
) -> IsolatedWorktree:
    project_path = Path(project).expanduser().resolve(strict=False)
    root = isolation_root(project_path)
    worktree_id = "iso-" + uuid.uuid4().hex[:12]
    workspace = root / worktree_id / "workspace"
    excluded: list[str] = []
    root.mkdir(parents=True, exist_ok=True)
    if include:
        copied = _copy_selected(project_path, workspace, include, excluded)
    else:
        copied = _copy_project(project_path, workspace, excluded)
    record = IsolatedWorktree(
        worktree_id=worktree_id,
        project=str(project_path),
        workspace_path=str(workspace),
        created_at=datetime.now().isoformat(timespec="seconds"),
        reason=reason,
        copied_files=copied,
        excluded=sorted(set(excluded))[:200],
        metadata={"mode": "selected" if include else "project_copy"},
    )
    _write_worktree(record)
    QueryRuntime(project_path).emit(
        "worktree_isolation",
        f"isolated worktree created: {worktree_id}",
        ok=True,
        data={"worktree_id": worktree_id, "workspace_path": str(workspace), "copied_files": copied},
    )
    return record


def load_isolated_worktree(project: str | Path, worktree_id: str) -> IsolatedWorktree:
    path = isolation_root(project) / worktree_id / "manifest.json"
    if not path.exists():
        raise KeyError(f"isolated worktree not found: {worktree_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("isolated worktree manifest must be a JSON object")
    return IsolatedWorktree(
        worktree_id=str(payload.get("worktree_id") or worktree_id),
        project=str(payload.get("project") or project),
        workspace_path=str(payload.get("workspace_path") or ""),
        created_at=str(payload.get("created_at") or ""),
        reason=str(payload.get("reason") or ""),
        status=str(payload.get("status") or "ready"),
        copied_files=int(payload.get("copied_files") or 0),
        excluded=[str(item) for item in payload.get("excluded", [])],
        metadata=dict(payload.get("metadata") or {}),
    )


def list_isolated_worktrees(project: str | Path, *, limit: int = 20) -> list[IsolatedWorktree]:
    root = isolation_root(project)
    if not root.exists():
        return []
    rows: list[IsolatedWorktree] = []
    for path in sorted(root.glob("iso-*/manifest.json"), reverse=True):
        try:
            rows.append(load_isolated_worktree(project, path.parent.name))
        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:193", exc)
            continue
    return rows[: max(0, limit)]


def detect_sandbox_backend(preferred: str = SANDBOX_AUTO, *, network: bool = False) -> SandboxCapability:
    backend = _normalize_sandbox_backend(preferred)
    if backend == SANDBOX_AUTO:
        sandbox_exec = _sandbox_exec_path()
        if sandbox_exec:
            return _sandbox_exec_capability(sandbox_exec, network=network)
        return SandboxCapability(
            backend=SANDBOX_WORKTREE,
            available=True,
            reason="sandbox-exec unavailable; falling back to copy-on-write worktree isolation only",
            write_scope="isolated workspace copy",
            network_policy=_fallback_network_policy(network),
            fallback_backend=SANDBOX_WORKTREE,
        )
    if backend == SANDBOX_EXEC:
        sandbox_exec = _sandbox_exec_path()
        if not sandbox_exec:
            return SandboxCapability(
                backend=SANDBOX_EXEC,
                available=False,
                reason="sandbox-exec requested but not found",
                write_scope="isolated workspace copy",
                network_policy="deny" if not network else "allow_requested",
                supports_filesystem_scope=True,
                supports_network_policy=True,
            )
        return _sandbox_exec_capability(sandbox_exec, network=network)
    if backend == SANDBOX_WORKTREE:
        return SandboxCapability(
            backend=SANDBOX_WORKTREE,
            available=True,
            reason="copy-on-write worktree isolation only; no OS process sandbox is enforced",
            write_scope="isolated workspace copy",
            network_policy=_fallback_network_policy(network),
            fallback_backend=SANDBOX_WORKTREE,
        )
    if backend == SANDBOX_HOST:
        return SandboxCapability(
            backend=SANDBOX_HOST,
            available=True,
            reason="host subprocess execution in the isolated workspace; no OS process sandbox is enforced",
            write_scope="host process with cwd set to isolated workspace",
            network_policy=_fallback_network_policy(network),
            fallback_backend=SANDBOX_HOST,
        )
    raise ValueError(f"unknown sandbox backend: {preferred}")


def build_sandboxed_command(
    command: Sequence[str | Path],
    workspace: str | Path,
    *,
    capability: SandboxCapability | None = None,
    sandbox_backend: str = SANDBOX_AUTO,
    network: bool = False,
) -> tuple[list[str], str]:
    cap = capability or detect_sandbox_backend(sandbox_backend, network=network)
    argv = [str(arg) for arg in command]
    if cap.backend != SANDBOX_EXEC:
        return argv, ""
    if not cap.available or not cap.executable:
        raise RuntimeError(cap.reason or "sandbox-exec backend is unavailable")
    profile = sandbox_exec_profile(workspace, network=network)
    return [cap.executable, "-p", profile, *argv], profile


def sandbox_exec_profile(workspace: str | Path, *, network: bool = False) -> str:
    workspace_path = Path(workspace).expanduser().resolve(strict=False)
    read_paths = _sandbox_read_paths(workspace_path)
    write_paths = _sandbox_write_paths(workspace_path)
    read_rules = "\n".join(f"    (subpath {_profile_string(path)})" for path in read_paths)
    write_rules = "\n".join(f"    (subpath {_profile_string(path)})" for path in write_paths)
    network_rule = "(allow network*)\n" if network else "(deny network*)\n"
    return (
        "(version 1)\n"
        "(deny default)\n"
        "(import \"system.sb\")\n"
        "(allow process*)\n"
        "(allow signal (target self))\n"
        "(allow sysctl-read)\n"
        "(allow mach-lookup)\n"
        "(allow file-read-metadata)\n"
        "(allow file-read*\n"
        f"{read_rules}\n"
        "    (literal \"/dev/null\")\n"
        "    (literal \"/dev/urandom\"))\n"
        "(allow file-write*\n"
        f"{write_rules}\n"
        "    (literal \"/dev/null\"))\n"
        f"{network_rule}"
    )


def run_in_isolated_worktree(
    project: str | Path,
    command: Sequence[str | Path],
    *,
    worktree_id: str = "",
    timeout: int = 120,
    allow_risky: bool = False,
    reason: str = "",
    sandbox_backend: str = SANDBOX_AUTO,
    network: bool = False,
) -> IsolatedRunResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    record = load_isolated_worktree(project_path, worktree_id) if worktree_id else create_isolated_worktree(project_path, reason=reason or "isolated run")
    workspace = Path(record.workspace_path)
    capability = detect_sandbox_backend(sandbox_backend, network=network)
    original_command = shlex.join(str(arg) for arg in command)
    if not capability.available:
        return IsolatedRunResult(
            ok=False,
            worktree=record,
            command=original_command,
            returncode=126,
            executed_command=original_command,
            blocked=True,
            reason=capability.reason,
            sandbox_backend=capability.backend,
            sandbox_available=False,
            network=network,
            network_policy=capability.network_policy,
            sandbox_reason=capability.reason,
        )
    started = time.monotonic()
    if capability.backend == SANDBOX_EXEC:
        result, executed_command = _run_command_args_with_sandbox(
            command,
            cwd=workspace,
            timeout=timeout,
            allow_risky=allow_risky,
            capability=capability,
            network=network,
        )
    else:
        result = run_command_args(command, cwd=workspace, timeout=timeout, allow_risky=allow_risky)
        executed_command = result.command
    duration_ms = round((time.monotonic() - started) * 1000)
    ok = result.returncode == 0 and not result.blocked
    QueryRuntime(project_path).emit(
        "worktree_isolation",
        "isolated command passed" if ok else "isolated command failed",
        ok=ok,
        data={
            "worktree_id": record.worktree_id,
            "command": original_command or result.command,
            "executed_command": executed_command,
            "returncode": result.returncode,
            "blocked": result.blocked,
            "sandbox_backend": capability.backend,
            "network_policy": capability.network_policy,
        },
    )
    return IsolatedRunResult(
        ok=ok,
        worktree=record,
        command=original_command or result.command,
        returncode=result.returncode,
        executed_command=executed_command,
        stdout_preview=_preview(result.stdout),
        stderr_preview=_preview(result.stderr),
        blocked=result.blocked,
        reason=result.reason,
        duration_ms=duration_ms,
        sandbox_backend=capability.backend,
        sandbox_available=capability.available,
        network=network,
        network_policy=capability.network_policy,
        sandbox_reason=capability.reason,
    )


def remove_isolated_worktree(project: str | Path, worktree_id: str) -> IsolatedWorktree:
    record = load_isolated_worktree(project, worktree_id)
    root = Path(record.workspace_path).parent
    shutil.rmtree(root, ignore_errors=True)
    return IsolatedWorktree(
        worktree_id=record.worktree_id,
        project=record.project,
        workspace_path=record.workspace_path,
        created_at=record.created_at,
        reason=record.reason,
        status="removed",
        copied_files=record.copied_files,
        excluded=record.excluded,
        metadata=record.metadata,
    )


def create_isolation_review(project: str | Path, worktree_id: str, *, max_diff_chars: int = 80_000) -> IsolationReview:
    project_path = Path(project).expanduser().resolve(strict=False)
    record = load_isolated_worktree(project_path, worktree_id)
    workspace = Path(record.workspace_path)
    source_files = _file_map(project_path)
    workspace_files = _file_map(workspace)
    changed: list[str] = []
    new: list[str] = []
    deleted: list[str] = []
    diff_parts: list[str] = []
    for rel in sorted(source_files | workspace_files):
        source = project_path / rel
        target = workspace / rel
        source_exists = rel in source_files
        target_exists = rel in workspace_files
        if source_exists and not target_exists:
            deleted.append(rel)
            diff_parts.append(_file_diff(source, None, rel))
        elif target_exists and not source_exists:
            new.append(rel)
            diff_parts.append(_file_diff(None, target, rel))
        elif source_exists and target_exists and source.read_bytes() != target.read_bytes():
            changed.append(rel)
            diff_parts.append(_file_diff(source, target, rel))
    unified = "\n".join(part for part in diff_parts if part)
    if len(unified) > max_diff_chars:
        unified = unified[: max_diff_chars - 24] + "\n[diff truncated]\n"
    review = IsolationReview(
        review_id="review-" + uuid.uuid4().hex[:12],
        worktree_id=worktree_id,
        project=str(project_path),
        workspace_path=str(workspace),
        created_at=datetime.now().isoformat(timespec="seconds"),
        changed_paths=changed,
        new_paths=new,
        deleted_paths=deleted,
        unified_diff=unified,
    )
    _write_review(project_path, review)
    QueryRuntime(project_path).emit(
        "worktree_isolation",
        f"isolation review created: {review.review_id}",
        ok=True,
        data={"worktree_id": worktree_id, "review_id": review.review_id, "changed": len(changed), "new": len(new), "deleted": len(deleted)},
    )
    return review


def load_isolation_review(project: str | Path, review_id: str) -> IsolationReview:
    root = isolation_root(project)
    for path in root.glob(f"iso-*/{review_id}.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("isolation review must be a JSON object")
        return _review_from_payload(payload, review_id)
    raise KeyError(f"isolation review not found: {review_id}")


def list_isolation_reviews(project: str | Path, *, limit: int = 20) -> list[IsolationReview]:
    root = isolation_root(project)
    if not root.exists():
        return []
    reviews: list[IsolationReview] = []
    for path in sorted(root.glob("iso-*/review-*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                reviews.append(_review_from_payload(payload, path.stem))
        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:455", exc)
            continue
        if len(reviews) >= limit:
            break
    return reviews


def apply_isolation_review(project: str | Path, review_id: str, *, reviewed: bool = False) -> IsolationReview:
    if not reviewed:
        raise PermissionError("isolation review must be explicitly marked reviewed before apply")
    project_path = Path(project).expanduser().resolve(strict=False)
    review = load_isolation_review(project_path, review_id)
    workspace = Path(review.workspace_path)
    for rel in [*review.changed_paths, *review.new_paths]:
        source = workspace / rel
        target = project_path / rel
        if not source.exists():
            raise FileNotFoundError(f"review source file missing: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for rel in review.deleted_paths:
        target = project_path / rel
        if target.exists() and target.is_file():
            target.unlink()
    applied = IsolationReview(
        review_id=review.review_id,
        worktree_id=review.worktree_id,
        project=review.project,
        workspace_path=review.workspace_path,
        created_at=review.created_at,
        changed_paths=review.changed_paths,
        new_paths=review.new_paths,
        deleted_paths=review.deleted_paths,
        unified_diff=review.unified_diff,
        status="applied",
    )
    _write_review(project_path, applied)
    QueryRuntime(project_path).emit(
        "worktree_isolation",
        f"isolation review applied: {review.review_id}",
        ok=True,
        data={"worktree_id": review.worktree_id, "review_id": review.review_id},
    )
    return applied


def render_isolated_worktrees(records: list[IsolatedWorktree]) -> str:
    if not records:
        return "No isolated worktrees.\n"
    lines = ["# Isolated Worktrees", ""]
    for record in records:
        lines.append(f"- [{record.status}] {record.worktree_id}: files={record.copied_files} path={record.workspace_path}")
        if record.reason:
            lines.append(f"  reason: {record.reason}")
    return "\n".join(lines) + "\n"


def render_isolation_review(review: IsolationReview, *, include_diff: bool = False) -> str:
    lines = [
        f"# Isolation Review {review.review_id}",
        "",
        f"- worktree_id: {review.worktree_id}",
        f"- status: {review.status}",
        f"- changed: {len(review.changed_paths)}",
        f"- new: {len(review.new_paths)}",
        f"- deleted: {len(review.deleted_paths)}",
    ]
    for title, paths in (("Changed", review.changed_paths), ("New", review.new_paths), ("Deleted", review.deleted_paths)):
        if paths:
            lines.extend(["", f"## {title}", ""])
            lines.extend(f"- {path}" for path in paths)
    if include_diff and review.unified_diff:
        lines.extend(["", "## Diff", "", "```diff", review.unified_diff.rstrip(), "```"])
    return "\n".join(lines).rstrip() + "\n"


def render_isolated_worktree(record: IsolatedWorktree) -> str:
    lines = [
        f"# Isolated Worktree {record.worktree_id}",
        "",
        f"- status: {record.status}",
        f"- project: {record.project}",
        f"- workspace_path: {record.workspace_path}",
        f"- created_at: {record.created_at}",
        f"- copied_files: {record.copied_files}",
        f"- reason: {record.reason or '-'}",
    ]
    if record.excluded:
        lines.extend(["", "## Excluded", ""])
        lines.extend(f"- {item}" for item in record.excluded[:50])
    return "\n".join(lines) + "\n"


def _write_worktree(record: IsolatedWorktree) -> Path:
    path = Path(record.workspace_path).parent / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_review(project: Path, review: IsolationReview) -> Path:
    path = isolation_root(project) / review.worktree_id / f"{review.review_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(review.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _copy_project(project: Path, workspace: Path, excluded: list[str]) -> int:
    count = 0
    for source in sorted(project.rglob("*")):
        rel = source.relative_to(project)
        if _skip(rel):
            excluded.append(str(rel))
            continue
        target = workspace / rel
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if not source.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        count += 1
    return count


def _copy_selected(project: Path, workspace: Path, include: Sequence[str | Path], excluded: list[str]) -> int:
    count = 0
    for raw in include:
        source = (project / raw).resolve(strict=False) if not Path(raw).is_absolute() else Path(raw).resolve(strict=False)
        try:
            rel = source.relative_to(project)
        except ValueError:
            excluded.append(str(raw))
            continue
        if _skip(rel) or not source.exists():
            excluded.append(str(rel))
            continue
        if source.is_dir():
            for child in sorted(source.rglob("*")):
                child_rel = child.relative_to(project)
                if _skip(child_rel) or not child.is_file():
                    continue
                target = workspace / child_rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(child, target)
                count += 1
        elif source.is_file():
            target = workspace / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            count += 1
    return count


def _skip(rel: Path) -> bool:
    text = str(rel)
    return any(part in EXCLUDED_PARTS or part == "quantagent_isolated_worktrees" for part in rel.parts) or text.startswith("AI_协作交接/quantagent_isolated_worktrees")


def _file_map(root: Path) -> set[str]:
    files: set[str] = set()
    if not root.exists():
        return files
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _skip(rel):
            continue
        files.add(str(rel))
    return files


def _file_diff(old: Path | None, new: Path | None, rel: str) -> str:
    old_lines = _read_lines(old)
    new_lines = _read_lines(new)
    return "".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
        )
    )


def _read_lines(path: Path | None) -> list[str]:
    if path is None or not path.exists():
        return []
    if path.stat().st_size > 2_000_000:
        return [f"[large file omitted: {path.name}]\n"]
    data = path.read_bytes()
    if b"\0" in data[:4096]:
        return [f"[binary file omitted: {path.name}]\n"]
    return data.decode("utf-8", errors="replace").splitlines(keepends=True)


def _review_from_payload(payload: dict[str, Any], review_id: str) -> IsolationReview:
    return IsolationReview(
        review_id=str(payload.get("review_id") or review_id),
        worktree_id=str(payload.get("worktree_id") or ""),
        project=str(payload.get("project") or ""),
        workspace_path=str(payload.get("workspace_path") or ""),
        created_at=str(payload.get("created_at") or ""),
        changed_paths=[str(item) for item in payload.get("changed_paths", [])],
        new_paths=[str(item) for item in payload.get("new_paths", [])],
        deleted_paths=[str(item) for item in payload.get("deleted_paths", [])],
        unified_diff=str(payload.get("unified_diff") or ""),
        status=str(payload.get("status") or "pending"),
    )


def _normalize_sandbox_backend(preferred: str) -> str:
    value = (preferred or SANDBOX_AUTO).strip().lower().replace("_", "-")
    aliases = {
        "macos": SANDBOX_EXEC,
        "macos-sandbox": SANDBOX_EXEC,
        "sandboxexec": SANDBOX_EXEC,
        "sandbox-exec": SANDBOX_EXEC,
        "seatbelt": SANDBOX_EXEC,
        "cow": SANDBOX_WORKTREE,
        "copy": SANDBOX_WORKTREE,
        "copy-on-write": SANDBOX_WORKTREE,
        "workspace": SANDBOX_WORKTREE,
        "worktree": SANDBOX_WORKTREE,
        "none": SANDBOX_HOST,
        "direct": SANDBOX_HOST,
        "host": SANDBOX_HOST,
        "auto": SANDBOX_AUTO,
    }
    return aliases.get(value, value)


def _sandbox_exec_path() -> str:
    found = shutil.which("sandbox-exec")
    if found:
        return found
    candidate = Path("/usr/bin/sandbox-exec")
    if candidate.exists() and os.access(candidate, os.X_OK):
        return str(candidate)
    return ""


def _sandbox_exec_capability(executable: str, *, network: bool) -> SandboxCapability:
    return SandboxCapability(
        backend=SANDBOX_EXEC,
        available=True,
        reason="macOS sandbox-exec available; writes are scoped to the isolated workspace",
        executable=executable,
        write_scope="isolated workspace",
        network_policy="allow" if network else "deny",
        supports_filesystem_scope=True,
        supports_network_policy=True,
    )


def _fallback_network_policy(network: bool) -> str:
    return "not_enforced_allow_requested" if network else "not_enforced_deny_requested"


def _sandbox_read_paths(workspace: Path) -> list[Path]:
    raw_paths = [
        workspace,
        Path("/bin"),
        Path("/sbin"),
        Path("/usr"),
        Path("/System"),
        Path("/Library"),
        Path("/Applications/Xcode.app"),
        Path("/opt/homebrew"),
        Path("/usr/local"),
        Path("/etc"),
        Path("/private/etc"),
        Path("/dev"),
        Path("/tmp"),
        Path("/private/tmp"),
        Path("/var/tmp"),
        Path("/private/var/tmp"),
        Path("/var/folders"),
        Path("/private/var/folders"),
        Path(sys.prefix),
        Path(sys.base_prefix),
        Path(sys.executable).resolve(strict=False).parent,
    ]
    return _unique_existing_or_declared_paths(raw_paths)


def _sandbox_write_paths(workspace: Path) -> list[Path]:
    return _unique_existing_or_declared_paths([workspace])


def _unique_existing_or_declared_paths(raw_paths: Sequence[Path]) -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()
    for raw in raw_paths:
        path = raw.expanduser().resolve(strict=False)
        text = str(path)
        if not text or text in seen:
            continue
        seen.add(text)
        paths.append(path)
    return paths


def _profile_string(path: str | Path) -> str:
    return json.dumps(str(path), ensure_ascii=True)


def _run_command_args_with_sandbox(
    args: Sequence[str | Path],
    *,
    cwd: Path,
    timeout: int,
    allow_risky: bool,
    capability: SandboxCapability,
    network: bool,
) -> tuple[CommandResult, str]:
    argv = [str(arg) for arg in args]
    command = shlex.join(argv)
    decision = assess_command(command, cwd=cwd, policy=SafetyPolicy(project=cwd))
    legacy_risks = command_risk(command)
    if decision.action == DENY or ((decision.action != ALLOW or legacy_risks) and not allow_risky):
        return (
            CommandResult(
                command=command,
                returncode=126,
                stdout="",
                stderr="",
                blocked=True,
                reason=f"{decision.render()}" + ("" if not legacy_risks else "; legacy: " + ", ".join(legacy_risks)),
            ),
            command,
        )
    wrapped, _profile = build_sandboxed_command(argv, cwd, capability=capability, network=network)
    executed_command = shlex.join(wrapped)
    try:
        proc = subprocess.run(
            wrapped,
            cwd=str(cwd),
            shell=False,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return (
            CommandResult(
                command=command,
                returncode=124,
                stdout=stdout,
                stderr=(stderr + f"\ncommand timed out after {timeout}s").strip(),
                blocked=False,
                reason=f"command timed out after {timeout}s",
            ),
            executed_command,
        )
    return (
        CommandResult(
            command=command,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        ),
        executed_command,
    )


def _preview(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 12] + "\n[trimmed]"
