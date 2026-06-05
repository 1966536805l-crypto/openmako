from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


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


def build_audit_record_from_codex_transcript(transcript_path: str | Path) -> dict[str, object]:
    path = Path(transcript_path).expanduser().resolve(strict=False)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("codex transcript must be a JSON object")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("codex transcript must include an items array")

    task = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    record: dict[str, object] = {
        "source_agent": str(payload.get("source_agent") or payload.get("source") or "codex"),
        "claimed_task": _first_text(payload.get("claimed_task"), task.get("claimed_task"), task.get("prompt")),
        "allowed_files": _file_list(payload.get("allowed_files") or task.get("allowed_files")),
        "files_read": [],
        "files_edited": [],
        "commands_run": [],
        "test_output": "",
        "final_claim": "",
    }
    files_read: list[str] = []
    files_edited: list[str] = []
    commands_run: list[dict[str, object]] = []
    run_metrics: dict[str, object] = {}
    unsupported_fields: list[str] = []

    for index, raw_item in enumerate(items):
        if not isinstance(raw_item, dict):
            raise ValueError(f"codex transcript item {index} must be an object")
        item = dict(raw_item)
        kind = str(item.get("type") or item.get("kind") or "").strip().lower()
        name = str(item.get("name") or item.get("tool") or "").strip().lower()
        input_payload = item.get("input") if isinstance(item.get("input"), dict) else {}
        output = str(item.get("output") or item.get("result") or "").strip()

        _collect_unsupported_fields(item, index, unsupported_fields)
        if kind in {"message", "assistant_message"} and str(item.get("role") or "").lower() == "assistant":
            final_claim = _first_text(item.get("text"), item.get("content"))
            if final_claim:
                record["final_claim"] = final_claim
            continue
        if kind in {"read", "file_read"} or name in {"read_file", "read_files", "view_file"}:
            files_read.extend(_file_list(item.get("files") or item.get("file") or item.get("path") or input_payload))
            continue
        if kind in {"edit", "file_edit", "patch"} or name in {"apply_patch", "write_file", "edit_file"}:
            files_edited.extend(_file_list(item.get("files") or item.get("file") or item.get("path") or input_payload))
            continue
        if kind in {"command", "shell"} or name in {"shell", "exec_command", "run_command"}:
            command = _first_text(item.get("command"), item.get("cmd"), input_payload.get("command"), input_payload.get("cmd"))
            if command:
                command_item: dict[str, object] = {"command": command}
                if isinstance(item.get("exit_code"), int):
                    command_item["exit_code"] = item["exit_code"]
                elif isinstance(input_payload.get("exit_code"), int):
                    command_item["exit_code"] = input_payload["exit_code"]
                commands_run.append(command_item)
            if output:
                record["test_output"] = output
            _merge_run_metrics(run_metrics, _extract_metrics(item))
            continue
        if kind or name:
            unsupported_fields.append(f"items[{index}].type:{kind or name}")

    record["files_read"] = _dedupe(files_read)
    record["files_edited"] = _dedupe(files_edited)
    record["commands_run"] = commands_run
    if run_metrics:
        if commands_run and "command_count" not in run_metrics:
            run_metrics["command_count"] = len(commands_run)
        record["run_metrics"] = run_metrics
    record["adapter_report"] = {
        "source_format": "codex-transcript/v0.1",
        "unsupported_fields": _dedupe(unsupported_fields),
        "missing_evidence": _missing_evidence(record),
        "claim_boundary": "import-and-audit supplied transcript records only; not live Codex control",
    }
    return record


def build_audit_record_from_openhands_transcript(transcript_path: str | Path) -> dict[str, object]:
    path = Path(transcript_path).expanduser().resolve(strict=False)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("openhands transcript must be a JSON object")
    events = payload.get("events") or payload.get("history") or payload.get("steps")
    if not isinstance(events, list):
        raise ValueError("openhands transcript must include an events, history, or steps array")

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    record: dict[str, object] = {
        "source_agent": str(payload.get("source_agent") or payload.get("source") or "openhands"),
        "claimed_task": _first_text(payload.get("claimed_task"), payload.get("goal"), metadata.get("task"), metadata.get("goal")),
        "allowed_files": _file_list(payload.get("allowed_files") or metadata.get("allowed_files")),
        "files_read": [],
        "files_edited": [],
        "commands_run": [],
        "test_output": "",
        "final_claim": "",
    }
    files_read: list[str] = []
    files_edited: list[str] = []
    commands_run: list[dict[str, object]] = []
    run_metrics: dict[str, object] = {}
    unsupported_fields: list[str] = []

    for index, raw_event in enumerate(events):
        if not isinstance(raw_event, dict):
            raise ValueError(f"openhands transcript event {index} must be an object")
        event = dict(raw_event)
        kind = str(event.get("event") or event.get("type") or event.get("action") or "").strip().lower()
        _collect_unsupported_fields(event, index, unsupported_fields, prefix="events")

        if kind in {"message", "assistant_message", "agent_message", "final_response"}:
            final_claim = _first_text(event.get("content"), event.get("message"), event.get("text"))
            if final_claim:
                record["final_claim"] = final_claim
            continue
        if kind in {"read", "file_read", "view_file", "read_file"}:
            files_read.extend(_file_list(event.get("files") or event.get("file") or event.get("path")))
            continue
        if kind in {"edit", "file_edit", "write_file", "apply_patch", "patch"}:
            files_edited.extend(_file_list(event.get("files") or event.get("file") or event.get("path")))
            continue
        if kind in {"command", "shell", "run_command", "execute"}:
            command = _first_text(event.get("command"), event.get("cmd"), event.get("args"))
            if command:
                command_item: dict[str, object] = {"command": command}
                if isinstance(event.get("exit_code"), int):
                    command_item["exit_code"] = event["exit_code"]
                commands_run.append(command_item)
            output = _first_text(event.get("stdout"), event.get("output"), event.get("summary"), event.get("stderr"))
            if output:
                record["test_output"] = output
            _merge_run_metrics(run_metrics, _extract_metrics(event))
            continue
        if kind:
            unsupported_fields.append(f"events[{index}].type:{kind}")

    record["files_read"] = _dedupe(files_read)
    record["files_edited"] = _dedupe(files_edited)
    record["commands_run"] = commands_run
    if run_metrics:
        if commands_run and "command_count" not in run_metrics:
            run_metrics["command_count"] = len(commands_run)
        record["run_metrics"] = run_metrics
    record["adapter_report"] = {
        "source_format": "openhands-transcript/v0.1",
        "unsupported_fields": _dedupe(unsupported_fields),
        "missing_evidence": _missing_evidence(record),
        "claim_boundary": "import-and-audit supplied transcript records only; not live OpenHands control",
    }
    return record


def build_audit_record_from_swe_agent_transcript(transcript_path: str | Path) -> dict[str, object]:
    path = Path(transcript_path).expanduser().resolve(strict=False)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("swe-agent transcript must be a JSON object")
    steps = payload.get("trajectory") or payload.get("steps") or payload.get("history")
    if not isinstance(steps, list):
        raise ValueError("swe-agent transcript must include a trajectory, steps, or history array")

    issue = payload.get("issue") if isinstance(payload.get("issue"), dict) else {}
    record: dict[str, object] = {
        "source_agent": str(payload.get("source_agent") or payload.get("source") or "swe-agent"),
        "claimed_task": _first_text(payload.get("claimed_task"), payload.get("problem_statement"), issue.get("title"), issue.get("body")),
        "allowed_files": _file_list(payload.get("allowed_files") or issue.get("allowed_files")),
        "files_read": [],
        "files_edited": [],
        "commands_run": [],
        "test_output": "",
        "final_claim": "",
    }
    files_read: list[str] = []
    files_edited: list[str] = []
    commands_run: list[dict[str, object]] = []
    run_metrics: dict[str, object] = {}
    unsupported_fields: list[str] = []

    for index, raw_step in enumerate(steps):
        if not isinstance(raw_step, dict):
            raise ValueError(f"swe-agent transcript step {index} must be an object")
        step = dict(raw_step)
        kind = str(step.get("type") or step.get("action") or step.get("event") or "").strip().lower()
        tool = str(step.get("tool") or step.get("name") or "").strip().lower()
        observation = step.get("observation") if isinstance(step.get("observation"), dict) else {}
        _collect_unsupported_fields(step, index, unsupported_fields, prefix="trajectory")

        if kind in {"message", "assistant_message", "final_response", "submit"}:
            final_claim = _first_text(step.get("content"), step.get("message"), step.get("text"), step.get("answer"))
            if final_claim:
                record["final_claim"] = final_claim
            continue
        if kind in {"read", "file_read", "open_file"} or tool in {"open_file", "read_file", "view_file"}:
            files_read.extend(_file_list(step.get("files") or step.get("file") or step.get("path") or observation))
            continue
        if kind in {"edit", "file_edit", "patch", "apply_patch"} or tool in {"edit", "apply_patch", "write_file"}:
            files_edited.extend(_file_list(step.get("files") or step.get("file") or step.get("path") or observation))
            continue
        if kind in {"command", "shell", "run_tests"} or tool in {"bash", "shell", "run_tests", "exec"}:
            command = _first_text(step.get("command"), step.get("cmd"), step.get("args"))
            if command:
                command_item: dict[str, object] = {"command": command}
                exit_code = step.get("exit_code")
                if not isinstance(exit_code, int):
                    exit_code = observation.get("exit_code")
                if isinstance(exit_code, int):
                    command_item["exit_code"] = exit_code
                commands_run.append(command_item)
            output = _first_text(step.get("output"), step.get("stdout"), step.get("stderr"), observation.get("output"), observation.get("stdout"))
            if output:
                record["test_output"] = output
            _merge_run_metrics(run_metrics, _extract_metrics(step))
            continue
        if kind or tool:
            unsupported_fields.append(f"trajectory[{index}].type:{kind or tool}")

    record["files_read"] = _dedupe(files_read)
    record["files_edited"] = _dedupe(files_edited)
    record["commands_run"] = commands_run
    if run_metrics:
        if commands_run and "command_count" not in run_metrics:
            run_metrics["command_count"] = len(commands_run)
        record["run_metrics"] = run_metrics
    record["adapter_report"] = {
        "source_format": "swe-agent-transcript/v0.1",
        "unsupported_fields": _dedupe(unsupported_fields),
        "missing_evidence": _missing_evidence(record),
        "claim_boundary": "import-and-audit supplied transcript records only; not live SWE-agent control",
    }
    return record


def build_audit_record_from_claude_transcript(transcript_path: str | Path) -> dict[str, object]:
    path = Path(transcript_path).expanduser().resolve(strict=False)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("claude transcript must be a JSON object")
    messages = payload.get("messages") or payload.get("turns") or payload.get("events")
    if not isinstance(messages, list):
        raise ValueError("claude transcript must include a messages, turns, or events array")

    task = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    record: dict[str, object] = {
        "source_agent": str(payload.get("source_agent") or payload.get("source") or "claude"),
        "claimed_task": _first_text(payload.get("claimed_task"), task.get("claimed_task"), task.get("prompt")),
        "allowed_files": _file_list(payload.get("allowed_files") or task.get("allowed_files")),
        "files_read": [],
        "files_edited": [],
        "commands_run": [],
        "test_output": "",
        "final_claim": "",
    }
    files_read: list[str] = []
    files_edited: list[str] = []
    commands_run: list[dict[str, object]] = []
    run_metrics: dict[str, object] = {}
    unsupported_fields: list[str] = []
    pending_command_index: int | None = None

    for message_index, raw_message in enumerate(messages):
        if not isinstance(raw_message, dict):
            raise ValueError(f"claude transcript message {message_index} must be an object")
        message = dict(raw_message)
        role = str(message.get("role") or "").strip().lower()
        content = message.get("content")
        if role == "assistant" and isinstance(content, str) and content.strip():
            record["final_claim"] = content.strip()
        _merge_run_metrics(run_metrics, _extract_metrics(message))

        blocks = content if isinstance(content, list) else []
        for block_index, raw_block in enumerate(blocks):
            if not isinstance(raw_block, dict):
                continue
            block = dict(raw_block)
            block_type = str(block.get("type") or "").strip().lower()
            name = str(block.get("name") or block.get("tool_name") or "").strip().lower()
            input_payload = block.get("input") if isinstance(block.get("input"), dict) else {}
            _collect_unsupported_fields(block, block_index, unsupported_fields, prefix=f"messages[{message_index}].content")
            _merge_run_metrics(run_metrics, _extract_metrics(block))

            if block_type == "tool_use":
                if name in {"read", "read_file", "view", "view_file"}:
                    files_read.extend(_file_list(block.get("files") or block.get("file") or block.get("path") or input_payload))
                    continue
                if name in {"edit", "write", "write_file", "apply_patch", "multiedit"}:
                    files_edited.extend(_file_list(block.get("files") or block.get("file") or block.get("path") or input_payload))
                    continue
                if name in {"bash", "shell", "run_command", "exec_command"}:
                    command = _first_text(block.get("command"), input_payload.get("command"), input_payload.get("cmd"))
                    if command:
                        command_item: dict[str, object] = {"command": command}
                        if isinstance(block.get("exit_code"), int):
                            command_item["exit_code"] = block["exit_code"]
                        commands_run.append(command_item)
                        pending_command_index = len(commands_run) - 1
                    output = _first_text(block.get("output"), block.get("stdout"), block.get("stderr"))
                    if output:
                        record["test_output"] = output
                    continue
                unsupported_fields.append(f"messages[{message_index}].content[{block_index}].tool:{name or 'missing'}")
                continue

            if block_type == "tool_result":
                output = _first_text(block.get("content"), block.get("output"), block.get("stdout"), block.get("stderr"))
                if output:
                    record["test_output"] = output
                if pending_command_index is not None and isinstance(block.get("exit_code"), int):
                    commands_run[pending_command_index]["exit_code"] = block["exit_code"]
                continue

    record["files_read"] = _dedupe(files_read)
    record["files_edited"] = _dedupe(files_edited)
    record["commands_run"] = commands_run
    if run_metrics:
        if commands_run and "command_count" not in run_metrics:
            run_metrics["command_count"] = len(commands_run)
        record["run_metrics"] = run_metrics
    record["adapter_report"] = {
        "source_format": "claude-transcript/v0.1",
        "unsupported_fields": _dedupe(unsupported_fields),
        "missing_evidence": _missing_evidence(record),
        "claim_boundary": "import-and-audit supplied transcript records only; not live Claude control",
    }
    return record


def _first_text(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _file_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Mapping):
        for key in ("files", "paths"):
            if key in value:
                return _file_list(value[key])
        for key in ("file", "path", "file_path"):
            if isinstance(value.get(key), str):
                return _file_list(value[key])
        return []
    if isinstance(value, list):
        files: list[str] = []
        for item in value:
            files.extend(_file_list(item))
        return files
    return []


def _extract_metrics(item: Mapping[str, object]) -> dict[str, object]:
    metrics: dict[str, object] = {}
    for source_key in ("run_metrics", "metrics"):
        source = item.get(source_key)
        if isinstance(source, dict):
            metrics.update(source)
    for field in RUN_METRIC_FIELDS:
        if field in item:
            metrics[field] = item[field]
    tokens = item.get("tokens")
    if isinstance(tokens, dict):
        for field in ("input_tokens", "output_tokens", "total_tokens"):
            if field in tokens and field not in metrics:
                metrics[field] = tokens[field]
    if "cost_usd" in metrics and "estimated_cost_usd" not in metrics:
        metrics["estimated_cost_usd"] = metrics["cost_usd"]
    if "missing_telemetry" in metrics:
        missing = metrics["missing_telemetry"]
        metrics["missing_telemetry"] = [str(entry) for entry in missing] if isinstance(missing, list) else [str(missing)]
    return metrics


def _merge_run_metrics(target: dict[str, object], source: dict[str, object]) -> None:
    for key, value in source.items():
        if key == "missing_telemetry":
            merged: list[str] = []
            existing = target.get(key)
            if isinstance(existing, list):
                merged.extend(str(item) for item in existing)
            if isinstance(value, list):
                merged.extend(str(item) for item in value)
            else:
                merged.append(str(value))
            target[key] = _dedupe(merged)
        else:
            target[key] = value


def _collect_unsupported_fields(item: Mapping[str, object], index: int, unsupported: list[str], *, prefix: str = "items") -> None:
    for key in ("screenshot_path", "browser_snapshot", "ui_snapshot", "raw_dom", "image"):
        if key in item:
            unsupported.append(f"{prefix}[{index}].{key}")


def _missing_evidence(record: Mapping[str, object]) -> list[str]:
    missing: list[str] = []
    if not record.get("claimed_task"):
        missing.append("claimed_task")
    if not record.get("files_edited"):
        missing.append("files_edited")
    if not record.get("commands_run"):
        missing.append("commands_run")
    if not record.get("test_output"):
        missing.append("test_output")
    return missing


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value.strip()))
