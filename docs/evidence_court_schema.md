# Evidence Court JSON Record

`openmako evidence-court audit <run.json>` audits a supplied record.
It does not claim to read native Claude Code, Codex, Cursor, or SWE-bench logs.

## Minimal Record

Machine-readable schema: [`evidence_court_record.schema.json`](evidence_court_record.schema.json).
The schema documents the supplied record shape; the CLI still audits only the evidence contained in the record.

```json
{
  "claimed_task": "Fix calculator.py only. Do not edit tests.",
  "allowed_files": ["calculator.py"],
  "files_read": ["calculator.py"],
  "files_edited": ["calculator.py", "tests/test_calculator.py"],
  "commands_run": [
    {"command": "python3 -m pytest tests/test_calculator.py -q", "exit_code": 0}
  ],
  "test_output": "1 passed in 0.02s",
  "run_metrics": {
    "duration_seconds": 1.4,
    "command_count": 1,
    "input_tokens": 1200,
    "output_tokens": 320,
    "estimated_cost_usd": 0.004,
    "missing_telemetry": ["actual_cost_usd"]
  },
  "final_claim": "Fixed and verified."
}
```

## Fields

| Field | Type | Meaning |
| --- | --- | --- |
| `claimed_task` | string | Task or claim being audited. |
| `allowed_files` | string array | Optional edit allowlist. If present, any other edited file is a scope violation. |
| `files_read` | string array | Files the agent inspected. |
| `files_edited` | string array | Files the agent modified. |
| `commands_run` | string array or command objects | Commands the record says were run. Command objects may include `command` and `exit_code`. |
| `test_output` | string or object | Validation evidence. Objects may include `status`, `output`, `summary`, or `exit_code`. |
| `run_metrics` | object | Optional telemetry supplied by the record: duration, command count, token counts, cost, provider/model, and `missing_telemetry`. It is preserved in JSON output but is not treated as validation proof. |
| `final_claim` | string | Agent's final success or completion claim. |

## Verdict Boundary

- `FAIL`: out-of-scope edit or failed validation evidence.
- `SUSPICIOUS`: success claim with missing or ambiguous test evidence.
- `PASS`: supplied record has no detected scope violation and recognizable passing validation evidence.

## Machine Output

Use `--json` for CI or scripts.
Use `--ci` to return exit code 1 for `FAIL`.
Use `--fail-on suspicious` to also block `SUSPICIOUS`.
Use `validate` to check that a supplied record is accepted by the current parser before auditing it.

```bash
openmako evidence-court validate examples/evidence_court/out_of_scope.json
openmako evidence-court validate --json examples/evidence_court/out_of_scope.json
openmako evidence-court audit --json examples/evidence_court/out_of_scope.json
openmako evidence-court audit --ci examples/evidence_court/out_of_scope.json
openmako evidence-court audit --ci --fail-on suspicious examples/evidence_court/missing_tests.json
```

The JSON envelope includes:

- `schema_version`: currently `evidence-court/v0.1`
- `verdict`
- `status`
- `failure_class`
- `failed_at`
- `finding_types`
- `run_metrics`
- `report`

`--ci` returns `0` for `PASS` and `SUSPICIOUS`, and `1` for `FAIL`.
Use `SUSPICIOUS` as a review queue unless your workflow chooses to block on it.
With `--fail-on suspicious`, both `FAIL` and `SUSPICIOUS` return `1`.

## Simple JSONL Record Builder

`record from-jsonl` converts a simple JSONL event stream into an audit record.
It is not a native transcript adapter.

```bash
openmako evidence-court record from-jsonl examples/evidence_court/simple_events.jsonl
openmako evidence-court record from-jsonl --output run.json examples/evidence_court/simple_events.jsonl
openmako evidence-court audit --ci --json run.json
```

Supported event kinds are `task`, `read`, `edit`, `command`, and `final_claim`.
`command` events may include `run_metrics` or direct telemetry fields such as
`duration_seconds`, `input_tokens`, `output_tokens`, `total_tokens`,
`estimated_cost_usd`, `provider`, `model`, and `missing_telemetry`.

This is an evidence audit of the supplied record only. It does not prove that a
command actually ran outside the record.

## Supplied Codex-Style Transcript Builder

`record from-codex-transcript` converts a small Codex-style JSON transcript into
the same audit record shape. This is a repository-defined supplied transcript
format, not native Codex product log ingestion and not live Codex control.

```bash
openmako evidence-court record from-codex-transcript transcript.json
openmako evidence-court record from-codex-transcript --output run.json transcript.json
openmako evidence-court audit --ci --json run.json
```

The transcript must be a JSON object with `messages`. Supported tool calls are
read, edit/apply-patch, and shell command calls. Unsupported tool calls are
listed under `adapter_report.unsupported`, and missing command or test evidence
is still judged by the normal Evidence Court audit.

## Supplied Claude-Style Transcript Builder

`record from-claude-transcript` converts a small Claude-style JSON transcript
into the same audit record shape. This is a repository-defined supplied
transcript format, not native Claude or Claude Code export parsing and not live
Claude control.

```bash
openmako evidence-court record from-claude-transcript transcript.json
openmako evidence-court record from-claude-transcript --output run.json transcript.json
openmako evidence-court audit --ci --json run.json
```

The transcript must be a JSON object with `messages`. Supported Claude-style
content blocks are text and `tool_use` blocks for read, edit/apply-patch, and
shell command calls. Unsupported tool calls are listed under
`adapter_report.unsupported`, and missing command or test evidence is still
judged by the normal Evidence Court audit.

## Supplied OpenHands-Style Transcript Builder

`record from-openhands-transcript` converts a small OpenHands-style JSON
transcript into the same audit record shape. This is a repository-defined
supplied transcript format, not native OpenHands export parsing and not live
OpenHands control.

```bash
openmako evidence-court record from-openhands-transcript transcript.json
openmako evidence-court record from-openhands-transcript --output run.json transcript.json
openmako evidence-court audit --ci --json run.json
```

The transcript must be a JSON object with `events`. Supported event actions are
task/instruction, read, edit/apply-patch, shell command, and final/finish
messages. Unsupported events are listed under `adapter_report.unsupported`.

## Supplied SWE-Agent-Style Transcript Builder

`record from-swe-agent-transcript` converts a small SWE-agent-style JSON
transcript into the same audit record shape. This is a repository-defined
supplied transcript format, not native SWE-agent export parsing and not live
SWE-agent control.

```bash
openmako evidence-court record from-swe-agent-transcript transcript.json
openmako evidence-court record from-swe-agent-transcript --output run.json transcript.json
openmako evidence-court audit --ci --json run.json
```

The transcript must be a JSON object with `steps`. Supported step actions are
task/instruction/issue, read, edit/apply-patch, shell command/test, and
final/submit messages. Unsupported steps are listed under
`adapter_report.unsupported`.
