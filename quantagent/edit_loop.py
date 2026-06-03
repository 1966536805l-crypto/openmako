from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import json
import difflib
import re
import shlex
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from . import patch_visa
from .checkpoints import create_checkpoint, restore_checkpoint
from .code_index import dependency_graph, search_code_index
from .file_ops import resolve_project_path
from .failure_interrupt_cache import EvidenceReceipt, build_invalidation_keys, find_diagnosis_asset, record_diagnosis_asset_for_interrupt, recheck_diagnosis_asset
from .guards import command_risk
from .lifecycle_hooks import run_lifecycle_hook
from .model_client import ModelClient, ModelRequest
from .patch_engine import apply_replace, restore_snapshot
from .policy_gate import enforce_tool
from .query_runtime import QueryRuntime
from .repo_map import render_repo_context, search_repo_map
from .safety import ALLOW, assess_command
from .tools import run_command_args
from .worktree_isolation import IsolationReview, IsolatedWorktree, create_isolated_worktree, create_isolation_review


DEFAULT_OUTPUT_PREVIEW_CHARS = 4000


@dataclass(frozen=True)
class EditPlan:
    path: str | Path
    old: str
    candidate_replacements: Sequence[str]
    test_command: Sequence[str | Path]
    expected_count: int = 1
    max_attempts: int = 3
    timeout: int = 120
    diff_max_lines: int = 240
    before_context: str | None = None
    after_context: str | None = None
    output_preview_chars: int = DEFAULT_OUTPUT_PREVIEW_CHARS
    allow_risky_tests: bool = False
    restore_on_failure: bool = True


@dataclass(frozen=True)
class EditAttempt:
    index: int
    replacement_preview: str
    preview_ok: bool
    apply_ok: bool
    test_returncode: int | None = None
    diff: str = ""
    stdout_preview: str = ""
    stderr_preview: str = ""
    blocked: bool = False
    reason: str = ""
    restored: bool = False
    contextual: bool = False
    summary: str = ""


@dataclass(frozen=True)
class EditLoopResult:
    ok: bool
    summary: str
    path: str
    attempts: list[EditAttempt] = field(default_factory=list)
    final_replacement: str | None = None
    command: str = ""

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "summary": self.summary,
            "path": self.path,
            "final_replacement": self.final_replacement,
            "command": self.command,
            "attempts": [
                {
                    "index": attempt.index,
                    "replacement_preview": attempt.replacement_preview,
                    "preview_ok": attempt.preview_ok,
                    "apply_ok": attempt.apply_ok,
                    "test_returncode": attempt.test_returncode,
                    "diff": attempt.diff,
                    "stdout_preview": attempt.stdout_preview,
                    "stderr_preview": attempt.stderr_preview,
                    "blocked": attempt.blocked,
                    "reason": attempt.reason,
                    "restored": attempt.restored,
                    "contextual": attempt.contextual,
                    "summary": attempt.summary,
                }
                for attempt in self.attempts
            ],
        }


@dataclass(frozen=True)
class FileReplacement:
    path: str | Path
    old: str
    new: str
    expected_count: int = 1
    before_context: str | None = None
    after_context: str | None = None
    visa_request: patch_visa.VisaRequest | None = None


@dataclass(frozen=True)
class ChangeSetCandidate:
    edits: Sequence[FileReplacement]
    name: str = ""


@dataclass(frozen=True)
class ChangeSetPlan:
    candidates: Sequence[ChangeSetCandidate]
    test_command: Sequence[str | Path]
    max_attempts: int = 3
    timeout: int = 120
    diff_max_lines: int = 240
    output_preview_chars: int = DEFAULT_OUTPUT_PREVIEW_CHARS
    allow_risky_tests: bool = False
    restore_on_failure: bool = True


@dataclass(frozen=True)
class ChangeSetAttempt:
    index: int
    name: str
    apply_ok: bool
    test_returncode: int | None = None
    diffs: list[dict[str, str]] = field(default_factory=list)
    stdout_preview: str = ""
    stderr_preview: str = ""
    blocked: bool = False
    reason: str = ""
    restored: bool = False
    summary: str = ""


@dataclass(frozen=True)
class ChangeSetResult:
    ok: bool
    summary: str
    attempts: list[ChangeSetAttempt] = field(default_factory=list)
    final_candidate: str = ""
    command: str = ""

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "summary": self.summary,
            "final_candidate": self.final_candidate,
            "command": self.command,
            "attempts": [
                {
                    "index": attempt.index,
                    "name": attempt.name,
                    "apply_ok": attempt.apply_ok,
                    "test_returncode": attempt.test_returncode,
                    "diffs": attempt.diffs,
                    "stdout_preview": attempt.stdout_preview,
                    "stderr_preview": attempt.stderr_preview,
                    "blocked": attempt.blocked,
                    "reason": attempt.reason,
                    "restored": attempt.restored,
                    "summary": attempt.summary,
                }
                for attempt in self.attempts
            ],
        }


@dataclass(frozen=True)
class PatchPlanFile:
    path: str
    reason: str = ""
    risk: str = "low"


@dataclass(frozen=True)
class PatchPlan:
    task: str
    files: list[PatchPlanFile]
    risks: list[str]
    test_command: list[str]
    candidates: list[ChangeSetCandidate] = field(default_factory=list)
    unified_diff: str = ""
    preview_required: bool = True
    max_attempts: int = 3
    allow_risky_tests: bool = False
    created_at: int = 0
    repo_context: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "files": [item.__dict__ for item in self.files],
            "risks": self.risks,
            "test_command": self.test_command,
            "preview_required": self.preview_required,
            "max_attempts": self.max_attempts,
            "allow_risky_tests": self.allow_risky_tests,
            "created_at": self.created_at,
            "repo_context": self.repo_context,
            "unified_diff": self.unified_diff,
            "candidates": [
                {
                    "name": candidate.name,
                    "edits": [
                        {
                            "path": str(edit.path),
                            "old": edit.old,
                            "new": edit.new,
                            "expected_count": edit.expected_count,
                            "before": edit.before_context,
                            "after": edit.after_context,
                        }
                        for edit in candidate.edits
                    ],
                }
                for candidate in self.candidates
            ],
        }


@dataclass(frozen=True)
class RepairAttempt:
    index: int
    classification: str
    summary: str
    returncode: int | None = None
    blocked: bool = False


@dataclass(frozen=True)
class PatchRunResult:
    ok: bool
    summary: str
    plan: PatchPlan
    applied: bool = False
    change_result: ChangeSetResult | None = None
    repair_trajectory: list[RepairAttempt] = field(default_factory=list)
    checkpoint_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "summary": self.summary,
            "applied": self.applied,
            "plan": self.plan.to_dict(),
            "change_result": self.change_result.to_dict() if self.change_result else None,
            "repair_trajectory": [attempt.__dict__ for attempt in self.repair_trajectory],
            "checkpoint_id": self.checkpoint_id,
        }


@dataclass(frozen=True)
class DiffApplyResult:
    ok: bool
    summary: str
    changed_paths: list[str] = field(default_factory=list)
    checkpoint_id: str = ""
    preview: str = ""


@dataclass(frozen=True)
class AutoPatchSpec:
    task: str
    path: str | Path
    old: str
    new: str
    test_command: Sequence[str | Path]
    expected_count: int = 1
    max_rounds: int = 2
    timeout: int = 120
    reviewed: bool = False


@dataclass(frozen=True)
class AutoPatchRound:
    index: int
    stage: str
    ok: bool
    summary: str
    classification: str = ""


@dataclass(frozen=True)
class AutoPatchResult:
    ok: bool
    summary: str
    plan: PatchPlan
    applied: bool = False
    rounds: list[AutoPatchRound] = field(default_factory=list)
    checkpoint_id: str = ""
    preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "summary": self.summary,
            "applied": self.applied,
            "checkpoint_id": self.checkpoint_id,
            "preview": self.preview,
            "plan": self.plan.to_dict(),
            "rounds": [round_item.__dict__ for round_item in self.rounds],
        }


@dataclass(frozen=True)
class RepairCandidate:
    name: str
    summary: str = ""
    unified_diff: str = ""
    edits: list[FileReplacement] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "summary": self.summary,
            "unified_diff": self.unified_diff,
            "edits": [
                {
                    "path": str(edit.path),
                    "old": edit.old,
                    "new": edit.new,
                    "expected_count": edit.expected_count,
                    "before": edit.before_context,
                    "after": edit.after_context,
                }
                for edit in self.edits
            ],
        }


@dataclass(frozen=True)
class RankedRepairCandidate:
    original_index: int
    rank: int
    score: int
    candidate: RepairCandidate
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RepairProposalResult:
    ok: bool
    summary: str
    candidates: list[RepairCandidate] = field(default_factory=list)
    model: str = ""
    error: str = ""
    tainted_output: patch_visa.TaintedModelOutput | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "summary": self.summary,
            "model": self.model,
            "error": self.error,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


@dataclass(frozen=True)
class RepairLoopRound:
    index: int
    proposal_ok: bool
    candidate_index: int = 0
    candidate_rank: int = 0
    candidate_score: int = 0
    candidate: str = ""
    patch_ok: bool = False
    test_ok: bool = False
    classification: str = ""
    summary: str = ""
    checkpoint_id: str = ""
    restored: bool = False
    context_paths: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    feedback: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RepairLoopResult:
    ok: bool
    summary: str
    worktree: IsolatedWorktree
    rounds: list[RepairLoopRound] = field(default_factory=list)
    review: IsolationReview | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "summary": self.summary,
            "worktree": self.worktree.to_dict(),
            "rounds": [round_item.__dict__ for round_item in self.rounds],
            "review": self.review.to_dict() if self.review else None,
        }


def _preview_text(text: str, max_chars: int) -> str:
    max_chars = max(0, max_chars)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n[output trimmed]"


def _replacement_preview(text: str, max_chars: int = 120) -> str:
    compact = text.replace("\n", "\\n")
    return _preview_text(compact, max_chars)


def run_edit_test_retry(project: Path, plan: EditPlan) -> EditLoopResult:
    """Try exact replacements until the supplied test command passes.

    This is intentionally deterministic: callers supply every candidate
    replacement, and this loop only previews, applies, tests, and optionally
    restores between failed attempts.
    """
    project = Path(project)
    try:
        target = resolve_project_path(project, plan.path)
        original_text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return EditLoopResult(False, f"edit loop failed before attempts: {exc}", str(plan.path))
    except ValueError as exc:
        return EditLoopResult(False, f"edit loop failed before attempts: {exc}", str(plan.path))

    attempts: list[EditAttempt] = []
    max_attempts = max(0, plan.max_attempts)
    candidates = list(plan.candidate_replacements)[:max_attempts]
    command_text = ""

    if not candidates:
        return EditLoopResult(False, "edit loop failed: no candidate replacements", str(plan.path))

    for index, replacement in enumerate(candidates, start=1):
        if plan.restore_on_failure and index > 1:
            target.write_text(original_text, encoding="utf-8")

        apply_result = apply_replace(
            project,
            plan.path,
            plan.old,
            replacement,
            before=plan.before_context,
            after=plan.after_context,
            expected_count=plan.expected_count,
            max_lines=plan.diff_max_lines,
        )
        diff = str(apply_result.data.get("diff", "")) if apply_result.data else ""
        if not apply_result.ok:
            attempts.append(
                EditAttempt(
                    index=index,
                    replacement_preview=_replacement_preview(replacement),
                    preview_ok=False,
                    apply_ok=False,
                    diff=diff,
                    contextual=bool(plan.before_context or plan.after_context),
                    summary=apply_result.summary,
                )
            )
            continue

        test_checkpoint = _checkpoint_before_test(project, [str(plan.path)], plan.test_command)
        command_result = run_command_args(
            plan.test_command,
            cwd=project,
            timeout=plan.timeout,
            allow_risky=plan.allow_risky_tests,
        )
        command_text = command_result.command
        passed = command_result.returncode == 0 and not command_result.blocked
        run_lifecycle_hook(
            project,
            "after_test_run",
            {
                "command": command_result.command,
                "returncode": command_result.returncode,
                "blocked": command_result.blocked,
                "passed": passed,
                "checkpoint_id": test_checkpoint,
            },
        )
        should_restore = bool(plan.restore_on_failure and not passed)
        if should_restore:
            snapshot = apply_result.data.get("snapshot") if apply_result.data else None
            if snapshot is not None:
                restore_snapshot(project, snapshot)
            else:
                target.write_text(original_text, encoding="utf-8")

        attempt = EditAttempt(
            index=index,
            replacement_preview=_replacement_preview(replacement),
            preview_ok=True,
            apply_ok=True,
            test_returncode=command_result.returncode,
            diff=diff,
            stdout_preview=_preview_text(command_result.stdout, plan.output_preview_chars),
            stderr_preview=_preview_text(command_result.stderr, plan.output_preview_chars),
            blocked=command_result.blocked,
            reason=command_result.reason,
            restored=should_restore,
            contextual=bool(plan.before_context or plan.after_context),
            summary="test passed" if passed else "test failed",
        )
        attempts.append(attempt)
        if passed:
            return EditLoopResult(
                True,
                f"edit loop passed on attempt {index}",
                str(apply_result.path or plan.path),
                attempts,
                replacement,
                command_text,
            )

    if plan.restore_on_failure:
        target.write_text(original_text, encoding="utf-8")
    return EditLoopResult(
        False,
        f"edit loop failed after {len(attempts)} attempt(s)",
        str(plan.path),
        attempts,
        None,
        command_text,
    )


def run_change_set_retry(project: Path, plan: ChangeSetPlan) -> ChangeSetResult:
    """Apply multi-file candidate change sets until tests pass.

    Each candidate is applied atomically for the purposes of failure handling:
    if any edit fails, already-applied edits from that candidate are restored;
    if tests fail, all edits from that candidate are restored unless disabled.
    """
    project = Path(project)
    candidates = list(plan.candidates)[: max(0, plan.max_attempts)]
    if not candidates:
        return ChangeSetResult(False, "change set failed: no candidates")
    if not plan.test_command:
        return ChangeSetResult(False, "change set failed: no test command")

    attempts: list[ChangeSetAttempt] = []
    command_text = ""
    for index, candidate in enumerate(candidates, start=1):
        applied_snapshots: list[Any] = []
        diffs: list[dict[str, str]] = []
        apply_summary = ""
        apply_ok = True
        for edit in candidate.edits:
            hook = run_lifecycle_hook(project, "before_patch_apply", {"path": str(edit.path), "old": edit.old, "new": edit.new, "candidate": candidate.name})
            if hook.blocked:
                apply_ok = False
                apply_summary = "; ".join(hook.summaries or hook.errors or ("patch blocked by hook",))
                attempts.append(
                    ChangeSetAttempt(
                        index=index,
                        name=candidate.name,
                        apply_ok=False,
                        diffs=diffs,
                        restored=bool(applied_snapshots),
                        summary=apply_summary,
                    )
                )
                break
            result = apply_replace(
                project,
                edit.path,
                edit.old,
                edit.new,
                before=edit.before_context,
                after=edit.after_context,
                expected_count=edit.expected_count,
                max_lines=plan.diff_max_lines,
            )
            if result.ok:
                snapshot = result.data.get("snapshot") if result.data else None
                if snapshot is not None:
                    applied_snapshots.append(snapshot)
                diffs.append({"path": str(result.path or edit.path), "diff": str(result.data.get("diff", ""))})
                continue

            apply_ok = False
            apply_summary = result.summary
            _restore_snapshots(project, applied_snapshots)
            attempts.append(
                ChangeSetAttempt(
                    index=index,
                    name=candidate.name,
                    apply_ok=False,
                    diffs=diffs,
                    restored=bool(applied_snapshots),
                    summary=apply_summary,
                )
            )
            break

        if not apply_ok:
            continue

        test_checkpoint = _checkpoint_before_test(project, [str(edit.path) for edit in candidate.edits], plan.test_command)
        command_result = run_command_args(
            plan.test_command,
            cwd=project,
            timeout=plan.timeout,
            allow_risky=plan.allow_risky_tests,
        )
        command_text = command_result.command
        passed = command_result.returncode == 0 and not command_result.blocked
        run_lifecycle_hook(
            project,
            "after_test_run",
            {
                "command": command_result.command,
                "returncode": command_result.returncode,
                "blocked": command_result.blocked,
                "passed": passed,
                "candidate": candidate.name,
                "checkpoint_id": test_checkpoint,
            },
        )
        should_restore = bool(plan.restore_on_failure and not passed)
        if should_restore:
            _restore_snapshots(project, applied_snapshots)

        attempt = ChangeSetAttempt(
            index=index,
            name=candidate.name,
            apply_ok=True,
            test_returncode=command_result.returncode,
            diffs=diffs,
            stdout_preview=_preview_text(command_result.stdout, plan.output_preview_chars),
            stderr_preview=_preview_text(command_result.stderr, plan.output_preview_chars),
            blocked=command_result.blocked,
            reason=command_result.reason,
            restored=should_restore,
            summary="test passed" if passed else "test failed",
        )
        attempts.append(attempt)
        if passed:
            return ChangeSetResult(
                True,
                f"change set passed on attempt {index}",
                attempts,
                candidate.name or f"candidate-{index}",
                command_text,
            )

    return ChangeSetResult(False, f"change set failed after {len(attempts)} attempt(s)", attempts, "", command_text)


def _restore_snapshots(project: Path, snapshots: Sequence[Any]) -> None:
    for snapshot in reversed(list(snapshots)):
        restore_snapshot(project, snapshot)


def _parse_unified_diff(diff_text: str) -> list[tuple[str, list[tuple[int, list[str]]]]]:
    lines = diff_text.splitlines(keepends=True)
    patches: list[tuple[str, list[tuple[int, list[str]]]]] = []
    current_path = ""
    hunks: list[tuple[int, list[str]]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("+++ "):
            raw = line[4:].strip()
            current_path = raw[2:] if raw.startswith("b/") else raw
            hunks = []
            patches.append((current_path, hunks))
            index += 1
            continue
        if line.startswith("@@ ") and current_path:
            header = line
            minus = header.split("-", 1)[1].split(" ", 1)[0]
            start = int(minus.split(",", 1)[0].lstrip("-+") or "1")
            hunk_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].startswith("@@ ") and not lines[index].startswith("--- ") and not lines[index].startswith("+++ "):
                hunk_lines.append(lines[index])
                index += 1
            hunks.append((start, hunk_lines))
            continue
        index += 1
    if not patches:
        raise ValueError("unified diff contains no file patches")
    return patches


def _apply_hunks(original: list[str], hunks: list[tuple[int, list[str]]]) -> list[str]:
    result: list[str] = []
    cursor = 0
    for old_start, hunk_lines in hunks:
        expected_start = max(0, old_start - 1)
        if expected_start < cursor:
            raise ValueError("unified diff hunks overlap")
        result.extend(original[cursor:expected_start])
        cursor = expected_start
        for raw in hunk_lines:
            if raw.startswith(" "):
                expected = raw[1:]
                if cursor >= len(original) or original[cursor] != expected:
                    raise ValueError("unified diff context mismatch")
                result.append(original[cursor])
                cursor += 1
            elif raw.startswith("-"):
                expected = raw[1:]
                if cursor >= len(original) or original[cursor] != expected:
                    raise ValueError("unified diff removal mismatch")
                cursor += 1
            elif raw.startswith("+"):
                result.append(raw[1:])
            elif raw.startswith("\\"):
                continue
    result.extend(original[cursor:])
    return result


def create_patch_plan(
    project: Path,
    task: str,
    *,
    paths: Sequence[str | Path] = (),
    test_command: Sequence[str | Path] = (),
    max_attempts: int = 3,
    allow_risky_tests: bool = False,
) -> PatchPlan:
    project = Path(project)
    selected = [str(path) for path in paths] or _infer_plan_paths(project, task)
    risks = _plan_risks(selected, task)
    tests = [str(item) for item in test_command] or _default_test_command(project, selected)
    files = [PatchPlanFile(path=item, reason=_path_reason(item, task), risk="medium" if item.endswith(".py") else "low") for item in selected]
    repo_context = _plan_repo_context(project, task, selected)
    return PatchPlan(
        task=task,
        files=files,
        risks=risks,
        test_command=tests,
        max_attempts=max(1, max_attempts),
        allow_risky_tests=allow_risky_tests,
        created_at=int(time.time() * 1000),
        repo_context=repo_context,
    )


def load_patch_plan(path: str | Path) -> PatchPlan:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("patch plan must be a JSON object")
    files = [PatchPlanFile(path=str(item.get("path") or ""), reason=str(item.get("reason") or ""), risk=str(item.get("risk") or "low")) for item in payload.get("files", []) if isinstance(item, dict)]
    candidates: list[ChangeSetCandidate] = []
    for raw_candidate in payload.get("candidates", []):
        if not isinstance(raw_candidate, dict):
            continue
        edits: list[FileReplacement] = []
        for raw_edit in raw_candidate.get("edits", []):
            if not isinstance(raw_edit, dict):
                continue
            edits.append(
                FileReplacement(
                    path=str(raw_edit.get("path") or ""),
                    old=str(raw_edit.get("old") or ""),
                    new=str(raw_edit.get("new") or ""),
                    expected_count=int(raw_edit.get("expected_count", 1)),
                    before_context=raw_edit.get("before"),
                    after_context=raw_edit.get("after"),
                )
            )
        if edits:
            candidates.append(ChangeSetCandidate(edits=edits, name=str(raw_candidate.get("name") or "")))
    return PatchPlan(
        task=str(payload.get("task") or ""),
        files=files,
        risks=[str(item) for item in payload.get("risks", [])],
        test_command=[str(item) for item in payload.get("test_command", [])],
        candidates=candidates,
        preview_required=bool(payload.get("preview_required", True)),
        max_attempts=int(payload.get("max_attempts", 3)),
        allow_risky_tests=bool(payload.get("allow_risky_tests", False)),
        created_at=int(payload.get("created_at", 0)),
        unified_diff=str(payload.get("unified_diff") or ""),
        repo_context=str(payload.get("repo_context") or ""),
    )


def write_patch_plan(path: str | Path, plan: PatchPlan) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def _auto_patch_plan(spec: AutoPatchSpec, *, unified_diff: str, preview_required: bool, repo_context: str = "") -> PatchPlan:
    return PatchPlan(
        task=spec.task,
        files=[PatchPlanFile(path=str(spec.path), reason="auto patch exact replacement", risk="medium")],
        risks=[
            "diff-first auto patch: preview the generated unified diff before apply",
            "checkpoint is created before apply/test and test failure is classified",
        ],
        test_command=[str(item) for item in spec.test_command],
        unified_diff=unified_diff,
        preview_required=preview_required,
        max_attempts=max(1, spec.max_rounds),
        created_at=int(time.time() * 1000),
        repo_context=repo_context,
    )


def run_auto_patch(project: Path, spec: AutoPatchSpec, *, apply: bool = False, profile: str = "") -> AutoPatchResult:
    """Build a unified diff from an exact replacement, then run the patch plan.

    The automatic path is intentionally conservative: it never applies without a
    reviewed flag, and it records each read/diff/apply/test stage as a round.
    """
    project = Path(project)
    query = QueryRuntime(project)
    rounds: list[AutoPatchRound] = []
    try:
        target = resolve_project_path(project, spec.path)
        original = target.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError) as exc:
        plan = _auto_patch_plan(spec, unified_diff="", preview_required=True)
        rounds.append(AutoPatchRound(1, "read", False, str(exc), "path"))
        query.emit("edit_auto", f"auto patch read failed: {exc}", ok=False, data={"path": str(spec.path), "stage": "read"})
        return AutoPatchResult(False, f"auto patch failed before diff: {exc}", plan, rounds=rounds)

    count = original.count(spec.old)
    if count != spec.expected_count:
        plan = _auto_patch_plan(spec, unified_diff="", preview_required=True, repo_context=_plan_repo_context(project, spec.task, [str(spec.path)]))
        summary = f"expected {spec.expected_count} occurrence(s) of old text, found {count}"
        rounds.append(AutoPatchRound(1, "read", False, summary, "path"))
        query.emit("edit_auto", summary, ok=False, data={"path": str(spec.path), "stage": "match", "found": count})
        return AutoPatchResult(False, summary, plan, rounds=rounds)

    updated = original.replace(spec.old, spec.new, spec.expected_count)
    diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"a/{spec.path}",
            tofile=f"b/{spec.path}",
        )
    )
    plan = _auto_patch_plan(spec, unified_diff=diff, preview_required=True, repo_context=_plan_repo_context(project, spec.task, [str(spec.path)]))
    rounds.append(AutoPatchRound(1, "diff", True, "unified diff generated"))
    if not apply:
        query.emit("edit_auto", "auto patch preview generated", ok=True, data={"path": str(spec.path), "apply": False})
        return AutoPatchResult(False, "preview generated; rerun with apply=true after review", plan, rounds=rounds, preview=diff)
    if not spec.reviewed:
        query.emit("edit_auto", "auto patch blocked: review required", ok=False, data={"path": str(spec.path), "apply": True})
        return AutoPatchResult(False, "review required before applying auto patch", plan, rounds=rounds, preview=diff)

    result = _run_patch_plan_from_patch_plan(project, plan, apply=True, timeout=spec.timeout, profile=profile)
    for repair in result.repair_trajectory[: max(0, spec.max_rounds)]:
        rounds.append(
            AutoPatchRound(
                index=len(rounds) + 1,
                stage="test",
                ok=repair.classification == "unknown" and repair.returncode == 0 and not repair.blocked,
                summary=repair.summary,
                classification=repair.classification,
            )
        )
    applied = result.applied
    summary = result.summary
    ok = result.ok
    query.emit(
        "edit_auto",
        summary,
        ok=ok,
        data={"path": str(spec.path), "apply": True, "checkpoint_id": result.checkpoint_id, "rounds": len(rounds)},
    )
    return AutoPatchResult(ok, summary, plan, applied=applied, rounds=rounds, checkpoint_id=result.checkpoint_id, preview=diff)


def propose_repair_candidates(
    project: Path,
    plan: PatchPlan,
    failure_output: str,
    *,
    model: str = "",
    base_url: str | None = None,
    client: Any | None = None,
    evidence_receipt: EvidenceReceipt | None = None,
    visa_receipt: patch_visa.EvidenceReceipt | None = None,
) -> RepairProposalResult:
    """Ask a model for repair candidates, but do not apply them."""
    selected_model = model or "gpt-5.5"
    runtime = QueryRuntime(project)
    prompt = _repair_prompt(project, plan, failure_output, evidence_receipt=evidence_receipt, visa_receipt=visa_receipt)
    selected_client = client or ModelClient(base_url=base_url)
    if client is None and not selected_client.configured:
        return RepairProposalResult(False, "model repair proposal unavailable: API key is not configured", model=selected_model, error="model_not_configured")
    response = selected_client.complete(
        ModelRequest(
            model=selected_model,
            system="You propose minimal code repair candidates as strict JSON. Do not include markdown.",
            prompt=prompt,
            project=str(project),
            query_id=runtime.query_id,
        )
    )
    if not response.ok:
        return RepairProposalResult(False, "model repair proposal failed", model=selected_model, error=response.error)
    tainted_output = patch_visa.TaintedModelOutput(response.text)
    try:
        candidates = _parse_repair_candidates(response.text)
    except ValueError as exc:
        return RepairProposalResult(False, f"model repair proposal was not valid JSON: {exc}", model=selected_model, error="invalid_json")
    runtime.emit("edit_auto", f"model proposed {len(candidates)} repair candidate(s)", ok=bool(candidates), data={"model": selected_model, "candidates": len(candidates)})
    return RepairProposalResult(bool(candidates), f"{len(candidates)} repair candidate(s) proposed", candidates=candidates, model=selected_model, tainted_output=tainted_output)


def run_isolated_repair_loop(
    project: Path,
    plan: PatchPlan,
    failure_output: str,
    *,
    max_rounds: int = 3,
    model: str = "",
    base_url: str | None = None,
    client: Any | None = None,
    timeout: int = 120,
) -> RepairLoopResult:
    """Run model-proposed repairs inside an isolated worktree and produce a review."""
    project = Path(project).expanduser().resolve(strict=False)
    worktree = create_isolated_worktree(project, reason=f"repair loop: {plan.task}")
    workspace = Path(worktree.workspace_path)
    rounds: list[RepairLoopRound] = []
    current_failure = failure_output
    quarantined_paths: set[str] = set()
    for index in range(1, max(1, max_rounds) + 1):
        expanded_plan = _expanded_repair_plan(workspace, plan, current_failure, excluded_paths=quarantined_paths)
        diagnostics = _repair_context_diagnostics(workspace, expanded_plan, current_failure)
        failure_class = _diagnostic_value(diagnostics, "failure_class")
        failure_interrupt, diagnosis_asset = find_diagnosis_asset(
            project,
            workspace,
            current_failure,
            failure_class=failure_class,
            planned_paths=[item.path for item in expanded_plan.files],
        )
        asset_invalidation_keys = build_invalidation_keys(workspace, failure_interrupt)
        evidence_receipt: EvidenceReceipt | None = None
        if index != 1:
            diagnosis_asset = None
        if diagnosis_asset is not None:
            recheck = recheck_diagnosis_asset(
                diagnosis_asset,
                _current_diagnosis_facts(workspace, expanded_plan, diagnostics),
            )
            evidence_receipt = recheck.receipt
        if evidence_receipt is not None and evidence_receipt.allowed_payload:
            expanded_plan = _plan_with_evidence_receipt(expanded_plan, evidence_receipt)
            diagnostics = _diagnostics_with_evidence_receipt(diagnostics, evidence_receipt)
        visa_receipt = _patch_visa_receipt(workspace, expanded_plan, diagnostics, evidence_receipt)
        context_paths = [item.path for item in expanded_plan.files]
        proposal = propose_repair_candidates(
            workspace,
            expanded_plan,
            current_failure,
            model=model,
            base_url=base_url,
            client=client,
            evidence_receipt=evidence_receipt,
            visa_receipt=visa_receipt,
        )
        if not proposal.ok or not proposal.candidates:
            rounds.append(
                RepairLoopRound(
                    index,
                    False,
                    summary=proposal.summary,
                    classification=proposal.error or "proposal_failed",
                    context_paths=context_paths,
                    diagnostics=diagnostics,
                )
            )
            if index < max(1, max_rounds):
                current_failure = "\n".join(
                    item
                    for item in (
                        current_failure,
                        "Previous model repair proposal failed.",
                        f"proposal_summary: {proposal.summary}",
                        f"proposal_error: {proposal.error}",
                        "Return strict JSON with a non-empty candidates list on the next attempt.",
                    )
                    if item
                )
                continue
            return RepairLoopResult(False, proposal.summary, worktree, rounds, review=create_isolation_review(project, worktree.worktree_id))
        ranked_candidates = _rank_repair_candidates(workspace, expanded_plan, proposal.candidates, diagnostics)
        failures: list[str] = []
        for ranked in ranked_candidates:
            candidate_index = ranked.original_index
            candidate = ranked.candidate
            visa_candidate, audit_or_reject = _candidate_to_visa_changeset(workspace, expanded_plan, candidate, visa_receipt)
            if isinstance(visa_candidate, patch_visa.ClosureReject):
                summary = "patch visa rejected candidate: " + visa_candidate.reason
                if isinstance(audit_or_reject, patch_visa.InternalAuditOnly):
                    quarantined_paths.update(record.path for record in audit_or_reject.reject_records if record.path)
                    summary += "; " + patch_visa.redacted_audit_summary(audit_or_reject)
                rounds.append(
                    RepairLoopRound(
                        index=index,
                        proposal_ok=True,
                        candidate_index=candidate_index,
                        candidate_rank=ranked.rank,
                        candidate_score=ranked.score,
                        candidate=candidate.name,
                        patch_ok=False,
                        test_ok=False,
                        classification="patch_visa",
                        summary=summary,
                        context_paths=context_paths,
                        diagnostics=diagnostics,
                        feedback=_patch_feedback_from_audit(audit_or_reject),
                    )
                )
                failures.append(
                    _candidate_failure_line(
                        ranked,
                        classification="patch_visa",
                        summary=summary,
                        feedback=_patch_feedback_from_audit(audit_or_reject),
                    )
                )
                continue
            candidate_plan = _patch_plan_from_visa_candidate(visa_candidate)
            checkpoint = create_checkpoint(
                workspace,
                _visa_checkpoint_paths(visa_candidate),
                plan_id=str(candidate_plan.created_at or ""),
                reason=f"repair loop round {index}.{candidate_index}: {candidate.name}",
            )
            patch = run_patch_plan(workspace, visa_candidate, apply=True, timeout=timeout)
            classification = patch.repair_trajectory[-1].classification if patch.repair_trajectory else ""
            targeted_ok = patch.ok
            full_test = _run_full_repair_tests(workspace, expanded_plan, timeout=timeout) if targeted_ok else None
            test_ok = targeted_ok and bool(full_test and full_test["ok"])
            feedback = _patch_feedback(patch, ranked)
            if full_test:
                feedback.append("full_test=" + _feedback_snippet(full_test["summary"]))
            restored = False
            if not test_ok:
                restore_checkpoint(workspace, checkpoint.checkpoint_id)
                restored = True
            rounds.append(
                RepairLoopRound(
                    index=index,
                    proposal_ok=True,
                    candidate_index=candidate_index,
                    candidate_rank=ranked.rank,
                    candidate_score=ranked.score,
                    candidate=candidate.name,
                    patch_ok=patch.applied,
                    test_ok=test_ok,
                    classification=classification if targeted_ok else classification,
                    summary=_repair_round_summary(patch.summary, targeted_ok=targeted_ok, full_test=full_test),
                    checkpoint_id=checkpoint.checkpoint_id,
                    restored=restored,
                    context_paths=context_paths,
                    diagnostics=diagnostics,
                    feedback=feedback,
                )
            )
            if test_ok:
                record_diagnosis_asset_for_interrupt(
                    project,
                    workspace,
                    failure_interrupt,
                    evidence_facts=_diagnosis_evidence_facts(
                        diagnostics,
                        context_paths=context_paths,
                        patch=patch,
                        full_test=full_test,
                    ),
                    suspect_symbols=_diagnosis_suspect_symbols(expanded_plan, failure_interrupt),
                    successful_fix_pattern=_successful_fix_pattern(candidate),
                    validation_result=_diagnosis_validation_result(patch, full_test),
                    invalidation_keys=asset_invalidation_keys,
                )
                review = create_isolation_review(project, worktree.worktree_id)
                return RepairLoopResult(True, f"repair loop passed on round {index} candidate {candidate_index}", worktree, rounds, review=review)
            failures.append(
                _candidate_failure_line(
                    ranked,
                    classification=classification or "unknown",
                    summary=patch.summary,
                    feedback=feedback,
                )
            )
        current_failure = _next_repair_failure_context(current_failure, index, failures, diagnostics)
    review = create_isolation_review(project, worktree.worktree_id)
    return RepairLoopResult(False, f"repair loop failed after {len(rounds)} round(s)", worktree, rounds, review=review)


def _plan_with_evidence_receipt(plan: PatchPlan, receipt: EvidenceReceipt) -> PatchPlan:
    suspect_paths = _receipt_suspect_paths(receipt)
    if not suspect_paths:
        return plan
    files = sorted(plan.files, key=lambda item: (0 if item.path in suspect_paths else 1, item.path))
    return PatchPlan(
        task=plan.task,
        files=files,
        risks=plan.risks,
        test_command=plan.test_command,
        candidates=plan.candidates,
        unified_diff=plan.unified_diff,
        preview_required=plan.preview_required,
        max_attempts=plan.max_attempts,
        allow_risky_tests=plan.allow_risky_tests,
        created_at=plan.created_at,
        repo_context=plan.repo_context,
    )


def _current_diagnosis_facts(project: Path, plan: PatchPlan, diagnostics: Sequence[str]) -> dict[str, Any]:
    context_paths = [item.path for item in plan.files]
    full_test_command = _full_test_command(project, plan)
    facts = list(diagnostics)
    if context_paths:
        facts.append("context_paths=" + ",".join(context_paths[:8]))
    if plan.test_command:
        facts.append("targeted_test_command=" + shlex.join([str(item) for item in plan.test_command]))
    if full_test_command:
        facts.append("full_test_command=" + shlex.join([str(item) for item in full_test_command]))
    return {
        "project": str(project),
        "failure_class": _diagnostic_value(diagnostics, "failure_class"),
        "facts": facts,
        "context_paths": context_paths,
        "targeted_test_command": list(plan.test_command),
        "full_test_command": full_test_command,
        "full_test_command_available": _command_executable_available(full_test_command),
        "full_test_command_blocked": _command_would_be_blocked(project, full_test_command),
    }


def _patch_visa_receipt(
    project: Path,
    plan: PatchPlan,
    diagnostics: Sequence[str],
    evidence_receipt: EvidenceReceipt | None,
) -> patch_visa.EvidenceReceipt:
    allowed = evidence_receipt.allowed_payload if evidence_receipt is not None else {}
    facts = [str(item) for item in allowed.get("evidence_facts", []) if str(item)]
    if not facts:
        facts = [item for item in diagnostics if item.startswith(("failure_class=", "python_file=", "imports["))]
    if not facts:
        facts = ["current_failure"]
    patterns = [str(allowed.get("successful_fix_pattern") or ""), patch_visa.DEFAULT_REPAIR_PATTERN]
    symbols = [str(item) for item in allowed.get("suspect_symbols", []) if str(item)]
    return patch_visa.build_receipt_from_paths(
        project,
        [item.path for item in plan.files],
        verified_facts=facts,
        allowed_repair_patterns=patterns,
        suspect_symbols=symbols,
    )


def _candidate_to_visa_changeset(
    project: Path,
    plan: PatchPlan,
    candidate: RepairCandidate,
    receipt: patch_visa.EvidenceReceipt,
) -> tuple[patch_visa.ChangeSetCandidate | patch_visa.ClosureReject, patch_visa.InternalAuditOnly]:
    hunks = [_edit_to_hunk_proposal(edit, candidate, receipt) for edit in candidate.edits]
    current_snapshot = patch_visa.build_current_snapshot(project, receipt)
    visa_results = [patch_visa.mint_patch_visa(hunk, receipt, current_snapshot) for hunk in hunks]
    approved, audit = patch_visa.filter_hunks(hunks, visa_results)
    closure = patch_visa.closure_check(
        approved,
        receipt,
        current_snapshot,
        task=f"{plan.task} / visa repair {candidate.name}",
        test_command=plan.test_command,
        max_attempts=1,
        allow_risky_tests=plan.allow_risky_tests,
        audit=audit,
    )
    return closure, audit


def _edit_to_hunk_proposal(
    edit: FileReplacement,
    candidate: RepairCandidate,
    receipt: patch_visa.EvidenceReceipt,
) -> patch_visa.HunkProposal:
    return patch_visa.HunkProposal(
        path=str(edit.path),
        old=edit.old,
        new=edit.new,
        visa_request=edit.visa_request or _default_visa_request(str(edit.path), candidate, receipt),
    )


def _default_visa_request(path: str, candidate: RepairCandidate, receipt: patch_visa.EvidenceReceipt) -> patch_visa.VisaRequest:
    fact_ids = tuple(sorted(receipt.verified_fact_ids, key=str)[:1])
    span_id = next((span_id for span_id, span in receipt.authorized_spans.items() if span.path == path), None)
    symbol_id = next((symbol_id for symbol_id, symbol in receipt.authorized_symbols.items() if symbol.split(":", 1)[0] == path), None)
    summary_pattern = " ".join((candidate.summary or "").split())
    repair_pattern = summary_pattern if summary_pattern in receipt.allowed_repair_patterns else patch_visa.DEFAULT_REPAIR_PATTERN
    return patch_visa.VisaRequest(
        receipt_id=receipt.receipt_id,
        fact_ids=fact_ids,
        suspect_symbol_id=symbol_id,
        authorized_span_id=span_id,
        repair_pattern_id=repair_pattern,
    )


def _patch_plan_from_visa_candidate(candidate: patch_visa.ChangeSetCandidate) -> PatchPlan:
    patch_visa.assert_changeset_candidate(candidate)
    paths = sorted({approved.proposal.path for approved in candidate.approved_hunks})
    edits = [
        FileReplacement(
            path=approved.proposal.path,
            old=approved.proposal.old,
            new=approved.proposal.new,
            expected_count=1,
        )
        for approved in candidate.approved_hunks
    ]
    return PatchPlan(
        task=candidate.task,
        files=[PatchPlanFile(path=path, reason="patch visa approved hunk", risk="medium") for path in paths],
        risks=["patch visa approved hunks only"],
        test_command=list(candidate.test_command),
        candidates=[ChangeSetCandidate(edits=edits, name="visa-approved")],
        preview_required=False,
        max_attempts=candidate.max_attempts,
        allow_risky_tests=candidate.allow_risky_tests,
        created_at=candidate.created_at,
    )


def _visa_checkpoint_paths(candidate: patch_visa.ChangeSetCandidate) -> list[str]:
    patch_visa.assert_changeset_candidate(candidate)
    return sorted({approved.proposal.path for approved in candidate.approved_hunks})


def _patch_feedback_from_audit(audit: Any) -> list[str]:
    if isinstance(audit, patch_visa.InternalAuditOnly):
        return [patch_visa.redacted_audit_summary(audit)]
    return []


def _successful_fix_pattern_from_visa_candidate(candidate: patch_visa.ChangeSetCandidate) -> str:
    patch_visa.assert_changeset_candidate(candidate)
    patterns = sorted({approved.visa.repair_pattern_id for approved in candidate.approved_hunks})
    return ",".join(patterns)[:240]


def _command_executable_available(command: Sequence[str | Path]) -> bool:
    if not command:
        return False
    executable = str(command[0])
    if "/" in executable:
        return Path(executable).exists()
    return shutil.which(executable) is not None


def _command_would_be_blocked(project: Path, command: Sequence[str | Path]) -> bool:
    if not command:
        return True
    command_text = shlex.join([str(item) for item in command])
    try:
        decision = assess_command(command_text, cwd=project)
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:1278", exc)
        return True
    return decision.action != ALLOW or bool(command_risk(command_text))


def _diagnostics_with_evidence_receipt(diagnostics: Sequence[str], receipt: EvidenceReceipt) -> list[str]:
    enriched = list(diagnostics)
    enriched.append(f"evidence_receipt={receipt.status.lower()}")
    allowed = receipt.allowed_payload
    if allowed.get("successful_fix_pattern"):
        enriched.append("successful_fix_pattern=" + str(allowed["successful_fix_pattern"]))
    enriched.extend("evidence_fact=" + str(item) for item in allowed.get("evidence_facts", [])[:8])
    enriched.extend("suspect_symbol=" + str(item) for item in allowed.get("suspect_symbols", [])[:8])
    return enriched[:32]


def _receipt_suspect_paths(receipt: EvidenceReceipt) -> set[str]:
    paths: set[str] = set()
    for symbol in receipt.allowed_payload.get("suspect_symbols", []):
        path = symbol.split(":", 1)[0].strip()
        if path:
            paths.add(path)
    return paths


def _run_full_repair_tests(project: Path, plan: PatchPlan, *, timeout: int) -> dict[str, Any]:
    command = _full_test_command(project, plan)
    result = run_command_args(command, cwd=project, timeout=timeout, allow_risky=plan.allow_risky_tests)
    ok = result.returncode == 0 and not result.blocked
    return {
        "ok": ok,
        "command": result.command,
        "summary": "full test passed" if ok else (result.reason or result.stderr or result.stdout or f"exit {result.returncode}")[:500],
        "returncode": result.returncode,
        "blocked": result.blocked,
        "stdout_preview": _preview_text(result.stdout, DEFAULT_OUTPUT_PREVIEW_CHARS),
        "stderr_preview": _preview_text(result.stderr, DEFAULT_OUTPUT_PREVIEW_CHARS),
    }


def _full_test_command(project: Path, plan: PatchPlan) -> list[str]:
    if (project / "tests").exists():
        return ["python3", "-m", "unittest", "discover", "-s", "tests"]
    return _default_test_command(project, [item.path for item in plan.files])


def _repair_round_summary(summary: str, *, targeted_ok: bool, full_test: dict[str, Any] | None) -> str:
    if not targeted_ok:
        return summary
    if full_test and full_test["ok"]:
        return summary + "; full tests passed"
    if full_test:
        return summary + "; full tests failed: " + str(full_test["summary"])
    return summary + "; full tests unavailable"


def _diagnosis_evidence_facts(
    diagnostics: Sequence[str],
    *,
    context_paths: Sequence[str],
    patch: PatchRunResult,
    full_test: dict[str, Any] | None,
) -> list[str]:
    facts = [item for item in diagnostics if item.startswith(("failure_class=", "python_file=", "imports["))]
    facts.append("context_paths=" + ",".join(context_paths[:8]))
    if patch.change_result and patch.change_result.command:
        facts.append("targeted_test_command=" + patch.change_result.command)
    facts.append("targeted_test=passed")
    if full_test:
        facts.append("full_test_command=" + str(full_test.get("command") or ""))
        facts.append("full_test=passed" if full_test.get("ok") else "full_test=failed")
    return _dedupe_sequence(facts)[:16]


def _diagnosis_suspect_symbols(plan: PatchPlan, failure_interrupt: Any) -> list[str]:
    symbols: list[str] = []
    for span in getattr(failure_interrupt, "source_spans", ()):
        symbols.append(span.path)
        if span.name:
            symbols.append(f"{span.path}:{span.name}")
    for item in plan.files[:8]:
        symbols.append(item.path)
    return _dedupe_sequence(symbols)[:16]


def _successful_fix_pattern(candidate: RepairCandidate) -> str:
    pattern = " ".join((candidate.summary or candidate.name or "verified repair pattern").split())
    return pattern[:240]


def _diagnosis_validation_result(patch: PatchRunResult, full_test: dict[str, Any] | None) -> dict[str, Any]:
    targeted_command = patch.change_result.command if patch.change_result else ""
    return {
        "targeted_test": {
            "ok": patch.ok,
            "command": targeted_command,
        },
        "full_test": {
            "ok": bool(full_test and full_test.get("ok")),
            "command": str(full_test.get("command") or "") if full_test else "",
        },
    }


def _dedupe_sequence(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        compact = " ".join(str(value).split())
        if not compact or compact in seen:
            continue
        seen.add(compact)
        result.append(compact)
    return result


def run_patch_plan(project: Path, candidate: patch_visa.ChangeSetCandidate, *, apply: bool = False, timeout: int = 120, profile: str = "") -> PatchRunResult:
    if not isinstance(candidate, patch_visa.ChangeSetCandidate):
        raise TypeError("run_patch_plan accepts only visa ChangeSetCandidate")
    project = Path(project)
    patch_visa.assert_changeset_candidate(candidate)
    plan = _patch_plan_from_visa_candidate(candidate)
    return _run_patch_plan_from_patch_plan(project, plan, apply=apply, timeout=timeout, profile=profile)


def _run_patch_plan_from_patch_plan(project: Path, plan: PatchPlan, *, apply: bool = False, timeout: int = 120, profile: str = "") -> PatchRunResult:
    project = Path(project)
    if not isinstance(plan, PatchPlan):
        raise TypeError("legacy patch runner requires PatchPlan")
    if apply and profile:
        decision = enforce_tool(
            profile,
            "edit",
            reason=f"run patch plan: {plan.task}",
            project=project,
            args={"paths": [item.path for item in plan.files], "task": plan.task},
        )
        if decision.action == "deny":
            return PatchRunResult(False, decision.summary, plan, applied=False)
        if decision.action == "ask":
            return PatchRunResult(False, decision.summary, plan, applied=False)
    checkpoint_paths = [item.path for item in plan.files]
    checkpoint = create_checkpoint(project, checkpoint_paths, plan_id=str(plan.created_at or ""), reason=f"edit run: {plan.task}") if checkpoint_paths else None
    checkpoint_id = checkpoint.checkpoint_id if checkpoint else ""
    if plan.unified_diff:
        if plan.preview_required and not apply:
            return PatchRunResult(False, "preview required before applying unified diff; rerun with apply=true after review", plan, applied=False, checkpoint_id=checkpoint_id)
        diff_result = apply_unified_diff(project, plan.unified_diff, apply=apply, checkpoint_id=checkpoint_id)
        if not diff_result.ok or not apply or not plan.test_command:
            return PatchRunResult(diff_result.ok, diff_result.summary, plan, applied=diff_result.ok and apply, checkpoint_id=checkpoint_id)
        test = _run_patch_tests(project, plan, checkpoint_id=checkpoint_id, timeout=timeout)
        repair = [
            RepairAttempt(
                index=1,
                classification=classify_test_failure(
                    stdout=test["stdout_preview"],
                    stderr=test["stderr_preview"],
                    returncode=test["returncode"],
                    blocked=bool(test["blocked"]),
                    timed_out=bool(test["timed_out"]),
                ),
                summary=test["summary"],
                returncode=test["returncode"],
                blocked=bool(test["blocked"]),
            )
        ]
        if test["ok"]:
            return PatchRunResult(True, f"{diff_result.summary}; tests passed", plan, applied=True, repair_trajectory=repair, checkpoint_id=checkpoint_id)
        return PatchRunResult(False, f"{diff_result.summary}; tests failed: {test['summary']}", plan, applied=True, repair_trajectory=repair, checkpoint_id=checkpoint_id)
    if not plan.candidates:
        return PatchRunResult(False, "patch plan has no executable candidates; review plan and add edits", plan, applied=False, checkpoint_id=checkpoint_id)
    if plan.preview_required and not apply:
        return PatchRunResult(False, "preview required before applying patch plan; rerun with apply=true after review", plan, applied=False, checkpoint_id=checkpoint_id)
    change_plan = ChangeSetPlan(
        candidates=plan.candidates,
        test_command=plan.test_command,
        max_attempts=plan.max_attempts,
        timeout=timeout,
        restore_on_failure=True,
        allow_risky_tests=plan.allow_risky_tests,
    )
    result = run_change_set_retry(project, change_plan)
    trajectory = build_repair_trajectory(result, max_rounds=plan.max_attempts)
    return PatchRunResult(result.ok, result.summary, plan, applied=True, change_result=result, repair_trajectory=trajectory, checkpoint_id=checkpoint_id)


def apply_unified_diff(project: Path, diff_text: str, *, apply: bool = False, checkpoint_id: str = "") -> DiffApplyResult:
    file_patches = _parse_unified_diff(diff_text)
    changed: list[str] = []
    for path, hunks in file_patches:
        hook = run_lifecycle_hook(project, "before_patch_apply", {"path": path, "unified_diff": diff_text[:4000], "checkpoint_id": checkpoint_id})
        if hook.blocked:
            return DiffApplyResult(False, "; ".join(hook.summaries or hook.errors or ("unified diff blocked by hook",)), changed, checkpoint_id, diff_text)
        target = resolve_project_path(project, path)
        original = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
        new_lines = _apply_hunks(original.splitlines(keepends=True), hunks)
        changed.append(path)
        if apply:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("".join(new_lines), encoding="utf-8")
    return DiffApplyResult(True, f"unified diff {'applied' if apply else 'previewed'} for {len(changed)} file(s)", changed, checkpoint_id, diff_text)


def _run_patch_tests(project: Path, plan: PatchPlan, *, checkpoint_id: str, timeout: int) -> dict[str, Any]:
    test_checkpoint = _checkpoint_before_test(project, [item.path for item in plan.files], plan.test_command)
    command_result = run_command_args(plan.test_command, cwd=project, timeout=timeout, allow_risky=plan.allow_risky_tests)
    ok = command_result.returncode == 0 and not command_result.blocked
    timed_out = "timed out" in command_result.reason.lower()
    run_lifecycle_hook(
        project,
        "after_test_run",
        {
            "command": command_result.command,
            "returncode": command_result.returncode,
            "blocked": command_result.blocked,
            "passed": ok,
            "checkpoint_id": test_checkpoint or checkpoint_id,
            "plan_id": plan.created_at,
        },
    )
    return {
        "ok": ok,
        "summary": "test passed" if ok else (command_result.reason or command_result.stderr or command_result.stdout or f"exit {command_result.returncode}")[:500],
        "returncode": command_result.returncode,
        "blocked": command_result.blocked,
        "timed_out": timed_out,
        "stdout_preview": _preview_text(command_result.stdout, DEFAULT_OUTPUT_PREVIEW_CHARS),
        "stderr_preview": _preview_text(command_result.stderr, DEFAULT_OUTPUT_PREVIEW_CHARS),
    }


def _checkpoint_before_test(project: Path, paths: Sequence[str | Path], command: Sequence[str | Path]) -> str:
    selected = [str(path) for path in paths if str(path)]
    if not selected:
        return ""
    try:
        return create_checkpoint(project, selected, reason=f"before test: {' '.join(str(item) for item in command)}").checkpoint_id
    except (OSError, ValueError):
        return ""


def build_repair_trajectory(result: ChangeSetResult, *, max_rounds: int) -> list[RepairAttempt]:
    trajectory: list[RepairAttempt] = []
    for attempt in result.attempts[: max(0, max_rounds)]:
        classification = classify_test_failure(
            stdout=attempt.stdout_preview,
            stderr=attempt.stderr_preview,
            returncode=attempt.test_returncode,
            blocked=attempt.blocked,
            timed_out="timed out" in attempt.reason.lower(),
        )
        trajectory.append(
            RepairAttempt(
                index=attempt.index,
                classification=classification,
                summary=attempt.summary,
                returncode=attempt.test_returncode,
                blocked=attempt.blocked,
            )
        )
    return trajectory


def classify_test_failure(
    *,
    stdout: str = "",
    stderr: str = "",
    returncode: int | None = None,
    blocked: bool = False,
    timed_out: bool = False,
) -> str:
    combined = f"{stdout}\n{stderr}".lower()
    if blocked:
        return "policy"
    if timed_out or returncode == 124 or "timed out" in combined or "timeout" in combined:
        return "timeout"
    if "syntaxerror" in combined or "indentationerror" in combined:
        return "syntax"
    if "modulenotfounderror" in combined or "importerror" in combined or "cannot import name" in combined:
        return "import"
    if "assertionerror" in combined or "assert " in combined or "failed" in combined and "pytest" in combined:
        return "assertion"
    if "no such file or directory" in combined or "filenotfounderror" in combined or "not found" in combined:
        return "path"
    if "environment variable" in combined or "permission denied" in combined or "bad interpreter" in combined:
        return "env"
    if returncode == 0:
        return "unknown"
    return "unknown"


def _repair_prompt(
    project: Path,
    plan: PatchPlan,
    failure_output: str,
    *,
    evidence_receipt: EvidenceReceipt | None = None,
    visa_receipt: patch_visa.EvidenceReceipt | None = None,
) -> str:
    payload = {
        "task": plan.task,
        "files": [item.__dict__ for item in plan.files],
        "file_previews": _plan_file_previews(project, plan, max_chars=900 if evidence_receipt and evidence_receipt.allowed_payload else 1800),
        "repo_context": plan.repo_context or _plan_repo_context(project, plan.task, [item.path for item in plan.files]),
        "risks": plan.risks,
        "test_command": plan.test_command,
        "failure_output": failure_output[-8000:],
        "evidence_receipt": _evidence_receipt_prompt_payload(evidence_receipt),
        "patch_visa_receipt": _patch_visa_receipt_prompt_payload(visa_receipt),
        "required_json_schema": {
            "candidates": [
                {
                    "name": "short name",
                    "summary": "why this minimal repair should fix the failure",
                    "edits": [
                        {
                            "path": "relative/path.py",
                            "old": "exact old text",
                            "new": "exact replacement text",
                            "expected_count": 1,
                            "visa_request": {
                                "receipt_id": "from patch_visa_receipt.receipt_id",
                                "fact_ids": ["one or more verified fact ids"],
                                "authorized_span_id": "authorized span id",
                                "suspect_symbol_id": "optional authorized symbol id",
                                "repair_pattern_id": "allowed repair pattern id",
                            },
                        }
                    ],
                }
            ]
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _evidence_receipt_prompt_payload(receipt: EvidenceReceipt | None) -> dict[str, Any]:
    if receipt is None:
        return {}
    return dict(receipt.allowed_payload)


def _patch_visa_receipt_prompt_payload(receipt: patch_visa.EvidenceReceipt | None) -> dict[str, Any]:
    if receipt is None:
        return {}
    return {
        "receipt_id": str(receipt.receipt_id),
        "verified_fact_ids": [str(item) for item in sorted(receipt.verified_fact_ids, key=str)],
        "suspect_scopes": sorted(receipt.suspect_scopes),
        "authorized_symbols": {str(key): value for key, value in receipt.authorized_symbols.items()},
        "authorized_spans": {
            str(key): {
                "path": span.path,
                "start": span.start,
                "end": span.end,
            }
            for key, span in receipt.authorized_spans.items()
        },
        "allowed_repair_patterns": sorted(receipt.allowed_repair_patterns),
    }


def _rank_repair_candidates(
    project: Path,
    plan: PatchPlan,
    candidates: Sequence[RepairCandidate],
    diagnostics: Sequence[str],
) -> list[RankedRepairCandidate]:
    scored: list[tuple[int, int, RepairCandidate, list[str]]] = []
    planned_paths = {str(item.path) for item in plan.files}
    failure_class = _diagnostic_value(diagnostics, "failure_class")
    for index, candidate in enumerate(candidates, start=1):
        score = 50
        reasons: list[str] = []
        paths = _candidate_paths(candidate)
        overlap = planned_paths & paths
        if overlap:
            score += 18
            reasons.append("touches_plan=" + ",".join(sorted(overlap)[:4]))
        elif planned_paths:
            score -= 8
            reasons.append("outside_initial_plan")
        extra_paths = paths - planned_paths
        if extra_paths:
            score -= min(12, len(extra_paths) * 2)
            reasons.append("extra_paths=" + ",".join(sorted(extra_paths)[:4]))
        exact_matches, stale_edits = _candidate_exact_match_counts(project, candidate)
        if candidate.edits:
            score += exact_matches * 12
            score -= stale_edits * 18
            reasons.append(f"exact_old_matches={exact_matches}/{len(candidate.edits)}")
            if stale_edits:
                reasons.append(f"stale_old_text={stale_edits}")
        if candidate.unified_diff and not candidate.edits:
            score += 4
            reasons.append("unified_diff_candidate")
        if failure_class and _candidate_mentions(candidate, failure_class):
            score += 5
            reasons.append(f"mentions_failure_class={failure_class}")
        if failure_class == "syntax" and any(path.endswith(".py") for path in paths):
            score += 4
            reasons.append("syntax_python_path")
        if not paths:
            score -= 12
            reasons.append("no_paths")
        scored.append((score, index, candidate, reasons))
    ordered = sorted(scored, key=lambda item: (-item[0], item[1]))
    return [
        RankedRepairCandidate(
            original_index=original_index,
            rank=rank,
            score=score,
            candidate=candidate,
            reasons=reasons,
        )
        for rank, (score, original_index, candidate, reasons) in enumerate(ordered, start=1)
    ]


def _candidate_to_patch_plan(plan: PatchPlan, candidate: RepairCandidate) -> PatchPlan:
    return PatchPlan(
        task=f"{plan.task} / repair {candidate.name}",
        files=plan.files,
        risks=[*plan.risks, candidate.summary or "model repair candidate"],
        test_command=plan.test_command,
        candidates=[ChangeSetCandidate(candidate.edits, name=candidate.name)] if candidate.edits else [],
        unified_diff=candidate.unified_diff,
        preview_required=False,
        max_attempts=1,
        allow_risky_tests=plan.allow_risky_tests,
        created_at=int(time.time() * 1000),
        repo_context=plan.repo_context,
    )


def _expanded_repair_plan(project: Path, plan: PatchPlan, failure_output: str, *, excluded_paths: set[str] | None = None) -> PatchPlan:
    excluded = set(excluded_paths or set())
    seen = {item.path for item in plan.files}
    files = list(plan.files)
    query = f"{plan.task}\n{failure_output[-1200:]}"
    try:
        hits = search_code_index(project, query, limit=6, rebuild=False)
    except Exception:
        hits = []
    for hit in hits:
        if hit.path in seen or hit.path in excluded:
            continue
        seen.add(hit.path)
        files.append(PatchPlanFile(path=hit.path, reason=f"repair context hit score={hit.score}", risk="low"))
    try:
        repo_hits = search_repo_map(project, query, limit=6, rebuild=False)
    except Exception:
        repo_hits = []
    for hit in repo_hits:
        if hit.path in seen or hit.path in excluded:
            continue
        seen.add(hit.path)
        files.append(PatchPlanFile(path=hit.path, reason=f"repo-map context hit score={hit.score}", risk="low"))
    return PatchPlan(
        task=plan.task,
        files=files,
        risks=plan.risks,
        test_command=plan.test_command,
        candidates=plan.candidates,
        unified_diff=plan.unified_diff,
        preview_required=plan.preview_required,
        max_attempts=plan.max_attempts,
        allow_risky_tests=plan.allow_risky_tests,
        created_at=plan.created_at,
        repo_context=plan.repo_context or _plan_repo_context(project, plan.task, [item.path for item in files]),
    )


def _next_repair_failure_context(previous: str, round_index: int, failures: Sequence[str], diagnostics: Sequence[str]) -> str:
    queries = _repair_retrieval_queries(previous, failures, diagnostics)
    lines = [
        previous[-4000:],
        "",
        f"Previous repair round {round_index} tried {len(failures)} candidate(s) without passing.",
    ]
    if failures:
        lines.extend(f"- {item}" for item in failures[-8:])
    if diagnostics:
        lines.extend(["", "Current workspace diagnostics:"])
        lines.extend(f"- {item}" for item in diagnostics[:12])
    if queries:
        lines.extend(["", "Next repair retrieval queries:"])
        lines.extend(f"- {item}" for item in queries)
    return "\n".join(line for line in lines if line is not None)


def _candidate_paths(candidate: RepairCandidate) -> set[str]:
    paths = {str(edit.path) for edit in candidate.edits if str(edit.path)}
    if candidate.unified_diff:
        try:
            paths.update(path for path, _hunks in _parse_unified_diff(candidate.unified_diff) if path)
        except ValueError:
            pass
    return paths


def _candidate_exact_match_counts(project: Path, candidate: RepairCandidate) -> tuple[int, int]:
    exact_matches = 0
    stale_edits = 0
    for edit in candidate.edits:
        try:
            path = resolve_project_path(project, edit.path)
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            stale_edits += 1
            continue
        count = text.count(edit.old)
        if count > 0:
            exact_matches += 1
            if edit.expected_count > 0 and count != edit.expected_count:
                stale_edits += 1
        else:
            stale_edits += 1
    return exact_matches, stale_edits


def _candidate_mentions(candidate: RepairCandidate, term: str) -> bool:
    needle = term.strip().lower()
    if not needle:
        return False
    haystack = f"{candidate.name}\n{candidate.summary}\n{candidate.unified_diff}".lower()
    return needle in haystack


def _diagnostic_value(diagnostics: Sequence[str], key: str) -> str:
    prefix = key + "="
    for item in diagnostics:
        if item.startswith(prefix):
            return item.removeprefix(prefix).strip()
    return ""


def _patch_feedback(patch: PatchRunResult, ranked: RankedRepairCandidate) -> list[str]:
    feedback = [
        f"candidate_rank={ranked.rank}",
        f"candidate_score={ranked.score}",
    ]
    if ranked.reasons:
        feedback.append("candidate_reasons=" + ",".join(ranked.reasons[:5]))
    if patch.repair_trajectory:
        attempt = patch.repair_trajectory[-1]
        feedback.append(f"test_returncode={attempt.returncode}")
        if attempt.blocked:
            feedback.append("blocked=true")
    if patch.change_result and patch.change_result.attempts:
        attempt = patch.change_result.attempts[-1]
        if attempt.reason:
            feedback.append("reason=" + _feedback_snippet(attempt.reason))
        if attempt.stdout_preview.strip():
            feedback.append("stdout=" + _feedback_snippet(attempt.stdout_preview))
        if attempt.stderr_preview.strip():
            feedback.append("stderr=" + _feedback_snippet(attempt.stderr_preview))
    feedback.append("summary=" + _feedback_snippet(patch.summary))
    return feedback[:8]


def _candidate_failure_line(
    ranked: RankedRepairCandidate,
    *,
    classification: str,
    summary: str,
    feedback: Sequence[str],
) -> str:
    candidate_name = ranked.candidate.name or str(ranked.original_index)
    parts = [
        f"candidate={candidate_name}",
        f"original_index={ranked.original_index}",
        f"rank={ranked.rank}",
        f"score={ranked.score}",
        f"classification={classification}",
        "summary=" + _feedback_snippet(summary),
    ]
    if ranked.reasons:
        parts.append("reasons=" + ",".join(ranked.reasons[:5]))
    if feedback:
        parts.append("feedback=" + " ; ".join(_feedback_snippet(item, max_chars=180) for item in feedback[:5]))
    return " ".join(parts)


def _repair_retrieval_queries(previous: str, failures: Sequence[str], diagnostics: Sequence[str]) -> list[str]:
    queries: list[str] = []
    failure_class = _diagnostic_value(diagnostics, "failure_class")
    if not failure_class:
        for item in failures:
            marker = "classification="
            if marker in item:
                failure_class = item.split(marker, 1)[1].split(" ", 1)[0].strip()
                break
    if failure_class and failure_class != "unknown":
        queries.append(f"{failure_class} failure repair in touched files")
    for item in diagnostics:
        if item.startswith("path_missing="):
            queries.append(f"find replacement path for {item.removeprefix('path_missing=')}")
        elif item.startswith("python_file="):
            queries.append(f"inspect python diagnostics for {item.removeprefix('python_file=')}")
        elif item.startswith("imports["):
            path = item.split("]", 1)[0].removeprefix("imports[")
            queries.append(f"inspect imports and dependents of {path}")
    for term in _failure_terms(previous):
        queries.append(f"search failure term {term}")
    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        compact = " ".join(query.split())
        if compact and compact not in seen:
            seen.add(compact)
            deduped.append(compact)
        if len(deduped) >= 6:
            break
    return deduped


def _failure_terms(text: str) -> list[str]:
    terms: list[str] = []
    for match in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Warning)\b|[A-Za-z0-9_./-]+\.py\b", text[-4000:]):
        if match not in terms:
            terms.append(match)
        if len(terms) >= 4:
            break
    return terms


def _feedback_snippet(text: str, *, max_chars: int = 240) -> str:
    compact = " ".join(str(text).split())
    return compact[: max(0, max_chars)]


def _repair_context_diagnostics(project: Path, plan: PatchPlan, failure_output: str) -> list[str]:
    diagnostics: list[str] = []
    classification = classify_test_failure(stdout=failure_output, stderr="", returncode=1)
    if classification != "unknown":
        diagnostics.append(f"failure_class={classification}")
    for item in plan.files[:8]:
        try:
            path = resolve_project_path(project, item.path)
        except Exception:
            diagnostics.append(f"path_unresolved={item.path}")
            continue
        if not path.exists():
            diagnostics.append(f"path_missing={item.path}")
        elif path.suffix == ".py":
            diagnostics.append(f"python_file={item.path}")
    try:
        graph = dependency_graph(project, rebuild=False)
    except Exception:
        graph = {}
    for item in plan.files[:5]:
        imports = graph.get(item.path, [])
        if imports:
            diagnostics.append(f"imports[{item.path}]={','.join(imports[:8])}")
    return diagnostics[:16]


def _repair_checkpoint_paths(plan: PatchPlan, candidate: RepairCandidate) -> list[str]:
    paths = [item.path for item in plan.files]
    paths.extend(str(edit.path) for edit in candidate.edits)
    if candidate.unified_diff:
        try:
            paths.extend(path for path, _hunks in _parse_unified_diff(candidate.unified_diff))
        except ValueError:
            pass
    return sorted({path for path in paths if path})


def _plan_file_previews(project: Path, plan: PatchPlan, *, max_chars: int = 1800) -> dict[str, str]:
    previews: dict[str, str] = {}
    for item in plan.files[:8]:
        try:
            path = resolve_project_path(project, item.path)
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:1953", exc)
            continue
        previews[item.path] = text[:max_chars]
    return previews


def _plan_repo_context(project: Path, task: str, paths: Sequence[str | Path], *, max_chars: int = 6000) -> str:
    query = "\n".join([task, *[str(path) for path in paths if str(path)]])
    if not query.strip():
        return ""
    try:
        return render_repo_context(project, query, budget_chars=max_chars, rebuild=False)
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:1965", exc)
        return ""


def _parse_repair_candidates(text: str) -> list[RepairCandidate]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if "\n" in stripped:
            stripped = stripped.split("\n", 1)[1]
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError(exc.msg) from exc
    raw_candidates = payload.get("candidates") if isinstance(payload, dict) else None
    if not isinstance(raw_candidates, list):
        raise ValueError("missing candidates list")
    candidates: list[RepairCandidate] = []
    for index, raw_candidate in enumerate(raw_candidates, start=1):
        if not isinstance(raw_candidate, dict):
            continue
        edits: list[FileReplacement] = []
        for raw_edit in raw_candidate.get("edits", []):
            if not isinstance(raw_edit, dict):
                continue
            path = str(raw_edit.get("path") or "")
            old = str(raw_edit.get("old") or "")
            new = str(raw_edit.get("new") or "")
            if not path or not old:
                continue
            edits.append(
                FileReplacement(
                    path=path,
                    old=old,
                    new=new,
                    expected_count=int(raw_edit.get("expected_count") or 1),
                    before_context=raw_edit.get("before"),
                    after_context=raw_edit.get("after"),
                    visa_request=_parse_visa_request(raw_edit.get("visa_request")),
                )
            )
        unified_diff = str(raw_candidate.get("unified_diff") or "")
        if not unified_diff and not edits:
            continue
        candidates.append(
            RepairCandidate(
                name=str(raw_candidate.get("name") or f"candidate-{index}"),
                summary=str(raw_candidate.get("summary") or ""),
                unified_diff=unified_diff,
                edits=edits,
            )
        )
    return candidates


def _parse_visa_request(raw: Any) -> patch_visa.VisaRequest | None:
    if not isinstance(raw, dict):
        return None
    return patch_visa.VisaRequest(
        receipt_id=patch_visa.ReceiptId(str(raw.get("receipt_id") or "")),
        fact_ids=tuple(patch_visa.FactId(str(item)) for item in raw.get("fact_ids", ()) if str(item)),
        suspect_symbol_id=patch_visa.SymbolId(str(raw.get("suspect_symbol_id"))) if raw.get("suspect_symbol_id") else None,
        authorized_span_id=patch_visa.SpanId(str(raw.get("authorized_span_id"))) if raw.get("authorized_span_id") else None,
        repair_pattern_id=str(raw.get("repair_pattern_id") or patch_visa.DEFAULT_REPAIR_PATTERN),
    )


def _infer_plan_paths(project: Path, task: str) -> list[str]:
    candidates: list[str] = []
    lowered = task.lower()
    for path in sorted(project.rglob("*.py")):
        rel = path.relative_to(project)
        if any(part.startswith(".") or part in {"__pycache__", "venv", ".venv"} for part in rel.parts):
            continue
        text = str(rel)
        if "test" in lowered and "test" in text:
            candidates.append(text)
        elif len(candidates) < 8:
            candidates.append(text)
        if len(candidates) >= 12:
            break
    return candidates


def _default_test_command(project: Path, paths: Sequence[str]) -> list[str]:
    if (project / "tests").exists():
        return ["python3", "-m", "unittest", "discover", "-s", "tests"]
    py_paths = [item for item in paths if item.endswith(".py")]
    if py_paths:
        return ["python3", "-m", "py_compile", *py_paths[:20]]
    return ["python3", "-c", "print('no default tests discovered')"]


def _plan_risks(paths: Sequence[str], task: str) -> list[str]:
    risks: list[str] = []
    risks.append("TDD guard: inspect or add a failing test before implementation, then rerun narrow and full tests")
    if not paths:
        risks.append("no target files inferred")
    if len(paths) > 6:
        risks.append("broad file surface; split into smaller plans before applying")
    if any(item.endswith(".py") for item in paths):
        risks.append("python behavior may change; run unit tests and py_compile")
    if any(word in task.lower() for word in ("permission", "approval", "mcp", "subagent", "runtime")):
        risks.append("runtime state changes require persisted JSON/SQLite compatibility checks")
    return risks or ["low blast radius if exact replacement previews are reviewed"]


def _path_reason(path: str, task: str) -> str:
    name = Path(path).name.lower()
    for token in ("approval", "mcp", "subagent", "edit", "runtime", "cli", "doctor"):
        if token in name or token in task.lower():
            return f"matches task keyword: {token}"
    return "candidate from project scan"
