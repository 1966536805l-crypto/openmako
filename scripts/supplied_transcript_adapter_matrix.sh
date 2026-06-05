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

  if ! grep -q '"verdict": "PASS"' "$audit"; then
    echo "adapter-matrix: expected PASS verdict for ${adapter}" >&2
    cat "$audit" >&2
    exit 1
  fi
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

smoke_adapter codex
smoke_adapter claude
smoke_adapter openhands
smoke_adapter swe-agent

echo "adapter-matrix: PASS"
