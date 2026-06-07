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

checks = {
    "suite_is_l4": payload.get("suite") == "suite_l4",
    "status_is_dry_run": payload.get("status") == "dry_run",
    "scenario_count_is_8": metrics.get("total") == 8 and len(scenarios) == 8,
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
print("desktop-control-local-gate: not-proof=live desktop control, L4, L5, external endorsement, star or repost traction")
PY

echo "desktop-control-local-gate: PASS"
