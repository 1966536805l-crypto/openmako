from __future__ import annotations

import json
import re
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


def build_audit_record_report(record_path: str | Path) -> AgentAutopsyReport:
    path = Path(record_path).expanduser().resolve(strict=False)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("audit record must be a JSON object")

    claimed_task = str(payload.get("claimed_task") or "").strip()
    final_claim = str(payload.get("final_claim") or "").strip()
    allowed_files = _string_list(payload.get("allowed_files"))
    files_read = _string_list(payload.get("files_read"))
    files_edited = _string_list(payload.get("files_edited"))
    commands_run = _command_summaries(payload.get("commands_run"))
    test_status, test_summary = _test_output_status(payload.get("test_output"), payload.get("commands_run"))

    evidence: list[AutopsyEvidence] = [
        AutopsyEvidence(
            "E1",
            "task",
            "claim",
            claimed_task or "No claimed_task was supplied.",
            step=0,
            name="claimed_task",
            ok=bool(claimed_task),
            data={"claimed_task": claimed_task, "allowed_files": allowed_files},
        )
    ]
    if final_claim:
        evidence.append(
            AutopsyEvidence(
                f"E{len(evidence) + 1}",
                "final_claim",
                "claim",
                final_claim,
                step=len(evidence),
                name="final_claim",
                ok=None,
                data={"final_claim": final_claim},
            )
        )
    if files_read:
        evidence.append(
            AutopsyEvidence(
                f"E{len(evidence) + 1}",
                "trajectory",
                "read",
                "Files read: " + ", ".join(files_read),
                step=len(evidence),
                name="files_read",
                ok=True,
                data={"files": files_read},
            )
        )
    for edited in files_edited:
        in_scope = not allowed_files or edited in allowed_files
        evidence.append(
            AutopsyEvidence(
                f"E{len(evidence) + 1}",
                "trajectory",
                "edit",
                f"Agent edited {edited}.",
                step=len(evidence),
                name="files_edited",
                ok=in_scope,
                reason="" if in_scope else "edited file outside allowed scope",
                data={"file": edited, "allowed_files": allowed_files},
            )
        )
    if commands_run:
        evidence.append(
            AutopsyEvidence(
                f"E{len(evidence) + 1}",
                "trajectory",
                "command",
                "Commands run: " + "; ".join(commands_run),
                step=len(evidence),
                name="commands_run",
                ok=True,
                data={"commands": commands_run},
            )
        )
    if test_summary:
        evidence.append(
            AutopsyEvidence(
                f"E{len(evidence) + 1}",
                "test_output",
                "test",
                test_summary,
                step=len(evidence),
                name="test_output",
                ok=(test_status == "passed"),
                reason="" if test_status == "passed" else "test output indicates failed validation",
                data={"status": test_status},
            )
        )

    findings: list[AutopsyFinding] = []
    out_of_scope = [item for item in evidence if item.kind == "edit" and item.ok is False]
    if out_of_scope:
        files = ", ".join(str(item.data.get("file")) for item in out_of_scope)
        findings.append(
            AutopsyFinding(
                "scope_violation",
                f"The run edited out-of-scope file(s): {files}.",
                evidence_ids=tuple(item.evidence_id for item in out_of_scope),
                intercept="reject runs that touch files outside the claimed patch scope",
                confidence="high",
            )
        )
    if test_status == "failed":
        test_ids = tuple(item.evidence_id for item in evidence if item.kind == "test" and item.ok is False)
        findings.append(
            AutopsyFinding(
                "post_edit_validation_failure",
                "The supplied test evidence indicates validation failed after the edit.",
                evidence_ids=test_ids,
                intercept="block final success claims when post-edit validation fails",
                confidence="high",
            )
        )
    if test_status == "unknown":
        test_ids = tuple(item.evidence_id for item in evidence if item.kind == "test")
        findings.append(
            AutopsyFinding(
                "ambiguous_test_evidence",
                "The supplied test output could not be classified as passing or failing.",
                evidence_ids=test_ids,
                intercept="require structured status or a recognizable test summary",
                confidence="medium",
            )
        )
    if test_status == "missing" and _looks_like_success_claim(final_claim):
        claim_ids = tuple(item.evidence_id for item in evidence if item.source == "final_claim")
        findings.append(
            AutopsyFinding(
                "missing_test_evidence",
                "The run has a success claim after an edit, but no command or test-output evidence was supplied.",
                evidence_ids=claim_ids,
                intercept="require a targeted validation command before accepting the final claim",
                confidence="high",
            )
        )

    failure_class = findings[0].finding_type if findings else ""
    status = "PASSED"
    failed_at = ""
    if any(item.finding_type == "scope_violation" for item in findings):
        status = "FAILED"
        failed_at = "scope_check"
    elif test_status == "failed":
        status = "FAILED"
        failed_at = "test_output"
    elif test_status == "unknown" and findings:
        status = "UNVERIFIED"
        failed_at = "test_output"
    elif test_status == "missing" and findings:
        status = "UNVERIFIED"
        failed_at = "final_claim"

    return AgentAutopsyReport(
        title="agent-run audit record",
        source_agent=str(payload.get("source_agent") or "unknown"),
        command=commands_run[0] if commands_run else "none supplied",
        status=status,
        failure_class=failure_class,
        failed_at=failed_at,
        evidence=tuple(evidence),
        findings=tuple(findings),
        intercepts=tuple(item.intercept for item in findings if item.intercept),
        sources=(str(path),),
    )


def render_evidence_court_report(report: AgentAutopsyReport) -> str:
    verdict = _verdict(report)
    claim_evidence = next((item for item in report.evidence if item.name == "claimed_task"), None)
    final_claim = next((item for item in report.evidence if item.name == "final_claim"), None)
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
        f"- claimed_task: {_claim_text(claim_evidence) or 'Fix the calculator bug and finish with passing validation.'}",
        f"- final_claim_under_audit: {_claim_text(final_claim) or 'The run should not be accepted as complete unless validation evidence supports it.'}",
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
        f"- reason: {scope_violation.summary if scope_violation else 'no out-of-scope edit evidence was supplied in this record.'}",
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


def dumps_evidence_court_json(report: AgentAutopsyReport) -> str:
    payload = {
        "verdict": _verdict(report),
        "status": report.status,
        "failure_class": report.failure_class or "",
        "failed_at": report.failed_at,
        "finding_types": [item.finding_type for item in report.findings],
        "report": report.to_dict(),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


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


def _claim_text(item: AutopsyEvidence | None) -> str:
    if item is None:
        return ""
    return item.summary.replace("\n", " ")[:220]


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("audit record list fields must be arrays")
    result: list[str] = []
    for item in value:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict) and isinstance(item.get("file"), str):
            result.append(str(item["file"]))
        else:
            raise ValueError("audit record arrays must contain strings or file objects")
    return result


def _command_summaries(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("commands_run must be an array")
    commands: list[str] = []
    for item in value:
        if isinstance(item, str):
            commands.append(item)
        elif isinstance(item, dict) and isinstance(item.get("command"), str):
            command = str(item["command"])
            if "exit_code" in item:
                command = f"{command} (exit_code={item['exit_code']})"
            commands.append(command)
        else:
            raise ValueError("commands_run entries must be strings or command objects")
    return commands


def _test_output_status(test_output: object, commands_run: object) -> tuple[str, str]:
    exit_codes = []
    if isinstance(commands_run, list):
        for item in commands_run:
            if isinstance(item, dict) and isinstance(item.get("exit_code"), int):
                exit_codes.append(int(item["exit_code"]))
    if isinstance(test_output, dict):
        status = str(test_output.get("status") or "").lower()
        text = str(test_output.get("output") or test_output.get("summary") or "").strip()
        if status in {"passed", "pass", "success"}:
            return "passed", text or "test output status: passed"
        if status in {"failed", "fail", "failure"}:
            return "failed", text or "test output status: failed"
        if isinstance(test_output.get("exit_code"), int):
            return ("passed" if int(test_output["exit_code"]) == 0 else "failed", text or f"test exit_code: {test_output['exit_code']}")
        if text:
            return _test_output_status(text, commands_run)
    if isinstance(test_output, str) and test_output.strip():
        text = test_output.strip()
        lowered = text.lower()
        if re.search(r"\b[1-9]\d*\s+failed\b", lowered) or re.search(r"\bfailures?=\s*[1-9]\d*\b", lowered):
            return "failed", text
        if re.search(r"\b\d+\s+passed\b", lowered) and not re.search(r"\b[1-9]\d*\s+failed\b", lowered):
            return "passed", text
        return "unknown", text
    if exit_codes:
        return ("passed" if all(code == 0 for code in exit_codes) else "failed", "command exit_code evidence: " + ", ".join(str(code) for code in exit_codes))
    return "missing", ""


def _looks_like_success_claim(text: str) -> bool:
    lowered = text.lower()
    success_markers = ("fixed", "complete", "completed", "done", "verified", "passed", "success")
    return any(marker in lowered for marker in success_markers)
