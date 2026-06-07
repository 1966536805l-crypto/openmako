#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON:-python3}"
export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"

RUN_FULL_PYTEST=1
RUN_EXTERNAL_REGRESSION=1
RUN_PUBLIC_GATE=1
RUN_DESKTOP_GATE=1
BENCH_REPEATS=1
BENCH_LIMIT=""
SUMMARY_JSON="${OPENMAKO_DESPAIR_GATE_SUMMARY_JSON:-.quantagent/despair_gate/last_summary.json}"
SUMMARY_DIR="$(dirname -- "$SUMMARY_JSON")"
TMP_DIR="$(mktemp -d)"
CURRENT_SEGMENT=""

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

update_summary() {
  "$PYTHON_BIN" - "$SUMMARY_JSON" "$1" "$2" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
segment = sys.argv[2]
status = sys.argv[3]
if segment:
    payload["segments"][segment] = status
else:
    payload["status"] = status
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

on_error() {
  rc="$1"
  trap - ERR
  if [ -f "$SUMMARY_JSON" ]; then
    if [ -n "$CURRENT_SEGMENT" ]; then
      update_summary "$CURRENT_SEGMENT" failed || true
    fi
    update_summary "" failed || true
    echo "despair-gate: FAILED segment=${CURRENT_SEGMENT:-unknown} summary=$SUMMARY_JSON" >&2
  fi
  exit "$rc"
}

maybe_inject_test_failure() {
  if [ "${OPENMAKO_DESPAIR_GATE_TEST_FAIL_SEGMENT:-}" = "$1" ]; then
    echo "despair-gate: injecting test failure for segment=$1" >&2
    return 1
  fi
  return 0
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --skip-full-pytest)
      RUN_FULL_PYTEST=0
      ;;
    --skip-external-regression)
      RUN_EXTERNAL_REGRESSION=0
      ;;
    --skip-public-gate)
      RUN_PUBLIC_GATE=0
      ;;
    --skip-desktop-gate)
      RUN_DESKTOP_GATE=0
      ;;
    --bench-repeats)
      shift
      if [ "$#" -eq 0 ]; then
        echo "despair-gate: --bench-repeats requires a value" >&2
        exit 2
      fi
      BENCH_REPEATS="$1"
      ;;
    --bench-limit)
      shift
      if [ "$#" -eq 0 ]; then
        echo "despair-gate: --bench-limit requires a value" >&2
        exit 2
      fi
      BENCH_LIMIT="$1"
      ;;
    -h|--help)
      cat <<'EOF'
Usage: bash scripts/despair_gate.sh [options]

Runs the local high-intensity verification loop:
  1. built-in CodingBench pack against the real OpenMako CLI agent
  2. external multimodule hidden regression
  3. full repository pytest
  4. public review gate
  5. desktop control local gate

Options:
  --skip-full-pytest    Skip the slow full-repository pytest pass.
  --skip-external-regression
                         Skip the external multimodule hidden regression file.
  --skip-public-gate    Skip scripts/public_review_gate.sh.
  --skip-desktop-gate   Skip scripts/desktop_control_local_gate.sh.
  --bench-repeats N     Repeat the CodingBench task pack N times.
  --bench-limit N       Limit CodingBench tasks for script smoke testing.

This is local regression evidence only. It is not external review,
benchmark ranking, live desktop-control proof, stars, reposts, or endorsement.
EOF
      exit 0
      ;;
    *)
      echo "despair-gate: unknown option: $1" >&2
      exit 2
      ;;
  esac
  shift
done

if ! [[ "$BENCH_REPEATS" =~ ^[0-9]+$ ]] || [ "$BENCH_REPEATS" -lt 1 ]; then
  echo "despair-gate: --bench-repeats must be a positive integer" >&2
  exit 2
fi

if [ -n "$BENCH_LIMIT" ]; then
  if ! [[ "$BENCH_LIMIT" =~ ^[0-9]+$ ]] || [ "$BENCH_LIMIT" -lt 1 ]; then
    echo "despair-gate: --bench-limit must be a positive integer" >&2
    exit 2
  fi
fi

AGENT_COMMAND="{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} --json --max-steps 12 --learning-context off {instruction}"
BENCH_JSON="$TMP_DIR/coding_bench.json"
mkdir -p "$SUMMARY_DIR"

echo "despair-gate: running built-in CodingBench pack with real OpenMako CLI agent"
if [ -n "$BENCH_LIMIT" ]; then
  "$PYTHON_BIN" -m quantagent.cli --no-trust-prompt coding-bench \
    --limit "$BENCH_LIMIT" \
    run \
    --agent-command "$AGENT_COMMAND" \
    --repeats "$BENCH_REPEATS" \
    --json > "$BENCH_JSON"
else
  "$PYTHON_BIN" -m quantagent.cli --no-trust-prompt coding-bench \
    run \
    --agent-command "$AGENT_COMMAND" \
    --repeats "$BENCH_REPEATS" \
    --json > "$BENCH_JSON"
fi

"$PYTHON_BIN" - "$BENCH_JSON" "$SUMMARY_JSON" "$RUN_EXTERNAL_REGRESSION" "$RUN_FULL_PYTEST" "$RUN_PUBLIC_GATE" "$RUN_DESKTOP_GATE" "$BENCH_REPEATS" "${BENCH_LIMIT:-}" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
summary_path = Path(sys.argv[2])
summary = payload.get("summary") or {}
artifact_dir = payload.get("artifact_dir") or ""
if "runs" in payload:
    summary = payload.get("summary") or {}
    artifact_dir = payload.get("artifact_dir") or ""
    solved = summary.get("solved")
    total = summary.get("total_task_attempts")
    success_rate = summary.get("overall_success_rate")
else:
    solved = summary.get("solved")
    total = summary.get("total")
    success_rate = summary.get("success_rate")
print(f"despair-gate: coding-bench solved={solved}/{total} success_rate={success_rate}")
print(f"despair-gate: coding-bench artifact_dir={artifact_dir}")
gate_summary = {
    "schema_version": "despair-gate/v0.1",
    "status": "running",
    "coding_bench": {
        "artifact_dir": artifact_dir,
        "solved": solved,
        "total": total,
        "success_rate": success_rate,
        "repeats": int(sys.argv[7]),
        "limit": int(sys.argv[8]) if sys.argv[8] else None,
    },
    "segments": {
        "external_regression": "pending" if sys.argv[3] == "1" else "skipped",
        "full_pytest": "pending" if sys.argv[4] == "1" else "skipped",
        "public_gate": "pending" if sys.argv[5] == "1" else "skipped",
        "desktop_gate": "pending" if sys.argv[6] == "1" else "skipped",
    },
    "not_proof": [
        "external review",
        "benchmark ranking",
        "live desktop control",
        "L4",
        "L5",
        "stars",
        "reposts",
        "endorsement",
    ],
}
summary_path.write_text(json.dumps(gate_summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

trap 'on_error "$?"' ERR

if [ "$RUN_EXTERNAL_REGRESSION" -eq 1 ]; then
  CURRENT_SEGMENT="external_regression"
  maybe_inject_test_failure "$CURRENT_SEGMENT"
  echo "despair-gate: running external multimodule hidden regression"
  "$PYTHON_BIN" -m pytest -p no:cacheprovider \
    tests/test_external_benchmark_multimodule_regression.py \
    -q
  update_summary "$CURRENT_SEGMENT" passed
  CURRENT_SEGMENT=""
else
  echo "despair-gate: skipping external multimodule hidden regression"
fi

if [ "$RUN_FULL_PYTEST" -eq 1 ]; then
  CURRENT_SEGMENT="full_pytest"
  maybe_inject_test_failure "$CURRENT_SEGMENT"
  echo "despair-gate: running full repository pytest"
  "$PYTHON_BIN" -m pytest -p no:cacheprovider -q
  update_summary "$CURRENT_SEGMENT" passed
  CURRENT_SEGMENT=""
else
  echo "despair-gate: skipping full repository pytest"
fi

if [ "$RUN_PUBLIC_GATE" -eq 1 ]; then
  CURRENT_SEGMENT="public_gate"
  maybe_inject_test_failure "$CURRENT_SEGMENT"
  echo "despair-gate: running public review gate"
  bash scripts/public_review_gate.sh
  update_summary "$CURRENT_SEGMENT" passed
  CURRENT_SEGMENT=""
else
  echo "despair-gate: skipping public review gate"
fi

if [ "$RUN_DESKTOP_GATE" -eq 1 ]; then
  CURRENT_SEGMENT="desktop_gate"
  maybe_inject_test_failure "$CURRENT_SEGMENT"
  echo "despair-gate: running desktop control local gate"
  bash scripts/desktop_control_local_gate.sh
  update_summary "$CURRENT_SEGMENT" passed
  CURRENT_SEGMENT=""
else
  echo "despair-gate: skipping desktop control local gate"
fi

update_summary "" passed

echo "despair-gate: PASS"
echo "despair-gate: summary=$SUMMARY_JSON"
echo "despair-gate: not-proof=external review, benchmark ranking, live desktop control, L4, L5, stars, reposts, endorsement"
