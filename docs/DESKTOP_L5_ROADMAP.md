# Desktop L5 Roadmap

Date: 2026-05-26

Current status: L3.7.

L5 is not "more desktop commands". L5 means the local desktop agent can run
overnight with bounded risk, recover from routine failures, and prove what
happened from replayable evidence.

## Gates

L4 gate:

- 30-60 minute desktop eval run.
- No process-level crash.
- STOP file stops before the next action.
- High-risk goals are blocked.
- Side effects require `--execute --reviewed --allow-actions`.
- Every non-ok terminal run writes state, query events, trajectory, and autopsy.

L5 gate:

- 6-8 hour eval run.
- Multi-app workflows.
- Recovery attempts are real and recorded, not only counted.
- Failure autopsies produce intercept rules.
- New actions check similar prior failures before execution.
- Score is computed from metrics, not operator vibes.

## Metrics

Minimum metrics for every eval run:

- `duration_minutes`
- `scenario_count`
- `success_count`
- `failure_count`
- `blocked_count`
- `stopped_count`
- `timeout_count`
- `crash_count`
- `side_effect_count`
- `manual_intervention_count`
- `recovery_attempt_count`
- `recovery_success_count`
- `autopsy_count`
- `missing_autopsy_count`

## Level Meaning

- L1: can describe desktop actions.
- L2: can dry-run deterministic desktop plans.
- L3: can execute bounded actions with review gates.
- L4: can pass a 30-60 minute local desktop eval without crashing or unsafe
  actions.
- L5: can pass an overnight multi-app eval with measured recovery and learning.

## Current Work

Implemented or in progress:

- `mako desktop-daemon`: queue/control plane.
- `mako desktop-eval`: CLI contract for L4/L5 eval runs.
- `desktop_daemon_core`: injectable loop for deterministic tests.
- `desktop_daemon_policy`: high-risk and side-effect gates.
- `desktop_daemon_evidence`: query events, trajectory, and autopsy helper.
- `desktop_learning`: planned autopsy-to-intercept feedback.
- `desktop_recovery`: planned deterministic recovery strategy selection.

The next hard target is `mako desktop-eval run --suite suite_l4
--duration-minutes 60`.
