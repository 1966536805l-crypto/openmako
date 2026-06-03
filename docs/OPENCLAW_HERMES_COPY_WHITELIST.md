# OpenClaw / Hermes Copy Whitelist

Internal clean-room planning note. This is not the current public v0.1 capability claim; the current public proof is the focused learning-effect gate linked from README.md and issue #1.

Date: 2026-05-26

Purpose: identify the smallest permissively licensed upstream pieces that can
be copied or ported into QuantAgent/OpenMako without replacing the local Python
architecture.

Verified upstream heads:

- `NousResearch/hermes-agent`: `2517917de34eeb6a40f5a17a2e59d9746803dfa5`
- `openclaw/openclaw`: `fe9f28f520e893185526ce10cf96e95373574aab`

Licensing rule:

- Both upstream repositories expose MIT license metadata in the inspected GitHub
  repositories.
- Direct copied code must keep the MIT license text and source attribution in
  `docs/UPSTREAM_ATTRIBUTION.md` plus `third_party/<project>/`.
- Do not copy whole subsystems when a Python-native port is smaller and easier
  to test.

## Current Local State

OpenMako already has a partial Hermes-style learning loop:

- `quantagent/trajectory.py`: deterministic JSONL events.
- `quantagent/agent_autopsy.py`: failure replay from `trajectory` and
  `query_events`.
- `quantagent/hermes_learning.py`: query-event to memory proposals.
- `quantagent/memory_sidecar.py`: human-approved memory proposal queue.
- `quantagent/memory_store.py`: local SQLite/FTS memory store.
- `quantagent/skill_pipeline.py`: trajectory/event to skill proposal with
  human approval.
- `quantagent/vendor/hermes/skills/**`: selected MIT Hermes skills.

This is not yet full "learns from use." The missing loop is:

`run -> trajectory/query_events/autopsy -> memory proposal -> skill proposal -> eval -> approval -> install -> future retrieval`.

## Direct Or Near-Direct Copy

These are small enough to copy with attribution or translate line-for-line into
Python-native shape.

| Priority | Upstream | Source path | Copy mode | Target | Why |
|---:|---|---|---|---|---|
| 1 | Hermes | `agent/trajectory.py` | direct/adapt | `quantagent/hermes_trajectory_format.py` | Add ShareGPT-compatible trajectory export with `completed` and failed-run separation. |
| 2 | Hermes | `batch_runner.py` tool-stat helpers | direct/adapt | `quantagent/tool_stats.py` | Normalize `tool_stats` and `tool_error_counts` with zero-filled tools for eval/autopsy. |
| 3 | Hermes | `agent/iteration_budget.py` | direct/adapt | `quantagent/iteration_budget.py` | Tiny deterministic iteration budget for daemon/decider loops. |
| 4 | OpenClaw | `src/agents/command-poll-backoff.ts` | already vendored/direct | `quantagent/openclaw_runtime_utils.py` | Stable command polling delay; already present in `third_party/openclaw/selected`. |
| 5 | OpenClaw | selected small runtime utilities | already vendored/direct | `quantagent/openclaw_runtime_utils.py` | Timeout parsing, backoff, JSON pointer, prompt sanitizing, secret masking. |

## Adapt, Do Not Whole-Copy

These files contain valuable mechanics but are coupled to upstream runtime,
providers, channel gateways, or TypeScript/Swift UI.

| Priority | Upstream | Source path | Copy mode | Target | Extract only |
|---:|---|---|---|---|---|
| 6 | Hermes | `agent/agent_runtime_helpers.py` | adapt | `quantagent/hermes_trajectory_format.py` | Message to ShareGPT role conversion, `<tool_call>`, `<tool_response>`, reasoning normalization. |
| 7 | Hermes | `trajectory_compressor.py` | adapt | `quantagent/trajectory_compact.py` | First/last preservation, middle compression metrics, deterministic truncation boundaries. |
| 8 | Hermes | `agent/memory_provider.py` | adapt | `quantagent/memory_provider.py` | Provider hooks: `prefetch`, turn sync, session end, pre-compress, delegation. |
| 9 | Hermes | `agent/memory_manager.py` | adapt | `quantagent/memory_runtime.py` | Multi-provider failure isolation and tool routing; do not copy external-provider coupling. |
| 10 | Hermes | `agent/skill_commands.py` | adapt | `quantagent/skills.py`, `quantagent/skill_pipeline.py` | Skill activation, disabled skills, support files, injection metadata. |
| 11 | Hermes | `agent/curator.py` | adapt/avoid direct | `quantagent/skill_curator.py` | Dry-run report, stale/archive/reactivate state machine only. |
| 12 | Hermes | `agent/insights.py` | adapt | `quantagent/learning_metrics.py` | Usage, tool, skill, and cost metrics for learning-score reporting. |
| 13 | OpenClaw | `packages/memory-host-sdk/src/host/memory-schema.ts` | adapt | `quantagent/memory_store.py` | Memory schema fields, not TS storage implementation. |
| 14 | OpenClaw | `packages/memory-host-sdk/src/host/query-expansion.ts` | adapt | `quantagent/memory_retrieval.py` | Query expansion/ranking ideas for future memory retrieval. |
| 15 | OpenClaw | `packages/memory-host-sdk/src/host/qmd-scope.ts` and `qmd-process.ts` | adapt | `quantagent/memory_retrieval.py` | Scoped memory query mechanics; rewrite in Python. |
| 16 | OpenClaw | `src/acp/event-ledger.ts` | adapt | `quantagent/event_log.py`, `quantagent/runtime_store.py` | Event ledger contract and ordering, not ACP-specific text. |
| 17 | OpenClaw | `src/acp/control-plane/session-actor-queue.ts` | adapt | `quantagent/desktop_daemon.py` | Per-session serialized action queue for daemon safety. |
| 18 | OpenClaw | `src/agents/command/session-store.ts` | adapt | `quantagent/runtime_store.py` | Session metadata and resume handles. |
| 19 | OpenClaw | `apps/macos/Sources/OpenClaw/ScreenSnapshotService.swift` | adapt | `quantagent/desktop_agent.py` | Permission diagnostics and screenshot failure classification only. |
| 20 | OpenClaw | `apps/macos/Sources/OpenClaw/ExecApprovalEvaluation.swift` and `ExecSystemRunCommandValidator.swift` | adapt | `quantagent/approvals.py`, `quantagent/safety.py` | Approval/command validation cases; no Swift UI copy. |
| 21 | OpenClaw | `src/process/supervisor/types.ts`, `registry.ts`, `supervisor.ts` | adapt | `quantagent/daemon_supervisor.py` | Run record state machine, scoped cancel, timeout, no-output timeout, orphan handling. |
| 22 | OpenClaw | `src/gateway/control-plane-rate-limit.ts` | direct/adapt | `quantagent/control_plane_policy.py` | Rate-limit control-plane writes so chat/daemon loops cannot self-amplify. |
| 23 | OpenClaw | `src/gateway/method-scopes.ts` | adapt | `quantagent/permission_policy_v2.py` | Read/write/admin/pairing method scopes for agent control-plane calls. |
| 24 | OpenClaw | `src/channels/allow-from.ts`, `command-gating.ts`, `mention-gating.ts`, `sender-identity.ts` | direct/adapt | `quantagent/operator_auth.py`, `quantagent/channel_gateway.py` | Remote operator allowlist, command gating, group-chat mention gating, sender identity validation. |
| 25 | OpenClaw | `src/agents/sandbox/sanitize-env-vars.ts` and `tool-policy.ts` | direct/adapt | `quantagent/sandbox_policy.py` | Filter secrets from daemon subprocess env and enforce source-priority allow/deny tool policy. |
| 26 | OpenClaw | `src/security/dangerous-tools.ts` | direct/adapt | `quantagent/permission_policy_v2.py`, `quantagent/safety.py` | Default-deny high-risk tool classes before model-driven actions. |
| 27 | OpenClaw | `src/daemon/service-types.ts`, `service.ts`, `inspect.ts` | adapt | `quantagent/night_daemon.py`, `quantagent/mcp_daemon.py` | Daemon status/recover model: stale pid, missing program, restart health. |

## Avoid

- Hermes `run_agent.py` as a whole: too coupled to provider, gateway, CLI, and
  runtime objects.
- Hermes `batch_runner.py` as a whole: useful internals, but the full runner is
  coupled to Hermes agent classes, Rich/Fire UX, and multiprocessing.
- Hermes `model_tools.py` as a whole: registry and stats ideas are useful; tool
  runtime does not match QuantAgent.
- Hermes `curator.py` as a whole: high-value but large and coupled to `AIAgent`;
  use clean-room state machine.
- OpenClaw `src/agents/**` as a whole: huge TypeScript agent runtime; port only
  queue/session/event contracts.
- OpenClaw `src/process/**` as a whole: process supervision is useful, but the
  full TS child/PTY implementation should be rewritten around Python
  `subprocess`, local stop files, and QuantAgent trajectory writes.
- OpenClaw `apps/**` UI code: Swift/Kotlin/React UI does not fit QuantAgent.
- Channel-specific OpenClaw platforms unless OpenMako becomes a multi-channel
  gateway.
- OpenClaw `src/daemon/launchd.ts`, `systemd.ts`, and `schtasks.ts` as a first
  import: useful later, but first implement a foreground/local daemon with
  deterministic tests.
- Any install scripts, secrets, OAuth flows, brand copy, marketplace policy, or
  telemetry.

## First Patch Batch

Only two files should be implemented first:

1. `quantagent/hermes_trajectory_format.py`
   - Export OpenMako trajectory/query runtime data to Hermes/ShareGPT-style
     JSONL.
   - Include `completed`, `timestamp`, `model`, `conversations`, and failure
     metadata.
   - Preserve reasoning/tool calls as structured text without inventing hidden
     reasoning.

2. `quantagent/tool_stats.py`
   - Normalize tool usage into stable `tool_stats` and `tool_error_counts`.
   - Zero-fill known tools so eval datasets have stable schema.
   - Feed `agent_autopsy`, runtime ledger, and future desktop eval reports.

Required tests:

- successful trajectory export has `completed=true`;
- failed trajectory export has `completed=false`;
- multi-tool assistant turns normalize to tool-call/tool-response records;
- tool stats zero-fill missing tools;
- unknown tools are retained but do not break schema;
- MIT attribution docs mention exact upstream paths.

## Second Patch Batch

After batch one passes:

1. `quantagent/learning_loop.py`
   - Drive `trajectory/query_events/autopsy -> memory proposal -> skill proposal`.
   - Never auto-install generated skills without approval.

2. `quantagent/learning_metrics.py`
   - Report proposal count, approval rate, skill hit rate, failure recurrence,
     stale skills, and eval pass rate.

3. `quantagent/skill_curator.py`
   - Dry-run first.
   - Archive stale generated skills only after approval.
   - Reactivate skills only when eval evidence supports them.

## Night Daemon Patch Batch

If the immediate target is overnight desktop autonomy, this batch has higher
priority than the learning-loop batch:

1. `quantagent/daemon_supervisor.py`
   - Port the OpenClaw process supervisor contract into Python-native
     `RunRecord`, `RunStatus`, scoped cancel, timeout, no-output timeout, and
     orphan detection.

2. `quantagent/control_plane_policy.py`
   - Rate-limit repeated chat/control-plane writes.
   - Default-deny unknown control methods.

3. `quantagent/operator_auth.py`
   - Sender identity normalization.
   - Allowlist and command-gating checks.

4. `quantagent/sandbox_policy.py`
   - Secret env filtering.
   - Tool allow/deny precedence.

Required tests:

- spawned run reaches terminal status;
- cancel by scope stops only matching runs;
- no-output timeout marks run failed;
- stale pid is detected on status;
- repeated control-plane writes are blocked inside the time window;
- unauthorized sender cannot start daemon;
- secret env vars are not passed into child process.

## Definition Of Done

The "learns from use" claim is only valid when all are true:

- Every material run writes trajectory and query events.
- Failed runs produce an autopsy or explicit missing-evidence report.
- Learnable facts become memory proposals, not silent memory writes.
- Repeated failure patterns become skill proposals.
- Skill proposals run at least one narrow eval before approval.
- Installed learned skills are retrievable in future context.
- Bad learned skills can be disabled or archived with traceable evidence.
