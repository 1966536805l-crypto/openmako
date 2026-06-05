# OpenMako Agent Trend Radar

Last refreshed: 2026-06-05.

This is a source-linked planning map for deciding what OpenMako should build
next after v0.1. It is not proof that OpenMako already implements these
capabilities, and it is not evidence of external review, endorsement, stars, or
reposts.

## Source Signals

| Signal | Source | What is moving |
| --- | --- | --- |
| Self-improving skills and memory | `https://hermes-agent.nousresearch.com/docs/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-hermes-agent` | Hermes positions persistent memory, reusable skills, profiles, gateways, plugins, MCP, cron, provider switching, and worktree-style parallel runs as agent runtime primitives. |
| External-harness sessions | `https://docs.openclaw.ai/tools/acp-agents` | OpenClaw uses Agent Client Protocol sessions to spawn external coding harnesses as tracked background tasks, with explicit bind/thread modes and fail-clear model overrides. |
| Composable agent surfaces | `https://github.com/OpenHands/OpenHands` | OpenHands exposes the same agent core through SDK, CLI, local GUI, cloud, and enterprise surfaces, with integrations and permissions in the cloud product. |
| Terminal-first evaluation | `https://github.com/harbor-framework/terminal-bench` | Terminal-Bench evaluates agents in sandboxed terminal environments with task instructions, verifier scripts, oracle solutions, dataset versions, and leaderboard submission paths. |
| Cost and telemetry as benchmark output | `https://github.com/Vexp-ai/vexp-swe-bench` | SWE-bench-style harnesses increasingly report resolution rate together with cost, duration, token usage, turn counts, and unique wins. |
| Chained maintenance tasks | `https://arxiv.org/abs/2605.14415` | SWE-Chain evaluates release-level package upgrades where each transition inherits the agent's prior codebase. |
| Full-cycle autonomy | `https://arxiv.org/abs/2605.13139` | SWE-Cycle separates environment reconstruction, implementation, verification generation, and end-to-end full-cycle execution. |
| Correct-and-secure coding | `https://arxiv.org/abs/2509.22097` | SecureVibeBench combines functionality testing with static and dynamic security oracles for multi-file secure coding tasks. |
| Evolvable memory routines | `https://arxiv.org/abs/2602.02474` | MemSkill frames memory extraction, consolidation, pruning, and hard-case review as learnable skills. |

## OpenMako Development Bets

### 1. Evidence Ledger Before Broader Runtime

Hot projects are moving toward persistent sessions, background tasks, and
profiled memories. OpenMako should not jump straight to a full agent runtime
claim. The next public build should first make run evidence more durable:

- session id, parent id, task id, and tool invocation identity
- patch boundary and required-test proof
- terminal outcome and failed-at boundary
- exported JSON/JSONL for reviewers

Public claim boundary: this would improve audit durability, not prove broad
autonomous repair.

### 2. Skill Evolution With Reproducible Approval

Hermes-style skills and MemSkill-style memory evolution are high-signal, but
they are easy to fake. OpenMako should treat every new skill as a proposal until
it passes:

- one seen task
- one hidden variant
- patch-scope checks
- required tests
- explicit approved-learning record

Public claim boundary: this proves one gated learning-effect path, not general
self-improvement.

### 3. External Harness Adapter Without Runtime Overclaim

OpenClaw's ACP path shows demand for controlling external coding harnesses as
tracked sessions. OpenMako should start with an import/export adapter for
external run records before claiming live orchestration:

- Codex/Claude/OpenHands/SWE-agent transcript import shape
- normalized command, diff, and test events
- Evidence Court audit over supplied records
- clear unsupported fields when a transcript lacks command or diff proof

Public claim boundary: record auditing first, live multi-agent control later.

### 4. Benchmark Telemetry Beyond Pass/Fail

Vexp-style benchmark reporting makes cost, duration, and token usage part of
the result, not an afterthought. OpenMako should add optional telemetry fields
to run records:

- model/provider name
- input/output token counts
- duration and command count
- estimated cost when pricing is known
- missing-telemetry marker when it is not known

Public claim boundary: telemetry improves comparability, but does not improve
repair capability by itself.

### 5. Full-Cycle And Secure-Coding Gates

SWE-Cycle, SWE-Chain, Terminal-Bench, and SecureVibeBench all push beyond
single patch success. The safest OpenMako direction is a two-lane roadmap:

- maintenance lane: chained package upgrade records with inherited state
- security lane: correct-and-secure verdicts that require both tests and
  security oracles

Public claim boundary: these are future gates until code, fixtures, and CI
exist.

## Do Not Claim Yet

- Do not claim OpenMako is a Hermes, OpenClaw, OpenHands, SWE-agent, or
  Terminal-Bench replacement.
- Do not claim ACP, MCP orchestration, long-term memory, skill self-evolution,
  cloud agent execution, or secure-code benchmarking as current public v0.1
  capability.
- Do not use this trend radar as evidence of endorsement, external review,
  star traction, or repost traction.

## Current Build Target

The `run-metrics` evidence extension is already on `main`, so it should not be
listed as the next build target. The next concrete build target is an external
run-record adapter matrix for supplied transcripts:

- keep Codex, Claude, OpenHands, and SWE-agent imports as supplied-record
  adapters first
- normalize command, diff, test, duration, token, cost, and unsupported-field
  evidence into one Evidence Court record shape
- make every adapter fail closed when a transcript omits command, diff, or test
  proof
- add one fixture and one CLI smoke test per adapter before listing it as
  public-supported

Public claim boundary: this would improve cross-agent supplied-record audit
coverage, not prove live orchestration, ACP control, broad SWE-bench repair, or
external endorsement.
