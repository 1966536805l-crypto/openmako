#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON:-python3}"
export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

assert_json_field() {
  local audit="$1"
  local field_path="$2"
  local expected="$3"

  "$PYTHON_BIN" - "$audit" "$field_path" "$expected" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
field_path = sys.argv[2]
expected = sys.argv[3]
payload = json.loads(path.read_text(encoding="utf-8"))
value = payload
for part in field_path.split("."):
    if not isinstance(value, dict) or part not in value:
        print(f"public-review-gate: missing JSON field {field_path} in {path}", file=sys.stderr)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), file=sys.stderr)
        raise SystemExit(1)
    value = value[part]

if value != expected:
    print(
        f"public-review-gate: expected {field_path}={expected!r}, got {value!r} in {path}",
        file=sys.stderr,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), file=sys.stderr)
    raise SystemExit(1)
PY
}

echo "public-review-gate: running planner focused public test"
"$PYTHON_BIN" -m pytest -p no:cacheprovider \
  tests/test_agent_planner_contract.py::AgentPlannerContractTest::test_planner_no_seed_repairs_package_level_http_manifest_js_module \
  -q

echo "public-review-gate: running learning-effect focused public test"
"$PYTHON_BIN" -m pytest -p no:cacheprovider \
  tests/test_external_benchmark_multimodule_regression.py::ExternalBenchmarkMultimoduleRegressionTest::test_package_level_http_manifest_js_trajectory_skill_reuses_on_hidden_tasks \
  -q

echo "public-review-gate: running public metadata boundary tests"
"$PYTHON_BIN" -m pytest -p no:cacheprovider \
  tests/test_public_metadata.py \
  -q

echo "public-review-gate: recording Evidence Court bad-run fixture"
# Public equivalent: ./bin/openmako --no-trust-prompt evidence-court record from-jsonl
"$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court record from-jsonl \
  --output "$TMP_DIR/run.json" examples/evidence_court/simple_events.jsonl

echo "public-review-gate: auditing supplied Evidence Court record"
set +e
# Public equivalent: ./bin/openmako --no-trust-prompt evidence-court audit --ci --json
"$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court audit --ci --json "$TMP_DIR/run.json" \
  > "$TMP_DIR/audit.json"
audit_exit=$?
set -e

if [ "$audit_exit" -ne 1 ]; then
  echo "public-review-gate: expected Evidence Court audit exit 1, got $audit_exit" >&2
  exit 1
fi

assert_json_field "$TMP_DIR/audit.json" failure_class scope_violation
assert_json_field "$TMP_DIR/audit.json" failed_at scope_check

echo "public-review-gate: auditing artifact provenance fixture"
"$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court audit --ci --json \
  examples/evidence_court/artifact_provenance.json > "$TMP_DIR/artifact_provenance.json"

assert_json_field "$TMP_DIR/artifact_provenance.json" artifact_provenance.eval_rule_version swtbench-strip-model-patch/v2

echo "public-review-gate: auditing SWTBench patch artifact fixture"
"$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court audit --ci --json \
  examples/evidence_court/swtbench_patch_artifact.json > "$TMP_DIR/swtbench_patch_artifact.json"

assert_json_field "$TMP_DIR/swtbench_patch_artifact.json" patch_shape.bucket mixed_test_source
assert_json_field "$TMP_DIR/swtbench_patch_artifact.json" artifact_provenance.eval_rule_version swtbench-strip-model-patch/v2

echo "public-review-gate: running supplied transcript adapter matrix"
bash scripts/supplied_transcript_adapter_matrix.sh

echo "public-review-gate: PASS"
