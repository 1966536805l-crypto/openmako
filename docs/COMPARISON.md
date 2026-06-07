# OpenMako Comparison

Internal comparison note. This is not the current public v0.1 capability claim; the current public proof command is `./scripts/public_review_gate.sh`.

OpenMako is positioned as a local-first agent runtime, not as a direct replacement for every coding assistant.

## Summary

| Product class | Strongest default | OpenMako distinction |
| --- | --- | --- |
| Claude Code / Codex | Model quality, coding flow, tool use | Adds auditable local runtime records, doctor checks, task registry, evidence trails, and replayable tool logs |
| Cursor / Cline | IDE-native editing and approval loops | Keeps terminal-first operation with policy, task, plugin, and runtime health surfaces |
| OpenHands / Devin | End-to-end autonomous software tasks | Focuses on local inspectability, small reproducible agent runs, and operator-controlled handoff |
| Aider | Reliable git/diff-oriented patching | Adds task state, approvals, runtime SQLite, subagents, isolation reviews, and evidence gates |
| OpenClaw | Personal assistant runtime across channels | Narrows the problem to serious coding/data work and makes `doctor` the central trust primitive |

## Product Thesis

Most agents optimize for action. OpenMako optimizes for inspectable action.

The core promise:

```text
Run local agents with measurable readiness, recorded state, evidence-backed outputs, and recoverable tool paths.
```

## Where OpenMako Should Win

- Teams that need local agent runs with readable task state and audit records.
- Data and quant workflows where model text cannot be accepted without evidence.
- Repos where permission policy, tool logs, checkpoints, and runtime health matter.
- Operators who want a compact terminal runtime instead of a full hosted autonomous platform.

## Where OpenMako Should Not Compete First

- Pure IDE autocomplete.
- Consumer personal assistant chat.
- Fully hosted enterprise task execution.
- Multichannel messaging automation.

Those surfaces can come later. The first wedge is local engineering trust.

## Demo Metric

The project should be judged by this 5-minute path:

```bash
mako onboard
mako doctor
mako agent "audit this repo and propose a safe fix plan"
mako query-events --limit 20
```

If that path is fast, clear, and screenshot-worthy, the project has launch surface.
