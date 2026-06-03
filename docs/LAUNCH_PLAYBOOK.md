# OpenMako Launch Playbook

Goal: convert OpenMako from a strong local codebase into a repo that a developer can understand in 30 seconds, run in 5 minutes, and share after one successful demo.

## Primary Hook

```text
OpenMako is a local-first, auditable agent runtime for serious coding and data work.
```

The shareable proof is:

```bash
mako doctor
```

The doctor score is the product memory hook. It compresses runtime health, permission hygiene, plugin state, sandboxing, task registry, evidence, and model-error readiness into one surface.

## Conversion Funnel

| Stage | Target | Required artifact |
| --- | --- | --- |
| 30 seconds | Understand why OpenMako exists | README hero, screenshot, comparison table |
| 2 minutes | Install and run health check | `pipx install open-mako` or editable install plus `mako onboard` |
| 5 minutes | Produce first useful artifact | `mako agent ...`, `mako query-events`, `mako runtime status` |
| 15 minutes | Inspect trust surface | doctor output, runtime ledger, task graph, approval/tool logs |
| 1 hour | Report useful feedback | issue templates, troubleshooting docs, reproducible demo repo |

## Required Before Public Launch

1. Package install path:
   - `pipx install open-mako`
   - `python3 -m pip install -e .` for contributors

2. Onboarding path:
   - `mako onboard`
   - `mako doctor`
   - model auth status
   - next commands printed by the CLI

3. Demo path:
   - demo repo or fixture
   - terminal recording
   - one command that creates runtime/query artifacts

4. Trust path:
   - `SECURITY.md`
   - `CONTRIBUTING.md`
   - `docs/COMPARISON.md`
   - clean-room and upstream attribution docs

5. CI path:
   - Linux and macOS tests
   - `python3 -m unittest discover -s tests`
   - `python3 -m py_compile ...`
   - `mako doctor --json` smoke run

## README Rules

- First screen must not be a command encyclopedia.
- The first command block must be runnable.
- The strongest artifact is `mako doctor`; keep it above the fold.
- Long command lists move below the positioning section or into docs.
- Quant-specific details stay available but should not dominate the first screen.

## Launch Message

```text
I built OpenMako: a local-first agent runtime with doctor checks, task registry, evidence trails, plugin state, worktree isolation, and replayable tool logs.

It is for developers who want agents that can be inspected after they act.

Try:
  pipx install open-mako
  mako onboard
  mako doctor
  mako agent "audit this repo and propose a safe fix plan"
```

## Success Metrics

- Clone/install to `mako doctor`: under 2 minutes.
- Install to first agent artifact: under 5 minutes.
- README first-screen comprehension: under 30 seconds.
- Launch issue quality: users report concrete install/runtime feedback.
- Star conversion: visitors star after seeing doctor output or running demo, not after reading a feature list.
