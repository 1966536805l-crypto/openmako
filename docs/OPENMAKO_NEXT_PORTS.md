# OpenMako Next Ports

## Clean-Room Absorption Spine

Use `docs/CLAUDE_SRC_ABSORPTION_PLAN.md` as the cross-subsystem blueprint.
It is mechanism-only: no proprietary source bodies, bundled prompts, product
strings, or private service flows.

## P0: Query State Machine And Message Ledger

Promote `QueryRuntime` from event recording into the primary query state
machine. Add SQLite-backed message identities, parent links, tool pair repair,
compact boundaries, transition reasons, terminal reasons, recovery reasons,
and token budget decisions.

## P0: SQLite Primary Runtime

Move sessions, messages, tool invocations, approvals, task runs, subagent
lineage, token usage, and cost accounting into SQLite as the primary store.
Keep JSON/JSONL as export and compatibility only.

## P0: Unified Permission Queue

Route local tools, shell, MCP tools, plugin tools, and skill-triggered actions
through one permission/approval queue with allow-once, allow-session,
allow-always, deny, fingerprint validation, checkpoint metadata, and
replayable invocation rows.

## P1: Subagent Controller/Worker Workflow

Implement parent-owned task specs, fresh worker contexts, terminal summaries,
and two-stage parent review: spec compliance first, quality review second.

## P1: Token And Cost Ledger

Record model, provider, input tokens, output tokens, reasoning tokens, cache
tokens, latency, estimated cost, query id, session id, and task id for every
model call.

## P2: Plugin Governance

Promote plugin registry from metadata-only to governed plugin lifecycle:
install, enable, disable, hash verification, policy hash, diagnostics, startup
roles, and compatibility checks.

## P2: MCP Long-Lived Runtime

Add background MCP server leases, catalog cache, reconnect, env whitelist,
credential redaction, idle cleanup, and per-server/tool permission rules.

## P2: Product REPL State

Unify transcript, prompt queue, active query generation, approvals, running
tasks, MCP/plugin status, token/cost, and resume metadata behind one status
model for chat UI, doctor, and headless SDK.

## P2: Stronger Doctor

Add checks for config permissions, secret-file permissions, stale WAL files,
stale daemon PIDs, world-writable plugin dirs, broken symlinks, and suspicious
MCP commands.
