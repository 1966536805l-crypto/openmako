# Claude Code Clean-Room Lessons

This note summarizes architecture lessons inferred from the safe metadata-only
analysis pack at:

`/Users/euhualihuawaiigeeeeegehanggeyewo/Documents/Codex/2026-05-22/7-30-8-9-9-30/claude_code_safe_analysis_pack`

Boundaries:

- Do not copy Claude Code source bodies, bundled prompts, source maps, or
  minified package internals.
- Use file trees, symbol names, package metadata, public docs, and QuantAgent
  code only.
- Treat all findings as clean-room architecture inspiration.

## Main Finding

Claude Code appears to be strong because it is a runtime, not because of a
single prompt. The metadata points to four heavy subsystems:

1. Tool execution and permission handling.
2. Query orchestration with lifecycle hooks and token budgets.
3. Task runtime for local agent, shell, remote, and teammate tasks.
4. Context, memory, session, and compaction infrastructure.

QuantAgent already has the right starter bones, but many pieces are still
flat functions rather than shared runtime layers.

## Priority Lessons

### 1. Unified Tool Execution

Current QuantAgent has `policy_gate.py`, `sandbox_policy.py`, `safety.py`,
`tool_registry.py`, `tool_loop.py`, and direct command execution from
`agent_v2.py`. These should converge behind one dispatcher.

Add:

- `quantagent/tool_execution.py`
- `quantagent/read_only_validation.py`
- `quantagent/path_policy.py`
- `quantagent/tool_result_handling.py`

Implemented in the first clean-room slice:

- `quantagent/tool_execution.py` now provides one execution envelope for
  `tool_loop` tools and `agent_v2` command steps.
- `quantagent/path_policy.py` now classifies project-contained reads/writes,
  symlink escapes, raw/tick paths, and QuantAgent output directories.
- Policy metadata, blocked state, duration, and error kind are attached to
  observations without changing the public result schema.

Target behavior:

- Every tool call goes through one execution envelope.
- Policy metadata is attached to every result.
- Permission blocks, timeouts, stderr, persisted output paths, and truncation
  state are normalized.
- Read-only validation is testable independently from shell execution.
- File write APIs enforce raw/tick path policy, not just project containment.

Useful tests:

- `tests/test_tool_execution_policy.py`
- `tests/test_read_only_validation.py`
- `tests/test_path_policy.py`
- `tests/test_tool_result_handling.py`

### 1.5 Workspace Trust Gate

Implemented in the workspace-trust slice:

- `quantagent/workspace_trust.py` adds a startup trust prompt before an
  interactive CLI command accesses a project workspace.
- Trusted workspace decisions are persisted outside the project by path, with
  `QUANTAGENT_TRUST_STORE` available for tests and isolated runs.
- `qagent --trust-workspace ...` explicitly trusts the workspace, while
  `qagent --no-trust-prompt ...` skips the prompt for automation.
- Non-interactive runs do not block waiting for input.

This borrows the architecture shape of a workspace permission boundary, not
any product prompt text or source implementation.

### 1.6 Startup Banner And Environment Warnings

Implemented in the startup-banner slice:

- `quantagent/startup_banner.py` renders a post-trust startup banner with
  QuantAgent version, current model, provider URL/source, and workspace path.
- Startup warnings flag QuantAgent/OpenAI API-key conflicts, Anthropic
  token/API-key conflicts, and `.zshrc` source lines pointing to missing files.
- Interactive chat now supports `/model` to inspect or switch the current
  model without restarting.

This is a clean-room product-shape lesson from startup diagnostics and auth
surface design; it does not copy proprietary banner text or implementation.

### 2. Query Runtime And Typed Hooks

Current QuantAgent has `hooks.py`, `tool_loop.py`, `agent_loop.py`, `chat_ui.py`,
and `agent_v2.py`, but no central query runtime.

Add:

- `quantagent/query_runtime.py`
- `quantagent/hook_events.py`

Lifecycle events to model:

- `query_start`
- `user_prompt_submit`
- `pre_model`
- `post_model`
- `pre_tool`
- `post_tool`
- `post_tool_batch`
- `stop`
- `stop_failure`
- `file_changed`
- `pre_compact`
- `post_compact`
- `session_end`

Target behavior:

- The existing communication-directory hook becomes one built-in
  `file_changed` hook.
- Normal completion emits `stop`; failed/blocked completion emits
  `stop_failure`.
- Token budget is enforced at query continuation points, not only displayed.
- Tool results from one model step are handled as a post-tool batch before
  being appended back into context.

Useful tests:

- Hook ordering and blocking.
- File-changed dedupe.
- Stop/failure event payloads.
- Post-tool batch budget enforcement.
- Pre/post compact event metrics.

### 3. Task Runtime

Current QuantAgent has task state, but execution is mostly synchronous. The
metadata points to separate local agent, local shell, remote agent, teammate,
stop, kill, and task output components.

Add a package:

```text
quantagent/task_runtime/
  types.py
  store.py
  events.py
  output.py
  cancellation.py
  shell_task.py
  local_agent.py
  remote_task.py
  scheduler.py
```

Implemented in the first task-runtime slice:

- `quantagent/task_runtime.py` starts guarded background shell tasks through a
  small worker process, persists stdout/stderr/status files, refreshes status,
  reads output tails, and stops running process groups.
- `quantagent/task_state.py` now stores runtime metadata such as kind, pid,
  command, and output paths while preserving the manual task board.
- `qagent task` gained `--run-shell`, `--refresh`, `--output`, and `--stop`.

Implemented in the local-agent task slice:

- `quantagent/task_runtime.py` can start `local_agent` background tasks that
  wrap `run_agent_v2`, persist stdout/stderr/status/result files, and attach
  trajectory/query-event evidence to the task record.
- Runtime refresh and stop now handle both shell and local-agent process
  groups.
- `task --output` now renders the local-agent status summary and evidence
  paths when the agent did not write plain stdout.
- `qagent task` gained `--run-agent`, `--no-validation`, and
  `--stop-on-failure`.
- `task_state.task_dir` now prefers an existing task registry path so a task
  cannot disappear if the agent later creates `AI_协作交接`.

Core model:

- `kind`: `local_agent`, `shell`, `remote`, `in_process_role`
- `status`: `queued`, `starting`, `running`, `backgrounded`, `passed`,
  `failed`, `blocked`, `aborted`
- task id, parent id, project, policy profile, output paths, event log,
  result summary, evidence, stop requested flag, and failure class

Target behavior:

- Short tools may keep using `run_command_args`.
- Long shell work should use a managed process with output files, timeout,
  process-group cleanup, and `stop`.
- Local agent tasks should wrap current `run_agent_v2`.
- Remote tasks should start as a blocked/stub interface until real remote
  credentials and preconditions exist.
- Parent cancellation cascades to children unless a child is explicitly
  detached.

Useful CLI shape:

```bash
qagent task run-agent "review P4 evidence"
qagent task run-shell -- rg -n PF .
qagent task list
qagent task show qa-0007
qagent task output qa-0007 --tail 12000
qagent task stop qa-0007
```

### 4. Context, Memory, And Compaction

Current QuantAgent has layered context, session JSON, deterministic compaction,
memory extraction, and a SQLite/FTS store. The next leap is statefulness and
inspectability.

Add:

- append-only session event logs
- compaction boundary records
- memory extraction lifecycle state
- context visualization output
- prompt/cache stability diagnostics

Target behavior:

- Keep current session JSON summaries, but add JSONL event logs for messages,
  tool results, compaction snapshots, memory extraction, and context builds.
- Do not split tool-call/tool-result pairs when compacting.
- Track `last_summarized_message_id`, `last_extraction_at`,
  `messages_since_extract`, `tool_calls_since_extract`, `last_token_count`,
  and `extraction_status`.
- Add `qagent context --viz` to show section, source path, chars, estimated
  tokens, rank score, relevance terms, trim status, and stale/obsolete penalty.
- Hash system prompt, tool list, context manifest, and source list so sudden
  context shape changes become visible.

### 5. Prompt Architecture

Do not copy Claude Code prompt text. QuantAgent should have original prompts,
but the prompt layers should be explicit and testable.

Add:

- `quantagent/prompts.py`

Implemented in the first prompt clean-room slice:

- `quantagent/prompts.py` defines original QuantAgent prompt sections instead
  of copying Claude Code prompt text.
- `tool_loop.py` now imports its system prompt from the prompt builder.
- `tests/test_prompts.py` checks required concepts and verifies the runtime
  prompt does not include Claude/Anthropic product text.

Suggested layers:

- `CORE_AGENT_PROMPT`: local quant research agent identity and evidence rules.
- `TOOL_DISCIPLINE_PROMPT`: tool-call ordering, observation grounding, no
  invented results.
- `SAFETY_PROMPT`: shell/file/data/funds/raw-tick boundaries.
- `QUANT_EVIDENCE_PROMPT`: PF, slippage, capacity, 2025 split, dedup and hash
  requirements.
- `SUBAGENT_CONTRACT_PROMPT`: `Scope`, `Evidence`, `Files`, `Verdict`,
  `Open Risks`.
- `STOP_VERIFICATION_PROMPT`: before final answer, report verification or
  explicitly state what was not verified.

Tests should check that required rule fragments appear in prompt builders
without snapshotting long prompt text.

## What Not To Copy

- Claude Code source bodies, source maps, bundled prompts, or minified package
  internals.
- Remote bridge behavior, telemetry, OAuth flows, mobile/desktop product
  surfaces, or vendor-specific protocol shims.
- Any permission bypass, model-routing workaround, or product-specific
  authentication behavior.

## Recommended Build Order

1. `path_policy.py` and file write policy enforcement.
2. `tool_execution.py` unified dispatcher.
3. `query_runtime.py` typed hooks plus `stop` / `stop_failure`.
4. `task_runtime` minimal shell/local-agent runtime.
5. `context --viz` and append-only session event logs.
6. `prompts.py` original QuantAgent prompt layers.

This sequence improves safety and architecture without importing proprietary
implementation text.
