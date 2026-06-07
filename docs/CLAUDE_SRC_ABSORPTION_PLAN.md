# OpenMako Clean-Room Absorption Plan

Internal planning note. This is not the current public v0.1 capability claim; the current public proof command is `./scripts/public_review_gate.sh`.

This note is a clean-room synthesis from local architecture inspection. It is
not a source port and must not be used to copy proprietary source bodies,
bundled prompts, product strings, minified internals, or private service
flows.

## Boundary

- Learn mechanisms, contracts, failure modes, and module boundaries only.
- Reimplement behavior in OpenMako's own Python style and test harness.
- Prefer local-first, auditable behavior over remote product control planes.
- Keep JSON/JSONL as export surfaces; make SQLite the runtime source of truth.

## Main Read

OpenMako already has unusually good starter bones: policy gates, approvals,
runtime SQLite, tool invocation envelopes, MCP leases, subagent records,
worktree isolation, deterministic compaction, UX status, and quant gates.

The gap is not one missing prompt. The gap is that many features are still
flat slices. The next jump is to turn them into a single product runtime with
strong lifecycle invariants:

- every query is a resumable state machine,
- every message and tool result has a ledger identity,
- every tool/MCP/plugin/skill action enters one permission queue,
- every long task has a parent-owned lifecycle,
- every TUI/status surface reads from the same state model.

## Track 1: Query Lifecycle And Context

Target modules:

- `quantagent/query_runtime.py`
- `quantagent/agent_loop_v3.py`
- `quantagent/tool_loop.py`
- `quantagent/model_client.py`
- `quantagent/runtime_store.py`
- `quantagent/sessions.py`
- `quantagent/resume.py`
- `quantagent/context_pack.py`
- `quantagent/compact_budget.py`
- `quantagent/trajectory_compact.py`
- `quantagent/tool_output.py`

Absorb these mechanisms:

- Promote `QueryRuntime` from an event emitter into a turn state machine with
  `QueryState`, `TransitionReason`, `TerminalReason`, `turn_count`,
  `generation`, and `recovery_count`.
- Add a message ledger with `message_id`, `parent_id`, `role`,
  `tool_call_id`, `compact_boundary`, and preserved segment metadata.
- Enforce token budget before model calls, after tool batches, and before
  continuation, not only when rendering context packs.
- Layer compaction: tool-result microcompact, deterministic trajectory
  compact, session snapshot compact, and post-compact context reinjection.
- Add recovery paths for context overflow, output limit, model fallback,
  missing tool result pairs, interrupted streams, and user abort.

P0 acceptance tests:

- Simulated context overflow triggers compact before the next model call.
- Interrupted tool use gets a paired synthetic tool result before resume.
- Failed model stream does not leak orphan assistant/tool state into resume.
- `runtime_store` records transition, recovery reason, usage, and terminal
  reason for each query.

## Track 2: Permission And Tool Execution

Target modules:

- `quantagent/tool_execution.py`
- `quantagent/policy_gate.py`
- `quantagent/permission_policy_v2.py`
- `quantagent/approvals.py`
- `quantagent/safety.py`
- `quantagent/checkpoints.py`
- `quantagent/tool_registry.py`
- `quantagent/tool_call_transcript.py`
- `quantagent/tool_transcript.py`

Absorb these mechanisms:

- Keep one execution envelope for every local tool, shell command, MCP tool,
  plugin tool, and skill-triggered action.
- Add a permission queue object that can represent pending, approved, denied,
  allow-once, allow-session, and allow-always decisions.
- Make policy decisions explainable by including classifier result, matched
  rule, risk level, scope, approval fingerprint, checkpoint id, and source.
- Make checkpoint and transcript writes part of the same tool lifecycle, so
  blocked, failed, truncated, and successful calls have one record shape.
- Normalize large outputs through `tool_output.py`: inline preview plus
  artifact path, never raw unbounded prompt injection.

P0 acceptance tests:

- A denied shell command, pending approval, and approved command all produce
  consistent `ToolExecutionResult` and SQLite invocation rows.
- Approval fingerprints reject changed args.
- MCP/plugin tools cannot bypass `permission_policy_v2`.
- Large tool output is summarized and persisted without losing replayability.

## Track 3: Tasks, Subagents, And Worktrees

Target modules:

- `quantagent/task_runtime.py`
- `quantagent/task_state.py`
- `quantagent/subagents.py`
- `quantagent/agent_supervisor.py`
- `quantagent/worktree_isolation.py`
- `quantagent/agent_profiles.py`
- `quantagent/review_arbitration.py`
- `quantagent/runtime_store.py`

Absorb these mechanisms:

- Treat subagents as parent-owned task objects, not just background process
  helpers. A task should have spec, status, lineage, context mode, permission
  profile, output paths, terminal summary, and review bundle.
- Make context fork vs isolated worktree an explicit contract. Isolated agents
  should return changed paths and a review artifact before merge.
- Add dependency-aware node status to the supervisor: queued, ready, running,
  blocked, passed, failed, aborted.
- Add cancellation cascade. Parent stop should stop child process groups unless
  a child is explicitly detached.
- Require two-stage parent review for worker edits: spec compliance first,
  quality/regression review second.

P1 acceptance tests:

- Parent cancellation stops running shell and local-agent children.
- Isolated subagent creates a review artifact with changed/new/deleted paths.
- Supervisor does not launch a dependent node until its dependency is terminal.
- Two-stage review rejects an edit that passes tests but violates the spec.

## Track 4: MCP, Plugins, And Skills

Target modules:

- `quantagent/mcp_runtime.py`
- `quantagent/mcp_daemon.py`
- `quantagent/mcp_gateway.py`
- `quantagent/plugin_runtime.py`
- `quantagent/skills.py`
- `quantagent/skill_pipeline.py`
- `quantagent/lifecycle_hooks.py`
- `quantagent/config.py`
- `quantagent/doctor.py`

Absorb these mechanisms:

- Split plugin state into three layers: declared intent, materialized cache,
  and active runtime components.
- Let plugins contribute MCP servers, skills, hooks, agents, and commands, but
  activate them through one governed registry.
- Promote MCP from `tools/list` and `tools/call` into a lifecycle manager with
  server state, config hash, reconnect generation, catalog invalidation, lease
  cleanup, and per-server diagnostics.
- Add catalog surfaces for MCP tools, resources, prompts, and MCP-provided
  skills as separate object types.
- Route plugin/MCP/skill actions through the same permission and approval
  system as local tools.

P0 acceptance tests:

- Disabled plugin components disappear from active tools, skills, and hooks.
- Manual MCP config can override plugin-provided MCP config deterministically.
- Stale MCP lease cleanup redacts env/header names and secrets.
- `list_changed` or config hash change invalidates the catalog cache.
- Broken manifests and failed MCP servers appear in doctor/status without
  crashing startup.

## Track 5: TUI, Status, And Reliability

Target modules:

- `quantagent/chat_ui.py`
- `quantagent/tui_status_model.py`
- `quantagent/ux_status.py`
- `quantagent/diagnostic_registry.py`
- `quantagent/startup_banner.py`
- `quantagent/config.py`
- `quantagent/sessions.py`
- `quantagent/resume.py`

Absorb these mechanisms:

- Treat the terminal as a product REPL with transcript, prompt, status/footer,
  modal/approval, and background task panes.
- Add an external app-state store or equivalent Python state model with
  selector-friendly views for UI, doctor, and headless SDK.
- Use query generation guards so old finally/cleanup paths cannot clear the
  state of a newer active query.
- Queue prompts while a query is active; drain only after the current guard is
  idle.
- Make shutdown idempotent with synchronous terminal cleanup, async cleanup,
  timeout fallback, and persisted partial state.
- Resume sessions with more than text: cwd, file-read cache, task state,
  tool context, approvals, cost, and compact boundary metadata.

P1 acceptance tests:

- Cancel before model response restores the prompt without duplicate history.
- Cancel after partial assistant output persists the partial message safely.
- Stale generation cleanup cannot clear a newer active query.
- Resume restores latest session plus pending approvals and running tasks.
- Status rendering stays bounded for long transcripts.

## P0 Build Order

1. `message_ledger.py` plus SQLite schema migration for query transitions,
   messages, tool pairs, compact boundaries, and token usage.
2. `query_runtime.py` state machine API, then wire `agent_loop_v3.py` and
   `tool_loop.py` through it.
3. Permission queue unification in `tool_execution.py`, `approvals.py`, and
   `permission_policy_v2.py`.
4. MCP/plugin active catalog: declared/materialized/active plugin state,
   plugin-contributed MCP and skills, and active catalog invalidation.
5. Runtime status model that reads from the ledger, not from ad hoc files.

## P1 Build Order

1. Subagent dependency graph and cancellation cascade.
2. Worktree review bundles and two-stage parent review.
3. MCP resources/prompts/skills catalog and reconnect backoff.
4. Config/settings layering with schema, atomic writes, backups, and doctor.
5. TUI query guard, prompt queue, partial-output preservation, and bounded
   transcript rendering.

## Do Not Absorb

- Vendor cloud bridge, remote-control flows, proprietary account logic, or
  commercial growth/telemetry systems.
- Brand-specific names, endpoints, prompts, product text, hidden flags, or
  experiment names.
- Marketplace trust assumptions that depend on a first-party service.
- Any source body that cannot be traced to an open-source license already
  accepted by this project.

## Definition Of Done

The absorption is successful when a user can inspect one query id and see the
whole lifecycle: prompt, context budget decision, model call, tool approvals,
tool invocations, compact/recovery decisions, subagent lineage, MCP/plugin
catalog state, cost, terminal reason, and resume boundary.

That is the product-level leap: OpenMako becomes a local agent runtime, not a
collection of clever commands.
