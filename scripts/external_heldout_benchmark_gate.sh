#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON:-python3}"
export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"

SUMMARY_JSON="${OPENMAKO_EXTERNAL_HELDOUT_BENCHMARK_SUMMARY_JSON:-.quantagent/external_heldout_benchmark_gate/last_summary.json}"
SUMMARY_DIR="$(dirname -- "$SUMMARY_JSON")"
PYTEST_LOG="$SUMMARY_DIR/pytest.log"
TASK_PROOF_DIR="$SUMMARY_DIR/task_proofs"
mkdir -p "$SUMMARY_DIR"
rm -rf "$TASK_PROOF_DIR"
rm -f "$PYTEST_LOG"
mkdir -p "$TASK_PROOF_DIR"
export OPENMAKO_EXTERNAL_HELDOUT_TASK_PROOF_DIR="$TASK_PROOF_DIR"
TASK_SOURCE_MANIFEST="${OPENMAKO_EXTERNAL_HELDOUT_TASK_SOURCE_MANIFEST:-scripts/external_heldout_task_source_provenance.json}"

load_selected_tests() {
  "$PYTHON_BIN" - "$TASK_SOURCE_MANIFEST" <<'PY'
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path.cwd()
manifest_arg = Path(sys.argv[1])
manifest_path = manifest_arg if manifest_arg.is_absolute() else ROOT / manifest_arg
manifest_text = manifest_path.read_text(encoding="utf-8")
payload = json.loads(manifest_text)
if payload.get("schema_version") != "external-heldout-task-source-provenance/v0.1":
    raise SystemExit("external-heldout-benchmark-gate: invalid task source manifest schema_version")
if payload.get("external_heldout") is not True:
    raise SystemExit("external-heldout-benchmark-gate: task source manifest external_heldout is not true")
selected_tests = payload.get("selected_tests")
if not isinstance(selected_tests, list) or len(selected_tests) != 2:
    raise SystemExit("external-heldout-benchmark-gate: invalid selected_tests count")
allowed_node_ids = {
    "tests/test_upstream_function_file_bundle_regression.py::"
    "UpstreamFunctionFileBundleRegressionTest::"
    "test_vendored_mcp_function_level_repair_reuses_without_non_target_drift",
    "tests/test_upstream_function_file_bundle_regression.py::"
    "UpstreamFunctionFileBundleRegressionTest::"
    "test_vendored_mcp_wrapper_seed_repair_reuses_without_non_target_drift",
}
if set(selected_tests) != allowed_node_ids or not all(isinstance(item, str) for item in selected_tests):
    raise SystemExit("external-heldout-benchmark-gate: invalid selected_tests node ids")
selected_digest = hashlib.sha256(("\n".join(selected_tests) + "\n").encode("utf-8")).hexdigest()
if payload.get("selected_tests_sha256") != selected_digest:
    raise SystemExit("external-heldout-benchmark-gate: invalid selected_tests_sha256")
test_file = payload.get("selected_test_file")
if not isinstance(test_file, dict):
    raise SystemExit("external-heldout-benchmark-gate: missing selected_test_file")
test_path = test_file.get("path")
expected_test_digest = test_file.get("sha256")
if test_path != "tests/test_upstream_function_file_bundle_regression.py":
    raise SystemExit("external-heldout-benchmark-gate: invalid selected_test_file path")
if not isinstance(expected_test_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_test_digest):
    raise SystemExit("external-heldout-benchmark-gate: invalid selected_test_file sha256")
actual_test_digest = hashlib.sha256((ROOT / test_path).read_bytes()).hexdigest()
if actual_test_digest != expected_test_digest:
    raise SystemExit(
        "external-heldout-benchmark-gate: selected test file sha256 mismatch: "
        f"expected {expected_test_digest}, got {actual_test_digest}"
    )
for item in selected_tests:
    print(item)
PY
}

SELECTED_TESTS=()
while IFS= read -r selected_test; do
  SELECTED_TESTS+=("$selected_test")
done < <(load_selected_tests)

GIT_COMMIT="unknown"
if git rev-parse HEAD >/dev/null 2>&1; then
  GIT_COMMIT="$(git rev-parse HEAD)"
fi

write_summary() {
  local status="$1"
  local pytest_exit="$2"
  "$PYTHON_BIN" - "$SUMMARY_JSON" "$PYTEST_LOG" "$TASK_PROOF_DIR" "$GIT_COMMIT" "$status" "$pytest_exit" "$TASK_SOURCE_MANIFEST" "${SELECTED_TESTS[@]}" <<'PY'
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path.cwd()
summary_arg = Path(sys.argv[1])
SUMMARY_JSON = summary_arg if summary_arg.is_absolute() else ROOT / summary_arg
pytest_log_arg = Path(sys.argv[2])
PYTEST_LOG = pytest_log_arg if pytest_log_arg.is_absolute() else ROOT / pytest_log_arg
task_proof_arg = Path(sys.argv[3])
TASK_PROOF_DIR = task_proof_arg if task_proof_arg.is_absolute() else ROOT / task_proof_arg
GIT_COMMIT = sys.argv[4]
STATUS = sys.argv[5]
PYTEST_EXIT = int(sys.argv[6])
TASK_SOURCE_MANIFEST_ARG = Path(sys.argv[7])
TASK_SOURCE_MANIFEST = TASK_SOURCE_MANIFEST_ARG if TASK_SOURCE_MANIFEST_ARG.is_absolute() else ROOT / TASK_SOURCE_MANIFEST_ARG
SELECTED_TESTS = sys.argv[8:]

MANIFEST = ROOT / "third_party" / "mcp_python_sdk" / "MANIFEST.sha256"
LICENSE = ROOT / "third_party" / "mcp_python_sdk" / "LICENSE"
ATTRIBUTION = ROOT / "docs" / "UPSTREAM_ATTRIBUTION.md"
AUTONOMOUS_MANIFEST = ROOT / "scripts" / "autonomous_task_source_provenance.json"
REQUIRED_SOURCE_PATHS = [
    "third_party/mcp_python_sdk/LICENSE",
    "third_party/mcp_python_sdk/src/mcp/shared/tool_name_validation.py",
]
NOT_PROOF = [
    "external benchmark standing",
    "external review",
    "endorsement",
    "stars",
    "reposts",
    "native live autonomy",
    "broad unknown-repository repair",
    "current remote CI proof",
    "owner license decision",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest() -> dict[str, str]:
    if not MANIFEST.exists():
        raise SystemExit(f"external-heldout-benchmark-gate: missing manifest {MANIFEST}")
    entries: dict[str, str] = {}
    for line_number, raw_line in enumerate(MANIFEST.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise SystemExit(f"external-heldout-benchmark-gate: invalid manifest line {line_number}: {raw_line!r}")
        expected, rel_path = parts
        rel_path = rel_path.strip()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise SystemExit(f"external-heldout-benchmark-gate: invalid sha256 on manifest line {line_number}")
        abs_path = ROOT / rel_path
        if not abs_path.exists():
            raise SystemExit(f"external-heldout-benchmark-gate: manifest path missing: {rel_path}")
        actual = sha256_file(abs_path)
        if actual != expected:
            raise SystemExit(
                f"external-heldout-benchmark-gate: manifest digest mismatch for {rel_path}: "
                f"expected {expected}, got {actual}"
            )
        entries[rel_path] = expected
    return entries


def read_task_source_manifest() -> tuple[dict[str, Any], str]:
    text = TASK_SOURCE_MANIFEST.read_text(encoding="utf-8")
    payload = json.loads(text)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return payload, digest


def parse_pytest_log() -> dict[str, Any]:
    if not PYTEST_LOG.exists():
        return {"exit_code": PYTEST_EXIT, "passed": 0, "skipped": 0, "warnings": 0}
    text = PYTEST_LOG.read_text(encoding="utf-8", errors="replace")
    passed = 0
    skipped = 0
    warnings = 0
    for match in re.finditer(r"(\d+)\s+passed", text):
        passed = int(match.group(1))
    for match in re.finditer(r"(\d+)\s+skipped", text):
        skipped = int(match.group(1))
    for match in re.finditer(r"(\d+)\s+warnings?", text):
        warnings = int(match.group(1))
    return {
        "exit_code": PYTEST_EXIT,
        "passed": passed,
        "skipped": skipped,
        "warnings": warnings,
    }


def log_tail() -> list[str]:
    if not PYTEST_LOG.exists():
        return []
    return PYTEST_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def autonomous_selected_tests() -> set[str]:
    payload = json.loads(AUTONOMOUS_MANIFEST.read_text(encoding="utf-8"))
    selected: set[str] = set()
    segments = payload.get("segments")
    if not isinstance(segments, dict):
        raise SystemExit("external-heldout-benchmark-gate: autonomous provenance segments missing")
    for segment in segments.values():
        if not isinstance(segment, dict):
            raise SystemExit("external-heldout-benchmark-gate: autonomous provenance segment is not an object")
        tests = segment.get("selected_tests")
        if not isinstance(tests, list):
            raise SystemExit("external-heldout-benchmark-gate: autonomous selected_tests missing")
        selected.update(str(item) for item in tests)
    return selected


def read_task_proofs() -> list[dict[str, Any]]:
    if not TASK_PROOF_DIR.exists():
        return []
    proofs: list[dict[str, Any]] = []
    for proof_path in sorted(TASK_PROOF_DIR.rglob("*.json")):
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        if not isinstance(proof, dict):
            raise SystemExit(f"external-heldout-benchmark-gate: task proof is not an object: {proof_path}")
        proof["proof_path"] = display_path(proof_path)
        proofs.append(proof)
    return proofs


def validate_task_proofs(proofs: list[dict[str, Any]]) -> list[str]:
    if STATUS != "passed":
        return []
    invalid: list[str] = []
    expected_source_sha256 = manifest_entries[
        "third_party/mcp_python_sdk/src/mcp/shared/tool_name_validation.py"
    ]
    expected_tasks = {
        "vendored_mcp_tool_name_validation_function_repair": {
            "function_name": "validate_tool_name",
        },
        "vendored_mcp_tool_name_wrapper_seed_repair": {
            "function_name": "validate_and_warn_tool_name",
        },
    }
    if len(proofs) != len(expected_tasks):
        return [f"task_proof_count={len(proofs)}"]
    seen_task_ids: set[str] = set()
    for proof in proofs:
        task_id = proof.get("task_id")
        if not isinstance(task_id, str) or task_id not in expected_tasks:
            invalid.append("task_proof.task_id")
            expected = {"function_name": ""}
        else:
            if task_id in seen_task_ids:
                invalid.append(f"task_proof.duplicate_task_id.{task_id}")
            seen_task_ids.add(task_id)
            expected = expected_tasks[task_id]
        before_failure = proof.get("before_failure")
        after_test = proof.get("after_test")
        patch_scope = proof.get("patch_scope")
        diff = proof.get("diff")
        command_log = proof.get("command_log")
        expected_boundary = proof.get("evidence_boundary", {}).get("not_proof", [])
        expected_counts = proof.get("observed_counts", {})
        prefix = f"task_proof[{task_id}]"
        if proof.get("schema_version") != "external-heldout-repair-proof/v0.1":
            invalid.append(f"{prefix}.schema_version")
        if proof.get("source_package") != "mcp-python-sdk":
            invalid.append(f"{prefix}.source_package")
        if proof.get("source_repository") != "https://github.com/modelcontextprotocol/python-sdk":
            invalid.append(f"{prefix}.source_repository")
        if proof.get("external_source_heldout") is not True:
            invalid.append(f"{prefix}.external_source_heldout")
        if proof.get("heldout_from_autonomous_gate") is not True:
            invalid.append(f"{prefix}.heldout_from_autonomous_gate")
        if proof.get("independent_external_benchmark") is not False:
            invalid.append(f"{prefix}.independent_external_benchmark")
        if proof.get("target_path") != "mcp/shared/tool_name_validation.py":
            invalid.append(f"{prefix}.target_path")
        function_name = expected["function_name"]
        if proof.get("function_name") != function_name:
            invalid.append(f"{prefix}.function_name")
        for digest_field in ("source_sha256", "broken_source_sha256", "repaired_source_sha256"):
            if not isinstance(proof.get(digest_field), str) or not re.fullmatch(r"[0-9a-f]{64}", proof[digest_field]):
                invalid.append(f"{prefix}.{digest_field}")
        if proof.get("source_sha256") != expected_source_sha256:
            invalid.append(f"{prefix}.source_sha256_manifest")
        if proof.get("broken_source_sha256") == proof.get("repaired_source_sha256"):
            invalid.append(f"{prefix}.repair_changed_source")
        if not isinstance(before_failure, dict):
            invalid.append(f"{prefix}.before_failure")
            before_failure = {}
        if not isinstance(after_test, dict):
            invalid.append(f"{prefix}.after_test")
            after_test = {}
        before_returncode = before_failure.get("returncode")
        after_returncode = after_test.get("returncode")
        if not isinstance(before_returncode, int) or before_returncode == 0:
            invalid.append(f"{prefix}.before_failure_returncode")
        if not isinstance(after_returncode, int) or after_returncode != 0:
            invalid.append(f"{prefix}.after_test_returncode")
        if not isinstance(before_failure.get("command"), list) or not before_failure.get("command"):
            invalid.append(f"{prefix}.before_failure.command")
        if not isinstance(after_test.get("command"), list) or not after_test.get("command"):
            invalid.append(f"{prefix}.after_test.command")
        if not isinstance(patch_scope, dict):
            invalid.append(f"{prefix}.patch_scope")
            patch_scope = {}
        if patch_scope.get("files_touched") != ["mcp/shared/tool_name_validation.py"]:
            invalid.append(f"{prefix}.patch_scope.files_touched")
        if patch_scope.get("stage1_changed_files") != ["mcp/shared/tool_name_validation.py"]:
            invalid.append(f"{prefix}.patch_scope.stage1_changed_files")
        if patch_scope.get("approved_learning_changed_files") != [
            ["mcp/shared/tool_name_validation.py"],
            ["mcp/shared/tool_name_validation.py"],
        ]:
            invalid.append(f"{prefix}.patch_scope.approved_learning_changed_files")
        if patch_scope.get("approved_learning_out_of_scope_files") != [[], []]:
            invalid.append(f"{prefix}.patch_scope.approved_learning_out_of_scope_files")
        if not isinstance(diff, dict):
            invalid.append(f"{prefix}.diff")
            diff = {}
        unified_diff = diff.get("unified_diff")
        if not isinstance(unified_diff, list) or not unified_diff or not all(
            isinstance(line, str) for line in unified_diff
        ):
            invalid.append(f"{prefix}.diff.unified_diff")
            unified_diff = []
        if not isinstance(diff.get("line_count"), int) or diff.get("line_count", 0) <= 0:
            invalid.append(f"{prefix}.diff.line_count")
        if unified_diff and diff.get("line_count") != len(unified_diff):
            invalid.append(f"{prefix}.diff.line_count_matches_unified_diff")
        if diff.get("contains_target_function") is not True:
            invalid.append(f"{prefix}.diff.contains_target_function")
        if function_name and not any(function_name in line for line in unified_diff):
            invalid.append(f"{prefix}.diff.unified_diff_target")
        if not proof.get("agent_diagnosis", {}).get("observations"):
            invalid.append(f"{prefix}.agent_diagnosis.observations")
        if not isinstance(command_log, list) or len(command_log) < 3:
            invalid.append(f"{prefix}.command_log")
            command_log = []
        if command_log:
            if command_log[0] != before_failure:
                invalid.append(f"{prefix}.command_log.before_failure")
            if command_log[-1] != after_test:
                invalid.append(f"{prefix}.command_log.after_test")
            agent_entries = [
                entry for entry in command_log
                if (
                    isinstance(entry, dict)
                    and isinstance(entry.get("command"), list)
                    and entry["command"][:1] == ["run_agent_loop"]
                )
            ]
            if not agent_entries or not all(entry.get("ok") is True for entry in agent_entries):
                invalid.append(f"{prefix}.command_log.agent_repair")
        if "vendored MCP held-out repair task" not in str(proof.get("final_claim", "")):
            invalid.append(f"{prefix}.final_claim")
        for boundary in (
            "native benchmark ingestion",
            "live patch proof",
            "broad unknown-repository repair",
            "external benchmark standing",
            "current remote CI proof",
        ):
            if boundary not in expected_boundary:
                invalid.append(f"{prefix}.evidence_boundary.{boundary}")
        if expected_counts.get("no_learning_solved") != 0:
            invalid.append(f"{prefix}.observed_counts.no_learning_solved")
        if expected_counts.get("approved_learning_solved") != 2:
            invalid.append(f"{prefix}.observed_counts.approved_learning_solved")
        if expected_counts.get("hidden_stage2_tasks") != 2:
            invalid.append(f"{prefix}.observed_counts.hidden_stage2_tasks")
        if expected_counts.get("stability_solved") != 4:
            invalid.append(f"{prefix}.observed_counts.stability_solved")
    missing_task_ids = sorted(set(expected_tasks) - seen_task_ids)
    if missing_task_ids:
        invalid.append(f"task_proof.missing_task_ids={missing_task_ids}")
    return invalid


manifest_entries = read_manifest()
task_source_manifest, task_source_manifest_sha256 = read_task_source_manifest()
missing_required = [path for path in REQUIRED_SOURCE_PATHS if path not in manifest_entries]
if missing_required:
    raise SystemExit(f"external-heldout-benchmark-gate: required manifest paths missing: {missing_required}")
license_text = LICENSE.read_text(encoding="utf-8")
if "MIT License" not in license_text or "Anthropic, PBC" not in license_text:
    raise SystemExit("external-heldout-benchmark-gate: MCP Python SDK license boundary is not the expected MIT text")
attribution_text = ATTRIBUTION.read_text(encoding="utf-8")
if (
    "https://github.com/modelcontextprotocol/python-sdk" not in attribution_text
    or "third_party/mcp_python_sdk/src/mcp/shared/tool_name_validation.py" not in attribution_text
    or "third_party/mcp_python_sdk/LICENSE" not in attribution_text
):
    raise SystemExit("external-heldout-benchmark-gate: upstream attribution boundary is missing MCP Python SDK evidence")
autonomous_selected = autonomous_selected_tests()
overlap = sorted(set(SELECTED_TESTS).intersection(autonomous_selected))
if overlap:
    raise SystemExit(f"external-heldout-benchmark-gate: selected tests overlap autonomous provenance: {overlap}")

observed = parse_pytest_log()
task_proofs = read_task_proofs()
summary = {
    "schema_version": "external-heldout-benchmark-gate/v0.1",
    "status": STATUS,
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "invocation": {
        "git_commit": GIT_COMMIT,
        "summary_json": display_path(SUMMARY_JSON),
        "task_proof_dir": display_path(TASK_PROOF_DIR),
    },
    "source": {
        "package": "mcp-python-sdk",
        "repository": "https://github.com/modelcontextprotocol/python-sdk",
        "license": "MIT",
        "license_path": "third_party/mcp_python_sdk/LICENSE",
        "license_sha256": manifest_entries["third_party/mcp_python_sdk/LICENSE"],
        "manifest_path": "third_party/mcp_python_sdk/MANIFEST.sha256",
        "manifest_sha256": sha256_file(MANIFEST),
        "manifest_entry_count": len(manifest_entries),
        "selected_source_files": {
            "third_party/mcp_python_sdk/src/mcp/shared/tool_name_validation.py": {
                "sha256": manifest_entries[
                    "third_party/mcp_python_sdk/src/mcp/shared/tool_name_validation.py"
                ],
                "bytes": (
                    ROOT
                    / "third_party/mcp_python_sdk/src/mcp/shared/tool_name_validation.py"
                ).stat().st_size,
            },
        },
    },
    "selected_tests": SELECTED_TESTS,
    "task_source_manifest": {
        "path": display_path(TASK_SOURCE_MANIFEST),
        "sha256": task_source_manifest_sha256,
    },
    "task_source_provenance": task_source_manifest,
    "expected_passed": len(SELECTED_TESTS),
    "observed_pytest": observed,
    "log_path": display_path(PYTEST_LOG),
    "log_tail": log_tail(),
    "expected_task_proof_count": len(SELECTED_TESTS),
    "task_proofs": task_proofs,
    "external_source": True,
    "external_source_heldout": True,
    "heldout_from_autonomous_gate": True,
    "independent_external_benchmark": False,
    "not_proof": NOT_PROOF,
}

invalid: list[str] = []
if len(SELECTED_TESTS) != 2:
    invalid.append("selected_tests_count")
if not all(test.startswith("tests/test_upstream_function_file_bundle_regression.py::") for test in SELECTED_TESTS):
    invalid.append("selected_test_node_shape")
if STATUS == "passed" and observed != {"exit_code": 0, "passed": len(SELECTED_TESTS), "skipped": 0, "warnings": 0}:
    invalid.append(f"observed_pytest={observed!r}")
if summary["external_source_heldout"] is not True:
    invalid.append("external_source_heldout")
if summary["heldout_from_autonomous_gate"] is not True:
    invalid.append("heldout_from_autonomous_gate")
if summary["independent_external_benchmark"] is not False:
    invalid.append("independent_external_benchmark_boundary")
if "external benchmark standing" not in summary["not_proof"]:
    invalid.append("not_proof_boundary")
invalid.extend(validate_task_proofs(task_proofs))

SUMMARY_JSON.parent.mkdir(parents=True, exist_ok=True)
SUMMARY_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

if invalid:
    print(f"external-heldout-benchmark-gate: invalid summary fields={'; '.join(invalid)}", file=sys.stderr)
    print(json.dumps(summary, indent=2, sort_keys=True), file=sys.stderr)
    raise SystemExit(1)

if STATUS != "running":
    print(f"external-heldout-benchmark-gate: source-package={summary['source']['package']}")
    print(f"external-heldout-benchmark-gate: source-license={summary['source']['license']}")
    print(f"external-heldout-benchmark-gate: source-manifest-sha256={summary['source']['manifest_sha256']}")
    print(f"external-heldout-benchmark-gate: selected-tests={len(SELECTED_TESTS)}")
    print(f"external-heldout-benchmark-gate: observed-passed={observed['passed']}")
    print(f"external-heldout-benchmark-gate: task-proof-files={len(task_proofs)}")
    print(f"external-heldout-benchmark-gate: external-source-heldout={str(summary['external_source_heldout']).lower()}")
    print(f"external-heldout-benchmark-gate: heldout-from-autonomous-gate={str(summary['heldout_from_autonomous_gate']).lower()}")
    print(f"external-heldout-benchmark-gate: summary={summary['invocation']['summary_json']}")
PY
}

write_summary "running" 0

echo "external-heldout-benchmark-gate: running MCP Python SDK held-out repair regression"
set +e
"$PYTHON_BIN" -m pytest -p no:cacheprovider "${SELECTED_TESTS[@]}" -q > "$PYTEST_LOG" 2>&1
pytest_exit=$?
set -e
cat "$PYTEST_LOG"

if [ "$pytest_exit" -ne 0 ]; then
  write_summary "failed" "$pytest_exit"
  echo "external-heldout-benchmark-gate: FAIL pytest-exit=$pytest_exit" >&2
  exit "$pytest_exit"
fi

write_summary "passed" "$pytest_exit"
echo "external-heldout-benchmark-gate: PASS"
echo "external-heldout-benchmark-gate: not-proof=external benchmark standing; external review; endorsement; stars; reposts; native live autonomy; broad unknown-repository repair; current remote CI proof; owner license decision"
