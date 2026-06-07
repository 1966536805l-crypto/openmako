# OpenClaw / Hermes Full Port Plan

Internal clean-room planning note. This is not the current public v0.1 capability claim; the current public proof command is `./scripts/public_review_gate.sh`.

This is the clean-room port map for borrowing the useful runtime mechanics from
OpenClaw and Hermes without copying private Claude Code code or bundled upstream
implementation text.

## Rule

- Copy contracts, state shapes, lifecycle mechanics, and product lessons.
- Rewrite implementation in QuantAgent/Mako style.
- Keep attribution when a meaningful MIT-licensed pattern is ported.
- Do not ingest `/Downloads/claude/src.zip` or any suspected private/leaked
  Claude Code source.

## Phase 1: Runtime Ledger

Goal: make SQLite the operator-facing source of truth, with JSON/JSONL as export
or compatibility artifacts.

Ported shape:

- sessions with parent linkage, model fields, counters, handoff fields
- messages with FTS search
- task_runs with owner, scope, child session, parent flow, delivery state
- approval_requests with stable fingerprints and decisions
- tool_invocations with policy, approval, checkpoint, summary, preview
- query_events for agent lifecycle traces

Mako landing points:

- `quantagent/runtime_store.py`
- `quantagent/runtime_ledger.py`
- `mako runtime status/export/search`

## Phase 2: Subagent Lifecycle

Goal: turn subagents into traceable child sessions, not just background tasks.

Port shape:

- parent task id
- child session key
- context mode: fork or isolated
- owner/profile/permission/tool/MCP/skill snapshot
- progress summary and terminal outcome
- review bundle after terminal state

Mako landing points:

- `quantagent/subagents.py`
- `quantagent/task_runtime.py`
- `quantagent/runtime_store.py`
- `mako subagent start/list/show/bundle`

## Phase 3: Hook Spine

Goal: all agent/tool/session transitions pass through one prioritized hook
runner.

Port shape:

- void hooks
- modifying hooks
- claiming/blocking hooks
- fail-open/fail-closed
- timeout
- lifecycle events before/after model, prompt, tool, compaction, session,
  subagent, task, install

Mako landing points:

- `quantagent/hook_runner.py`
- `quantagent/lifecycle_hooks.py`
- `quantagent/tool_execution.py`
- `quantagent/query_runtime.py`

## Phase 4: MCP Runtime

Goal: make MCP a real session-scoped tool source.

Port shape:

- config parser
- stdio/http/sse transport records
- catalog cache
- session lease
- idle cleanup
- env whitelist
- argument guards
- redacted errors
- permission pattern per server/tool

Mako landing points:

- `quantagent/mcp_runtime.py`
- `quantagent/mcp_gateway.py`
- `mako mcp list/tools/call/status/cleanup`

## Phase 5: Plugin Registry

Goal: generated plugin state, not ad hoc plugin behavior.

Port shape:

- manifest hash
- package hash
- origin
- enabled flag
- startup roles
- compatibility tags
- policy hash
- diagnostics

Mako landing points:

- `quantagent/plugin_runtime.py`
- `mako plugins --refresh --json`

## Phase 6: Skill Snapshots

Goal: every material run records exactly which skills were injected.

Port shape:

- snapshot id
- session/run id
- prompt fragment
- selected skill metadata
- filters
- env requirements
- version/timestamp

Mako landing points:

- `quantagent/skills.py`
- `quantagent/runtime_store.py`
- `quantagent/agent_v2.py`
- `quantagent/agent_loop_v3.py`

## Phase 7: Doctor And Security

Goal: make local readiness and danger obvious before the agent acts.

Port shape:

- config permission checks
- world/group writable checks
- broken symlink checks
- stale WAL/process checks
- auth conflict checks
- completion/source checks
- plugin registry diagnostics
- quant raw-data and broker credential checks

Mako landing points:

- `quantagent/doctor.py`
- `quantagent/source_checks.py`
- `quantagent/safety.py`

## Phase 8: Quant Runtime Specialization

Goal: use the runtime spine for the quant hell path.

Port shape:

- data adapter as MCP/plugin tool
- broker adapter as gated tool
- execution gate evidence as first-class runtime artifacts
- post-experiment hooks for auditor and evidence ledger
- subagent roles: researcher, auditor, data_engineer, execution_checker

Mako landing points:

- `quantagent/quant_data_adapter.py`
- `quantagent/quant_execution_gate.py`
- `quantagent/quant_run_gate.py`
- `quantagent/evidence_ledger.py`
- `quantagent/orchestrator.py`
