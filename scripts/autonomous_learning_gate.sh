#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON:-python3}"
export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"

echo "autonomous-learning-gate: running stage1 trajectory reuse matrix"
"$PYTHON_BIN" -m pytest -p no:cacheprovider \
  tests/test_learning_effect_e2e.py::LearningEffectE2ETest::test_real_hidden_stage1_agent_runs_extract_then_reuse_on_clean_stage2 \
  tests/test_learning_effect_e2e.py::LearningEffectE2ETest::test_no_seed_multi_file_stage1_extracts_then_reuses_on_clean_stage2 \
  tests/test_learning_effect_e2e.py::LearningEffectE2ETest::test_no_seed_package_module_file_bundle_extracts_then_reuses_on_clean_stage2 \
  -q

echo "autonomous-learning-gate: running upstream hidden-pack reuse stress test"
"$PYTHON_BIN" -m pytest -p no:cacheprovider \
  tests/test_upstream_function_file_bundle_regression.py::UpstreamFunctionFileBundleRegressionTest::test_fixed_version_combined_upstream_hidden_pack_reuses_without_cheating \
  -q

echo "autonomous-learning-gate: PASS"
