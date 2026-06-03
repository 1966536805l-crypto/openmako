# Hermes / OpenClaw Source Scan

Date: 2026-05-24

## Scope

Read-only scan of the local material available on this machine:

- OpenClaw package: `/Users/euhualihuawaiigeeeeegehanggeyewo/.npm-global/lib/node_modules/openclaw`
- OpenClaw runtime state: `/Users/euhualihuawaiigeeeeegehanggeyewo/.openclaw`
- Hermes runtime state and skills: `/Users/euhualihuawaiigeeeeegehanggeyewo/.hermes`
- Project reference folders: `upstream_refs/openclaw`, `upstream_refs/hermes-agent`

The project reference folders currently contain only license files, so the useful scan material is the installed OpenClaw npm bundle and Hermes local runtime/skills. This report records architecture-level lessons only; no upstream implementation is copied here.

## OpenClaw Findings

OpenClaw is installed as an npm package named `openclaw`, version `2026.5.20`, with MIT license metadata. The installed artifact is mostly bundled `dist/*.js` plus TypeScript declaration files. It is not a clean source tree, but its module boundaries are clear.

High-value architecture visible in the bundle:

- Plugin system: 91 bundled plugin manifests under `dist/extensions/*/openclaw.plugin.json`.
- Provider catalog and auth: provider modules for OpenAI, Anthropic, OpenRouter, Ollama, Google, Qwen, DeepSeek, etc.; generated plugin install state includes manifest hashes, source paths, compatibility tags, startup flags, and auth references.
- Agent harness: runtime plan construction, model/tool normalization, tool progress formatting, context-engine maintenance, session transcript append, compaction hooks, terminal outcome classification, gateway tool calls.
- Hooks: a global prioritized hook runner with fail-open/fail-closed policy, timeouts, void hooks, modifying hooks, claiming hooks, and lifecycle points including `before_model_resolve`, `before_prompt_build`, `before_tool_call`, `after_tool_call`, `before_agent_finalize`, `before_compaction`, `after_compaction`, `session_start`, `session_end`, `subagent_spawning`, `subagent_spawned`, `subagent_ended`, `gateway_start`, `gateway_stop`, and `before_install`.
- Native hook relay: provider-facing bridge events `pre_tool_use`, `post_tool_use`, `permission_request`, `before_agent_finalize`; permission decisions include allow, deny, allow-always, defer.
- Session binding: records bind a target session/subagent to a conversation, with active/ending/ended status, TTL, metadata, placement, and conversation reference.
- Thread binding policy: per-channel/per-account enablement, idle timeout, max age, spawn policy, and default spawn context (`isolated` or `fork`).
- MCP runtime: session-scoped MCP manager with catalog generation, server/tool records, session-key binding, tool calls, leases, idle sweeping, and disposal.
- Skills: a `SkillSnapshot` captures prompt text, resolved skills, env requirements, filters, and a version stamp. OpenClaw stores that snapshot in session state.
- Detached task registry: SQLite-backed task runs with owner/session lineage, child session key, parent task/flow, progress summary, terminal summary, delivery status, cleanup, and indexes.
- Security/doctor: filesystem permission inspection, world/group writable checks, remediation commands, secret-file runtime, SSRF-related types, approval forwarding, channel allowlists.

Runtime state confirms these designs:

- `/Users/euhualihuawaiigeeeeegehanggeyewo/.openclaw/agents/main/sessions/sessions.json` stores session id, session key, session file, auth profile override, compaction count, and skills snapshot.
- `/Users/euhualihuawaiigeeeeegehanggeyewo/.openclaw/plugins/installs.json` is generated state with manifest hashes, policy hash, compatibility registry version, enabled plugins, origins, startup flags, and package metadata.
- `/Users/euhualihuawaiigeeeeegehanggeyewo/.openclaw/tasks/runs.sqlite` stores detached task lifecycle and delivery state.

## Hermes Findings

Hermes local install appears as runtime state plus a native binary:

- `/Users/euhualihuawaiigeeeeegehanggeyewo/.hermes/bin/tirith` is a Mach-O arm64 executable, not readable source.
- `/Users/euhualihuawaiigeeeeegehanggeyewo/.hermes/config.yaml` currently points at `openai-codex` / `gpt-5.5`, with `xhigh` reasoning.
- `/Users/euhualihuawaiigeeeeegehanggeyewo/.hermes/state.db` is a SQLite session store.
- `/Users/euhualihuawaiigeeeeegehanggeyewo/.hermes/skills` is the most useful readable asset.

Hermes state database has a stronger session model than QuantAgent currently has:

- `sessions`: id, source, user, model, model config, system prompt, parent session id, timestamps, title, token counts, cache tokens, reasoning tokens, billing metadata, cost fields, handoff fields.
- `messages`: session id, role, content, tool call id, tool calls, tool name, timestamp, token count, finish reason, reasoning fields, Codex reasoning/message items.
- FTS indexes over messages using both normal text and trigram tokenization.

Useful Hermes skills inspected:

- `subagent-driven-development`: fresh subagent per task, plan parsed once by controller, complete task context passed to workers, two-stage review: spec compliance first, code quality second.
- `test-driven-development`: strict red/green/refactor, watch test fail before implementation, then pass specific test and full suite.
- `systematic-debugging`: four phases: root cause investigation, pattern analysis, hypothesis testing, implementation; explicitly blocks random fixes.
- `native-mcp`: stdio/HTTP MCP servers, startup discovery, tool naming convention, auto-injection, long-lived background connections, reconnection, filtered env, credential redaction.
- `hermes-agent`: product surface includes profiles, sessions, skills, MCP, gateway, cron, webhooks, credential pools, doctor, model switching, worktree mode.

## Best Borrowable Patterns

Highest return for QuantAgent:

1. SQLite task/session store.
   Replace or complement JSON task files with SQLite tables for sessions, messages, task runs, delivery state, token/cost counters, parent-child lineage, and FTS search.

2. Real subagent task lifecycle.
   Add OpenClaw-style task rows with `owner_key`, `scope_kind`, `child_session_key`, `parent_task_id`, `progress_summary`, `terminal_summary`, `terminal_outcome`, and cleanup indexes.

3. Hook runner.
   Upgrade current one-shot hooks into a prioritized registry with hook types: void, modifying, claiming. Start with agent/tool/session lifecycle hooks.

4. Skill snapshots.
   Store the exact skills injected into each session/run, including resolved paths, env requirements, and version. This makes old decisions reproducible.

5. MCP runtime.
   Implement Hermes/OpenClaw-inspired MCP discovery as a first-class tool source: config, stdio/http transport, catalog, sanitized env, redacted errors, session-scoped runtime.

6. Permission approval bridge.
   Add structured permission requests around shell/file/network actions, with stable fingerprints and allow/deny/allow-once/allow-always outcomes.

7. Session binding / spawn policy.
   Track parent and child sessions explicitly, define fork vs isolated context, and set max-age/idle timeout behavior.

8. Plugin manifest registry.
   Move from ad hoc plugin runtime to generated registry state with manifest hash, origin, enabled flag, startup roles, compatibility tags, and policy hash.

9. Doctor checks.
   Add security checks for world/group-writable config, missing completion files, auth conflicts, broken symlinks, stale state DB WAL files, and suspicious permissions.

10. Strict engineering workflows as skills.
    Port the ideas of TDD, systematic debugging, and two-stage subagent review into QuantAgent-native skills without copying the exact upstream prose.

## Direct Copy Risk

OpenClaw package metadata says MIT, and many Hermes skill frontmatter entries also say MIT, so legal reuse may be possible with attribution. Still, direct copy is not the best path for QuantAgent:

- OpenClaw is bundled/minified-ish runtime output, not maintainable source.
- Hermes core executable is binary; only skills/config/state are readable.
- QuantAgent is Python and domain-specific; direct JS/Python prose copy would create mismatch.
- Clean-room reimplementation keeps design coherent and avoids dragging in hidden assumptions.

Recommended stance: borrow contracts, data shapes, and workflow mechanics; rewrite implementation and user-facing text in QuantAgent style; keep attribution in `docs/UPSTREAM_ATTRIBUTION.md` when porting a meaningful pattern.

## QuantAgent Gap Map

Already present:

- Startup trust prompt.
- Safety/policy gate.
- Local skills.
- Basic hooks plus a reusable prioritized hook runner.
- Background tasks with JSON compatibility and SQLite runtime mirroring.
- Agent v2 event/trajectory files.
- SQLite runtime store for sessions, messages, query events, skill snapshots, task runs, and delivery state.
- Plugin registry metadata with manifest hashes, enabled state, origins, policy hash, diagnostics, and refresh output.
- Doctor checks for runtime DB health, stale tasks, auth conflicts, broken shell completion source paths, project skills, and plugin registry errors.
- Multi-file edit-loop with test retry.
- Domain-specific quant checks and evidence discipline.

Still shallow versus OpenClaw/Hermes:

- SQLite is currently a compatibility mirror; JSON remains the primary user-facing task/session artifact.
- Session/message storage has SQLite and FTS search, but token/cost/tool-call/reasoning accounting is still mostly empty.
- Hooks have a runner, but core agent/tool paths are not fully driven through plugin-owned hooks yet.
- MCP is not yet a real runtime.
- Subagent lifecycle is not yet represented as first-class parent/child sessions.
- Plugin execution and install/update flows are still metadata-only.
- Permission approvals are policy decisions, not resumable approval objects.

## Suggested Build Order

1. Done: add SQLite `runtime_store.py` with sessions, messages, query_events, skill_snapshots, task_runs, task_delivery_state, schema version, and FTS-backed message search.
2. Partial: task lifecycle is mirrored into SQLite for manual, shell, and local-agent tasks; explicit recover_orphans/list/status APIs still need CLI exposure.
3. Done: wire current task/session/query runtime paths to write both JSON/JSONL and SQLite during migration.
4. Partial: session/message persistence and FTS search exist; `qagent sessions export/search` still needs a CLI surface.
5. Done: skill snapshot persistence at agent-v2 start, with snapshot id attached to `query_start`.
6. Done foundation: hook registry with prioritized handlers, modifying hooks, claiming hooks, fail-open/fail-closed, and timeouts. Still needs full integration into agent/tool paths.
7. Add MCP config parser and catalog-only discovery first; tool calls second.
8. Partial: doctor/security checks cover runtime DB health, auth conflicts, broken completion source, task DB health, stale runtime processes, project skills, and plugin registry errors. Config file permission checks are still pending.
