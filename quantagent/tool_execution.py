from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import importlib
import inspect
import time
import uuid
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Callable

from .approvals import ensure_approval_for_policy
from .checkpoints import create_checkpoint
from .desktop_control import click_grid_cell, hotkey, pointer, screenshot, screenshot_grid, type_text
from .desktop_intelligence import build_desktop_tokenization, decide_desktop_action, latest_desktop_tokenization, load_desktop_tokenization, run_desktop_daemon
from .desktop_live import build_desktop_live_state
from .desktop_workflow import (
    ax_snapshot,
    click_som_target,
    desktop_find,
    execute_desktop_plan,
    load_desktop_plan,
    ocr_image,
    open_target,
    plan_find_and_click,
    plan_web_search,
    som_capture,
)
from .file_ops import read_preview, search_text
from .policy_gate import enforce_tool
from .quant_checks import audit_project
from .reporting import build_audit_report, build_status_report
from .result_registry import load_registry, render_registry_markdown
from .safety import SafetyPolicy, assess_command, assess_quant_claim
from .context_pack import build_context_pack
from .lifecycle_hooks import run_lifecycle_hook
from .tool_registry import run_registered_tool
from .tool_output import collapse_tool_result
from .runtime_store import record_tool_invocation
from .validation import validate_project_scripts


@dataclass(frozen=True)
class ToolExecutionResult:
    name: str
    ok: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    blocked: bool = False
    error_kind: str = ""
    approval_id: str = ""
    invocation_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def execute_tool(
    project: Path,
    name: str,
    args: dict[str, Any] | None = None,
    *,
    profile: str = "project",
    owner_approved: bool = False,
    enforce_ask: bool = False,
    approval_id: str | None = None,
    query_id: str | None = None,
) -> ToolExecutionResult:
    """Execute a local Mako tool through one policy/result envelope.

    ASK decisions are fail-closed by default. They require either an approved
    approval_id/allow_always record or an explicit owner_approved override.
    """
    started = time.monotonic()
    args = args or {}
    hook_result = run_lifecycle_hook(project, "before_tool_call", {"tool": name, "args": args, "profile": profile}, query_id=query_id or "")
    if hook_result.blocked:
        blocked_result = _record_invocation(
            project,
            name,
            args,
            _result(name, False, "; ".join(hook_result.summaries or hook_result.errors or ("tool call blocked by hook",)), started, policy={}, blocked=True, error_kind="hook_blocked"),
            query_id=query_id,
        )
        return _after_tool_hook(project, name, args, blocked_result, profile=profile, query_id=query_id)
    name = str(hook_result.payload.get("tool") or name)
    args = hook_result.payload.get("args") if isinstance(hook_result.payload.get("args"), dict) else args
    policy_tool = _policy_tool_name(name)
    try:
        decision = enforce_tool(profile, policy_tool, reason=f"execute {name}", owner_approved=owner_approved, project=project, args=args)
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:90", exc)
        return _result(
            name,
            False,
            f"policy failed: {type(exc).__name__}: {exc}",
            started,
            policy={},
            blocked=True,
            error_kind="policy_error",
        )

    policy = decision.metadata()
    approval = ensure_approval_for_policy(
        project,
        tool=name,
        args=args,
        policy=policy,
        reason=f"execute {name}",
        approval_id=approval_id,
    )
    if approval.approval_id:
        policy = policy | _approval_policy_fields(approval)
        run_lifecycle_hook(project, "permission_request", {"tool": name, "args": args, "approval_id": approval.approval_id, "policy": policy}, query_id=query_id or "")
    approved = owner_approved or approval.allowed
    handler_guarded = _handler_enforces_runtime_approval(name)
    if decision.action == "deny" or (decision.action == "ask" and not approved and not handler_guarded):
        blocked_result = _record_invocation(
            project,
            name,
            args,
            _result(
                name,
                False,
                decision.summary if decision.action == "deny" else (approval.summary if approval.approval_id else decision.summary),
                started,
                policy=policy,
                blocked=True,
                error_kind="policy_blocked",
                approval_id=approval.approval_id,
            ),
            query_id=query_id,
        )
        return _after_tool_hook(project, name, args, blocked_result, profile=profile, query_id=query_id)

    checkpoint_id = _checkpoint_before_tool(project, name, args)
    if checkpoint_id:
        policy = policy | {"checkpoint_id": checkpoint_id}
    try:
        handler = _HANDLERS.get(name)
        if not handler:
            unknown_result = _record_invocation(
                project,
                name,
                args,
                _result(
                    name,
                    False,
                    f"unknown agent tool: {name}",
                    started,
                    policy=policy,
                    error_kind="unknown_tool",
                    approval_id=approval.approval_id,
                ),
                query_id=query_id,
                checkpoint_id=checkpoint_id,
            )
            return _after_tool_hook(project, name, args, unknown_result, profile=profile, query_id=query_id)
        result = handler(project, args, started, policy)
        if approval.approval_id and not result.approval_id:
            result = _replace_result_approval(result, approval.approval_id)
        return _after_tool_hook(project, name, args, _record_invocation(project, name, args, result, query_id=query_id, checkpoint_id=checkpoint_id), profile=profile, query_id=query_id)
    except Exception as exc:  # pragma: no cover - defensive tool boundary
        audit_suppressed_exception(f"{__name__}:160", exc)
        return _after_tool_hook(project, name, args, _record_invocation(
            project,
            name,
            args,
            _result(
                name,
                False,
                f"{type(exc).__name__}: {exc}",
                started,
                policy=policy,
                error_kind="exception",
                approval_id=approval.approval_id,
            ),
            query_id=query_id,
            checkpoint_id=checkpoint_id,
        ), profile=profile, query_id=query_id)


def execute_command_step(
    project: Path,
    command: list[Any],
    *,
    timeout: int = 120,
    allow_risky: bool = False,
    profile: str = "project",
    owner_approved: bool = False,
    enforce_ask: bool = False,
    approval_id: str | None = None,
    query_id: str | None = None,
) -> ToolExecutionResult:
    started = time.monotonic()
    args_payload = {"command": [str(item) for item in command], "timeout": timeout, "allow_risky": allow_risky}
    hook_result = run_lifecycle_hook(project, "before_tool_call", {"tool": "command", "args": args_payload, "profile": profile}, query_id=query_id or "")
    if hook_result.blocked:
        blocked_result = _record_invocation(
            project,
            "command",
            args_payload,
            _result("command", False, "; ".join(hook_result.summaries or hook_result.errors or ("command blocked by hook",)), started, policy={}, blocked=True, error_kind="hook_blocked"),
            query_id=query_id,
        )
        return _after_tool_hook(project, "command", args_payload, blocked_result, profile=profile, query_id=query_id)
    args_payload = hook_result.payload.get("args") if isinstance(hook_result.payload.get("args"), dict) else args_payload
    command = args_payload.get("command") if isinstance(args_payload.get("command"), list) else command
    timeout = int(args_payload.get("timeout") or timeout)
    allow_risky = bool(args_payload.get("allow_risky", allow_risky))
    try:
        decision = enforce_tool(profile, "shell", reason="execute command step", owner_approved=owner_approved, project=project, args=args_payload)
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:209", exc)
        return _result(
            "command",
            False,
            f"policy failed: {type(exc).__name__}: {exc}",
            started,
            policy={},
            blocked=True,
            error_kind="policy_error",
        )
    policy = decision.metadata()
    approval = ensure_approval_for_policy(
        project,
        tool="command",
        args=args_payload,
        policy=policy,
        reason="execute command step",
        approval_id=approval_id,
    )
    if approval.approval_id:
        policy = policy | _approval_policy_fields(approval)
        run_lifecycle_hook(project, "permission_request", {"tool": "command", "args": args_payload, "approval_id": approval.approval_id, "policy": policy}, query_id=query_id or "")
    approved = owner_approved or approval.allowed
    if decision.action == "deny" or (decision.action == "ask" and not approved):
        blocked_result = _record_invocation(
            project,
            "command",
            args_payload,
            _result(
                "command",
                False,
                decision.summary if decision.action == "deny" else (approval.summary if approval.approval_id else decision.summary),
                started,
                policy=policy,
                blocked=True,
                error_kind="policy_blocked",
                approval_id=approval.approval_id,
            ),
            query_id=query_id,
        )
        return _after_tool_hook(project, "command", args_payload, blocked_result, profile=profile, query_id=query_id)
    if not command:
        invalid_result = _record_invocation(
            project,
            "command",
            args_payload,
            _result("command", False, "command step has no argv command", started, policy=policy, error_kind="invalid_args", approval_id=approval.approval_id),
            query_id=query_id,
        )
        return _after_tool_hook(project, "command", args_payload, invalid_result, profile=profile, query_id=query_id)

    from .tools import run_command_args

    checkpoint_id = _checkpoint_before_tool(project, "command", args_payload)
    if checkpoint_id:
        policy = policy | {"checkpoint_id": checkpoint_id}
    result = run_command_args(command, cwd=project, timeout=timeout, allow_risky=allow_risky)
    ok = result.returncode == 0 and not result.blocked
    summary = "command ok" if ok else (result.reason or result.stderr or result.stdout or f"exit {result.returncode}")
    stdout_preview, stdout_artifact = collapse_tool_result(project, result.stdout, tool_name="command_stdout", output_id=uuid.uuid4().hex[:12], threshold=4000)
    stderr_preview, stderr_artifact = collapse_tool_result(project, result.stderr, tool_name="command_stderr", output_id=uuid.uuid4().hex[:12], threshold=4000)
    artifacts = [item.to_dict() for item in (stdout_artifact, stderr_artifact) if item is not None]
    return _after_tool_hook(project, "command", args_payload, _record_invocation(
        project,
        "command",
        args_payload,
        _result(
            "command",
            ok,
            summary[:500],
            started,
            {
                "command": result.command,
                "stdout": stdout_preview[:4000],
                "stderr": stderr_preview[:4000],
                "returncode": result.returncode,
                "artifacts": artifacts,
            },
            policy=policy,
            blocked=result.blocked,
            error_kind="" if ok else "command_failed",
            approval_id=approval.approval_id,
        ),
        query_id=query_id,
        checkpoint_id=checkpoint_id,
    ), profile=profile, query_id=query_id)


def _preview(text: str, limit: int = 2500) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 80].rstrip() + "\n\n[trimmed]"


def _result(
    name: str,
    ok: bool,
    summary: str,
    started: float,
    data: dict[str, Any] | None = None,
    *,
    policy: dict[str, Any],
    blocked: bool = False,
    error_kind: str = "",
    approval_id: str = "",
) -> ToolExecutionResult:
    return ToolExecutionResult(
        name=name,
        ok=ok,
        summary=summary[:500],
        data=data or {},
        policy=policy,
        duration_ms=round((time.monotonic() - started) * 1000),
        blocked=blocked,
        error_kind=error_kind,
        approval_id=approval_id,
    )


def _record_invocation(
    project: Path,
    name: str,
    args: dict[str, Any],
    result: ToolExecutionResult,
    *,
    query_id: str | None = None,
    checkpoint_id: str = "",
) -> ToolExecutionResult:
    invocation_id = result.invocation_id or "inv-" + uuid.uuid4().hex[:12]
    output_preview = _invocation_output_preview(result)
    record_tool_invocation(
        project,
        invocation_id=invocation_id,
        tool=name,
        status="ok" if result.ok else "failed",
        args=args,
        policy=result.policy,
        approval_id=result.approval_id or None,
        query_id=query_id,
        summary=result.summary,
        error_kind=result.error_kind,
        output_preview=output_preview,
        checkpoint_id=checkpoint_id or result.policy.get("checkpoint_id"),
        duration_ms=result.duration_ms,
    )
    return ToolExecutionResult(
        name=result.name,
        ok=result.ok,
        summary=result.summary,
        data=result.data
        | {
            "invocation_id": invocation_id,
            **_approval_data_fields(result),
            **({"checkpoint_id": checkpoint_id} if checkpoint_id else {}),
        },
        policy=result.policy,
        duration_ms=result.duration_ms,
        blocked=result.blocked,
        error_kind=result.error_kind,
        approval_id=result.approval_id,
        invocation_id=invocation_id,
    )


def _approval_policy_fields(approval: Any) -> dict[str, str]:
    fields = {
        "approval_id": approval.approval_id,
        "approval_status": approval.approval.status if approval.approval else "",
    }
    if approval.fingerprint:
        fields["approval_fingerprint"] = approval.fingerprint
    return fields


def _handler_enforces_runtime_approval(name: str) -> bool:
    return name in {
        "desktop.eval",
        "desktop.live",
        "desktop.decide",
        "desktop.open",
        "desktop.web-search",
        "desktop.find-click",
        "desktop.run",
    }


def _approval_data_fields(result: ToolExecutionResult) -> dict[str, str]:
    if not result.approval_id:
        return {}
    fields = {"approval_id": result.approval_id}
    fingerprint = result.policy.get("approval_fingerprint")
    if isinstance(fingerprint, str) and fingerprint:
        fields["approval_fingerprint"] = fingerprint
    return fields


def _replace_result_approval(result: ToolExecutionResult, approval_id: str) -> ToolExecutionResult:
    return ToolExecutionResult(
        name=result.name,
        ok=result.ok,
        summary=result.summary,
        data=result.data,
        policy=result.policy,
        duration_ms=result.duration_ms,
        blocked=result.blocked,
        error_kind=result.error_kind,
        approval_id=approval_id,
        invocation_id=result.invocation_id,
    )


def _after_tool_hook(project: Path, name: str, args: dict[str, Any], result: ToolExecutionResult, *, profile: str = "", query_id: str | None = None) -> ToolExecutionResult:
    run_lifecycle_hook(
        project,
        "after_tool_call",
        {
            "tool": name,
            "args": args,
            "profile": profile,
            "ok": result.ok,
            "summary": result.summary,
            "invocation_id": result.invocation_id,
            "approval_id": result.approval_id,
            "checkpoint_id": result.data.get("checkpoint_id", ""),
            "error_kind": result.error_kind,
        },
        query_id=query_id or "",
    )
    if not result.ok:
        run_lifecycle_hook(
            project,
            "post_tool_use_failure",
            {
                "tool": name,
                "args": args,
                "profile": profile,
                "ok": result.ok,
                "summary": result.summary,
                "invocation_id": result.invocation_id,
                "approval_id": result.approval_id,
                "checkpoint_id": result.data.get("checkpoint_id", ""),
                "error_kind": result.error_kind,
                "blocked": result.blocked,
            },
            query_id=query_id or "",
        )
    return result


def _checkpoint_before_tool(project: Path, name: str, args: dict[str, Any]) -> str:
    paths = _extract_checkpoint_paths(args)
    if not paths:
        return ""
    try:
        record = create_checkpoint(project, paths, reason=f"before tool: {name}")
    except (OSError, ValueError):
        return ""
    return record.checkpoint_id


def _extract_checkpoint_paths(args: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in ("path", "paths", "file", "files", "target", "targets"):
        value = args.get(key)
        if isinstance(value, str) and value:
            paths.append(value)
        elif isinstance(value, list):
            paths.extend(str(item) for item in value if isinstance(item, (str, Path)) and str(item))
    operations = args.get("operations")
    if isinstance(operations, list):
        for operation in operations:
            if not isinstance(operation, dict):
                continue
            if operation.get("op") != "write_text":
                continue
            value = operation.get("path")
            if isinstance(value, (str, Path)) and str(value):
                paths.append(str(value))
    return sorted(set(paths))


def _invocation_output_preview(result: ToolExecutionResult) -> str:
    pieces: list[str] = []
    for key in ("stdout", "stderr", "report", "markdown", "preview", "text_preview"):
        value = result.data.get(key)
        if isinstance(value, str) and value:
            pieces.append(f"{key}:\n{value}")
    if not pieces and result.summary:
        pieces.append(result.summary)
    return _preview("\n\n".join(pieces), 3000)


def _status(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    report = build_status_report(project)
    return _result("status", True, "status read", started, {"report": _preview(report)}, policy=policy)


def _context(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    task = str(args.get("task") or "")
    pack = build_context_pack(project, task=task)
    return _result(
        "context",
        True,
        pack.budget_summary(),
        started,
        {
            "source_summary": pack.source_summary(),
            "estimated_tokens": pack.estimated_tokens,
            "text_preview": _preview(pack.text),
        },
        policy=policy,
    )


def _audit(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    findings = audit_project(project)
    ok = not any(item.level == "error" for item in findings)
    return _result(
        "audit",
        ok,
        "no blocking audit findings" if ok else "blocking audit findings",
        started,
        {"report": _preview(build_audit_report(project))},
        policy=policy,
    )


def _validate(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    results = validate_project_scripts(project)
    ok = all(item.ok for item in results)
    return _result(
        "validate",
        ok,
        "validation passed" if ok else "validation failed",
        started,
        {"results": [asdict(item) for item in results]},
        policy=policy,
    )


def _implement(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    """Execute explicit file operations without planning.

    Phase 2: Safe file operation executor. Requires structured operations input.
    Does NOT generate code from task text. Planner integration is future work.

    Args:
        operations: List of operation dicts, each with:
            - op: "write_text" (only supported operation)
            - path: relative path within project
            - text: file content string
    """
    from .file_ops import write_text

    operations = args.get("operations", [])
    if not isinstance(operations, list) or not operations:
        return _result(
            "implement",
            False,
            "no implementation operations supplied",
            started,
            {
                "task": args.get("task", ""),
                "operations_count": 0,
                "files_touched": [],
                "created_files": [],
                "errors": [],
            },
            policy=policy,
        )

    protected_paths, protected_errors = _normalize_protected_paths(args.get("protected_paths", []))
    planned: list[tuple[str, str, bool]] = []
    errors: list[str] = []
    errors.extend(protected_errors)
    for idx, op_spec in enumerate(operations):
        if not isinstance(op_spec, dict):
            errors.append(f"operation {idx}: operation must be an object")
            continue
        op_type = op_spec.get("op")
        if op_type != "write_text":
            errors.append(f"operation {idx}: unknown operation type '{op_type}'")
            continue

        path = op_spec.get("path")
        if not isinstance(path, str) or not path:
            errors.append(f"operation {idx}: missing path")
            continue
        candidate = Path(path)
        if candidate.is_absolute():
            errors.append(f"operation {idx}: absolute paths are not allowed")
            continue
        if ".." in candidate.parts:
            errors.append(f"operation {idx}: parent path components are not allowed")
            continue
        normalized_path = _normalize_relative_path(candidate)
        if normalized_path in protected_paths:
            errors.append(f"operation {idx}: protected path edits are not allowed: {path}")
            continue
        if _is_existing_test_file(project, candidate):
            errors.append(f"operation {idx}: protected test file edits are not allowed: {path}")
            continue
        if "text" not in op_spec:
            errors.append(f"operation {idx}: missing text")
            continue
        text = op_spec.get("text")
        if not isinstance(text, str):
            errors.append(f"operation {idx}: text must be a string")
            continue
        planned.append((path, text, (project / candidate).exists()))

    if errors:
        return _result(
            "implement",
            False,
            f"failed: {'; '.join(errors)}",
            started,
            {
                "task": args.get("task", ""),
                "operations_count": len(operations),
                "files_touched": [],
                "created_files": [],
                "errors": errors,
            },
            policy=policy,
        )

    files_touched: list[str] = []
    created_files: list[str] = []
    for idx, (path, text, existed_before) in enumerate(planned):
        result = write_text(project, path, text, create_parents=True)
        if not result.ok:
            errors.append(f"operation {idx}: {result.summary}")
        else:
            if result.path:
                files_touched.append(result.path)
                if not existed_before:
                    created_files.append(result.path)

    ok = not errors
    summary = (
        f"executed {len(operations)} operation(s), created {len(created_files)} file(s)"
        if ok
        else f"failed: {'; '.join(errors)}"
    )

    return _result(
        "implement",
        ok,
        summary,
        started,
        {
            "task": args.get("task", ""),
            "operations_count": len(operations),
            "files_touched": files_touched if ok else [],
            "created_files": created_files if ok else [],
            "errors": errors,
        },
        policy=policy,
    )


def _normalize_protected_paths(value: Any) -> tuple[set[str], list[str]]:
    if value in (None, "", ()):
        return set(), []
    if not isinstance(value, list):
        return set(), ["protected_paths must be a list of relative paths"]
    protected: set[str] = set()
    errors: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            errors.append(f"protected_paths {index}: path must be a non-empty string")
            continue
        candidate = Path(item)
        if candidate.is_absolute():
            errors.append(f"protected_paths {index}: absolute paths are not allowed")
            continue
        if ".." in candidate.parts:
            errors.append(f"protected_paths {index}: parent path components are not allowed")
            continue
        protected.add(_normalize_relative_path(candidate))
    return protected, errors


def _normalize_relative_path(path: Path) -> str:
    normalized = path.as_posix()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _is_existing_test_file(project: Path, path: Path) -> bool:
    target = project / path
    if not target.exists() or not target.is_file():
        return False
    filename = path.name.lower()
    stem = path.stem.lower()
    parts = {part.lower() for part in path.parts}
    return filename.startswith("test_") or stem.endswith("_test") or bool(parts & {"test", "tests"})


def _registry(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    entries = load_registry(project)
    return _result(
        "registry",
        True,
        f"{len(entries)} registry entries",
        started,
        {"markdown": _preview(render_registry_markdown(entries, limit=12))},
        policy=policy,
    )


def _safety_command(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    command = str(args.get("command") or "")
    decision = assess_command(command, cwd=project, policy=SafetyPolicy(project=project))
    return _result("safety_command", decision.allowed, decision.render(), started, {"command": command}, policy=policy)


def _safety_claim(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    claim = str(args.get("claim") or "")
    decision = assess_quant_claim(claim)
    return _result("safety_claim", decision.allowed, decision.render(), started, {"claim": claim}, policy=policy)


def _file_read(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    result = read_preview(project, str(args.get("path") or ""), max_chars=6000)
    return _result("file_read", result.ok, result.summary, started, result.data | {"path": result.path}, policy=policy)


def _file_search(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    result = search_text(
        project,
        str(args.get("pattern") or ""),
        path=str(args.get("path") or "."),
        glob=args.get("glob") if isinstance(args.get("glob"), str) else None,
        max_results=30,
    )
    return _result("file_search", result.ok, result.summary, started, result.data, policy=policy)


def _py_compile(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    target = str(args.get("path") or "")
    result = run_registered_tool("py_compile", project, target)
    ok = result.returncode == 0
    return _result(
        "py_compile",
        ok,
        "py_compile ok" if ok else (result.reason or result.stderr or "py_compile failed"),
        started,
        {"command": result.command, "stdout": _preview(result.stdout, 1000), "stderr": _preview(result.stderr, 1000)},
        policy=policy,
        blocked=result.blocked,
        error_kind="" if ok else "command_failed",
    )


def _shell(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    command = str(args.get("command") or "")
    result = run_registered_tool("shell", project, command)
    ok = result.returncode == 0 and not result.blocked
    stdout_preview, stdout_artifact = collapse_tool_result(project, result.stdout, tool_name="shell_stdout", output_id=uuid.uuid4().hex[:12], threshold=4000)
    stderr_preview, stderr_artifact = collapse_tool_result(project, result.stderr, tool_name="shell_stderr", output_id=uuid.uuid4().hex[:12], threshold=4000)
    artifacts = [item.to_dict() for item in (stdout_artifact, stderr_artifact) if item is not None]
    return _result(
        "shell",
        ok,
        "shell ok" if ok else (result.reason or result.stderr or "shell failed"),
        started,
        {"command": result.command, "stdout": stdout_preview[:4000], "stderr": stderr_preview[:4000], "returncode": result.returncode, "artifacts": artifacts},
        policy=policy,
        blocked=result.blocked,
        error_kind="" if ok else "command_failed",
    )


def _desktop_result(name: str, result: Any, started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    data = getattr(result, "data", {}) or {}
    return _result(
        name,
        bool(getattr(result, "ok", False)),
        str(getattr(result, "summary", "")),
        started,
        data if isinstance(data, dict) else {},
        policy=policy,
        blocked=not bool(getattr(result, "ok", False)) and "requires" in str(getattr(result, "summary", "")).lower(),
        error_kind="" if bool(getattr(result, "ok", False)) else "desktop_failed",
    )


def _desktop_live(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    state = build_desktop_live_state(
        project,
        limit=int(args.get("limit") or 8),
        probe=bool(args.get("probe")),
        probe_network_url=str(args.get("probe_network") or args.get("probe_network_url") or ""),
    )
    return _result(
        "desktop.live",
        True,
        f"desktop live status={state.status} artifacts={len(state.artifacts)} approvals={len(state.approvals)} tools={len(state.tools)}",
        started,
        state.to_dict(),
        policy=policy,
    )


def _desktop_open(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    run = open_target(
        project,
        str(args.get("target") or ""),
        kind=str(args.get("kind") or "auto"),
        browser=str(args.get("browser") or ""),
        cwd=str(args.get("cwd") or ""),
        execute=bool(args.get("execute")),
        reviewed=bool(args.get("reviewed")) and bool(policy.get("allowed")),
    )
    return _result(
        "desktop.open",
        run.ok,
        run.summary,
        started,
        run.to_payload(),
        policy=policy,
        blocked=run.status == "blocked",
        error_kind="" if run.ok else "desktop_failed",
    )


def _desktop_shot(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    return _desktop_result("desktop.shot", screenshot(project, name=args.get("name")), started, policy)


def _desktop_grid(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    result = screenshot_grid(
        project,
        cols=int(args.get("cols") or 12),
        rows=int(args.get("rows") or 8),
        name=args.get("name"),
    )
    return _desktop_result("desktop.grid", result, started, policy)


def _desktop_ax(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    result = ax_snapshot(
        project,
        max_depth=int(args.get("depth") or args.get("max_depth") or 4),
        limit=int(args.get("limit") or 500),
        name=args.get("name"),
    )
    return _desktop_result("desktop.ax", result, started, policy)


def _desktop_ocr(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    result = ocr_image(
        project,
        image_path=args.get("image") if isinstance(args.get("image"), str) else None,
        name=args.get("name") if isinstance(args.get("name"), str) else None,
    )
    return _desktop_result("desktop.ocr", result, started, policy)


def _desktop_som(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    result = som_capture(
        project,
        image_path=args.get("image") if isinstance(args.get("image"), str) else None,
        include_ax=bool(args.get("include_ax", True)),
        include_ocr=bool(args.get("include_ocr", True)),
        include_grid=bool(args.get("include_grid", False)),
        cols=int(args.get("cols") or 12),
        rows=int(args.get("rows") or 8),
        name=args.get("name") if isinstance(args.get("name"), str) else None,
    )
    return _desktop_result("desktop.som", result, started, policy)


def _desktop_tokenize(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    tokenization = build_desktop_tokenization(
        project,
        image_path=args.get("image") if isinstance(args.get("image"), str) else None,
        include_ax=bool(args.get("include_ax", True)),
        include_ocr=bool(args.get("include_ocr", True)),
        include_som=bool(args.get("include_som", True)),
        include_grid=bool(args.get("include_grid", False)),
        cols=int(args.get("cols") or 12),
        rows=int(args.get("rows") or 8),
        limit=int(args.get("limit") or 240),
        name=args.get("name") if isinstance(args.get("name"), str) else None,
    )
    return _result(
        "desktop.tokenize",
        tokenization.ok,
        tokenization.summary,
        started,
        tokenization.to_payload(),
        policy=policy,
        error_kind="" if tokenization.ok else "desktop_failed",
    )


def _desktop_decide(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    tokens_path = args.get("tokens") or args.get("tokenization")
    path = Path(str(tokens_path)).expanduser() if isinstance(tokens_path, str) and tokens_path else latest_desktop_tokenization(project)
    if path and not path.is_absolute():
        path = project / path
    if not path or not path.exists():
        return _result("desktop.decide", False, "desktop.decide requires a tokenization file", started, policy=policy, error_kind="desktop_failed")
    decision = decide_desktop_action(
        str(args.get("goal") or ""),
        load_desktop_tokenization(path),
        last_action=str(args.get("last_action") or ""),
        last_result=str(args.get("last_result") or ""),
        browser=str(args.get("browser") or "Safari"),
        engine=str(args.get("engine") or "google"),
    )
    return _result(
        "desktop.decide",
        decision.ok,
        decision.reason,
        started,
        decision.to_payload(),
        policy=policy,
        blocked=decision.status == "blocked",
        error_kind="" if decision.ok else "desktop_failed",
    )


def _desktop_daemon(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    daemon = run_desktop_daemon(
        project,
        str(args.get("goal") or ""),
        execute=bool(args.get("execute")),
        reviewed=bool(args.get("reviewed")) and bool(policy.get("allowed")),
        allow_actions=bool(args.get("allow_actions")) and bool(policy.get("allowed")),
        browser=str(args.get("browser") or "Safari"),
        engine=str(args.get("engine") or "google"),
        max_steps=int(args.get("max_steps") or 20),
        delay=float(args.get("delay") or 1.0),
        stop_file=args.get("stop_file") if isinstance(args.get("stop_file"), str) else None,
        include_grid=bool(args.get("include_grid")),
        token_limit=int(args.get("token_limit") or 240),
    )
    return _result(
        "desktop.daemon",
        daemon.ok,
        daemon.summary,
        started,
        daemon.to_payload(),
        policy=policy,
        blocked=daemon.status == "blocked",
        error_kind="" if daemon.ok else "desktop_failed",
    )


def _desktop_eval(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    try:
        run_desktop_eval, render_desktop_eval_result = _load_desktop_eval_runner()
    except ImportError as exc:
        return _result(
            "desktop.eval",
            False,
            f"Desktop eval runner unavailable: {exc}",
            started,
            policy=policy,
            blocked=True,
            error_kind="missing_dependency",
        )

    payload = _desktop_eval_args(args, policy)
    result = _call_desktop_eval_runner(run_desktop_eval, project, payload)
    rendered = _call_desktop_eval_renderer(render_desktop_eval_result, result, payload)
    return _desktop_eval_result(result, rendered, started, policy, json_output=bool(payload.get("json")))


def _load_desktop_eval_runner() -> tuple[Callable[..., Any], Callable[..., Any]]:
    try:
        module = importlib.import_module("quantagent.desktop_eval")
    except ImportError as exc:
        raise ImportError(str(exc)) from exc
    run_desktop_eval = getattr(module, "run_desktop_eval", None)
    render_desktop_eval_result = getattr(module, "render_desktop_eval_result", None)
    if not callable(run_desktop_eval) or not callable(render_desktop_eval_result):
        raise ImportError("quantagent.desktop_eval must expose run_desktop_eval and render_desktop_eval_result")
    return run_desktop_eval, render_desktop_eval_result


def _desktop_eval_args(args: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "execute": bool(args.get("execute")) and bool(policy.get("allowed")),
        "reviewed": bool(args.get("reviewed")) and bool(policy.get("allowed")),
        "allow_actions": bool(args.get("allow_actions")) and bool(policy.get("allowed")),
        "json": bool(args.get("json")),
    }
    if isinstance(args.get("suite"), str):
        payload["suite"] = args["suite"]
    if isinstance(args.get("scenario"), str):
        payload["scenario"] = args["scenario"]
    if args.get("duration_minutes") is not None:
        payload["duration_minutes"] = float(args["duration_minutes"])
    if args.get("max_steps") is not None:
        payload["max_steps"] = int(args["max_steps"])
    if isinstance(args.get("stop_file"), str):
        payload["stop_file"] = args["stop_file"]
    return payload


def _call_desktop_eval_runner(helper: Callable[..., Any], project: Path, payload: dict[str, Any]) -> Any:
    try:
        signature = inspect.signature(helper)
    except (TypeError, ValueError):
        return helper(project, **payload)

    params = signature.parameters
    accepts_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values())
    if accepts_kwargs:
        return helper(project, **payload)

    accepted = {
        key: value
        for key, value in payload.items()
        if key in params and params[key].kind in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
    }
    return helper(project, **accepted)


def _call_desktop_eval_renderer(helper: Callable[..., Any], result: Any, payload: dict[str, Any]) -> Any:
    try:
        signature = inspect.signature(helper)
    except (TypeError, ValueError):
        return helper(result, json=bool(payload.get("json")))

    params = signature.parameters
    accepts_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values())
    if accepts_kwargs or "json" in params:
        return helper(result, json=bool(payload.get("json")))
    if "json_output" in params:
        return helper(result, json_output=bool(payload.get("json")))
    return helper(result)


def _desktop_eval_result(result: Any, rendered: Any, started: float, policy: dict[str, Any], *, json_output: bool) -> ToolExecutionResult:
    data = _payload_from_result(result)
    if isinstance(rendered, dict):
        data = data | rendered
    elif isinstance(rendered, str) and rendered:
        if json_output:
            json_text = result.to_json() if hasattr(result, "to_json") and callable(result.to_json) else rendered
            data = data | {"json": json_text}
            if rendered != json_text:
                data["markdown"] = rendered
        else:
            data = data | {"markdown": rendered}
    status = str(data.get("status") or getattr(result, "status", "") or "")
    summary = str(data.get("summary") or getattr(result, "summary", "") or f"desktop.eval {status or 'ok'}")
    ok_value = data.get("ok", getattr(result, "ok", None))
    ok = bool(ok_value) if ok_value is not None else status.lower() not in {"blocked", "denied", "failed", "error"}
    blocked = status.lower() in {"blocked", "denied"} or (not ok and "requires" in summary.lower())
    return _result(
        "desktop.eval",
        ok,
        summary,
        started,
        data,
        policy=policy,
        blocked=blocked,
        error_kind="" if ok else ("policy_blocked" if blocked else "desktop_failed"),
    )


_NIGHT_HELPER_MODULES = (
    "quantagent.desktop_night",
    "quantagent.desktop_night_daemon",
    "quantagent.night_daemon",
)

_NIGHT_HELPERS = {
    "run": ("run_night_daemon", "run_desktop_night", "run_desktop_night_daemon", "run_night", "run"),
    "enqueue": ("enqueue_night_daemon", "enqueue_desktop_night", "enqueue_desktop_night_task", "enqueue_night", "enqueue"),
    "status": ("status_night_daemon", "status_desktop_night", "get_night_daemon_status", "get_night_status", "night_status", "status"),
    "stop": ("stop_night_daemon", "stop_desktop_night", "stop_desktop_night_daemon", "stop_night", "stop"),
    "resume": ("resume_night_daemon", "resume_desktop_night", "resume_desktop_night_daemon", "resume_night", "resume"),
}


def _desktop_night(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    return _desktop_night_action("desktop.night", "run", project, args, started, policy)


def _desktop_night_enqueue(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    return _desktop_night_action("desktop.night.enqueue", "enqueue", project, args, started, policy)


def _desktop_night_status(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    return _desktop_night_action("desktop.night.status", "status", project, args, started, policy)


def _desktop_night_stop(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    return _desktop_night_action("desktop.night.stop", "stop", project, args, started, policy)


def _desktop_night_resume(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    return _desktop_night_action("desktop.night.resume", "resume", project, args, started, policy)


def _desktop_night_action(name: str, action: str, project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    try:
        helper = _load_night_helper(action)
    except ImportError as exc:
        return _result(
            name,
            False,
            f"Night Daemon core helper unavailable: {exc}",
            started,
            policy=policy,
            blocked=True,
            error_kind="missing_dependency",
        )

    payload = _night_core_args(args, policy)
    result = _call_night_helper(helper, project, payload)
    return _night_result(name, result, started, policy)


def _load_night_helper(action: str) -> Callable[..., Any]:
    helper_names = _NIGHT_HELPERS[action]
    import_errors: list[str] = []
    for module_name in _NIGHT_HELPER_MODULES:
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            import_errors.append(f"{module_name}: {exc}")
            continue
        for helper_name in helper_names:
            helper = getattr(module, helper_name, None)
            if callable(helper):
                return helper
    raise ImportError("; ".join(import_errors) or f"no helper found for {action}")


def _night_core_args(args: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    payload = dict(args)
    reviewed = payload.pop("reviewed", None)
    allow_actions = payload.pop("allow_actions", None)
    if policy.get("allowed"):
        if reviewed is not None:
            payload["reviewed"] = bool(reviewed)
        if allow_actions is not None:
            payload["allow_actions"] = bool(allow_actions)
    return payload


def _call_night_helper(helper: Callable[..., Any], project: Path, payload: dict[str, Any]) -> Any:
    try:
        signature = inspect.signature(helper)
    except (TypeError, ValueError):
        return helper(project, **payload)

    params = signature.parameters
    accepts_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values())
    if accepts_kwargs:
        return helper(project, **payload)

    accepted = {
        key: value
        for key, value in payload.items()
        if key in params and params[key].kind in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
    }
    return helper(project, **accepted)


def _night_result(name: str, result: Any, started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    data = _payload_from_result(result)
    status = str(data.get("status") or getattr(result, "status", "") or "")
    summary = str(data.get("summary") or getattr(result, "summary", "") or f"{name} {status or 'ok'}")
    ok_value = data.get("ok", getattr(result, "ok", None))
    ok = bool(ok_value) if ok_value is not None else status.lower() not in {"blocked", "denied", "failed", "error"}
    blocked = status.lower() in {"blocked", "denied"} or (not ok and "requires" in summary.lower())
    return _result(
        name,
        ok,
        summary,
        started,
        data,
        policy=policy,
        blocked=blocked,
        error_kind="" if ok else ("policy_blocked" if blocked else "desktop_failed"),
    )


def _payload_from_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "to_payload") and callable(result.to_payload):
        payload = result.to_payload()
        return payload if isinstance(payload, dict) else {"result": payload}
    if hasattr(result, "to_dict") and callable(result.to_dict):
        payload = result.to_dict()
        return payload if isinstance(payload, dict) else {"result": payload}
    if isinstance(result, dict):
        return dict(result)
    if is_dataclass(result) and not isinstance(result, type):
        payload = asdict(result)
        return payload if isinstance(payload, dict) else {"result": payload}
    return {"result": result}


def _desktop_find(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    result = desktop_find(
        project,
        str(args.get("query") or ""),
        source=str(args.get("source") or "all"),
        limit=int(args.get("limit") or 10),
        ax_path=args.get("ax_path") if isinstance(args.get("ax_path"), str) else None,
        grid_path=args.get("grid_path") if isinstance(args.get("grid_path"), str) else None,
        ocr_path=args.get("ocr_path") if isinstance(args.get("ocr_path"), str) else None,
        som_path=args.get("som_path") if isinstance(args.get("som_path"), str) else None,
        refresh_ax=bool(args.get("refresh_ax")),
        refresh_som=bool(args.get("refresh_som")),
    )
    return _desktop_result("desktop.find", result, started, policy)


def _desktop_web_search(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    plan = plan_web_search(
        str(args.get("query") or ""),
        browser=str(args.get("browser") or "Safari"),
        engine=str(args.get("engine") or "google"),
    )
    execute = bool(args.get("execute"))
    reviewed = bool(args.get("reviewed")) and bool(policy.get("allowed"))
    run = execute_desktop_plan(project, plan, execute=execute, reviewed=reviewed, verify_after=bool(args.get("verify_after")))
    return _result(
        "desktop.web-search",
        run.ok,
        run.summary,
        started,
        run.to_payload(),
        policy=policy,
        blocked=run.status == "blocked",
        error_kind="" if run.ok else "desktop_failed",
    )


def _desktop_find_click(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    plan = plan_find_and_click(project, str(args.get("query") or ""), source=str(args.get("source") or "all"))
    execute = bool(args.get("execute"))
    reviewed = bool(args.get("reviewed")) and bool(policy.get("allowed"))
    run = execute_desktop_plan(project, plan, execute=execute, reviewed=reviewed, verify_after=bool(args.get("verify_after")))
    return _result(
        "desktop.find-click",
        run.ok,
        run.summary,
        started,
        run.to_payload(),
        policy=policy,
        blocked=run.status == "blocked",
        error_kind="" if run.ok else "desktop_failed",
    )


def _desktop_run(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    path = Path(str(args.get("plan") or args.get("path") or ""))
    if not path.is_absolute():
        path = project / path
    plan = load_desktop_plan(path)
    run = execute_desktop_plan(
        project,
        plan,
        execute=bool(args.get("execute")),
        reviewed=bool(args.get("reviewed")) and bool(policy.get("allowed")),
        verify_after=bool(args.get("verify_after")),
    )
    return _result(
        "desktop.run",
        run.ok,
        run.summary,
        started,
        run.to_payload(),
        policy=policy,
        blocked=run.status == "blocked",
        error_kind="" if run.ok else "desktop_failed",
    )


def _desktop_click(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    if not policy.get("allowed"):
        return _result("desktop.click", False, "desktop.click requires explicit owner approval", started, policy=policy, blocked=True, error_kind="policy_blocked")
    return _desktop_result("desktop.click", pointer(project, "click", int(args.get("x") or 0), int(args.get("y") or 0)), started, policy)


def _desktop_som_click(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    if not policy.get("allowed"):
        return _result("desktop.som-click", False, "desktop.som-click requires explicit owner approval", started, policy=policy, blocked=True, error_kind="policy_blocked")
    return _desktop_result(
        "desktop.som-click",
        click_som_target(project, str(args.get("mark") or args.get("target") or ""), som_path=args.get("som_path") if isinstance(args.get("som_path"), str) else None),
        started,
        policy,
    )


def _desktop_type(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    if not policy.get("allowed"):
        return _result("desktop.type", False, "desktop.type requires explicit owner approval", started, policy=policy, blocked=True, error_kind="policy_blocked")
    return _desktop_result("desktop.type", type_text(str(args.get("text") or "")), started, policy)


def _desktop_hotkey(project: Path, args: dict[str, Any], started: float, policy: dict[str, Any]) -> ToolExecutionResult:
    if not policy.get("allowed"):
        return _result("desktop.hotkey", False, "desktop.hotkey requires explicit owner approval", started, policy=policy, blocked=True, error_kind="policy_blocked")
    keys = args.get("keys") or []
    if isinstance(keys, str):
        keys = [item for item in keys.replace("+", " ").split() if item]
    return _desktop_result("desktop.hotkey", hotkey([str(key) for key in keys]), started, policy)


def _policy_tool_name(name: str) -> str:
    return {
        "py_compile": "shell",
        "safety_command": "safety",
        "safety_claim": "safety",
    }.get(name, name)


_HANDLERS: dict[str, Callable[[Path, dict[str, Any], float, dict[str, Any]], ToolExecutionResult]] = {
    "status": _status,
    "context": _context,
    "audit": _audit,
    "validate": _validate,
    "implement": _implement,
    "registry": _registry,
    "safety_command": _safety_command,
    "safety_claim": _safety_claim,
    "file_read": _file_read,
    "file_search": _file_search,
    "py_compile": _py_compile,
    "shell": _shell,
    "desktop.live": _desktop_live,
    "desktop.open": _desktop_open,
    "desktop.shot": _desktop_shot,
    "desktop.grid": _desktop_grid,
    "desktop.ax": _desktop_ax,
    "desktop.ocr": _desktop_ocr,
    "desktop.som": _desktop_som,
    "desktop.tokenize": _desktop_tokenize,
    "desktop.decide": _desktop_decide,
    "desktop.daemon": _desktop_daemon,
    "desktop.eval": _desktop_eval,
    "desktop.night": _desktop_night,
    "desktop.night.enqueue": _desktop_night_enqueue,
    "desktop.night.status": _desktop_night_status,
    "desktop.night.stop": _desktop_night_stop,
    "desktop.night.resume": _desktop_night_resume,
    "desktop.find": _desktop_find,
    "desktop.web-search": _desktop_web_search,
    "desktop.find-click": _desktop_find_click,
    "desktop.run": _desktop_run,
    "desktop.som-click": _desktop_som_click,
    "desktop.click": _desktop_click,
    "desktop.type": _desktop_type,
    "desktop.hotkey": _desktop_hotkey,
}
