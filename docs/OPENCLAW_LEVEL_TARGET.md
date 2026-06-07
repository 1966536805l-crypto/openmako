# OpenMako Capability Target

Internal planning note. This is not the current public v0.1 capability claim; the current public proof command is `./scripts/public_review_gate.sh`.

North star: reach OpenClaw-class local agent capability.

Current project target is not SWE-bench score chasing. The target is a fast local desktop agent that can:

- observe the screen and local workspace,
- plan the next action,
- control the desktop through reviewed, traceable tools,
- verify whether the action worked,
- diagnose failures through query events, trajectory, and evidence trails,
- run unattended within explicit safety fuses and task budgets.

Working level scale:

- L0: scripts and static reports only.
- L1: CLI tools with logs and narrow automation.
- L2: traceable agent workflow, policy gates, tests, autopsy reports.
- L3: closed-loop local desktop agent for simple tasks: observe, act, verify, recover.
- L4: OpenClaw-class agent: robust multi-app desktop autonomy, long-running tasks, replayable failure analysis, strong safety gates, multi-agent delegation, regression evals.
- L5: production-grade operator: reliable overnight execution across real workflows with monitoring, rollback, and measurable task success.

Current assessment: L3 alpha.

Reason: OpenMako now has trace/autopsy/policy/test infrastructure, direct desktop-agent control, an overnight runner, and a first desktop intelligence loop: tokenize merges screenshot/AX/OCR/SoM/grid into structured state with observation ids and screen hashes, decide emits one deterministic action, and daemon runs observe-tokenize-decide-act-verify with STOP-file, skip markers, stale-target checks, semantic typed-text verification, target-change verification, and a loop detector. It is not L4 because the decider is still deterministic and narrow, recovery is mostly stop/fail rather than replan, and multi-app regression evals are not yet robust.

L3 hardening contract:

Build a desktop takeover loop with this contract:

1. observe: screenshot plus accessibility/ocr/som state.
2. decide: deterministic local plan first, model plan only when needed.
3. act: one reviewed desktop action.
4. verify: compare post-action state against expected condition.
5. recover: retry, alternate tool, or stop with autopsy.

Passing L3 means a real local task can run for at least 20 steps with trace, screenshots, tokenization records, STOP fuse, and failure autopsy without manual command stitching.

Next gate to reach L4:

1. broaden decider coverage beyond deterministic click/type/search/open flows.
2. broaden semantic verification beyond type/click target changes into app/window/title/URL/file assertions.
3. add recovery actions: retry alternate target, switch AX/OCR/SoM mode, or stop with an autopsy.
4. add multi-app regression fixtures that replay 20+ step desktop workflows.
5. bind subagents to desktop tasks only through the same token/decision/permission ledger.
