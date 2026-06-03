from __future__ import annotations

from pathlib import Path

from .agent_autopsy import AgentAutopsyReport, build_agent_autopsy


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


def render_evidence_court_report(report: AgentAutopsyReport) -> str:
    verdict = _verdict(report)
    first_failed = next((item for item in report.evidence if item.ok is False), None)
    no_baseline = next((item for item in report.evidence if "no failing test output was captured" in item.summary.lower()), None)
    post_edit_failure = next((item for item in report.findings if item.finding_type == "post_edit_validation_failure"), None)
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
        "- file_scope: PASS",
        "- reason: this fixture shows a failed validation path, not an out-of-scope edit path.",
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
        f"- post_edit_failure: {post_edit_failure.summary if post_edit_failure else 'not detected'}",
        "",
        f"## Verdict: {verdict}",
        "",
        _verdict_reason(report, verdict),
        "",
    ]
    return "\n".join(lines)


def _verdict(report: AgentAutopsyReport) -> str:
    if report.status == "FAILED":
        return "FAIL"
    if report.status == "UNVERIFIED" or report.failure_class:
        return "SUSPICIOUS"
    return "PASS"


def _verdict_reason(report: AgentAutopsyReport, verdict: str) -> str:
    if verdict == "FAIL":
        return "- reason: post-edit validation failed, so the supplied evidence cannot support a success claim."
    if verdict == "SUSPICIOUS":
        return "- reason: evidence is incomplete or ambiguous, so the success claim needs more proof."
    return "- reason: supplied evidence supports the audited claim."


def _summary(item: object | None) -> str:
    if item is None:
        return "not found"
    summary = str(getattr(item, "summary", ""))
    return summary.replace("\n", " ")[:220]
