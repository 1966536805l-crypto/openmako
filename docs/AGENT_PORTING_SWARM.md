# Agent Porting Swarm

Internal clean-room planning note. This is not the current public v0.1 capability claim; the current public proof command is `./scripts/public_review_gate.sh`.

Date: 2026-05-26

This is the clean-room porting board for pulling useful agent mechanics into
OpenMako without importing closed-source code or license-poisoning the project.
"Copy" means one of:

- Direct copy: only small permissively licensed files, with license and manifest.
- Clean-room port: reimplement public behavior, architecture, or data contract.
- Study only: learn product mechanics from public docs; do not copy code, text,
  prompts, schemas, endpoints, telemetry, or private service flows.

## Hard Boundary

- Closed products are study-only: Claude Code, Codex product UX, Devin, Cursor,
  Windsurf, Copilot coding agent, and Manus.
- AGPL/GPL/Commons-Clause code is study-only unless it is isolated as an
  external optional dependency with explicit legal review.
- Every direct-copy batch must update `docs/UPSTREAM_ATTRIBUTION.md`, keep the
  upstream license under `third_party/<project>/`, and write a
  `MANIFEST.sha256`.
- A port is not accepted until it has a deterministic test, a failing toxic
  fixture, and a rollback or stop condition.

## Current Swarm Limit

The local sub-agent runtime currently admitted 6 concurrent workers in this
thread. Treat the board as 10 lanes, not a promise that all 10 can run at once.
Run lanes 7-10 after a worker slot is free.

## Ten Porting Lanes

| Lane | Source | Copy mode | OpenMako landing | First useful port | Acceptance test |
| ---: | --- | --- | --- | --- | --- |
| 1 | OpenHands | Clean-room first; direct-copy only after per-path license check | `quantagent/task_runtime.py`, `quantagent/worktree_isolation.py`, `quantagent/agent_supervisor.py` | Task container contract: workspace, command log, terminal status, artifact bundle | A failed task can be replayed from artifacts without rerunning the agent |
| 2 | SWE-agent | MIT; small direct-copy allowed, prefer Python-native port | `quantagent/eval_harness.py`, `quantagent/edit_loop.py`, `quantagent/agent_autopsy.py` | Issue-to-patch harness with patch artifact, test command, and failure class | Bad patch fixture produces patch, test failure, and autopsy timeline |
| 3 | Aider | Apache-2.0; repo-map already vendored | `quantagent/code_index.py`, `quantagent/context_pack.py`, `quantagent/edit_loop.py` | Symbol-ranked file context and diff-first repair loop | Context selection ranks referenced definitions above random files |
| 4 | browser-use | Clean-room behavior port unless license is checked per file | `quantagent/desktop_intelligence.py`, `quantagent/desktop_workflow.py` | Observe-act-verify state machine for visual targets | 20 desktop fixtures: target token, action, post-action semantic check |
| 5 | Open Interpreter | AGPL-3.0: study-only for default repo | `quantagent/desktop_control.py`, `quantagent/sandbox_policy.py`, `quantagent/approvals.py` | Local computer-control consent gates and command preview | Side-effect desktop actions cannot run without explicit execute/review flags |
| 6 | Goose | Apache-2.0; small direct-copy after per-path check | `quantagent/mcp_runtime.py`, `quantagent/plugin_runtime.py`, `quantagent/tool_registry.py` | Extension/MCP tool lifecycle with env whitelist and diagnostics | Broken MCP config reports actionable doctor errors without running tools |
| 7 | LangGraph | MIT; clean-room graph/state port preferred | `quantagent/task_graph.py`, `quantagent/orchestrator.py`, `quantagent/runtime_store.py` | Durable state graph with checkpoints and retry edges | Interrupted graph resumes from checkpoint with same terminal result |
| 8 | AutoGPT Forge | License check required; clean-room task protocol | `quantagent/task_state.py`, `quantagent/runtime_ledger.py`, `quantagent/eval_harness.py` | Agent benchmark task spec: input, constraints, expected artifact, score | Same task spec can run local agent and desktop daemon with common verdict |
| 9 | Claude/Codex/Copilot public mechanics | Study-only | `quantagent/query_runtime.py`, `quantagent/approvals.py`, `quantagent/sessions.py` | Query generation guard, permission queue, resumable session state | Stale tool completion cannot clear a newer active query |
| 10 | Devin/Cursor/Windsurf/Manus public UX | Study-only | `quantagent/chat_ui.py`, `quantagent/ux_status.py`, `quantagent/checkpoints.py` | Checkpointed UX status: plan, active tool, changed files, next approval | UI status stays coherent during queued input, active tool, and abort |

## First Cut Order

1. Desktop L4 regression harness from lane 4.
2. Issue-to-patch autopsy fixture from lane 2.
3. MCP/plugin doctor gate from lane 6.
4. Durable checkpoint graph from lane 7.
5. Product status model from lanes 9-10.

This order raises the current desktop-agent score fastest because it attacks
the weakest parts first: verification, recovery, and repeated-task evidence.

## Worker Findings Received

### Lane 2: SWE-agent

- Port the ACI idea as a narrow file/edit shell: open, goto, scroll, search
  directory, search file, edit range, submit patch.
- Keep search bounded. A large search result must force query narrowing instead
  of dumping massive grep output into model context.
- Edit must be gated: build a diff, run syntax/lint checks, and reject without
  changing source files when validation fails.
- Issue-to-patch needs a first-class artifact: issue text, changed files,
  targeted test, full test, patch, trajectory, and failure class.
- Toxic fixtures: wrong line, repeated old text, Python syntax error, path
  escape, binary edit, targeted-test pass with full-test failure, and isolated
  worktree pollution.

Landing modules:

- `quantagent/file_ops.py`
- `quantagent/tool_execution.py`
- `quantagent/edit_loop.py`
- `quantagent/patch_engine.py`
- `quantagent/apply_gate.py`
- `quantagent/worktree_isolation.py`
- `quantagent/trajectory.py`

### Lane 1: OpenHands

- Add a clean-room `SandboxSpec`: backend, command, environment, cwd, network,
  status, and terminal reason. Host/process mode must never be described as
  secure isolation.
- Tool events must be typed as action and observation pairs. An orphan action
  cannot enter the next model view; tool crashes must produce synthetic error
  observations.
- Run-loop state should be explicit: idle, running, waiting for confirmation,
  paused, finished, error, stuck.
- Context condensation must be append-only: record a tombstone/summary view
  instead of rewriting history, and never split tool-call atomic pairs.
- Parallel tool batches require resource locks. Default to serial until every
  tool declares a resource key.

Landing modules:

- `quantagent/worktree_isolation.py`
- `quantagent/task_runtime.py`
- `quantagent/sandbox_policy.py`
- `quantagent/runtime_store.py`
- `quantagent/event_log.py`
- `quantagent/trajectory.py`
- `quantagent/query_runtime.py`
- `quantagent/agent_loop_core.py`
- `quantagent/tool_execution.py`

### Lane 3: Aider

- Keep repo-map as ranked symbol context: definitions, references, mentioned
  identifiers, graph score, and token budget clipping.
- Add cache invalidation by file mtime/hash so deleted or changed files cannot
  survive in ranked context.
- Add edit-block codec and dry-run previews. Exact unique match comes first;
  fuzzy match may suggest but must not auto-apply.
- Test receipts should be structured: command, return code, stdout/stderr
  artifact, failure class, targeted/full scope.
- Compression must preserve current user request, tool-call pairs, test
  commands, file paths, and summary provenance/hash.

Landing modules:

- `quantagent/repo_map.py`
- `quantagent/context_providers.py`
- `quantagent/patch_engine.py`
- `quantagent/edit_loop.py`
- `quantagent/patch_visa.py`
- `quantagent/trajectory_compact.py`
- `quantagent/compact_budget.py`

### Lane 4: browser-use

- Port the browser state idea into `DesktopObservation`: screenshot, AX, OCR,
  SoM, grid, front app/window, screen hash, and observation id.
- Side-effect actions should target `token_id` or `mark_id`; naked coordinates
  are blocked unless explicitly reviewed.
- Before click/type, re-tokenize and reject stale targets when the foreground
  window changed, target disappeared, or bounds moved too far.
- Verify must become semantic: target appeared/disappeared, text value matched,
  title/window changed, or expected query is visible. A fresh screenshot alone
  is not proof.
- Add loop detection: same action hash with unchanged token hash three times
  becomes `blocked/replan_needed`.
- Status: first L4 gate slice landed in `quantagent/desktop_intelligence.py`:
  observation id, screen hash, target hash, stale-target preflight, typed-text
  semantic verify, click target-change verify, legacy tokenization compatibility,
  and stagnant-loop blocking.

Landing modules:

- `quantagent/desktop_intelligence.py`
- `quantagent/desktop_workflow.py`
- `quantagent/gui_patterns.py`
- `quantagent/desktop_agent.py`
- `quantagent/trajectory.py`
- `quantagent/query_runtime.py`

### Lane 5: Open Interpreter

- Open Interpreter is AGPL-3.0 in the inspected public repo; default stance is
  study-only. Do not direct-copy source into OpenMako.
- Useful shape: execution request, preview, user confirmation, local execution,
  stream result, and persisted output.
- Do not expose a raw Python `computer` object to the model. Desktop and shell
  operations must remain manifest tools with schema, policy, and audit records.
- `auto_run` should not be ported as a default behavior. If it ever exists, it
  belongs behind an explicit developer profile and a visible local switch.
- Approval must bind to a fingerprint. Changing command/code/args invalidates
  approval.

Landing modules:

- `quantagent/tool_execution.py`
- `quantagent/policy_gate.py`
- `quantagent/approvals.py`
- `quantagent/sandbox_policy.py`
- `quantagent/shell_semantics.py`
- `quantagent/desktop_workflow.py`
- `quantagent/tool_manifest_v2.py`
- `quantagent/runtime_store.py`

### Lane 6: Goose

- The Goose lane failed due to a remote compact/network error in the sub-agent,
  so this is a conservative fallback from the existing porting map.
- Useful mechanism: local extension/MCP tool lifecycle with explicit install,
  enable, disable, env whitelist, diagnostics, and per-tool permission rules.
- Recipes/automation should become task specs, not hidden prompt blobs.
- Tool discovery must be cached and diagnostic-first. Broken MCP servers should
  show doctor errors without running arbitrary startup commands.

Landing modules:

- `quantagent/mcp_runtime.py`
- `quantagent/plugin_runtime.py`
- `quantagent/tool_registry.py`
- `quantagent/tool_manifest_v2.py`
- `quantagent/doctor.py`

### Lane 9: Claude/Codex/Copilot Public Mechanics

- Study-only. Learn public product mechanics, not source, prompts, schemas,
  private APIs, telemetry, or branded wording.
- Query guard should use idle/dispatching/running plus a generation token.
  Stale completion cannot clear a newer query.
- Permission queue must run before every side effect: allow, ask, deny, hook,
  sandbox, approval fingerprint, invocation ledger.
- Resume restores transcript, tool calls/results, artifacts, and approvals.
  File rollback is a checkpoint feature, not a session feature.
- Issue/PR tasks should be one repo, one branch, one task, one reviewable
  output bundle.
- Background subagents default to isolated worktrees. If they need approval,
  they fail or auto-deny; they do not block the parent on a hidden prompt.

Landing modules:

- `quantagent/query_guard.py`
- `quantagent/query_runtime.py`
- `quantagent/approvals.py`
- `quantagent/tool_execution.py`
- `quantagent/policy_gate.py`
- `quantagent/permission_policy_v2.py`
- `quantagent/sessions.py`
- `quantagent/resume.py`
- `quantagent/task_runtime.py`
- `quantagent/worktree_isolation.py`

### Lane 7: LangGraph

- LangGraph core is MIT, but default porting mode is clean-room mechanism
  reuse. Enterprise/self-hosted server paths are out of scope.
- Add durable checkpointing by super-step: values, next nodes, metadata,
  parent, task list, schema version.
- Side-effect tool calls need memo keys: thread id, node id, and args hash.
  Resume must not repeat a successful write/click/API call.
- Reducers are mandatory for concurrent writes. Append-only fields such as
  messages and observations can merge; scalar double writes without reducers
  fail closed.
- Supervisor should be a graph, not a pile of callbacks: plan, launch, refresh,
  repair, finish, with `active_agent` and handoff state.
- Human-in-the-loop interrupts checkpoint before waiting and resume by appending
  a new decision, not mutating old history.

Landing modules:

- `quantagent/agent_loop_core.py`
- `quantagent/runtime_store.py`
- `quantagent/checkpoints.py`
- `quantagent/tool_execution.py`
- `quantagent/query_runtime.py`
- `quantagent/resume.py`
- `quantagent/agent_supervisor.py`
- `quantagent/subagents.py`
- `quantagent/task_graph.py`

### Lane 8: AutoGPT Forge / Agent Protocol

- AutoGPT platform has mixed licensing; the useful Classic/Forge/benchmark
  pieces should still be clean-room ported. Do not import platform code.
- Useful interface shape: task, step, artifact, list/get lifecycle. This can
  become a local OpenMako task protocol without adding FastAPI to core.
- Challenge spec should be data-first: name, category, task, dependencies,
  cutoff, ground truth, artifacts in/out, evaluator.
- Runner must isolate workspace, copy only declared input artifacts, enforce
  time/step cutoff, collect outputs, and write comparison reports.
- Evaluators should be deterministic: file contains/excludes, Python script,
  or pytest. No prose-only pass.

Landing modules:

- `quantagent/eval_harness.py`
- `quantagent/task_runtime.py`
- `quantagent/task_state.py`
- `quantagent/run_artifacts.py`
- `quantagent/trajectory.py`
- `quantagent/permission_policy_v2.py`
- `quantagent/cli.py`

### Lane 10: Devin/Cursor/Windsurf/Manus Public UX

- Study-only. Port product mechanics, not UI code, private APIs, prompts,
  telemetry, or brand language.
- Make `task_id` the UX spine: checkpoint, active status, current tool,
  changed files, latest artifact, next approval, queue state, and resume
  command all derive from runtime ledger.
- Checkpoints should be agent-scoped and independent of Git. Restore first
  previews a diff and blocks when manual changes would be overwritten.
- Active task view must show progress timeline, current tool, next blocker,
  and latest checkpoint from facts only.
- Long-task queue needs sequence, target task, deliver-after status, dedupe key,
  and restart-safe delivery.
- Desktop/browser/IDE context is untrusted evidence. Inject paths and summaries,
  never raw screen/web text as system instruction.

Landing modules:

- `quantagent/checkpoints.py`
- `quantagent/edit_loop.py`
- `quantagent/ux_status.py`
- `quantagent/tui_status_model.py`
- `quantagent/query_runtime.py`
- `quantagent/task_state.py`
- `quantagent/task_runtime.py`
- `quantagent/session_bus.py`
- `quantagent/runtime_store.py`
- `quantagent/desktop_intelligence.py`
- `quantagent/context_providers.py`
- `quantagent/worktree_isolation.py`

## L4 Gate

OpenMako should not claim L4 until all of these pass:

- At least 20 multi-step desktop fixtures run with screenshots, tokens,
  actions, semantic verification, and failure autopsy.
- At least 5 code-repair fixtures run through issue-to-patch with isolated
  worktrees and deterministic test classification.
- Permission policy blocks high-risk desktop goals by default and leaves a
  replayable denial record.
- A killed daemon can resume or produce a deterministic incomplete-run report.
- The evaluator can compare two agents on the same task from recorded evidence,
  not from final prose.

## Worker Output Contract

Each porting worker must return:

1. Source and license status.
2. Mechanisms that can be copied, ported, or only studied.
3. Exact OpenMako files to modify.
4. Smallest useful patch.
5. Toxic test that prevents a lazy implementation from passing.
6. Stop condition where the idea should be rejected.
