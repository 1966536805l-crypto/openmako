#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON:-python3}"
export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"

BENCHMARK_JSON="${OPENMAKO_INDEPENDENT_EXTERNAL_HELDOUT_BENCHMARK_JSON:-benchmarks/independent_external_heldout/v0.1/cases.json}"
SUMMARY_JSON="${OPENMAKO_INDEPENDENT_EXTERNAL_HELDOUT_SUMMARY_JSON:-.quantagent/independent_external_heldout_benchmark/last_summary.json}"
SUMMARY_DIR="$(dirname -- "$SUMMARY_JSON")"
SOURCE_SUMMARY_JSON="${OPENMAKO_INDEPENDENT_EXTERNAL_HELDOUT_SOURCE_SUMMARY_JSON:-$SUMMARY_DIR/external_heldout_benchmark_gate/last_summary.json}"
PACKET_JSON="${OPENMAKO_INDEPENDENT_EXTERNAL_HELDOUT_PACKET_JSON:-$SUMMARY_DIR/heldout_reproduction_packet/packet.json}"
GIT_COMMIT="$(git rev-parse HEAD 2>/dev/null || printf unknown)"

mkdir -p "$SUMMARY_DIR"

json_commit_matches_current() {
  local path="$1"
  [ -f "$path" ] || return 1
  "$PYTHON_BIN" - "$path" "$GIT_COMMIT" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
commit = sys.argv[2]
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)
if payload.get("status") != "passed":
    raise SystemExit(1)
if payload.get("invocation", {}).get("git_commit") != commit:
    raise SystemExit(1)
PY
}

SOURCE_SUMMARY_REBUILT=0
if ! json_commit_matches_current "$SOURCE_SUMMARY_JSON"; then
  echo "independent-external-heldout-benchmark-gate: running source held-out gate"
  OPENMAKO_EXTERNAL_HELDOUT_BENCHMARK_SUMMARY_JSON="$SOURCE_SUMMARY_JSON" \
    bash scripts/external_heldout_benchmark_gate.sh
  SOURCE_SUMMARY_REBUILT=1
fi

if [ "$SOURCE_SUMMARY_REBUILT" = "1" ]; then
  rm -f "$PACKET_JSON"
fi

if ! json_commit_matches_current "$PACKET_JSON"; then
  echo "independent-external-heldout-benchmark-gate: building held-out reproduction packet"
  OPENMAKO_HELDOUT_REPRODUCTION_SOURCE_SUMMARY_JSON="$SOURCE_SUMMARY_JSON" \
  OPENMAKO_HELDOUT_REPRODUCTION_PACKET_JSON="$PACKET_JSON" \
    bash scripts/heldout_reproduction_packet.sh
fi

"$PYTHON_BIN" - "$BENCHMARK_JSON" "$SOURCE_SUMMARY_JSON" "$PACKET_JSON" "$SUMMARY_JSON" "$GIT_COMMIT" <<'PY'
from __future__ import annotations

import hashlib
import ast
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path.cwd()
BENCHMARK_JSON = Path(sys.argv[1])
SOURCE_SUMMARY_JSON = Path(sys.argv[2])
PACKET_JSON = Path(sys.argv[3])
SUMMARY_JSON = Path(sys.argv[4])
GIT_COMMIT = sys.argv[5]

BENCHMARK_JSON = BENCHMARK_JSON if BENCHMARK_JSON.is_absolute() else ROOT / BENCHMARK_JSON
SOURCE_SUMMARY_JSON = (
    SOURCE_SUMMARY_JSON if SOURCE_SUMMARY_JSON.is_absolute() else ROOT / SOURCE_SUMMARY_JSON
)
PACKET_JSON = PACKET_JSON if PACKET_JSON.is_absolute() else ROOT / PACKET_JSON
SUMMARY_JSON = SUMMARY_JSON if SUMMARY_JSON.is_absolute() else ROOT / SUMMARY_JSON


def fail(reason: str) -> None:
    raise SystemExit(f"independent-external-heldout-benchmark-gate: {reason}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        fail(f"missing {label}: {display_path(path)}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        fail(f"{label} is not an object")
    return payload


def require_dict(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{field} is not an object")
    return value


def require_sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        fail(f"{field} is not a sha256 hex digest")
    return value


def call_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def validate_selected_test_semantic_lock(
    benchmark: dict[str, Any],
    selected_test_path: Path,
    expected_tests: list[str],
) -> dict[str, Any]:
    lock = require_dict(
        benchmark.get("selected_test_semantic_lock"),
        "selected_test_semantic_lock",
    )
    if lock.get("schema_version") != "openmako-selected-test-semantic-lock/v0.1":
        fail("selected_test_semantic_lock.schema_version mismatch")
    if lock.get("expected_node_ids") != expected_tests:
        fail("selected_test_semantic_lock.expected_node_ids mismatch")
    method_locks = require_dict(lock.get("method_locks"), "selected_test_semantic_lock.method_locks")
    selected_methods = [node_id.rsplit("::", 1)[-1] for node_id in expected_tests]
    if set(method_locks) != set(selected_methods):
        fail("selected_test_semantic_lock.method_locks mismatch")

    source = selected_test_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        fail(f"selected test semantic lock parse failed: {exc}")
    classes = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }
    test_class = classes.get("UpstreamFunctionFileBundleRegressionTest")
    if test_class is None:
        fail("selected test semantic lock missing UpstreamFunctionFileBundleRegressionTest")
    methods = {
        node.name: node
        for node in test_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    checked: list[dict[str, Any]] = []
    for method_name in selected_methods:
        method = methods.get(method_name)
        if method is None:
            fail(f"selected test semantic lock missing method: {method_name}")
        method_lock = require_dict(
            method_locks.get(method_name),
            f"selected_test_semantic_lock.method_locks.{method_name}",
        )
        required_calls = method_lock.get("required_calls")
        if not isinstance(required_calls, list) or not required_calls:
            fail(f"selected test semantic lock missing required_calls: {method_name}")
        if any(not isinstance(item, str) or not item for item in required_calls):
            fail(f"selected test semantic lock malformed required_calls: {method_name}")
        required_fragments = method_lock.get("required_source_fragments")
        if not isinstance(required_fragments, list) or not required_fragments:
            fail(f"selected test semantic lock missing required_source_fragments: {method_name}")
        if any(not isinstance(item, str) or not item for item in required_fragments):
            fail(f"selected test semantic lock malformed required_source_fragments: {method_name}")
        observed_calls = call_names(method)
        missing_calls = sorted(set(required_calls) - observed_calls)
        if missing_calls:
            fail(
                "selected test semantic lock missing required calls "
                f"for {method_name}: {', '.join(missing_calls)}"
            )
        method_source = ast.get_source_segment(source, method) or ""
        missing_fragments = [
            fragment for fragment in required_fragments if fragment not in method_source
        ]
        if missing_fragments:
            fail(
                "selected test semantic lock missing source fragments "
                f"for {method_name}: {', '.join(missing_fragments)}"
            )
        checked.append(
            {
                "method": method_name,
                "required_call_count": len(required_calls),
                "required_source_fragment_count": len(required_fragments),
            }
        )

    return {
        "schema_version": lock["schema_version"],
        "expected_node_ids_sha256": hashlib.sha256(
            ("\n".join(lock["expected_node_ids"]) + "\n").encode()
        ).hexdigest(),
        "checked_methods": checked,
    }


benchmark = read_json(BENCHMARK_JSON, "benchmark definition")
source_summary = read_json(SOURCE_SUMMARY_JSON, "source summary")
packet = read_json(PACKET_JSON, "held-out reproduction packet")

if benchmark.get("schema_version") != "independent-external-heldout-benchmark-cases/v0.1":
    fail("benchmark schema_version mismatch")
if benchmark.get("benchmark_id") != "openmako-independent-external-heldout-v0.1":
    fail("benchmark_id mismatch")
cases = benchmark.get("cases")
if not isinstance(cases, list) or benchmark.get("case_count") != len(cases) or len(cases) != 2:
    fail("case_count mismatch")

case_ids: set[str] = set()
expected_task_ids: set[str] = set()
expected_labels: dict[str, str] = {}
expected_tests: list[str] = []
expected_functions: dict[str, str] = {}
expected_targets: dict[str, str] = {}
for case in cases:
    case = require_dict(case, "case")
    case_id = case.get("case_id")
    task_id = case.get("expected_task_id")
    selected_test = case.get("selected_test")
    function_name = case.get("function_name")
    target_path = case.get("target_path")
    if not isinstance(case_id, str) or not case_id:
        fail("case_id missing")
    if case_id in case_ids:
        fail(f"duplicate case_id: {case_id}")
    case_ids.add(case_id)
    if not isinstance(task_id, str) or not task_id:
        fail(f"{case_id}.expected_task_id missing")
    if task_id in expected_task_ids:
        fail(f"duplicate expected_task_id: {task_id}")
    expected_task_ids.add(task_id)
    if case.get("expected_label") != "supported_repair_claim":
        fail(f"{case_id}.expected_label mismatch")
    if not isinstance(selected_test, str) or "::" not in selected_test:
        fail(f"{case_id}.selected_test malformed")
    if not isinstance(function_name, str) or not function_name:
        fail(f"{case_id}.function_name missing")
    if target_path != "mcp/shared/tool_name_validation.py":
        fail(f"{case_id}.target_path mismatch")
    expected_tests.append(selected_test)
    expected_labels[task_id] = "supported_repair_claim"
    expected_functions[task_id] = function_name
    expected_targets[task_id] = target_path

selected_tests_digest = hashlib.sha256(("\n".join(expected_tests) + "\n").encode()).hexdigest()
if benchmark.get("selected_tests_sha256") != selected_tests_digest:
    fail("benchmark selected_tests_sha256 mismatch")

selected_test_file = require_dict(benchmark.get("selected_test_file"), "selected_test_file")
if selected_test_file.get("path") != "tests/test_upstream_function_file_bundle_regression.py":
    fail("selected_test_file.path mismatch")
expected_test_sha = require_sha(selected_test_file.get("sha256"), "selected_test_file.sha256")
if sha256_file(ROOT / selected_test_file["path"]) != expected_test_sha:
    fail("selected test file sha256 mismatch")
semantic_lock_summary = validate_selected_test_semantic_lock(
    benchmark,
    ROOT / selected_test_file["path"],
    expected_tests,
)

external_source = require_dict(benchmark.get("external_source"), "external_source")
if external_source.get("package") != "mcp-python-sdk":
    fail("external_source.package mismatch")
if external_source.get("repository") != "https://github.com/modelcontextprotocol/python-sdk":
    fail("external_source.repository mismatch")
if external_source.get("license") != "MIT":
    fail("external_source.license mismatch")
manifest_path = external_source.get("manifest_path")
if manifest_path != "third_party/mcp_python_sdk/MANIFEST.sha256":
    fail("external_source.manifest_path mismatch")
if sha256_file(ROOT / manifest_path) != require_sha(
    external_source.get("manifest_sha256"), "external_source.manifest_sha256"
):
    fail("external_source.manifest_sha256 mismatch")
source_files = require_dict(external_source.get("selected_source_files"), "selected_source_files")
for rel_path, meta in source_files.items():
    meta = require_dict(meta, f"selected_source_files.{rel_path}")
    if not (ROOT / rel_path).is_file():
        fail(f"selected source file missing: {rel_path}")
    if sha256_file(ROOT / rel_path) != require_sha(meta.get("sha256"), f"{rel_path}.sha256"):
        fail(f"selected source file sha256 mismatch: {rel_path}")

scope = require_dict(benchmark.get("independence_scope"), "independence_scope")
required_scope = {
    "external_source_heldout": True,
    "heldout_from_autonomous_gate": True,
    "independent_from_autonomous_task_manifest": True,
    "repo_defined_benchmark_packet": True,
    "third_party_benchmark_standing": False,
}
for key, expected in required_scope.items():
    if scope.get(key) is not expected:
        fail(f"independence_scope.{key} mismatch")

if source_summary.get("schema_version") != "external-heldout-benchmark-gate/v0.1":
    fail("source summary schema_version mismatch")
if source_summary.get("status") != "passed":
    fail("source summary status is not passed")
if source_summary.get("invocation", {}).get("git_commit") != GIT_COMMIT:
    fail("source summary git_commit mismatch")
if source_summary.get("external_source_heldout") is not True:
    fail("source summary external_source_heldout mismatch")
if source_summary.get("heldout_from_autonomous_gate") is not True:
    fail("source summary heldout_from_autonomous_gate mismatch")
if source_summary.get("independent_external_benchmark") is not False:
    fail("source summary independent_external_benchmark boundary mismatch")
if source_summary.get("selected_tests") != expected_tests:
    fail("source summary selected_tests mismatch")
observed = source_summary.get("observed_pytest")
if observed != {"exit_code": 0, "passed": 2, "skipped": 0, "warnings": 0}:
    fail(f"source summary observed_pytest mismatch: {observed!r}")

source_manifest = require_dict(source_summary.get("task_source_manifest"), "source task manifest")
if source_manifest.get("sha256") != sha256_file(ROOT / source_manifest.get("path", "")):
    fail("source task manifest sha256 mismatch")
source_provenance = require_dict(source_summary.get("task_source_provenance"), "task_source_provenance")
if source_provenance.get("external_heldout") is not True:
    fail("task_source_provenance.external_heldout mismatch")
if source_provenance.get("selected_tests_sha256") != selected_tests_digest:
    fail("task_source_provenance selected_tests_sha256 mismatch")

task_proofs = source_summary.get("task_proofs")
if not isinstance(task_proofs, list) or len(task_proofs) != 2:
    fail("task proof count mismatch")
proof_task_ids = {proof.get("task_id") for proof in task_proofs if isinstance(proof, dict)}
if proof_task_ids != expected_task_ids:
    fail("task proof ids mismatch")
case_results: list[dict[str, Any]] = []
for proof in task_proofs:
    proof = require_dict(proof, "task proof")
    task_id = str(proof["task_id"])
    if proof.get("function_name") != expected_functions[task_id]:
        fail(f"{task_id}.function_name mismatch")
    if proof.get("target_path") != expected_targets[task_id]:
        fail(f"{task_id}.target_path mismatch")
    if proof.get("before_failure", {}).get("returncode") == 0:
        fail(f"{task_id}.before_failure was not a failure")
    if proof.get("after_test", {}).get("returncode") != 0:
        fail(f"{task_id}.after_test did not pass")
    if proof.get("diff", {}).get("contains_target_function") is not True:
        fail(f"{task_id}.diff missing target function")
    if "vendored MCP held-out repair task" not in str(proof.get("final_claim", "")):
        fail(f"{task_id}.final_claim boundary mismatch")
    case_results.append(
        {
            "task_id": task_id,
            "label": expected_labels[task_id],
            "before_failure_returncode": proof["before_failure"]["returncode"],
            "after_test_returncode": proof["after_test"]["returncode"],
            "target_diff": True,
        }
    )

if packet.get("schema_version") != "heldout-reproduction-packet/v0.1":
    fail("packet schema_version mismatch")
if packet.get("status") != "passed":
    fail("packet status mismatch")
if packet.get("invocation", {}).get("git_commit") != GIT_COMMIT:
    fail("packet git_commit mismatch")
if packet.get("task_proof_count") != 2:
    fail("packet task_proof_count mismatch")
if packet.get("labels") != expected_labels:
    fail("packet labels mismatch")
if packet.get("external_source_heldout") is not True:
    fail("packet external_source_heldout mismatch")
if packet.get("heldout_from_autonomous_gate") is not True:
    fail("packet heldout_from_autonomous_gate mismatch")
if packet.get("independent_external_benchmark") is not False:
    fail("packet independent_external_benchmark boundary mismatch")
raw_files = packet.get("raw_evidence_files")
if not isinstance(raw_files, dict) or len(raw_files) < 4:
    fail("packet raw_evidence_files missing")
for key, value in raw_files.items():
    if not isinstance(key, str) or not isinstance(value, str) or not value.startswith("sha256:"):
        fail("packet raw_evidence_files malformed")

required_not_proof = {
    "third-party benchmark standing",
    "external review",
    "endorsement",
    "stars",
    "reposts",
    "native live autonomy",
    "broad unknown-repository repair",
    "GitHub Actions artifact zip contents",
}
if not required_not_proof.issubset(set(benchmark.get("not_proof") or [])):
    fail("benchmark not_proof boundary mismatch")

summary = {
    "schema_version": "independent-external-heldout-benchmark-gate/v0.1",
    "status": "passed",
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "invocation": {
        "git_commit": GIT_COMMIT,
        "proof_command": "bash scripts/independent_external_heldout_benchmark_gate.sh",
    },
    "benchmark": {
        "path": display_path(BENCHMARK_JSON),
        "sha256": "sha256:" + sha256_file(BENCHMARK_JSON),
        "benchmark_id": benchmark["benchmark_id"],
        "case_count": len(cases),
        "case_ids": sorted(case_ids),
    },
    "source_summary": {
        "path": display_path(SOURCE_SUMMARY_JSON),
        "sha256": "sha256:" + sha256_file(SOURCE_SUMMARY_JSON),
    },
    "heldout_reproduction_packet": {
        "path": display_path(PACKET_JSON),
        "sha256": "sha256:" + sha256_file(PACKET_JSON),
    },
    "case_results": sorted(case_results, key=lambda item: item["task_id"]),
    "selected_tests": expected_tests,
    "selected_tests_sha256": selected_tests_digest,
    "selected_test_semantic_lock": semantic_lock_summary,
    "observed_pytest": observed,
    "raw_evidence_files": raw_files,
    "external_source": external_source,
    "independence_scope": scope,
    "external_source_heldout": True,
    "heldout_from_autonomous_gate": True,
    "independent_from_autonomous_task_manifest": True,
    "repo_defined_benchmark_packet": True,
    "independent_external_heldout_benchmark": True,
    "third_party_benchmark_standing": False,
    "not_proof": benchmark["not_proof"],
}

SUMMARY_JSON.parent.mkdir(parents=True, exist_ok=True)
SUMMARY_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

print(f"independent-external-heldout-benchmark-gate: benchmark={display_path(BENCHMARK_JSON)}")
print(f"independent-external-heldout-benchmark-gate: benchmark-sha256={summary['benchmark']['sha256']}")
print(f"independent-external-heldout-benchmark-gate: case-count={len(cases)}")
print(f"independent-external-heldout-benchmark-gate: observed-passed={observed['passed']}")
print("independent-external-heldout-benchmark-gate: selected-test-semantic-lock=passed")
print("independent-external-heldout-benchmark-gate: independent-from-autonomous-task-manifest=true")
print("independent-external-heldout-benchmark-gate: repo-defined-benchmark-packet=true")
print("independent-external-heldout-benchmark-gate: third-party-benchmark-standing=false")
print(f"independent-external-heldout-benchmark-gate: summary={display_path(SUMMARY_JSON)}")
print("independent-external-heldout-benchmark-gate: PASS")
print(
    "independent-external-heldout-benchmark-gate: "
    "not-proof=third-party benchmark standing; external review; endorsement; "
    "stars; reposts; native live autonomy; broad unknown-repository repair; "
    "GitHub Actions artifact zip contents"
)
PY
