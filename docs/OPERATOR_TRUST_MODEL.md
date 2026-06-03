# QuantAgent Operator Trust Model

This document adapts local-first operator and sandbox-policy concepts from
OpenClaw under its MIT license. See `docs/UPSTREAM_ATTRIBUTION.md` and the
OpenClaw MIT license in `upstream_refs/openclaw/LICENSE` for attribution.

## Positioning

QuantAgent is a personal or small-team quant research assistant. It is not a
multi-tenant security boundary between adversarial users. The default design is:

- one trusted operator or one trusted research team
- one local project workspace
- one set of local credentials, market data files, and research artifacts
- agents and tools that help the operator, not independent principals with
  separate ownership rights

If mutually untrusted people need to use QuantAgent, run separate OS users,
machines, containers, VMs, broker accounts, data roots, and QuantAgent projects.
Do not rely on session IDs, task IDs, chat history, or toolset names as security
boundaries.

## Trust Classes

QuantAgent should reason about callers and inputs using these classes:

- `owner_operator`: the local user who controls the project, terminal, desktop,
  API keys, and data files.
- `trusted_project_collaborator`: a human inside the same research boundary.
  They may contribute code and reports, but should not automatically gain broker
  or account authority.
- `local_agent`: a QuantAgent process launched by the operator. It is a helper
  inside the operator boundary, not a separate authority.
- `subagent_worker`: a delegated read/edit worker. It should inherit a smaller
  tool profile than the main agent and report its evidence.
- `model_output`: untrusted planning text. It can propose actions, but tools,
  policy, evidence gates, and operator approvals decide what happens.
- `external_content`: files, web text, copied prompts, PDFs, model-generated
  code, notebooks, and upstream repos. Treat as untrusted until inspected.
- `trusted_plugin_or_tool`: local code intentionally installed or enabled by the
  operator. Installing it adds it to the trusted computing base for that project.
- `broker_or_funds_surface`: any API, UI, script, or credential that can place
  orders, transfer funds, change account settings, or expose secrets. This is a
  protected surface even for otherwise trusted research tasks.
- `raw_market_data`: tick, Level2, raw, original, or vendor-delivered market
  data. This is read-mostly evidence and should not be mutated in place.

## Boundaries That Count

These are real QuantAgent boundaries:

- project root path containment for file tools
- raw/tick data mutation protection
- broker/account/funds/secret protection
- tool policy allow/ask/deny decisions
- explicit operator approval for write, desktop input, experiment, and shell
  escalation
- future OS/container sandbox filesystem and network isolation
- quant evidence gates before publishing PF, slippage, capacity, or P4 claims

These are not security boundaries by themselves:

- chat sessions
- task IDs
- subagent names
- memory rows
- toolset labels
- model roles or system prompts
- comments saying a tool is "safe" without enforcement
- deterministic fallback summaries

## Tool Policy Model

QuantAgent should keep three controls separate, following the OpenClaw pattern:

1. Runtime sandbox: where a tool runs and what host resources it can reach.
2. Tool policy: which tools are available and whether each is allow, ask, or
   deny for the active profile.
3. Elevated execution: a narrow, explicit escape hatch for commands that must
   run outside the sandbox.

Current QuantAgent mostly implements tool policy and command/path guards. It
does not yet provide a hard OS sandbox. Documentation, UI, and doctor checks
should keep saying this plainly.

Recommended default profiles:

- `strict`: read-only evidence mode. Allow status, context, audit, validate,
  registry, file read/search, memory search, desktop screenshot/grid. Deny
  shell writes, desktop input, account actions, raw data mutation, and
  experiments.
- `project`: default local research mode. Allow low-risk read/evidence tools.
  Ask for source edits, memory writes, guarded shell, desktop screenshots with
  persistent artifacts, and experiment runs. Deny desktop input and broker/funds
  surfaces unless the operator explicitly changes profile.
- `operator`: trusted local mode. Allow project-contained edits and selected
  desktop actions after visible confirmation. Still deny broker/funds actions,
  secret exfiltration, raw data mutation, and broad host destruction.
- `break_glass`: temporary owner-only mode for maintenance. It must be logged,
  time-limited, and never enabled by model output alone.

`deny` wins over `allow`. If an allowlist exists for a profile, tools not on the
allowlist should be unavailable. A tool policy decision should not pretend to
make shell read-only; only a real sandbox, structured file APIs, or argumentized
tools can enforce that.

## Quant-Specific Protected Assets

QuantAgent has domain assets that generic coding agents do not understand well:

- raw tick and Level2 data
- vendor data license files and download scripts
- broker API keys, trading passwords, account exports, and order logs
- P4 real-execution evidence
- PF, capacity, slippage, and sample-cleanliness claims
- research notebooks and scripts that generate production-facing conclusions

The safe default is to read and derive, not mutate originals. Any tool that
touches protected assets should write a derived artifact with provenance, hash,
source path, timestamp, and command/tool metadata.

## Desktop and Screen Control

Desktop tools are powerful because they act through the operator's live UI. A
click or hotkey can trigger broker actions, payments, account changes, data
uploads, or irreversible app state changes.

Policy should distinguish:

- screen observation: screenshot, window title, accessibility tree, OCR
- screen planning: locating a button or field
- screen input: click, type, hotkey, drag
- sensitive screen input: broker, password manager, terminal sudo, data vendor
  account, cloud console, email send, file delete dialogs

Observation can be allowed in `strict` or `project` when local privacy is
acceptable. Input should default to ask or deny unless the operator has selected
an explicit desktop profile and the target app/window is visible in the action
summary.

## Security Report Triage

A QuantAgent security issue should show a real boundary bypass, not only that a
trusted operator can use a local feature. High-signal reports should include:

- affected version or commit
- exact path, function, or command surface
- reproducible steps
- the trust boundary crossed
- demonstrated impact on data integrity, account/funds safety, secrets, host
  state, or research credibility
- proposed remediation if practical

Usually not a security bug by itself:

- prompt injection that only changes model text and does not bypass tool policy
- a trusted operator intentionally running a local shell command
- malicious behavior from a plugin the operator intentionally installed
- multiple adversarial users sharing one project and expecting isolation
- a session/memory/task visibility surprise without a policy or sandbox bypass
- command-risk detection parity gaps that do not bypass an enforced gate

These can still be useful hardening issues, but they should be labeled as such.

## Operational Guidance

For personal research:

- keep QuantAgent local and project-scoped
- keep raw market data read-only
- keep broker credentials outside the project when possible
- use `strict` for unknown code, copied prompts, upstream repos, and generated
  scripts
- use `project` for normal read/edit/test research
- reserve `operator` for visible local desktop assistance

For a shared research team:

- use a dedicated machine, VM, or OS user for the shared agent
- use dedicated broker/data accounts for that boundary
- do not mix personal browser profiles or password managers with shared agents
- log approvals, experiments, and generated conclusions
- separate production trading from research automation

