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
./bin/openmako --no-trust-prompt evidence-court record from-jsonl \
  --output "$TMP_DIR/run.json" examples/evidence_court/simple_events.jsonl

echo "public-review-gate: auditing supplied Evidence Court record"
set +e
./bin/openmako --no-trust-prompt evidence-court audit --ci --json "$TMP_DIR/run.json" \
  > "$TMP_DIR/audit.json"
audit_exit=$?
set -e

if [ "$audit_exit" -ne 1 ]; then
  echo "public-review-gate: expected Evidence Court audit exit 1, got $audit_exit" >&2
  exit 1
fi

if ! grep -q '"failure_class": "scope_violation"' "$TMP_DIR/audit.json"; then
  echo "public-review-gate: expected scope_violation in Evidence Court audit JSON" >&2
  exit 1
fi

if ! grep -q '"failed_at": "scope_check"' "$TMP_DIR/audit.json"; then
  echo "public-review-gate: expected scope_check failure boundary" >&2
  exit 1
fi

echo "public-review-gate: PASS"
