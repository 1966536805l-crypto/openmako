from __future__ import annotations

from pathlib import Path

from .agent_autopsy import AgentAutopsyReport, AutopsyEvidence, AutopsyFinding, build_agent_autopsy


BAD_RUN_FIXTURE = Path("tests/fixtures/agent_autopsy/agent_modified_test_failed")


def build_bad_run_demo_report(project: str | Path) -> AgentAutopsyReport:
    root = Path(project).expanduser().resolve(strict=False)
    fixture = root / BAD_RUN_FIXTURE
    if not fixture.exists():
        raise FileNotFoundError(f"bad-run demo fixture not found: {fixture}")
    return build_agent_autopsy(
        fixture,
        trajectory_path=fixture / "trajectory.jsonl",
        query_events_path=fixture / "query_events.jsonl",
        failure_file=fixture / "failure.txt",
        source_agent="codex",
        title="10-second bad run demo",
        command="python3 -m unittest",
    )


def build_missing_tests_demo_report() -> AgentAutopsyReport:
    return AgentAutopsyReport(
        title="missing-tests success claim demo",
        source_agent="codex",
        command="final answer: fixed calculator and verified",
        status="UNVERIFIED",
        failure_class="missing_test_evidence",
        failed_at="final_claim",
        evidence=(
            AutopsyEvidence(
                "E1",
                "trajectory",
                "action",
                "Agent read calculator.py and described a one-line fix.",
                step=1,
                name="read_files",
                ok=True,
            ),
            AutopsyEvidence(
                "E2",
                "trajectory",
                "edit",
                "Agent edited calculator.py.",
                step=2,
                name="apply_patch",
                ok=True,
            ),
            AutopsyEvidence(
                "E3",
                "final_claim",
                "claim",
                "Agent final message claimed the task was fixed and verified.",
                step=3,
                name="final_answer",
                ok=None,
            ),
        ),
        findings=(
            AutopsyFinding(
                "missing_test_evidence",
                "The run has a success claim after an edit, but no command or test-output evidence was supplied.",
                evidence_ids=("E3",),
                intercept="require a targeted validation command before accepting the final claim",
                confidence="high",
            ),
        ),
        intercepts=("require a targeted validation command before accepting the final claim",),
        sources=("built-in missing-tests demo record",),
    )


def build_out_of_scope_demo_report() -> AgentAutopsyReport:
    return AgentAutopsyReport(
        title="out-of-scope edit demo",
        source_agent="codex",
        command="final answer: fixed calculator tests",
        status="FAILED",
        failure_class="scope_violation",
        failed_at="scope_check",
        evidence=(
            AutopsyEvidence(
                "E1",
                "task",
                "claim",
                "Claimed task allowed edits only under calculator.py.",
                step=0,
                name="claimed_scope",
                ok=True,
                data={"allowed_files": ["calculator.py"]},
            ),
            AutopsyEvidence(
                "E2",
                "trajectory",
                "edit",
                "Agent edited calculator.py.",
                step=1,
                name="apply_patch",
                ok=True,
                data={"file": "calculator.py"},
            ),
            AutopsyEvidence(
                "E3",
                "trajectory",
                "edit",
                "Agent also edited tests/test_calculator.py, which was outside the claimed edit scope.",
                step=2,
                name="apply_patch",
                ok=False,
                reason="edited file outside allowed scope",
                data={"file": "tests/test_calculator.py", "allowed_files": ["calculator.py"]},
            ),
        ),
        findings=(
            AutopsyFinding(
                "scope_violation",
                "The run edited tests/test_calculator.py even though the claimed task allowed only calculator.py.",
                evidence_ids=("E3",),
                intercept="reject runs that touch files outside the claimed patch scope",
                confidence="high",
            ),
        ),
        intercepts=("reject runs that touch files outside the claimed patch scope",),
        sources=("built-in out-of-scope demo record",),
    )


def render_evidence_court_report(report: AgentAutopsyReport) -> str:
    verdict = _verdict(report)
    first_failed = next((item for item in report.evidence if item.ok is False), None)
    no_baseline = next((item for item in report.evidence if "no failing test output was captured" in item.summary.lower()), None)
    scope_violation = next((item for item in report.findings if item.finding_type == "scope_violation"), None)
    post_edit_failure = next((item for item in report.findings if item.finding_type == "post_edit_validation_failure"), None)
    missing_test_evidence = next((item for item in report.findings if item.finding_type == "missing_test_evidence"), None)
    test_failure = next((item for item in report.evidence if item.source == "failure" or item.kind == "test"), None)

    lines = [
        "# Evidence Court Report",
        "",
        "## Claim",
        "",
        "- claimed_task: Fix the calculator bug and finish with passing validation.",
        "- final_claim_under_audit: The run should not be accepted as complete unless validation evidence supports it.",
        "",
        "## Evidence",
        "",
        f"- source_agent: {report.source_agent or 'unknown'}",
        f"- command: {report.command or 'unknown'}",
        f"- evidence_items: {len(report.evidence)}",
        f"- failed_at: {report.failed_at or 'unknown'}",
        f"- sources: {len(report.sources)} trace files",
        "",
        "## Scope Violations",
        "",
        f"- file_scope: {'FAIL' if scope_violation else 'PASS'}",
        f"- reason: {scope_violation.summary if scope_violation else 'no out-of-scope edit evidence was supplied in this demo record.'}",
        "",
        "## Test Verification",
        "",
        f"- status: {report.status}",
        f"- failure_class: {report.failure_class or 'unknown'}",
        f"- failed_validation: {_summary(first_failed)}",
        f"- test_output: {_summary(test_failure)}",
        "",
        "## Suspicious Behavior",
        "",
        f"- missing_baseline: {_summary(no_baseline)}",
        f"- missing_test_evidence: {missing_test_evidence.summary if missing_test_evidence else 'not detected'}",
        f"- post_edit_failure: {post_edit_failure.summary if post_edit_failure else 'not detected'}",
        "",
        f"## Verdict: {verdict}",
        "",
        _verdict_reason(report, verdict),
        "",
    ]
    return "\n".join(lines)


def _verdict(report: AgentAutopsyReport) -> str:
    if any(item.finding_type == "scope_violation" for item in report.findings):
        return "FAIL"
    if report.status == "FAILED":
        return "FAIL"
    if report.status == "UNVERIFIED" or report.failure_class:
        return "SUSPICIOUS"
    return "PASS"


def _verdict_reason(report: AgentAutopsyReport, verdict: str) -> str:
    if verdict == "FAIL":
        if any(item.finding_type == "scope_violation" for item in report.findings):
            return "- reason: edited files crossed the claimed patch scope, so the run cannot be accepted."
        return "- reason: post-edit validation failed, so the supplied evidence cannot support a success claim."
    if verdict == "SUSPICIOUS":
        return "- reason: evidence is incomplete or ambiguous, so the success claim needs more proof."
    return "- reason: supplied evidence supports the audited claim."


def _summary(item: object | None) -> str:
    if item is None:
        return "not found"
    summary = str(getattr(item, "summary", ""))
    return summary.replace("\n", " ")[:220]
