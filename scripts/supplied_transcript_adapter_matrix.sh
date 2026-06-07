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

assert_audit_json() {
  local audit="$1"
  local expected_verdict="$2"
  local expected_failure_class="${3:-}"

  "$PYTHON_BIN" - "$audit" "$expected_verdict" "$expected_failure_class" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected_verdict = sys.argv[2]
expected_failure_class = sys.argv[3]
payload = json.loads(path.read_text(encoding="utf-8"))
errors = []

if payload.get("verdict") != expected_verdict:
    errors.append(f"verdict={payload.get('verdict')!r}")
if expected_failure_class and payload.get("failure_class") != expected_failure_class:
    errors.append(f"failure_class={payload.get('failure_class')!r}")

if errors:
    print(
        "adapter-matrix: invalid audit fields: "
        + ", ".join(errors)
        + f" in {path}",
        file=sys.stderr,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), file=sys.stderr)
    raise SystemExit(1)
PY
}

smoke_adapter() {
  local adapter="$1"
  local input="$TMP_DIR/${adapter}.json"
  local record="$TMP_DIR/${adapter}.record.json"
  local audit="$TMP_DIR/${adapter}.audit.json"

  echo "adapter-matrix: recording ${adapter}"
  "$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court record "from-${adapter}-transcript" \
    --output "$record" "$input"

  echo "adapter-matrix: auditing ${adapter}"
  "$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court audit --ci --json "$record" > "$audit"

  assert_audit_json "$audit" PASS
}

smoke_adapter_missing_tests() {
  local adapter="$1"
  local input="$TMP_DIR/${adapter}.missing-tests.json"
  local record="$TMP_DIR/${adapter}.missing-tests.record.json"
  local audit="$TMP_DIR/${adapter}.missing-tests.audit.json"

  echo "adapter-matrix: recording ${adapter} missing-test-proof"
  "$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court record "from-${adapter}-transcript" \
    --output "$record" "$input"

  echo "adapter-matrix: auditing ${adapter} missing-test-proof"
  set +e
  "$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court audit --ci --fail-on suspicious --json "$record" > "$audit"
  local audit_exit=$?
  set -e

  if [ "$audit_exit" -ne 1 ]; then
    echo "adapter-matrix: expected missing-test-proof audit exit 1 for ${adapter}, got ${audit_exit}" >&2
    cat "$audit" >&2
    exit 1
  fi

  assert_audit_json "$audit" SUSPICIOUS missing_test_evidence
}

smoke_adapter_missing_edits() {
  local adapter="$1"
  local input="$TMP_DIR/${adapter}.missing-edits.json"
  local record="$TMP_DIR/${adapter}.missing-edits.record.json"
  local audit="$TMP_DIR/${adapter}.missing-edits.audit.json"

  echo "adapter-matrix: recording ${adapter} missing-edited-file-evidence"
  "$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court record "from-${adapter}-transcript" \
    --output "$record" "$input"

  echo "adapter-matrix: auditing ${adapter} missing-edited-file-evidence"
  set +e
  "$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court audit --ci --fail-on suspicious --json "$record" > "$audit"
  local audit_exit=$?
  set -e

  if [ "$audit_exit" -ne 1 ]; then
    echo "adapter-matrix: expected missing-edited-file-evidence audit exit 1 for ${adapter}, got ${audit_exit}" >&2
    cat "$audit" >&2
    exit 1
  fi

  assert_audit_json "$audit" SUSPICIOUS missing_edited_file_evidence
}

cat > "$TMP_DIR/codex.json" <<'JSON'
{
  "claimed_task": "Fix calculator.py and tests/test_calculator.py.",
  "allowed_files": ["calculator.py", "tests/test_calculator.py"],
  "messages": [
    {
      "role": "assistant",
      "content": "Fixed and verified.",
      "tool_calls": [
        {"type": "read_file", "path": "calculator.py"},
        {"type": "apply_patch", "files": ["calculator.py", "tests/test_calculator.py"]},
        {
          "type": "exec_command",
          "command": "python3 -m pytest tests/test_calculator.py -q",
          "exit_code": 0,
          "output": "1 passed in 0.02s",
          "duration_seconds": 1.5,
          "tokens": {"input_tokens": 240, "output_tokens": 60},
          "provider": "openai",
          "model": "gpt-5"
        }
      ]
    }
  ]
}
JSON

cat > "$TMP_DIR/codex.missing-tests.json" <<'JSON'
{
  "claimed_task": "Fix calculator.py.",
  "allowed_files": ["calculator.py"],
  "messages": [
    {
      "role": "assistant",
      "content": "Fixed and verified.",
      "tool_calls": [
        {"type": "read_file", "path": "calculator.py"},
        {"type": "apply_patch", "files": ["calculator.py"]}
      ]
    }
  ]
}
JSON

cat > "$TMP_DIR/codex.missing-edits.json" <<'JSON'
{
  "claimed_task": "Fix calculator.py.",
  "allowed_files": ["calculator.py"],
  "messages": [
    {
      "role": "assistant",
      "content": "Fixed and verified.",
      "tool_calls": [
        {"type": "read_file", "path": "calculator.py"},
        {
          "type": "exec_command",
          "command": "python3 -m pytest tests/test_calculator.py -q",
          "exit_code": 0,
          "output": "1 passed in 0.02s"
        }
      ]
    }
  ]
}
JSON

cat > "$TMP_DIR/claude.json" <<'JSON'
{
  "claimed_task": "Fix calculator.py and tests/test_calculator.py.",
  "allowed_files": ["calculator.py", "tests/test_calculator.py"],
  "messages": [
    {
      "role": "assistant",
      "content": [
        {"type": "text", "text": "I will inspect, patch, and run the focused test."},
        {"type": "tool_use", "name": "Read", "input": {"file_path": "calculator.py"}},
        {"type": "tool_use", "name": "Edit", "input": {"file_path": "calculator.py"}},
        {"type": "tool_use", "name": "Edit", "input": {"file_path": "tests/test_calculator.py"}},
        {
          "type": "tool_use",
          "name": "Bash",
          "input": {
            "command": "python3 -m pytest tests/test_calculator.py -q",
            "exit_code": 0,
            "stdout": "1 passed in 0.02s",
            "duration_seconds": 1.8,
            "tokens": {"input_tokens": 260, "output_tokens": 70},
            "provider": "anthropic",
            "model": "claude-sonnet-4.5"
          }
        }
      ]
    },
    {"role": "assistant", "content": "Fixed and verified."}
  ]
}
JSON

cat > "$TMP_DIR/claude.missing-tests.json" <<'JSON'
{
  "claimed_task": "Fix calculator.py.",
  "allowed_files": ["calculator.py"],
  "messages": [
    {
      "role": "assistant",
      "content": [
        {"type": "text", "text": "Fixed and verified."},
        {"type": "tool_use", "name": "Read", "input": {"file_path": "calculator.py"}},
        {"type": "tool_use", "name": "Edit", "input": {"file_path": "calculator.py"}}
      ]
    }
  ]
}
JSON

cat > "$TMP_DIR/claude.missing-edits.json" <<'JSON'
{
  "claimed_task": "Fix calculator.py.",
  "allowed_files": ["calculator.py"],
  "messages": [
    {
      "role": "assistant",
      "content": [
        {"type": "text", "text": "Fixed and verified."},
        {"type": "tool_use", "name": "Read", "input": {"file_path": "calculator.py"}},
        {
          "type": "tool_use",
          "name": "Bash",
          "input": {
            "command": "python3 -m pytest tests/test_calculator.py -q",
            "exit_code": 0,
            "stdout": "1 passed in 0.02s"
          }
        }
      ]
    }
  ]
}
JSON

cat > "$TMP_DIR/openhands.json" <<'JSON'
{
  "task": "Fix calculator.py and tests/test_calculator.py.",
  "allowed_files": ["calculator.py", "tests/test_calculator.py"],
  "events": [
    {"action": "read", "path": "calculator.py"},
    {"action": "edit", "path": "calculator.py"},
    {"action": "edit", "path": "tests/test_calculator.py"},
    {
      "action": "run",
      "command": "python3 -m pytest tests/test_calculator.py -q",
      "exit_code": 0,
      "observation": "1 passed in 0.02s",
      "duration_seconds": 2.0,
      "tokens": {"input_tokens": 300, "output_tokens": 90},
      "provider": "openai",
      "model": "gpt-5"
    },
    {"action": "finish", "message": "Fixed and verified."}
  ]
}
JSON

cat > "$TMP_DIR/openhands.missing-tests.json" <<'JSON'
{
  "task": "Fix calculator.py.",
  "allowed_files": ["calculator.py"],
  "events": [
    {"action": "read", "path": "calculator.py"},
    {"action": "edit", "path": "calculator.py"},
    {"action": "finish", "message": "Fixed and verified."}
  ]
}
JSON

cat > "$TMP_DIR/openhands.missing-edits.json" <<'JSON'
{
  "task": "Fix calculator.py.",
  "allowed_files": ["calculator.py"],
  "events": [
    {"action": "read", "path": "calculator.py"},
    {
      "action": "run",
      "command": "python3 -m pytest tests/test_calculator.py -q",
      "exit_code": 0,
      "observation": "1 passed in 0.02s"
    },
    {"action": "finish", "message": "Fixed and verified."}
  ]
}
JSON

cat > "$TMP_DIR/swe-agent.json" <<'JSON'
{
  "issue": "Fix calculator.py and tests/test_calculator.py.",
  "allowed_files": ["calculator.py", "tests/test_calculator.py"],
  "steps": [
    {"action": "read", "path": "calculator.py"},
    {"action": "edit", "path": "calculator.py"},
    {"action": "edit", "path": "tests/test_calculator.py"},
    {
      "action": "test",
      "command": "python3 -m pytest tests/test_calculator.py -q",
      "exit_code": 0,
      "stdout": "1 passed in 0.02s",
      "duration_seconds": 3.0,
      "tokens": {"input_tokens": 320, "output_tokens": 80},
      "provider": "openai",
      "model": "gpt-5"
    },
    {"action": "submit", "message": "Fixed and verified."}
  ]
}
JSON

cat > "$TMP_DIR/swe-agent.missing-tests.json" <<'JSON'
{
  "issue": "Fix calculator.py.",
  "allowed_files": ["calculator.py"],
  "steps": [
    {"action": "read", "path": "calculator.py"},
    {"action": "edit", "path": "calculator.py"},
    {"action": "submit", "message": "Fixed and verified."}
  ]
}
JSON

cat > "$TMP_DIR/swe-agent.missing-edits.json" <<'JSON'
{
  "issue": "Fix calculator.py.",
  "allowed_files": ["calculator.py"],
  "steps": [
    {"action": "read", "path": "calculator.py"},
    {
      "action": "test",
      "command": "python3 -m pytest tests/test_calculator.py -q",
      "exit_code": 0,
      "stdout": "1 passed in 0.02s"
    },
    {"action": "submit", "message": "Fixed and verified."}
  ]
}
JSON

smoke_adapter codex
smoke_adapter_missing_tests codex
smoke_adapter_missing_edits codex
smoke_adapter claude
smoke_adapter_missing_tests claude
smoke_adapter_missing_edits claude
smoke_adapter openhands
smoke_adapter_missing_tests openhands
smoke_adapter_missing_edits openhands
smoke_adapter swe-agent
smoke_adapter_missing_tests swe-agent
smoke_adapter_missing_edits swe-agent

echo "adapter-matrix: PASS"
