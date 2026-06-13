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
CURRENT_SEGMENT=""
CURRENT_SEGMENT_STARTED_AT=0

init_summary() {
  mkdir -p "$SUMMARY_DIR"
  mkdir -p "$PYTEST_LOG_DIR"
  summary_args=("$SUMMARY_JSON" "$GIT_COMMIT" "$PYTEST_LOG_DIR")
  if [ "${#ORIGINAL_ARGS[@]}" -gt 0 ]; then
    summary_args+=("${ORIGINAL_ARGS[@]}")
  fi
  "$PYTHON_BIN" - "${summary_args[@]}" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "schema_version": "autonomous-learning-gate/v0.1",
    "status": "running",
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "invocation": {
        "git_commit": sys.argv[2],
        "argv": sys.argv[4:],
    },
    "artifacts": {
        "pytest_log_dir": sys.argv[3],
    },
    "segments": {
        "stage1_trajectory_reuse_matrix": "pending",
        "upstream_hidden_pack_reuse": "pending",
        "cross_upstream_no_seed_reuse": "pending",
    },
    "segment_elapsed_seconds": {},
    "tests": {
        "stage1_trajectory_reuse_matrix": {
            "selected": [
                "tests/test_learning_effect_e2e.py::LearningEffectE2ETest::test_real_hidden_stage1_agent_runs_extract_then_reuse_on_clean_stage2",
                "tests/test_learning_effect_e2e.py::LearningEffectE2ETest::test_no_seed_multi_file_stage1_extracts_then_reuses_on_clean_stage2",
                "tests/test_learning_effect_e2e.py::LearningEffectE2ETest::test_no_seed_package_module_file_bundle_extracts_then_reuses_on_clean_stage2",
            ],
            "expected_passed": 3,
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
            "selected": [
                "tests/test_upstream_function_file_bundle_regression.py::UpstreamFunctionFileBundleRegressionTest::test_fixed_version_combined_upstream_hidden_pack_reuses_without_cheating",
            ],
            "expected_passed": 1,
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
            "selected": [
                "tests/test_upstream_function_file_bundle_regression.py::UpstreamFunctionFileBundleRegressionTest::test_vendored_pandera_scale_no_seed_stage1_extracts_function_repair_without_non_target_drift",
                "tests/test_upstream_function_file_bundle_regression.py::UpstreamFunctionFileBundleRegressionTest::test_vendored_pandera_bool_predicate_no_seed_stage1_reuses_with_stability",
                "tests/test_upstream_function_file_bundle_regression.py::UpstreamFunctionFileBundleRegressionTest::test_vendored_great_expectations_result_format_no_seed_stage1_extracts_function_repair",
                "tests/test_upstream_function_file_bundle_regression.py::UpstreamFunctionFileBundleRegressionTest::test_vendored_aider_random_color_no_seed_stage1_reuses_on_opaque_stage2",
            ],
            "expected_passed": 4,
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
        "endorsement",
        "stars",
        "reposts",
    ],
}
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
import json
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

expected_stage1_selected = [
    "tests/test_learning_effect_e2e.py::LearningEffectE2ETest::test_real_hidden_stage1_agent_runs_extract_then_reuse_on_clean_stage2",
    "tests/test_learning_effect_e2e.py::LearningEffectE2ETest::test_no_seed_multi_file_stage1_extracts_then_reuses_on_clean_stage2",
    "tests/test_learning_effect_e2e.py::LearningEffectE2ETest::test_no_seed_package_module_file_bundle_extracts_then_reuses_on_clean_stage2",
]
expected_upstream_selected = [
    "tests/test_upstream_function_file_bundle_regression.py::UpstreamFunctionFileBundleRegressionTest::test_fixed_version_combined_upstream_hidden_pack_reuses_without_cheating",
]
expected_cross_upstream_selected = [
    "tests/test_upstream_function_file_bundle_regression.py::UpstreamFunctionFileBundleRegressionTest::test_vendored_pandera_scale_no_seed_stage1_extracts_function_repair_without_non_target_drift",
    "tests/test_upstream_function_file_bundle_regression.py::UpstreamFunctionFileBundleRegressionTest::test_vendored_pandera_bool_predicate_no_seed_stage1_reuses_with_stability",
    "tests/test_upstream_function_file_bundle_regression.py::UpstreamFunctionFileBundleRegressionTest::test_vendored_great_expectations_result_format_no_seed_stage1_extracts_function_repair",
    "tests/test_upstream_function_file_bundle_regression.py::UpstreamFunctionFileBundleRegressionTest::test_vendored_aider_random_color_no_seed_stage1_reuses_on_opaque_stage2",
]
if stage1.get("selected") != expected_stage1_selected:
    errors.append("tests.stage1_trajectory_reuse_matrix.selected")
if stage1.get("expected_passed") != 3:
    errors.append("tests.stage1_trajectory_reuse_matrix.expected_passed")
if upstream.get("selected") != expected_upstream_selected:
    errors.append("tests.upstream_hidden_pack_reuse.selected")
if upstream.get("expected_passed") != 1:
    errors.append("tests.upstream_hidden_pack_reuse.expected_passed")
if cross_upstream.get("selected") != expected_cross_upstream_selected:
    errors.append("tests.cross_upstream_no_seed_reuse.selected")
if cross_upstream.get("expected_passed") != 4:
    errors.append("tests.cross_upstream_no_seed_reuse.expected_passed")


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


check_observed("stage1_trajectory_reuse_matrix", stage1, 3)
check_observed("upstream_hidden_pack_reuse", upstream, 1)
check_observed("cross_upstream_no_seed_reuse", cross_upstream, 4)

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

not_proof = payload.get("not_proof")
required_not_proof = {
    "native live autonomy",
    "broad unknown-repository repair",
    "external benchmark standing",
    "remote CI proof",
    "external review",
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

init_summary

echo "autonomous-learning-gate: running stage1 trajectory reuse matrix"
run_pytest_segment "stage1_trajectory_reuse_matrix" 3 \
  "$PYTHON_BIN" -m pytest -p no:cacheprovider \
  tests/test_learning_effect_e2e.py::LearningEffectE2ETest::test_real_hidden_stage1_agent_runs_extract_then_reuse_on_clean_stage2 \
  tests/test_learning_effect_e2e.py::LearningEffectE2ETest::test_no_seed_multi_file_stage1_extracts_then_reuses_on_clean_stage2 \
  tests/test_learning_effect_e2e.py::LearningEffectE2ETest::test_no_seed_package_module_file_bundle_extracts_then_reuses_on_clean_stage2 \
  -q

echo "autonomous-learning-gate: running upstream hidden-pack reuse stress test"
run_pytest_segment "upstream_hidden_pack_reuse" 1 \
  "$PYTHON_BIN" -m pytest -p no:cacheprovider \
  tests/test_upstream_function_file_bundle_regression.py::UpstreamFunctionFileBundleRegressionTest::test_fixed_version_combined_upstream_hidden_pack_reuses_without_cheating \
  -q

echo "autonomous-learning-gate: running cross-upstream no-seed reuse stress tests"
run_pytest_segment "cross_upstream_no_seed_reuse" 4 \
  "$PYTHON_BIN" -m pytest -p no:cacheprovider \
  tests/test_upstream_function_file_bundle_regression.py::UpstreamFunctionFileBundleRegressionTest::test_vendored_pandera_scale_no_seed_stage1_extracts_function_repair_without_non_target_drift \
  tests/test_upstream_function_file_bundle_regression.py::UpstreamFunctionFileBundleRegressionTest::test_vendored_pandera_bool_predicate_no_seed_stage1_reuses_with_stability \
  tests/test_upstream_function_file_bundle_regression.py::UpstreamFunctionFileBundleRegressionTest::test_vendored_great_expectations_result_format_no_seed_stage1_extracts_function_repair \
  tests/test_upstream_function_file_bundle_regression.py::UpstreamFunctionFileBundleRegressionTest::test_vendored_aider_random_color_no_seed_stage1_reuses_on_opaque_stage2 \
  -q

update_summary_status passed
maybe_corrupt_summary_for_test
if ! validate_summary; then
  CURRENT_SEGMENT="summary_validation"
  CURRENT_SEGMENT_STARTED_AT="$(date +%s)"
  on_error 1
fi

echo "autonomous-learning-gate: PASS"
echo "autonomous-learning-gate: summary=$SUMMARY_JSON"
echo "autonomous-learning-gate: not-proof=native live autonomy, broad unknown-repository repair, external benchmark standing, remote CI proof, external review, endorsement, stars, reposts"
