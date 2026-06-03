from __future__ import annotations

from .exception_audit import audit_suppressed_exception
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .checkpoints import create_checkpoint, restore_checkpoint
from .diagnostic_registry import diagnostics_for_paths, refresh_diagnostic_registry
from .policy_gate import enforce_tool
from .source_checks import FAIL, WARN, run_source_checks
from .structured_diff_preview import (
    StructuredDiffPreview,
    create_preview_from_isolation_review,
    load_structured_diff_preview,
    save_structured_diff_preview,
)
from .tools import run_command_args
from .worktree_isolation import IsolationReview, apply_isolation_review, load_isolation_review


@dataclass(frozen=True)
class ApplyGateFinding:
    level: str
    code: str
    message: str
    path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ApplyGateVerdict:
    allowed: bool
    status: str
    review_id: str
    preview_id: str
    findings: list[ApplyGateFinding] = field(default_factory=list)
    checkpoint_paths: list[str] = field(default_factory=list)
    preview_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "status": self.status,
            "review_id": self.review_id,
            "preview_id": self.preview_id,
            "findings": [item.to_dict() for item in self.findings],
            "checkpoint_paths": self.checkpoint_paths,
            "preview_path": self.preview_path,
        }


@dataclass(frozen=True)
class ApplyGateResult:
    ok: bool
    summary: str
    verdict: ApplyGateVerdict
    applied: bool = False
    checkpoint_id: str = ""
    test_command: list[str] = field(default_factory=list)
    test_returncode: int | None = None
    test_stdout_preview: str = ""
    test_stderr_preview: str = ""
    rolled_back: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "summary": self.summary,
            "verdict": self.verdict.to_dict(),
            "applied": self.applied,
            "checkpoint_id": self.checkpoint_id,
            "test_command": self.test_command,
            "test_returncode": self.test_returncode,
            "test_stdout_preview": self.test_stdout_preview,
            "test_stderr_preview": self.test_stderr_preview,
            "rolled_back": self.rolled_back,
        }


def evaluate_apply_gate(
    project: str | Path,
    review_id: str,
    *,
    preview_id: str = "",
    test_command: Sequence[str | Path] = (),
    profile: str = "build",
    approved: bool = False,
    allow_no_tests: bool = False,
    allow_diagnostic_errors: bool = False,
    allow_high_risk: bool = False,
    source_checks_enabled: bool = True,
    run_source_check_commands: bool = False,
    expected_review_id: str = "",
    write_preview: bool = True,
) -> ApplyGateVerdict:
    project_path = Path(project).expanduser().resolve(strict=False)
    review = load_isolation_review(project_path, review_id)
    preview, preview_path = _load_or_create_preview(
        project_path,
        review,
        preview_id=preview_id,
        test_command=test_command,
        profile=profile,
        write_preview=write_preview,
    )
    findings: list[ApplyGateFinding] = []
    changed_paths = _changed_paths(review)
    if expected_review_id and review.review_id != expected_review_id:
        findings.append(ApplyGateFinding("error", "not_recommended_review", f"review {review.review_id} is not the expected review {expected_review_id}"))
    if not changed_paths:
        findings.append(ApplyGateFinding("error", "empty_review", "isolation review has no changed/new/deleted paths"))
    if preview.approval_required and not approved:
        findings.append(ApplyGateFinding("error", "approval_required", "structured preview requires explicit approval before apply"))
    high_risk_paths = [item.path for item in preview.files if item.risk == "high"]
    if high_risk_paths and not allow_high_risk and not approved:
        findings.append(ApplyGateFinding("error", "high_risk_paths", "high-risk paths require approval: " + ", ".join(high_risk_paths)))
    diagnostics = _workspace_diagnostics(review, changed_paths)
    error_diagnostics = [item for item in diagnostics if item.level == "error"]
    if error_diagnostics and not allow_diagnostic_errors:
        for diagnostic in error_diagnostics[:8]:
            findings.append(
                ApplyGateFinding(
                    "error",
                    "diagnostic_error",
                    f"{diagnostic.code}: {diagnostic.message}",
                    _diagnostic_location(diagnostic),
                )
            )
    command = _effective_test_command(test_command, preview)
    if not command and not allow_no_tests:
        findings.append(ApplyGateFinding("error", "missing_test_command", "apply gate requires a test command or explicit allow_no_tests"))
    if command:
        decision = enforce_tool(profile, "shell", project=project_path, args={"command": " ".join(command)}, owner_approved=approved)
        if decision.action == "deny" or (decision.action == "ask" and not approved):
            findings.append(ApplyGateFinding("error", "test_permission", decision.summary))
    if source_checks_enabled:
        findings.extend(_source_check_findings(project_path, review, changed_paths, run_commands=run_source_check_commands))
    status = "pass" if not any(item.level == "error" for item in findings) else "blocked"
    return ApplyGateVerdict(
        allowed=status == "pass",
        status=status,
        review_id=review.review_id,
        preview_id=preview.preview_id,
        findings=findings,
        checkpoint_paths=changed_paths,
        preview_path=preview_path,
    )


def apply_review_with_gate(
    project: str | Path,
    review_id: str,
    *,
    preview_id: str = "",
    test_command: Sequence[str | Path] = (),
    profile: str = "build",
    approved: bool = False,
    allow_no_tests: bool = False,
    allow_diagnostic_errors: bool = False,
    allow_high_risk: bool = False,
    source_checks_enabled: bool = True,
    run_source_check_commands: bool = False,
    expected_review_id: str = "",
    rollback_on_failure: bool = True,
) -> ApplyGateResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    verdict = evaluate_apply_gate(
        project_path,
        review_id,
        preview_id=preview_id,
        test_command=test_command,
        profile=profile,
        approved=approved,
        allow_no_tests=allow_no_tests,
        allow_diagnostic_errors=allow_diagnostic_errors,
        allow_high_risk=allow_high_risk,
        source_checks_enabled=source_checks_enabled,
        run_source_check_commands=run_source_check_commands,
        expected_review_id=expected_review_id,
        write_preview=True,
    )
    if not verdict.allowed:
        return ApplyGateResult(False, "apply gate blocked review", verdict)

    checkpoint = create_checkpoint(project_path, verdict.checkpoint_paths, reason=f"before gated apply: {review_id}")
    applied = apply_isolation_review(project_path, review_id, reviewed=True)
    command = _effective_test_command(test_command, _preview_for_verdict(project_path, verdict))
    if not command:
        return ApplyGateResult(True, "review applied without tests by override", verdict, applied=True, checkpoint_id=checkpoint.checkpoint_id)

    test = run_command_args(command, cwd=project_path, timeout=120, allow_risky=False)
    test_ok = test.returncode == 0 and not test.blocked
    rolled_back = False
    if not test_ok and rollback_on_failure:
        restore_checkpoint(project_path, checkpoint.checkpoint_id)
        rolled_back = True
    return ApplyGateResult(
        test_ok,
        "review applied and tests passed" if test_ok else "review applied but tests failed; rolled back" if rolled_back else "review applied but tests failed",
        verdict,
        applied=applied.status == "applied",
        checkpoint_id=checkpoint.checkpoint_id,
        test_command=[str(item) for item in command],
        test_returncode=test.returncode,
        test_stdout_preview=test.stdout[:4000],
        test_stderr_preview=test.stderr[:4000],
        rolled_back=rolled_back,
    )


def render_apply_gate_verdict(verdict: ApplyGateVerdict) -> str:
    lines = [
        "# Apply Gate Verdict",
        "",
        f"- status: {verdict.status}",
        f"- allowed: {str(verdict.allowed).lower()}",
        f"- review_id: {verdict.review_id}",
        f"- preview_id: {verdict.preview_id}",
        f"- preview_path: {verdict.preview_path or '-'}",
        f"- checkpoint_paths: {', '.join(verdict.checkpoint_paths) if verdict.checkpoint_paths else '-'}",
        "",
        "## Findings",
    ]
    if not verdict.findings:
        lines.append("- No blocking findings.")
    else:
        lines.extend(f"- [{item.level}] {item.code}{' ' + item.path if item.path else ''}: {item.message}" for item in verdict.findings)
    return "\n".join(lines) + "\n"


def render_apply_gate_result(result: ApplyGateResult) -> str:
    lines = [
        "# Apply Gate Result",
        "",
        f"- ok: {str(result.ok).lower()}",
        f"- summary: {result.summary}",
        f"- applied: {str(result.applied).lower()}",
        f"- checkpoint_id: {result.checkpoint_id or '-'}",
        f"- rolled_back: {str(result.rolled_back).lower()}",
    ]
    if result.test_command:
        lines.append(f"- test_command: {' '.join(result.test_command)}")
        lines.append(f"- test_returncode: {result.test_returncode}")
    lines.extend(["", render_apply_gate_verdict(result.verdict).rstrip()])
    return "\n".join(lines) + "\n"


def _source_check_findings(project: Path, review: IsolationReview, paths: list[str], *, run_commands: bool) -> list[ApplyGateFinding]:
    workspace = Path(review.workspace_path)
    try:
        results = run_source_checks(
            workspace,
            paths=paths,
            run_commands=run_commands,
            checks_project=project,
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:259", exc)
        return [ApplyGateFinding("error", "source_checks_error", f"source checks failed to run: {type(exc).__name__}: {exc}")]
    findings: list[ApplyGateFinding] = []
    for result in results:
        if result.status not in {FAIL, WARN}:
            continue
        level = "warn" if result.status == WARN or result.severity.lower() in {"warn", "warning", "advisory"} else "error"
        path = ",".join(result.paths[:3])
        findings.append(
            ApplyGateFinding(
                level,
                "source_check_failed" if result.status == FAIL else "source_check_warning",
                f"{result.check_id}: {result.message}",
                path,
            )
        )
    return findings


def _load_or_create_preview(
    project: Path,
    review: IsolationReview,
    *,
    preview_id: str,
    test_command: Sequence[str | Path],
    profile: str,
    write_preview: bool,
) -> tuple[StructuredDiffPreview, str]:
    if preview_id:
        preview = load_structured_diff_preview(project, preview_id)
        return preview, str(Path(project) / ".quantagent" / "diff_previews" / f"{preview.preview_id}.json")
    preview = create_preview_from_isolation_review(project, review, task=f"apply {review.review_id}", test_command=test_command, profile=profile)
    path = str(save_structured_diff_preview(project, preview)) if write_preview else ""
    return preview, path


def _preview_for_verdict(project: Path, verdict: ApplyGateVerdict) -> StructuredDiffPreview:
    return load_structured_diff_preview(project, verdict.preview_id)


def _changed_paths(review: IsolationReview) -> list[str]:
    return sorted(set([*review.changed_paths, *review.new_paths, *review.deleted_paths]))


def _workspace_diagnostics(review: IsolationReview, paths: list[str]) -> list[Any]:
    try:
        snapshot = refresh_diagnostic_registry(Path(review.workspace_path), limit=500)
        return diagnostics_for_paths(snapshot, paths)
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:307", exc)
        return []


def _diagnostic_location(diagnostic: Any) -> str:
    location = str(getattr(diagnostic, "path", "") or "")
    line = getattr(diagnostic, "line", None)
    if line is not None:
        location += f":{line}"
    return location


def _effective_test_command(test_command: Sequence[str | Path], preview: StructuredDiffPreview) -> list[str]:
    explicit = [str(item) for item in test_command]
    if explicit:
        return explicit
    return list(preview.test_command)
