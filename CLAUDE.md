# OpenMako Local Agent Notes

This file is for local coding-agent behavior inside this repository. It is not a public capability claim.

Current public position:

- OpenMako is a focused evidence harness for coding-agent repair runs.
- The public v0.1 proof is the focused learning-effect gate linked from
  `README.md` and issue #1.
- Claims about broader agent-runtime, desktop-control, quant, or benchmark
  behavior require current tests and public evidence before they can be used in
  launch copy.

Core rules:

- Prefer deterministic commands and file evidence before model conclusions.
- Keep edits scoped to the requested files and explain any scope expansion.
- Do not claim tests passed unless the exact command ran in the current
  workspace.
- Do not copy closed-source code, prompts, endpoints, constants, or proprietary
  strings from commercial coding-agent tools.
- Treat open-source upstream references as attribution-bound sources, not as
  proof of OpenMako capability.

Current public quality gate:

```bash
python3 -m pytest -p no:cacheprovider \
  tests/test_agent_planner_contract.py::AgentPlannerContractTest::test_planner_no_seed_repairs_package_level_http_manifest_js_module \
  tests/test_external_benchmark_multimodule_regression.py::ExternalBenchmarkMultimoduleRegressionTest::test_package_level_http_manifest_js_trajectory_skill_reuses_on_hidden_tasks \
  tests/test_public_metadata.py \
  -q
```
