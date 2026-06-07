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

echo "desktop-control-local-gate: running focused desktop intelligence tests"
"$PYTHON_BIN" -m pytest -p no:cacheprovider \
  tests/test_desktop_intelligence.py \
  tests/test_desktop_daemon_policy.py \
  -q

echo "desktop-control-local-gate: running L4 dry-run eval"
"$PYTHON_BIN" -m quantagent.cli --no-trust-prompt desktop-eval run --suite suite_l4 --json \
  > "$TMP_DIR/desktop_eval.json"

"$PYTHON_BIN" - "$TMP_DIR/desktop_eval.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
metrics = payload.get("metrics") or {}
scenarios = payload.get("scenarios") or []
level_reasons = metrics.get("level_reasons") or []
required_metrics = {
    "scenario_count",
    "success_count",
    "failure_count",
    "blocked_count",
    "stopped_count",
    "timeout_count",
    "crash_count",
    "side_effect_count",
    "manual_intervention_count",
    "recovery_attempt_count",
    "recovery_success_count",
    "autopsy_count",
    "missing_autopsy_count",
    "total_actions",
    "action_count",
    "misoperation_rate",
    "crash_rate",
}

checks = {
    "suite_is_l4": payload.get("suite") == "suite_l4",
    "status_is_dry_run": payload.get("status") == "dry_run",
    "scenario_count_is_8": metrics.get("total") == 8 and len(scenarios) == 8,
    "roadmap_metrics_are_present": required_metrics.issubset(metrics),
    "roadmap_scenario_count_matches": metrics.get("scenario_count") == 8,
    "roadmap_status_counts_are_zero": all(metrics.get(key) == 0 for key in ("success_count", "failure_count", "blocked_count", "stopped_count", "timeout_count")),
    "roadmap_safety_rates_are_explicit": metrics.get("misoperation_rate") == 0.0 and metrics.get("crash_rate") == 0.0,
    "roadmap_action_counts_are_zero": metrics.get("total_actions") == 0 and metrics.get("action_count") == 0,
    "roadmap_missing_autopsy_count_is_zero": metrics.get("missing_autopsy_count") == 0,
    "level_reasons_do_not_hide_missing_safety_rate": all("misoperation_rate" not in str(reason) for reason in level_reasons),
    "all_scenarios_are_suite_l4": all(item.get("suite") == "suite_l4" for item in scenarios),
    "all_scenarios_disable_execute": all((item.get("data") or {}).get("execute") is False for item in scenarios),
    "all_scenarios_are_dry_run": all(item.get("status") == "dry_run" for item in scenarios),
    "level_is_not_l4_claim": metrics.get("level") in {"L0", "L1", "L2", "L3"},
    "score_is_conservative": int(metrics.get("score") or 0) < 60,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    print("desktop-control-local-gate: failed checks: " + ", ".join(failed), file=sys.stderr)
    sys.exit(1)

print("desktop-control-local-gate: status=dry_run")
print(f"desktop-control-local-gate: scenarios={len(scenarios)}")
print(f"desktop-control-local-gate: level={metrics.get('level')}")
print(f"desktop-control-local-gate: misoperation_rate={metrics.get('misoperation_rate')}")
print(f"desktop-control-local-gate: crash_rate={metrics.get('crash_rate')}")
print("desktop-control-local-gate: not-proof=live desktop control, L4, L5, external endorsement, star or repost traction")
PY

echo "desktop-control-local-gate: PASS"
