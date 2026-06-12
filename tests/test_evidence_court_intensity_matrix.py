from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from quantagent.evidence_court import _test_output_status, build_audit_record_report, dumps_evidence_court_json


@dataclass(frozen=True)
class StatusCase:
    name: str
    test_output: Any
    expected: str | None
    commands_run: Any = None
    error: str | None = None


def _validation_command(exit_code: int) -> list[dict[str, Any]]:
    return [{"command": "python3 -m pytest tests/test_calculator.py -q", "exit_code": exit_code}]


def _assert_status_case(case: StatusCase) -> None:
    if case.error is not None:
        with pytest.raises(ValueError, match=case.error):
            _test_output_status(case.test_output, case.commands_run)
        return
    status, summary = _test_output_status(case.test_output, case.commands_run)
    assert status == case.expected
    assert summary


def _medium_cases() -> list[StatusCase]:
    cases: list[StatusCase] = []
    cases.extend(StatusCase(f"plain-pass-{index}", f"{index + 1} passed in 0.{index:02d}s", "passed") for index in range(25))
    cases.extend(StatusCase(f"zero-failed-pass-{index}", f"0 failed, {index + 1} passed in 0.{index:02d}s", "passed") for index in range(25))
    cases.extend(StatusCase(f"plain-failed-{index}", f"{index + 1} failed, 0 passed in 0.{index:02d}s", "failed") for index in range(20))
    cases.extend(StatusCase(f"plain-error-{index}", f"{index + 1} error, 0 failed, 2 passed in 0.{index:02d}s", "failed") for index in range(10))
    cases.extend(StatusCase(f"plain-failure-{index}", f"{index + 1} failure, 2 passed in 0.{index:02d}s", "failed") for index in range(10))
    cases.extend(StatusCase(f"structured-status-pass-{index}", {"status": "passed", "output": f"{index + 1} passed in 0.01s"}, "passed") for index in range(5))
    cases.extend(StatusCase(f"structured-status-fail-{index}", {"status": "failed", "output": f"{index + 1} failed in 0.01s"}, "failed") for index in range(5))
    return cases


def _high_cases() -> list[StatusCase]:
    cases: list[StatusCase] = []
    cases.extend(
        StatusCase(
            f"validation-exit-fail-over-pass-{index}",
            f"{index + 1} passed in 0.02s",
            "failed",
            _validation_command(index + 1),
        )
        for index in range(20)
    )
    cases.extend(
        StatusCase(
            f"structured-failed-output-over-status-{index}",
            {"status": "passed", "output": f"{index + 1} failed, 0 passed in 0.02s"},
            "failed",
            _validation_command(0),
        )
        for index in range(20)
    )
    cases.extend(
        StatusCase(
            f"structured-failed-summary-over-output-{index}",
            {
                "status": "passed",
                "output": f"{index + 1} passed in 0.02s",
                "summary": f"{index + 1} errors, 0 failed, 2 passed in 0.02s",
            },
            "failed",
            _validation_command(0),
        )
        for index in range(20)
    )
    cases.extend(
        StatusCase(
            f"structured-exit-fail-over-status-{index}",
            {"status": "passed", "exit_code": index + 1, "output": f"{index + 1} passed in 0.02s"},
            "failed",
            _validation_command(0),
        )
        for index in range(20)
    )
    cases.extend(
        StatusCase(
            f"malformed-structured-exit-code-{index}",
            {"status": "passed", "exit_code": str(index + 1), "output": f"{index + 1} passed in 0.02s"},
            None,
            _validation_command(0),
            "test_output exit_code must be an integer",
        )
        for index in range(5)
    )
    cases.extend(
        StatusCase(
            f"malformed-structured-status-{index}",
            {"status": bool(index % 2), "output": f"{index + 1} passed in 0.02s"},
            None,
            _validation_command(0),
            "test_output status must be a string",
        )
        for index in range(5)
    )
    cases.extend(
        StatusCase(
            f"malformed-structured-output-{index}",
            {"status": "passed", "output": [f"{index + 1} failed in 0.02s"]},
            None,
            _validation_command(0),
            "test_output output must be a string",
        )
        for index in range(5)
    )
    cases.extend(
        StatusCase(
            f"malformed-structured-summary-{index}",
            {"status": "passed", "summary": {"failed": index + 1}},
            None,
            _validation_command(0),
            "test_output summary must be a string",
        )
        for index in range(5)
    )
    return cases


def _ultra_cases() -> list[StatusCase]:
    return [
        StatusCase(
            "ultra-conflicting-status-output-summary-exit",
            {"status": "passed", "exit_code": 0, "output": "7 passed in 0.02s", "summary": "2 failures, 5 passed in 0.02s"},
            "failed",
            _validation_command(0),
        ),
        StatusCase(
            "ultra-command-fail-over-structured-pass",
            {"status": "passed", "exit_code": 0, "output": "9 passed in 0.02s"},
            "failed",
            _validation_command(2),
        ),
        StatusCase(
            "ultra-structured-exit-fail-over-clean-text",
            {"status": "passed", "exit_code": 3, "output": "12 passed in 0.02s", "summary": "0 failed, 12 passed"},
            "failed",
            _validation_command(0),
        ),
        StatusCase(
            "ultra-summary-error-over-output-pass",
            {"status": "success", "output": "20 passed", "summary": "1 error, 0 failed, 20 passed"},
            "failed",
            _validation_command(0),
        ),
        StatusCase(
            "ultra-output-failure-over-summary-pass",
            {"status": "pass", "output": "1 failure, 19 passed", "summary": "19 passed"},
            "failed",
            _validation_command(0),
        ),
        StatusCase(
            "ultra-bool-exit-code-rejected",
            {"status": "passed", "exit_code": False, "output": "20 passed"},
            None,
            _validation_command(0),
            "test_output exit_code must be an integer",
        ),
        StatusCase(
            "ultra-numeric-status-rejected",
            {"status": 1, "output": "20 passed"},
            None,
            _validation_command(0),
            "test_output status must be a string",
        ),
        StatusCase(
            "ultra-object-output-rejected",
            {"status": "passed", "output": {"passed": 20}},
            None,
            _validation_command(0),
            "test_output output must be a string",
        ),
        StatusCase(
            "ultra-list-summary-rejected",
            {"status": "passed", "summary": ["1 failed"]},
            None,
            _validation_command(0),
            "test_output summary must be a string",
        ),
        StatusCase(
            "ultra-zero-failed-and-zero-errors-pass",
            {"status": "passed", "output": "0 failed, 0 errors, 30 passed", "summary": "30 passed"},
            "passed",
            _validation_command(0),
        ),
    ]


MEDIUM_CASES = _medium_cases()
HIGH_CASES = _high_cases()
ULTRA_CASES = _ultra_cases()
ADVERSARIAL_MATRIX = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "tests"
        / "fixtures"
        / "evidence_court"
        / "adversarial_claim_matrix.json"
    ).read_text(encoding="utf-8")
)
ADVERSARIAL_CLAIM_CASES = ADVERSARIAL_MATRIX["cases"]

assert len(MEDIUM_CASES) == 100
assert len(HIGH_CASES) == 100
assert len(ULTRA_CASES) == 10
assert len(ADVERSARIAL_CLAIM_CASES) == 100


@pytest.mark.parametrize("case", MEDIUM_CASES, ids=lambda case: case.name)
def test_evidence_court_medium_intensity_matrix(case: StatusCase) -> None:
    _assert_status_case(case)


@pytest.mark.parametrize("case", HIGH_CASES, ids=lambda case: case.name)
def test_evidence_court_high_intensity_matrix(case: StatusCase) -> None:
    _assert_status_case(case)


@pytest.mark.parametrize("case", ULTRA_CASES, ids=lambda case: case.name)
def test_evidence_court_ultra_intensity_matrix(case: StatusCase) -> None:
    _assert_status_case(case)


@pytest.mark.parametrize("case", ADVERSARIAL_CLAIM_CASES, ids=lambda case: case["name"])
def test_evidence_court_adversarial_claim_matrix(case: dict[str, Any], tmp_path: Path) -> None:
    record_path = tmp_path / f"{case['name']}.json"
    record_path.write_text(json.dumps(case["record"], sort_keys=True), encoding="utf-8")

    report = build_audit_record_report(record_path)
    payload = json.loads(dumps_evidence_court_json(report))
    expected = case["expected"]

    assert payload["schema_version"] == "evidence-court/v0.1"
    assert payload["verdict"] == expected["verdict"]
    assert payload["failure_class"] == expected["failure_class"]
    assert payload["failed_at"] == expected["failed_at"]
    assert payload["finding_types"] == expected["finding_types"]
