from __future__ import annotations

import hashlib
import json
import shlex
from pathlib import Path
from typing import Any


PRODUCT_LOG_SCHEMA_VERSION = "openmako-product-log/v0.1"
PRODUCT_LOG_SOURCE_FORMAT = "openmako-product-log/v0.1"
PRODUCT_LOG_NOT_PROOF = (
    "live autonomy",
    "broad unknown-repository repair",
    "external benchmark standing",
    "external review",
    "endorsement",
    "stars",
    "reposts",
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


def build_audit_record_from_product_log(log_path: str | Path) -> dict[str, Any]:
    """Convert a native OpenMako product-log packet into an Evidence Court record."""

    path = Path(log_path).expanduser().resolve(strict=False)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("product log must be a JSON object")
    if payload.get("schema_version") != PRODUCT_LOG_SCHEMA_VERSION:
        raise ValueError(f"product log schema_version must be {PRODUCT_LOG_SCHEMA_VERSION}")

    events = payload.get("events")
    if not isinstance(events, list) or not events:
        raise ValueError("product log events must be a non-empty array")

    claimed_task = _required_string(payload, "claimed_task")
    final_claim = _required_string(payload, "final_claim")
    source_agent = _required_string(payload, "source_agent")
    allowed_files = _string_array(payload.get("allowed_files"), "allowed_files")

    files_read: list[str] = []
    files_edited: list[str] = []
    diff_hunks: list[str] = []
    commands_run: list[dict[str, Any]] = []
    command_log: list[dict[str, Any]] = []
    evidence_timeline: list[dict[str, Any]] = []
    tool_invocation_ids: list[str] = []
    diagnosis_texts: list[str] = []
    before_failure_indices: list[int] = []
    after_test_indices: list[int] = []
    diagnosis_indices: list[int] = []
    edit_indices: list[int] = []
    after_test_output = ""

    for index, raw_event in enumerate(events):
        if not isinstance(raw_event, dict):
            raise ValueError(f"events[{index}] must be an object")
        event_type = _required_kind(raw_event, index)
        invocation_id = _optional_string(raw_event, "tool_invocation_id") or _optional_string(raw_event, "invocation_id")
        if invocation_id:
            tool_invocation_ids.append(invocation_id)

        if event_type == "read":
            files_read.extend(_event_files(raw_event, f"events[{index}]"))
            continue
        if event_type == "diagnosis":
            diagnosis_texts.append(_required_string(raw_event, "text", label=f"events[{index}].text"))
            diagnosis_indices.append(index)
            continue
        if event_type == "edit":
            edited = _event_files(raw_event, f"events[{index}]")
            if not edited:
                raise ValueError(f"events[{index}] edit must include file or files")
            hunks = _event_diff_hunks(raw_event, f"events[{index}]")
            if not hunks:
                raise ValueError(f"events[{index}] edit must include diff content")
            files_edited.extend(edited)
            diff_hunks.extend(hunks)
            evidence_timeline.append({"kind": "edit", "files": _unique_strings(edited)})
            edit_indices.append(index)
            continue
        if event_type == "command":
            command = _event_command(raw_event, f"events[{index}]")
            exit_code = _integer(raw_event.get("exit_code"), f"events[{index}].exit_code")
            phase = _required_string(raw_event, "phase", label=f"events[{index}].phase")
            output = _required_command_output(raw_event, f"events[{index}]")
            item = {"phase": phase, "command": command, "exit_code": exit_code, "output": output}
            command_log.append(item)
            evidence_timeline.append({"kind": "command", "phase": phase, "command": command, "exit_code": exit_code})
            if phase == "before_failure":
                if exit_code == 0:
                    raise ValueError("before_failure command must have a nonzero exit_code")
                before_failure_indices.append(index)
            elif phase == "after_test":
                if exit_code != 0:
                    raise ValueError("after_test command must have exit_code 0")
                commands_run.append({"command": command, "exit_code": exit_code})
                after_test_indices.append(index)
                after_test_output = output
            else:
                raise ValueError(f"events[{index}].phase must be before_failure or after_test")
            continue
        raise ValueError(f"events[{index}].type is unsupported: {event_type}")

    _validate_failure_to_fix_contract(
        before_failure_indices=before_failure_indices,
        diagnosis_indices=diagnosis_indices,
        edit_indices=edit_indices,
        after_test_indices=after_test_indices,
        files_edited=files_edited,
        diff_hunks=diff_hunks,
    )

    log_hash = _sha256_file(path)
    record: dict[str, Any] = {
        "source_agent": source_agent,
        "source_format": PRODUCT_LOG_SOURCE_FORMAT,
        "claimed_task": claimed_task,
        "allowed_files": allowed_files,
        "files_read": _unique_strings(files_read),
        "files_edited": _unique_strings(files_edited),
        "diff_hunks": _unique_strings(diff_hunks),
        "commands_run": commands_run,
        "test_output": after_test_output,
        "final_claim": final_claim,
        "evidence_timeline": evidence_timeline,
        "run_metrics": {
            "command_count": len(command_log),
            "post_edit_validation_command_count": len(commands_run),
            "missing_telemetry": ["duration_seconds", "model", "cost_usd"],
        },
        "artifact_provenance": {
            "input_hashes": {path.name: log_hash},
            "runner_version": PRODUCT_LOG_SCHEMA_VERSION,
            "missing_provenance": ["native runner signature", "external reviewer identity"],
        },
        "ledger_identity": _ledger_identity(payload, tool_invocation_ids),
        "agent_risk_ledger": {
            "live_control": False,
            "self_improved": False,
            "tool_call_evidence": _unique_strings(tool_invocation_ids),
        },
        "adapter_report": {"unsupported": []},
        "product_log_boundary": {
            "schema_version": PRODUCT_LOG_SCHEMA_VERSION,
            "native_product_log_ingested": True,
            "before_failure": _select_command_log(command_log, "before_failure"),
            "after_test": _select_command_log(command_log, "after_test"),
            "agent_diagnosis": diagnosis_texts,
            "command_log": command_log,
            "not_proof": list(PRODUCT_LOG_NOT_PROOF),
        },
    }
    return record


def _validate_failure_to_fix_contract(
    *,
    before_failure_indices: list[int],
    diagnosis_indices: list[int],
    edit_indices: list[int],
    after_test_indices: list[int],
    files_edited: list[str],
    diff_hunks: list[str],
) -> None:
    if len(before_failure_indices) != 1:
        raise ValueError("product log must include exactly one before_failure command")
    if not diagnosis_indices:
        raise ValueError("product log must include an agent diagnosis event")
    if not edit_indices:
        raise ValueError("product log must include at least one edit event")
    if len(after_test_indices) != 1:
        raise ValueError("product log must include exactly one after_test command")
    if before_failure_indices[0] > edit_indices[0]:
        raise ValueError("before_failure command must occur before the first edit")
    if not any(before_failure_indices[0] < index < after_test_indices[0] for index in diagnosis_indices):
        raise ValueError("agent diagnosis must occur between before_failure and after_test")
    if after_test_indices[0] < max(edit_indices):
        raise ValueError("after_test command must occur after the final edit")

    source_edits = [path for path in _unique_strings(files_edited) if _is_source_file(path)]
    if not source_edits:
        raise ValueError("product log must include at least one source-file edit")
    diff_paths = _diff_hunk_file_paths(diff_hunks)
    missing_diff_paths = [path for path in source_edits if _normalize_diff_path(path) not in diff_paths]
    if missing_diff_paths:
        raise ValueError(
            "product log edit diff must cover every edited source file: "
            + ", ".join(missing_diff_paths)
        )


def _ledger_identity(payload: dict[str, Any], invocation_ids: list[str]) -> dict[str, Any]:
    identity: dict[str, Any] = {}
    for field in ("run_id", "session_id", "task_id"):
        value = _optional_string(payload, field)
        if value:
            identity[field] = value
    if invocation_ids:
        identity["tool_invocation_ids"] = _unique_strings(invocation_ids)
    return identity


def _select_command_log(command_log: list[dict[str, Any]], phase: str) -> dict[str, Any]:
    for item in command_log:
        if item.get("phase") == phase:
            return item
    return {}


def _required_kind(event: dict[str, Any], index: int) -> str:
    for field in ("type", "kind", "event"):
        value = event.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ValueError(f"events[{index}].type must be a non-empty string")


def _event_files(event: dict[str, Any], label: str) -> list[str]:
    values: list[str] = []
    path = _optional_string(event, "path") or _optional_string(event, "file")
    if path:
        values.append(path)
    values.extend(_string_array(event.get("files"), f"{label}.files"))
    for item in values:
        if Path(item).is_absolute() or ".." in Path(item).parts:
            raise ValueError(f"{label}.files must be repository-relative paths")
    return _unique_strings(values)


def _event_diff_hunks(event: dict[str, Any], label: str) -> list[str]:
    hunks: list[str] = []
    for field in ("diff", "patch", "unified_diff"):
        value = event.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"{label}.{field} must be a string")
        if value.strip():
            hunks.append(value.strip())
    raw_hunks = event.get("diff_hunks")
    if raw_hunks is not None:
        if not isinstance(raw_hunks, list) or not all(isinstance(item, str) for item in raw_hunks):
            raise ValueError(f"{label}.diff_hunks must be an array of strings")
        hunks.extend(item.strip() for item in raw_hunks if item.strip())
    return _unique_strings(hunks)


def _event_command(event: dict[str, Any], label: str) -> str:
    value = event.get("command")
    if isinstance(value, str):
        command = value.strip()
    elif isinstance(value, list) and value and all(isinstance(item, str) and item for item in value):
        command = shlex.join(value)
    else:
        raise ValueError(f"{label}.command must be a string or a non-empty string array")
    if not command:
        raise ValueError(f"{label}.command must be non-empty")
    return command


def _required_command_output(event: dict[str, Any], label: str) -> str:
    for field in ("output", "stdout", "stderr", "summary"):
        value = event.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ValueError(f"{label} command must include output, stdout, stderr, or summary text")


def _required_string(payload: dict[str, Any], field: str, *, label: str | None = None) -> str:
    value = payload.get(field)
    name = label or field
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _string_array(value: object, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{label} must be an array of non-empty strings")
    return _unique_strings([item.strip() for item in value])


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    return value


def _unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = value.strip()
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _is_source_file(path: str) -> bool:
    normalized = _normalize_diff_path(path)
    return normalized.endswith(SOURCE_FILE_SUFFIXES) and "/test" not in normalized and not normalized.startswith("tests/")


def _diff_hunk_file_paths(diff_hunks: list[str]) -> set[str]:
    paths: set[str] = set()
    for hunk in diff_hunks:
        for raw_line in hunk.splitlines():
            line = raw_line.strip()
            if line.startswith("diff --git "):
                for part in line.split()[2:4]:
                    normalized = _normalize_diff_path(part)
                    if normalized:
                        paths.add(normalized)
                continue
            if line.startswith(("--- ", "+++ ")):
                normalized = _normalize_diff_path(line[4:].strip().split("\t", 1)[0].split(" ", 1)[0])
                if normalized:
                    paths.add(normalized)
    return paths


def _normalize_diff_path(path: str) -> str:
    normalized = path.strip().strip('"').replace("\\", "/")
    if not normalized or normalized == "/dev/null":
        return ""
    if normalized.startswith(("a/", "b/")):
        normalized = normalized[2:]
    return normalized.lstrip("./")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()
