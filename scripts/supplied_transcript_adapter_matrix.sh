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

smoke_adapter_missing_diff() {
  local adapter="$1"
  local input="$TMP_DIR/${adapter}.missing-diff.json"
  local record="$TMP_DIR/${adapter}.missing-diff.record.json"
  local audit="$TMP_DIR/${adapter}.missing-diff.audit.json"

  echo "adapter-matrix: recording ${adapter} missing-diff-content-evidence"
  "$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court record "from-${adapter}-transcript" \
    --output "$record" "$input"

  echo "adapter-matrix: auditing ${adapter} missing-diff-content-evidence"
  set +e
  "$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court audit --ci --fail-on suspicious --json "$record" > "$audit"
  local audit_exit=$?
  set -e

  if [ "$audit_exit" -ne 1 ]; then
    echo "adapter-matrix: expected missing-diff-content-evidence audit exit 1 for ${adapter}, got ${audit_exit}" >&2
    cat "$audit" >&2
    exit 1
  fi

  assert_audit_json "$audit" SUSPICIOUS missing_diff_content_evidence
}

smoke_adapter_test_only_source_diff() {
  local adapter="$1"
  local source="$TMP_DIR/${adapter}.json"
  local input="$TMP_DIR/${adapter}.test-only-source-diff.json"
  local record="$TMP_DIR/${adapter}.test-only-source-diff.record.json"
  local audit="$TMP_DIR/${adapter}.test-only-source-diff.audit.json"

  "$PYTHON_BIN" - "$source" "$input" <<'PY'
import json
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
payload = json.loads(source.read_text(encoding="utf-8"))
test_hunk = (
    "--- a/tests/test_calculator.py\n"
    "+++ b/tests/test_calculator.py\n"
    "@@ -1,2 +1,2 @@\n"
    "-assert add(1, 2) == 0\n"
    "+assert add(1, 2) == 3"
)

def replace_diff_content(value):
    if isinstance(value, dict):
        for key, item in list(value.items()):
            if key in {"diff", "patch", "unified_diff"}:
                value[key] = test_hunk
            elif key == "diff_hunks":
                value[key] = [test_hunk]
            else:
                replace_diff_content(item)
    elif isinstance(value, list):
        for item in value:
            replace_diff_content(item)

replace_diff_content(payload)
target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY

  echo "adapter-matrix: recording ${adapter} test-only-source-diff-evidence"
  "$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court record "from-${adapter}-transcript" \
    --output "$record" "$input"

  echo "adapter-matrix: auditing ${adapter} test-only-source-diff-evidence"
  set +e
  "$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court audit --ci --fail-on suspicious --json "$record" > "$audit"
  local audit_exit=$?
  set -e

  if [ "$audit_exit" -ne 1 ]; then
    echo "adapter-matrix: expected test-only-source-diff-evidence audit exit 1 for ${adapter}, got ${audit_exit}" >&2
    cat "$audit" >&2
    exit 1
  fi

  assert_audit_json "$audit" SUSPICIOUS missing_diff_content_evidence
}

smoke_adapter_partial_source_diff() {
  local adapter="$1"
  local source="$TMP_DIR/${adapter}.json"
  local input="$TMP_DIR/${adapter}.partial-source-diff.json"
  local record="$TMP_DIR/${adapter}.partial-source-diff.record.json"
  local audit="$TMP_DIR/${adapter}.partial-source-diff.audit.json"

  "$PYTHON_BIN" - "$source" "$input" <<'PY'
import json
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
payload = json.loads(source.read_text(encoding="utf-8"))

def add_allowed_source(value):
    if isinstance(value, dict):
        allowed = value.get("allowed_files")
        if isinstance(allowed, list) and "src/api.py" not in allowed:
            allowed.append("src/api.py")
        for item in value.values():
            add_allowed_source(item)
    elif isinstance(value, list):
        for item in value:
            add_allowed_source(item)

def has_diff_content(value):
    return any(key in value for key in ("diff", "patch", "unified_diff", "diff_hunks"))

def add_source_file(value):
    if isinstance(value, dict):
        if has_diff_content(value):
            files = value.get("files")
            if isinstance(files, list):
                if "src/api.py" not in files:
                    files.append("src/api.py")
            else:
                value["files"] = ["calculator.py", "src/api.py"]
        for item in value.values():
            add_source_file(item)
    elif isinstance(value, list):
        for item in value:
            add_source_file(item)

add_allowed_source(payload)
add_source_file(payload)
target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY

  echo "adapter-matrix: recording ${adapter} partial-source-diff-evidence"
  "$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court record "from-${adapter}-transcript" \
    --output "$record" "$input"

  echo "adapter-matrix: auditing ${adapter} partial-source-diff-evidence"
  set +e
  "$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court audit --ci --fail-on suspicious --json "$record" > "$audit"
  local audit_exit=$?
  set -e

  if [ "$audit_exit" -ne 1 ]; then
    echo "adapter-matrix: expected partial-source-diff-evidence audit exit 1 for ${adapter}, got ${audit_exit}" >&2
    cat "$audit" >&2
    exit 1
  fi

  assert_audit_json "$audit" SUSPICIOUS missing_diff_content_evidence
}

smoke_adapter_stale_validation_after_source_edit() {
  local adapter="$1"
  local source="$TMP_DIR/${adapter}.json"
  local input="$TMP_DIR/${adapter}.stale-validation-after-source-edit.json"
  local record="$TMP_DIR/${adapter}.stale-validation-after-source-edit.record.json"
  local audit="$TMP_DIR/${adapter}.stale-validation-after-source-edit.audit.json"

  "$PYTHON_BIN" - "$source" "$input" <<'PY'
import json
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
payload = json.loads(source.read_text(encoding="utf-8"))
late_hunk = (
    "--- a/calculator.py\n"
    "+++ b/calculator.py\n"
    "@@ -4,2 +4,2 @@\n"
    "-def sub(a, b): return a - b\n"
    "+def sub(a, b): return b - a"
)

def late_edit_for(template):
    if isinstance(template.get("input"), dict):
        return {
            "type": template.get("type", "tool_use"),
            "name": template.get("name", "Edit"),
            "input": {"file_path": "calculator.py", "diff": late_hunk},
        }
    event = {"diff_hunks": [late_hunk], "files": ["calculator.py"]}
    if "action" in template:
        event["action"] = template["action"]
    elif "type" in template:
        event["type"] = template["type"]
    else:
        event["type"] = "apply_patch"
    return event

def command_text(value):
    if not isinstance(value, dict):
        return ""
    direct = value.get("command") or value.get("cmd")
    if direct:
        return str(direct)
    nested = value.get("input")
    if isinstance(nested, dict):
        return str(nested.get("command") or nested.get("cmd") or "")
    return ""

def has_diff_content(value):
    if not isinstance(value, dict):
        return False
    if any(key in value for key in ("diff", "patch", "unified_diff", "diff_hunks")):
        return True
    nested = value.get("input")
    return isinstance(nested, dict) and any(key in nested for key in ("diff", "patch", "unified_diff", "diff_hunks"))

def insert_late_edit(value):
    if isinstance(value, dict):
        for key in ("tool_calls", "content", "events", "steps"):
            items = value.get(key)
            if not isinstance(items, list):
                continue
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                command = command_text(item).lower()
                if "pytest" in command:
                    edit_template = next((candidate for candidate in items if has_diff_content(candidate)), {})
                    items.insert(index + 1, late_edit_for(edit_template))
                    return True
        for item in value.values():
            if insert_late_edit(item):
                return True
    elif isinstance(value, list):
        for item in value:
            if insert_late_edit(item):
                return True
    return False

if not insert_late_edit(payload):
    raise SystemExit("could not insert stale-validation late edit")

target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY

  echo "adapter-matrix: recording ${adapter} stale-validation-after-source-edit"
  "$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court record "from-${adapter}-transcript" \
    --output "$record" "$input"

  echo "adapter-matrix: auditing ${adapter} stale-validation-after-source-edit"
  set +e
  "$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court audit --ci --fail-on suspicious --json "$record" > "$audit"
  local audit_exit=$?
  set -e

  if [ "$audit_exit" -ne 1 ]; then
    echo "adapter-matrix: expected stale-validation-after-source-edit audit exit 1 for ${adapter}, got ${audit_exit}" >&2
    cat "$audit" >&2
    exit 1
  fi

  assert_audit_json "$audit" SUSPICIOUS stale_validation_after_source_edit
}

smoke_adapter_missing_exit_status() {
  local adapter="$1"
  local source="$TMP_DIR/${adapter}.json"
  local input="$TMP_DIR/${adapter}.missing-exit-status.json"
  local record="$TMP_DIR/${adapter}.missing-exit-status.record.json"
  local stderr="$TMP_DIR/${adapter}.missing-exit-status.stderr"

  "$PYTHON_BIN" - "$source" "$input" <<'PY'
import json
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
payload = json.loads(source.read_text(encoding="utf-8"))

def strip_exit_codes(value):
    if isinstance(value, dict):
        value.pop("exit_code", None)
        for item in value.values():
            strip_exit_codes(item)
    elif isinstance(value, list):
        for item in value:
            strip_exit_codes(item)

strip_exit_codes(payload)
target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY

  echo "adapter-matrix: recording ${adapter} missing-exit-status-evidence"
  set +e
  "$PYTHON_BIN" -m quantagent.cli --no-trust-prompt evidence-court record "from-${adapter}-transcript" \
    --output "$record" "$input" 2> "$stderr"
  local record_exit=$?
  set -e

  if [ "$record_exit" -ne 2 ]; then
    echo "adapter-matrix: expected missing-exit-status record exit 2 for ${adapter}, got ${record_exit}" >&2
    cat "$record" >&2 || true
    cat "$stderr" >&2
    exit 1
  fi
  if ! grep -q "exit_code is required for validation commands" "$stderr"; then
    echo "adapter-matrix: missing exit-status diagnostic for ${adapter}" >&2
    cat "$stderr" >&2
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
        {
          "type": "apply_patch",
          "files": ["calculator.py", "tests/test_calculator.py"],
          "diff": "--- a/calculator.py\n+++ b/calculator.py\n@@ -1,2 +1,2 @@\n-def add(a, b): return a - b\n+def add(a, b): return a + b"
        },
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

cat > "$TMP_DIR/codex.missing-diff.json" <<'JSON'
{
  "claimed_task": "Fix calculator.py.",
  "allowed_files": ["calculator.py"],
  "messages": [
    {
      "role": "assistant",
      "content": "Fixed and verified.",
      "tool_calls": [
        {"type": "read_file", "path": "calculator.py"},
        {"type": "apply_patch", "files": ["calculator.py"]},
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
        {
          "type": "tool_use",
          "name": "Edit",
          "input": {
            "file_path": "calculator.py",
            "diff": "--- a/calculator.py\n+++ b/calculator.py\n@@ -1,2 +1,2 @@\n-def add(a, b): return a - b\n+def add(a, b): return a + b"
          }
        },
        {
          "type": "tool_use",
          "name": "Edit",
          "input": {
            "file_path": "tests/test_calculator.py",
            "diff": "--- a/tests/test_calculator.py\n+++ b/tests/test_calculator.py\n@@ -1,2 +1,2 @@\n-assert add(1, 2) == 0\n+assert add(1, 2) == 3"
          }
        },
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

cat > "$TMP_DIR/claude.missing-diff.json" <<'JSON'
{
  "claimed_task": "Fix calculator.py.",
  "allowed_files": ["calculator.py"],
  "messages": [
    {
      "role": "assistant",
      "content": [
        {"type": "text", "text": "Fixed and verified."},
        {"type": "tool_use", "name": "Read", "input": {"file_path": "calculator.py"}},
        {"type": "tool_use", "name": "Edit", "input": {"file_path": "calculator.py"}},
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
    {
      "action": "edit",
      "path": "calculator.py",
      "diff": "--- a/calculator.py\n+++ b/calculator.py\n@@ -1,2 +1,2 @@\n-def add(a, b): return a - b\n+def add(a, b): return a + b"
    },
    {
      "action": "edit",
      "path": "tests/test_calculator.py",
      "diff": "--- a/tests/test_calculator.py\n+++ b/tests/test_calculator.py\n@@ -1,2 +1,2 @@\n-assert add(1, 2) == 0\n+assert add(1, 2) == 3"
    },
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

cat > "$TMP_DIR/openhands.missing-diff.json" <<'JSON'
{
  "task": "Fix calculator.py.",
  "allowed_files": ["calculator.py"],
  "events": [
    {"action": "read", "path": "calculator.py"},
    {"action": "edit", "path": "calculator.py"},
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
    {
      "action": "edit",
      "path": "calculator.py",
      "diff": "--- a/calculator.py\n+++ b/calculator.py\n@@ -1,2 +1,2 @@\n-def add(a, b): return a - b\n+def add(a, b): return a + b"
    },
    {
      "action": "edit",
      "path": "tests/test_calculator.py",
      "diff": "--- a/tests/test_calculator.py\n+++ b/tests/test_calculator.py\n@@ -1,2 +1,2 @@\n-assert add(1, 2) == 0\n+assert add(1, 2) == 3"
    },
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

cat > "$TMP_DIR/swe-agent.missing-diff.json" <<'JSON'
{
  "issue": "Fix calculator.py.",
  "allowed_files": ["calculator.py"],
  "steps": [
    {"action": "read", "path": "calculator.py"},
    {"action": "edit", "path": "calculator.py"},
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
smoke_adapter_missing_exit_status codex
smoke_adapter_missing_diff codex
smoke_adapter_test_only_source_diff codex
smoke_adapter_partial_source_diff codex
smoke_adapter_stale_validation_after_source_edit codex
smoke_adapter_missing_tests codex
smoke_adapter_missing_edits codex
smoke_adapter claude
smoke_adapter_missing_exit_status claude
smoke_adapter_missing_diff claude
smoke_adapter_test_only_source_diff claude
smoke_adapter_partial_source_diff claude
smoke_adapter_stale_validation_after_source_edit claude
smoke_adapter_missing_tests claude
smoke_adapter_missing_edits claude
smoke_adapter openhands
smoke_adapter_missing_exit_status openhands
smoke_adapter_missing_diff openhands
smoke_adapter_test_only_source_diff openhands
smoke_adapter_partial_source_diff openhands
smoke_adapter_stale_validation_after_source_edit openhands
smoke_adapter_missing_tests openhands
smoke_adapter_missing_edits openhands
smoke_adapter swe-agent
smoke_adapter_missing_exit_status swe-agent
smoke_adapter_missing_diff swe-agent
smoke_adapter_test_only_source_diff swe-agent
smoke_adapter_partial_source_diff swe-agent
smoke_adapter_stale_validation_after_source_edit swe-agent
smoke_adapter_missing_tests swe-agent
smoke_adapter_missing_edits swe-agent

echo "adapter-matrix: PASS"
