# Context Engine

QuantAgent uses layered context instead of dumping every recent file into the model.

## Layers

1. Core rules: dedup only, no 1253 polluted sample, 09:25 signal / 09:30 entry, three-pass ChatGPT consistency gate, model output is not fact.
2. Project state: compact stage, hard rules, baselines, scripts, known conclusions.
3. Rule source: `CLAUDE.md` preview.
4. Latest communication: recent handoff files scored by recency and task relevance.
5. Evidence: result registry and clean baseline/request files.
6. Tools: known scripts.

## Budget

Default non-chat context budget is 80,000 estimated tokens, controlled by:

```bash
QUANTAGENT_CONTEXT_BUDGET_TOKENS=80000
```

The engine converts that token budget to a conservative character budget, sorts items by priority and relevance, then trims to fit. It does not blindly fill the whole budget; it keeps the strongest sources first so stale or discarded conclusions do not crowd out current evidence.

Recommended non-chat modes:

- Daily: `80000`
- Deep research: `180000`
- Full reconstruction: `276000`

`qagent chat` uses an automatic context router so short messages do not send the whole project memory:

- light: short command/status/usage questions, `QUANTAGENT_CHAT_CONTEXT_TOKENS=6000`
- standard: analysis, code, audit, strategy, P4/tick/backtest/PF questions, `QUANTAGENT_LONG_CONTEXT_TOKENS=18000`
- deep: full reconstruction, handoff, final reports, or explicit `--deep-context`, `QUANTAGENT_DEEP_CONTEXT_TOKENS=80000`

The selected mode and trigger reasons are written into the reasoning summary for each reply.

## Claude Code Patterns Adopted

- Protected core: hard rules are always restored at the top of context.
- Budget tracker: every chat shows estimated tokens, token budget, percent used, and warning state.
- Tool-result compression: large outputs should live in registry; context carries summaries and paths.
- Manifest: `qagent context --write` writes `QUANTAGENT_CONTEXT_MANIFEST.json` with source files and budget stats.
- Relevance projection: context is selected per task instead of dumping every handoff file.

## Chat Transparency

`qagent chat` shows:

- context chars used / budget
- source filenames used
- latest handoff file
- token usage when the provider returns it

This makes hallucination easier to catch: if the answer cites something outside the displayed sources, treat it as unsupported.

## Run-Next Orchestration Output

`qagent run-next` is a safe advisory loop, not an experiment runner. Its JSON and Markdown outputs now separate chat-style review from machine-readable workflow routing:

- `next_action_queue.allowed_safe_actions`: read-only, audit, validation, reporting, or evidence-collection actions that can be queued now. Each item includes `owner_role` and `source`.
- `next_action_queue.blocked_material_actions`: experiments, P4 execution, strategy changes, data mutation, or unsupported result claims that must remain blocked. Each item includes `owner_role` and `source`.
- `next_action_queue.required_evidence`: hashes, validation results, dedup confirmations, consensus replies, or other artifacts required before a blocked material action can be reconsidered. Each item includes `owner_role` and `source`.
- `role_consensus`: verdict counts, per-role verdicts, shared safe actions, shared blockers, shared evidence needs, and per-role action counts.
- `role_conflicts`: structured disagreements such as verdict disagreement, approval versus blockers, or the same normalized action being classified as both allowed and blocked.

The three orchestration roles return structured fields directly:

```json
{
  "role": "researcher|auditor|data_engineer",
  "verdict": "APPROVE|NEEDS_WORK|REJECT",
  "summary": "...",
  "findings": [],
  "allowed_safe_actions": [],
  "blocked_material_actions": [],
  "required_evidence": [],
  "required_actions": []
}
```

These fields are intended for downstream automation. Markdown remains a human-readable report, while JSON is the source of truth for queue routing.
