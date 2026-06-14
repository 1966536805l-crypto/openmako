from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_openmako(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "quantagent.cli", "--no-trust-prompt", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _product_log() -> dict:
    diff = (
        "diff --git a/src/calculator.py b/src/calculator.py\n"
        "--- a/src/calculator.py\n"
        "+++ b/src/calculator.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-def add(a, b): return a - b\n"
        "+def add(a, b): return a + b\n"
    )
    return {
        "schema_version": "openmako-product-log/v0.1",
        "source_agent": "openmako-local-agent",
        "run_id": "run-native-product-log-001",
        "session_id": "session-native-product-log-001",
        "task_id": "repair-calculator-add",
        "claimed_task": "Fix src/calculator.py so add returns the sum.",
        "allowed_files": ["src/calculator.py"],
        "final_claim": "Fixed src/calculator.py and verified with pytest.",
        "events": [
            {
                "type": "read",
                "path": "src/calculator.py",
                "tool_invocation_id": "tool-read-1",
            },
            {
                "type": "command",
                "phase": "before_failure",
                "command": ["python3", "-m", "pytest", "tests/test_calculator.py", "-q"],
                "exit_code": 1,
                "output": "FAILED tests/test_calculator.py::test_add - assert -1 == 3",
                "tool_invocation_id": "tool-before-1",
            },
            {
                "type": "diagnosis",
                "text": "add subtracts b instead of adding it.",
            },
            {
                "type": "edit",
                "path": "src/calculator.py",
                "diff": diff,
                "tool_invocation_id": "tool-edit-1",
            },
            {
                "type": "command",
                "phase": "after_test",
                "command": ["python3", "-m", "pytest", "tests/test_calculator.py", "-q"],
                "exit_code": 0,
                "output": "1 passed in 0.02s",
                "tool_invocation_id": "tool-after-1",
            },
        ],
    }


def _write_log(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "product-log.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_product_log_ingestion_builds_auditable_failure_to_fix_record(tmp_path: Path) -> None:
    log_path = _write_log(tmp_path, _product_log())

    converted = _run_openmako("evidence-court", "record", "from-product-log", str(log_path))

    assert converted.returncode == 0, converted.stderr
    record = json.loads(converted.stdout)
    assert record["source_format"] == "openmako-product-log/v0.1"
    assert record["files_read"] == ["src/calculator.py"]
    assert record["files_edited"] == ["src/calculator.py"]
    assert record["commands_run"] == [
        {"command": "python3 -m pytest tests/test_calculator.py -q", "exit_code": 0}
    ]
    assert record["test_output"] == "1 passed in 0.02s"
    assert record["run_metrics"]["command_count"] == 2
    assert record["run_metrics"]["post_edit_validation_command_count"] == 1
    assert record["ledger_identity"]["run_id"] == "run-native-product-log-001"
    assert record["ledger_identity"]["tool_invocation_ids"] == [
        "tool-read-1",
        "tool-before-1",
        "tool-edit-1",
        "tool-after-1",
    ]
    assert record["artifact_provenance"]["input_hashes"]["product-log.json"].startswith("sha256:")
    assert record["product_log_boundary"]["native_product_log_ingested"] is True
    assert record["product_log_boundary"]["before_failure"]["exit_code"] == 1
    assert record["product_log_boundary"]["after_test"]["exit_code"] == 0
    assert record["product_log_boundary"]["agent_diagnosis"] == [
        "add subtracts b instead of adding it."
    ]
    assert [item["phase"] for item in record["product_log_boundary"]["command_log"]] == [
        "before_failure",
        "after_test",
    ]
    assert "live autonomy" in record["product_log_boundary"]["not_proof"]

    record_path = tmp_path / "record.json"
    record_path.write_text(json.dumps(record), encoding="utf-8")
    audited = _run_openmako("evidence-court", "audit", "--json", str(record_path))

    assert audited.returncode == 0, audited.stderr
    verdict = json.loads(audited.stdout)
    assert verdict["verdict"] == "PASS"
    assert verdict["failure_class"] == ""
    assert verdict["patch_shape"]["bucket"] == "source_only"


def test_product_log_ingestion_fails_closed_without_before_failure(tmp_path: Path) -> None:
    payload = _product_log()
    payload["events"] = [event for event in payload["events"] if event.get("phase") != "before_failure"]
    log_path = _write_log(tmp_path, payload)

    converted = _run_openmako("evidence-court", "record", "from-product-log", str(log_path))

    assert converted.returncode == 2
    assert "exactly one before_failure" in converted.stderr


def test_product_log_ingestion_fails_closed_without_diagnosis(tmp_path: Path) -> None:
    payload = _product_log()
    payload["events"] = [event for event in payload["events"] if event.get("type") != "diagnosis"]
    log_path = _write_log(tmp_path, payload)

    converted = _run_openmako("evidence-court", "record", "from-product-log", str(log_path))

    assert converted.returncode == 2
    assert "agent diagnosis" in converted.stderr


def test_product_log_ingestion_fails_closed_without_source_diff_content(tmp_path: Path) -> None:
    payload = _product_log()
    for event in payload["events"]:
        if event.get("type") == "edit":
            event.pop("diff")
            event["diff"] = (
                "diff --git a/tests/test_calculator.py b/tests/test_calculator.py\n"
                "--- a/tests/test_calculator.py\n"
                "+++ b/tests/test_calculator.py\n"
            )
    log_path = _write_log(tmp_path, payload)

    converted = _run_openmako("evidence-court", "record", "from-product-log", str(log_path))

    assert converted.returncode == 2
    assert "diff must cover every edited source file" in converted.stderr


def test_product_log_ingestion_fails_closed_when_after_test_fails(tmp_path: Path) -> None:
    payload = _product_log()
    for event in payload["events"]:
        if event.get("phase") == "after_test":
            event["exit_code"] = 1
            event["output"] = "FAILED tests/test_calculator.py::test_add"
    log_path = _write_log(tmp_path, payload)

    converted = _run_openmako("evidence-court", "record", "from-product-log", str(log_path))

    assert converted.returncode == 2
    assert "after_test command must have exit_code 0" in converted.stderr


def test_product_log_ingestion_fails_closed_when_validation_is_stale(tmp_path: Path) -> None:
    payload = _product_log()
    events = payload["events"]
    after_test = events.pop()
    events.insert(3, after_test)
    log_path = _write_log(tmp_path, payload)

    converted = _run_openmako("evidence-court", "record", "from-product-log", str(log_path))

    assert converted.returncode == 2
    assert "after_test command must occur after the final edit" in converted.stderr
