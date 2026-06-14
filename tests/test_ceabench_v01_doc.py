from pathlib import Path
import json
import subprocess
import sys

from quantagent.evidence_court import build_audit_record_report, dumps_evidence_court_json


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "CEABENCH_V0_1.md"
CASE_INDEX = ROOT / "benchmarks" / "ceabench" / "v0.1" / "cases.json"
CASE_INDEX_SHA256 = "232245a8f7205c93f4a9d290e271cb10907166eb228346990a90a461e6b86512"
CASE_IDS = (
    "ceabench-v0.1-scope-violation-001",
    "ceabench-v0.1-missing-test-proof-001",
    "ceabench-v0.1-artifact-provenance-pass-001",
    "ceabench-v0.1-swtbench-patch-shape-pass-001",
    "ceabench-v0.1-verifier-tamper-risk-001",
    "ceabench-v0.1-runtime-shadowing-risk-001",
    "ceabench-v0.1-config-only-pass-001",
)


def test_ceabench_v01_doc_exists_and_preserves_core_framing() -> None:
    text = DOC.read_text(encoding="utf-8")

    assert "OpenMako revealed the practical problem; CEABench formalizes it into a\nmeasurable research framework." in text
    assert "claim-evidence alignment" in text
    assert "[ANECDOTAL OBSERVATION]" in text
    assert "[NEEDS SYSTEMATIC DATA]" in text
    assert "[PLANNED]" in text
    assert "benchmarks/ceabench/v0.1/cases.json" in text
    assert "This is not an external\nbenchmark result" in text
    assert "external review, leaderboard" in text


def test_ceabench_v01_doc_maps_only_existing_openmako_artifacts() -> None:
    text = DOC.read_text(encoding="utf-8")
    required_paths = (
        "quantagent/evidence_court.py",
        "docs/evidence_court_schema.md",
        "tests/test_evidence_court_intensity_matrix.py",
        "scripts/public_review_gate.sh",
        "tests/test_public_metadata.py",
        "docs/TECHNICAL_REVIEW_PACKET.md",
        "quantagent/mcp_runtime.py",
        "quantagent/mcp_daemon.py",
        "quantagent/plugin_runtime.py",
        "tests/test_mcp_runtime.py",
        "tests/test_plugin_runtime.py",
        "quantagent/sandbox_policy.py",
        "quantagent/tool_execution.py",
        "tests/test_sandbox_policy.py",
        "tests/test_tool_execution.py",
        "scripts/supplied_transcript_adapter_matrix.sh",
        "benchmarks/ceabench/v0.1/cases.json",
    )

    for relative_path in required_paths:
        assert relative_path in text
        assert (ROOT / relative_path).exists(), relative_path


def test_ceabench_v01_doc_keeps_planned_and_measured_boundaries_separate() -> None:
    text = DOC.read_text(encoding="utf-8")

    assert "Dataset-level frequencies, confidence intervals, model rankings, and human\nagreement statistics are [NEEDS SYSTEMATIC DATA]." in text
    assert "Implemented seed index:" in text
    assert "[PLANNED] CEABench v0.1 larger dataset export:" in text
    assert "not a v0.1 metric yet" in text

    forbidden_claims = (
        "OpenMako proves native product-log ingestion",
        "CEABench ranks coding agents",
        "external review has validated CEABench",
        "CEABench has leaderboard evidence",
    )
    for forbidden in forbidden_claims:
        assert forbidden not in text


def test_ceabench_v01_doc_defines_case_labels_and_metrics() -> None:
    text = DOC.read_text(encoding="utf-8")
    required_labels = (
        "aligned",
        "scope_violation",
        "failed_validation",
        "missing_test_evidence",
        "missing_diff_content_evidence",
        "missing_final_claim_evidence",
        "verifier_tamper_risk",
        "missing_ledger_identity_evidence",
        "missing_agent_risk_evidence",
    )
    required_metrics = (
        "Claim-evidence alignment accuracy",
        "Unsupported completion catch rate",
        "Contradiction catch rate",
        "Boundary discipline score",
        "Evidence coverage vector",
        "Tamper-risk sensitivity",
    )

    for label in required_labels:
        assert f"`{label}`" in text
    for metric in required_metrics:
        assert metric in text


def test_ceabench_v01_doc_preserves_evidence_audit_author_stance() -> None:
    text = DOC.read_text(encoding="utf-8")

    assert "## Author Stance" in text
    assert "Did the agent actually do the task?" in text
    assert "Where is the command, diff, log, or test evidence?" in text
    assert "Is the apparent capability real, or just false completion?" in text
    assert "FACT: implemented OpenMako code, tests, scripts, fixtures, or docs" in text
    assert "OBSERVATION: development experience that motivated the benchmark." in text
    assert "ASSUMPTION: a design choice that still needs validation." in text
    assert "LIMITATION: what the current artifact does not prove." in text
    assert "Avoid vague\nphrases like \"trustworthy AI agent ecosystem\"" in text


def _load_case_index() -> list[dict[str, str]]:
    payload = json.loads(CASE_INDEX.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    return payload


def test_ceabench_v01_case_index_is_versioned_and_unique() -> None:
    cases = _load_case_index()
    case_ids = [case["case_id"] for case in cases]

    assert len(cases) >= 7
    assert len(case_ids) == len(set(case_ids))
    assert all(case["schema_version"] == "ceabench-case-index/v0.1" for case in cases)
    assert all(case["split"] == "seed" for case in cases)
    assert {
        "claim_evidence_alignment_accuracy",
        "unsupported_completion_catch_rate",
        "contradiction_catch_rate",
        "boundary_discipline_score",
        "evidence_coverage_vector",
        "tamper_risk_sensitivity",
    }.issubset({case["metric_family"] for case in cases})


def test_ceabench_v01_case_index_matches_current_evidence_court_outputs() -> None:
    cases = _load_case_index()

    for case in cases:
        source_record = ROOT / case["source_record_path"]
        assert source_record.exists(), case["source_record_path"]

        report = build_audit_record_report(source_record)
        payload = json.loads(dumps_evidence_court_json(report))

        assert payload["schema_version"] == "evidence-court/v0.1"
        assert payload["verdict"] == case["expected_verdict"], case["case_id"]
        assert payload["failure_class"] == case["expected_failure_class"], case["case_id"]
        assert (payload["failed_at"] or "") == case["expected_failed_at"], case["case_id"]
        assert payload["patch_shape"]["bucket"] == case["expected_patch_shape"], case["case_id"]


def test_ceabench_v01_cli_scores_seed_packet_with_locked_identity() -> None:
    command = [
        sys.executable,
        "-m",
        "quantagent.cli",
        "--no-trust-prompt",
        "ceabench",
        "score",
        "--json",
        "--expected-index-sha256",
        CASE_INDEX_SHA256,
        "--expected-case-count",
        str(len(CASE_IDS)),
    ]
    for case_id in CASE_IDS:
        command.extend(["--expected-case-id", case_id])
    command.append(str(CASE_INDEX.relative_to(ROOT)))

    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=True)
    payload = json.loads(result.stdout)

    assert payload["schema_version"] == "ceabench-score/v0.1"
    assert payload["status"] == "passed"
    assert payload["case_index_sha256"] == CASE_INDEX_SHA256
    assert payload["case_count"] == len(CASE_IDS)
    assert payload["matched_count"] == len(CASE_IDS)
    assert payload["mismatch_count"] == 0
    assert payload["score"] == 1.0
    assert "native product-log ingestion" in payload["not_proof"]
    assert {case["case_id"] for case in payload["case_results"]} == set(CASE_IDS)


def test_ceabench_v01_cli_fails_closed_on_weak_case_replacement(tmp_path: Path) -> None:
    cases = _load_case_index()
    weakened_cases = [dict(case) for case in cases]
    weakened_cases[1]["source_record_path"] = "examples/evidence_court/artifact_provenance.json"
    weakened_index = tmp_path / "cases.json"
    weakened_index.write_text(json.dumps(weakened_cases, indent=2), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "quantagent.cli",
            "--no-trust-prompt",
            "ceabench",
            "score",
            "--json",
            "--expected-case-count",
            str(len(CASE_IDS)),
            str(weakened_index),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["mismatch_count"] == 1
    assert payload["mismatches"][0]["case_id"] == "ceabench-v0.1-missing-test-proof-001"
    assert payload["mismatches"][0]["observed_verdict"] == "PASS"


def test_ceabench_v01_cli_rejects_case_index_identity_mismatch() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "quantagent.cli",
            "--no-trust-prompt",
            "ceabench",
            "score",
            "--expected-index-sha256",
            "0" * 64,
            str(CASE_INDEX.relative_to(ROOT)),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "case index sha256 mismatch" in result.stderr


def test_ceabench_v01_cli_rejects_record_path_escape(tmp_path: Path) -> None:
    cases = _load_case_index()
    escaped_cases = [dict(case) for case in cases]
    escaped_cases[0]["source_record_path"] = "../outside.json"
    escaped_index = tmp_path / "cases.json"
    escaped_index.write_text(json.dumps(escaped_cases, indent=2), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "quantagent.cli",
            "--no-trust-prompt",
            "ceabench",
            "score",
            str(escaped_index),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "source_record_path must be a repository-relative path" in result.stderr
