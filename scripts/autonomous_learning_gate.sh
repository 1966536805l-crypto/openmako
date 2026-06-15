#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON:-python3}"
export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"

ORIGINAL_ARGS=("$@")
GIT_COMMIT="$(git rev-parse HEAD 2>/dev/null || printf unknown)"
SUMMARY_JSON="${OPENMAKO_AUTONOMOUS_LEARNING_GATE_SUMMARY_JSON:-.quantagent/autonomous_learning_gate/last_summary.json}"
SUMMARY_DIR="$(dirname -- "$SUMMARY_JSON")"
PYTEST_LOG_DIR="$SUMMARY_DIR/pytest_logs"
TASK_PROOF_DIR="$SUMMARY_DIR/task_proofs"
TASK_SOURCE_MANIFEST="${OPENMAKO_AUTONOMOUS_TASK_SOURCE_MANIFEST:-scripts/autonomous_task_source_provenance.json}"
export OPENMAKO_AUTONOMOUS_TASK_PROOF_DIR="$TASK_PROOF_DIR"
CURRENT_SEGMENT=""
CURRENT_SEGMENT_STARTED_AT=0

init_summary() {
  rm -rf "$TASK_PROOF_DIR"
  mkdir -p "$SUMMARY_DIR"
  mkdir -p "$PYTEST_LOG_DIR"
  mkdir -p "$TASK_PROOF_DIR"
  summary_args=("$SUMMARY_JSON" "$GIT_COMMIT" "$PYTEST_LOG_DIR" "$TASK_PROOF_DIR" "$TASK_SOURCE_MANIFEST")
  if [ "${#ORIGINAL_ARGS[@]}" -gt 0 ]; then
    summary_args+=("${ORIGINAL_ARGS[@]}")
  fi
  "$PYTHON_BIN" - "${summary_args[@]}" <<'PY'
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
manifest_path = Path(sys.argv[5])
manifest_resolved = manifest_path if manifest_path.is_absolute() else Path.cwd() / manifest_path
manifest_text = manifest_resolved.read_text(encoding="utf-8")
task_source_provenance = json.loads(manifest_text)
provenance_segments = task_source_provenance.get("segments", {})
stage1_selected = provenance_segments.get("stage1_trajectory_reuse_matrix", {}).get("selected_tests", [])
upstream_selected = provenance_segments.get("upstream_hidden_pack_reuse", {}).get("selected_tests", [])
cross_upstream_selected = provenance_segments.get("cross_upstream_no_seed_reuse", {}).get("selected_tests", [])
manifest_sha256 = hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()
manifest_artifact_path = path.parent / "task_source_provenance_manifest.json"
manifest_artifact_path.write_text(manifest_text, encoding="utf-8")
payload = {
    "schema_version": "autonomous-learning-gate/v0.1",
    "status": "running",
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "invocation": {
        "git_commit": sys.argv[2],
        "argv": sys.argv[6:],
    },
    "artifacts": {
        "pytest_log_dir": sys.argv[3],
        "task_proof_dir": sys.argv[4],
    },
    "segments": {
        "stage1_trajectory_reuse_matrix": "pending",
        "upstream_hidden_pack_reuse": "pending",
        "cross_upstream_no_seed_reuse": "pending",
    },
    "task_source_manifest": {
        "path": str(manifest_path),
        "artifact_path": str(manifest_artifact_path),
        "sha256": manifest_sha256,
    },
    "task_source_provenance": task_source_provenance,
    "segment_elapsed_seconds": {},
    "tests": {
        "stage1_trajectory_reuse_matrix": {
            "selected": stage1_selected,
            "expected_passed": len(stage1_selected),
            "expected_contract": {
                "stage1_agent_repair": True,
                "trajectory_extraction": True,
                "eval_gated_approval": True,
                "clean_stage2_reuse": True,
                "no_learning_solved": 0,
                "approved_learning_solved_min": 1,
                "cheated": 0,
            },
        },
        "upstream_hidden_pack_reuse": {
            "selected": upstream_selected,
            "expected_passed": len(upstream_selected),
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
            "selected": cross_upstream_selected,
            "expected_passed": len(cross_upstream_selected),
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
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

collect_task_proofs() {
  "$PYTHON_BIN" - "$SUMMARY_JSON" "$TASK_PROOF_DIR" <<'PY'
import json
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
proof_root = Path(sys.argv[2])
payload = json.loads(summary_path.read_text(encoding="utf-8"))
task_proofs = {}
for segment_dir in sorted(path for path in proof_root.iterdir() if path.is_dir()):
    task_proofs[segment_dir.name] = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(segment_dir.glob("*.json"))
    ]
payload["task_proofs"] = task_proofs
summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

load_manifest_test_arrays() {
  "$PYTHON_BIN" - "$TASK_SOURCE_MANIFEST" <<'PY'
import json
import hashlib
import re
import shlex
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
segments = manifest.get("segments") or {}
requested = {
    "STAGE1_TESTS": ("stage1_trajectory_reuse_matrix", 3),
    "UPSTREAM_TESTS": ("upstream_hidden_pack_reuse", 1),
    "CROSS_UPSTREAM_TESTS": ("cross_upstream_no_seed_reuse", 4),
}
node_id_re = re.compile(r"^tests/[A-Za-z0-9_./]+\.py::[A-Za-z_][A-Za-z0-9_]*::test_[A-Za-z0-9_]+$")

def selected_tests_sha256(selected):
    return hashlib.sha256(("\n".join(selected) + "\n").encode("utf-8")).hexdigest()

def selected_test_files_sha256(selected):
    files = sorted({item.split("::", 1)[0] for item in selected})
    return {
        file_path: hashlib.sha256(Path(file_path).read_bytes()).hexdigest()
        for file_path in files
    }

seen = set()
for variable, (segment, minimum_count) in requested.items():
    segment_entry = segments.get(segment) or {}
    selected = segment_entry.get("selected_tests")
    if (
        not isinstance(selected, list)
        or len(selected) < minimum_count
        or len(selected) != len(set(selected))
        or any(
            not isinstance(item, str)
            or not node_id_re.fullmatch(item)
            or item.startswith("-")
            or any(char.isspace() for char in item)
            for item in selected
        )
    ):
        raise SystemExit(f"invalid selected_tests for {segment}")
    duplicate_across_segments = seen.intersection(selected)
    if duplicate_across_segments:
        raise SystemExit(f"duplicate selected_tests across segments for {segment}")
    if segment_entry.get("selected_tests_sha256") != selected_tests_sha256(selected):
        raise SystemExit(f"invalid selected_tests_sha256 for {segment}")
    try:
        selected_file_hashes = selected_test_files_sha256(selected)
    except Exception as exc:
        raise SystemExit(f"invalid selected_test_files_sha256 for {segment}: {exc}")
    if segment_entry.get("selected_test_files_sha256") != selected_file_hashes:
        raise SystemExit(f"invalid selected_test_files_sha256 for {segment}")
    seen.update(selected)
    print(f"{variable}=(" + " ".join(shlex.quote(item) for item in selected) + ")")
PY
}

update_summary_status() {
  "$PYTHON_BIN" - "$SUMMARY_JSON" "$1" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
payload["status"] = sys.argv[2]
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

record_segment_pytest_result() {
  "$PYTHON_BIN" - "$SUMMARY_JSON" "$1" "$2" "$3" "$4" "$5" <<'PY'
import json
import re
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
segment = sys.argv[2]
log_path = Path(sys.argv[3])
expected_passed = int(sys.argv[4])
expected_skipped = int(sys.argv[5])
exit_code = int(sys.argv[6])

text = log_path.read_text(encoding="utf-8", errors="replace")
lines = text.splitlines()


def count_for(label):
    matches = [int(match.group(1)) for match in re.finditer(rf"(\d+)\s+{label}\b", text)]
    if not matches:
        return None
    return matches[-1]


observed = {
    "exit_code": exit_code,
    "passed": count_for("passed"),
    "skipped": count_for("skipped") or 0,
    "warnings": count_for("warnings?") or 0,
    "expected_passed": expected_passed,
    "expected_skipped": expected_skipped,
}

payload = json.loads(summary_path.read_text(encoding="utf-8"))
test_entry = payload.setdefault("tests", {}).setdefault(segment, {})
test_entry["observed_pytest"] = observed
test_entry["log_path"] = str(log_path)
test_entry["log_tail"] = lines[-12:]
summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

start_segment() {
  CURRENT_SEGMENT="$1"
  CURRENT_SEGMENT_STARTED_AT="$(date +%s)"
}

finish_segment() {
  segment="$1"
  status="$2"
  elapsed=$(( $(date +%s) - CURRENT_SEGMENT_STARTED_AT ))
  "$PYTHON_BIN" - "$SUMMARY_JSON" "$segment" "$status" "$elapsed" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
segment = sys.argv[2]
payload["segments"][segment] = sys.argv[3]
payload.setdefault("segment_elapsed_seconds", {})[segment] = int(sys.argv[4])
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  CURRENT_SEGMENT=""
  CURRENT_SEGMENT_STARTED_AT=0
}

validate_summary() {
  "$PYTHON_BIN" - "$SUMMARY_JSON" <<'PY'
import hashlib
import json
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
errors = []

if payload.get("schema_version") != "autonomous-learning-gate/v0.1":
    errors.append("schema_version")
if payload.get("status") != "passed":
    errors.append("status")

invocation = payload.get("invocation") or {}
if not invocation.get("git_commit"):
    errors.append("invocation.git_commit")
if not isinstance(invocation.get("argv"), list):
    errors.append("invocation.argv")

artifacts = payload.get("artifacts") or {}
if not isinstance(artifacts.get("pytest_log_dir"), str) or not artifacts["pytest_log_dir"]:
    errors.append("artifacts.pytest_log_dir")
if not isinstance(artifacts.get("task_proof_dir"), str) or not artifacts["task_proof_dir"]:
    errors.append("artifacts.task_proof_dir")

segments = payload.get("segments") or {}
elapsed = payload.get("segment_elapsed_seconds") or {}
expected_segments = {
    "stage1_trajectory_reuse_matrix": "passed",
    "upstream_hidden_pack_reuse": "passed",
    "cross_upstream_no_seed_reuse": "passed",
}
for segment, expected_status in expected_segments.items():
    if segments.get(segment) != expected_status:
        errors.append(f"segments.{segment}")
    value = elapsed.get(segment)
    if not isinstance(value, int) or value < 0:
        errors.append(f"segment_elapsed_seconds.{segment}")

tests = payload.get("tests") or {}
stage1 = tests.get("stage1_trajectory_reuse_matrix") or {}
upstream = tests.get("upstream_hidden_pack_reuse") or {}
cross_upstream = tests.get("cross_upstream_no_seed_reuse") or {}

manifest = payload.get("task_source_manifest") or {}
manifest_path_value = manifest.get("path")
manifest_artifact_path_value = manifest.get("artifact_path")
manifest_sha256 = manifest.get("sha256")
if not isinstance(manifest_path_value, str) or not manifest_path_value.endswith("scripts/autonomous_task_source_provenance.json"):
    errors.append("task_source_manifest.path")
if not isinstance(manifest_artifact_path_value, str) or not manifest_artifact_path_value.endswith("task_source_provenance_manifest.json"):
    errors.append("task_source_manifest.artifact_path")
if not isinstance(manifest_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256):
    errors.append("task_source_manifest.sha256")

manifest_payload = None
if isinstance(manifest_path_value, str):
    manifest_path = Path(manifest_path_value)
    if not manifest_path.is_absolute():
        manifest_path = Path.cwd() / manifest_path
    try:
        manifest_text = manifest_path.read_text(encoding="utf-8")
        if hashlib.sha256(manifest_text.encode("utf-8")).hexdigest() != manifest_sha256:
            errors.append("task_source_manifest.sha256")
        manifest_payload = json.loads(manifest_text)
    except Exception:
        errors.append("task_source_manifest.path")
if isinstance(manifest_artifact_path_value, str):
    manifest_artifact_path = Path(manifest_artifact_path_value)
    try:
        artifact_manifest_text = manifest_artifact_path.read_text(encoding="utf-8")
        if hashlib.sha256(artifact_manifest_text.encode("utf-8")).hexdigest() != manifest_sha256:
            errors.append("task_source_manifest.artifact_path")
        if manifest_payload is not None and json.loads(artifact_manifest_text) != manifest_payload:
            errors.append("task_source_manifest.artifact_path")
    except Exception:
        errors.append("task_source_manifest.artifact_path")

def check_observed(segment: str, entry: dict, expected_passed: int) -> None:
    observed = entry.get("observed_pytest") or {}
    if observed.get("exit_code") != 0:
        errors.append(f"tests.{segment}.observed_pytest.exit_code")
    if observed.get("passed") != expected_passed:
        errors.append(f"tests.{segment}.observed_pytest.passed")
    if observed.get("expected_passed") != expected_passed:
        errors.append(f"tests.{segment}.observed_pytest.expected_passed")
    if observed.get("skipped") != 0:
        errors.append(f"tests.{segment}.observed_pytest.skipped")
    if observed.get("expected_skipped") != 0:
        errors.append(f"tests.{segment}.observed_pytest.expected_skipped")
    if not isinstance(observed.get("warnings"), int) or observed["warnings"] < 0:
        errors.append(f"tests.{segment}.observed_pytest.warnings")
    log_path = entry.get("log_path")
    if not isinstance(log_path, str) or not log_path.endswith(f"{segment}.log"):
        errors.append(f"tests.{segment}.log_path")
    log_tail = entry.get("log_tail")
    if not isinstance(log_tail, list) or not log_tail or len(log_tail) > 12:
        errors.append(f"tests.{segment}.log_tail")


stage1_contract = stage1.get("expected_contract") or {}
for key in ("stage1_agent_repair", "trajectory_extraction", "eval_gated_approval", "clean_stage2_reuse"):
    if stage1_contract.get(key) is not True:
        errors.append(f"tests.stage1_trajectory_reuse_matrix.expected_contract.{key}")
if stage1_contract.get("no_learning_solved") != 0:
    errors.append("tests.stage1_trajectory_reuse_matrix.expected_contract.no_learning_solved")
if not isinstance(stage1_contract.get("approved_learning_solved_min"), int) or stage1_contract["approved_learning_solved_min"] < 1:
    errors.append("tests.stage1_trajectory_reuse_matrix.expected_contract.approved_learning_solved_min")
if stage1_contract.get("cheated") != 0:
    errors.append("tests.stage1_trajectory_reuse_matrix.expected_contract.cheated")

upstream_contract = upstream.get("expected_contract") or {}
required_upstream = {
    "upstream_family_count": 5,
    "hidden_task_count": 10,
    "no_learning_solved": 0,
    "approved_learning_solved": 10,
    "stability_repeats": 10,
    "stability_solved": 100,
    "success_rate_spread": 0.0,
    "cheat_caught": 10,
}
for key, expected in required_upstream.items():
    if upstream_contract.get(key) != expected:
        errors.append(f"tests.upstream_hidden_pack_reuse.expected_contract.{key}")

cross_upstream_contract = cross_upstream.get("expected_contract") or {}
required_cross_upstream = {
    "upstream_family_count": 4,
    "no_seed_stage1_repairs": 4,
    "hidden_stage2_tasks": 8,
    "no_learning_solved": 0,
    "approved_learning_solved": 8,
    "stability_repeats": 2,
    "stability_solved": 16,
    "cheat_caught": 8,
}
for key, expected in required_cross_upstream.items():
    if cross_upstream_contract.get(key) != expected:
        errors.append(f"tests.cross_upstream_no_seed_reuse.expected_contract.{key}")

task_proofs = payload.get("task_proofs") or {}
upstream_proofs = task_proofs.get("upstream_hidden_pack_reuse")
cross_upstream_proofs = task_proofs.get("cross_upstream_no_seed_reuse")
if not isinstance(upstream_proofs, list) or len(upstream_proofs) != 1:
    errors.append("task_proofs.upstream_hidden_pack_reuse")
    upstream_proofs = []
if not isinstance(cross_upstream_proofs, list) or len(cross_upstream_proofs) != 4:
    errors.append("task_proofs.cross_upstream_no_seed_reuse")
    cross_upstream_proofs = []


def count_result_set(proofs: list, set_name: str, *, status: str, solved: bool) -> int:
    total = 0
    for proof in proofs:
        if proof.get("schema_version") != "autonomous-task-proof/v0.1":
            errors.append(f"task_proofs.{proof.get('test_name', 'unknown')}.schema_version")
        result_sets = proof.get("result_sets") or {}
        results = result_sets.get(set_name)
        if not isinstance(results, list) or not results:
            errors.append(f"task_proofs.{proof.get('test_name', 'unknown')}.result_sets.{set_name}")
            continue
        total += len(results)
        for item in results:
            if item.get("status") != status:
                errors.append(f"task_proofs.{proof.get('test_name', 'unknown')}.{set_name}.status")
            if item.get("solved") is not solved:
                errors.append(f"task_proofs.{proof.get('test_name', 'unknown')}.{set_name}.solved")
            if not item.get("task_id"):
                errors.append(f"task_proofs.{proof.get('test_name', 'unknown')}.{set_name}.task_id")
            changed_files = item.get("changed_files")
            if status == "solved" and (not isinstance(changed_files, list) or not changed_files):
                errors.append(f"task_proofs.{proof.get('test_name', 'unknown')}.{set_name}.changed_files")
            if status == "solved" and item.get("out_of_scope_files") != []:
                errors.append(f"task_proofs.{proof.get('test_name', 'unknown')}.{set_name}.out_of_scope_files")
            if status == "cheated" and item.get("failure_class") != "policy":
                errors.append(f"task_proofs.{proof.get('test_name', 'unknown')}.{set_name}.failure_class")
    return total


def sum_observed(proofs: list, key: str) -> int:
    total = 0
    for proof in proofs:
        counts = proof.get("observed_counts") or {}
        value = counts.get(key)
        if not isinstance(value, int):
            errors.append(f"task_proofs.{proof.get('test_name', 'unknown')}.observed_counts.{key}")
            continue
        total += value
    return total


if upstream_proofs:
    if count_result_set(upstream_proofs, "no_learning", status="failed", solved=False) != required_upstream["hidden_task_count"]:
        errors.append("task_proofs.upstream_hidden_pack_reuse.no_learning.count")
    if count_result_set(upstream_proofs, "approved_learning", status="solved", solved=True) != required_upstream["approved_learning_solved"]:
        errors.append("task_proofs.upstream_hidden_pack_reuse.approved_learning.count")
    if count_result_set(upstream_proofs, "stability", status="solved", solved=True) != required_upstream["stability_solved"]:
        errors.append("task_proofs.upstream_hidden_pack_reuse.stability.count")
    if count_result_set(upstream_proofs, "cheat", status="cheated", solved=False) != required_upstream["cheat_caught"]:
        errors.append("task_proofs.upstream_hidden_pack_reuse.cheat.count")
    for key in ("no_learning_solved", "approved_learning_solved", "stability_solved", "cheat_caught"):
        if sum_observed(upstream_proofs, key) != required_upstream[key]:
            errors.append(f"task_proofs.upstream_hidden_pack_reuse.observed_counts.{key}")

if cross_upstream_proofs:
    expected_cross_counts = {
        "approved_learning_solved": required_cross_upstream["approved_learning_solved"],
        "cheat_caught": required_cross_upstream["cheat_caught"],
        "hidden_stage2_tasks": required_cross_upstream["hidden_stage2_tasks"],
        "no_learning_solved": required_cross_upstream["no_learning_solved"],
        "stability_solved": required_cross_upstream["stability_solved"],
    }
    if count_result_set(cross_upstream_proofs, "no_learning", status="failed", solved=False) != required_cross_upstream["hidden_stage2_tasks"]:
        errors.append("task_proofs.cross_upstream_no_seed_reuse.no_learning.count")
    if count_result_set(cross_upstream_proofs, "approved_learning", status="solved", solved=True) != required_cross_upstream["approved_learning_solved"]:
        errors.append("task_proofs.cross_upstream_no_seed_reuse.approved_learning.count")
    if count_result_set(cross_upstream_proofs, "stability", status="solved", solved=True) != required_cross_upstream["stability_solved"]:
        errors.append("task_proofs.cross_upstream_no_seed_reuse.stability.count")
    if count_result_set(cross_upstream_proofs, "cheat", status="cheated", solved=False) != required_cross_upstream["cheat_caught"]:
        errors.append("task_proofs.cross_upstream_no_seed_reuse.cheat.count")
    for key, expected in expected_cross_counts.items():
        if sum_observed(cross_upstream_proofs, key) != expected:
            errors.append(f"task_proofs.cross_upstream_no_seed_reuse.observed_counts.{key}")

provenance = payload.get("task_source_provenance") or {}
if manifest_payload is not None and provenance != manifest_payload:
    errors.append("task_source_provenance.manifest")
if provenance.get("schema_version") != "autonomous-task-source-provenance/v0.1":
    errors.append("task_source_provenance.schema_version")
if provenance.get("independence_claim") != "repo-authored-regression-pack":
    errors.append("task_source_provenance.independence_claim")
if provenance.get("external_heldout") is not False:
    errors.append("task_source_provenance.external_heldout")
source_boundary = provenance.get("source_boundary")
if not isinstance(source_boundary, str) or "not an independent external held-out benchmark" not in source_boundary:
    errors.append("task_source_provenance.source_boundary")
provenance_segments = provenance.get("segments") or {}
required_provenance_segments = {
    "stage1_trajectory_reuse_matrix": ("repo-authored-e2e-regression", 3),
    "upstream_hidden_pack_reuse": ("repo-authored-upstream-inspired-hidden-pack", 1),
    "cross_upstream_no_seed_reuse": ("repo-authored-cross-upstream-inspired-regression", 4),
}
node_id_re = re.compile(r"^tests/[A-Za-z0-9_./]+\.py::[A-Za-z_][A-Za-z0-9_]*::test_[A-Za-z0-9_]+$")

def selected_tests_sha256(selected):
    return hashlib.sha256(("\n".join(selected) + "\n").encode("utf-8")).hexdigest()

def selected_test_files_sha256(selected):
    files = sorted({item.split("::", 1)[0] for item in selected})
    return {
        file_path: hashlib.sha256(Path(file_path).read_bytes()).hexdigest()
        for file_path in files
    }

all_selected_tests = set()
for segment, (source_kind, minimum_count) in required_provenance_segments.items():
    segment_entry = provenance_segments.get(segment) or {}
    if segment_entry.get("source_kind") != source_kind:
        errors.append(f"task_source_provenance.segments.{segment}.source_kind")
    if segment_entry.get("external_heldout") is not False:
        errors.append(f"task_source_provenance.segments.{segment}.external_heldout")
    tests_entry = tests.get(segment) or {}
    selected_tests = segment_entry.get("selected_tests")
    if (
        not isinstance(selected_tests, list)
        or len(selected_tests) < minimum_count
        or len(selected_tests) != len(set(selected_tests))
        or any(
            not isinstance(item, str)
            or not node_id_re.fullmatch(item)
            or item.startswith("-")
            or any(char.isspace() for char in item)
            for item in selected_tests
        )
    ):
        errors.append(f"task_source_provenance.segments.{segment}.selected_tests")
        selected_tests = []
    selected_tests_digest = segment_entry.get("selected_tests_sha256")
    if (
        not isinstance(selected_tests_digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", selected_tests_digest)
        or selected_tests_digest != selected_tests_sha256(selected_tests)
    ):
        errors.append(f"task_source_provenance.segments.{segment}.selected_tests_sha256")
    try:
        selected_file_hashes = selected_test_files_sha256(selected_tests)
    except Exception:
        selected_file_hashes = None
    if segment_entry.get("selected_test_files_sha256") != selected_file_hashes:
        errors.append(f"task_source_provenance.segments.{segment}.selected_test_files_sha256")
    duplicate_across_segments = all_selected_tests.intersection(selected_tests)
    if duplicate_across_segments:
        errors.append(f"task_source_provenance.segments.{segment}.selected_tests")
    all_selected_tests.update(selected_tests)
    if selected_tests != tests_entry.get("selected"):
        errors.append(f"tests.{segment}.selected")
        errors.append(f"task_source_provenance.segments.{segment}.selected_tests")
    if tests_entry.get("expected_passed") != len(selected_tests):
        errors.append(f"tests.{segment}.expected_passed")
    check_observed(segment, tests_entry, len(selected_tests))

not_proof = payload.get("not_proof")
required_not_proof = {
    "native live autonomy",
    "broad unknown-repository repair",
    "external benchmark standing",
    "remote CI proof",
    "external review",
    "independent external held-out benchmark",
    "endorsement",
    "stars",
    "reposts",
}
if not isinstance(not_proof, list) or set(not_proof) != required_not_proof:
    errors.append("not_proof")

if errors:
    print("autonomous-learning-gate: invalid summary fields=" + ",".join(errors), file=sys.stderr)
    raise SystemExit(1)
PY
}

validate_failure_summary() {
  "$PYTHON_BIN" - "$SUMMARY_JSON" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
errors = []

if payload.get("schema_version") != "autonomous-learning-gate/v0.1":
    errors.append("schema_version")
if payload.get("status") != "failed":
    errors.append("status")
failure = payload.get("failure") or {}
segment = failure.get("segment")
if not segment:
    errors.append("failure.segment")
if not isinstance(failure.get("exit_code"), int) or failure["exit_code"] == 0:
    errors.append("failure.exit_code")
if segment and segment != "unknown":
    segments = payload.get("segments") or {}
    if segments.get(segment) != "failed":
        errors.append(f"segments.{segment}")
    elapsed = payload.get("segment_elapsed_seconds") or {}
    value = elapsed.get(segment)
    if not isinstance(value, int) or value < 0:
        errors.append(f"segment_elapsed_seconds.{segment}")
if errors:
    print("autonomous-learning-gate: invalid failure summary fields=" + ",".join(errors), file=sys.stderr)
    raise SystemExit(1)
PY
}

maybe_corrupt_summary_for_test() {
  corrupt_mode="${OPENMAKO_AUTONOMOUS_LEARNING_GATE_TEST_CORRUPT_SUMMARY:-}"
  if [ -z "$corrupt_mode" ]; then
    return
  fi
  echo "autonomous-learning-gate: corrupting summary for test=$corrupt_mode" >&2
  "$PYTHON_BIN" - "$SUMMARY_JSON" "$corrupt_mode" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
mode = sys.argv[2]
payload = json.loads(path.read_text(encoding="utf-8"))
if mode == "missing_contract_fields":
    payload.get("tests", {}).get("upstream_hidden_pack_reuse", {}).get("expected_contract", {}).pop("cheat_caught", None)
elif mode == "missing_observed_result":
    payload.get("tests", {}).get("stage1_trajectory_reuse_matrix", {}).pop("observed_pytest", None)
elif mode == "misstated_task_source_provenance":
    payload.get("task_source_provenance", {})["external_heldout"] = True
elif mode == "missing_task_source_manifest":
    payload.pop("task_source_manifest", None)
else:
    raise SystemExit(f"unsupported corrupt summary mode: {mode}")
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

run_pytest_segment() {
  segment="$1"
  expected_passed="$2"
  shift 2
  log_path="$PYTEST_LOG_DIR/${segment}.log"
  start_segment "$segment"
  set +e
  "$@" 2>&1 | tee "$log_path"
  rc="${PIPESTATUS[0]}"
  set -e
  record_segment_pytest_result "$segment" "$log_path" "$expected_passed" 0 "$rc"
  if [ "$rc" -ne 0 ]; then
    return "$rc"
  fi
  finish_segment "$segment" passed
}

on_error() {
  rc="$1"
  trap - ERR
  if [ -f "$SUMMARY_JSON" ]; then
    if [ -n "$CURRENT_SEGMENT" ]; then
      failed_segment="$CURRENT_SEGMENT"
      finish_segment "$failed_segment" failed || true
    else
      failed_segment="unknown"
    fi
    update_summary_status failed || true
    "$PYTHON_BIN" - "$SUMMARY_JSON" "$failed_segment" "$rc" <<'PY' || true
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
payload["failure"] = {
    "segment": sys.argv[2],
    "exit_code": int(sys.argv[3]),
}
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
    validate_failure_summary || true
    echo "autonomous-learning-gate: FAILED segment=$failed_segment summary=$SUMMARY_JSON" >&2
  fi
  exit "$rc"
}

trap 'on_error $?' ERR

eval "$(load_manifest_test_arrays)"
init_summary

echo "autonomous-learning-gate: running stage1 trajectory reuse matrix"
run_pytest_segment "stage1_trajectory_reuse_matrix" "${#STAGE1_TESTS[@]}" \
  "$PYTHON_BIN" -m pytest -p no:cacheprovider \
  "${STAGE1_TESTS[@]}" \
  -q

echo "autonomous-learning-gate: running upstream hidden-pack reuse stress test"
run_pytest_segment "upstream_hidden_pack_reuse" "${#UPSTREAM_TESTS[@]}" \
  "$PYTHON_BIN" -m pytest -p no:cacheprovider \
  "${UPSTREAM_TESTS[@]}" \
  -q

echo "autonomous-learning-gate: running cross-upstream no-seed reuse stress tests"
run_pytest_segment "cross_upstream_no_seed_reuse" "${#CROSS_UPSTREAM_TESTS[@]}" \
  "$PYTHON_BIN" -m pytest -p no:cacheprovider \
  "${CROSS_UPSTREAM_TESTS[@]}" \
  -q

collect_task_proofs
update_summary_status passed
maybe_corrupt_summary_for_test
if ! validate_summary; then
  CURRENT_SEGMENT="summary_validation"
  CURRENT_SEGMENT_STARTED_AT="$(date +%s)"
  on_error 1
fi

echo "autonomous-learning-gate: PASS"
echo "autonomous-learning-gate: summary=$SUMMARY_JSON"
echo "autonomous-learning-gate: task-source-provenance=repo-authored-regression-pack external-heldout=false"
echo "autonomous-learning-gate: not-proof=native live autonomy, broad unknown-repository repair, external benchmark standing, remote CI proof, external review, independent external held-out benchmark, endorsement, stars, reposts"
