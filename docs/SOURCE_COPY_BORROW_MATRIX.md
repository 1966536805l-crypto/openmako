# Source Copy / Borrow Matrix

Date: 2026-05-25

This matrix separates what OpenMako may directly reuse from what should be
ported or only studied. It covers the local OpenClaw, Hermes, and Claude-like
source trees inspected on this machine.

## Rule Of Thumb

- OpenClaw: MIT. Direct reuse is legally possible with attribution, but TS/JS
  code should usually be ported into small Python-native modules.
- Hermes: MIT. Direct reuse is legally possible with attribution, and Python
  modules are easier to adapt, but user-facing prose should still be rewritten
  in OpenMako style.
- Claude-like source: no permissive license found in the local material and it
  contains product/brand/private-service code. Do not copy source, prompts,
  constants, strings, endpoint logic, or implementation text. Use only
  clean-room architectural lessons.

## Direct Copy Candidates

These are small, bounded, permissively licensed, and low-risk if attribution is
kept in `docs/UPSTREAM_ATTRIBUTION.md` plus the relevant `third_party/*`
license files.

### OpenClaw

- Small runtime utilities already vendored in `third_party/openclaw/selected`:
  backoff, timeout parsing, balanced JSON, JSON pointer, secret masking,
  console/text sanitizing, command polling delay, date/duration formatting,
  arg splitting, session id validation, finite number parsing, and human-list
  formatting.
- Additional small media guards worth porting:
  `src/media/read-response-with-limit.ts`,
  `src/media/read-byte-stream-with-limit.ts`,
  `src/media/inbound-path-policy.ts`,
  `src/media/sniff-mime-from-base64.ts`,
  `src/media/file-name.ts`, and `src/media/temp-files.ts`.
- Additional small security helpers worth porting:
  `src/security/safe-regex.ts`, `src/security/scan-paths.ts`,
  `src/security/secret-equal.ts`, and the data-only parts of
  `src/security/dangerous-tools.ts`.
- Tests can be copied or translated when they are validating generic behavior:
  path traversal, byte limits, timeout behavior, plugin path escapes, stale
  task reconciliation, and secret redaction.

Target OpenMako modules:

- `quantagent/openclaw_runtime_utils.py`
- `quantagent/path_policy.py`
- `quantagent/redaction.py`
- `quantagent/doctor.py`
- `quantagent/media_policy.py` if media support becomes a first-class feature.

### Hermes

- `tools/path_security.py` and the simple validation shape behind it.
- `tools/tool_output_limits.py` and the config fallback pattern.
- The small `agent/iteration_budget.py` budget counter.
- Pieces of `tools/tool_result_storage.py` that implement preview plus
  persisted output artifact, as long as wording is rewritten and paths are
  OpenMako-native.
- Test fixtures or assertions for large tool output, path traversal, URL
  safety, and permission bridging.

Target OpenMako modules:

- `quantagent/tool_output.py`
- `quantagent/tool_execution.py`
- `quantagent/path_policy.py`
- `quantagent/compact_budget.py`
- `quantagent/agent_loop_v3.py`

## Port, Do Not Copy Whole

These are strong designs but too coupled to their original runtime. Rebuild
them in OpenMako's Python architecture.

### OpenClaw

- `src/tasks/*`: port the task registry contract, not the implementation.
  The valuable pieces are runtime kind, owner key, child session key, notify
  policy, delivery state, terminal summary, cleanup time, and reconcile/lost
  task handling.
- `src/plugin-state/*`: port the keyed plugin state store contract:
  namespace, max entries, TTL, consume-once, probe results, schema version,
  and explicit error codes.
- `src/hooks/*`: port the model of hook entries, source policy, enable state,
  collisions, plugin hooks, internal hooks, and status reporting. Do not
  import the JS module-loader behavior directly.
- `src/mcp/*`: port the idea that local tools and plugin tools can be exposed
  as MCP servers, but keep OpenMako's `mcp_runtime.py` as the implementation.
- `src/security/external-content.ts`: port the untrusted-content boundary and
  suspicious-pattern detection idea, but rewrite all warning text and marker
  strings.
- `src/security/audit*.ts`: port the doctor/audit categories, not the full
  OpenClaw gateway assumptions.
- `src/channels/*`: only useful if OpenMako grows chat-channel gateways. Port
  allowlists, mention gating, sender identity, binding, debounce, and typing
  state as data contracts.

Target OpenMako modules:

- `quantagent/task_runtime.py`
- `quantagent/task_state.py`
- `quantagent/runtime_store.py`
- `quantagent/plugin_runtime.py`
- `quantagent/lifecycle_hooks.py`
- `quantagent/mcp_runtime.py`
- `quantagent/doctor.py`
- `quantagent/input_provenance.py`

### Hermes

- `hermes_state.py`: port schema ideas, not the whole state layer. The useful
  ideas are rich session rows, parent lineage, token/cost fields, message FTS,
  anchored message views, title/search helpers, orphan compression cleanup,
  and vacuum/prune maintenance.
- `agent/context_engine.py` and `agent/context_compressor.py`: port the
  pluggable context engine interface, preflight compression, old tool-result
  pruning, historical media stripping, and fallback behavior. Do not copy
  summarizer prompts.
- `agent/error_classifier.py`: port the taxonomy and recovery hints, then map
  them to OpenMako provider/model errors.
- `agent/tool_executor.py`: port concurrent tool-call lifecycle ideas, not the
  global agent coupling.
- `acp_adapter/*`: port the event and permission bridge shape if OpenMako
  exposes ACP or editor integrations. Do not copy client-specific UI strings.
- `agent/lsp/*`: port range-shift and diagnostic reporting concepts if LSP
  becomes a serious first-class integration.

Target OpenMako modules:

- `quantagent/runtime_store.py`
- `quantagent/query_runtime.py`
- `quantagent/model_client.py`
- `quantagent/retry_utils.py`
- `quantagent/context_pack.py`
- `quantagent/trajectory_compact.py`
- `quantagent/tool_execution.py`
- `quantagent/lsp_diagnostics.py`

## Clean-Room Only

These are useful to study, but direct copying is off-limits.

### Claude-Like Source

Observed source areas:

- `QueryEngine.ts`, `query.ts`, `utils/QueryGuard.ts`
- `Task.ts`, `tasks/*`
- `state/AppStateStore.ts`, `state/selectors.ts`, `state/onChangeAppState.ts`
- `screens/REPL.tsx`, `hooks/useCancelRequest.ts`,
  `hooks/useQueueProcessor.ts`
- `services/compact/*`, `services/contextCollapse/*`
- `utils/permissions/*`, `components/permissions/*`
- `mcp/*`, `plugins/*`, `skills/*`, `bridge/*`, `remote/*`

Borrow only these mechanisms:

- Query guard with generation numbers to prevent stale cleanup.
- Prompt queue that reserves a dispatch slot before the model call begins.
- Query loop as a reducer-like state machine with recovery branches.
- Message/tool pairing invariants and synthetic tool results after abort.
- Compact boundary messages and post-compact context reinjection.
- App state store with selector-style views for TUI, approvals, tasks, and
  status.
- Permission requests as first-class queue entries with scope and denial
  tracking.
- Cancel behavior that distinguishes queued input, active model call, active
  tool, and modal permission prompt.
- Session resume that restores more than transcript text.

Do not copy:

- Source bodies, prompts, constants, output strings, schemas, endpoint names,
  brand names, auth flows, telemetry, feature flags, private bridge code,
  marketplace policy, or cloud remote-control behavior.

Target OpenMako modules:

- `quantagent/query_runtime.py`
- `quantagent/runtime_store.py`
- `quantagent/sessions.py`
- `quantagent/resume.py`
- `quantagent/chat_ui.py`
- `quantagent/tui_status_model.py`
- `quantagent/approvals.py`
- `quantagent/tool_execution.py`
- `quantagent/plugin_runtime.py`
- `quantagent/mcp_runtime.py`

## Do Not Borrow

- Claude/Anthropic private bridge, remote sessions, trusted-device tokens,
  JWT/work secret, cloud permission callbacks, or product telemetry.
- First-party commercial marketplace rules, subscription/usage upsell flows,
  account/org identifiers, or experiment names.
- OpenClaw/Hermes platform-specific channel integrations unless OpenMako
  intentionally becomes a multi-channel gateway.
- Large TS UI surfaces from OpenClaw or Claude. OpenMako is currently Python
  CLI/TUI; copying React/Ink architecture directly would add mismatch.
- Hermes provider-specific OAuth, chat-platform, voice, image/video provider,
  and meeting integrations until there is a concrete product requirement.

## Best Next Imports

1. OpenClaw task registry data contract.
   Add owner key, child session key, delivery status, notify policy, terminal
   summary, cleanup time, and lost-task reconciliation to OpenMako's task
   SQLite rows.

2. Hermes error classifier.
   Add a provider-error taxonomy to `model_client.py` and `retry_utils.py`:
   auth, billing, rate limit, overloaded, timeout, context overflow, payload
   too large, model not found, format error, multimodal tool-content fallback,
   and unknown.

3. Plugin keyed state store.
   Add plugin-scoped namespace, TTL, max entries, consume-once, probe result,
   and doctor diagnostics.

4. External content fence.
   Add `quantagent/input_provenance.py` or `quantagent/external_content.py`
   wrappers for web/search/email/channel content, with OpenMako-native text
   and tests for spoofed markers.

5. Tool output aggregate budget.
   OpenMako already has `tool_output.py`; add per-turn aggregate enforcement
   so many medium results cannot overflow context.

6. MCP active catalog.
   Use plugin/MCP config hashes and reconnect generation. Invalidate tool,
   resource, prompt, and skill catalogs when config or server notifications
   change.

7. QueryGuard clean-room implementation.
   Add an OpenMako-native guard with idle/dispatching/running, generation, and
   stale-finally protection.

## Attribution Checklist

When directly reusing OpenClaw or Hermes code:

- Keep the MIT license text in `third_party/<project>/LICENSE`.
- Record the exact source file in `docs/UPSTREAM_ATTRIBUTION.md`.
- Add or update a manifest hash under `third_party/<project>/MANIFEST.sha256`.
- Prefer a Python-native wrapper over a large vendored subsystem.
- Rewrite product-facing prose unless the source is intentionally vendored as
  documentation with attribution.

When using Claude-like source:

- Do not copy text or code.
- Write a short clean-room note describing the mechanism and target OpenMako
  module.
- Implement from OpenMako tests outward.
