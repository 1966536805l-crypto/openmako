from __future__ import annotations

import ast
import hashlib
import http.server
import json
import os
import re
import shlex
import socketserver
import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTONOMOUS_TASK_SOURCE_MANIFEST = ROOT / "scripts" / "autonomous_task_source_provenance.json"
PUBLIC_DESCRIPTION = (
    "Evidence harness for coding agents: learning-effect, patch-scope, and test-proof checks."
)
FORBIDDEN_DESCRIPTION_TERMS = (
    "agent runtime",
    "coding and data work",
    "general autonomy",
)
FORBIDDEN_README_CLAIMS = (
    "Today, OpenMako proves",
    "## What It Proves Today",
    "| Green public CI |",
    "OpenMako does not copy Claude/closed-source code",
    "docs/COMPARISON.md",
    "docs/LAUNCH_PLAYBOOK.md",
    "docs/MARKET_TOOL_COPY_SCAN.md",
)
FORBIDDEN_PUBLIC_PROGRESS_CLAIMS = (
    "112/112",
    "60/60",
    "full pytest passed",
    "level=L5",
    "SWE-style repository reasoning",
    "broad unknown NPM repo repair",
)
FORBIDDEN_ROOT_AGENT_NOTES = (
    "QuantAgent Project Memory",
    "local quant-focused coding agent starter",
    "quant-focused coding agent starter",
    "Claude Code-like local workflow",
    "PF, slippage, capacity, tick, broker",
    "python3 -m unittest discover -s tests",
    "desktop actions",
    "Claude Code source",
    "OpenClaw, Hermes Agent",
    "desktop_plan.py",
)
ARCHIVED_ROOT_QUANT_FILES = (
    "TICK_CAPACITY_VALIDATOR_GUIDE.md",
    "capacity_validation_report.json",
    "tick_price_validation.json",
    "tick_price_validation.md",
)
EXAMPLE_ROOT_QUANT_FILES = (
    "demo_capacity_comprehensive.py",
    "demo_capacity_validation.py",
    "example_tick_price_validator.py",
    "realistic_t1_trades.csv",
)
LEGACY_ROOT_QUANT_TEST_FILES = (
    "test_tick_price_validator.py",
    "test_realistic_t1_trades.csv",
    "test_slippage_calculator.py",
    "test_tick_extraction_real.py",
    "test_tick_extraction.py",
    "tick_data_request_test.csv",
)
INTERNAL_PLANNING_DOCS = (
    "docs/LAUNCH_PLAYBOOK.md",
    "docs/COMPARISON.md",
    "docs/MARKET_TOOL_COPY_SCAN.md",
    "docs/CLAUDE_SRC_ABSORPTION_PLAN.md",
    "docs/DESKTOP_L5_ROADMAP.md",
    "docs/OPENCLAW_LEVEL_TARGET.md",
    "docs/OPENCLAW_HERMES_FULL_PORT_PLAN.md",
    "docs/AGENT_PORTING_SWARM.md",
    "docs/DESKTOP_DAEMON_L4.md",
    "docs/HERMES_OPENCLAW_SOURCE_SCAN.md",
    "docs/OPENCLAW_HERMES_COPY_WHITELIST.md",
    "docs/SOURCE_COPY_BORROW_MATRIX.md",
    "docs/SAFETY_POLICY.md",
    "docs/SANDBOX_ROADMAP.md",
    "docs/TICK_VALIDATION.md",
    "docs/OPENAI_COMPATIBLE_SETUP.md",
    "docs/UPSTREAM_ATTRIBUTION.md",
    "docs/DESIGN_DECISIONS.md",
    "docs/OPERATOR_TRUST_MODEL.md",
    "docs/OPENMAKO_NEXT_PORTS.md",
)
FORBIDDEN_PUBLIC_DOC_VENDOR_ENDPOINTS = (
    "api.xiaoma.best",
    "lanyiapi.com",
)


def _proof_result(
    task_id: str,
    *,
    status: str,
    solved: bool,
    changed_files: list[str] | None = None,
    failure_class: str | None = None,
    out_of_scope_files: list[str] | None = None,
) -> dict:
    return {
        "changed_files": changed_files or ["subject.py"],
        "failure_class": failure_class,
        "out_of_scope_files": out_of_scope_files or [],
        "solved": solved,
        "status": status,
        "task_id": task_id,
        "workspace_added_files": [],
        "workspace_deleted_files": [],
    }


def _task_proof(
    *,
    segment: str,
    test_name: str,
    task_ids: list[str],
    observed_counts: dict,
) -> dict:
    repeat_count = 10 if segment == "upstream_hidden_pack_reuse" else 2
    stability_ids = [task_id for task_id in task_ids for _ in range(repeat_count)]
    return {
        "benchmark_fingerprint": "0" * 64,
        "observed_counts": observed_counts,
        "result_sets": {
            "approved_learning": [
                _proof_result(task_id, status="solved", solved=True)
                for task_id in task_ids
            ],
            "cheat": [
                _proof_result(
                    task_id,
                    status="cheated",
                    solved=False,
                    changed_files=[],
                    failure_class="policy",
                    out_of_scope_files=["tests/test_subject.py", "tests/failure_log.txt"],
                )
                for task_id in task_ids
            ],
            "no_learning": [
                _proof_result(task_id, status="failed", solved=False, changed_files=[])
                for task_id in task_ids
            ],
            "stability": [
                _proof_result(task_id, status="solved", solved=True)
                for task_id in stability_ids
            ],
        },
        "schema_version": "autonomous-task-proof/v0.1",
        "segment": segment,
        "test_name": test_name,
    }


def _autonomous_task_proofs_fixture() -> dict:
    upstream_ids = [f"combined_task_{index}" for index in range(10)]
    cross_specs = [
        ("pandera_scale_no_seed", "pandera_scale"),
        ("pandera_bool_no_seed", "pandera_bool"),
        ("great_expectations_result_format_no_seed", "ge_result_format"),
        ("aider_random_color_no_seed", "aider_random_color"),
    ]
    return {
        "upstream_hidden_pack_reuse": [
            _task_proof(
                segment="upstream_hidden_pack_reuse",
                test_name="combined_upstream_hidden_pack",
                task_ids=upstream_ids,
                observed_counts={
                    "approved_learning_solved": 10,
                    "cheat_caught": 10,
                    "hidden_task_count": 10,
                    "no_learning_solved": 0,
                    "stability_solved": 100,
                },
            )
        ],
        "cross_upstream_no_seed_reuse": [
            _task_proof(
                segment="cross_upstream_no_seed_reuse",
                test_name=test_name,
                task_ids=[f"{family}_stage2_a", f"{family}_stage2_b"],
                observed_counts={
                    "approved_learning_solved": 2,
                    "cheat_caught": 2,
                    "hidden_stage2_tasks": 2,
                    "no_learning_solved": 0,
                    "stability_solved": 4,
                },
            )
            for test_name, family in cross_specs
        ],
    }


def _autonomous_task_source_provenance_fixture() -> dict:
    return json.loads(AUTONOMOUS_TASK_SOURCE_MANIFEST.read_text(encoding="utf-8"))


def _autonomous_task_source_manifest_fixture() -> dict:
    manifest_text = AUTONOMOUS_TASK_SOURCE_MANIFEST.read_text(encoding="utf-8")
    return {
        "path": "scripts/autonomous_task_source_provenance.json",
        "artifact_path": ".quantagent/autonomous_learning_gate/task_source_provenance_manifest.json",
        "sha256": hashlib.sha256(manifest_text.encode("utf-8")).hexdigest(),
    }


def _selected_tests_sha256(selected: list[str]) -> str:
    return hashlib.sha256(("\n".join(selected) + "\n").encode("utf-8")).hexdigest()


def _pyproject_description() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^description = "([^"]+)"$', text, flags=re.MULTILINE)
    assert match, "pyproject.toml must declare a project description"
    return match.group(1)


def _setup_description() -> str:
    tree = ast.parse((ROOT / "setup.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "setup":
            for keyword in node.keywords:
                if keyword.arg == "description" and isinstance(keyword.value, ast.Constant):
                    return str(keyword.value.value)
    raise AssertionError("setup.py must declare a setup(description=...)")


def test_package_metadata_uses_focused_public_positioning() -> None:
    descriptions = [_pyproject_description(), _setup_description()]

    assert descriptions == [PUBLIC_DESCRIPTION, PUBLIC_DESCRIPTION]
    for description in descriptions:
        lowered = description.lower()
        for forbidden in FORBIDDEN_DESCRIPTION_TERMS:
            assert forbidden not in lowered


def test_readme_links_public_proof_issue() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "## Technical Review Entry Points" in readme
    assert "Public proof card" in readme
    assert "https://github.com/1966536805l-crypto/openmako/issues/1" in readme
    assert "Technical boundary criticism request" in readme
    assert "https://github.com/1966536805l-crypto/openmako/issues/2" in readme
    assert "Technical boundary issue form" in readme
    assert "issues/new?template=technical-boundary-check.yml" in readme
    assert "External review record form" in readme
    assert "issues/new?template=external-review-record.yml" in readme
    assert "already-public technical feedback only" in readme
    assert "a review request rather than endorsement or promotion" in readme
    assert "Technical review packet" in readme
    assert "docs/TECHNICAL_REVIEW_PACKET.md" in readme
    assert "Reproduction guide" in readme
    assert "docs/REPRODUCE_V0_1.md" in readme
    assert "Contributor guide" in readme
    assert "CONTRIBUTING.md" in readme
    assert "Attribution boundary" in readme
    assert "docs/UPSTREAM_ATTRIBUTION.md" in readme
    assert "External-source benchmark gate" in readme
    assert "bash scripts/external_source_benchmark_gate.sh" in readme
    assert "OpenClaw vendored-source manifest, MIT license, selected source digest" in readme
    assert "external_source=true" in readme
    assert "independent_external_heldout=false" in readme
    assert "external-source regression evidence only, not independent external held-out benchmark evidence" in readme
    assert "External-heldout benchmark gate" in readme
    assert "bash scripts/external_heldout_benchmark_gate.sh" in readme
    assert "MCP Python SDK vendored-source manifest, MIT license, selected source digest" in readme
    assert "external_source_heldout=true" in readme
    assert "heldout_from_autonomous_gate=true" in readme
    assert "independent_external_benchmark=false" in readme
    assert "external-source held-out regression evidence only, not external benchmark standing" in readme
    assert "Agent trend radar" in readme
    assert "docs/AGENT_TREND_RADAR.md" in readme
    assert "Reviewer target map" in readme
    assert "docs/REVIEWER_TARGETS.md" in readme
    assert "Wave 1 review requests" in readme
    assert "docs/WAVE1_REVIEW_REQUESTS.md" in readme
    assert "Wave 1 public target queue" in readme
    assert "docs/WAVE1_PUBLIC_TARGET_QUEUE.md" in readme
    assert "Wave 1 short-message helper" in readme
    assert "bash scripts/wave1_review_request.sh swe-agent" in readme
    assert "Wave 1 send-ready check" in readme
    assert "bash scripts/wave1_send_ready.sh swe-agent" in readme
    assert "Public share packet" in readme
    assert "docs/PUBLIC_SHARE_PACKET.md" in readme
    assert "Public share-ready check" in readme
    assert "bash scripts/public_share_ready.sh review-request" in readme
    assert "bash scripts/desktop_control_proof_card.sh" in readme
    assert "Post-review broader share packet" in readme
    assert "docs/LARGE_REPOST_PACKET.md" in readme
    assert "Post-review share check" in readme
    assert "bash scripts/large_repost_ready.sh REVIEW_RECORD_ISSUE_URL --confirm-external-review" in readme
    assert "Remote focused CI snapshot" in readme
    assert "bash scripts/remote_focused_ci_snapshot.sh" in readme
    assert "a fail-closed check for the latest focused workflow on current `openmako/main`" in readme
    assert "supports `OPENMAKO_GITHUB_TOKEN`, `GITHUB_TOKEN`, or `GH_TOKEN`" in readme
    assert "if the GitHub API is unavailable it prints the remote SHA, local UTC check time, manual Actions URL, rate-limit reset countdown, and a copyable rerun command when available before exiting nonzero" in readme
    assert "not external review or endorsement" in readme
    assert "Remote autonomous-learning artifact snapshot" in readme
    assert "bash scripts/remote_autonomous_learning_snapshot.sh" in readme
    assert "a fail-closed check for the latest autonomous-learning workflow on current `openmako/main` plus the `autonomous-learning-gate-summary` artifact id, digest, downloaded `last_summary.json` contract fields, task-level proof records, and task-source provenance showing `repo-authored-regression-pack` with `external_heldout=false`" in readme
    assert "OPENMAKO_AUTONOMOUS_ARTIFACT_ZIP" in readme
    assert "artifact zip 401 results print token and saved-fixture rerun commands before exiting nonzero" in readme
    assert "public CI artifact evidence only, not external review, endorsement, stars, reposts, live autonomy, broad unknown-repository repair, external benchmark standing, or independent external held-out benchmark evidence" in readme
    assert "Saved autonomous artifact snapshot" in readme
    assert "bash scripts/saved_autonomous_artifact_snapshot.sh runs.json artifacts.json autonomous-learning-gate-summary.zip <openmako-main-sha>" in readme
    assert "an explicit fixture wrapper for saved GitHub Actions run metadata, artifact metadata, and the downloaded autonomous-learning artifact zip" in readme
    assert "useful when live API reads are rate-limited" in readme
    assert "checks the same artifact contract against saved inputs but does not prove fixture provenance or current live GitHub API state" in readme
    assert "saved public CI artifact evidence only, not external review, endorsement, stars, reposts, live autonomy, broad unknown-repository repair, or external benchmark standing" in readme
    assert "Public evidence comment check" in readme
    assert "bash scripts/public_evidence_comment_check.sh" in readme
    assert "a fail-closed marker check for the published issue evidence comment" in readme
    assert "defaults to issue #1 comment `4694860161`" in readme
    assert "verifies the configured commit, run, job, artifact id, artifact digest, and boundary phrase in public HTML" in readme
    assert "OPENMAKO_PUBLIC_EVIDENCE_HTML" in readme
    assert "public record consistency only, not external review, endorsement, stars, reposts, live autonomy, broad unknown-repository repair, or external benchmark standing" in readme
    assert "Why It Is Worth Checking" in readme


def test_focused_workflow_runs_same_public_gate_as_readme() -> None:
    workflow = (ROOT / ".github" / "workflows" / "focused.yml").read_text(encoding="utf-8")

    assert "Run focused OpenMako evidence gate" in workflow
    assert "bash scripts/public_review_gate.sh" in workflow
    assert "tests/test_agent_planner_contract.py::AgentPlannerContractTest" not in workflow
    assert "tests/test_external_benchmark_multimodule_regression.py::ExternalBenchmarkMultimoduleRegressionTest" not in workflow
    assert "python -m pip install -e . pytest" in workflow


def test_despair_gate_is_repeatable_but_not_a_public_claim() -> None:
    script = ROOT / "scripts" / "despair_gate.sh"
    workflow = (ROOT / ".github" / "workflows" / "despair-gate.yml").read_text(encoding="utf-8")
    progress = (ROOT / "PROGRESS.md").read_text(encoding="utf-8")
    text = script.read_text(encoding="utf-8")

    assert os.access(script, os.X_OK)
    assert "coding-bench solved=" in text
    assert '"invocation"' in text
    assert '"git_commit"' in text
    assert '"argv"' in text
    assert '"elapsed_seconds"' in text
    assert '"segment_elapsed_seconds"' in text
    assert '"failure"' in text
    assert '"exit_code"' in text
    assert "validate_summary" in text
    assert "validate_failure_summary" in text
    assert "despair-gate: invalid summary fields=" in text
    assert "despair-gate: invalid failure summary fields=" in text
    assert "type(solved) is not int" in text
    assert "coding_bench.success_rate" in text
    assert "coding_bench.artifact_dir" in text
    assert "tests/test_external_benchmark_multimodule_regression.py" in text
    assert '"$PYTHON_BIN" -m pytest -p no:cacheprovider -q' in text
    assert "bash scripts/public_review_gate.sh" in text
    assert "bash scripts/desktop_control_local_gate.sh" in text
    assert "--skip-full-pytest" in text
    assert "--bench-limit" in text
    assert "OPENMAKO_DESPAIR_GATE_SUMMARY_JSON" in text
    assert "OPENMAKO_DESPAIR_GATE_TEST_FAIL_SEGMENT" in text
    assert "OPENMAKO_DESPAIR_GATE_TEST_CORRUPT_SUMMARY" in text
    assert "missing_bench_fields" in text
    assert "despair-gate: FAILED segment=" in text
    assert "not-proof=external review, benchmark ranking, live desktop control, L4, L5, stars, reposts, endorsement" in text

    assert "workflow_dispatch:" in workflow
    assert "push:" not in workflow
    assert "pull_request:" not in workflow
    assert "timeout-minutes: 45" in workflow
    assert "bash scripts/despair_gate.sh" in workflow
    assert "Upload CodingBench artifacts" in workflow
    assert "if: always()" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "name: despair-gate-coding-bench" in workflow
    assert "path: |" in workflow
    assert ".quantagent/coding_bench" in workflow
    assert ".quantagent/despair_gate" in workflow
    assert "if-no-files-found: ignore" in workflow

    assert "`bash scripts/despair_gate.sh` now wraps that high-intensity local loop" in progress
    assert "Its skip and limit flags are for\n  script smoke testing only; they do not create public proof" in progress
    assert "`.github/workflows/despair-gate.yml` exposes that gate as a manual\n  `workflow_dispatch` check" in progress
    assert "not attached to default push\n  or pull-request CI" in progress
    assert "uploads CodingBench artifacts for\n  debugging failed manual runs" in progress
    assert "`.quantagent/despair_gate/last_summary.json` as a local machine-readable\n  run summary" in progress
    assert "Failed segments are also\n  recorded in that summary with the failed segment and exit code" in progress
    assert "Smoke-test\n  calls can write to a separate summary path" in progress
    assert "invoking commit, argv,\n  CodingBench elapsed seconds, and per-segment elapsed seconds" in progress
    assert "validates the summary before printing `PASS`" in progress
    assert "CodingBench solved, total, success rate, artifact directory, and elapsed\n  fields are also type-checked" in progress
    assert "A corrupt-summary smoke path deletes those fields\n  before validation and must fail closed" in progress
    assert "pytest log paths and log tails,\n  observed pass/skip/warning counts" in progress
    assert "observed pytest result fields so validation fails closed" in progress
    assert "Failed summaries are validated after\n  failure metadata is written" in progress
    assert "internally inconsistent summaries fail closed" in progress


def test_autonomous_learning_gate_workflow_uploads_summary_artifacts() -> None:
    workflow = (ROOT / ".github" / "workflows" / "autonomous-learning-gate.yml").read_text(encoding="utf-8")
    progress = (ROOT / "PROGRESS.md").read_text(encoding="utf-8")

    assert "name: autonomous-learning-gate" in workflow
    assert "workflow_dispatch:" in workflow
    assert "push:" in workflow
    assert "branches:" in workflow
    assert "- main" in workflow
    assert "paths:" in workflow
    assert '".github/workflows/autonomous-learning-gate.yml"' in workflow
    assert '"scripts/autonomous_task_source_provenance.json"' in workflow
    assert '"scripts/autonomous_learning_gate.sh"' in workflow
    assert '"scripts/remote_autonomous_learning_snapshot.sh"' in workflow
    assert '"scripts/supplied_transcript_adapter_matrix.sh"' in workflow
    assert '"PROGRESS.md"' in workflow
    assert '"quantagent/agent_loop_core.py"' in workflow
    assert '"quantagent/coding_bench.py"' in workflow
    assert '"quantagent/evidence_court.py"' in workflow
    assert '"quantagent/learning_effect_coding_bench.py"' in workflow
    assert '"quantagent/skill_learning.py"' in workflow
    assert '"quantagent/skill_pipeline.py"' in workflow
    assert '"tests/test_cli_wrappers.py"' in workflow
    assert '"tests/test_learning_effect_e2e.py"' in workflow
    assert '"tests/test_skill_learning.py"' in workflow
    assert '"tests/test_upstream_function_file_bundle_regression.py"' in workflow
    assert '"tests/test_public_metadata.py"' in workflow
    assert "pull_request:" not in workflow
    assert "timeout-minutes: 20" in workflow
    assert "python -m pip install -e . pytest typing_extensions" in workflow
    assert "bash scripts/autonomous_learning_gate.sh" in workflow
    assert "Upload autonomous-learning summary and logs" in workflow
    assert "if: always()" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "name: autonomous-learning-gate-summary" in workflow
    assert "path: .quantagent/autonomous_learning_gate" in workflow
    assert "if-no-files-found: error" in workflow

    assert "`.github/workflows/autonomous-learning-gate.yml` exposes the autonomous-learning\n  stress gate as a manual `workflow_dispatch` check and as a path-filtered\n  `push` check" in progress
    assert "for the workflow file, tracked task-source manifest, gate script,\n  remote artifact snapshot script, `PROGRESS.md`, and selected gate-test paths" in progress
    assert "The path filter also includes core learning modules, retained-failure\n  skill-learning code and tests, the supplied transcript adapter matrix,\n  `quantagent/evidence_court.py`, and `tests/test_cli_wrappers.py`" in progress
    assert "The gate derives the selected pytest\n  node ids and expected\n  pass counts from `scripts/autonomous_task_source_provenance.json` rather than\n  duplicating that test list inside the shell script" in progress
    assert "fails closed\n  before pytest runs if a manifest segment falls below its expected minimum\n  selected-test count, contains a non-pytest-node id, passes a pytest option,\n  includes whitespace, duplicates a test inside a segment, or duplicates a test\n  across segments" in progress
    assert "It uploads\n  `.quantagent/autonomous_learning_gate` as the\n  `autonomous-learning-gate-summary` artifact" in progress
    assert "attached to broad\n  default push or pull-request CI" in progress
    assert "task-source provenance can be inspected for an exact workflow run" in progress
    assert "artifact-copied task-source manifest, task-source manifest sha256, and\n  task-source provenance can be inspected" in progress
    assert "The summary\n  records `task_source_provenance` as `repo-authored-regression-pack` with\n  `external_heldout=false`" in progress
    assert "A passing manual or path-filtered push run is public CI artifact\n  evidence only, not external review, endorsement, stars, reposts, live\n  autonomy, broad unknown-repository repair proof, external benchmark standing,\n  or independent external held-out benchmark evidence" in progress
    assert "the artifact-copied task-source manifest, the manifest sha256, summary versus\n  manifest equality, and the downloaded `last_summary.json` contract fields for\n  the manifest-derived selected segments" in progress
    assert "It also fails closed when a provenance segment's\n  `selected_tests` no longer matches the summary's selected tests or expected\n  pass count" in progress
    assert "applies the same minimum count, pytest-node-id shape,\n  no-option, no-whitespace, and no-duplicate constraints to the\n  artifact-contained manifest" in progress
    assert "`GITHUB_TOKEN`, or `GH_TOKEN` fallback token names as the focused snapshot,\n  plus `OPENMAKO_AUTONOMOUS_ARTIFACT_ZIP` for saved artifact fixtures" in progress
    assert "When API\n  data or artifact download is unavailable" in progress
    assert "Artifact zip 401 now gets\n  a distinct\n  `artifact_zip_requires_auth` boundary snapshot with token and saved fixture\n  rerun commands, while still failing closed" in progress
    assert "local HTTP 401 regression test\n  asserts the nonzero exit, auth hints, fixture rerun command, and absence of\n  `PASS`" in progress
    assert "Passing this script is current public CI artifact evidence only, not\n  external review, endorsement, stars, reposts, live autonomy, broad\n  unknown-repository repair, external benchmark standing, or independent\n  external held-out benchmark evidence" in progress
    assert "`bash scripts/public_evidence_comment_check.sh` is the fail-closed marker\n  check for the published issue #1 evidence comment" in progress
    assert "comment id, commit, run id, job id, artifact name, artifact id, artifact\n  digest, and boundary phrase" in progress
    assert "`OPENMAKO_PUBLIC_EVIDENCE_HTML` fixture" in progress
    assert "Passing this script is public comment\n  record consistency only, not external review, endorsement, stars, reposts,\n  live autonomy, broad unknown-repository repair, or external benchmark\n  standing" in progress


def test_agent_trend_radar_tracks_current_next_build_target() -> None:
    radar = (ROOT / "docs" / "AGENT_TREND_RADAR.md").read_text(encoding="utf-8")

    assert "Last refreshed: 2026-06-05." in radar
    assert "Status alignment updated: 2026-06-12." in radar
    assert "## Current Build Target" in radar
    assert "The `run-metrics` evidence extension, the first supplied-transcript adapter\nmatrix, and supplied diff-content evidence handling are already on `main`" in radar
    assert "rejects success claims when command/test proof, edited-file\nevidence, or supplied diff-content evidence is missing" in radar
    assert "duplicate diff-hunk handling are covered for the repository-defined\nCodex, Claude, OpenHands, and SWE-agent supplied formats" in radar
    assert "Adapter evidence edge-case hardening has also moved from next target into\ncurrent `main` work" in radar
    assert "final-claim evidence, empty\ndiff strings, failed test commands, unsupported edit events, malformed" in radar
    assert "malformed path fields, message roles, classifier fields,\ncontent text blocks, and nested tool payload containers" in radar
    assert "Supplied evidence ledger identity has also moved into current `main` work" in radar
    assert "preserves supplied `session_id`, `task_id`, `parent_id`,\n`tool_invocation_ids`, `missing_identity`, and extra string identity fields" in radar
    assert "rejects conflicting or malformed nested/direct\nledger identity fields" in radar
    assert "Identity-gap review routing has now moved into current `main` work for raw\naudit records and the repository-defined supplied transcript adapters" in radar
    assert "routes identity-dependent claims with supplied\n`ledger_identity.missing_identity` gaps to\n`missing_ledger_identity_evidence`" in radar
    assert "plain missing-identity metadata\nremains preserved reviewer evidence" in radar
    assert "adapter-level regression\nconverts Codex, Claude, OpenHands, and SWE-agent supplied transcripts" in radar
    assert "audits the converted records to the same\n`missing_ledger_identity_evidence` boundary" in radar
    assert "The next concrete build target is narrower again: another adapter evidence edge\ncase" in radar
    assert "preserve `missing_identity` as reviewer evidence, not runtime proof" in radar
    assert "conversion must preserve the supplied field,\n  and audit must route the resulting boundary" in radar
    assert "not prove live orchestration, ACP control, broad\nSWE-bench repair, native export ingestion, or external endorsement" in radar


def test_readme_exposes_reviewer_entry_points_before_scope_claims() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    why_index = readme.index("## Why It Is Worth Checking")
    proof_index = readme.index("## 60-Second Proof")
    benchmark_thread_index = readme.index("## If You Came From A Benchmark Thread")
    review_index = readme.index("## Technical Review Entry Points")
    scope_index = readme.index("## Public v0.1 Scope")
    install_index = readme.index("## Install And Reproduce")
    evidence_links_index = readme.index("## Public Evidence Links")

    assert why_index < proof_index
    assert proof_index < review_index
    assert proof_index < benchmark_thread_index < review_index
    assert review_index < scope_index
    why_section = readme[why_index:proof_index]
    assert "Coding-agent evals often collapse into a final pass/fail." in why_section
    assert "make the run evidence inspectable" in why_section
    assert "improve hidden variants" in why_section
    assert "stay inside patch scope" in why_section
    assert "did the required\ntests run as claimed" in why_section
    assert (
        "concrete mismatch between a public claim and\n"
        "the command, workflow, issue, or artifact"
    ) in why_section
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in why_section.lower()
    proof_section = readme[proof_index:review_index]
    assert "git clone https://github.com/1966536805l-crypto/openmako.git" in proof_section
    assert "python -m pip install -e . pytest" in proof_section
    assert "./scripts/public_review_gate.sh" in proof_section
    assert "bash scripts/public_proof_card.sh" in proof_section
    assert "screenshot-friendly summary" in proof_section
    assert "public-review-gate: running external-source benchmark gate" in proof_section
    assert "public-review-gate: running external-heldout benchmark gate" in proof_section
    assert "external-heldout-benchmark-gate: PASS" in proof_section
    assert "public-review-gate: checking external-heldout gate fail-closed negatives" in proof_section
    assert "public-review-gate: checking adversarial claim matrix generator" in proof_section
    assert "public-review-gate: running Evidence Court intensity matrix" in proof_section
    assert "public-review-gate: recording Evidence Court bad-run fixture" in proof_section
    assert "public-review-gate: auditing supplied Evidence Court record" in proof_section
    assert "public-review-gate: auditing artifact provenance fixture" in proof_section
    assert "public-review-gate: auditing SWTBench patch artifact fixture" in proof_section
    assert "public-review-gate: auditing config-only repair fixture" in proof_section
    assert "public-review-gate: auditing runtime shadowing fixture" in proof_section
    assert "public-review-gate: auditing verifier tamper-risk fixture" in proof_section
    assert "public-review-gate: auditing verifier attack fixture" in proof_section
    assert "public-review-gate: auditing CI workflow tamper fixture" in proof_section
    assert "public-review-gate: running supplied transcript adapter matrix" in proof_section
    assert "adapter-matrix: PASS" in proof_section
    assert "public-review-gate: PASS" in proof_section
    assert "What this checks is narrow" in proof_section
    assert (
        "local Evidence\n"
        "Court intensity matrix covers supplied test-output parser edge cases and 105\n"
        "full supplied audit-record claim-boundary cases, including five multi-finding\n"
        "precedence cases"
    ) in proof_section
    assert (
        "adversarial claim matrix generator check prevents\n"
        "checked-in fixture metadata from drifting from the compact generator"
    ) in proof_section
    assert "Supplied\ntranscript adapters preserve complete\nsupplied proof fields while rejecting success claims that have\nmissing-test-proof, missing exit-status evidence, missing edited-file evidence,\nmissing supplied diff-content evidence, supplied diff-content that only names\ntest files, or supplied diff-content that covers only a subset of edited source\nfiles, or supplied ordered edit/command evidence where passing validation\noccurs before a later source edit for a claimed source repair" in proof_section
    assert "supplied runtime-shadowing and verifier/CI tamper fixtures that classify\npassing success claims as review-risk" in proof_section
    assert "It does not prove broad\nunknown-repository repair, native runtime hardening, native benchmark\ningestion, native CI hardening, or external endorsement." in proof_section
    assert "This is a local script\nresult, not external reviewer approval." in proof_section
    assert "bash scripts/autonomous_learning_gate.sh" in proof_section
    assert "autonomous-learning-gate: running stage1 trajectory reuse matrix" in proof_section
    assert "autonomous-learning-gate: running upstream hidden-pack reuse stress test" in proof_section
    assert "autonomous-learning-gate: running cross-upstream no-seed reuse stress tests" in proof_section
    assert "autonomous-learning-gate: PASS" in proof_section
    assert (
        "high-intensity learning evidence only, not proof of native live autonomy, broad\n"
        "unknown-repository repair, external benchmark standing, remote CI proof,\n"
        "external review, independent external held-out benchmarking, endorsement,\n"
        "stars, or reposts"
    ) in proof_section
    assert "`.quantagent/autonomous_learning_gate/last_summary.json` by default" in proof_section
    assert "selected tests, per-segment elapsed\nseconds" in proof_section
    assert "per-segment pytest log paths and log tails, observed pass/skip/warning\ncounts" in proof_section
    assert "`task_source_provenance=repo-authored-regression-pack` with\n`external_heldout=false`" in proof_section
    assert "cannot be reported as an\nindependent external held-out benchmark" in proof_section
    assert "OPENMAKO_AUTONOMOUS_LEARNING_GATE_SUMMARY_JSON" in proof_section
    assert "`.github/workflows/autonomous-learning-gate.yml` workflow" in proof_section
    assert "core learning modules, selected gate-test paths, or\nsupplied Evidence Court/transcript proof surfaces" in proof_section
    assert "uploads the summary and\npytest logs" in proof_section
    assert "path-filtered and is not\nbroad default push or pull-request CI, external review, or endorsement" in proof_section
    assert "## If You Came From A Benchmark Thread" in proof_section
    assert "Start with the public gate:" in proof_section
    assert 'The useful review is not "do you like this project?"' in proof_section
    assert "Run `./scripts/public_review_gate.sh`." in proof_section
    assert "For artifact-identity questions, inspect the supplied-record fixture:" in proof_section
    assert (
        "./bin/openmako --no-trust-prompt evidence-court audit --ci --json "
        "examples/evidence_court/artifact_provenance.json"
    ) in proof_section
    assert "For config-only false-positive questions, inspect:" in proof_section
    assert (
        "./bin/openmako --no-trust-prompt evidence-court audit --ci --json "
        "examples/evidence_court/config_only_repair.json"
    ) in proof_section
    assert "Check whether the README claims more than those commands prove." in proof_section
    assert "leave the concrete mismatch on\n   [issue #2]" in proof_section
    assert "If something is unclear, please point to the file, command, workflow, or\nmissing artifact." in proof_section
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in proof_section.lower()
    install_section = readme[install_index:evidence_links_index]
    assert (
        "the external-source benchmark\n"
        "gate, the external-heldout benchmark gate, metadata boundary checks, the supplied Evidence Court bad-run audit, the\n"
        "artifact-provenance fixture, the SWTBench patch-artifact fixture, and the\n"
        "supplied transcript adapter matrix"
    ) in install_section
    assert "bash scripts/external_source_benchmark_gate.sh" in install_section
    assert "bash scripts/external_heldout_benchmark_gate.sh" in install_section
    assert "bash scripts/autonomous_learning_gate.sh" in install_section
    assert (
        "not native live autonomy or broad\n"
        "unknown-repository repair proof, remote CI proof, external review, endorsement,\n"
        "stars, or reposts"
    ) in install_section
    assert "`.quantagent/autonomous_learning_gate/last_summary.json` unless" in install_section
    assert "validates that summary, including observed pytest result counts and log tails,\nbefore printing `PASS`" in install_section
    review_section = readme[review_index:scope_index]
    assert "https://github.com/1966536805l-crypto/openmako/issues/2" in review_section
    assert "issues/new?template=technical-boundary-check.yml" in review_section
    assert "issues/new?template=external-review-record.yml" in review_section
    assert "docs/TECHNICAL_REVIEW_PACKET.md" in review_section
    assert "docs/REPRODUCE_V0_1.md" in review_section
    assert "CONTRIBUTING.md" in review_section
    assert "docs/UPSTREAM_ATTRIBUTION.md" in review_section
    assert "docs/AGENT_TREND_RADAR.md" in review_section
    assert "docs/REVIEWER_TARGETS.md" in review_section
    assert "docs/WAVE1_REVIEW_REQUESTS.md" in review_section
    assert "docs/WAVE1_PUBLIC_TARGET_QUEUE.md" in review_section
    assert "bash scripts/wave1_review_request.sh swe-agent" in review_section
    assert "bash scripts/wave1_send_ready.sh swe-agent" in review_section
    assert "docs/PUBLIC_SHARE_PACKET.md" in review_section
    assert "bash scripts/public_share_ready.sh review-request" in review_section
    assert "docs/LARGE_REPOST_PACKET.md" in review_section
    assert "bash scripts/large_repost_ready.sh REVIEW_RECORD_ISSUE_URL --confirm-external-review" in review_section
    assert "https://github.com/1966536805l-crypto/openmako/issues/1" in review_section
    assert "https://github.com/1966536805l-crypto/openmako/actions/workflows/focused.yml" in review_section
    assert "./scripts/public_review_gate.sh" in review_section
    assert "This path is for technical boundary review, not promotion." in review_section
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in review_section.lower()


def test_desktop_control_proof_card_stays_bounded() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    packet = (ROOT / "docs" / "TECHNICAL_REVIEW_PACKET.md").read_text(encoding="utf-8")
    script = ROOT / "scripts" / "desktop_control_proof_card.sh"
    text = script.read_text(encoding="utf-8")

    assert os.access(script, os.X_OK)
    assert "bash scripts/desktop_control_proof_card.sh" in readme
    assert "bash scripts/desktop_control_proof_card.sh" in packet
    assert "bash scripts/desktop_control_local_gate.sh" in text
    assert "openmako-desktop-control-proof-card: PASS" in text
    assert "suite_l4 dry-run plan" in text
    assert "AX-only target preflight" in text
    assert "OCR fallback after failed AX type verify" in text
    assert "not-proof: live desktop control; L4; L5; external endorsement; star or repost traction" in text
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in text.lower()


def test_readme_has_runnable_bad_run_demo() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "## CI Quickstart" in readme
    assert "a matching CI workflow\nresult for that exact claim" in readme
    assert "passing CI for that exact\nclaim" not in readme
    assert (
        "./bin/openmako --no-trust-prompt evidence-court record from-jsonl "
        "--output run.json examples/evidence_court/simple_events.jsonl"
    ) in readme
    assert "./bin/openmako --no-trust-prompt evidence-court audit --ci --json run.json" in readme
    assert "not a native Claude Code, Codex, or Cursor transcript adapter" in readme
    assert "docs/github_actions_evidence_court.md" in readme
    assert "## 10-Second Bad-Run Demo" in readme
    assert "./bin/openmako --no-trust-prompt evidence-court demo bad-run" in readme
    assert "./bin/openmako --no-trust-prompt evidence-court demo missing-tests" in readme
    assert "./bin/openmako --no-trust-prompt evidence-court demo out-of-scope" in readme
    assert "## Claim" in readme
    assert "## Evidence" in readme
    assert "## Scope Violations" in readme
    assert "## Test Verification" in readme
    assert "## Suspicious Behavior" in readme
    assert "## Verdict: FAIL" in readme
    assert "## Verdict: SUSPICIOUS" in readme


def test_github_actions_evidence_court_doc_uses_supported_commands() -> None:
    doc = (ROOT / "docs" / "github_actions_evidence_court.md").read_text(encoding="utf-8")

    assert ".github/workflows/evidence-court-demo.yml" in doc
    assert ".github/actions/evidence-court/action.yml" in doc
    assert "repository-local action, not a published Marketplace action" in doc
    assert "asserts that `audit --ci --json` exits with `1`" in doc
    assert "test -f run.json" in doc
    assert "uses: ./.github/actions/evidence-court" in doc
    assert "record: run.json" in doc
    assert "report: evidence-court-report.json" in doc
    assert "actions/upload-artifact@v7" in doc
    assert "openmako evidence-court record from-jsonl --output run.json path/to/events.jsonl" in doc
    assert "openmako evidence-court audit --ci --fail-on suspicious --json run.json" in doc
    assert "does not collect native Claude Code, Codex, Cursor, or SWE-bench logs" in doc
    assert "audits only the supplied `run.json`" in doc


def test_evidence_court_demo_workflow_uses_supported_bad_run_commands() -> None:
    workflow = (ROOT / ".github" / "workflows" / "evidence-court-demo.yml").read_text(encoding="utf-8")

    assert "name: evidence-court-demo" in workflow
    assert "workflow_dispatch:" in workflow
    assert "python -m pip install -e ." in workflow
    assert "openmako evidence-court record from-jsonl --output run.json examples/evidence_court/simple_events.jsonl" in workflow
    assert "uses: ./.github/actions/evidence-court" in workflow
    assert "record: run.json" in workflow
    assert "report: evidence-court-report.json" in workflow
    assert "expected-exit: \"1\"" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "Claude Code" not in workflow
    assert "Codex" not in workflow
    assert "Cursor" not in workflow


def test_evidence_court_composite_action_wraps_supported_cli_commands() -> None:
    action = (ROOT / ".github" / "actions" / "evidence-court" / "action.yml").read_text(encoding="utf-8")

    assert "using: composite" in action
    assert "record:" in action
    assert "report:" in action
    assert "fail-on:" in action
    assert "expected-exit:" in action
    assert 'default: "0"' in action
    assert "openmako evidence-court validate \"$RECORD\"" in action
    assert "openmako evidence-court audit --ci --fail-on \"$FAIL_ON\" --json \"$RECORD\" > \"$REPORT\"" in action
    assert "test \"${audit_exit}\" -eq \"${EXPECTED_EXIT}\"" in action
    assert "Marketplace" not in action
    assert "Claude Code" not in action
    assert "Codex" not in action
    assert "Cursor" not in action


def test_release_checklist_keeps_v01_claims_evidence_gated() -> None:
    checklist = (ROOT / "docs" / "release_checklist.md").read_text(encoding="utf-8")

    assert "Do not treat this file as proof that a release already happened." in checklist
    assert "bash scripts/release_readiness_gate.sh" in checklist
    assert "root package has a `LICENSE`/`COPYING` file" in checklist
    assert "`pyproject.toml` license\n  metadata" in checklist
    assert "[NEEDS OWNER DECISION: LICENSE]" in checklist
    assert "do not invent a license choice" in checklist
    assert "CHANGELOG.md" in checklist
    assert "docs/v0.1_release_notes.md" in checklist
    assert ".github/workflows/focused.yml" in checklist
    assert ".github/workflows/evidence-court-demo.yml" in checklist
    assert "tests/test_public_metadata.py" in checklist
    assert "tests/test_cli_wrappers.py" in checklist
    assert "artifact named `evidence-court-report`" in checklist
    assert "evidence-court-report.json" in checklist
    assert "Do not claim native Claude Code, Codex, Cursor, or SWE-bench export" in checklist
    assert "Current adapter checks cover repository-defined supplied\n  transcript fixtures only." in checklist
    assert "Do not claim broad unknown-repository SWE repair." in checklist
    assert "Do not claim full pytest or hidden benchmark numbers" in checklist
    assert "repository-local composite action" in checklist
    assert "published\n  Marketplace action" in checklist
    assert "git tag -a v0.1.0" in checklist
    assert "git push origin v0.1.0" in checklist
    assert "v0.1 audits repository-defined supplied records and supplied transcript\nfixtures only" in checklist
    assert "supplied\nartifact provenance, and supplied transcript adapter proof gaps" in checklist


def test_release_readiness_gate_fails_closed_on_missing_license_decision() -> None:
    script = ROOT / "scripts" / "release_readiness_gate.sh"
    text = script.read_text(encoding="utf-8")
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    progress = (ROOT / "PROGRESS.md").read_text(encoding="utf-8")

    assert script.exists()
    assert script.stat().st_mode & 0o111
    assert "MIT License" in license_text
    assert "OpenMako contributors" in license_text
    assert 'license = { file = "LICENSE" }' in pyproject
    assert "release-readiness-gate: START" in text
    assert "root-license=[NEEDS OWNER DECISION: LICENSE]" in text
    assert "pyproject-license=[NEEDS OWNER DECISION: LICENSE]" in text
    assert "not-proof=legal advice; owner license decision; external review; endorsement; release announcement" in text
    assert "bash scripts/release_readiness_gate.sh" in readme
    assert "current owner-selected project license is MIT" in readme
    assert "bash scripts/release_readiness_gate.sh" in progress
    assert "owner\n  selected MIT on 2026-06-14" in progress

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        scripts = tmp_root / "scripts"
        scripts.mkdir()
        gate = scripts / "release_readiness_gate.sh"
        gate.write_text(text, encoding="utf-8")
        gate.chmod(gate.stat().st_mode | 0o111)
        (tmp_root / "pyproject.toml").write_text(
            "[project]\nname = \"open-mako-smoke\"\nversion = \"0.0.0\"\n",
            encoding="utf-8",
        )

        missing = subprocess.run(
            ["bash", str(gate)],
            cwd=tmp_root,
            check=False,
            text=True,
            capture_output=True,
        )
        assert missing.returncode == 1
        assert "release-readiness-gate: START" in missing.stdout
        assert "release-readiness-gate: root-license=[NEEDS OWNER DECISION: LICENSE]" in missing.stderr
        assert "release-readiness-gate: pyproject-license=[NEEDS OWNER DECISION: LICENSE]" in missing.stderr
        assert "release-readiness-gate: FAIL" in missing.stderr
        assert "release-readiness-gate: PASS" not in missing.stdout

        (tmp_root / "LICENSE").write_text("Owner-selected test license placeholder.\n", encoding="utf-8")
        (tmp_root / "pyproject.toml").write_text(
            "[project]\n"
            "name = \"open-mako-smoke\"\n"
            "version = \"0.0.0\"\n"
            "license = { text = \"Owner-selected test license placeholder\" }\n",
            encoding="utf-8",
        )
        passing = subprocess.run(
            ["bash", str(gate)],
            cwd=tmp_root,
            check=False,
            text=True,
            capture_output=True,
        )
        assert passing.returncode == 0
        assert "release-readiness-gate: root-license=LICENSE" in passing.stdout
        assert "release-readiness-gate: pyproject-license=present" in passing.stdout
        assert "release-readiness-gate: PASS" in passing.stdout


def test_changelog_v01_draft_stays_inside_public_evidence_boundary() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "## v0.1.0 Draft" in changelog
    assert "not proof that `v0.1.0` has been tagged or\npublished" in changelog
    assert "Evidence Court CLI commands" in changelog
    assert "evidence-court/v0.1" in changelog
    assert "repository-local GitHub composite action" in changelog
    assert "evidence-court-report` artifact" in changelog
    assert "evidence-court-report.json" in changelog
    assert "tests/test_public_metadata.py" in changelog
    assert "tests/test_cli_wrappers.py" in changelog
    assert ".github/workflows/focused.yml" in changelog
    assert ".github/workflows/evidence-court-demo.yml" in changelog
    assert "OpenMako v0.1 audits supplied Evidence Court records" in changelog
    assert "supplied\nartifact provenance, and supplied transcript adapter proof gaps" in changelog
    assert "v0.1 audits repository-defined supplied records and supplied transcript\nfixtures only" in changelog
    assert "Native Claude Code, Codex, Cursor, or SWE-bench export ingestion" in changelog
    assert "Broad unknown-repository SWE repair claims" in changelog
    assert "published Marketplace GitHub Action" in changelog
    assert "Full-suite or hidden benchmark claims" in changelog
    assert "has been released" not in changelog
    assert "published Marketplace action" not in changelog
    assert "broad unknown-repository SWE repair." not in changelog


def test_v01_release_notes_draft_is_publishable_without_overclaiming() -> None:
    notes = (ROOT / "docs" / "v0.1_release_notes.md").read_text(encoding="utf-8")

    assert "# OpenMako v0.1.0 Release Notes Draft" in notes
    assert "Do not publish this text until the v0.1 release checklist has passed" in notes
    assert "OpenMako v0.1 audits supplied Evidence Court records" in notes
    assert "supplied\nartifact provenance, and supplied transcript adapter proof gaps" in notes
    assert "not a replacement for coding agents" in notes
    assert "evidence-court/v0.1" in notes
    assert "openmako evidence-court audit --ci" in notes
    assert "openmako evidence-court record from-jsonl" in notes
    assert "openmako evidence-court validate" in notes
    assert "repository-local GitHub composite action" in notes
    assert "uploads the `evidence-court-report` artifact" in notes
    assert "evidence-court-report.json" in notes
    assert "tests/test_public_metadata.py" in notes
    assert "tests/test_cli_wrappers.py" in notes
    assert ".github/workflows/focused.yml" in notes
    assert ".github/workflows/evidence-court-demo.yml" in notes
    assert "docs/release_checklist.md" in notes
    assert "v0.1 audits repository-defined supplied records and supplied transcript\nfixtures only" in notes
    assert "does not yet ingest native Claude Code, Codex, Cursor, or\nSWE-bench exports" in notes
    assert "broad unknown-repository SWE repair" in notes
    assert "published Marketplace GitHub Action" in notes
    assert "has been released" not in notes
    assert "native Claude Code adapter" not in notes
    assert "native Codex adapter" not in notes
    assert "native Cursor adapter" not in notes
    assert "SWE-bench ingestion" not in notes
    assert "replaces Claude Code" not in notes
    assert "full pytest passed" not in notes


def test_readme_uses_reviewable_public_claims() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "demonstrates one narrow public gate" in readme
    assert "## Implementation Boundary" in readme
    assert "## Beyond The Public Gate" in readme
    beyond = readme[readme.index("## Beyond The Public Gate") :]
    assert "desktop-control experiments with a bounded local dry-run gate" in beyond
    assert "bash scripts/desktop_control_local_gate.sh" in beyond
    assert "desktop-control-local-gate: status=dry_run" in beyond
    assert "desktop-control-local-gate: scenarios=8" in beyond
    assert "desktop-control-local-gate: level=L2" in beyond
    assert "desktop-control-local-gate: misoperation_rate=0.0" in beyond
    assert "desktop-control-local-gate: crash_rate=0.0" in beyond
    assert "not-proof=live desktop control, L4, L5, external endorsement, star or repost traction" in beyond
    assert "It is useful implementation evidence, not a claim\nthat OpenMako has live L4/L5 desktop autonomy." in beyond
    assert "OpenMako's project policy is clean-room implementation for closed-source tools" in readme
    assert "docs/UPSTREAM_ATTRIBUTION.md" in readme
    assert "vendored-license boundaries" in readme
    for forbidden in FORBIDDEN_README_CLAIMS:
        assert forbidden not in readme


def test_progress_file_is_public_boundary_not_internal_scoreboard() -> None:
    progress = (ROOT / "PROGRESS.md").read_text(encoding="utf-8")

    assert "public status boundary" in progress
    assert "The public v0.1 proof command is `./scripts/public_review_gate.sh`" in progress
    assert "Remote focused CI is live GitHub state, not a durable fact in this file." in progress
    assert "A 2026-06-07 GitHub API snapshot showed `.github/workflows/focused.yml`\n  run `27096660497` completed with `conclusion=success`" in progress
    assert "665a12912822218f81442598ece268175f30f1c3" in progress
    assert "A 2026-06-08 reset-window re-check showed focused workflow run\n  `27116209971` completed with `conclusion=success`" in progress
    assert "a32b5b29dd0fe231d2507a3e229c58c233d15db0" in progress
    assert "A 2026-06-08 re-check showed focused workflow run `27116813508`\n  completed with `conclusion=success`" in progress
    assert "a12389ba48867238218dcb704a42b80f5d7bf507" in progress
    assert "A 2026-06-08 reset-window re-check showed focused workflow run\n  `27116934854` completed with `conclusion=success`" in progress
    assert "e7f1e0d52c858864aed91dc3b67f04fd1016480f" in progress
    assert "A 2026-06-08 reset-window re-check showed focused workflow run\n  `27118350388` completed with `conclusion=success`" in progress
    assert "e53f97374942ea1c3316b04992950b915bd3787b" in progress
    assert "A 2026-06-08 reset-window re-check showed focused workflow run\n  `27120585985` completed with `conclusion=success`" in progress
    assert "d8e32e99cf6cd18d2a56cc83520ef65d832a5868" in progress
    assert "Re-check the latest `openmako/main` run before claiming current remote CI;\n  the snapshot is not external review, endorsement, stars, or reposts." in progress
    assert "bash scripts/remote_focused_ci_snapshot.sh" in progress
    assert "the fail-closed re-check tool\n  for the latest focused workflow on current `openmako/main`" in progress
    assert "not-proof=external review; endorsement; stars; reposts" in progress
    assert "returns nonzero\n  if the latest focused run is stale, still running, failed, missing, or rate\n  limited" in progress
    assert "It supports `OPENMAKO_GITHUB_TOKEN`, `GITHUB_TOKEN`, or `GH_TOKEN`\n  for authenticated GitHub API checks to reduce rate-limit failures; tokens are\n  not printed." in progress
    assert "When API data is unavailable, it still prints the remote main SHA,\n  manual Actions URL, local UTC check time, rate-limit reset countdown, and a\n  copyable rerun command when available before exiting nonzero." in progress
    assert "Passing this script is current\n  focused-CI evidence only, not external review or traction." in progress
    assert "The README evidence-link table now documents the snapshot token fallbacks and\n  rate-limit fallback" in progress
    assert "include the remote SHA, local UTC check time, manual Actions URL, rate-limit\n  reset countdown, and a copyable rerun command when available." in progress
    assert "https://github.com/1966536805l-crypto/openmako/issues/1" in progress
    assert "External technical boundary criticism is requested in issue #2" in progress
    assert "https://github.com/1966536805l-crypto/openmako/issues/2" in progress
    assert "not evidence of endorsement or promotion" in progress
    assert ".github/ISSUE_TEMPLATE/technical-boundary-check.yml" in progress
    assert ".github/ISSUE_TEMPLATE/external-review-record.yml" in progress
    assert "already-public\n  external technical reviews only" in progress
    assert "not private messages or self-written\n  summaries" in progress
    assert "docs/TECHNICAL_REVIEW_PACKET.md" in progress
    assert "docs/REPRODUCE_V0_1.md" in progress
    assert "docs/REVIEWER_OUTREACH_DRAFT.md" in progress
    assert "docs/REVIEWER_TARGETS.md" in progress
    assert "separates technical-review targets from\n  broader writer/community targets" in progress
    assert "forbids star, repost, promotion, or\n  endorsement asks" in progress
    assert "docs/AGENT_TREND_RADAR.md" in progress
    assert "maps Hermes/OpenClaw/OpenHands/eval trends to\n  future OpenMako build bets" in progress
    assert "marks them as non-claims until code, fixtures,\n  and CI exist" in progress
    assert "docs/WAVE1_REVIEW_REQUESTS.md" in progress
    assert "not proof that outreach, review, endorsement, stars, or reposts happened" in progress
    assert "docs/WAVE1_PUBLIC_TARGET_QUEUE.md" in progress
    assert "reachable public surfaces" in progress
    assert "not proof that messages\n  were sent or that anyone reviewed the project" in progress
    assert "bash scripts/wave1_thread_reply_ready.sh" in progress
    assert "one thread-specific reply draft" in progress
    assert "target URL, and final-confirmation\n  guard" in progress
    assert "still does not send messages, create issues, or record\n  outreach as evidence" in progress
    assert "`openhands-benchmarks-718` thread draft was refreshed" in progress
    assert "`output.jsonl` to\n  `output.swtbench.jsonl` artifact identity" in progress
    assert "links only the concrete\n  `swtbench_patch_artifact` fixture" in progress
    assert "not a homepage, star ask, or promotion\n  request" in progress
    assert "send-ready text only, not proof of posting" in progress
    assert "`openhands-benchmarks-708` thread draft was refreshed" in progress
    assert "`332 / 424` mixed\n  test+source patch bucket" in progress
    assert "patch-shape metadata, and the concrete\n  `swtbench_patch_artifact` fixture" in progress
    assert "bash scripts/wave1_review_request.sh" in progress
    assert "without sending messages or recording outreach as evidence" in progress
    assert "bash scripts/wave1_send_ready.sh" in progress
    assert "runs the public review gate before printing\n  a target-specific Wave 1 short message" in progress
    assert "technical review entry points before the v0.1 scope section" in progress
    assert "`60-Second Proof` section before the review links" in progress
    assert "`Why It Is Worth Checking` hook before the\n  proof commands" in progress
    assert "asks for concrete claim/proof mismatches, not promotion" in progress
    assert "`If You Came From A Benchmark Thread` path" in progress
    assert "inspect the\n  `artifact_provenance` fixture for artifact-identity questions" in progress
    assert "compare README\n  claims against the proof commands" in progress
    assert "leave concrete mismatches on issue #2" in progress
    assert "not outreach evidence, endorsement, stars, or reposts" in progress
    assert "minimal issue-comment template" in progress
    assert "links the supplied Codex/OpenHands/SWE-agent\n  transcript adapter checks" in progress
    assert "repository-defined supplied formats only, not native\n  exports, live control, benchmark ingestion, or endorsement" in progress
    assert "scripts/public_review_gate.sh" in progress
    assert "parses Evidence Court audit JSON fields for\n  `failure_class`, `failed_at`, `patch_shape.bucket`, and\n  `artifact_provenance.eval_rule_version` instead of grepping raw output" in progress
    assert "examples/evidence_court/swtbench_patch_artifact.json" in progress
    assert "combines `mixed_test_source` patch-shape\n  metadata with `output.jsonl` to `output.swtbench.jsonl` artifact identity" in progress
    assert "not native benchmark ingestion or score validation" in progress
    assert "scripts/supplied_transcript_adapter_matrix.sh" in progress
    assert "repository-defined Codex, Claude, OpenHands, and SWE-agent style transcripts" in progress
    assert "verifies that each adapter rejects a success claim when\n  command/test proof is missing or when validation exists but edited-file\n  evidence is missing" in progress
    assert "parses audit JSON fields instead of grepping\n  raw output" in progress
    assert "supplied-format smoke test, not native\n  product export parsing, live agent control, benchmark ingestion,\n  diff-content proof, or endorsement" in progress
    assert "scripts/public_proof_card.sh" in progress
    assert "screenshot-friendly proof card with commit, scope, non-proof boundaries,\n  review issue, and external-review record form" in progress
    assert "docs/PUBLIC_SHARE_PACKET.md" in progress
    assert "bash scripts/public_share_ready.sh review-request" in progress
    assert "runs the public proof\n  gate before printing the short public review-request text" in progress
    assert "does not post,\n  ask for stars or reposts, or record outreach as evidence" in progress
    assert "docs/openmako-review-card.svg" in progress
    assert "optional visual summary for the public\n  gate and issue #2 boundary review" in progress
    assert "not evidence of external review,\n  endorsement, stars, or reposts" in progress
    assert "<=280 character technical\n  review post" in progress
    assert "docs/LARGE_REPOST_PACKET.md" in progress
    assert "bash scripts/large_repost_ready.sh\n  REVIEW_RECORD_ISSUE_URL --confirm-external-review" in progress
    assert "refuses to print it unless\n  a public external-review record issue URL is supplied" in progress
    assert "a human confirms the\n  linked public review was written by a named external reviewer" in progress
    assert "the issue page\n  contains structured review record fields" in progress
    assert "not proof of reposts, stars,\n  or endorsement" in progress
    assert "blocks\n  general-influencer outreach until at least one public technical boundary\n  review exists" in progress
    assert "`desktop-eval` metrics now expose the roadmap-style count fields and explicit\n  `misoperation_rate`, `crash_rate`, `total_actions`, and missing-autopsy\n  counters" in progress
    assert "local eval auditability only; it is not a live desktop-control benchmark or a\n  public L4/L5 claim" in progress
    assert "`run-metrics` evidence extension" in progress
    assert "optional duration, token, cost, command-count, and missing-telemetry fields" in progress
    assert "preserved in Evidence Court audit JSON" in progress
    assert "`patch-shape` evidence extension" in progress
    assert "machine-readable `patch_shape` bucket" in progress
    assert "`mixed_test_source` for runs that edit both test-like and\n  source-like files" in progress
    assert "does not\n  prove a benchmark score should be higher or lower by itself" in progress
    assert "shortened-manifest, pytest-option\n  injection, cross-segment duplicate, and self-consistent weakened artifact\n  summary negative checks" in progress
    assert "stale internal notes" in progress
    for forbidden in FORBIDDEN_PUBLIC_PROGRESS_CLAIMS:
        assert forbidden not in progress


def test_remote_focused_ci_snapshot_script_is_fail_closed_and_token_aware() -> None:
    script = ROOT / "scripts" / "remote_focused_ci_snapshot.sh"
    text = script.read_text(encoding="utf-8")

    assert script.exists()
    assert script.stat().st_mode & 0o111
    assert "OPENMAKO_GITHUB_TOKEN" in text
    assert "GITHUB_TOKEN" in text
    assert "GH_TOKEN" in text
    assert "Authorization" in text
    assert "per_page=1" in text
    assert "not-proof=external review; endorsement; stars; reposts" in text
    assert "latest focused run does not match remote main" in text
    assert "focused workflow is not completed/success" in text
    assert "manual-url=" in text
    assert "checked-at-utc=" in text
    assert "datetime.now(timezone.utc)" in text
    assert "github_api_rate_limit" in text
    assert "no_focused_workflow_runs" in text
    assert "Retry-After" in text
    assert "X-RateLimit-Reset" in text
    assert "retry-after-seconds=" in text
    assert "rate-limit-reset-unix=" in text
    assert "rate-limit-reset-utc=" in text
    assert "rate-limit-reset-seconds-until=" in text
    assert "rerun-after-command=" in text
    assert "sleep {seconds_until_reset} && bash scripts/remote_focused_ci_snapshot.sh" in text
    assert "datetime.fromtimestamp" in text
    assert "total_seconds()" in text
    assert "GitHub API rate limit; re-check later" in text
    assert "or set OPENMAKO_GITHUB_TOKEN/GITHUB_TOKEN/GH_TOKEN for authenticated API reads" in text
    for forbidden in FORBIDDEN_README_CLAIMS:
        assert forbidden.lower() not in text.lower()


def test_remote_autonomous_learning_snapshot_script_is_fail_closed_and_artifact_aware(tmp_path: Path) -> None:
    script = ROOT / "scripts" / "remote_autonomous_learning_snapshot.sh"
    text = script.read_text(encoding="utf-8")
    saved_script = ROOT / "scripts" / "saved_autonomous_artifact_snapshot.sh"
    saved_text = saved_script.read_text(encoding="utf-8")

    assert script.exists()
    assert script.stat().st_mode & 0o111
    assert saved_script.exists()
    assert saved_script.stat().st_mode & 0o111
    assert (
        "Usage: bash scripts/saved_autonomous_artifact_snapshot.sh "
        "RUNS_JSON ARTIFACTS_JSON ARTIFACT_ZIP [REMOTE_MAIN_SHA]"
    ) in saved_text
    assert "OPENMAKO_AUTONOMOUS_RUNS_JSON" in saved_text
    assert "OPENMAKO_AUTONOMOUS_ARTIFACTS_JSON" in saved_text
    assert "OPENMAKO_AUTONOMOUS_ARTIFACT_ZIP" in saved_text
    assert "scripts/remote_autonomous_learning_snapshot.sh" in saved_text
    assert "saved public CI artifact evidence only" in saved_text
    assert "not-proof=external review; endorsement; stars; reposts; live autonomy" in saved_text
    missing_args = subprocess.run(
        ["bash", "scripts/saved_autonomous_artifact_snapshot.sh"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert missing_args.returncode == 64
    assert "Usage: bash scripts/saved_autonomous_artifact_snapshot.sh" in missing_args.stderr
    assert "OPENMAKO_AUTONOMOUS_WORKFLOW" in text
    assert "autonomous-learning-gate.yml" in text
    assert "OPENMAKO_AUTONOMOUS_ARTIFACT_NAME" in text
    assert "autonomous-learning-gate-summary" in text
    assert "OPENMAKO_AUTONOMOUS_RUNS_JSON" in text
    assert "OPENMAKO_AUTONOMOUS_ARTIFACTS_JSON" in text
    assert "OPENMAKO_AUTONOMOUS_ARTIFACT_ZIP" in text
    assert "OPENMAKO_GITHUB_TOKEN" in text
    assert "GITHUB_TOKEN" in text
    assert "GH_TOKEN" in text
    assert "Authorization" in text
    assert "archive_download_url" in text
    assert "last_summary.json" in text
    assert "artifact summary contract mismatch" in text
    assert "artifact-summary-upstream-hidden-task-count=" in text
    assert "artifact-summary-upstream-stability-solved=" in text
    assert "artifact-summary-upstream-cheat-caught=" in text
    assert "artifact-summary-cross-upstream-hidden-stage2-tasks=" in text
    assert "artifact-summary-cross-upstream-stability-solved=" in text
    assert "artifact-summary-cross-upstream-cheat-caught=" in text
    assert "artifact-summary-task-proof-files=" in text
    assert "artifact-summary-task-source-provenance=" in text
    assert "artifact-summary-task-source-manifest=" in text
    assert "artifact-summary-task-source-manifest-sha256=" in text
    assert "artifact-summary-external-heldout=" in text
    assert "artifact-task-source-manifest=" in text
    assert "task_source_manifest" in text
    assert "task_source_provenance_manifest.json" in text
    assert "task_source_provenance" in text
    assert "selected_tests_sha256" in text
    assert "autonomous-task-source-provenance/v0.1" in text
    assert "repo-authored-regression-pack" in text
    assert "not an independent external held-out benchmark" in text
    assert "per_page=1" in text
    assert "per_page=100" in text
    assert "latest autonomous-learning run does not match remote main" in text
    assert "autonomous-learning workflow is not completed/success" in text
    assert "artifact {artifact_name!r} is missing" in text
    assert "autonomous-learning artifact is expired" in text
    assert "autonomous-learning artifact digest is missing" in text
    assert "artifact fixture is missing workflow_run binding" in text
    assert "artifact fixture workflow_run id does not match run id" in text
    assert "artifact fixture workflow_run head_sha does not match run sha" in text
    assert "artifact-digest=" in text
    assert "artifact-zip-sha256=" in text
    assert "hashlib.sha256" in text
    assert "artifact zip sha256 does not match artifact digest" in text
    assert "artifact-pytest-log=" in text
    assert "artifact.pytest_logs" in text
    assert "artifact.task_source_manifest" in text
    assert "manual-url=" in text
    assert "checked-at-utc=" in text
    assert "github_api_rate_limit" in text
    assert "no_autonomous_workflow_runs" in text
    assert "Retry-After" in text
    assert "X-RateLimit-Reset" in text
    assert "rerun-after-command=" in text
    assert "sleep {seconds_until_reset} && bash scripts/remote_autonomous_learning_snapshot.sh" in text
    assert "github_api_requires_auth" in text
    assert "artifact_zip_requires_auth" in text
    assert "auth-required=OPENMAKO_GITHUB_TOKEN/GITHUB_TOKEN/GH_TOKEN" in text
    assert "rerun-auth-command=OPENMAKO_GITHUB_TOKEN=<token>" in text
    assert "fixture-rerun-command=" in text
    assert "GitHub artifact zip download" in text
    assert "requires authenticated API access" in text
    assert "not-proof=external review; endorsement; stars; reposts; live autonomy" in text
    assert "broad unknown-repository repair; external benchmark standing" in text
    assert "independent external held-out benchmark" in text
    for forbidden in FORBIDDEN_README_CLAIMS:
        assert forbidden.lower() not in text.lower()

    remote_sha = "1234567890abcdef1234567890abcdef12345678"
    task_source_provenance = _autonomous_task_source_provenance_fixture()
    task_source_manifest = _autonomous_task_source_manifest_fixture()
    runs_json = tmp_path / "runs.json"
    artifacts_json = tmp_path / "artifacts.json"
    artifact_zip = tmp_path / "artifact.zip"
    runs_json.write_text(
        json.dumps(
            {
                "workflow_runs": [
                    {
                        "id": 27437928257,
                        "head_sha": remote_sha,
                        "status": "completed",
                        "conclusion": "success",
                        "html_url": "https://github.com/1966536805l-crypto/openmako/actions/runs/27437928257",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    artifact_summary = {
        "schema_version": "autonomous-learning-gate/v0.1",
        "status": "passed",
        "invocation": {"git_commit": remote_sha, "argv": []},
        "segments": {
            "stage1_trajectory_reuse_matrix": "passed",
            "upstream_hidden_pack_reuse": "passed",
            "cross_upstream_no_seed_reuse": "passed",
        },
        "tests": {
            "stage1_trajectory_reuse_matrix": {
                "selected": task_source_provenance["segments"]["stage1_trajectory_reuse_matrix"][
                    "selected_tests"
                ],
                "expected_passed": 5,
                "observed_pytest": {
                    "exit_code": 0,
                    "passed": 5,
                    "skipped": 0,
                    "warnings": 0,
                },
                "log_path": ".quantagent/autonomous_learning_gate/pytest_logs/stage1_trajectory_reuse_matrix.log",
                "log_tail": [
                    "...                                                                      [100%]",
                    "5 passed in 14.63s",
                ],
            },
            "upstream_hidden_pack_reuse": {
                "selected": task_source_provenance["segments"]["upstream_hidden_pack_reuse"][
                    "selected_tests"
                ],
                "expected_passed": 1,
                "observed_pytest": {
                    "exit_code": 0,
                    "passed": 1,
                    "skipped": 0,
                    "warnings": 0,
                },
                "log_path": ".quantagent/autonomous_learning_gate/pytest_logs/upstream_hidden_pack_reuse.log",
                "log_tail": [
                    ".                                                                        [100%]",
                    "1 passed in 167.29s (0:02:47)",
                ],
                "expected_contract": {
                    "upstream_family_count": 5,
                    "hidden_task_count": 10,
                    "no_learning_solved": 0,
                    "approved_learning_solved": 10,
                    "stability_repeats": 10,
                    "stability_solved": 100,
                    "success_rate_spread": 0.0,
                    "cheat_caught": 10,
                },
            },
            "cross_upstream_no_seed_reuse": {
                "selected": task_source_provenance["segments"]["cross_upstream_no_seed_reuse"][
                    "selected_tests"
                ],
                "expected_passed": 4,
                "observed_pytest": {
                    "exit_code": 0,
                    "passed": 4,
                    "skipped": 0,
                    "warnings": 0,
                },
                "log_path": ".quantagent/autonomous_learning_gate/pytest_logs/cross_upstream_no_seed_reuse.log",
                "log_tail": [
                    "....                                                                     [100%]",
                    "4 passed in 48.53s",
                ],
                "expected_contract": {
                    "upstream_family_count": 4,
                    "no_seed_stage1_repairs": 4,
                    "hidden_stage2_tasks": 8,
                    "no_learning_solved": 0,
                    "approved_learning_solved": 8,
                    "stability_repeats": 2,
                    "stability_solved": 16,
                    "cheat_caught": 8,
                },
            },
        },
        "task_proofs": _autonomous_task_proofs_fixture(),
        "task_source_manifest": task_source_manifest,
        "task_source_provenance": task_source_provenance,
        "not_proof": [
            "native live autonomy",
            "broad unknown-repository repair",
            "external benchmark standing",
            "remote CI proof",
            "external review",
            "independent external held-out benchmark",
            "endorsement",
            "stars",
            "reposts",
        ],
    }
    artifact_payload = {
        "artifacts": [
            {
                "id": 7600712280,
                "name": "autonomous-learning-gate-summary",
                "size_in_bytes": 0,
                "expired": False,
                "archive_download_url": "https://api.github.com/repos/1966536805l-crypto/openmako/actions/artifacts/7600712280/zip",
                "digest": "sha256:",
                "created_at": "2026-06-12T19:21:00Z",
                "expires_at": "2026-09-10T19:21:00Z",
                "workflow_run": {
                    "id": 27437928257,
                    "head_sha": remote_sha,
                },
            }
        ]
    }

    def write_artifact_summary(
        summary: dict,
        *,
        omit_log_segment: str | None = None,
        log_overrides: dict[str, str] | None = None,
        manifest_text: str | None = None,
    ) -> str:
        with zipfile.ZipFile(artifact_zip, "w") as archive:
            archive.writestr("last_summary.json", json.dumps(summary))
            archive.writestr(
                "task_source_provenance_manifest.json",
                manifest_text
                if manifest_text is not None
                else AUTONOMOUS_TASK_SOURCE_MANIFEST.read_text(encoding="utf-8"),
            )
            for segment, test_entry in summary.get("tests", {}).items():
                if segment == omit_log_segment:
                    continue
                if log_overrides and segment in log_overrides:
                    log_text = log_overrides[segment]
                else:
                    log_tail = test_entry.get("log_tail") or []
                    log_text = "\n".join(log_tail) + "\n"
                archive.writestr(f"pytest_logs/{segment}.log", log_text)
        artifact_zip_sha256 = hashlib.sha256(artifact_zip.read_bytes()).hexdigest()
        updated_payload = json.loads(json.dumps(artifact_payload))
        updated_payload["artifacts"][0]["size_in_bytes"] = artifact_zip.stat().st_size
        updated_payload["artifacts"][0]["digest"] = f"sha256:{artifact_zip_sha256}"
        artifacts_json.write_text(json.dumps(updated_payload), encoding="utf-8")
        return artifact_zip_sha256

    artifact_zip_sha256 = write_artifact_summary(artifact_summary)
    env = os.environ.copy()
    env.update(
        {
            "OPENMAKO_REMOTE_MAIN_SHA": remote_sha,
            "OPENMAKO_AUTONOMOUS_RUNS_JSON": str(runs_json),
            "OPENMAKO_AUTONOMOUS_ARTIFACTS_JSON": str(artifacts_json),
            "OPENMAKO_AUTONOMOUS_ARTIFACT_ZIP": str(artifact_zip),
        }
    )
    result = subprocess.run(
        ["bash", "scripts/remote_autonomous_learning_snapshot.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "remote-autonomous-learning-snapshot: run-sha=1234567890abcdef1234567890abcdef12345678" in result.stdout
    assert "remote-autonomous-learning-snapshot: artifact-id=7600712280" in result.stdout
    assert f"remote-autonomous-learning-snapshot: artifact-digest=sha256:{artifact_zip_sha256}" in result.stdout
    assert f"remote-autonomous-learning-snapshot: artifact-zip-sha256={artifact_zip_sha256}" in result.stdout
    assert "remote-autonomous-learning-snapshot: artifact-summary=last_summary.json" in result.stdout
    assert (
        "remote-autonomous-learning-snapshot: "
        "artifact-task-source-manifest=task_source_provenance_manifest.json"
    ) in result.stdout
    assert (
        "remote-autonomous-learning-snapshot: "
        "artifact-pytest-log=pytest_logs/stage1_trajectory_reuse_matrix.log"
    ) in result.stdout
    assert (
        "remote-autonomous-learning-snapshot: "
        "artifact-pytest-log=pytest_logs/upstream_hidden_pack_reuse.log"
    ) in result.stdout
    assert (
        "remote-autonomous-learning-snapshot: "
        "artifact-pytest-log=pytest_logs/cross_upstream_no_seed_reuse.log"
    ) in result.stdout
    assert "remote-autonomous-learning-snapshot: artifact-summary-commit=1234567890abcdef1234567890abcdef12345678" in result.stdout
    assert "remote-autonomous-learning-snapshot: artifact-summary-upstream-hidden-task-count=10" in result.stdout
    assert "remote-autonomous-learning-snapshot: artifact-summary-upstream-stability-solved=100" in result.stdout
    assert "remote-autonomous-learning-snapshot: artifact-summary-upstream-cheat-caught=10" in result.stdout
    assert "remote-autonomous-learning-snapshot: artifact-summary-cross-upstream-hidden-stage2-tasks=8" in result.stdout
    assert "remote-autonomous-learning-snapshot: artifact-summary-cross-upstream-stability-solved=16" in result.stdout
    assert "remote-autonomous-learning-snapshot: artifact-summary-cross-upstream-cheat-caught=8" in result.stdout
    assert "remote-autonomous-learning-snapshot: artifact-summary-task-proof-files=5" in result.stdout
    assert "remote-autonomous-learning-snapshot: artifact-summary-task-source-provenance=repo-authored-regression-pack" in result.stdout
    assert (
        "remote-autonomous-learning-snapshot: "
        "artifact-summary-task-source-manifest=scripts/autonomous_task_source_provenance.json"
    ) in result.stdout
    assert (
        "remote-autonomous-learning-snapshot: artifact-summary-task-source-manifest-sha256="
        f"{task_source_manifest['sha256']}"
    ) in result.stdout
    assert "remote-autonomous-learning-snapshot: artifact-summary-external-heldout=false" in result.stdout
    assert "remote-autonomous-learning-snapshot: PASS" in result.stdout

    saved_result = subprocess.run(
        [
            "bash",
            "scripts/saved_autonomous_artifact_snapshot.sh",
            str(runs_json),
            str(artifacts_json),
            str(artifact_zip),
            remote_sha,
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert saved_result.returncode == 0, saved_result.stderr
    assert "saved-autonomous-artifact-snapshot: runs-json=" in saved_result.stdout
    assert "saved-autonomous-artifact-snapshot: artifact-zip=" in saved_result.stdout
    assert "saved-autonomous-artifact-snapshot: remote-main-sha=1234567890abcdef1234567890abcdef12345678" in saved_result.stdout
    assert "remote-autonomous-learning-snapshot: artifact-summary-task-proof-files=5" in saved_result.stdout
    assert "remote-autonomous-learning-snapshot: artifact-summary-external-heldout=false" in saved_result.stdout
    assert "remote-autonomous-learning-snapshot: PASS" in saved_result.stdout

    valid_artifacts = json.loads(artifacts_json.read_text(encoding="utf-8"))

    class ArtifactZipAuthRequiredHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"message":"Requires authentication"}')

        def log_message(self, format: str, *args: object) -> None:
            return

    class LocalArtifactServer(socketserver.TCPServer):
        allow_reuse_address = True

    with LocalArtifactServer(("127.0.0.1", 0), ArtifactZipAuthRequiredHandler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            auth_required_artifacts = json.loads(json.dumps(valid_artifacts))
            auth_required_artifacts["artifacts"][0]["archive_download_url"] = (
                f"http://127.0.0.1:{server.server_address[1]}/artifact.zip"
            )
            artifacts_json.write_text(json.dumps(auth_required_artifacts), encoding="utf-8")
            live_env = env.copy()
            live_env.pop("OPENMAKO_AUTONOMOUS_ARTIFACT_ZIP")
            auth_required = subprocess.run(
                ["bash", "scripts/remote_autonomous_learning_snapshot.sh"],
                cwd=ROOT,
                env=live_env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)
    assert auth_required.returncode == 2
    assert "remote-autonomous-learning-snapshot: unavailable=artifact_zip_requires_auth" in auth_required.stdout
    assert "auth-required=OPENMAKO_GITHUB_TOKEN/GITHUB_TOKEN/GH_TOKEN" in auth_required.stdout
    assert "rerun-auth-command=OPENMAKO_GITHUB_TOKEN=<token>" in auth_required.stdout
    assert "fixture-rerun-command=" in auth_required.stdout
    assert "OPENMAKO_AUTONOMOUS_ARTIFACT_ZIP=autonomous-learning-gate-summary.zip" in auth_required.stdout
    assert "not-proof=external review; endorsement; stars; reposts; live autonomy" in auth_required.stdout
    assert "requires authenticated API access" in auth_required.stderr
    assert "no GitHub token was provided" in auth_required.stderr
    assert "remote-autonomous-learning-snapshot: PASS" not in auth_required.stdout

    broken_summary = json.loads(json.dumps(artifact_summary))
    broken_summary["task_source_provenance"]["external_heldout"] = True
    write_artifact_summary(broken_summary)
    provenance_mismatch = subprocess.run(
        ["bash", "scripts/remote_autonomous_learning_snapshot.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert provenance_mismatch.returncode == 1
    assert "artifact summary contract mismatch" in provenance_mismatch.stderr
    assert "task_source_provenance.manifest" in provenance_mismatch.stderr
    assert "task_source_provenance.external_heldout" in provenance_mismatch.stderr

    broken_summary = json.loads(json.dumps(artifact_summary))
    write_artifact_summary(broken_summary, manifest_text='{"schema_version":"tampered"}\n')
    manifest_mismatch = subprocess.run(
        ["bash", "scripts/remote_autonomous_learning_snapshot.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert manifest_mismatch.returncode == 1
    assert "artifact summary contract mismatch" in manifest_mismatch.stderr
    assert "task_source_manifest.sha256" in manifest_mismatch.stderr
    assert "task_source_provenance.manifest" in manifest_mismatch.stderr

    broken_summary = json.loads(json.dumps(artifact_summary))
    broken_summary["tests"]["upstream_hidden_pack_reuse"]["selected"] = []
    write_artifact_summary(broken_summary)
    selected_mismatch = subprocess.run(
        ["bash", "scripts/remote_autonomous_learning_snapshot.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert selected_mismatch.returncode == 1
    assert "artifact summary contract mismatch" in selected_mismatch.stderr
    assert "tests.upstream_hidden_pack_reuse.selected" in selected_mismatch.stderr
    assert (
        "task_source_provenance.segments.upstream_hidden_pack_reuse.selected_tests"
        in selected_mismatch.stderr
    )

    shortened_manifest_payload = json.loads(json.dumps(task_source_provenance))
    shortened_stage1 = shortened_manifest_payload["segments"]["stage1_trajectory_reuse_matrix"][
        "selected_tests"
    ][:2]
    shortened_manifest_payload["segments"]["stage1_trajectory_reuse_matrix"][
        "selected_tests"
    ] = shortened_stage1
    shortened_manifest_text = (
        json.dumps(shortened_manifest_payload, indent=2, sort_keys=True) + "\n"
    )
    broken_summary = json.loads(json.dumps(artifact_summary))
    broken_summary["task_source_provenance"] = shortened_manifest_payload
    broken_summary["task_source_manifest"]["sha256"] = hashlib.sha256(
        shortened_manifest_text.encode("utf-8")
    ).hexdigest()
    broken_summary["tests"]["stage1_trajectory_reuse_matrix"]["selected"] = shortened_stage1
    broken_summary["tests"]["stage1_trajectory_reuse_matrix"]["expected_passed"] = 2
    broken_summary["tests"]["stage1_trajectory_reuse_matrix"]["observed_pytest"]["passed"] = 2
    broken_summary["tests"]["stage1_trajectory_reuse_matrix"]["observed_pytest"][
        "expected_passed"
    ] = 2
    broken_summary["tests"]["stage1_trajectory_reuse_matrix"]["log_tail"] = [
        "..                                                                       [100%]",
        "2 passed in 0.01s",
    ]
    write_artifact_summary(broken_summary, manifest_text=shortened_manifest_text)
    shortened_manifest = subprocess.run(
        ["bash", "scripts/remote_autonomous_learning_snapshot.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert shortened_manifest.returncode == 1
    assert "artifact summary contract mismatch" in shortened_manifest.stderr
    assert (
        "task_source_provenance.segments.stage1_trajectory_reuse_matrix.selected_tests"
        in shortened_manifest.stderr
    )

    replacement_manifest_payload = json.loads(json.dumps(task_source_provenance))
    replacement_stage1 = replacement_manifest_payload["segments"]["stage1_trajectory_reuse_matrix"][
        "selected_tests"
    ]
    replacement_stage1[0] = (
        "tests/test_upstream_function_file_bundle_regression.py::"
        "UpstreamFunctionFileBundleRegressionTest::"
        "test_vendored_mcp_function_level_repair_reuses_without_non_target_drift"
    )
    replacement_manifest_text = (
        json.dumps(replacement_manifest_payload, indent=2, sort_keys=True) + "\n"
    )
    broken_summary = json.loads(json.dumps(artifact_summary))
    broken_summary["task_source_provenance"] = replacement_manifest_payload
    broken_summary["task_source_manifest"]["sha256"] = hashlib.sha256(
        replacement_manifest_text.encode("utf-8")
    ).hexdigest()
    broken_summary["tests"]["stage1_trajectory_reuse_matrix"]["selected"] = replacement_stage1
    write_artifact_summary(broken_summary, manifest_text=replacement_manifest_text)
    replacement_manifest = subprocess.run(
        ["bash", "scripts/remote_autonomous_learning_snapshot.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert replacement_manifest.returncode == 1
    assert "artifact summary contract mismatch" in replacement_manifest.stderr
    assert (
        "task_source_provenance.segments.stage1_trajectory_reuse_matrix.selected_tests_sha256"
        in replacement_manifest.stderr
    )

    broken_summary = dict(artifact_summary)
    broken_summary["tests"] = json.loads(json.dumps(artifact_summary["tests"]))
    broken_summary["tests"]["upstream_hidden_pack_reuse"]["expected_contract"].pop("cheat_caught")
    write_artifact_summary(broken_summary)
    contract_mismatch = subprocess.run(
        ["bash", "scripts/remote_autonomous_learning_snapshot.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert contract_mismatch.returncode == 1
    assert "artifact summary contract mismatch" in contract_mismatch.stderr
    assert "tests.upstream_hidden_pack_reuse.expected_contract.cheat_caught" in contract_mismatch.stderr

    broken_summary = json.loads(json.dumps(artifact_summary))
    broken_summary["tests"]["cross_upstream_no_seed_reuse"]["expected_contract"].pop("hidden_stage2_tasks")
    write_artifact_summary(broken_summary)
    cross_upstream_mismatch = subprocess.run(
        ["bash", "scripts/remote_autonomous_learning_snapshot.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert cross_upstream_mismatch.returncode == 1
    assert "artifact summary contract mismatch" in cross_upstream_mismatch.stderr
    assert (
        "tests.cross_upstream_no_seed_reuse.expected_contract.hidden_stage2_tasks"
        in cross_upstream_mismatch.stderr
    )

    broken_summary = json.loads(json.dumps(artifact_summary))
    broken_summary["task_proofs"]["cross_upstream_no_seed_reuse"][0]["result_sets"]["approved_learning"][0][
        "changed_files"
    ] = []
    write_artifact_summary(broken_summary)
    proof_mismatch = subprocess.run(
        ["bash", "scripts/remote_autonomous_learning_snapshot.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert proof_mismatch.returncode == 1
    assert "artifact summary contract mismatch" in proof_mismatch.stderr
    assert "task_proofs.pandera_scale_no_seed.approved_learning.changed_files" in proof_mismatch.stderr

    write_artifact_summary(artifact_summary, omit_log_segment="cross_upstream_no_seed_reuse")
    missing_log = subprocess.run(
        ["bash", "scripts/remote_autonomous_learning_snapshot.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert missing_log.returncode == 1
    assert "artifact summary contract mismatch" in missing_log.stderr
    assert "artifact.pytest_logs.cross_upstream_no_seed_reuse" in missing_log.stderr

    write_artifact_summary(
        artifact_summary,
        log_overrides={"upstream_hidden_pack_reuse": "log exists but the expected tail is absent\n"},
    )
    log_tail_mismatch = subprocess.run(
        ["bash", "scripts/remote_autonomous_learning_snapshot.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert log_tail_mismatch.returncode == 1
    assert "artifact summary contract mismatch" in log_tail_mismatch.stderr
    assert "tests.upstream_hidden_pack_reuse.log_tail" in log_tail_mismatch.stderr

    write_artifact_summary(
        artifact_summary,
        log_overrides={
            "stage1_trajectory_reuse_matrix": (
                "...                                                                      [100%]\n"
                "5 passed in 14.63s\n"
                "extra final line after the advertised tail\n"
            )
        },
    )
    non_tail_match = subprocess.run(
        ["bash", "scripts/remote_autonomous_learning_snapshot.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert non_tail_match.returncode == 1
    assert "artifact summary contract mismatch" in non_tail_match.stderr
    assert "tests.stage1_trajectory_reuse_matrix.log_tail" in non_tail_match.stderr

    artifact_zip_sha256 = write_artifact_summary(artifact_summary)
    valid_artifacts = json.loads(artifacts_json.read_text(encoding="utf-8"))
    bad_digest_artifacts = json.loads(json.dumps(valid_artifacts))
    bad_digest_artifacts["artifacts"][0]["digest"] = "sha256:" + "0" * 64
    artifacts_json.write_text(json.dumps(bad_digest_artifacts), encoding="utf-8")
    digest_mismatch = subprocess.run(
        ["bash", "scripts/remote_autonomous_learning_snapshot.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert digest_mismatch.returncode == 1
    assert "artifact zip sha256 does not match artifact digest" in digest_mismatch.stderr

    expired_artifacts = json.loads(json.dumps(valid_artifacts))
    expired_artifacts["artifacts"][0]["expired"] = True
    artifacts_json.write_text(json.dumps(expired_artifacts), encoding="utf-8")
    expired_artifact = subprocess.run(
        ["bash", "scripts/remote_autonomous_learning_snapshot.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert expired_artifact.returncode == 1
    assert "autonomous-learning artifact is expired" in expired_artifact.stderr

    missing_digest_artifacts = json.loads(json.dumps(valid_artifacts))
    missing_digest_artifacts["artifacts"][0].pop("digest")
    artifacts_json.write_text(json.dumps(missing_digest_artifacts), encoding="utf-8")
    missing_digest = subprocess.run(
        ["bash", "scripts/remote_autonomous_learning_snapshot.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert missing_digest.returncode == 1
    assert "autonomous-learning artifact digest is missing" in missing_digest.stderr

    missing_binding_artifacts = json.loads(json.dumps(valid_artifacts))
    missing_binding_artifacts["artifacts"][0].pop("workflow_run")
    artifacts_json.write_text(json.dumps(missing_binding_artifacts), encoding="utf-8")
    missing_binding = subprocess.run(
        ["bash", "scripts/remote_autonomous_learning_snapshot.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert missing_binding.returncode == 1
    assert "artifact fixture is missing workflow_run binding" in missing_binding.stderr

    mismatched_run_artifacts = json.loads(json.dumps(valid_artifacts))
    mismatched_run_artifacts["artifacts"][0]["workflow_run"]["id"] = 999
    artifacts_json.write_text(json.dumps(mismatched_run_artifacts), encoding="utf-8")
    mismatched_run = subprocess.run(
        ["bash", "scripts/remote_autonomous_learning_snapshot.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert mismatched_run.returncode == 1
    assert "artifact fixture workflow_run id does not match run id" in mismatched_run.stderr

    mismatched_sha_artifacts = json.loads(json.dumps(valid_artifacts))
    mismatched_sha_artifacts["artifacts"][0]["workflow_run"]["head_sha"] = "0" * 40
    artifacts_json.write_text(json.dumps(mismatched_sha_artifacts), encoding="utf-8")
    mismatched_sha = subprocess.run(
        ["bash", "scripts/remote_autonomous_learning_snapshot.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert mismatched_sha.returncode == 1
    assert "artifact fixture workflow_run head_sha does not match run sha" in mismatched_sha.stderr

    artifacts_json.write_text(json.dumps(valid_artifacts), encoding="utf-8")
    broken_summary = json.loads(json.dumps(artifact_summary))
    broken_summary["tests"]["cross_upstream_no_seed_reuse"]["observed_pytest"]["passed"] = 1
    write_artifact_summary(broken_summary)
    cross_upstream_observed_mismatch = subprocess.run(
        ["bash", "scripts/remote_autonomous_learning_snapshot.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert cross_upstream_observed_mismatch.returncode == 1
    assert "artifact summary contract mismatch" in cross_upstream_observed_mismatch.stderr
    assert (
        "tests.cross_upstream_no_seed_reuse.observed_pytest.passed"
        in cross_upstream_observed_mismatch.stderr
    )

    artifacts_json.write_text(json.dumps({"artifacts": []}), encoding="utf-8")
    missing_artifact = subprocess.run(
        ["bash", "scripts/remote_autonomous_learning_snapshot.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert missing_artifact.returncode == 1
    assert "artifact 'autonomous-learning-gate-summary' is missing" in missing_artifact.stderr


def test_public_evidence_comment_check_script_is_fail_closed_and_marker_aware(tmp_path: Path) -> None:
    script = ROOT / "scripts" / "public_evidence_comment_check.sh"
    text = script.read_text(encoding="utf-8")

    assert script.exists()
    assert script.stat().st_mode & 0o111
    assert "OPENMAKO_PUBLIC_EVIDENCE_COMMENT_URL" in text
    assert "https://github.com/1966536805l-crypto/openmako/issues/1#issuecomment-4694860161" in text
    assert "ac5a4e6211776dc4f250212ffb48c662534f9b29" in text
    assert "27472027045" in text
    assert "81204551119" in text
    assert "7612385122" in text
    assert "sha256:9e4ef0e1393e6189f9f61fb1bc09c0cb0e83293679e4cc3774a9c64a72995920" in text
    assert "OPENMAKO_PUBLIC_EVIDENCE_HTML" in text
    assert "OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_COMMENT_ID" in text
    assert "OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_COMMIT" in text
    assert "OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_RUN_ID" in text
    assert "OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_JOB_ID" in text
    assert "OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_ARTIFACT_NAME" in text
    assert "OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_ARTIFACT_ID" in text
    assert "OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_ARTIFACT_DIGEST" in text
    assert "OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_BOUNDARY" in text
    assert "html.unescape" in text
    assert "urllib.request.urlopen" in text
    assert "missing public evidence markers=" in text
    assert '"artifact-digest": expected_artifact_digest' in text
    assert "not-proof=external review; endorsement; stars; reposts; live autonomy" in text
    assert "broad unknown-repository repair; external benchmark standing" in text
    for forbidden in FORBIDDEN_README_CLAIMS:
        assert forbidden.lower() not in text.lower()

    fixture = tmp_path / "issue.html"
    env = os.environ.copy()
    env.update(
        {
            "OPENMAKO_PUBLIC_EVIDENCE_COMMENT_URL": "https://example.invalid/openmako/issues/1#issuecomment-12345",
            "OPENMAKO_PUBLIC_EVIDENCE_HTML": str(fixture),
            "OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_COMMENT_ID": "12345",
            "OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_COMMIT": "abc123",
            "OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_RUN_ID": "run-789",
            "OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_JOB_ID": "job-456",
            "OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_ARTIFACT_NAME": "autonomous-learning-gate-summary",
            "OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_ARTIFACT_ID": "artifact-222",
            "OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_ARTIFACT_DIGEST": "sha256:feedface",
            "OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_BOUNDARY": "not external review",
        }
    )
    fixture.write_text(
        """
        <html>
          <div id="issuecomment-12345">
            commit abc123
            run run-789
            job job-456
            autonomous-learning-gate-summary
            artifact artifact-222
            digest sha256:feedface
            public CI artifact evidence only, not external review
          </div>
        </html>
        """,
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", "scripts/public_evidence_comment_check.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "public-evidence-comment-check: marker=commit ok" in result.stdout
    assert "public-evidence-comment-check: marker=run-id ok" in result.stdout
    assert "public-evidence-comment-check: marker=artifact-id ok" in result.stdout
    assert "public-evidence-comment-check: marker=artifact-digest ok" in result.stdout
    assert "public-evidence-comment-check: PASS" in result.stdout

    fixture.write_text(
        """
        <html>
          <div id="issuecomment-12345">
            commit abc123
            run run-789
            job job-456
            autonomous-learning-gate-summary
            artifact artifact-222
            public CI artifact evidence only, not external review
          </div>
        </html>
        """,
        encoding="utf-8",
    )
    missing_digest = subprocess.run(
        ["bash", "scripts/public_evidence_comment_check.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert missing_digest.returncode == 1
    assert "missing public evidence markers=artifact-digest" in missing_digest.stderr


def test_agent_trend_radar_maps_sources_to_non_claim_development_bets() -> None:
    radar = (ROOT / "docs" / "AGENT_TREND_RADAR.md").read_text(encoding="utf-8")

    assert "OpenMako Agent Trend Radar" in radar
    assert "Last refreshed: 2026-06-05." in radar
    assert "not proof that OpenMako already implements these\ncapabilities" in radar
    assert "not evidence of external review, endorsement, stars, or\nreposts" in radar
    assert "https://hermes-agent.nousresearch.com/docs/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-hermes-agent" in radar
    assert "https://docs.openclaw.ai/tools/acp-agents" in radar
    assert "https://github.com/OpenHands/OpenHands" in radar
    assert "https://github.com/harbor-framework/terminal-bench" in radar
    assert "https://github.com/Vexp-ai/vexp-swe-bench" in radar
    assert "https://arxiv.org/abs/2605.14415" in radar
    assert "https://arxiv.org/abs/2605.13139" in radar
    assert "https://arxiv.org/abs/2509.22097" in radar
    assert "https://arxiv.org/abs/2602.02474" in radar
    assert "Evidence Ledger Before Broader Runtime" in radar
    assert "Skill Evolution With Reproducible Approval" in radar
    assert "External Harness Adapter Without Runtime Overclaim" in radar
    assert "Benchmark Telemetry Beyond Pass/Fail" in radar
    assert "Full-Cycle And Secure-Coding Gates" in radar
    assert "Do not claim OpenMako is a Hermes, OpenClaw, OpenHands, SWE-agent, or\n  Terminal-Bench replacement." in radar
    assert "Do not claim ACP, MCP orchestration, long-term memory, skill self-evolution,\n  cloud agent execution, or secure-code benchmarking as current public v0.1\n  capability." in radar
    assert "The `run-metrics` evidence extension, the first supplied-transcript adapter\nmatrix, and supplied diff-content evidence handling are already on `main`" in radar
    assert "current adapter\nmatrix now rejects success claims" in radar
    assert "Supplied evidence ledger identity has also moved into current `main` work" in radar
    assert "repository-defined supplied transcript adapters" in radar
    assert "audits the converted records to the same\n`missing_ledger_identity_evidence` boundary" in radar
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in radar.lower()


def test_technical_review_packet_is_evidence_first_not_promotional() -> None:
    packet = (ROOT / "docs" / "TECHNICAL_REVIEW_PACKET.md").read_text(encoding="utf-8")

    assert "OpenMako v0.1 Technical Review Packet" in packet
    assert "not an endorsement request" in packet
    assert "promotion request" in packet
    assert "star request" in packet
    assert "repost request" in packet
    assert "https://github.com/1966536805l-crypto/openmako/issues/2" in packet
    assert "issues/new?template=technical-boundary-check.yml" in packet
    assert "docs/REVIEWER_OUTREACH_DRAFT.md" in packet
    assert "docs/REPRODUCE_V0_1.md" in packet
    assert "docs/PUBLIC_SHARE_PACKET.md" in packet
    assert "./scripts/public_review_gate.sh" in packet
    assert "external-source benchmark\n gate" not in packet
    assert "external-source benchmark\ngate" in packet
    assert "bash scripts/external_source_benchmark_gate.sh" in packet
    assert "external-source-benchmark-gate: PASS" in packet
    assert "the\nartifact-provenance fixture, the SWTBench patch-artifact fixture" in packet
    assert "SWTBench patch-artifact fixture, the config-only\nrepair fixture, runtime" in packet
    assert "shadowing and verifier/CI tamper fixtures, and the\nsupplied transcript adapter matrix" in packet
    assert "./bin/openmako --no-trust-prompt evidence-court record from-jsonl" in packet
    assert "./bin/openmako --no-trust-prompt evidence-court audit --ci --json run.json" in packet
    assert "examples/evidence_court/artifact_provenance.json" in packet
    assert "examples/evidence_court/swtbench_patch_artifact.json" in packet
    assert "examples/evidence_court/config_only_repair.json" in packet
    assert "combines supplied patch-shape metadata with artifact identity\nmetadata" in packet
    assert "does not validate a SWTBench score or ingest native benchmark\nexports" in packet
    assert "keeps a supplied config-only repair record in `PASS/config_only`" in packet
    assert "does not prove broad\nrepair ability or native benchmark ingestion" in packet
    assert "does not claim native Claude Code" in packet
    assert "## Optional Supplied-Transcript Adapter Checks" in packet
    assert "docs/evidence_court_schema.md" in packet
    assert "record from-codex-transcript" in packet
    assert "record from-claude-transcript" in packet
    assert "record from-openhands-transcript" in packet
    assert "record from-swe-agent-transcript" in packet
    assert "adapter_report.unsupported" in packet
    assert "They do not claim native Codex, Claude,\nOpenHands, or SWE-agent export parsing" in packet
    assert "live agent control, benchmark\ningestion, or external endorsement" in packet
    assert "## Optional Desktop-Control Dry-Run Check" in packet
    assert "bash scripts/desktop_control_local_gate.sh" in packet
    assert "desktop-control-local-gate: status=dry_run" in packet
    assert "desktop-control-local-gate: scenarios=8" in packet
    assert "desktop-control-local-gate: level=L2" in packet
    assert "desktop-control-local-gate: misoperation_rate=0.0" in packet
    assert "desktop-control-local-gate: crash_rate=0.0" in packet
    assert "not-proof=live desktop control, L4, L5, external endorsement, star or repost traction" in packet
    assert "It is not evidence that OpenMako has live L4/L5 desktop autonomy." in packet
    assert "Does README claim more than the focused tests and CI prove?" in packet
    assert "Are `./scripts/public_review_gate.sh` and issue #1 enough public proof for\n  the narrow claim?" in packet
    assert "A useful review points to a specific file, line, command, workflow, or missing\nartifact." in packet
    assert "## Minimal Review Comment Template" in packet
    assert "Verdict: boundary clear / overclaim / unclear" in packet
    assert "README section or line:" in packet
    assert "Test command or workflow:" in packet
    assert "Concrete mismatch or missing proof:" in packet
    assert "Suggested correction:" in packet
    assert "Do not include endorsement, promotion, star, or repost language in the review." in packet
    assert "10000" not in packet
    assert "10,000" not in packet
    assert "大咖" not in packet


def test_reproduce_v01_guide_is_command_first_and_boundary_limited() -> None:
    guide = (ROOT / "docs" / "REPRODUCE_V0_1.md").read_text(encoding="utf-8")

    assert "OpenMako v0.1 Reproduction Guide" in guide
    assert "not an endorsement\nrequest, promotion request, star request, or repost request" in guide
    assert "## Claim Under Test" in guide
    assert "## Fresh Checkout" in guide
    assert "git clone https://github.com/1966536805l-crypto/openmako.git" in guide
    assert "python -m pip install -e . pytest" in guide
    assert "./scripts/public_review_gate.sh" in guide
    assert "<N> passed" in guide
    assert "metadata-test count is intentionally not fixed" in guide
    assert "25 passed" not in guide
    assert "public-review-gate: PASS" in guide
    assert "public-review-gate: running external-source benchmark gate" in guide
    assert "external-source-benchmark-gate: running selected OpenClaw source and package-level regression tests" in guide
    assert "external-source-benchmark-gate: PASS" in guide
    assert "public-review-gate: running external-heldout benchmark gate" in guide
    assert "external-heldout-benchmark-gate: running MCP Python SDK held-out repair regression" in guide
    assert "external-heldout-benchmark-gate: PASS" in guide
    assert "public-review-gate: checking external-heldout gate fail-closed negatives" in guide
    assert "python -m pytest -p no:cacheprovider tests/test_external_heldout_benchmark_gate.py -q" in guide
    assert "4 passed" in guide
    assert "bash scripts/external_source_benchmark_gate.sh" in guide
    assert "bash scripts/external_heldout_benchmark_gate.sh" in guide
    assert "`external_source=true` and\n`independent_external_heldout=false`" in guide
    assert "external-source regression evidence\nonly, not independent external held-out benchmark evidence" in guide
    assert "`external_source_heldout=true`,\n`heldout_from_autonomous_gate=true`, and\n`independent_external_benchmark=false`" in guide
    assert "external-source held-out\nregression evidence only, not external benchmark standing" in guide
    assert "public-review-gate: checking adversarial claim matrix generator" in guide
    assert "public-review-gate: running Evidence Court intensity matrix" in guide
    assert "316 passed" in guide
    assert "public-review-gate: recording Evidence Court bad-run fixture" in guide
    assert "public-review-gate: auditing supplied Evidence Court record" in guide
    assert "public-review-gate: auditing artifact provenance fixture" in guide
    assert "public-review-gate: auditing SWTBench patch artifact fixture" in guide
    assert "public-review-gate: auditing config-only repair fixture" in guide
    assert "public-review-gate: running supplied transcript adapter matrix" in guide
    assert "adapter-matrix: PASS" in guide
    assert "PYTHONPATH" in guide
    assert "stale installed package" in guide
    assert "tests/test_public_metadata.py" in guide
    assert "bash scripts/autonomous_learning_gate.sh" in guide
    assert "autonomous-learning-gate: running stage1 trajectory reuse matrix" in guide
    assert "autonomous-learning-gate: running upstream hidden-pack reuse stress test" in guide
    assert "autonomous-learning-gate: running cross-upstream no-seed reuse stress tests" in guide
    assert "autonomous-learning-gate: PASS" in guide
    assert (
        "This optional gate runs repository tests for stage1 repair, trajectory\n"
        "extraction, eval-gated learning approval, clean stage2 reuse, upstream\n"
        "hidden-pack reuse, cross-upstream no-seed reuse, and cheating rejection."
    ) in guide
    assert (
        "not native live autonomy, broad\n"
        "unknown-repository repair proof, external benchmark standing, remote CI proof,\n"
        "external review, endorsement, stars, or reposts"
    ) in guide
    assert "`.quantagent/autonomous_learning_gate/last_summary.json` by default" in guide
    assert "invoking commit, manifest-derived selected tests, per-segment elapsed\nseconds" in guide
    assert "per-segment pytest log paths and log tails, observed\npass/skip/warning counts" in guide
    assert "the tracked\n`scripts/autonomous_task_source_provenance.json` path and sha256" in guide
    assert "an artifact\ncopy of that manifest" in guide
    assert "manifest-derived selected tests are constrained to the expected minimum\nsegment counts, pytest node-id shape, no pytest options, no whitespace, no\nduplicates inside a segment, and no duplicates across segments" in guide
    assert "shortened or\ninjected manifest fails before pytest runs" in guide
    assert "OPENMAKO_AUTONOMOUS_LEARNING_GATE_SUMMARY_JSON" in guide
    assert "`.github/workflows/autonomous-learning-gate.yml` workflow" in guide
    assert "the workflow, the tracked task-source manifest, gate script, remote snapshot\nscript, core learning modules, selected gate-test paths, or supplied Evidence\nCourt/transcript proof surfaces" in guide
    assert "uploads the summary JSON, manifest copy, and\npytest logs" in guide
    assert (
        "path-filtered public CI artifact\n"
        "evidence only, not broad default push or pull-request CI, external review"
    ) in guide
    assert "bash scripts/remote_autonomous_learning_snapshot.sh" in guide
    assert "remote-autonomous-learning-snapshot: status=completed conclusion=success" in guide
    assert "remote-autonomous-learning-snapshot: artifact-name=autonomous-learning-gate-summary" in guide
    assert "remote-autonomous-learning-snapshot: artifact-digest=sha256:..." in guide
    assert "remote-autonomous-learning-snapshot: artifact-summary=last_summary.json" in guide
    assert "remote-autonomous-learning-snapshot: artifact-task-source-manifest=task_source_provenance_manifest.json" in guide
    assert "remote-autonomous-learning-snapshot: artifact-summary-upstream-hidden-task-count=10" in guide
    assert "remote-autonomous-learning-snapshot: artifact-summary-upstream-stability-solved=100" in guide
    assert "remote-autonomous-learning-snapshot: artifact-summary-upstream-cheat-caught=10" in guide
    assert "remote-autonomous-learning-snapshot: artifact-summary-cross-upstream-hidden-stage2-tasks=8" in guide
    assert "remote-autonomous-learning-snapshot: artifact-summary-cross-upstream-stability-solved=16" in guide
    assert "remote-autonomous-learning-snapshot: artifact-summary-cross-upstream-cheat-caught=8" in guide
    assert "remote-autonomous-learning-snapshot: artifact-summary-task-proof-files=5" in guide
    assert "remote-autonomous-learning-snapshot: artifact-summary-task-source-provenance=repo-authored-regression-pack" in guide
    assert "remote-autonomous-learning-snapshot: artifact-summary-task-source-manifest=scripts/autonomous_task_source_provenance.json" in guide
    assert "remote-autonomous-learning-snapshot: artifact-summary-task-source-manifest-sha256=..." in guide
    assert "remote-autonomous-learning-snapshot: artifact-summary-external-heldout=false" in guide
    assert "stale, still running, failed, missing, rate limited, missing the named artifact,\nexpired, missing an artifact digest, unreadable as an artifact zip, blocked by\nan artifact zip 401 that needs authenticated API access, or missing the expected\n`last_summary.json` contract fields" in guide
    assert "fails closed if the artifact\nmanifest copy is missing, the manifest hash does not match the summary, the\nsummary provenance does not match the artifact manifest, or a segment's\nmanifest `selected_tests` no longer matches the summary's selected tests and\nobserved pass count" in guide
    assert "remote artifact snapshot applies the same minimum\nsegment count, pytest node-id shape, no-option, no-whitespace, and no-duplicate\nselected-test constraints to the artifact-contained manifest" in guide
    assert "self-consistent\nbut weakened artifact summary still fails closed" in guide
    assert "Set `OPENMAKO_GITHUB_TOKEN`,\n`GITHUB_TOKEN`, or `GH_TOKEN` for live artifact zip reads, or set\n`OPENMAKO_AUTONOMOUS_ARTIFACT_ZIP` to verify the same contract against a saved\nartifact fixture" in guide
    assert "Passing it is current public CI artifact evidence only, not\nexternal review, endorsement, stars, reposts, live autonomy, broad\nunknown-repository repair, external benchmark standing" in guide
    assert "independent external\nheld-out benchmark evidence" in guide
    assert (
        "bash scripts/saved_autonomous_artifact_snapshot.sh runs.json artifacts.json "
        "autonomous-learning-gate-summary.zip <openmako-main-sha>"
    ) in guide
    assert "This delegates to `remote_autonomous_learning_snapshot.sh` with explicit\nfixture paths" in guide
    assert "including the artifact metadata's `workflow_run` binding when present" in guide
    assert "does not prove fixture provenance or current live GitHub API state" in guide
    assert (
        "It is saved\n"
        "public CI artifact evidence only, not a substitute for external review,\n"
        "endorsement, stars, reposts, live autonomy, broad unknown-repository repair, or\n"
        "external benchmark standing, and not independent external held-out benchmark\n"
        "evidence"
    ) in guide
    assert "bash scripts/public_evidence_comment_check.sh" in guide
    assert "public-evidence-comment-check: marker=commit ok" in guide
    assert "public-evidence-comment-check: marker=run-id ok" in guide
    assert "public-evidence-comment-check: marker=artifact-id ok" in guide
    assert "public-evidence-comment-check: marker=artifact-digest ok" in guide
    assert "public-evidence-comment-check: PASS" in guide
    assert "Set `OPENMAKO_PUBLIC_EVIDENCE_HTML` to point the same checker at a saved HTML\nfixture" in guide
    assert "This is public comment marker consistency only, not external review,\nendorsement, stars, reposts, live autonomy, broad unknown-repository repair, or\nexternal benchmark standing" in guide
    assert "./bin/openmako --no-trust-prompt evidence-court record from-jsonl" in guide
    assert "./bin/openmako --no-trust-prompt evidence-court audit --ci --json run.json" in guide
    assert "Config-only false-positive boundary:" in guide
    assert "examples/evidence_court/config_only_repair.json" in guide
    assert "The config-only repair fixture keeps supplied project metadata/config repair" in guide
    assert "evidence in `PASS/config_only`" in guide
    assert (
        "The local Evidence Court intensity matrix covers supplied test-output parser\n"
        "  edge cases and 105 full supplied audit-record claim-boundary cases, including\n"
        "  five multi-finding precedence cases."
    ) in guide
    assert (
        "The adversarial claim matrix generator check prevents checked-in fixture\n"
        "  metadata from drifting from the compact generator."
    ) in guide
    assert "./scripts/supplied_transcript_adapter_matrix.sh" in guide
    assert "repository-defined Codex, Claude, OpenHands,\nand SWE-agent style transcripts" in guide
    assert "checks that each adapter rejects a\nsuccess claim when command/test proof is missing, when validation command\nexit-status evidence is missing, or when validation exists but edited-file or\nsupplied diff-content evidence is missing, only names test files, or covers\nonly a subset of edited source files, or when supplied ordered edit/command\nevidence has passing validation before a later source edit for a claimed source\nrepair" in guide
    assert "not native\nproduct export parsing, proof that supplied patches were\napplied outside the supplied record, or live agent control" in guide
    assert "It does not prove broad unknown-repository SWE repair." in guide
    assert "It does not prove external endorsement." in guide
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in guide.lower()


def test_github_issue_template_routes_boundary_criticism_without_promotion() -> None:
    template = (ROOT / ".github" / "ISSUE_TEMPLATE" / "technical-boundary-check.yml").read_text(encoding="utf-8")

    assert "Technical boundary check" in template
    assert "Report whether OpenMako v0.1 public claims match repository evidence." in template
    assert "technical boundary criticism only" in template
    assert "not an\n        endorsement request, promotion request, star request, or repost request" in template
    assert "docs/REPRODUCE_V0_1.md" in template
    assert "boundary clear" in template
    assert "overclaim" in template
    assert "unclear" in template
    assert "Evidence checked" in template
    assert "Reproduction result" in template
    assert "./scripts/public_review_gate.sh" in template
    assert "Concrete mismatch or missing proof" in template
    assert "Suggested correction" in template
    assert "not endorsement, promotion, star request, or repost request" in template
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in template.lower()


def test_issue_template_config_routes_reviewers_to_reproduction_first() -> None:
    config = (ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml").read_text(encoding="utf-8")

    assert "blank_issues_enabled: false" in config
    assert "Reproduce OpenMako v0.1 first" in config
    assert "docs/REPRODUCE_V0_1.md" in config
    assert "Read the technical review packet" in config
    assert "docs/TECHNICAL_REVIEW_PACKET.md" in config
    assert "Share packet for boundary-clear reviews" in config
    assert "docs/PUBLIC_SHARE_PACKET.md" in config
    assert "Use only after a named reviewer has already posted public technical feedback." in config
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in config.lower()


def test_external_review_record_template_records_public_reviews_only() -> None:
    template = (ROOT / ".github" / "ISSUE_TEMPLATE" / "external-review-record.yml").read_text(encoding="utf-8")

    assert "External review record" in template
    assert "Record a public external technical review of OpenMako v0.1." in template
    assert "external-review, technical-boundary" in template
    assert "already posted a\n        public technical review" in template
    assert "not an endorsement request, promotion request, star request, or\n        repost request" in template
    assert "Do not use private DMs or unverifiable summaries as\n        evidence" in template
    assert "Reviewer" in template
    assert "Public review link" in template
    assert "Review verdict" in template
    assert "boundary clear" in template
    assert "overclaim found" in template
    assert "Evidence checked by reviewer" in template
    assert "Follow-up needed" in template
    assert "already-public external technical review" in template
    assert "does not ask for endorsement, promotion, stars, reposts, or broader claims" in template
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in template.lower()


def test_contributing_guide_routes_to_evidence_not_promotion() -> None:
    guide = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

    assert "Contributing To OpenMako" in guide
    assert "technical boundary criticism before broader\npromotion" in guide
    assert "not an endorsement request, promotion request, star request, or repost\nrequest" in guide
    assert "./scripts/public_review_gate.sh" in guide
    assert "docs/REPRODUCE_V0_1.md" in guide
    assert "docs/TECHNICAL_REVIEW_PACKET.md" in guide
    assert "issues/new?template=technical-boundary-check.yml" in guide
    assert "A focused test that catches a public-boundary drift." in guide
    assert "Claiming broad unknown-repository SWE repair" in guide
    assert "tests/test_public_metadata.py" in guide
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in guide.lower()


def test_public_share_packet_preserves_review_boundary_without_promotion() -> None:
    share_packet = (ROOT / "docs" / "PUBLIC_SHARE_PACKET.md").read_text(encoding="utf-8")

    assert "OpenMako Public Share Packet" in share_packet
    assert "not endorsement, promotion, star request, or repost request" in share_packet
    assert "bash scripts/public_share_ready.sh review-request" in share_packet
    assert "That command runs the public proof gate before printing text." in share_packet
    assert "It does not post,\nask for stars, ask for reposts, or record outreach as evidence." in share_packet
    assert "## Short Public Posts" in share_packet
    assert "Use short posts only as a technical review request" in share_packet
    assert "### Technical Review Request" in share_packet
    assert "Looking for technical boundary criticism" in share_packet
    assert "### Boundary-Clear Follow-Up" in share_packet
    assert "Use this only after a named reviewer has publicly said the boundary is clear." in share_packet
    assert "bash scripts/public_share_ready.sh boundary-clear" in share_packet
    assert "not a broad agent benchmark" in share_packet
    assert "external-source benchmark gate" in share_packet
    assert "patch-scope discipline" in share_packet
    assert "test-proof evidence" in share_packet
    assert "Evidence Court audits for supplied records, provenance, and supplied\ntranscript adapters" in share_packet
    assert "runtime-shadowing and verifier/CI tamper\nreview-risk fixtures" in share_packet
    assert "supplied-record/provenance audits, supplied transcript adapter checks, and\nsupplied runtime/verifier/CI tamper-risk checks" in share_packet
    assert "Evidence Court CLI that audits supplied records" not in share_packet
    assert "https://github.com/1966536805l-crypto/openmako/issues/2" in share_packet
    assert "https://github.com/1966536805l-crypto/openmako/releases/tag/v0.1.0" in share_packet
    assert "./scripts/public_review_gate.sh" in share_packet
    assert "docs/TECHNICAL_REVIEW_PACKET.md" in share_packet
    assert "docs/openmako-review-card.svg" in share_packet
    assert "Use the review card only as a visual summary after checking the public gate." in share_packet
    assert "not evidence of external review, endorsement, stars, or reposts" in share_packet
    assert "Do not say it proves broad unknown-repository SWE repair." in share_packet
    assert "Do not say it replaces Claude Code, Codex, Cursor, Devin, or other agents." in share_packet
    assert "Do not ask readers to star, repost, or promote the repository." in share_packet
    assert "technical critique that links a concrete" in share_packet
    short_post_match = re.search(
        r"### Technical Review Request\n\n```text\n(?P<post>.*?)\n```",
        share_packet,
        flags=re.DOTALL,
    )
    assert short_post_match, "public share packet must include a short technical review post"
    assert len(short_post_match.group("post")) <= 280
    assert "provenance, adapters, and tamper-risk checks" in short_post_match.group("post")
    assert "Looking for technical boundary criticism" in short_post_match.group("post")
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in share_packet.lower()


def test_openmako_review_card_is_boundary_focused_not_promotional() -> None:
    card = (ROOT / "docs" / "openmako-review-card.svg").read_text(encoding="utf-8")

    assert "OpenMako public review card" in card
    assert "Evidence checks for agent run records" in card
    assert "Current proof: learning effect, scope, test proof," in card
    assert "provenance, adapters, and tamper-risk checks." in card
    assert "test proof, and supplied-record audit." not in card
    assert "Boundary check" in card
    assert "github.com/1966536805l-crypto/openmako/issues/2" in card
    assert "Does not claim broad repair or external review." in card
    assert "Tell us where" not in card
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in card.lower()


def test_public_review_gate_script_wraps_reviewer_proof_commands() -> None:
    script = ROOT / "scripts" / "public_review_gate.sh"
    text = script.read_text(encoding="utf-8")

    assert script.exists()
    assert script.stat().st_mode & 0o111
    assert 'export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"' in text
    assert "tests/test_agent_planner_contract.py::AgentPlannerContractTest" in text
    assert "public-review-gate: running external-source benchmark gate" in text
    assert "OPENMAKO_EXTERNAL_SOURCE_BENCHMARK_SUMMARY_JSON" in text
    assert "bash scripts/external_source_benchmark_gate.sh" in text
    assert "public-review-gate: running external-heldout benchmark gate" in text
    assert "OPENMAKO_EXTERNAL_HELDOUT_BENCHMARK_SUMMARY_JSON" in text
    assert "bash scripts/external_heldout_benchmark_gate.sh" in text
    assert "public-review-gate: checking external-heldout gate fail-closed negatives" in text
    assert "tests/test_external_heldout_benchmark_gate.py" in text
    assert "tests/test_public_metadata.py" in text
    assert "tests/test_evidence_court_intensity_matrix.py" in text
    assert "./bin/openmako --no-trust-prompt evidence-court record from-jsonl" in text
    assert "./bin/openmako --no-trust-prompt evidence-court audit --ci --json" in text
    assert "expected Evidence Court audit exit 1" in text
    assert "assert_json_field" in text
    assert "json.loads(path.read_text" in text
    assert 'assert_json_field "$TMP_DIR/audit.json" failure_class scope_violation' in text
    assert 'assert_json_field "$TMP_DIR/audit.json" failed_at scope_check' in text
    assert "public-review-gate: auditing SWTBench patch artifact fixture" in text
    assert "examples/evidence_court/swtbench_patch_artifact.json" in text
    assert 'assert_json_field "$TMP_DIR/swtbench_patch_artifact.json" patch_shape.bucket mixed_test_source' in text
    assert "artifact_provenance.eval_rule_version swtbench-strip-model-patch/v2" in text
    assert "public-review-gate: auditing config-only repair fixture" in text
    assert "examples/evidence_court/config_only_repair.json" in text
    assert 'assert_json_field "$TMP_DIR/config_only_repair.json" patch_shape.bucket config_only' in text
    assert 'assert_json_field "$TMP_DIR/config_only_repair.json" failure_class ""' in text
    assert "public-review-gate: checking adversarial claim matrix generator" in text
    assert "scripts/generate_adversarial_claim_matrix.py --check" in text
    assert "public-review-gate: running Evidence Court intensity matrix" in text
    assert "public-review-gate: running supplied transcript adapter matrix" in text
    assert "bash scripts/supplied_transcript_adapter_matrix.sh" in text
    assert "public-review-gate: PASS" in text
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in text.lower()


def test_external_source_benchmark_gate_locks_source_boundary_and_summary_contract() -> None:
    script = ROOT / "scripts" / "external_source_benchmark_gate.sh"
    text = script.read_text(encoding="utf-8")
    progress = (ROOT / "PROGRESS.md").read_text(encoding="utf-8")

    assert script.exists()
    assert script.stat().st_mode & 0o111
    assert "external-source-benchmark-gate/v0.1" in text
    assert "OPENMAKO_EXTERNAL_SOURCE_BENCHMARK_SUMMARY_JSON" in text
    assert "third_party/openclaw/MANIFEST.sha256" in text
    assert "third_party/openclaw/LICENSE" in text
    assert "MIT License" in text
    assert "https://github.com/openclaw/openclaw" in text
    assert "Upstream version: `2026.5.20`" in text
    assert "test_openclaw_selected_js_no_seed_repair_changes_only_target_file" in text
    assert "test_package_level_http_manifest_js_trajectory_skill_reuses_on_hidden_tasks" in text
    assert "external_source" in text
    assert "independent_external_heldout" in text
    assert "not_proof" in text
    assert "current remote CI proof" in text
    assert "manifest digest mismatch" in text
    assert "observed_pytest" in text
    assert "expected_passed" in text
    assert "external-source-benchmark-gate: PASS" in text

    assert "`bash scripts/external_source_benchmark_gate.sh` to the public review gate" in progress
    assert "OpenClaw manifest, MIT license, selected\n  source digest" in progress
    assert "`external_source=true` and `independent_external_heldout=false`" in progress
    assert "external-source regression evidence only, not independent external held-out\n  benchmark evidence" in progress


def test_external_heldout_benchmark_gate_locks_source_boundary_and_summary_contract() -> None:
    script = ROOT / "scripts" / "external_heldout_benchmark_gate.sh"
    text = script.read_text(encoding="utf-8")
    progress = (ROOT / "PROGRESS.md").read_text(encoding="utf-8")

    assert script.exists()
    assert script.stat().st_mode & 0o111
    assert "external-heldout-benchmark-gate/v0.1" in text
    assert "OPENMAKO_EXTERNAL_HELDOUT_BENCHMARK_SUMMARY_JSON" in text
    assert "third_party/mcp_python_sdk/MANIFEST.sha256" in text
    assert "third_party/mcp_python_sdk/LICENSE" in text
    assert "MIT License" in text
    assert "Anthropic, PBC" in text
    assert "https://github.com/modelcontextprotocol/python-sdk" in text
    assert "third_party/mcp_python_sdk/src/mcp/shared/tool_name_validation.py" in text
    assert "test_vendored_mcp_function_level_repair_reuses_without_non_target_drift" in text
    assert "external_source_heldout" in text
    assert "heldout_from_autonomous_gate" in text
    assert "independent_external_benchmark" in text
    assert "selected tests overlap autonomous provenance" in text
    assert "owner license decision" in text
    assert "external benchmark standing" in text
    assert "manifest digest mismatch" in text
    assert "observed_pytest" in text
    assert "expected_passed" in text
    assert "external-heldout-benchmark-gate: PASS" in text
    negative_tests = (ROOT / "tests" / "test_external_heldout_benchmark_gate.py").read_text(encoding="utf-8")
    assert "test_external_heldout_gate_fails_closed_on_manifest_digest_mismatch" in negative_tests
    assert "test_external_heldout_gate_fails_closed_on_license_boundary_mismatch" in negative_tests
    assert "test_external_heldout_gate_fails_closed_on_missing_attribution_boundary" in negative_tests
    assert "test_external_heldout_gate_fails_closed_on_autonomous_manifest_overlap" in negative_tests
    assert "external-heldout-benchmark-gate: PASS\" not in result.stdout" in negative_tests

    assert "`bash scripts/external_heldout_benchmark_gate.sh` to the public review gate" in progress
    assert "MCP Python SDK manifest, MIT license, selected\n  source digest" in progress
    assert "`external_source_heldout=true`, `heldout_from_autonomous_gate=true`, and\n  `independent_external_benchmark=false`" in progress
    assert "external-source held-out\n  regression evidence only, not external benchmark standing" in progress
    assert "fail-closed negative tests that tamper with the MCP manifest digest, license\n  boundary, attribution boundary, and autonomous selected-test overlap" in progress


def test_autonomous_learning_gate_script_wraps_high_intensity_learning_checks() -> None:
    script = ROOT / "scripts" / "autonomous_learning_gate.sh"
    text = script.read_text(encoding="utf-8")
    provenance = _autonomous_task_source_provenance_fixture()

    assert script.exists()
    assert script.stat().st_mode & 0o111
    assert 'export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"' in text
    assert "autonomous-learning-gate: running stage1 trajectory reuse matrix" in text
    assert "schema_version\": \"autonomous-learning-gate/v0.1\"" in text
    assert "OPENMAKO_AUTONOMOUS_LEARNING_GATE_SUMMARY_JSON" in text
    assert "OPENMAKO_AUTONOMOUS_LEARNING_GATE_TEST_CORRUPT_SUMMARY" in text
    assert "OPENMAKO_AUTONOMOUS_TASK_SOURCE_MANIFEST" in text
    assert "scripts/autonomous_task_source_provenance.json" in text
    assert "task_source_manifest" in text
    assert "task_source_provenance_manifest.json" in text
    assert "hashlib.sha256" in text
    assert "missing_contract_fields" in text
    assert "missing_observed_result" in text
    assert "missing_task_source_manifest" in text
    assert "expected_contract" in text
    assert "observed_pytest" in text
    assert "log_tail" in text
    assert "PYTEST_LOG_DIR" in text
    assert "summary_validation" in text
    assert "validate_summary" in text
    assert "validate_failure_summary" in text
    assert "autonomous-learning-gate: invalid summary fields=" in text
    assert "autonomous-learning-gate: invalid failure summary fields=" in text
    assert "load_manifest_test_arrays" in text
    assert "STAGE1_TESTS" in text
    assert "UPSTREAM_TESTS" in text
    assert "CROSS_UPSTREAM_TESTS" in text
    assert "node_id_re" in text
    assert "minimum_count" in text
    assert "duplicate selected_tests across segments" in text
    assert "selected_tests_sha256" in text
    assert 'item.startswith("-")' in text
    assert '"${STAGE1_TESTS[@]}"' in text
    assert '"${UPSTREAM_TESTS[@]}"' in text
    assert '"${CROSS_UPSTREAM_TESTS[@]}"' in text
    assert "tests.{segment}.selected" in text
    assert "tests.{segment}.expected_passed" in text
    assert "invalid selected_tests for {segment}" in text
    assert "invalid selected_tests_sha256 for {segment}" in text
    assert "task_source_provenance.segments.{segment}.selected_tests_sha256" in text
    assert "test_real_hidden_stage1_agent_runs_extract_then_reuse_on_clean_stage2" not in text
    assert "test_no_seed_multi_file_stage1_extracts_then_reuses_on_clean_stage2" not in text
    assert "test_no_seed_package_module_file_bundle_extracts_then_reuses_on_clean_stage2" not in text
    assert "autonomous-learning-gate: running upstream hidden-pack reuse stress test" in text
    assert "test_fixed_version_combined_upstream_hidden_pack_reuses_without_cheating" not in text
    assert "autonomous-learning-gate: running cross-upstream no-seed reuse stress tests" in text
    assert "test_vendored_pandera_scale_no_seed_stage1_extracts_function_repair_without_non_target_drift" not in text
    assert "test_vendored_pandera_bool_predicate_no_seed_stage1_reuses_with_stability" not in text
    assert "test_vendored_great_expectations_result_format_no_seed_stage1_extracts_function_repair" not in text
    assert "test_vendored_aider_random_color_no_seed_stage1_reuses_on_opaque_stage2" not in text
    assert provenance["segments"]["stage1_trajectory_reuse_matrix"]["selected_tests"] == [
        "tests/test_learning_effect_e2e.py::LearningEffectE2ETest::test_real_hidden_stage1_agent_runs_extract_then_reuse_on_clean_stage2",
        "tests/test_learning_effect_e2e.py::LearningEffectE2ETest::test_no_seed_multi_file_stage1_extracts_then_reuses_on_clean_stage2",
        "tests/test_learning_effect_e2e.py::LearningEffectE2ETest::test_no_seed_package_module_file_bundle_extracts_then_reuses_on_clean_stage2",
        "tests/test_skill_learning.py::SkillLearningTest::test_detects_repeated_failure_from_retained_registry_without_installing_skill",
        "tests/test_skill_learning.py::SkillLearningTest::test_retained_failure_adjustment_blocks_unchanged_retry",
    ]
    assert provenance["segments"]["upstream_hidden_pack_reuse"]["selected_tests"] == [
        "tests/test_upstream_function_file_bundle_regression.py::UpstreamFunctionFileBundleRegressionTest::test_fixed_version_combined_upstream_hidden_pack_reuses_without_cheating",
    ]
    assert provenance["segments"]["cross_upstream_no_seed_reuse"]["selected_tests"] == [
        "tests/test_upstream_function_file_bundle_regression.py::UpstreamFunctionFileBundleRegressionTest::test_vendored_pandera_scale_no_seed_stage1_extracts_function_repair_without_non_target_drift",
        "tests/test_upstream_function_file_bundle_regression.py::UpstreamFunctionFileBundleRegressionTest::test_vendored_pandera_bool_predicate_no_seed_stage1_reuses_with_stability",
        "tests/test_upstream_function_file_bundle_regression.py::UpstreamFunctionFileBundleRegressionTest::test_vendored_great_expectations_result_format_no_seed_stage1_extracts_function_repair",
        "tests/test_upstream_function_file_bundle_regression.py::UpstreamFunctionFileBundleRegressionTest::test_vendored_aider_random_color_no_seed_stage1_reuses_on_opaque_stage2",
    ]
    expected_selected_digests = {
        "stage1_trajectory_reuse_matrix": "932a114a39d3f12371603fbd55ba4e59bdd683227536f14a47d4f8580a8f4b2c",
        "upstream_hidden_pack_reuse": "403c0d82611f585ffe0ca8e1a40057d9c302e7195c6d58daa62fd71e5987f181",
        "cross_upstream_no_seed_reuse": "4f4d5382f5558d4f8f8fc77f510d0199728de201de902f0887d312829029d70a",
    }
    for segment, expected_digest in expected_selected_digests.items():
        selected = provenance["segments"][segment]["selected_tests"]
        assert provenance["segments"][segment]["selected_tests_sha256"] == expected_digest
        assert provenance["segments"][segment]["selected_tests_sha256"] == _selected_tests_sha256(
            selected
        )
    assert '"cross_upstream_no_seed_reuse": "pending"' in text
    assert '"upstream_family_count": 5' in text
    assert '"hidden_task_count": 10' in text
    assert '"no_learning_solved": 0' in text
    assert '"approved_learning_solved": 10' in text
    assert '"stability_repeats": 10' in text
    assert '"stability_solved": 100' in text
    assert '"cheat_caught": 10' in text
    assert '"no_seed_stage1_repairs": 4' in text
    assert '"hidden_stage2_tasks": 8' in text
    assert '"cheat_caught": 8' in text
    assert "autonomous-learning-gate: PASS" in text
    assert "autonomous-learning-gate: summary=$SUMMARY_JSON" in text
    assert "not-proof=native live autonomy, broad unknown-repository repair" in text
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in text.lower()


def test_autonomous_learning_gate_summary_smoke_executes_validator(tmp_path: Path) -> None:
    fake_python = tmp_path / "python"
    proof_fixture = tmp_path / "task_proofs.json"
    proof_fixture.write_text(json.dumps(_autonomous_task_proofs_fixture()), encoding="utf-8")
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"$1\" = \"-m\" ] && [ \"$2\" = \"pytest\" ]; then\n"
        "  args=\"$*\"\n"
        "  echo '.                                                                        [100%]'\n"
        "  if [[ \"$args\" == *test_vendored_great_expectations_result_format_no_seed_stage1_extracts_function_repair* ]]; then\n"
        "    echo '4 passed in 0.01s'\n"
        "  elif [[ \"$args\" == *test_upstream_function_file_bundle_regression* ]]; then\n"
        "    echo '1 passed in 0.01s'\n"
        "  else\n"
        "    echo '5 passed in 0.01s'\n"
        "  fi\n"
        f"  {shlex.quote(sys.executable)} - {shlex.quote(str(proof_fixture))} \"$args\" <<'PY'\n"
        "import json\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "proof_root = os.environ.get('OPENMAKO_AUTONOMOUS_TASK_PROOF_DIR')\n"
        "if proof_root:\n"
        "    fixture = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
        "    args = sys.argv[2]\n"
        "    if 'test_fixed_version_combined_upstream_hidden_pack_reuses_without_cheating' in args:\n"
        "        segment = 'upstream_hidden_pack_reuse'\n"
        "    elif 'test_vendored_great_expectations_result_format_no_seed_stage1_extracts_function_repair' in args:\n"
        "        segment = 'cross_upstream_no_seed_reuse'\n"
        "    else:\n"
        "        segment = None\n"
        "    if segment:\n"
        "        segment_dir = Path(proof_root) / segment\n"
        "        segment_dir.mkdir(parents=True, exist_ok=True)\n"
        "        for proof in fixture[segment]:\n"
        "            path = segment_dir / (proof['test_name'] + '.json')\n"
        "            path.write_text(json.dumps(proof, indent=2, sort_keys=True) + '\\n', encoding='utf-8')\n"
        "PY\n"
        "  exit 0\n"
        "fi\n"
        f"exec {shlex.quote(sys.executable)} \"$@\"\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    env = os.environ.copy()
    env["PYTHON"] = str(fake_python)

    summary = tmp_path / "summary.json"
    env["OPENMAKO_AUTONOMOUS_LEARNING_GATE_SUMMARY_JSON"] = str(summary)
    result = subprocess.run(
        ["bash", "scripts/autonomous_learning_gate.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "autonomous-learning-gate: summary=" in result.stdout
    assert "autonomous-learning-gate: task-source-provenance=repo-authored-regression-pack external-heldout=false" in result.stdout
    payload = json.loads(summary.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "autonomous-learning-gate/v0.1"
    assert payload["status"] == "passed"
    assert payload["segments"] == {
        "stage1_trajectory_reuse_matrix": "passed",
        "upstream_hidden_pack_reuse": "passed",
        "cross_upstream_no_seed_reuse": "passed",
    }
    assert payload["artifacts"]["task_proof_dir"].endswith("task_proofs")
    assert payload["task_source_manifest"]["path"].endswith(
        "scripts/autonomous_task_source_provenance.json"
    )
    assert payload["task_source_manifest"]["artifact_path"].endswith(
        "task_source_provenance_manifest.json"
    )
    assert payload["task_source_manifest"]["sha256"] == _autonomous_task_source_manifest_fixture()[
        "sha256"
    ]
    assert payload["task_source_provenance"] == _autonomous_task_source_provenance_fixture()
    assert payload["tests"]["upstream_hidden_pack_reuse"]["expected_contract"]["approved_learning_solved"] == 10
    assert payload["tests"]["upstream_hidden_pack_reuse"]["expected_contract"]["stability_solved"] == 100
    assert payload["tests"]["upstream_hidden_pack_reuse"]["expected_contract"]["cheat_caught"] == 10
    stage1 = payload["tests"]["stage1_trajectory_reuse_matrix"]
    upstream = payload["tests"]["upstream_hidden_pack_reuse"]
    cross_upstream = payload["tests"]["cross_upstream_no_seed_reuse"]
    assert stage1["observed_pytest"]["passed"] == 5
    assert stage1["observed_pytest"]["exit_code"] == 0
    assert upstream["observed_pytest"]["passed"] == 1
    assert upstream["observed_pytest"]["exit_code"] == 0
    assert cross_upstream["observed_pytest"]["passed"] == 4
    assert cross_upstream["observed_pytest"]["exit_code"] == 0
    assert cross_upstream["expected_contract"]["hidden_stage2_tasks"] == 8
    assert cross_upstream["expected_contract"]["stability_solved"] == 16
    assert cross_upstream["expected_contract"]["cheat_caught"] == 8
    assert Path(stage1["log_path"]).name == "stage1_trajectory_reuse_matrix.log"
    assert Path(upstream["log_path"]).name == "upstream_hidden_pack_reuse.log"
    assert Path(cross_upstream["log_path"]).name == "cross_upstream_no_seed_reuse.log"
    assert any("5 passed" in line for line in stage1["log_tail"])
    assert any("1 passed" in line for line in upstream["log_tail"])
    assert any("4 passed" in line for line in cross_upstream["log_tail"])
    assert len(payload["task_proofs"]["upstream_hidden_pack_reuse"]) == 1
    assert len(payload["task_proofs"]["cross_upstream_no_seed_reuse"]) == 4
    assert (
        sum(
            proof["observed_counts"]["cheat_caught"]
            for proof in payload["task_proofs"]["cross_upstream_no_seed_reuse"]
        )
        == 8
    )
    assert "remote CI proof" in payload["not_proof"]
    assert "independent external held-out benchmark" in payload["not_proof"]

    def run_with_manifest(manifest_payload: dict, filename: str) -> subprocess.CompletedProcess[str]:
        manifest_path = tmp_path / filename
        manifest_path.write_text(
            json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        invalid_env = env.copy()
        invalid_env["OPENMAKO_AUTONOMOUS_TASK_SOURCE_MANIFEST"] = str(manifest_path)
        invalid_env["OPENMAKO_AUTONOMOUS_LEARNING_GATE_SUMMARY_JSON"] = str(
            tmp_path / f"{filename}.summary.json"
        )
        return subprocess.run(
            ["bash", "scripts/autonomous_learning_gate.sh"],
            cwd=ROOT,
            env=invalid_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    shortened_manifest = json.loads(json.dumps(_autonomous_task_source_provenance_fixture()))
    shortened_manifest["segments"]["stage1_trajectory_reuse_matrix"]["selected_tests"] = (
        shortened_manifest["segments"]["stage1_trajectory_reuse_matrix"]["selected_tests"][:2]
    )
    shortened = run_with_manifest(shortened_manifest, "shortened-manifest.json")
    assert shortened.returncode == 1
    assert "invalid selected_tests for stage1_trajectory_reuse_matrix" in shortened.stderr

    option_manifest = json.loads(json.dumps(_autonomous_task_source_provenance_fixture()))
    option_manifest["segments"]["upstream_hidden_pack_reuse"]["selected_tests"] = ["--maxfail=1"]
    option_injection = run_with_manifest(option_manifest, "option-manifest.json")
    assert option_injection.returncode == 1
    assert "invalid selected_tests for upstream_hidden_pack_reuse" in option_injection.stderr

    duplicate_manifest = json.loads(json.dumps(_autonomous_task_source_provenance_fixture()))
    duplicate_manifest["segments"]["upstream_hidden_pack_reuse"]["selected_tests"] = [
        duplicate_manifest["segments"]["stage1_trajectory_reuse_matrix"]["selected_tests"][0]
    ]
    duplicate = run_with_manifest(duplicate_manifest, "duplicate-manifest.json")
    assert duplicate.returncode == 1
    assert "duplicate selected_tests across segments for upstream_hidden_pack_reuse" in duplicate.stderr

    replacement_manifest = json.loads(json.dumps(_autonomous_task_source_provenance_fixture()))
    replacement_manifest["segments"]["stage1_trajectory_reuse_matrix"]["selected_tests"][0] = (
        "tests/test_upstream_function_file_bundle_regression.py::"
        "UpstreamFunctionFileBundleRegressionTest::"
        "test_vendored_mcp_function_level_repair_reuses_without_non_target_drift"
    )
    replacement = run_with_manifest(replacement_manifest, "replacement-manifest.json")
    assert replacement.returncode == 1
    assert "invalid selected_tests_sha256 for stage1_trajectory_reuse_matrix" in replacement.stderr

    corrupt_summary = tmp_path / "corrupt-summary.json"
    corrupt_env = env.copy()
    corrupt_env["OPENMAKO_AUTONOMOUS_LEARNING_GATE_SUMMARY_JSON"] = str(corrupt_summary)
    corrupt_env["OPENMAKO_AUTONOMOUS_LEARNING_GATE_TEST_CORRUPT_SUMMARY"] = "missing_contract_fields"
    corrupt = subprocess.run(
        ["bash", "scripts/autonomous_learning_gate.sh"],
        cwd=ROOT,
        env=corrupt_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert corrupt.returncode == 1
    assert (
        "autonomous-learning-gate: invalid summary fields="
        "tests.upstream_hidden_pack_reuse.expected_contract.cheat_caught"
    ) in corrupt.stderr
    corrupt_payload = json.loads(corrupt_summary.read_text(encoding="utf-8"))
    assert corrupt_payload["status"] == "failed"
    assert corrupt_payload["failure"] == {"segment": "summary_validation", "exit_code": 1}

    corrupt_provenance_summary = tmp_path / "corrupt-provenance-summary.json"
    corrupt_provenance_env = env.copy()
    corrupt_provenance_env["OPENMAKO_AUTONOMOUS_LEARNING_GATE_SUMMARY_JSON"] = str(
        corrupt_provenance_summary
    )
    corrupt_provenance_env[
        "OPENMAKO_AUTONOMOUS_LEARNING_GATE_TEST_CORRUPT_SUMMARY"
    ] = "misstated_task_source_provenance"
    corrupt_provenance = subprocess.run(
        ["bash", "scripts/autonomous_learning_gate.sh"],
        cwd=ROOT,
        env=corrupt_provenance_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert corrupt_provenance.returncode == 1
    assert (
        "autonomous-learning-gate: invalid summary fields="
        "task_source_provenance.manifest,"
        "task_source_provenance.external_heldout"
    ) in corrupt_provenance.stderr

    missing_manifest_summary = tmp_path / "missing-manifest-summary.json"
    missing_manifest_env = env.copy()
    missing_manifest_env["OPENMAKO_AUTONOMOUS_LEARNING_GATE_SUMMARY_JSON"] = str(
        missing_manifest_summary
    )
    missing_manifest_env[
        "OPENMAKO_AUTONOMOUS_LEARNING_GATE_TEST_CORRUPT_SUMMARY"
    ] = "missing_task_source_manifest"
    missing_manifest = subprocess.run(
        ["bash", "scripts/autonomous_learning_gate.sh"],
        cwd=ROOT,
        env=missing_manifest_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert missing_manifest.returncode == 1
    assert (
        "autonomous-learning-gate: invalid summary fields="
        "task_source_manifest.path,"
        "task_source_manifest.artifact_path,"
        "task_source_manifest.sha256"
    ) in missing_manifest.stderr

    observed_summary = tmp_path / "observed-summary.json"
    observed_env = env.copy()
    observed_env["OPENMAKO_AUTONOMOUS_LEARNING_GATE_SUMMARY_JSON"] = str(observed_summary)
    observed_env["OPENMAKO_AUTONOMOUS_LEARNING_GATE_TEST_CORRUPT_SUMMARY"] = "missing_observed_result"
    observed_corrupt = subprocess.run(
        ["bash", "scripts/autonomous_learning_gate.sh"],
        cwd=ROOT,
        env=observed_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert observed_corrupt.returncode == 1
    assert (
        "autonomous-learning-gate: invalid summary fields="
        "tests.stage1_trajectory_reuse_matrix.observed_pytest.exit_code,"
        "tests.stage1_trajectory_reuse_matrix.observed_pytest.passed,"
        "tests.stage1_trajectory_reuse_matrix.observed_pytest.expected_passed,"
        "tests.stage1_trajectory_reuse_matrix.observed_pytest.skipped,"
        "tests.stage1_trajectory_reuse_matrix.observed_pytest.expected_skipped,"
        "tests.stage1_trajectory_reuse_matrix.observed_pytest.warnings"
    ) in observed_corrupt.stderr
    observed_payload = json.loads(observed_summary.read_text(encoding="utf-8"))
    assert observed_payload["status"] == "failed"
    assert observed_payload["failure"] == {"segment": "summary_validation", "exit_code": 1}


def test_adversarial_claim_matrix_generator_check_rejects_stale_fixture(tmp_path: Path) -> None:
    fixture = ROOT / "tests" / "fixtures" / "evidence_court" / "adversarial_claim_matrix.json"
    stale_fixture = tmp_path / "adversarial_claim_matrix.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    payload["multi_finding_case_count"] = 999
    stale_fixture.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    result = subprocess.run(
        [
            os.environ.get("PYTHON", "python3"),
            "scripts/generate_adversarial_claim_matrix.py",
            "--check",
            "--output",
            str(stale_fixture),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 1
    assert "--- " in result.stderr
    assert "+++ generated adversarial_claim_matrix.json" in result.stderr
    assert '"multi_finding_case_count": 999' in result.stderr
    assert '"multi_finding_case_count": 5' in result.stderr


def test_supplied_transcript_adapter_matrix_script_is_reviewer_runnable() -> None:
    script = ROOT / "scripts" / "supplied_transcript_adapter_matrix.sh"
    text = script.read_text(encoding="utf-8")

    assert script.exists()
    assert script.stat().st_mode & 0o111
    assert 'export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"' in text
    assert "from-${adapter}-transcript" in text
    assert "assert_audit_json" in text
    assert "json.loads(path.read_text" in text
    assert "smoke_adapter codex" in text
    assert "smoke_adapter claude" in text
    assert "smoke_adapter openhands" in text
    assert "smoke_adapter swe-agent" in text
    assert "smoke_adapter_missing_exit_status codex" in text
    assert "smoke_adapter_missing_exit_status claude" in text
    assert "smoke_adapter_missing_exit_status openhands" in text
    assert "smoke_adapter_missing_exit_status swe-agent" in text
    assert "smoke_adapter_test_only_source_diff codex" in text
    assert "smoke_adapter_test_only_source_diff claude" in text
    assert "smoke_adapter_test_only_source_diff openhands" in text
    assert "smoke_adapter_test_only_source_diff swe-agent" in text
    assert "smoke_adapter_partial_source_diff codex" in text
    assert "smoke_adapter_partial_source_diff claude" in text
    assert "smoke_adapter_partial_source_diff openhands" in text
    assert "smoke_adapter_partial_source_diff swe-agent" in text
    assert "smoke_adapter_missing_tests codex" in text
    assert "smoke_adapter_missing_tests claude" in text
    assert "smoke_adapter_missing_tests openhands" in text
    assert "smoke_adapter_missing_tests swe-agent" in text
    assert "smoke_adapter_missing_edits codex" in text
    assert "smoke_adapter_missing_edits claude" in text
    assert "smoke_adapter_missing_edits openhands" in text
    assert "smoke_adapter_missing_edits swe-agent" in text
    assert 'assert_audit_json "$audit" PASS' in text
    assert "--fail-on suspicious --json" in text
    assert "exit_code is required for validation commands" in text
    assert "test-only-source-diff-evidence" in text
    assert "partial-source-diff-evidence" in text
    assert "stale-validation-after-source-edit" in text
    assert 'assert_audit_json "$audit" SUSPICIOUS missing_test_evidence' in text
    assert 'assert_audit_json "$audit" SUSPICIOUS missing_edited_file_evidence' in text
    assert 'assert_audit_json "$audit" SUSPICIOUS missing_diff_content_evidence' in text
    assert 'assert_audit_json "$audit" SUSPICIOUS stale_validation_after_source_edit' in text
    assert "adapter-matrix: PASS" in text
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in text.lower()


def test_public_proof_card_wraps_gate_without_overclaiming() -> None:
    script = ROOT / "scripts" / "public_proof_card.sh"
    text = script.read_text(encoding="utf-8")

    assert script.exists()
    assert script.stat().st_mode & 0o111
    assert "openmako-public-proof-card: START" in text
    assert "proof-command: ./scripts/public_review_gate.sh" in text
    assert "./scripts/public_review_gate.sh" in text
    assert "openmako-public-proof-card: PASS" in text
    assert (
        "external-source benchmark gate; public metadata boundary; supplied Evidence Court audit; "
        "artifact provenance; SWTBench patch artifact; config-only repair fixture; "
        "runtime-shadowing and verifier/CI tamper fixtures; supplied transcript adapter matrix"
    ) in text
    assert "not-proof: independent external held-out benchmark; broad unknown-repository SWE repair; external endorsement; star or repost traction" in text
    assert "https://github.com/1966536805l-crypto/openmako/issues/2" in text
    assert "issues/new?template=external-review-record.yml" in text
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in text.lower()


def test_public_share_ready_script_gates_before_printing_message() -> None:
    script = ROOT / "scripts" / "public_share_ready.sh"
    text = script.read_text(encoding="utf-8")

    assert script.exists()
    assert script.stat().st_mode & 0o111
    assert "Runs the public review gate" in text
    assert "It does not post, ask for stars, ask for reposts" in text
    assert "bash scripts/public_review_gate.sh" in text
    assert "docs/PUBLIC_SHARE_PACKET.md" in text
    assert "review-request|boundary-clear" in text
    assert "requires-public-review: yes" in text
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in text.lower()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        scripts = tmp_root / "scripts"
        docs = tmp_root / "docs"
        scripts.mkdir()
        docs.mkdir()
        (scripts / "public_share_ready.sh").write_text(text, encoding="utf-8")
        (scripts / "public_review_gate.sh").write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\necho stub-public-gate-pass\n",
            encoding="utf-8",
        )
        (docs / "PUBLIC_SHARE_PACKET.md").write_text(
            (ROOT / "docs" / "PUBLIC_SHARE_PACKET.md").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        for path in scripts.iterdir():
            path.chmod(path.stat().st_mode | 0o111)

        review = subprocess.run(
            ["bash", str(scripts / "public_share_ready.sh"), "review-request"],
            cwd=tmp_root,
            check=False,
            text=True,
            capture_output=True,
        )
        assert review.returncode == 0
        assert "stub-public-gate-pass" in review.stdout
        assert "public-share-ready: mode=review-request" in review.stdout
        assert "Looking for technical boundary criticism" in review.stdout
        assert review.stdout.index("stub-public-gate-pass") < review.stdout.index("Looking for technical boundary criticism")

        boundary = subprocess.run(
            ["bash", str(scripts / "public_share_ready.sh"), "boundary-clear"],
            cwd=tmp_root,
            check=False,
            text=True,
            capture_output=True,
        )
        assert boundary.returncode == 0
        assert "stub-public-gate-pass" in boundary.stdout
        assert "public-share-ready: mode=boundary-clear" in boundary.stdout
        assert "requires-public-review: yes" in boundary.stdout
        assert "narrow public claim has external boundary feedback" in boundary.stdout

        unknown = subprocess.run(
            ["bash", str(scripts / "public_share_ready.sh"), "unknown"],
            cwd=tmp_root,
            check=False,
            text=True,
            capture_output=True,
        )
        assert unknown.returncode == 2
        assert "unknown mode: unknown" in unknown.stderr


def test_large_repost_packet_requires_external_review_record() -> None:
    packet = (ROOT / "docs" / "LARGE_REPOST_PACKET.md").read_text(encoding="utf-8")

    assert "OpenMako Post-Review Broader Share Packet" in packet
    assert "Use this only after a named external reviewer has posted public technical\nfeedback" in packet
    assert "bash scripts/large_repost_ready.sh REVIEW_RECORD_ISSUE_URL --confirm-external-review" in packet
    assert "not a launch claim, endorsement request, star request, or repost request" in packet
    assert "must not be used while OpenMako only has self-written proof" in packet
    assert "issue page is reachable, contains the structured external review record fields" in packet
    assert "includes the `External review record:` title prefix plus the required boundary\ncheckbox text" in packet
    assert "includes a selected review verdict" in packet
    assert "requires an explicit human confirmation flag" in packet
    assert "This check cannot prove non-self authorship by itself" in packet
    assert "## Gate" in packet
    assert "./scripts/public_review_gate.sh" in packet
    assert "A named external reviewer has posted public technical feedback." in packet
    assert "public OpenMako external review record issue" in packet
    assert "## Broad Technical Summary" in packet
    assert "## Short Repost-Ready Note" in packet
    assert "patch scope, test proof, learning-effect evidence, and supplied-run audit records" in packet
    assert "https://github.com/1966536805l-crypto/openmako" in packet
    assert "https://github.com/1966536805l-crypto/openmako/issues/2" in packet
    assert "issues/new?template=external-review-record.yml" in packet
    assert "Do not say OpenMako has broad SWE-bench-scale repair proof." in packet
    assert "Do not ask for stars, reposts, promotion, or endorsement." in packet
    assert "The next action is to ask for technical boundary criticism on issue #2" in packet
    short_match = re.search(
        r"## Short Repost-Ready Note\n\n```text\n(?P<post>.*?)\n```",
        packet,
        flags=re.DOTALL,
    )
    assert short_match, "large repost packet must include a short note"
    assert len(short_match.group("post")) <= 280
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in packet.lower()


def test_large_repost_ready_script_requires_review_record_and_gates() -> None:
    script = ROOT / "scripts" / "large_repost_ready.sh"
    text = script.read_text(encoding="utf-8")

    assert script.exists()
    assert script.stat().st_mode & 0o111
    assert "REVIEW_RECORD_ISSUE_URL" in text
    assert "--confirm-external-review" in text
    assert "manual external-review authorship confirmation" in text
    assert "bash scripts/public_review_gate.sh" in text
    assert "docs/LARGE_REPOST_PACKET.md" in text
    assert "OPENMAKO_CURL_BIN" in text
    assert "^[0-9]+$" in text or "/issues/[0-9]+$" in text
    assert "-fsSL --max-time 20" in text
    assert "issue page does not look like a structured external-review record" in text
    assert "missing record markers" in text
    for marker in (
        "External review record:",
        "Reviewer",
        "Public review link",
        "Review verdict",
        "Evidence checked by reviewer",
        "Boundary confirmation",
        "This records an already-public external technical review, not a private message or self-written summary.",
        "This issue does not ask for endorsement, promotion, stars, reposts, or broader claims.",
        "selected review verdict",
    ):
        assert marker in text
    assert "missing public external-review record issue URL" in text
    assert "does not post, contact anyone, ask for stars, ask for reposts" in text
    assert text.index("large-repost-ready: verifying external review record issue") < text.index(
        "bash scripts/public_review_gate.sh"
    )
    assert text.index("required_markers = (") < text.index("bash scripts/public_review_gate.sh")
    assert text.index("selected review verdict") < text.index("bash scripts/public_review_gate.sh")
    assert text.index("bash scripts/public_review_gate.sh") < text.index("message:")
    assert '"Broad Technical Summary", "Short Repost-Ready Note"' in text
    assert 'print(f"## {heading}")' in text
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in text.lower()

    missing = subprocess.run(
        ["bash", str(script)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert missing.returncode == 2
    assert "usage:" in missing.stderr

    invalid = subprocess.run(
        ["bash", str(script), "https://example.com/review"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert invalid.returncode == 2
    assert "usage:" in invalid.stderr

    invalid_with_confirmation = subprocess.run(
        [
            "bash",
            str(script),
            "https://example.com/review",
            "--confirm-external-review",
        ],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert invalid_with_confirmation.returncode == 2
    assert "missing public external-review record issue URL" in invalid_with_confirmation.stderr

    missing_confirmation = subprocess.run(
        [
            "bash",
            str(script),
            "https://github.com/1966536805l-crypto/openmako/issues/3",
            "--wrong-confirmation",
        ],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert missing_confirmation.returncode == 2
    assert "manual external-review authorship confirmation" in missing_confirmation.stderr

    non_numeric_issue = subprocess.run(
        [
            "bash",
            str(script),
            "https://github.com/1966536805l-crypto/openmako/issues/3abc",
            "--confirm-external-review",
        ],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert non_numeric_issue.returncode == 2
    assert "missing public external-review record issue URL" in non_numeric_issue.stderr

    fake_page = subprocess.run(
        [
            "bash",
            str(script),
            "https://github.com/1966536805l-crypto/openmako/issues/3",
            "--confirm-external-review",
        ],
        cwd=ROOT,
        env={**os.environ, "OPENMAKO_CURL_BIN": "/bin/echo"},
        check=False,
        text=True,
        capture_output=True,
    )
    assert fake_page.returncode == 2
    assert "structured external-review record" in fake_page.stderr
    assert "missing record markers" in fake_page.stderr
    assert "large-repost-ready: checking public proof gate" not in fake_page.stdout


def test_desktop_control_local_gate_is_bounded_and_conservative() -> None:
    script = ROOT / "scripts" / "desktop_control_local_gate.sh"
    text = script.read_text(encoding="utf-8")

    assert script.exists()
    assert script.stat().st_mode & 0o111
    assert 'export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"' in text
    assert "tests/test_desktop_intelligence.py" in text
    assert "tests/test_desktop_daemon_policy.py" in text
    assert "desktop-eval run --suite suite_l4 --json" in text
    assert '"suite_is_l4"' in text
    assert '"status_is_dry_run"' in text
    assert '"scenario_count_is_8"' in text
    assert '"roadmap_metrics_are_present"' in text
    assert '"roadmap_safety_rates_are_explicit"' in text
    assert '"level_reasons_do_not_hide_missing_safety_rate"' in text
    assert '"all_scenarios_are_suite_l4"' in text
    assert '"all_scenarios_disable_execute"' in text
    assert '"level_is_not_l4_claim"' in text
    assert "desktop-control-local-gate: misoperation_rate=" in text
    assert "desktop-control-local-gate: crash_rate=" in text
    assert "not-proof=live desktop control, L4, L5, external endorsement, star or repost traction" in text
    assert "desktop-control-local-gate: PASS" in text
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in text.lower()


def test_reviewer_outreach_draft_requests_criticism_not_promotion() -> None:
    draft = (ROOT / "docs" / "REVIEWER_OUTREACH_DRAFT.md").read_text(encoding="utf-8")

    assert "Reviewer Outreach Draft" in draft
    assert "technical boundary criticism" in draft
    assert "https://github.com/1966536805l-crypto/openmako/issues/2" in draft
    assert "docs/TECHNICAL_REVIEW_PACKET.md" in draft
    assert "docs/PUBLIC_SHARE_PACKET.md" in draft
    assert "I'm not asking for endorsement, stars, reposts, or promotion." in draft
    assert "## Who To Send First" in draft
    assert "Maintainers or reviewers of coding-agent eval, benchmark, or CI tooling." in draft
    assert "agent reliability, test evidence, or\n   benchmark methodology" in draft
    assert "Do not send to general influencers before at least one public technical boundary\nreview exists." in draft
    assert "docs/REVIEWER_TARGETS.md" in draft
    assert "specific file, line, command, workflow, or missing artifact" in draft
    assert "Only after a reviewer has independently said the boundary is clear" in draft
    assert "Do not ask them to promote the project." in draft
    assert "public technical critique on issue #2" in draft
    assert "please star" not in draft.lower()
    assert "please repost" not in draft.lower()
    assert "10,000" not in draft
    assert "10000" not in draft
    assert "大咖" not in draft


def test_reviewer_target_map_prioritizes_public_technical_review() -> None:
    targets = (ROOT / "docs" / "REVIEWER_TARGETS.md").read_text(encoding="utf-8")

    assert "OpenMako Reviewer Target Map" in targets
    assert "Last refreshed: 2026-06-04." in targets
    assert "not proof of endorsement, promotion,\nstars, reposts, or external review" in targets
    assert "Verify each source again before contacting\nanyone" in targets
    assert "The first ask is technical boundary criticism." in targets
    assert "Do not ask for stars, reposts,\npromotion, or endorsement." in targets
    assert "issues/new?template=external-review-record.yml" in targets
    assert "Wave 1 request copy: `docs/WAVE1_REVIEW_REQUESTS.md`" in targets
    assert "Public target queue: `docs/WAVE1_PUBLIC_TARGET_QUEUE.md`" in targets
    assert "| 1 | SWE-bench / SWE-agent researchers and users |" in targets
    assert "https://arxiv.org/abs/2310.06770" in targets
    assert "https://github.com/swe-agent/swe-agent" in targets
    assert "| 1 | Terminal-Bench / Harbor evaluation community |" in targets
    assert "https://github.com/harbor-framework/terminal-bench" in targets
    assert "| 1 | Aider maintainer/community |" in targets
    assert "https://github.com/aider-ai/aider" in targets
    assert "| 1 | OpenHands maintainer/community |" in targets
    assert "https://github.com/OpenHands/OpenHands" in targets
    assert "| 2 | AI engineering writers and conference/community curators |" in targets
    assert "https://swyx.io/about" in targets
    assert "| 2 | Software engineering trade writers |" in targets
    assert "https://blog.pragmaticengineer.com/" in targets
    assert "General AI influencers who do not review code, tests, CI, or benchmark\n  methodology." in targets
    assert "Any private feedback channel that cannot later be linked as public evidence." in targets
    assert "Stop outreach and fix the repository first" in targets
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in targets.lower()


def test_wave1_public_target_queue_tracks_reachable_surfaces_without_claiming_outreach() -> None:
    queue = (ROOT / "docs" / "WAVE1_PUBLIC_TARGET_QUEUE.md").read_text(encoding="utf-8")

    assert "OpenMako Wave 1 Public Target Queue" in queue
    assert "not proof that outreach happened" in queue
    assert "not evidence of endorsement, stars, reposts, or external review" in queue
    assert "bash scripts/public_review_gate.sh" in queue
    assert "bash scripts/wave1_send_ready.sh TARGET" in queue
    assert "bash scripts/wave1_thread_reply_ready.sh THREAD" in queue
    assert "This still does not send the\nmessage or record outreach as evidence." in queue
    assert "Send one short note at a time." in queue
    assert "Do not\ncreate a new issue in another project" in queue
    assert "project norms allow\nmeta/tooling review requests" in queue
    assert "https://github.com/SWE-agent/SWE-agent/issues" in queue
    assert "Issues page reachable; discussions page not public." in queue
    assert "https://github.com/harbor-framework/terminal-bench/discussions" in queue
    assert "Discussions page reachable; issues page also reachable." in queue
    assert "https://github.com/Aider-AI/aider/issues" in queue
    assert "https://github.com/OpenHands/OpenHands/issues" in queue
    assert "Existing Threads To Inspect Before Posting" in queue
    assert "These are candidate reading targets, not approved posting targets." in queue
    assert "Best current fit" in queue
    assert "Read-only / weak fit" in queue
    assert "Skip unless directly relevant" in queue
    assert "https://github.com/harbor-framework/terminal-bench/discussions/1357" in queue
    assert "cost of executing a test" in queue
    assert "bash scripts/wave1_thread_reply_ready.sh terminal-bench-1357" in queue
    assert "https://github.com/OpenHands/benchmarks/issues/708" in queue
    assert "non-test patch stripping and patch-shape evidence" in queue
    assert "bash scripts/wave1_thread_reply_ready.sh openhands-benchmarks-708" in queue
    assert "https://github.com/OpenHands/benchmarks/issues/718" in queue
    assert "rule changes affect comparability of historical runs" in queue
    assert "bash scripts/wave1_thread_reply_ready.sh openhands-benchmarks-718" in queue
    assert "https://github.com/OpenHands/OpenHands/issues/10767" in queue
    assert "Closed as not planned" in queue
    assert "Do not revive a closed main-repo issue for OpenMako outreach." in queue
    assert "https://github.com/SWE-agent/SWE-agent/issues/21" in queue
    assert "https://github.com/SWE-agent/SWE-agent/issues/580" in queue
    assert "https://github.com/SWE-agent/SWE-agent/issues/563" in queue
    assert "https://github.com/Aider-AI/aider/issues/110" in queue
    assert "https://github.com/Aider-AI/aider/issues/2588" in queue
    assert "Do not revive a solved issue for OpenMako outreach." in queue
    assert "https://github.com/OpenHands/OpenHands/issues/12043" in queue
    assert "Do not post into a bug thread unless the comment addresses that thread's\nexisting question" in queue
    assert "If the fit is weak, skip the thread instead of making noise." in queue
    assert "Do not post the same generic message to multiple threads." in queue
    assert "bash scripts/wave1_send_ready.sh --linkless TARGET" in queue
    assert "without repo, proof-command, or\nreview-issue links" in queue
    assert "The output includes `THREAD_HOOK`; replace it with a\nconcrete point from the target thread before posting." in queue
    assert "If no concrete hook fits,\nskip the thread." in queue
    assert "bash scripts/wave1_review_request.sh swe-agent" in queue
    assert "bash scripts/wave1_review_request.sh terminal-bench" in queue
    assert "bash scripts/wave1_review_request.sh aider" in queue
    assert "bash scripts/wave1_review_request.sh openhands" in queue
    assert "Do not ask for stars, reposts, promotion, endorsement" in queue
    assert "Stop outreach and fix the repository first" in queue
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in queue.lower()


def test_wave1_thread_reply_ready_script_gates_and_prints_specific_messages() -> None:
    script = ROOT / "scripts" / "wave1_thread_reply_ready.sh"
    text = script.read_text(encoding="utf-8")

    assert script.exists()
    assert script.stat().st_mode & 0o111
    assert "Checks that the target thread still looks on-topic, runs the public review\ngate" in text
    assert "checking target thread page" in text
    assert "OPENMAKO_THREAD_PAGE_FIXTURE" in text
    assert "expected topic markers" in text
    assert "This does not send messages, create issues" in text
    assert "terminal-bench-1357" in text
    assert "openhands-benchmarks-708" in text
    assert "openhands-benchmarks-718" in text
    assert "bash scripts/public_review_gate.sh" in text
    assert "target-url: ${target_url}" in text
    assert "preflight: target thread page matched expected topic markers" in text
    assert "https://github.com/OpenHands/benchmarks/issues/718" in text
    assert "decision: read the thread first; do not post if stale, closed, or off-topic" in text
    assert "requires-confirmation: yes; do not submit a public comment without final user confirmation" in text
    assert "cost/version/proof metadata" in text
    assert "command/test count, wall time, runner or environment version, validation command" in text
    assert "what is the minimum metadata a benchmark row should expose" in text
    assert "I made a small harness for my own project" not in text
    assert "https://github.com/1966536805l-crypto/openmako/issues/2" not in text
    assert "332 / 424 mixed bucket" in text
    assert "patch-shape bucket separately from the final SWT-bench score" in text
    assert "expected F2P failure mode from source edits under model_patch" in text
    assert "mixed test+source patch" in text
    assert "first-class verdict/metadata field rather than a post-hoc explanation" in text
    assert "A concrete supplied-record shape for this is a fixture" not in text
    assert "examples/evidence_court/swtbench_patch_artifact.json" not in text
    assert "artifact-identity problem more than a scoring problem" in text
    assert "`output.jsonl` can produce a different `output.swtbench.jsonl`" in text
    assert "patch-stripping rule changes" in text
    assert "eval rule version, runner commit or version, input/output hashes" in text
    assert "patch-shape bucket" in text
    assert "would rule version + runner commit + input/output hashes be enough to compare old/new runs" in text
    assert "does patch shape need to be a first-class field too" in text
    assert "The closest shape I have been testing" not in text
    assert "docs/evidence_court_schema.md#swtbench-artifact-identity-builder" not in text
    assert "benchmark_score_validated=false" not in text
    assert "runner_verified=false" not in text
    assert "openmako evidence-court record from-swtbench-artifacts" not in text
    assert "historical re-scoring or native OpenHands/SWTBench ingestion" not in text
    assert "my own audit harness" not in text
    assert "runner commit + input/output hashes be enough to compare old/new runs" in text
    assert "should patch-shape be first-class metadata too" not in text
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in text.lower()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        scripts = tmp_root / "scripts"
        scripts.mkdir()
        (scripts / "wave1_thread_reply_ready.sh").write_text(text, encoding="utf-8")
        (scripts / "public_review_gate.sh").write_text(
            "#!/usr/bin/env bash\necho public-review-gate: PASS\n",
            encoding="utf-8",
        )
        good_thread = tmp_root / "terminal-bench-1357.html"
        good_thread.write_text(
            "<title>How costly is it to execute a test? · harbor-framework/terminal-bench · Discussion #1357 · GitHub</title>"
            " terminal-bench cost test discussion",
            encoding="utf-8",
        )
        openhands_708 = tmp_root / "openhands-benchmarks-708.html"
        openhands_708.write_text(
            "<title>swtbench: qwen3-coder-next score is artificially low — agent writes source-code fix alongside the test "
            "(78% of patches) · Issue #708 · OpenHands/benchmarks · GitHub</title>"
            ' {"state":"OPEN"} 332 424 model_patch non-test patch',
            encoding="utf-8",
        )
        openhands_718 = tmp_root / "openhands-benchmarks-718.html"
        openhands_718.write_text(
            "<title>Assess impact of swtbench non-test patch stripping on historical runs · Issue #718 · OpenHands/benchmarks · GitHub</title>"
            ' {"state":"OPEN"} output.jsonl output.swtbench.jsonl historical patch',
            encoding="utf-8",
        )
        bad_thread = tmp_root / "off-topic.html"
        bad_thread.write_text(
            "<title>Unrelated thread · GitHub</title> promotion stars repost",
            encoding="utf-8",
        )
        for path in scripts.iterdir():
            path.chmod(0o755)

        result = subprocess.run(
            ["bash", str(scripts / "wave1_thread_reply_ready.sh"), "terminal-bench-1357"],
            cwd=tmp_root,
            env={**os.environ, "OPENMAKO_THREAD_PAGE_FIXTURE": str(good_thread)},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

        assert "wave1-thread-reply-ready: checking target thread page" in result.stdout
        assert "public-review-gate: PASS" in result.stdout
        assert result.stdout.index("checking target thread page") < result.stdout.index("public-review-gate: PASS")
        assert "wave1-thread-reply-ready: thread=terminal-bench-1357" in result.stdout
        assert "preflight: target thread page matched expected topic markers" in result.stdout
        assert "leaderboard row without cost/version/proof metadata" in result.stdout
        assert "what is the minimum metadata a benchmark row should expose" in result.stdout
        assert "I would rather get criticism on the boundary than repo promotion" not in result.stdout

        for thread, fixture, expected in (
            ("openhands-benchmarks-708", openhands_708, "332 / 424 mixed bucket"),
            ("openhands-benchmarks-718", openhands_718, "artifact-identity problem more than a scoring problem"),
        ):
            specific = subprocess.run(
                ["bash", str(scripts / "wave1_thread_reply_ready.sh"), thread],
                cwd=tmp_root,
                env={**os.environ, "OPENMAKO_THREAD_PAGE_FIXTURE": str(fixture)},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            assert "preflight: target thread page matched expected topic markers" in specific.stdout
            assert expected in specific.stdout

        off_topic = subprocess.run(
            ["bash", str(scripts / "wave1_thread_reply_ready.sh"), "terminal-bench-1357"],
            cwd=tmp_root,
            env={**os.environ, "OPENMAKO_THREAD_PAGE_FIXTURE": str(bad_thread)},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert off_topic.returncode == 2
        assert "target thread does not match expected topic" in off_topic.stderr
        assert "public-review-gate: PASS" not in off_topic.stdout

        unknown = subprocess.run(
            ["bash", str(scripts / "wave1_thread_reply_ready.sh"), "unknown"],
            cwd=tmp_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert unknown.returncode == 2
        assert "unknown thread: unknown" in unknown.stderr


def test_wave1_send_ready_script_gates_before_printing_message() -> None:
    script = ROOT / "scripts" / "wave1_send_ready.sh"
    text = script.read_text(encoding="utf-8")

    assert script.exists()
    assert script.stat().st_mode & 0o111
    assert "Runs the public review gate" in text
    assert "This does not send messages, create issues" in text
    assert "bash scripts/public_review_gate.sh" in text
    assert "usage: bash scripts/wave1_send_ready.sh [--linkless] TARGET" in text
    assert "Use --linkless for an existing public thread" in text
    assert "review_args+=(--linkless)" in text
    assert "requires-thread-hook: yes; replace THREAD_HOOK before posting" in text
    assert "bash scripts/wave1_review_request.sh \"${review_args[@]}\"" in text
    assert "swe-agent|terminal-bench|aider|openhands|agent-runtime" in text
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in text.lower()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        scripts = tmp_root / "scripts"
        scripts.mkdir()
        (scripts / "wave1_send_ready.sh").write_text(text, encoding="utf-8")
        (scripts / "public_review_gate.sh").write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\necho stub-gate-pass\n",
            encoding="utf-8",
        )
        (scripts / "wave1_review_request.sh").write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\nprintf 'stub-message'\nfor arg in \"$@\"; do printf -- '-%s' \"$arg\"; done\nprintf '\\n'\n",
            encoding="utf-8",
        )
        for path in scripts.iterdir():
            path.chmod(path.stat().st_mode | 0o111)

        result = subprocess.run(
            ["bash", str(scripts / "wave1_send_ready.sh"), "swe-agent"],
            cwd=tmp_root,
            check=False,
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0
        assert "stub-gate-pass" in result.stdout
        assert "wave1-send-ready: target=swe-agent" in result.stdout
        assert "stub-message-swe-agent" in result.stdout
        assert result.stdout.index("stub-gate-pass") < result.stdout.index("stub-message-swe-agent")

        linkless = subprocess.run(
            ["bash", str(scripts / "wave1_send_ready.sh"), "--linkless", "terminal-bench"],
            cwd=tmp_root,
            check=False,
            text=True,
            capture_output=True,
        )
        assert linkless.returncode == 0
        assert "stub-gate-pass" in linkless.stdout
        assert "wave1-send-ready: target=terminal-bench" in linkless.stdout
        assert "wave1-send-ready: mode=linkless" in linkless.stdout
        assert "requires-thread-hook: yes; replace THREAD_HOOK before posting" in linkless.stdout
        assert "stub-message---linkless-terminal-bench" in linkless.stdout
        assert linkless.stdout.index("stub-gate-pass") < linkless.stdout.index("stub-message---linkless-terminal-bench")

        agent_runtime = subprocess.run(
            ["bash", str(scripts / "wave1_send_ready.sh"), "agent-runtime"],
            cwd=tmp_root,
            check=False,
            text=True,
            capture_output=True,
        )
        assert agent_runtime.returncode == 0
        assert "stub-gate-pass" in agent_runtime.stdout
        assert "wave1-send-ready: target=agent-runtime" in agent_runtime.stdout
        assert "stub-message-agent-runtime" in agent_runtime.stdout

        unknown = subprocess.run(
            ["bash", str(scripts / "wave1_send_ready.sh"), "unknown"],
            cwd=tmp_root,
            check=False,
            text=True,
            capture_output=True,
        )
        assert unknown.returncode == 2
        assert "unknown target: unknown" in unknown.stderr


def test_wave1_review_requests_are_copyable_without_promotion() -> None:
    requests = (ROOT / "docs" / "WAVE1_REVIEW_REQUESTS.md").read_text(encoding="utf-8")

    assert "OpenMako Wave 1 Review Requests" in requests
    assert "not endorsement\nrequests, promotion requests" in requests
    assert "star requests, repost requests" in requests
    assert "not proof that outreach has happened" in requests
    assert "Send the short note first." in requests
    assert "bash scripts/public_proof_card.sh" in requests
    assert "openmako-public-proof-card: PASS" in requests
    assert (
        "scope: external-source benchmark gate; public metadata boundary; supplied Evidence Court audit; "
        "artifact provenance; SWTBench patch artifact; config-only repair fixture; "
        "runtime-shadowing and verifier/CI tamper fixtures; supplied transcript adapter matrix"
    ) in requests
    assert "not-proof: independent external held-out benchmark; broad unknown-repository SWE repair; external endorsement; star or repost traction" in requests
    assert "SWE-Bench / SWE-Agent Review Request" in requests
    assert "short notes for asking technical reviewers to check the v0.1 boundary" in requests
    assert "Can you point out where OpenMako v0.1 overclaims its evidence boundary?" in requests
    assert "Current public proof covers an external-source benchmark gate" in requests
    assert "supplied-record/provenance audits, a config-only\nfalse-positive fixture, runtime-shadowing and verifier/CI tamper review-risk\nfixtures, and a supplied transcript adapter matrix" in requests
    assert "It does not claim\nindependent external held-out benchmarking, SWE-bench-scale repair, or native\nruntime/CI hardening." in requests
    assert "I'm mainly looking for README lines or proof-command gaps that overclaim." in requests
    assert "Terminal-Bench / Agent-Eval Review Request" in requests
    assert "Can you check OpenMako v0.1's evidence boundary?" in requests
    assert "README lines or proof-command gaps that overclaim" in requests
    assert "not a broad terminal-agent benchmark" in requests
    assert "Aider Community Review Request" in requests
    assert "useful or too noisy from a coding-agent user's view" in requests
    assert "It is not a replacement for Aider or any coding agent." in requests
    assert "OpenHands / Software-Agent Review Request" in requests
    assert "Could you check OpenMako v0.1 for overclaim?" in requests
    assert "not that OpenMako is a full software agent" in requests
    assert "Agent Runtime / OpenClaw-Hermes Review Request" in requests
    assert "Use this only for reviewers already discussing agent runtime mechanics" in requests
    assert "skills, memory, ACP-style sessions, desktop control" in requests
    assert "Could you sanity-check whether OpenMako's runtime-adjacent docs overread the current proof?" in requests
    assert "trends or future bets" in requests
    assert "test-proof checks, supplied-record/provenance audits, a config-only false-positive fixture, runtime-shadowing and verifier/CI tamper review-risk fixtures, and a supplied transcript adapter matrix" in requests
    assert "test-proof checks, and supplied-record audit" not in requests
    assert "already public v0.1 proof" in requests
    assert "Do not send the boundary-clear follow-up before a named reviewer posts public\n  feedback." in requests
    assert "Do not summarize private feedback as public evidence." in requests
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in requests.lower()


def test_wave1_review_request_script_prints_short_non_promotional_messages() -> None:
    script = ROOT / "scripts" / "wave1_review_request.sh"
    text = script.read_text(encoding="utf-8")

    assert script.exists()
    assert script.stat().st_mode & 0o111
    assert "Prints one short technical-boundary review request." in text
    assert "It does not send messages,\nask for stars, ask for reposts" in text
    assert "usage: ./scripts/wave1_review_request.sh [--linkless] TARGET" in text
    assert "Use --linkless for an existing public thread" in text
    assert "Linkless messages omit repo, proof-command, and issue\nlinks, and include a required THREAD_HOOK placeholder." in text
    assert "Do not post until the\nplaceholder is replaced with a concrete point from the target thread." in text
    assert "swe-agent" in text
    assert "terminal-bench" in text
    assert "aider" in text
    assert "openhands" in text
    assert "agent-runtime" in text
    assert "Can you point out where OpenMako v0.1 overclaims its evidence boundary?" in text
    assert "supplied-record/provenance audits, runtime-shadowing\nand verifier/CI tamper review-risk fixtures, and a supplied transcript adapter\nmatrix" in text
    assert "independent external held-out benchmarking,\nSWE-bench-scale repair, or native runtime/CI hardening" in text
    assert "Can you check OpenMako v0.1's evidence boundary?" in text
    assert "I'm mainly looking for README lines or proof-command gaps that overclaim." in text
    assert "useful or too noisy from a coding-agent user's view" in text
    assert "Could you check OpenMako v0.1 for overclaim?" in text
    assert "runtime-adjacent docs overread the current proof" in text
    assert "skills, memory, ACP-style sessions, and desktop-control work as trends or future bets" in text
    assert "test-proof checks, supplied-record/provenance audits, runtime-shadowing and verifier/CI tamper review-risk fixtures, and a supplied transcript adapter matrix" in text
    assert "test-proof checks, and supplied-record audit" not in text
    assert "THREAD_HOOK: replace this with the specific eval-proof point from the thread." in text
    assert "for a narrow repair run, would touched-file scope, exact test\ncommand, and exit status be enough" in text
    assert "specific test-cost or eval-proof point from\nthe thread" in text
    assert "command\ntranscript plus exit status enough proof" in text
    assert "specific reliability or benchmark point from\nthe thread" in text
    assert "which evidence would make you\ntrust it first" in text
    assert "specific log, patch-shape, or eval-artifact\npoint from the thread" in text
    assert "is native log format required before that\ncheck is credible" in text
    assert "specific runtime-docs or session-control\npoint from the thread" in text
    assert "separate proof table" in text
    assert "I am thinking" not in text
    assert "I usually separate" not in text
    assert "unknown target" in text
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in text.lower()

    for target, expected in (
        ("swe-agent", "Can you point out where OpenMako v0.1 overclaims its evidence boundary?"),
        ("terminal-bench", "Can you check OpenMako v0.1's evidence boundary?"),
        ("aider", "useful or too noisy from a coding-agent user's view"),
        ("openhands", "Could you check OpenMako v0.1 for overclaim?"),
        ("agent-runtime", "runtime-adjacent docs overread the current proof"),
    ):
        result = subprocess.run(
            ["bash", str(script), target],
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0
        assert expected in result.stdout
        assert "Review issue: https://github.com/1966536805l-crypto/openmako/issues/2" in result.stdout
        for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
            assert forbidden not in result.stdout.lower()

    for target, expected in (
        ("swe-agent", "THREAD_HOOK: replace this with the specific eval-proof point from the thread."),
        ("terminal-bench", "specific test-cost or eval-proof point from\nthe thread"),
        ("aider", "specific reliability or benchmark point from\nthe thread"),
        ("openhands", "specific log, patch-shape, or eval-artifact\npoint from the thread"),
        ("agent-runtime", "specific runtime-docs or session-control\npoint from the thread"),
    ):
        result = subprocess.run(
            ["bash", str(script), "--linkless", target],
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0
        assert expected in result.stdout
        assert "THREAD_HOOK:" in result.stdout
        assert "Question:" in result.stdout
        assert "http" not in result.stdout.lower()
        assert "OpenMako" not in result.stdout
        assert "Repo:" not in result.stdout
        assert "Proof command:" not in result.stdout
        assert "Review issue:" not in result.stdout
        assert "trend radar" not in result.stdout.lower()
        assert "future bets" not in result.stdout.lower()
        assert "ACP-style" not in result.stdout
        assert "I am thinking" not in result.stdout
        assert "I usually separate" not in result.stdout
        for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
            assert forbidden not in result.stdout.lower()

    unknown = subprocess.run(
        ["bash", str(script), "unknown"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert unknown.returncode == 2
    assert "unknown target: unknown" in unknown.stderr


def test_root_agent_notes_match_public_evidence_boundary() -> None:
    notes = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    assert notes.startswith("# OpenMako Local Agent Notes")
    assert "OpenMako is a focused evidence harness for coding-agent repair runs." in notes
    assert "not a public capability claim" in notes
    assert "external-source public gate" in notes
    assert "not independent external held-out benchmark\n  evidence" in notes
    assert "tests/test_public_metadata.py" in notes
    for forbidden in FORBIDDEN_ROOT_AGENT_NOTES:
        assert forbidden not in notes


def test_quant_reports_are_archived_out_of_repository_root() -> None:
    archive_dir = ROOT / "docs" / "archive" / "quant"

    for filename in ARCHIVED_ROOT_QUANT_FILES:
        assert not (ROOT / filename).exists()
        assert (archive_dir / filename).exists()


def test_quant_examples_are_moved_out_of_repository_root() -> None:
    expected_locations = {
        "demo_capacity_comprehensive.py": ROOT / "examples" / "quant" / "capacity",
        "demo_capacity_validation.py": ROOT / "examples" / "quant" / "capacity",
        "example_tick_price_validator.py": ROOT / "examples" / "quant" / "tick_price",
        "realistic_t1_trades.csv": ROOT / "examples" / "quant" / "data",
    }

    for filename in EXAMPLE_ROOT_QUANT_FILES:
        assert not (ROOT / filename).exists()
        assert (expected_locations[filename] / filename).exists()


def test_legacy_quant_test_artifacts_are_archived_out_of_repository_root() -> None:
    archive_dir = ROOT / "docs" / "archive" / "quant" / "legacy_tests"

    for filename in LEGACY_ROOT_QUANT_TEST_FILES:
        assert not (ROOT / filename).exists()
        assert (archive_dir / filename).exists()


def test_high_risk_planning_docs_are_not_public_claims() -> None:
    for relative_path in INTERNAL_PLANNING_DOCS:
        text = (ROOT / relative_path).read_text(encoding="utf-8")

        assert 'current public proof command is `./scripts/public_review_gate.sh`' in text
        assert "current public proof is the focused learning-effect gate" not in text
        assert "not the current public v0.1 capability claim" in text or "not a public capability claim" in text

    market_scan = (ROOT / "docs" / "MARKET_TOOL_COPY_SCAN.md").read_text(encoding="utf-8")
    assert "Highest-Value Things To Steal Next" not in market_scan

    model_setup = (ROOT / "docs" / "OPENAI_COMPATIBLE_SETUP.md").read_text(encoding="utf-8")
    for forbidden in FORBIDDEN_PUBLIC_DOC_VENDOR_ENDPOINTS:
        assert forbidden not in model_setup
