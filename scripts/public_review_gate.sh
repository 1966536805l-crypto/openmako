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
expected_value = {"True": True, "False": False}.get(expected, expected)
payload = json.loads(path.read_text(encoding="utf-8"))
value = payload
for part in field_path.split("."):
    if not isinstance(value, dict) or part not in value:
        print(f"public-review-gate: missing JSON field {field_path} in {path}", file=sys.stderr)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), file=sys.stderr)
        raise SystemExit(1)
    value = value[part]

if value != expected_value:
    print(
        f"public-review-gate: expected {field_path}={expected_value!r}, got {value!r} in {path}",
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

echo "public-review-gate: running external-source benchmark gate"
OPENMAKO_EXTERNAL_SOURCE_BENCHMARK_SUMMARY_JSON="$TMP_DIR/external_source_benchmark_gate/last_summary.json" \
  bash scripts/external_source_benchmark_gate.sh

echo "public-review-gate: running external-heldout benchmark gate"
OPENMAKO_EXTERNAL_HELDOUT_BENCHMARK_SUMMARY_JSON="$TMP_DIR/external_heldout_benchmark_gate/last_summary.json" \
  bash scripts/external_heldout_benchmark_gate.sh

echo "public-review-gate: running public metadata boundary tests"
"$PYTHON_BIN" -m pytest -p no:cacheprovider \
  tests/test_public_metadata.py \
  -q

echo "public-review-gate: scoring CEABench v0.1 seed packet"
"$PYTHON_BIN" -m quantagent.cli --no-trust-prompt ceabench score --json \
  --expected-index-sha256 232245a8f7205c93f4a9d290e271cb10907166eb228346990a90a461e6b86512 \
  --expected-case-count 7 \
  --expected-case-id ceabench-v0.1-scope-violation-001 \
  --expected-case-id ceabench-v0.1-missing-test-proof-001 \
  --expected-case-id ceabench-v0.1-artifact-provenance-pass-001 \
  --expected-case-id ceabench-v0.1-swtbench-patch-shape-pass-001 \
  --expected-case-id ceabench-v0.1-verifier-tamper-risk-001 \
  --expected-case-id ceabench-v0.1-runtime-shadowing-risk-001 \
  --expected-case-id ceabench-v0.1-config-only-pass-001 \
  benchmarks/ceabench/v0.1/cases.json > "$TMP_DIR/ceabench_v01_score.json"

assert_json_field "$TMP_DIR/ceabench_v01_score.json" status passed
assert_json_field "$TMP_DIR/ceabench_v01_score.json" schema_version ceabench-score/v0.1

echo "public-review-gate: checking external-heldout gate fail-closed negatives"
"$PYTHON_BIN" -m pytest -p no:cacheprovider \
  tests/test_external_heldout_benchmark_gate.py \
  -q

echo "public-review-gate: checking native product-log ingestion"
"$PYTHON_BIN" -m pytest -p no:cacheprovider \
  tests/test_product_log_ingestion.py \
  -q

echo "public-review-gate: checking adversarial claim matrix generator"
"$PYTHON_BIN" scripts/generate_adversarial_claim_matrix.py --check

echo "public-review-gate: running Evidence Court intensity matrix"
"$PYTHON_BIN" -m pytest -p no:cacheprovider \
  tests/test_evidence_court_intensity_matrix.py \
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
assert_json_field "$TMP_DIR/swtbench_patch_artifact.json" verifier_tamper_risk.verifier_tamper_risk False
assert_json_field "$TMP_DIR/swtbench_patch_artifact.json" artifact_provenance.eval_rule_version swtbench-strip-model-patch/v2

echo "public-review-gate: auditing config-only repair fixture"
"$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court audit --ci --json \
  examples/evidence_court/config_only_repair.json > "$TMP_DIR/config_only_repair.json"

assert_json_field "$TMP_DIR/config_only_repair.json" verdict PASS
assert_json_field "$TMP_DIR/config_only_repair.json" status PASSED
assert_json_field "$TMP_DIR/config_only_repair.json" failure_class ""
assert_json_field "$TMP_DIR/config_only_repair.json" patch_shape.bucket config_only

echo "public-review-gate: auditing runtime shadowing fixture"
"$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court audit --ci --json \
  examples/evidence_court/runtime_shadowing_risk.json > "$TMP_DIR/runtime_shadowing_risk.json"

assert_json_field "$TMP_DIR/runtime_shadowing_risk.json" verdict SUSPICIOUS
assert_json_field "$TMP_DIR/runtime_shadowing_risk.json" failure_class verifier_tamper_risk
assert_json_field "$TMP_DIR/runtime_shadowing_risk.json" verifier_tamper_risk.verifier_tamper_risk True

echo "public-review-gate: auditing verifier tamper-risk fixture"
"$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court audit --ci --json \
  examples/evidence_court/verifier_tamper_risk.json > "$TMP_DIR/verifier_tamper_risk.json"

assert_json_field "$TMP_DIR/verifier_tamper_risk.json" verdict SUSPICIOUS
assert_json_field "$TMP_DIR/verifier_tamper_risk.json" failure_class verifier_tamper_risk
assert_json_field "$TMP_DIR/verifier_tamper_risk.json" verifier_tamper_risk.verifier_tamper_risk True

echo "public-review-gate: auditing verifier attack fixture"
"$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court audit --ci --json \
  examples/evidence_court/verifier_attack_success.json > "$TMP_DIR/verifier_attack_success.json"

assert_json_field "$TMP_DIR/verifier_attack_success.json" verdict SUSPICIOUS
assert_json_field "$TMP_DIR/verifier_attack_success.json" failure_class verifier_tamper_risk
assert_json_field "$TMP_DIR/verifier_attack_success.json" verifier_tamper_risk.verifier_tamper_risk True

echo "public-review-gate: auditing CI workflow tamper fixture"
"$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court audit --ci --json \
  examples/evidence_court/ci_workflow_tamper_success.json > "$TMP_DIR/ci_workflow_tamper_success.json"

assert_json_field "$TMP_DIR/ci_workflow_tamper_success.json" verdict SUSPICIOUS
assert_json_field "$TMP_DIR/ci_workflow_tamper_success.json" failure_class verifier_tamper_risk
assert_json_field "$TMP_DIR/ci_workflow_tamper_success.json" verifier_tamper_risk.verifier_tamper_risk True

echo "public-review-gate: running supplied transcript adapter matrix"
bash scripts/supplied_transcript_adapter_matrix.sh

echo "public-review-gate: PASS"
