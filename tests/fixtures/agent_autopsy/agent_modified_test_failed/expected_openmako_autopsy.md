# Fixture: agent modified code then tests failed

- source_agent: codex
- command: python3 -m unittest
- status: FAILED
- failure_class: verification_failed
- failed_at: query:post_tool shell (step 3)
- evidence_items: 12

## Timeline

- Q1 [query:query_start step=0 name=codex ok] Codex run started for a small calculator repair.
- Q2 [query:pre_tool step=1 name=read_files ok] Read calculator.py and tests/test_calculator.py before editing.
- Q3 [query:post_tool step=1 name=read_files ok] Read target files; no failing test output was captured before the edit.
- Q4 [query:pre_tool step=2 name=apply_patch ok] Apply patch to calculator.py.
- Q5 [query:post_tool step=2 name=apply_patch ok] Applied patch to calculator.py.
- Q6 [query:pre_tool step=3 name=shell ok] Run python3 -m unittest after the edit.
- Q7 [query:post_tool step=3 name=shell failed] python3 -m unittest failed with AssertionError: expected 2 got 1.
  reason: event failed error_kind=test_failure
- Q8 [query:stop_failure step=3 name=runtime failed] Stopped because validation failed after an agent edit.
  reason: terminal failure_class=verification_failed
- T1 [trajectory:action step=1 ok] Codex inspected calculator.py and tests/test_calculator.py before editing.
- T2 [trajectory:edit step=2 ok] Agent changed add(a, b) in calculator.py while trying to simplify the failing branch.
- T3 [trajectory:test step=3 failed] python3 -m unittest failed: AssertionError: expected add(1, 1) == 2, got 1.
  reason: trajectory event failed
- F1 [failure:failure_log failed] FAIL: test_add (tests.test_calculator.CalculatorTest.test_add) AssertionError: expected 2 got 1 command: python3 -m unittest
  reason: external failure log supplied

## Findings

- [terminal_failure_class] Trace ended with failure_class=verification_failed. evidence=Q8
  intercept: require targeted validation to pass before broadening or finalizing
  confidence: high
- [first_failed_event] First failed event was query:post_tool shell (step 3). evidence=Q7
  intercept: validate tool preconditions and expected output contract before dependent steps
  confidence: high
- [post_edit_validation_failure] A validation/test failure appeared after an edit was made. evidence=T3
  intercept: run patch-shape and targeted-test gates before accepting the edited state
  confidence: medium
- [external_failure_log] A caller-supplied failure log marks this run as failed; deeper cause attribution depends on trajectory/query evidence. evidence=F1
  intercept: capture query_events and trajectory for this external agent run before comparing behavior
  confidence: high

## Earlier Intercepts

- require targeted validation to pass before broadening or finalizing
- validate tool preconditions and expected output contract before dependent steps
- run patch-shape and targeted-test gates before accepting the edited state
- capture query_events and trajectory for this external agent run before comparing behavior

## Sources

- <fixture>/query_events.jsonl
- <fixture>/trajectory.jsonl
- <fixture>/failure.txt

## Middleware Trial

- Wrap external agents with `mako agent-autopsy --run -- <agent command>` to capture a failure timeline without replacing the agent.

## GitHub Action Trial

- Use `action.yml` to upload `openmako-autopsy.md` when an agent-generated CI run fails.

All conclusions above are deterministic from the supplied trace data; no model validity judgment was used.
