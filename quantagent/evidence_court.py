from __future__ import annotations

import json
import re
from pathlib import Path

from .agent_autopsy import AgentAutopsyReport, AutopsyEvidence, AutopsyFinding, build_agent_autopsy


BAD_RUN_FIXTURE = Path("tests/fixtures/agent_autopsy/agent_modified_test_failed")
EVIDENCE_COURT_SCHEMA_VERSION = "evidence-court/v0.1"
RUN_METRIC_FIELDS = (
    "duration_seconds",
    "command_count",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "estimated_cost_usd",
    "actual_cost_usd",
    "cost_usd",
    "provider",
    "model",
    "missing_telemetry",
)


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
    run_metrics = _run_metrics(payload.get("run_metrics"))
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
    if run_metrics:
        evidence.append(
            AutopsyEvidence(
                f"E{len(evidence) + 1}",
                "run_metrics",
                "metrics",
                "Run metrics: " + _run_metrics_summary(run_metrics),
                step=len(evidence),
                name="run_metrics",
                ok=True,
                data={"run_metrics": run_metrics},
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


def build_audit_record_from_jsonl(events_path: str | Path) -> dict[str, object]:
    path = Path(events_path).expanduser().resolve(strict=False)
    record: dict[str, object] = {
        "claimed_task": "",
        "allowed_files": [],
        "files_read": [],
        "files_edited": [],
        "commands_run": [],
        "test_output": "",
        "final_claim": "",
    }
    files_read: list[str] = []
    files_edited: list[str] = []
    commands_run: list[object] = []
    run_metrics: dict[str, object] = {}
    test_output = ""

    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        event = json.loads(line)
        if not isinstance(event, dict):
            raise ValueError(f"JSONL event at line {line_no} must be an object")
        kind = str(event.get("kind") or event.get("type") or event.get("event") or "").strip()
        if kind == "task":
            record["claimed_task"] = str(event.get("claimed_task") or event.get("task") or "").strip()
            if "allowed_files" in event:
                record["allowed_files"] = _string_list(event.get("allowed_files"))
        elif kind == "read":
            files_read.extend(_event_files(event))
        elif kind == "edit":
            files_edited.extend(_event_files(event))
        elif kind == "command":
            command = str(event.get("command") or "").strip()
            if command:
                item: dict[str, object] = {"command": command}
                if isinstance(event.get("exit_code"), int):
                    item["exit_code"] = event["exit_code"]
                commands_run.append(item)
            event_metrics = _event_run_metrics(event)
            if event_metrics:
                _merge_run_metrics(run_metrics, event_metrics)
            output = str(event.get("output") or event.get("summary") or "").strip()
            if output:
                test_output = output
        elif kind == "final_claim":
            record["final_claim"] = str(event.get("final_claim") or event.get("claim") or event.get("text") or "").strip()
        else:
            raise ValueError(f"unsupported JSONL event kind at line {line_no}: {kind or 'missing'}")

    record["files_read"] = files_read
    record["files_edited"] = files_edited
    record["commands_run"] = commands_run
    record["test_output"] = test_output
    if run_metrics:
        if commands_run and "command_count" not in run_metrics:
            run_metrics["command_count"] = len(commands_run)
        record["run_metrics"] = run_metrics
    return record


def build_audit_record_from_codex_transcript(transcript_path: str | Path) -> dict[str, object]:
    path = Path(transcript_path).expanduser().resolve(strict=False)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Codex transcript must be a JSON object")

    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise ValueError("Codex transcript must include a messages array")

    record: dict[str, object] = {
        "source_agent": "codex",
        "source_format": "codex-transcript/v0.1",
        "claimed_task": str(payload.get("claimed_task") or payload.get("task") or "").strip(),
        "allowed_files": _string_list(payload.get("allowed_files")),
        "files_read": [],
        "files_edited": [],
        "commands_run": [],
        "test_output": "",
        "run_metrics": {},
        "final_claim": str(payload.get("final_claim") or "").strip(),
        "adapter_report": {
            "unsupported": [],
        },
    }
    files_read: list[str] = []
    files_edited: list[str] = []
    commands_run: list[dict[str, object]] = []
    run_metrics: dict[str, object] = {}
    unsupported: list[str] = []
    test_output = ""

    for message_index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise ValueError(f"Codex transcript message {message_index} must be an object")
        role = str(message.get("role") or "").strip().lower()
        content = _codex_content_text(message.get("content"))
        if role == "user" and content and not record["claimed_task"]:
            record["claimed_task"] = content
        if role == "assistant" and content:
            record["final_claim"] = content

        for tool_path, tool_call in _codex_tool_calls(message, message_index):
            tool_payload = _codex_tool_payload(tool_call)
            tool_kind = _codex_tool_kind(tool_call, tool_payload)
            if tool_kind in {"read", "read_file", "open", "cat"}:
                files_read.extend(_codex_tool_files(tool_payload))
            elif tool_kind in {"edit", "write", "write_file", "apply_patch", "patch"}:
                files_edited.extend(_codex_tool_files(tool_payload))
            elif tool_kind in {"command", "shell", "exec", "exec_command", "run_command"}:
                command = str(tool_payload.get("command") or tool_payload.get("cmd") or "").strip()
                if not command:
                    unsupported.append(f"{tool_path}: missing command")
                    continue
                item: dict[str, object] = {"command": command}
                if isinstance(tool_payload.get("exit_code"), int):
                    item["exit_code"] = tool_payload["exit_code"]
                commands_run.append(item)
                metrics = _event_run_metrics(tool_payload)
                if metrics:
                    _merge_run_metrics(run_metrics, metrics)
                output = _codex_command_output(tool_payload)
                if output:
                    test_output = output
            else:
                unsupported.append(f"{tool_path}: {tool_kind or 'unsupported'}")

    if commands_run and "command_count" not in run_metrics:
        run_metrics["command_count"] = len(commands_run)
    record["files_read"] = files_read
    record["files_edited"] = files_edited
    record["commands_run"] = commands_run
    record["test_output"] = test_output
    if run_metrics:
        record["run_metrics"] = run_metrics
    else:
        record.pop("run_metrics")
    adapter_report = {"unsupported": unsupported}
    record["adapter_report"] = adapter_report
    return record


def build_audit_record_from_claude_transcript(transcript_path: str | Path) -> dict[str, object]:
    path = Path(transcript_path).expanduser().resolve(strict=False)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Claude transcript must be a JSON object")

    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise ValueError("Claude transcript must include a messages array")

    record: dict[str, object] = {
        "source_agent": "claude",
        "source_format": "claude-transcript/v0.1",
        "claimed_task": str(payload.get("claimed_task") or payload.get("task") or "").strip(),
        "allowed_files": _string_list(payload.get("allowed_files")),
        "files_read": [],
        "files_edited": [],
        "commands_run": [],
        "test_output": "",
        "run_metrics": {},
        "final_claim": str(payload.get("final_claim") or "").strip(),
        "adapter_report": {
            "unsupported": [],
        },
    }
    files_read: list[str] = []
    files_edited: list[str] = []
    commands_run: list[dict[str, object]] = []
    run_metrics: dict[str, object] = {}
    unsupported: list[str] = []
    test_output = ""

    for message_index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise ValueError(f"Claude transcript message {message_index} must be an object")
        role = str(message.get("role") or "").strip().lower()
        content = _codex_content_text(message.get("content"))
        if role == "user" and content and not record["claimed_task"]:
            record["claimed_task"] = content
        if role == "assistant" and content:
            record["final_claim"] = content

        tool_calls = _codex_tool_calls(message, message_index)
        tool_calls.extend(_claude_content_tool_uses(message, message_index))
        for tool_path, tool_call in tool_calls:
            tool_payload = _codex_tool_payload(tool_call)
            tool_kind = _codex_tool_kind(tool_call, tool_payload)
            if tool_kind in {"read", "read_file", "open", "view", "cat"}:
                files_read.extend(_codex_tool_files(tool_payload))
            elif tool_kind in {"edit", "write", "write_file", "apply_patch", "patch", "multi_edit", "multiedit"}:
                files_edited.extend(_codex_tool_files(tool_payload))
            elif tool_kind in {"command", "shell", "exec", "exec_command", "run_command", "bash"}:
                command = str(tool_payload.get("command") or tool_payload.get("cmd") or "").strip()
                if not command:
                    unsupported.append(f"{tool_path}: missing command")
                    continue
                item: dict[str, object] = {"command": command}
                if isinstance(tool_payload.get("exit_code"), int):
                    item["exit_code"] = tool_payload["exit_code"]
                commands_run.append(item)
                metrics = _event_run_metrics(tool_payload)
                if metrics:
                    _merge_run_metrics(run_metrics, metrics)
                output = _codex_command_output(tool_payload)
                if output:
                    test_output = output
            else:
                unsupported.append(f"{tool_path}: {tool_kind or 'unsupported'}")

    if commands_run and "command_count" not in run_metrics:
        run_metrics["command_count"] = len(commands_run)
    record["files_read"] = files_read
    record["files_edited"] = files_edited
    record["commands_run"] = commands_run
    record["test_output"] = test_output
    if run_metrics:
        record["run_metrics"] = run_metrics
    else:
        record.pop("run_metrics")
    record["adapter_report"] = {"unsupported": unsupported}
    return record


def build_audit_record_from_openhands_transcript(transcript_path: str | Path) -> dict[str, object]:
    path = Path(transcript_path).expanduser().resolve(strict=False)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("OpenHands transcript must be a JSON object")

    events = payload.get("events")
    if not isinstance(events, list):
        raise ValueError("OpenHands transcript must include an events array")

    record: dict[str, object] = {
        "source_agent": "openhands",
        "source_format": "openhands-transcript/v0.1",
        "claimed_task": str(payload.get("claimed_task") or payload.get("task") or "").strip(),
        "allowed_files": _string_list(payload.get("allowed_files")),
        "files_read": [],
        "files_edited": [],
        "commands_run": [],
        "test_output": "",
        "run_metrics": {},
        "final_claim": str(payload.get("final_claim") or "").strip(),
        "adapter_report": {
            "unsupported": [],
        },
    }
    files_read: list[str] = []
    files_edited: list[str] = []
    commands_run: list[dict[str, object]] = []
    run_metrics: dict[str, object] = {}
    unsupported: list[str] = []
    test_output = ""

    for event_index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"OpenHands transcript event {event_index} must be an object")
        event_kind = _openhands_event_kind(event)
        event_path = f"events[{event_index}]"
        if event_kind in {"task", "instruction"}:
            text = _openhands_event_text(event)
            if text and not record["claimed_task"]:
                record["claimed_task"] = text
        elif event_kind in {"read", "read_file", "file_read"}:
            files_read.extend(_codex_tool_files(event))
        elif event_kind in {"edit", "write", "write_file", "apply_patch", "patch"}:
            files_edited.extend(_codex_tool_files(event))
        elif event_kind in {"command", "shell", "run", "execute", "run_command"}:
            command = str(event.get("command") or event.get("cmd") or "").strip()
            if not command:
                unsupported.append(f"{event_path}: missing command")
                continue
            item: dict[str, object] = {"command": command}
            if isinstance(event.get("exit_code"), int):
                item["exit_code"] = event["exit_code"]
            commands_run.append(item)
            metrics = _event_run_metrics(event)
            if metrics:
                _merge_run_metrics(run_metrics, metrics)
            output = _codex_command_output(event)
            if output:
                test_output = output
        elif event_kind in {"finish", "final", "final_claim", "message"}:
            text = _openhands_event_text(event)
            if text:
                record["final_claim"] = text
        else:
            unsupported.append(f"{event_path}: {event_kind or 'unsupported'}")

    if commands_run and "command_count" not in run_metrics:
        run_metrics["command_count"] = len(commands_run)
    record["files_read"] = files_read
    record["files_edited"] = files_edited
    record["commands_run"] = commands_run
    record["test_output"] = test_output
    if run_metrics:
        record["run_metrics"] = run_metrics
    else:
        record.pop("run_metrics")
    record["adapter_report"] = {"unsupported": unsupported}
    return record


def build_audit_record_from_swe_agent_transcript(transcript_path: str | Path) -> dict[str, object]:
    path = Path(transcript_path).expanduser().resolve(strict=False)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("SWE-agent transcript must be a JSON object")

    steps = payload.get("steps")
    if not isinstance(steps, list):
        raise ValueError("SWE-agent transcript must include a steps array")

    record: dict[str, object] = {
        "source_agent": "swe-agent",
        "source_format": "swe-agent-transcript/v0.1",
        "claimed_task": str(payload.get("claimed_task") or payload.get("task") or payload.get("issue") or "").strip(),
        "allowed_files": _string_list(payload.get("allowed_files")),
        "files_read": [],
        "files_edited": [],
        "commands_run": [],
        "test_output": "",
        "run_metrics": {},
        "final_claim": str(payload.get("final_claim") or "").strip(),
        "adapter_report": {
            "unsupported": [],
        },
    }
    files_read: list[str] = []
    files_edited: list[str] = []
    commands_run: list[dict[str, object]] = []
    run_metrics: dict[str, object] = {}
    unsupported: list[str] = []
    test_output = ""

    for step_index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"SWE-agent transcript step {step_index} must be an object")
        step_kind = _swe_agent_step_kind(step)
        step_path = f"steps[{step_index}]"
        if step_kind in {"task", "instruction", "issue"}:
            text = _openhands_event_text(step)
            if text and not record["claimed_task"]:
                record["claimed_task"] = text
        elif step_kind in {"read", "read_file", "open"}:
            files_read.extend(_codex_tool_files(step))
        elif step_kind in {"edit", "write", "write_file", "apply_patch", "patch"}:
            files_edited.extend(_codex_tool_files(step))
        elif step_kind in {"command", "shell", "run", "run_command", "test"}:
            command = str(step.get("command") or step.get("cmd") or "").strip()
            if not command:
                unsupported.append(f"{step_path}: missing command")
                continue
            item: dict[str, object] = {"command": command}
            if isinstance(step.get("exit_code"), int):
                item["exit_code"] = step["exit_code"]
            commands_run.append(item)
            metrics = _event_run_metrics(step)
            if metrics:
                _merge_run_metrics(run_metrics, metrics)
            output = _codex_command_output(step)
            if output:
                test_output = output
        elif step_kind in {"finish", "final", "final_claim", "submit"}:
            text = _openhands_event_text(step)
            if text:
                record["final_claim"] = text
        else:
            unsupported.append(f"{step_path}: {step_kind or 'unsupported'}")

    if commands_run and "command_count" not in run_metrics:
        run_metrics["command_count"] = len(commands_run)
    record["files_read"] = files_read
    record["files_edited"] = files_edited
    record["commands_run"] = commands_run
    record["test_output"] = test_output
    if run_metrics:
        record["run_metrics"] = run_metrics
    else:
        record.pop("run_metrics")
    record["adapter_report"] = {"unsupported": unsupported}
    return record


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
        "schema_version": EVIDENCE_COURT_SCHEMA_VERSION,
        "verdict": evidence_court_verdict(report),
        "status": report.status,
        "failure_class": report.failure_class or "",
        "failed_at": report.failed_at,
        "finding_types": [item.finding_type for item in report.findings],
        "run_metrics": _report_run_metrics(report),
        "report": report.to_dict(),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def evidence_court_verdict(report: AgentAutopsyReport) -> str:
    return _verdict(report)


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


def _run_metrics(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("run_metrics must be an object")
    metrics = dict(value)
    if "missing_telemetry" in metrics:
        missing = metrics["missing_telemetry"]
        if not isinstance(missing, list) or not all(isinstance(item, str) for item in missing):
            raise ValueError("run_metrics.missing_telemetry must be an array of strings")
        metrics["missing_telemetry"] = [item for item in missing if item.strip()]
    return metrics


def _event_run_metrics(event: dict[str, object]) -> dict[str, object]:
    metrics = _run_metrics(event.get("run_metrics"))
    for field in RUN_METRIC_FIELDS:
        if field in event:
            metrics[field] = event[field]
    if isinstance(event.get("tokens"), dict):
        tokens = event["tokens"]
        for field in ("input_tokens", "output_tokens", "total_tokens"):
            if field in tokens and field not in metrics:
                metrics[field] = tokens[field]
    if "cost_usd" in metrics and "estimated_cost_usd" not in metrics:
        metrics["estimated_cost_usd"] = metrics["cost_usd"]
    return _run_metrics(metrics) if metrics else {}


def _merge_run_metrics(target: dict[str, object], source: dict[str, object]) -> None:
    for key, value in source.items():
        if key == "missing_telemetry":
            existing = target.get(key)
            values: list[str] = []
            if isinstance(existing, list):
                values.extend(str(item) for item in existing)
            if isinstance(value, list):
                values.extend(str(item) for item in value)
            target[key] = list(dict.fromkeys(item for item in values if item.strip()))
        else:
            target[key] = value


def _report_run_metrics(report: AgentAutopsyReport) -> dict[str, object]:
    item = next((evidence for evidence in report.evidence if evidence.name == "run_metrics"), None)
    if item is None:
        return {}
    metrics = item.data.get("run_metrics")
    return dict(metrics) if isinstance(metrics, dict) else {}


def _run_metrics_summary(metrics: dict[str, object]) -> str:
    parts: list[str] = []
    for field in RUN_METRIC_FIELDS:
        if field not in metrics:
            continue
        value = metrics[field]
        if field == "missing_telemetry" and isinstance(value, list):
            value = ",".join(str(item) for item in value) or "none"
        parts.append(f"{field}={value}")
    extra_fields = sorted(key for key in metrics if key not in RUN_METRIC_FIELDS)
    parts.extend(f"{key}={metrics[key]}" for key in extra_fields)
    return ", ".join(parts) if parts else "none supplied"


def _event_files(event: dict[str, object]) -> list[str]:
    if "files" in event:
        return _string_list(event.get("files"))
    if isinstance(event.get("file"), str):
        return [str(event["file"])]
    raise ValueError("read/edit JSONL events must include file or files")


def _codex_tool_calls(message: dict[str, object], message_index: int) -> list[tuple[str, dict[str, object]]]:
    calls: list[tuple[str, dict[str, object]]] = []
    for field in ("tool_calls", "tool_uses", "tools"):
        value = message.get(field)
        if value is None:
            continue
        if not isinstance(value, list):
            raise ValueError(f"Codex transcript messages[{message_index}].{field} must be an array")
        for call_index, item in enumerate(value):
            if not isinstance(item, dict):
                raise ValueError(
                    f"Codex transcript messages[{message_index}].{field}[{call_index}] must be an object"
                )
            calls.append((f"messages[{message_index}].{field}[{call_index}]", item))
    return calls


def _claude_content_tool_uses(message: dict[str, object], message_index: int) -> list[tuple[str, dict[str, object]]]:
    content = message.get("content")
    if content is None:
        return []
    if not isinstance(content, list):
        return []
    calls: list[tuple[str, dict[str, object]]] = []
    for block_index, block in enumerate(content):
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "").strip().lower().replace("-", "_")
        if block_type not in {"tool_use", "server_tool_use"}:
            continue
        calls.append((f"messages[{message_index}].content[{block_index}]", block))
    return calls


def _codex_tool_payload(tool_call: dict[str, object]) -> dict[str, object]:
    payload = dict(tool_call)
    for field in ("arguments", "input", "params"):
        nested = tool_call.get(field)
        if isinstance(nested, dict):
            payload.update(nested)
        elif isinstance(nested, str) and nested.strip().startswith("{"):
            try:
                decoded = json.loads(nested)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, dict):
                payload.update(decoded)
    return payload


def _codex_tool_kind(tool_call: dict[str, object], tool_payload: dict[str, object]) -> str:
    block_type = str(tool_payload.get("type") or tool_call.get("type") or "").strip().lower().replace("-", "_")
    if block_type in {"tool_use", "server_tool_use"} and (
        isinstance(tool_payload.get("name"), str) or isinstance(tool_call.get("name"), str)
    ):
        return str(tool_payload.get("name") or tool_call.get("name") or "").strip().lower().replace("-", "_")
    value = (
        tool_payload.get("kind")
        or tool_payload.get("type")
        or tool_payload.get("tool")
        or tool_payload.get("name")
        or tool_call.get("kind")
        or tool_call.get("type")
        or tool_call.get("name")
        or ""
    )
    return str(value).strip().lower().replace("-", "_")


def _codex_tool_files(tool_payload: dict[str, object]) -> list[str]:
    if "files" in tool_payload:
        return _string_list(tool_payload.get("files"))
    if "paths" in tool_payload:
        return _string_list(tool_payload.get("paths"))
    for field in ("file", "path", "file_path"):
        if isinstance(tool_payload.get(field), str):
            return [str(tool_payload[field])]
    return []


def _codex_content_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(str(item["text"]))
        return "\n".join(part.strip() for part in parts if part.strip())
    return ""


def _codex_command_output(tool_payload: dict[str, object]) -> str:
    parts: list[str] = []
    for field in ("output", "stdout", "stderr", "summary", "observation"):
        if isinstance(tool_payload.get(field), str) and str(tool_payload[field]).strip():
            parts.append(str(tool_payload[field]).strip())
    return "\n".join(parts)


def _openhands_event_kind(event: dict[str, object]) -> str:
    value = event.get("kind") or event.get("type") or event.get("action") or event.get("operation") or ""
    return str(value).strip().lower().replace("-", "_")


def _openhands_event_text(event: dict[str, object]) -> str:
    for field in ("message", "content", "text", "instruction", "final_claim"):
        if isinstance(event.get(field), str) and str(event[field]).strip():
            return str(event[field]).strip()
    return ""


def _swe_agent_step_kind(step: dict[str, object]) -> str:
    value = step.get("kind") or step.get("type") or step.get("action") or step.get("operation") or step.get("role") or ""
    return str(value).strip().lower().replace("-", "_")


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
