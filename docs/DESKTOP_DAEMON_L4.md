# Desktop Daemon L4 Contract

Date: 2026-05-26

Scope: `mako desktop daemon` for the bounded single-goal loop and
`mako desktop-daemon` for the operator-facing queue/control plane. This
document describes the current contract and the L4 target without claiming
unimplemented autonomy.

## Current Level

Current status: L3 alpha.

Implemented behavior:

- Observe: captures screenshot-backed desktop state and merges AX, OCR, SoM,
  and optional grid data into desktop tokens.
- Decide: emits one deterministic next action from the current tokenization.
- Act: executes at most one desktop side-effect action per step.
- Verify: recaptures state after side effects and checks typed-text visibility
  or token-target progress.
- Stop: checks the STOP file before every daemon step.
- Trace: writes state, query events, and trajectory records.
- Fail closed: high-risk goals, stale targets, missing observation fences,
  repeated loops, failed actions, and failed semantic verification stop or block
  the run before continuing.

Not L4 yet:

- The decider is deterministic and narrow.
- Recovery is mostly stop/fail instead of alternate-plan replanning.
- Multi-app regression fixtures are not yet broad enough.
- Multi-agent delegation through the desktop ledger is planned, not current
  daemon behavior.

## L4 Standard

L4 means OpenClaw-class local desktop autonomy:

- robust multi-app workflows, not one narrow click/type/search path;
- long-running tasks with explicit budgets, STOP fuse, and replayable state;
- failure analysis from query events, trajectory, screenshots/tokens, and
  autopsy output;
- strong permission gates before desktop side effects;
- regression evals covering multi-step desktop workflows and poison cases;
- planned: subagents bound to the same token, decision, permission, and
  trajectory ledger.

L4 is not a claim until the daemon passes broad multi-app evals with recovery
behavior, not only deterministic happy paths.

## Permission Model

`mako desktop daemon` and `mako desktop-daemon run` are dry-run by default.

Desktop side effects require all three gates:

- `--execute`: allow the daemon to perform side effects instead of previewing.
- `--reviewed`: operator confirms the run was reviewed.
- `--allow-actions`: allow control actions such as click, move, type, hotkey,
  open, activate, grid-click, and som-click.

If any required gate is missing, the daemon records a skipped action with
`needs` and does not call the desktop execution primitive. It does not ask for
permission mid-run.

Host permissions are external to the CLI:

- Screen capture requires the operating system to allow screenshot access.
- AX state and control require Accessibility permission on macOS.
- Missing OS permission is treated as observation/tokenization/action failure;
  the daemon should pause or fail closed rather than invent screen state.

## STOP File

Default STOP file:

```text
.quantagent/desktop/agent/STOP
```

The daemon resolves relative STOP paths under the project root. If the STOP file
exists before a step, the daemon stops before tokenization or action and writes
terminal state. A custom STOP path can be passed by the runtime API; CLI surface
may expose more STOP routing later.

## Artifacts

The daemon writes under:

```text
.quantagent/desktop/intelligence/daemon/
```

Current artifacts:

- `latest_state.json`: terminal or running state, recent records, results, goal,
  and STOP file path.
- `query_events.jsonl`: query lifecycle and tool events for the daemon run.
- `trajectory.jsonl`: observation, decision, stale-check, act, and verify
  records.
- `openmako-autopsy.md`: written for non-ok terminal exits such as tokenization
  failure, blocked decision, stale target, action failure, verification failure,
  loop detection, or STOP-file stop.

Permission-gate dry-run skips are ok/skipped results, so they write state,
query events, and trajectory but do not currently write an autopsy.

## Poison Tests

The desktop daemon poison surface is tracked by
`tests/test_desktop_night_daemon.py`.

Covered cases include:

- STOP file present before first observation.
- Missing `--execute`, `--reviewed`, or `--allow-actions` prevents side effects.
- Screenshot/tokenization failure pauses with autopsy.
- Desktop action failure pauses with autopsy.
- Semantic verification failure pauses with autopsy.
- High-risk payment, trading, credential, destructive, and message-sending goals
  are blocked before desktop action.
- Loop detector blocks repeated action/signature cycles.
- Step-budget exhaustion returns explicit status.
- State, query events, and trajectory artifacts exist.
- Stale target and missing observation-fence paths are part of the eval pack.

The eval pack is necessary but not sufficient for L4. The L4 gate requires
broader multi-app fixtures and recovery tests that prove alternate targeting,
alternate observation modes, and replayable failure analysis.
