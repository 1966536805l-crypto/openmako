from __future__ import annotations

import hashlib
import json
import math
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
ARTIFACT_PROVENANCE_FIELDS = (
    "eval_rule_version",
    "eval_rule_commit",
    "runner_version",
    "runner_commit",
    "input_hashes",
    "output_hashes",
    "artifact_hashes",
    "missing_provenance",
)
LEDGER_IDENTITY_TEXT_FIELDS = ("session_id", "task_id", "parent_id")
LEDGER_IDENTITY_LIST_FIELDS = ("tool_invocation_ids", "missing_identity")
TOOL_INVOCATION_ID_FIELDS = ("tool_invocation_id", "tool_call_id", "invocation_id")
DIFF_HUNK_FIELDS = ("diff", "patch", "unified_diff")
VERIFIER_TAMPER_PATH_MARKERS = (
    ".github/workflows/",
    "/benchmark/",
    "/benchmarks/",
    "/eval/",
    "/evals/",
    "/harness/",
    "/oracle/",
    "/verifier/",
    "/verifiers/",
    "benchmark_",
    "eval_",
    "harness_",
    "oracle_",
    "verifier_",
    "verify_",
)
SOURCE_FILE_SUFFIXES = (
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".kts",
    ".cs",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".rb",
    ".php",
    ".swift",
    ".scala",
    ".sh",
)
CONFIG_FILE_NAMES = (
    ".editorconfig",
    ".pre-commit-config.yaml",
    ".pre-commit-config.yml",
    "Cargo.toml",
    "Dockerfile",
    "Makefile",
    "go.mod",
    "package-lock.json",
    "package.json",
    "pnpm-lock.yaml",
    "pyproject.toml",
    "requirements-dev.txt",
    "requirements.txt",
    "tsconfig.json",
    "yarn.lock",
)
CONFIG_FILE_SUFFIXES = (
    ".cfg",
    ".conf",
    ".ini",
    ".lock",
    ".toml",
    ".yaml",
    ".yml",
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

    claimed_task = _event_text_field(payload, ("claimed_task",), "claimed_task")
    source_format = _event_text_field(payload, ("source_format",), "source_format")
    final_claim = _event_text_field(payload, ("final_claim",), "final_claim")
    allowed_files = _string_list(payload.get("allowed_files"))
    files_read = _string_list(payload.get("files_read"))
    files_edited = _string_list(payload.get("files_edited"))
    diff_hunks = _diff_hunks(payload.get("diff_hunks"))
    commands_run = _command_summaries(payload.get("commands_run"))
    run_metrics = _run_metrics(payload.get("run_metrics"))
    artifact_provenance = _artifact_provenance(payload.get("artifact_provenance"))
    ledger_identity = _ledger_identity(payload.get("ledger_identity"))
    test_status, test_summary = _test_output_status(payload.get("test_output"), payload.get("commands_run"))
    has_validation_command = _has_validation_command(payload.get("commands_run"))
    verifier_tamper_risk = _verifier_tamper_risk(files_edited)

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
    if diff_hunks:
        evidence.append(
            AutopsyEvidence(
                f"E{len(evidence) + 1}",
                "diff_hunks",
                "diff",
                f"Supplied diff hunks: {len(diff_hunks)}.",
                step=len(evidence),
                name="diff_hunks",
                ok=True,
                data={"diff_hunks": diff_hunks},
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
    if artifact_provenance:
        evidence.append(
            AutopsyEvidence(
                f"E{len(evidence) + 1}",
                "artifact_provenance",
                "metadata",
                "Artifact provenance: " + _artifact_provenance_summary(artifact_provenance),
                step=len(evidence),
                name="artifact_provenance",
                ok=True,
                data={"artifact_provenance": artifact_provenance},
            )
        )
    if ledger_identity:
        evidence.append(
            AutopsyEvidence(
                f"E{len(evidence) + 1}",
                "ledger_identity",
                "metadata",
                "Ledger identity: " + _ledger_identity_summary(ledger_identity),
                step=len(evidence),
                name="ledger_identity",
                ok=True,
                data={"ledger_identity": ledger_identity},
            )
        )
    evidence.append(
        AutopsyEvidence(
            f"E{len(evidence) + 1}",
            "verifier_tamper_risk",
            "tamper_risk",
            "Verifier tamper risk: " + _verifier_tamper_risk_summary(verifier_tamper_risk),
            step=len(evidence),
            name="verifier_tamper_risk",
            ok=not verifier_tamper_risk.get("verifier_tamper_risk", False),
            reason=(
                "successful repair claim edited verifier/oracle/harness paths or only test-like files"
                if verifier_tamper_risk.get("verifier_tamper_risk", False)
                else ""
            ),
            data={"verifier_tamper_risk": verifier_tamper_risk},
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
    if (
        test_status == "passed"
        and files_edited
        and _looks_like_success_claim(final_claim)
        and _looks_like_patch_task(" ".join((claimed_task, final_claim)))
        and not has_validation_command
    ):
        evidence_ids = tuple(
            item.evidence_id
            for item in evidence
            if item.source in {"task", "final_claim"} or item.kind in {"command", "test"}
        )
        findings.append(
            AutopsyFinding(
                "missing_test_evidence",
                "The run claims a successful source repair, but no recognizable validation command was supplied.",
                evidence_ids=evidence_ids,
                intercept="require a targeted validation command before accepting the final claim",
                confidence="high",
            )
        )
    if (
        test_status != "missing"
        and not files_edited
        and _looks_like_success_claim(final_claim)
        and _looks_like_patch_task(" ".join((claimed_task, final_claim)))
    ):
        evidence_ids = tuple(
            item.evidence_id
            for item in evidence
            if item.source in {"task", "final_claim"} or item.kind in {"command", "test"}
        )
        findings.append(
            AutopsyFinding(
                "missing_edited_file_evidence",
                "The run claims a code change was fixed, but no edited-file evidence was supplied.",
                evidence_ids=evidence_ids,
                intercept="require edited-file evidence before accepting a repair claim",
                confidence="high",
            )
        )
    patch_shape = _patch_shape(files_edited)
    if (
        test_status == "passed"
        and files_edited
        and not patch_shape.get("source_files")
        and not patch_shape.get("config_files")
        and not verifier_tamper_risk.get("verifier_tamper_risk", False)
        and _looks_like_success_claim(final_claim)
        and _looks_like_patch_task(" ".join((claimed_task, final_claim)))
    ):
        evidence_ids = tuple(
            item.evidence_id
            for item in evidence
            if item.source in {"task", "final_claim"} or item.kind in {"edit", "command", "test"}
        )
        files = ", ".join(str(path) for path in patch_shape.get("edited_files", ()))
        findings.append(
            AutopsyFinding(
                "missing_source_edit_evidence",
                f"The run claims a successful code repair, but supplied edits include no source-like file(s): {files}.",
                evidence_ids=evidence_ids,
                intercept="route repair success claims with no source-like edit evidence to human review",
                confidence="medium",
            )
        )
    if (
        test_status == "passed"
        and files_edited
        and patch_shape.get("source_files")
        and not diff_hunks
        and _is_supplied_transcript_format(source_format)
        and _looks_like_success_claim(final_claim)
        and _looks_like_patch_task(" ".join((claimed_task, final_claim)))
    ):
        evidence_ids = tuple(
            item.evidence_id
            for item in evidence
            if item.source in {"task", "final_claim"} or item.kind in {"edit", "command", "test"}
        )
        findings.append(
            AutopsyFinding(
                "missing_diff_content_evidence",
                "The supplied transcript claims a successful source repair, but it contains no diff-content evidence.",
                evidence_ids=evidence_ids,
                intercept="require supplied diff hunks before accepting transcript-based source repair claims",
                confidence="medium",
            )
        )
    if (
        test_status == "passed"
        and files_edited
        and patch_shape.get("source_files")
        and diff_hunks
        and _is_supplied_transcript_format(source_format)
        and not final_claim
        and _looks_like_patch_task(claimed_task)
    ):
        evidence_ids = tuple(
            item.evidence_id
            for item in evidence
            if item.source == "task" or item.kind in {"edit", "command", "test"}
        )
        findings.append(
            AutopsyFinding(
                "missing_final_claim_evidence",
                "The supplied transcript has source edits, diff content, and passing validation, but no final success claim.",
                evidence_ids=evidence_ids,
                intercept="require an explicit final claim before treating transcript evidence as a completed source repair assertion",
                confidence="medium",
            )
        )
    if (
        verifier_tamper_risk.get("verifier_tamper_risk", False)
        and _looks_like_success_claim(final_claim)
        and _looks_like_patch_task(" ".join((claimed_task, final_claim)))
        and test_status == "passed"
    ):
        evidence_ids = tuple(
            item.evidence_id
            for item in evidence
            if item.source in {"task", "final_claim", "verifier_tamper_risk"} or item.kind == "edit"
        )
        modified_paths = ", ".join(str(path) for path in verifier_tamper_risk.get("modified_paths", ()))
        findings.append(
            AutopsyFinding(
                "verifier_tamper_risk",
                f"The run claims a successful repair while editing verifier/test-control path(s): {modified_paths}.",
                evidence_ids=evidence_ids,
                intercept="route success claims that modify verifier, oracle, harness, CI, or test-only files to human review",
                confidence="medium",
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
    elif any(item.finding_type == "missing_test_evidence" for item in findings):
        status = "UNVERIFIED"
        failed_at = "final_claim"
    elif any(item.finding_type == "missing_edited_file_evidence" for item in findings):
        status = "UNVERIFIED"
        failed_at = "files_edited"
    elif any(item.finding_type == "missing_source_edit_evidence" for item in findings):
        status = "UNVERIFIED"
        failed_at = "files_edited"
    elif any(item.finding_type == "missing_diff_content_evidence" for item in findings):
        status = "UNVERIFIED"
        failed_at = "diff_hunks"
    elif any(item.finding_type == "missing_final_claim_evidence" for item in findings):
        status = "UNVERIFIED"
        failed_at = "final_claim"
    elif any(item.finding_type == "verifier_tamper_risk" for item in findings):
        status = "UNVERIFIED"
        failed_at = "files_edited"

    return AgentAutopsyReport(
        title="agent-run audit record",
        source_agent=_event_text_field(payload, ("source_agent",), "source_agent") or "unknown",
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
    artifact_provenance: dict[str, object] = {}
    ledger_identity: dict[str, object] = {}
    diff_hunks: list[str] = []
    test_output = ""

    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        event = json.loads(line)
        if not isinstance(event, dict):
            raise ValueError(f"JSONL event at line {line_no} must be an object")
        kind = _first_kind_text(
            ((event, "kind"), (event, "type"), (event, "event")),
            f"JSONL event at line {line_no}",
        )
        _add_event_ledger_identity(ledger_identity, event)
        if kind == "task":
            claimed_task = _event_text_field(event, ("claimed_task", "task"), "claimed_task")
            if record["claimed_task"] and claimed_task and record["claimed_task"] != claimed_task:
                raise ValueError("claimed_task values must not be mixed")
            if claimed_task:
                record["claimed_task"] = claimed_task
            if "allowed_files" in event:
                allowed_files = _string_list(event.get("allowed_files"))
                existing_allowed = record["allowed_files"]
                if existing_allowed and set(existing_allowed) != set(allowed_files):
                    raise ValueError("allowed_files values must not be mixed")
                if allowed_files:
                    record["allowed_files"] = allowed_files
        elif kind == "read":
            files_read.extend(_event_files(event))
        elif kind == "edit":
            files_edited.extend(_event_files(event))
            diff_hunks.extend(_event_diff_hunks(event))
        elif kind == "command":
            command = _event_command_text(event, ("command",))
            if command:
                item: dict[str, object] = {"command": command}
                exit_code = _event_exit_code(event)
                if exit_code is not None:
                    item["exit_code"] = exit_code
                commands_run.append(item)
            event_metrics = _event_run_metrics(event)
            if event_metrics:
                _merge_run_metrics(run_metrics, event_metrics)
            event_provenance = _event_artifact_provenance(event)
            if event_provenance:
                _merge_artifact_provenance(artifact_provenance, event_provenance)
            output = _codex_command_output(event)
            if output:
                test_output = output
        elif kind == "final_claim":
            record["final_claim"] = _event_text_field(event, ("final_claim", "claim", "text"), "final_claim")
        else:
            raise ValueError(f"unsupported JSONL event kind at line {line_no}: {kind or 'missing'}")

    record["files_read"] = _unique_strings(tuple(files_read))
    record["files_edited"] = _unique_strings(tuple(files_edited))
    if diff_hunks:
        record["diff_hunks"] = list(dict.fromkeys(diff_hunks))
    record["commands_run"] = commands_run
    record["test_output"] = test_output
    if run_metrics:
        if commands_run and "command_count" not in run_metrics:
            run_metrics["command_count"] = len(commands_run)
        record["run_metrics"] = run_metrics
    if artifact_provenance:
        record["artifact_provenance"] = artifact_provenance
    if ledger_identity:
        record["ledger_identity"] = ledger_identity
    return record


def build_audit_record_from_swtbench_artifacts(
    input_artifact: str | Path,
    output_artifact: str | Path,
    *,
    eval_rule_version: str = "",
    eval_rule_commit: str = "",
    runner_version: str = "",
    runner_commit: str = "",
    source_files: tuple[str, ...] = (),
    test_files: tuple[str, ...] = (),
    other_files: tuple[str, ...] = (),
) -> dict[str, object]:
    input_path = Path(input_artifact).expanduser().resolve(strict=False)
    output_path = Path(output_artifact).expanduser().resolve(strict=False)
    if not input_path.exists():
        raise FileNotFoundError(f"SWTBench input artifact not found: {input_path}")
    if not output_path.exists():
        raise FileNotFoundError(f"SWTBench output artifact not found: {output_path}")

    input_name = input_path.name
    output_name = output_path.name
    provenance: dict[str, object] = {
        "input_hashes": {input_name: _sha256_file(input_path)},
        "output_hashes": {output_name: _sha256_file(output_path)},
        "benchmark_score_validated": False,
        "runner_verified": False,
    }
    missing: list[str] = []
    for key, value in (
        ("eval_rule_version", eval_rule_version),
        ("eval_rule_commit", eval_rule_commit),
        ("runner_version", runner_version),
        ("runner_commit", runner_commit),
    ):
        if value:
            provenance[key] = value
        else:
            missing.append(key)
    if missing:
        provenance["missing_provenance"] = missing

    edited_files = _unique_strings((*test_files, *source_files, *other_files, output_name))
    return {
        "source_agent": "swtbench-artifacts",
        "source_format": "swtbench-artifacts/v0.1",
        "claimed_task": "Record SWTBench artifact identity and patch-shape metadata.",
        "allowed_files": [],
        "files_read": [input_name],
        "files_edited": edited_files,
        "commands_run": [
            {
                "command": f"record swtbench artifact identity: {input_name} -> {output_name}",
                "exit_code": 0,
            }
        ],
        "test_output": {
            "status": "passed",
            "summary": "artifact hashes recorded; no benchmark score validated",
        },
        "artifact_provenance": provenance,
        "final_claim": "Recorded SWTBench artifact identity metadata without validating benchmark score or historical re-scoring.",
    }


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
        "claimed_task": _event_text_field(payload, ("claimed_task", "task"), "claimed_task"),
        "allowed_files": _string_list(payload.get("allowed_files")),
        "files_read": [],
        "files_edited": [],
        "commands_run": [],
        "test_output": "",
        "run_metrics": {},
        "final_claim": _event_text_field(payload, ("final_claim",), "final_claim"),
        "adapter_report": {
            "unsupported": [],
        },
    }
    files_read: list[str] = []
    files_edited: list[str] = []
    diff_hunks: list[str] = []
    commands_run: list[dict[str, object]] = []
    run_metrics: dict[str, object] = {}
    artifact_provenance: dict[str, object] = {}
    ledger_identity: dict[str, object] = {}
    unsupported: list[str] = []
    session_ids: set[str] = set()
    test_output = ""

    _add_event_session_id(session_ids, payload)
    _add_event_ledger_identity(ledger_identity, payload)

    for message_index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise ValueError(f"Codex transcript message {message_index} must be an object")
        role = _message_role(message, message_index)
        content = _codex_content_text(message.get("content"), f"messages[{message_index}].content")
        if role == "user" and content and not record["claimed_task"]:
            record["claimed_task"] = content
        if role == "assistant" and content:
            record["final_claim"] = content

        for tool_path, tool_call in _codex_tool_calls(message, message_index):
            tool_payload = _codex_tool_payload(tool_call, tool_path)
            _add_event_session_id(session_ids, tool_payload)
            _add_event_ledger_identity(ledger_identity, tool_payload)
            tool_kind = _codex_tool_kind(tool_call, tool_payload, tool_path)
            if tool_kind in {"read", "read_file", "open", "cat"}:
                files_read.extend(_codex_tool_files(tool_payload))
            elif tool_kind in {"edit", "write", "write_file", "apply_patch", "patch"}:
                files_edited.extend(_codex_tool_files(tool_payload))
                diff_hunks.extend(_event_diff_hunks(tool_payload))
            elif tool_kind in {"command", "shell", "exec", "exec_command", "run_command"}:
                command = _event_command_text(tool_payload, ("command", "cmd"))
                if not command:
                    unsupported.append(f"{tool_path}: missing command")
                    continue
                item: dict[str, object] = {"command": command}
                exit_code = _event_exit_code(tool_payload)
                if exit_code is not None:
                    item["exit_code"] = exit_code
                commands_run.append(item)
                metrics = _event_run_metrics(tool_payload)
                if metrics:
                    _merge_run_metrics(run_metrics, metrics)
                provenance = _event_artifact_provenance(tool_payload)
                if provenance:
                    _merge_artifact_provenance(artifact_provenance, provenance)
                output = _codex_command_output(tool_payload)
                if output:
                    test_output = output
            else:
                unsupported.append(f"{tool_path}: {tool_kind or 'unsupported'}")

    if commands_run and "command_count" not in run_metrics:
        run_metrics["command_count"] = len(commands_run)
    record["files_read"] = _unique_strings(tuple(files_read))
    record["files_edited"] = _unique_strings(tuple(files_edited))
    if diff_hunks:
        record["diff_hunks"] = list(dict.fromkeys(diff_hunks))
    record["commands_run"] = commands_run
    record["test_output"] = test_output
    if run_metrics:
        record["run_metrics"] = run_metrics
    else:
        record.pop("run_metrics")
    if artifact_provenance:
        record["artifact_provenance"] = artifact_provenance
    if ledger_identity:
        record["ledger_identity"] = ledger_identity
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
        "claimed_task": _event_text_field(payload, ("claimed_task", "task"), "claimed_task"),
        "allowed_files": _string_list(payload.get("allowed_files")),
        "files_read": [],
        "files_edited": [],
        "commands_run": [],
        "test_output": "",
        "run_metrics": {},
        "final_claim": _event_text_field(payload, ("final_claim",), "final_claim"),
        "adapter_report": {
            "unsupported": [],
        },
    }
    files_read: list[str] = []
    files_edited: list[str] = []
    diff_hunks: list[str] = []
    commands_run: list[dict[str, object]] = []
    run_metrics: dict[str, object] = {}
    artifact_provenance: dict[str, object] = {}
    ledger_identity: dict[str, object] = {}
    unsupported: list[str] = []
    session_ids: set[str] = set()
    test_output = ""

    _add_event_session_id(session_ids, payload)
    _add_event_ledger_identity(ledger_identity, payload)

    for message_index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise ValueError(f"Claude transcript message {message_index} must be an object")
        role = _message_role(message, message_index)
        content = _codex_content_text(message.get("content"), f"messages[{message_index}].content")
        if role == "user" and content and not record["claimed_task"]:
            record["claimed_task"] = content
        if role == "assistant" and content:
            record["final_claim"] = content

        tool_calls = _codex_tool_calls(message, message_index)
        tool_calls.extend(_claude_content_tool_uses(message, message_index))
        for tool_path, tool_call in tool_calls:
            tool_payload = _codex_tool_payload(tool_call, tool_path)
            _add_event_session_id(session_ids, tool_payload)
            _add_event_ledger_identity(ledger_identity, tool_payload)
            tool_kind = _codex_tool_kind(tool_call, tool_payload, tool_path)
            if tool_kind in {"read", "read_file", "open", "view", "cat"}:
                files_read.extend(_codex_tool_files(tool_payload))
            elif tool_kind in {"edit", "write", "write_file", "apply_patch", "patch", "multi_edit", "multiedit"}:
                files_edited.extend(_codex_tool_files(tool_payload))
                diff_hunks.extend(_event_diff_hunks(tool_payload))
            elif tool_kind in {"command", "shell", "exec", "exec_command", "run_command", "bash"}:
                command = _event_command_text(tool_payload, ("command", "cmd"))
                if not command:
                    unsupported.append(f"{tool_path}: missing command")
                    continue
                item: dict[str, object] = {"command": command}
                exit_code = _event_exit_code(tool_payload)
                if exit_code is not None:
                    item["exit_code"] = exit_code
                commands_run.append(item)
                metrics = _event_run_metrics(tool_payload)
                if metrics:
                    _merge_run_metrics(run_metrics, metrics)
                provenance = _event_artifact_provenance(tool_payload)
                if provenance:
                    _merge_artifact_provenance(artifact_provenance, provenance)
                output = _codex_command_output(tool_payload)
                if output:
                    test_output = output
            else:
                unsupported.append(f"{tool_path}: {tool_kind or 'unsupported'}")

    if commands_run and "command_count" not in run_metrics:
        run_metrics["command_count"] = len(commands_run)
    record["files_read"] = _unique_strings(tuple(files_read))
    record["files_edited"] = _unique_strings(tuple(files_edited))
    if diff_hunks:
        record["diff_hunks"] = list(dict.fromkeys(diff_hunks))
    record["commands_run"] = commands_run
    record["test_output"] = test_output
    if run_metrics:
        record["run_metrics"] = run_metrics
    else:
        record.pop("run_metrics")
    if artifact_provenance:
        record["artifact_provenance"] = artifact_provenance
    if ledger_identity:
        record["ledger_identity"] = ledger_identity
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
        "claimed_task": _event_text_field(payload, ("claimed_task", "task"), "claimed_task"),
        "allowed_files": _string_list(payload.get("allowed_files")),
        "files_read": [],
        "files_edited": [],
        "commands_run": [],
        "test_output": "",
        "run_metrics": {},
        "final_claim": _event_text_field(payload, ("final_claim",), "final_claim"),
        "adapter_report": {
            "unsupported": [],
        },
    }
    files_read: list[str] = []
    files_edited: list[str] = []
    diff_hunks: list[str] = []
    commands_run: list[dict[str, object]] = []
    run_metrics: dict[str, object] = {}
    artifact_provenance: dict[str, object] = {}
    ledger_identity: dict[str, object] = {}
    unsupported: list[str] = []
    session_ids: set[str] = set()
    test_output = ""

    _add_event_session_id(session_ids, payload)
    _add_event_ledger_identity(ledger_identity, payload)

    for event_index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"OpenHands transcript event {event_index} must be an object")
        _add_event_session_id(session_ids, event)
        _add_event_ledger_identity(ledger_identity, event)
        event_path = f"events[{event_index}]"
        event_kind = _openhands_event_kind(event, event_path)
        if event_kind in {"task", "instruction"}:
            text = _openhands_event_text(event, "claimed_task")
            if text and not record["claimed_task"]:
                record["claimed_task"] = text
        elif event_kind in {"read", "read_file", "file_read"}:
            files_read.extend(_codex_tool_files(event))
        elif event_kind in {"edit", "write", "write_file", "apply_patch", "patch"}:
            files_edited.extend(_codex_tool_files(event))
            diff_hunks.extend(_event_diff_hunks(event))
        elif event_kind in {"command", "shell", "run", "execute", "run_command"}:
            command = _event_command_text(event, ("command", "cmd"))
            if not command:
                unsupported.append(f"{event_path}: missing command")
                continue
            item: dict[str, object] = {"command": command}
            exit_code = _event_exit_code(event)
            if exit_code is not None:
                item["exit_code"] = exit_code
            commands_run.append(item)
            metrics = _event_run_metrics(event)
            if metrics:
                _merge_run_metrics(run_metrics, metrics)
            provenance = _event_artifact_provenance(event)
            if provenance:
                _merge_artifact_provenance(artifact_provenance, provenance)
            output = _codex_command_output(event)
            if output:
                test_output = output
        elif event_kind in {"finish", "final", "final_claim", "message"}:
            text = _openhands_event_text(event, "final_claim")
            if text:
                record["final_claim"] = text
        else:
            unsupported.append(f"{event_path}: {event_kind or 'unsupported'}")

    if commands_run and "command_count" not in run_metrics:
        run_metrics["command_count"] = len(commands_run)
    record["files_read"] = _unique_strings(tuple(files_read))
    record["files_edited"] = _unique_strings(tuple(files_edited))
    if diff_hunks:
        record["diff_hunks"] = list(dict.fromkeys(diff_hunks))
    record["commands_run"] = commands_run
    record["test_output"] = test_output
    if run_metrics:
        record["run_metrics"] = run_metrics
    else:
        record.pop("run_metrics")
    if artifact_provenance:
        record["artifact_provenance"] = artifact_provenance
    if ledger_identity:
        record["ledger_identity"] = ledger_identity
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
        "claimed_task": _event_text_field(payload, ("claimed_task", "task", "issue"), "claimed_task"),
        "allowed_files": _string_list(payload.get("allowed_files")),
        "files_read": [],
        "files_edited": [],
        "commands_run": [],
        "test_output": "",
        "run_metrics": {},
        "final_claim": _event_text_field(payload, ("final_claim",), "final_claim"),
        "adapter_report": {
            "unsupported": [],
        },
    }
    files_read: list[str] = []
    files_edited: list[str] = []
    diff_hunks: list[str] = []
    commands_run: list[dict[str, object]] = []
    run_metrics: dict[str, object] = {}
    artifact_provenance: dict[str, object] = {}
    ledger_identity: dict[str, object] = {}
    unsupported: list[str] = []
    session_ids: set[str] = set()
    test_output = ""

    _add_event_session_id(session_ids, payload)
    _add_event_ledger_identity(ledger_identity, payload)

    for step_index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"SWE-agent transcript step {step_index} must be an object")
        _add_event_session_id(session_ids, step)
        _add_event_ledger_identity(ledger_identity, step)
        step_path = f"steps[{step_index}]"
        step_kind = _swe_agent_step_kind(step, step_path)
        if step_kind in {"task", "instruction", "issue"}:
            text = _openhands_event_text(step, "claimed_task")
            if text and not record["claimed_task"]:
                record["claimed_task"] = text
        elif step_kind in {"read", "read_file", "open"}:
            files_read.extend(_codex_tool_files(step))
        elif step_kind in {"edit", "write", "write_file", "apply_patch", "patch"}:
            files_edited.extend(_codex_tool_files(step))
            diff_hunks.extend(_event_diff_hunks(step))
        elif step_kind in {"command", "shell", "run", "run_command", "test"}:
            command = _event_command_text(step, ("command", "cmd"))
            if not command:
                unsupported.append(f"{step_path}: missing command")
                continue
            item: dict[str, object] = {"command": command}
            exit_code = _event_exit_code(step)
            if exit_code is not None:
                item["exit_code"] = exit_code
            commands_run.append(item)
            metrics = _event_run_metrics(step)
            if metrics:
                _merge_run_metrics(run_metrics, metrics)
            provenance = _event_artifact_provenance(step)
            if provenance:
                _merge_artifact_provenance(artifact_provenance, provenance)
            output = _codex_command_output(step)
            if output:
                test_output = output
        elif step_kind in {"finish", "final", "final_claim", "submit"}:
            text = _openhands_event_text(step, "final_claim")
            if text:
                record["final_claim"] = text
        else:
            unsupported.append(f"{step_path}: {step_kind or 'unsupported'}")

    if commands_run and "command_count" not in run_metrics:
        run_metrics["command_count"] = len(commands_run)
    record["files_read"] = _unique_strings(tuple(files_read))
    record["files_edited"] = _unique_strings(tuple(files_edited))
    if diff_hunks:
        record["diff_hunks"] = list(dict.fromkeys(diff_hunks))
    record["commands_run"] = commands_run
    record["test_output"] = test_output
    if run_metrics:
        record["run_metrics"] = run_metrics
    else:
        record.pop("run_metrics")
    if artifact_provenance:
        record["artifact_provenance"] = artifact_provenance
    if ledger_identity:
        record["ledger_identity"] = ledger_identity
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
    patch_shape = _report_patch_shape(report)
    artifact_provenance = _report_artifact_provenance(report)
    ledger_identity = _report_ledger_identity(report)
    verifier_tamper_risk = _report_verifier_tamper_risk(report)

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
        "## Patch Shape",
        "",
        f"- bucket: {patch_shape.get('bucket', 'unknown')}",
        f"- test_files: {', '.join(patch_shape.get('test_files', ())) or 'none'}",
        f"- source_files: {', '.join(patch_shape.get('source_files', ())) or 'none'}",
        f"- other_files: {', '.join(patch_shape.get('other_files', ())) or 'none'}",
        "",
        "## Artifact Provenance",
        "",
        f"- summary: {_artifact_provenance_summary(artifact_provenance)}",
        "",
        "## Ledger Identity",
        "",
        f"- summary: {_ledger_identity_summary(ledger_identity)}",
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
        f"- verifier_tamper_risk: {_verifier_tamper_risk_summary(verifier_tamper_risk)}",
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
        "patch_shape": _report_patch_shape(report),
        "artifact_provenance": _report_artifact_provenance(report),
        "ledger_identity": _report_ledger_identity(report),
        "verifier_tamper_risk": _report_verifier_tamper_risk(report),
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


def _diff_hunks(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("diff_hunks must be an array")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("diff_hunks entries must be strings")
        text = item.strip()
        if text:
            result.append(text)
    return result


def _event_diff_hunks(event: dict[str, object]) -> list[str]:
    hunks = _diff_hunks(event.get("diff_hunks"))
    for field in DIFF_HUNK_FIELDS:
        if field not in event:
            continue
        value = event.get(field)
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a string")
        text = value.strip()
        if text:
            hunks.append(text)
    return list(dict.fromkeys(hunks))


def _is_supplied_transcript_format(source_format: str) -> bool:
    return source_format.endswith("-transcript/v0.1")


def _unique_strings(values: tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


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
                if not _is_integer_exit_code(item["exit_code"]):
                    raise ValueError("commands_run exit_code must be an integer")
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
    for field in ("duration_seconds", "estimated_cost_usd", "actual_cost_usd", "cost_usd"):
        if field in metrics:
            metrics[field] = _non_negative_number(metrics[field], f"run_metrics.{field}")
    for field in ("command_count", "input_tokens", "output_tokens", "total_tokens"):
        if field in metrics:
            metrics[field] = _non_negative_integer(metrics[field], f"run_metrics.{field}")
    for field in ("provider", "model"):
        if field in metrics and not isinstance(metrics[field], str):
            raise ValueError(f"run_metrics.{field} must be a string")
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


def _ledger_identity(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("ledger_identity must be an object")
    known_fields = {*LEDGER_IDENTITY_TEXT_FIELDS, *LEDGER_IDENTITY_LIST_FIELDS}
    identity: dict[str, object] = {}
    for key, item in value.items():
        if key in known_fields:
            continue
        if not isinstance(item, str):
            raise ValueError(f"ledger_identity.{key} must be a string")
        text = item.strip()
        if text:
            identity[key] = text
    for field in LEDGER_IDENTITY_TEXT_FIELDS:
        if field not in value:
            continue
        field_value = value[field]
        if not isinstance(field_value, str):
            raise ValueError(f"ledger_identity.{field} must be a string")
        text = field_value.strip()
        if text:
            identity[field] = text
    for field in LEDGER_IDENTITY_LIST_FIELDS:
        items = _string_array(value.get(field), f"ledger_identity.{field}")
        if items:
            identity[field] = items
    return identity


def _string_array(value: object, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be an array of strings")
    return _unique_strings(tuple(value))


def _add_event_ledger_identity(target: dict[str, object], event: dict[str, object]) -> None:
    nested = _ledger_identity(event.get("ledger_identity"))
    if nested:
        _merge_ledger_identity(target, nested)
    identity: dict[str, object] = {}
    for field in LEDGER_IDENTITY_TEXT_FIELDS:
        text = _event_identity_text(event, field)
        if text:
            identity[field] = text
    invocation_ids: list[str] = []
    for field in TOOL_INVOCATION_ID_FIELDS:
        text = _event_identity_text(event, field)
        if text:
            invocation_ids.append(text)
    if invocation_ids:
        identity["tool_invocation_ids"] = _unique_strings(tuple(invocation_ids))
    for field in LEDGER_IDENTITY_LIST_FIELDS:
        items = _string_array(event.get(field), field)
        if not items:
            continue
        existing_items = identity.get(field)
        if isinstance(existing_items, list):
            items = _unique_strings(tuple([*existing_items, *items]))
        identity[field] = items
    if identity:
        _merge_ledger_identity(target, identity)


def _event_identity_text(event: dict[str, object], field: str) -> str:
    if field not in event:
        return ""
    value = event[field]
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value.strip()


def _add_event_session_id(session_ids: set[str], event: dict[str, object]) -> None:
    if "session_id" not in event:
        return
    value = event["session_id"]
    if not isinstance(value, str):
        raise ValueError("session_id must be a string")
    session_id = value.strip()
    if not session_id:
        return
    session_ids.add(session_id)
    if len(session_ids) > 1:
        raise ValueError("transcript session_id values must not be mixed")


def _artifact_provenance(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("artifact_provenance must be an object")
    provenance = dict(value)
    for field in ("eval_rule_version", "eval_rule_commit", "runner_version", "runner_commit"):
        if field in provenance and not isinstance(provenance[field], str):
            raise ValueError(f"artifact_provenance.{field} must be a string")
    missing = provenance.get("missing_provenance")
    if missing is not None:
        if not isinstance(missing, list) or not all(isinstance(item, str) for item in missing):
            raise ValueError("artifact_provenance.missing_provenance must be an array of strings")
        provenance["missing_provenance"] = [item for item in missing if item.strip()]
    for field in ("input_hashes", "output_hashes", "artifact_hashes"):
        hashes = provenance.get(field)
        if hashes is not None and not isinstance(hashes, dict):
            raise ValueError(f"artifact_provenance.{field} must be an object")
        if isinstance(hashes, dict) and not all(isinstance(item, str) for item in hashes.values()):
            raise ValueError(f"artifact_provenance.{field} values must be strings")
    return provenance


def _event_artifact_provenance(event: dict[str, object]) -> dict[str, object]:
    provenance = _artifact_provenance(event.get("artifact_provenance"))
    for field in ARTIFACT_PROVENANCE_FIELDS:
        if field in event:
            provenance[field] = event[field]
    return _artifact_provenance(provenance) if provenance else {}


def _merge_artifact_provenance(target: dict[str, object], source: dict[str, object]) -> None:
    for key, value in source.items():
        if key == "missing_provenance":
            existing = target.get(key)
            values: list[str] = []
            if isinstance(existing, list):
                values.extend(str(item) for item in existing)
            if isinstance(value, list):
                values.extend(str(item) for item in value)
            target[key] = list(dict.fromkeys(item for item in values if item.strip()))
        elif key in {"input_hashes", "output_hashes", "artifact_hashes"} and isinstance(value, dict):
            existing = target.get(key)
            merged = dict(existing) if isinstance(existing, dict) else {}
            for item_key, item_value in value.items():
                if item_key in merged and merged[item_key] != item_value:
                    raise ValueError(f"artifact_provenance.{key}.{item_key} values must not be mixed")
                merged[item_key] = item_value
            target[key] = merged
        else:
            if key in target and target[key] != value:
                raise ValueError(f"artifact_provenance.{key} values must not be mixed")
            target[key] = value


def _merge_ledger_identity(target: dict[str, object], source: dict[str, object]) -> None:
    for key, value in source.items():
        if key in LEDGER_IDENTITY_TEXT_FIELDS:
            existing = target.get(key)
            if existing and existing != value:
                raise ValueError(f"ledger_identity.{key} values must not be mixed")
            target[key] = value
        elif key in LEDGER_IDENTITY_LIST_FIELDS:
            existing = target.get(key)
            values: list[str] = []
            if isinstance(existing, list):
                values.extend(str(item) for item in existing)
            if isinstance(value, list):
                values.extend(str(item) for item in value)
            target[key] = _unique_strings(tuple(values))
        else:
            existing = target.get(key)
            if key in target and existing != value:
                raise ValueError(f"ledger_identity.{key} values must not be mixed")
            target[key] = value


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
        elif key in {
            "duration_seconds",
            "estimated_cost_usd",
            "actual_cost_usd",
            "cost_usd",
            "command_count",
            "input_tokens",
            "output_tokens",
            "total_tokens",
        }:
            existing = target.get(key)
            if isinstance(existing, (int, float)) and not isinstance(existing, bool):
                target[key] = existing + value
            else:
                target[key] = value
        else:
            if key in target and target[key] != value:
                raise ValueError(f"run_metrics.{key} values must not be mixed")
            target[key] = value


def _report_run_metrics(report: AgentAutopsyReport) -> dict[str, object]:
    item = next((evidence for evidence in report.evidence if evidence.name == "run_metrics"), None)
    if item is None:
        return {}
    metrics = item.data.get("run_metrics")
    return dict(metrics) if isinstance(metrics, dict) else {}


def _report_artifact_provenance(report: AgentAutopsyReport) -> dict[str, object]:
    item = next((evidence for evidence in report.evidence if evidence.name == "artifact_provenance"), None)
    if item is None:
        return {}
    provenance = item.data.get("artifact_provenance")
    return dict(provenance) if isinstance(provenance, dict) else {}


def _report_ledger_identity(report: AgentAutopsyReport) -> dict[str, object]:
    item = next((evidence for evidence in report.evidence if evidence.name == "ledger_identity"), None)
    if item is None:
        return {}
    identity = item.data.get("ledger_identity")
    return dict(identity) if isinstance(identity, dict) else {}


def _report_verifier_tamper_risk(report: AgentAutopsyReport) -> dict[str, object]:
    item = next((evidence for evidence in report.evidence if evidence.name == "verifier_tamper_risk"), None)
    if item is None:
        return _verifier_tamper_risk(_report_patch_shape(report).get("edited_files", []))
    risk = item.data.get("verifier_tamper_risk")
    return dict(risk) if isinstance(risk, dict) else _verifier_tamper_risk([])


def _report_patch_shape(report: AgentAutopsyReport) -> dict[str, object]:
    edited_files = [
        str(item.data.get("file"))
        for item in report.evidence
        if item.kind == "edit" and isinstance(item.data, dict) and item.data.get("file")
    ]
    return _patch_shape(edited_files)


def _patch_shape(files_edited: list[str]) -> dict[str, object]:
    unique_files = list(dict.fromkeys(item for item in files_edited if item))
    test_files = [item for item in unique_files if _is_test_file(item)]
    config_files = [item for item in unique_files if item not in test_files and _is_config_file(item)]
    source_files = [
        item for item in unique_files if item not in test_files and item not in config_files and _is_source_file(item)
    ]
    other_files = [
        item for item in unique_files if item not in test_files and item not in config_files and item not in source_files
    ]
    bucket = "no_edits"
    if test_files and source_files:
        bucket = "mixed_test_source"
    elif test_files and config_files:
        bucket = "test_and_config"
    elif test_files and other_files:
        bucket = "test_and_other"
    elif source_files and config_files:
        bucket = "source_and_config"
    elif source_files and other_files:
        bucket = "source_and_other"
    elif test_files:
        bucket = "test_only"
    elif source_files:
        bucket = "source_only"
    elif config_files:
        bucket = "config_only"
    elif other_files:
        bucket = "other_only"
    return {
        "bucket": bucket,
        "edited_files": unique_files,
        "test_files": test_files,
        "config_files": config_files,
        "source_files": source_files,
        "other_files": other_files,
    }


def _is_test_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1]
    parts = normalized.split("/")
    return (
        any(part in {"test", "tests", "testing"} for part in parts[:-1])
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
    )


def _is_source_file(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return normalized.endswith(SOURCE_FILE_SUFFIXES)


def _is_config_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1]
    lowered = normalized.lower()
    return name in CONFIG_FILE_NAMES or lowered.endswith(CONFIG_FILE_SUFFIXES)


def _verifier_tamper_risk(files_edited: object) -> dict[str, object]:
    if not isinstance(files_edited, list):
        files: list[str] = []
    else:
        files = [str(item) for item in files_edited if item]
    patch_shape = _patch_shape(files)
    source_files = patch_shape.get("source_files", [])
    modified_paths: list[str] = []
    reasons: dict[str, str] = {}
    for path in patch_shape.get("edited_files", []):
        item = str(path)
        normalized = "/" + item.replace("\\", "/").lower().lstrip("/")
        if _is_verifier_control_path(normalized):
            reason = "verifier_or_harness_path"
        elif _is_test_file(item) and not source_files:
            reason = "test_only_success_path"
        else:
            continue
        modified_paths.append(item)
        reasons[item] = reason
    return {
        "verifier_tamper_risk": bool(modified_paths),
        "modified_paths": modified_paths,
        "reasons": reasons,
    }


def _is_verifier_control_path(normalized_path: str) -> bool:
    name = normalized_path.rsplit("/", 1)[-1]
    if name in {"conftest.py", "pytest.ini", "tox.ini"}:
        return True
    return any(marker in normalized_path or name.startswith(marker) for marker in VERIFIER_TAMPER_PATH_MARKERS)


def _verifier_tamper_risk_summary(risk: dict[str, object]) -> str:
    paths = risk.get("modified_paths")
    if not risk.get("verifier_tamper_risk") or not isinstance(paths, list) or not paths:
        return "not detected"
    return "detected paths=" + ",".join(str(path) for path in paths)


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


def _artifact_provenance_summary(provenance: dict[str, object]) -> str:
    parts: list[str] = []
    for field in ARTIFACT_PROVENANCE_FIELDS:
        if field not in provenance:
            continue
        value = provenance[field]
        if field == "missing_provenance" and isinstance(value, list):
            value = ",".join(str(item) for item in value) or "none"
        elif field.endswith("_hashes") and isinstance(value, dict):
            value = ",".join(f"{key}={value[key]}" for key in sorted(value)) or "none"
        parts.append(f"{field}={value}")
    extra_fields = sorted(key for key in provenance if key not in ARTIFACT_PROVENANCE_FIELDS)
    parts.extend(f"{key}={provenance[key]}" for key in extra_fields)
    return ", ".join(parts) if parts else "none supplied"


def _ledger_identity_summary(identity: dict[str, object]) -> str:
    parts: list[str] = []
    for field in (*LEDGER_IDENTITY_TEXT_FIELDS, *LEDGER_IDENTITY_LIST_FIELDS):
        if field not in identity:
            continue
        value = identity[field]
        if isinstance(value, list):
            value = ",".join(str(item) for item in value) or "none"
        parts.append(f"{field}={value}")
    extra_fields = sorted(key for key in identity if key not in {*LEDGER_IDENTITY_TEXT_FIELDS, *LEDGER_IDENTITY_LIST_FIELDS})
    parts.extend(f"{key}={identity[key]}" for key in extra_fields)
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


def _message_role(message: dict[str, object], message_index: int) -> str:
    return _first_kind_text(((message, "role"),), f"messages[{message_index}]")


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
        block_type = _first_kind_text(((block, "type"),), f"messages[{message_index}].content[{block_index}]")
        if block_type not in {"tool_use", "server_tool_use"}:
            continue
        calls.append((f"messages[{message_index}].content[{block_index}]", block))
    return calls


def _codex_tool_payload(tool_call: dict[str, object], label: str) -> dict[str, object]:
    payload = dict(tool_call)
    for field in ("arguments", "input", "params"):
        if field not in tool_call:
            continue
        nested = tool_call.get(field)
        if nested is None:
            continue
        if isinstance(nested, dict):
            payload.update(nested)
        elif isinstance(nested, str):
            text = nested.strip()
            if not text:
                continue
            if not text.startswith("{"):
                raise ValueError(f"{label}.{field} must be an object or JSON object string")
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{label}.{field} must be a JSON object string") from exc
            if not isinstance(decoded, dict):
                raise ValueError(f"{label}.{field} must decode to a JSON object")
            payload.update(decoded)
        else:
            raise ValueError(f"{label}.{field} must be an object or JSON object string")
    return payload


def _codex_tool_kind(tool_call: dict[str, object], tool_payload: dict[str, object], label: str) -> str:
    block_type = _first_kind_text(((tool_payload, "type"), (tool_call, "type")), label)
    if block_type in {"tool_use", "server_tool_use"}:
        name = _first_kind_text(((tool_payload, "name"), (tool_call, "name")), label)
        if name:
            return name
    return _first_kind_text(
        (
            (tool_payload, "kind"),
            (tool_payload, "type"),
            (tool_payload, "tool"),
            (tool_payload, "name"),
            (tool_call, "kind"),
            (tool_call, "type"),
            (tool_call, "name"),
        ),
        label,
    )


def _first_kind_text(sources: tuple[tuple[dict[str, object], str], ...], label: str) -> str:
    for source, field in sources:
        if field not in source:
            continue
        value = source[field]
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"{label}.{field} must be a string")
        text = value.strip()
        if text:
            return text.lower().replace("-", "_")
    return ""


def _codex_tool_files(tool_payload: dict[str, object]) -> list[str]:
    if "files" in tool_payload:
        return _string_list(tool_payload.get("files"))
    if "paths" in tool_payload:
        return _string_list(tool_payload.get("paths"))
    for field in ("file", "path", "file_path"):
        if field not in tool_payload:
            continue
        value = tool_payload[field]
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a string")
        text = value.strip()
        return [text] if text else []
    return []


def _codex_content_text(value: object, label: str) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item_index, item in enumerate(value):
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                text_value = item["text"]
                if not isinstance(text_value, str):
                    raise ValueError(f"{label}[{item_index}].text must be a string")
                parts.append(text_value)
        return "\n".join(part.strip() for part in parts if part.strip())
    return ""


def _event_command_text(event: dict[str, object], fields: tuple[str, ...]) -> str:
    for field in fields:
        if field not in event:
            continue
        value = event[field]
        if not isinstance(value, str):
            raise ValueError(f"command {field} must be a string")
        text = value.strip()
        if text:
            return text
    return ""


def _event_text_field(event: dict[str, object], fields: tuple[str, ...], label: str) -> str:
    for field in fields:
        if field not in event:
            continue
        value = event[field]
        if not isinstance(value, str):
            raise ValueError(f"{label} {field} must be a string")
        text = value.strip()
        if text:
            return text
    return ""


def _codex_command_output(tool_payload: dict[str, object]) -> str:
    parts: list[str] = []
    for field in ("output", "stdout", "stderr", "summary", "observation"):
        if field not in tool_payload:
            continue
        value = tool_payload[field]
        if not isinstance(value, str):
            raise ValueError(f"command output {field} must be a string")
        if value.strip():
            parts.append(value.strip())
    return "\n".join(parts)


def _openhands_event_kind(event: dict[str, object], label: str) -> str:
    return _first_kind_text(
        ((event, "kind"), (event, "type"), (event, "action"), (event, "operation")),
        label,
    )


def _openhands_event_text(event: dict[str, object], label: str) -> str:
    return _event_text_field(event, ("message", "content", "text", "instruction", "final_claim"), label)


def _swe_agent_step_kind(step: dict[str, object], label: str) -> str:
    return _first_kind_text(
        ((step, "kind"), (step, "type"), (step, "action"), (step, "operation"), (step, "role")),
        label,
    )


def _is_integer_exit_code(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _non_negative_integer(value: object, field_name: str) -> int:
    if not _is_integer_exit_code(value):
        raise ValueError(f"{field_name} must be an integer")
    result = int(value)
    if result < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return result


def _non_negative_number(value: object, field_name: str) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a number")
    if not math.isfinite(float(value)):
        raise ValueError(f"{field_name} must be finite")
    if float(value) < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


def _event_exit_code(event: dict[str, object]) -> int | None:
    if "exit_code" not in event:
        return None
    value = event.get("exit_code")
    if not _is_integer_exit_code(value):
        raise ValueError("exit_code must be an integer")
    return int(value)


def _test_output_status(test_output: object, commands_run: object) -> tuple[str, str]:
    exit_codes = []
    if isinstance(commands_run, list):
        for item in commands_run:
            if (
                isinstance(item, dict)
                and _is_integer_exit_code(item.get("exit_code"))
                and _looks_like_validation_command(str(item.get("command") or ""))
            ):
                exit_codes.append(int(item["exit_code"]))
    if test_output is not None and not isinstance(test_output, (str, dict)):
        raise ValueError("test_output must be a string or object")
    if any(code != 0 for code in exit_codes):
        return "failed", "command exit_code evidence: " + ", ".join(str(code) for code in exit_codes)
    if isinstance(test_output, dict):
        if "status" in test_output and not isinstance(test_output["status"], str):
            raise ValueError("test_output status must be a string")
        for field in ("output", "summary"):
            if field in test_output and not isinstance(test_output[field], str):
                raise ValueError(f"test_output {field} must be a string")
        status = str(test_output.get("status") or "").lower()
        text_parts = [
            str(test_output[field]).strip()
            for field in ("output", "summary")
            if isinstance(test_output.get(field), str) and str(test_output[field]).strip()
        ]
        text = "\n".join(dict.fromkeys(text_parts))
        if "exit_code" in test_output and not _is_integer_exit_code(test_output["exit_code"]):
            raise ValueError("test_output exit_code must be an integer")
        if _is_integer_exit_code(test_output.get("exit_code")) and int(test_output["exit_code"]) != 0:
            return "failed", text or f"test exit_code: {test_output['exit_code']}"
        for text_part in text_parts:
            text_status, text_summary = _test_output_status(text_part, commands_run)
            if text_status == "failed":
                return text_status, text_summary
        if status in {"passed", "pass", "success"}:
            return "passed", text or "test output status: passed"
        if status in {"failed", "fail", "failure"}:
            return "failed", text or "test output status: failed"
        if _is_integer_exit_code(test_output.get("exit_code")):
            return ("passed" if int(test_output["exit_code"]) == 0 else "failed", text or f"test exit_code: {test_output['exit_code']}")
        if text:
            return _test_output_status(text, commands_run)
    if isinstance(test_output, str) and test_output.strip():
        text = test_output.strip()
        lowered = text.lower()
        failed_count = (
            re.search(r"\b[1-9]\d*\s+failed\b", lowered)
            or re.search(r"\b[1-9]\d*\s+failures?\b", lowered)
            or re.search(r"\bfailures?=\s*[1-9]\d*\b", lowered)
            or re.search(r"(?m)^failed\s+\S+", lowered)
        )
        error_count = re.search(r"\b[1-9]\d*\s+errors?\b", lowered) or re.search(r"\berrors?=\s*[1-9]\d*\b", lowered)
        if failed_count or error_count:
            return "failed", text
        if re.search(r"\b\d+\s+passed\b", lowered) and not failed_count and not error_count:
            return "passed", text
        return "unknown", text
    if exit_codes:
        return ("passed" if all(code == 0 for code in exit_codes) else "failed", "command exit_code evidence: " + ", ".join(str(code) for code in exit_codes))
    return "missing", ""


def _looks_like_validation_command(command: str) -> bool:
    lowered = f" {command.lower()} "
    patterns = (
        r"\bpytest\b",
        r"\bunittest\b",
        r"\btox\b",
        r"\bnox\b",
        r"\bcoverage\b",
        r"\bgo\s+test\b",
        r"\bcargo\s+test\b",
        r"\bswift\s+test\b",
        r"\bzig\s+build\s+test\b",
        r"\bctest\b",
        r"\bbats\b",
        r"\bjest\b",
        r"\bvitest\b",
        r"\bplaywright\s+test\b",
        r"\bnpm\s+(?:run\s+)?test\b",
        r"\bpnpm\s+(?:run\s+)?test\b",
        r"\byarn\s+(?:run\s+)?test\b",
        r"\bmake\s+test\b",
        r"\bmvn\s+test\b",
        r"\bgradle\s+test\b",
        r"\bgradlew\s+test\b",
    )
    return any(re.search(pattern, lowered) for pattern in patterns)


def _has_validation_command(commands_run: object) -> bool:
    if not isinstance(commands_run, list):
        return False
    for item in commands_run:
        if isinstance(item, str) and _looks_like_validation_command(item):
            return True
        if isinstance(item, dict) and _looks_like_validation_command(str(item.get("command") or "")):
            return True
    return False


def _looks_like_success_claim(text: str) -> bool:
    lowered = text.lower()
    success_markers = ("fixed", "complete", "completed", "done", "verified", "passed", "success")
    return any(marker in lowered for marker in success_markers)


def _looks_like_patch_task(text: str) -> bool:
    lowered = text.lower()
    word_patterns = (
        r"\bfix(?:e[ds])?\b",
        r"\brepair(?:ed)?\b",
        r"\bpatch(?:ed)?\b",
        r"\bedit(?:ed)?\b",
        r"\badd(?:ed)?\s+regression\b",
        r"\bcode\s+change\b",
    )
    if any(re.search(pattern, lowered) for pattern in word_patterns):
        return True
    return any(marker in text for marker in ("修复", "编辑", "修改", "实现"))
