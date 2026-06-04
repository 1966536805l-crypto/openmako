# Upstream Attribution

Attribution note. This is not the current public v0.1 capability claim; the
current public proof is the focused learning-effect gate linked from `README.md`
and issue #1.

QuantAgent borrows and adapts architecture ideas from permissively licensed
agent projects. Code in this repository is kept small and local-first, but some
modules intentionally mirror upstream patterns.

## NousResearch/hermes-agent

- Repository: https://github.com/NousResearch/hermes-agent
- License: MIT
- Local license copy: `upstream_refs/hermes-agent/LICENSE`
- Direct vendored license copy: `third_party/hermes/LICENSE`
- Direct vendored skill sources: `third_party/hermes/skills/**`
- Packaged vendored skill sources: `quantagent/vendor/hermes/skills/**`
- Packaged vendored license copy: `quantagent/vendor/hermes/LICENSE`
- Useful patterns adopted: SQLite/FTS memory store, toolset grouping, trajectory
  compression strategy, skills-oriented agent workflows.
- Substantial project-native adaptations:
  - `quantagent/vendor/hermes/iteration_budget.py`,
    `quantagent/vendor/hermes/retry_utils.py`, and
    `quantagent/vendor/hermes/error_classifier.py`: upstream-derived MIT
    vendor modules retained under a vendor namespace with local attribution and
    license notice. Use these only through an explicit adapter boundary.
  - `quantagent/error_classifier.py`: OpenMako-facing API error classifier
    derived from the Hermes taxonomy and recovery-action pipeline, with local
    exception-audit integration and OpenMako-specific provider cases.
  - `quantagent/retry_utils.py`: OpenMako-facing retry helpers derived from
    Hermes jittered backoff behavior, extended with `RetryFuse`,
    retry-after parsing, and watchdog-friendly task attribution.
  - `quantagent/safety.py`: hardline denial patterns for catastrophic host
    commands, adapted from Hermes dangerous-command approval guards.
  - `quantagent/tool_output.py` and `quantagent/tools.py`: oversized tool
    output persistence with bounded previews, adapted from Hermes tool result
    storage and output budget patterns.
  - `quantagent/ansi_strip.py`: ANSI/control-sequence stripping before command
    output is exposed to model context.
  - `quantagent/hermes_trajectory_format.py`: Python-native ShareGPT JSONL
    trajectory export adapted from Hermes `agent/trajectory.py` and
    `agent/agent_runtime_helpers.py` formatting ideas for completed runs,
    failed runs, role mapping, tool XML blocks, and explicit reasoning blocks.
  - `quantagent/tool_stats.py`: project-native adaptation of the
    `batch_runner.py` `tool_stats` / `tool_error_counts` normalization idea,
    keeping stable zero-filled tool maps for eval and autopsy output without
    copying the upstream batch runner.
  - `quantagent/iteration_budget.py`: Python-native tiny iteration budget for
    daemon/decider loops, adapted from Hermes `agent/iteration_budget.py`.
  - `quantagent/tool_result_classification.py`: small tool-result landing
    classifier adapted from Hermes `agent/tool_result_classification.py` for
    distinguishing successful `write_file` / `patch` payloads from malformed or
    error payloads.
  - `quantagent/hermes_learning.py` and `quantagent/skill_pipeline.py`:
    OpenMako-native proposal/approval/eval/rollback flow inspired by Hermes
    learning and skill-management mechanics. This is a behavior rewrite; failed
    experience becomes proposal evidence and is not silently installed.
  - `quantagent/skills.py`: OpenMako skill loader for packaged Hermes skill
    documents, keeping the copied skill text behind a vendor/source boundary.

## openclaw/openclaw

- Repository: https://github.com/openclaw/openclaw
- License: MIT
- Local license copy: `upstream_refs/openclaw/LICENSE`
- Direct vendored snippets: `third_party/openclaw/selected/*.js`
- Direct vendored license copy: `third_party/openclaw/LICENSE`
- Useful patterns adopted: local-first gateway philosophy, channel/session
  separation, operator trust model, sandbox-aware tool policy, plugin/skills
  boundary discipline.
- Substantial project-native adaptations:
  - `quantagent/openclaw_runtime_utils.py`: Python ports of selected MIT
    runtime utilities for prompt/plain-text sanitization, timeout parsing,
    backoff calculation, session id validation, balanced JSON extraction,
    JSON Pointer reads, shell-like argument splitting, secret masking, and
    compact token usage display. Later ports from the same selected bundle add
    console output sanitization, finite-number and strict-integer coercion,
    human-list formatting, duration/relative-time display, and compact string
    entry sampling.
  - `quantagent/input_provenance.py` and `quantagent/sessions.py`: inter-session
    provenance labels that prevent routed/internal text from masquerading as
    direct user instruction.
  - `quantagent/operator_auth.py` and `quantagent/sandbox_policy.py`: Python-native
    adaptations of sender identity checks, channel allow-from command gating,
    and child-process environment secret and unsafe value filtering inspired by OpenClaw
    `src/channels/allow-from.ts`, `src/channels/command-gating.ts`,
    `src/channels/sender-identity.ts`, and
    `src/agents/sandbox/sanitize-env-vars.ts`.
  - `quantagent/control_plane_policy.py`: Python-native adaptation of
    `src/gateway/control-plane-rate-limit.ts` and `src/gateway/method-scopes.ts`
    fixed-window control-plane write limiting and explicit read/write/admin/
    pairing method scopes.
  - `quantagent/daemon_supervisor.py`: Python-native foreground process
    supervisor adapted from the run-record/state-machine ideas in
    `src/process/supervisor/types.ts`, `src/process/supervisor/registry.ts`,
    and `src/process/supervisor/supervisor.ts`; no TypeScript runtime code is
    copied.
  - `quantagent/desktop_intelligence.py` and `docs/DESKTOP_DAEMON_L4.md`:
    Python-native desktop daemon contract inspired by OpenClaw session/control
    separation and safety-gated local automation patterns. Current behavior is
    L3 alpha; broader L4 multi-app autonomy and delegation are planned, not
    claimed.
  - `quantagent/mcp_runtime.py`, `quantagent/plugin_runtime.py`, and
    `quantagent/cli.py`: OpenMako-native behavior rewrite of OpenClaw-style MCP
    catalog/session boundaries, plugin install state snapshots, schema drift
    detection, and short machine-readable CLI reports. No OpenClaw TypeScript
    runtime is copied into these modules.

When code is copied substantially from an upstream project, keep the relevant
copyright notice and license text with the copied portion. Prefer small,
project-native adaptations when a direct copy would import a large framework
or a mismatched runtime.

## paul-gauthier/aider

- Repository: https://github.com/paul-gauthier/aider
- License: Apache-2.0
- Direct vendored source: `third_party/aider/aider/repomap.py`
- Direct vendored license copy: `third_party/aider/LICENSE.txt`
- Useful patterns to port: repository map ranking, symbol-aware context
  selection, edit loop context budgeting.
- Mako-native port: `quantagent/repo_map.py` ports the definition/reference
  graph ranking and weighted PageRank idea into a stdlib implementation that
  boosts related code context without importing Aider's runtime dependencies.

## SWE-agent/SWE-agent

- Repository: https://github.com/SWE-agent/SWE-agent
- License: MIT
- Direct vendored source: `third_party/swe_agent/sweagent/environment/swe_env.py`
- Direct vendored license copy: `third_party/swe_agent/LICENSE`
- Useful patterns to port: reproducible task environment, command/result
  observation, patch/test lifecycle for issue-to-fix work.

## vnpy/vnpy

- Repository: https://github.com/vnpy/vnpy
- License: MIT
- Direct vendored sources:
  - `third_party/vnpy/vnpy/trader/constant.py`
  - `third_party/vnpy/vnpy/trader/object.py`
  - `third_party/vnpy/vnpy/trader/event.py`
- Direct vendored license copy: `third_party/vnpy/LICENSE`
- Useful patterns to port: exchange/order/direction/status enums, account,
  position, order, trade, tick, and bar event object shapes.
- Mako-native port: `quantagent/broker_gateway.py` normalizes broker, account,
  fill, order, and position evidence into project-native dataclasses.

## hummingbot/hummingbot

- Repository: https://github.com/hummingbot/hummingbot
- License: Apache-2.0
- Direct vendored sources:
  - `third_party/hummingbot/hummingbot/core/data_type/common.py`
  - `third_party/hummingbot/hummingbot/core/data_type/in_flight_order.py`
- Direct vendored license copy: `third_party/hummingbot/LICENSE`
- Useful patterns to port: connector/order lifecycle status, in-flight order
  accounting, exchange adapter state reconciliation.
- Mako-native port: `quantagent/broker_gateway.py` uses these order lifecycle
  ideas for execution evidence before `live_ready`.

## modelcontextprotocol/python-sdk

- Repository: https://github.com/modelcontextprotocol/python-sdk
- License: MIT
- Direct vendored sources:
  - `third_party/mcp_python_sdk/src/mcp/types/_types.py`
  - `third_party/mcp_python_sdk/src/mcp/server/mcpserver/tools/base.py`
  - `third_party/mcp_python_sdk/src/mcp/server/mcpserver/tools/tool_manager.py`
  - `third_party/mcp_python_sdk/src/mcp/shared/tool_name_validation.py`
- Direct vendored license copy: `third_party/mcp_python_sdk/LICENSE`
- Useful patterns to port: typed protocol records, tool declaration shape,
  tool-name validation, and server tool-manager boundaries.
- Mako-native port: `quantagent/mcp_tool_manager.py` ports the MIT Tool,
  ToolManager, argument schema, call wrapper, and tool-name validation into a
  lightweight standard-library implementation.

## unionai-oss/pandera

- Repository: https://github.com/unionai-oss/pandera
- License: MIT
- Direct vendored sources:
  - `third_party/pandera/pandera/api/base/checks.py`
  - `third_party/pandera/pandera/api/base/schema.py`
  - `third_party/pandera/pandera/errors.py`
  - `third_party/pandera/pandera/dtypes.py`
- Direct vendored license copy: `third_party/pandera/LICENSE.txt`
- Useful patterns to port: dataframe schema contracts, checks, typed dtypes,
  and structured validation failures.
- Mako-native port: `quantagent/quant_expectations.py` implements lightweight
  CSV expectation suites without requiring pandas.

## great-expectations/great_expectations

- Repository: https://github.com/great-expectations/great_expectations
- License: Apache-2.0
- Direct vendored sources:
  - `third_party/great_expectations/great_expectations/expectations/core/expect_column_values_to_not_be_null.py`
  - `third_party/great_expectations/great_expectations/expectations/core/expect_column_values_to_be_between.py`
  - `third_party/great_expectations/great_expectations/expectations/core/expect_column_values_to_be_dateutil_parseable.py`
  - `third_party/great_expectations/great_expectations/expectations/core/expect_column_values_to_be_unique.py`
  - `third_party/great_expectations/great_expectations/expectations/core/expect_table_columns_to_match_set.py`
  - `third_party/great_expectations/great_expectations/expectations/expectation_configuration.py`
- Direct vendored license copy: `third_party/great_expectations/LICENSE`
- Useful patterns to port: expectation naming, validation result semantics,
  column parseability, uniqueness, range checks, and table column-set checks.
- Mako-native port: `quantagent/quant_expectations.py` applies these ideas to
  A-share market bars, minute bars, ticks, fills, slippage, capacity, and
  position evidence.
