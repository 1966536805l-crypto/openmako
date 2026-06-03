# Market Tool Copy Scan

Internal clean-room research note. This is not launch copy, not a public capability claim, and not permission to copy closed-source or license-incompatible code. The current public proof is the focused learning-effect gate linked from `README.md` and issue #1.

Scan date: 2026-05-24.

This is the practical copy map for Mako/QuantAgent. "Copy" here means one of:

- direct vendor: copy small source files/snippets with license and attribution
- clean-room port: copy behavior, UX, state shape, or workflow, then rewrite in
  project-native Python
- no code: observe product mechanics only

Do not ingest closed-source bundles or suspected private/leaked source. In
particular, do not read or copy `/Downloads/claude/src.zip`.

## License Gate

| Tool | Official Source | Branch Seen | License Seen | Copy Mode |
| --- | --- | ---: | --- | --- |
| Aider | https://github.com/paul-gauthier/aider | main | Apache-2.0 | direct vendor small Python pieces, or port repo-map/edit-loop ideas |
| Cline | https://github.com/cline/cline | main | Apache-2.0 | direct vendor small TS helpers if useful, mostly port permission UX |
| Roo Code | https://github.com/RooVetGit/Roo-Code | main | Apache-2.0 | direct vendor small TS helpers if useful, mostly port modes/auto-approval |
| opencode | https://github.com/sst/opencode | dev | MIT | direct vendor small runtime helpers, port TUI/provider/session ideas |
| Continue | https://github.com/continuedev/continue | main | Apache-2.0 | direct vendor small config/schema pieces, port context providers |
| SWE-agent | https://github.com/SWE-agent/SWE-agent | main | MIT | direct vendor small harness/eval utilities, port issue-to-patch workflow |
| vn.py | https://github.com/vnpy/vnpy | master | MIT | direct vendor small trading constants/adapters, port broker gateway ideas |
| Zipline | https://github.com/quantopian/zipline | master | Apache-2.0 | direct vendor small calendar/data abstractions if still useful |
| Hummingbot | https://github.com/hummingbot/hummingbot | master | Apache-2.0 | direct vendor small connector abstractions, port exchange gateway ideas |
| OpenAI Codex | https://github.com/openai/codex | main | Apache-2.0 | direct vendor small CLI/runtime helpers, port task/session ergonomics |
| Goose | https://github.com/block/goose | main | Apache-2.0 | direct vendor small extension/runtime helpers, port desktop-local agent UX |
| MCP Python SDK | https://github.com/modelcontextprotocol/python-sdk | main | MIT | direct vendor small protocol/schema helpers, port MCP server/client contracts |
| MCP TypeScript SDK | https://github.com/modelcontextprotocol/typescript-sdk | main | MIT/Apache transition notice | direct vendor only after per-path notice check |
| LangGraph | https://github.com/langchain-ai/langgraph | main | MIT | direct vendor small graph/state helpers, port durable agent graph design |
| LangChain | https://github.com/langchain-ai/langchain | master | MIT | direct vendor small splitters/loaders if useful, port tool abstractions |
| LlamaIndex | https://github.com/run-llama/llama_index | main | MIT | direct vendor small indexing/retrieval utilities, port document index patterns |
| Haystack | https://github.com/deepset-ai/haystack | main | Apache-2.0 | direct vendor small pipeline component ideas, port RAG pipeline contracts |
| Semantic Kernel | https://github.com/microsoft/semantic-kernel | main | MIT | direct vendor small planning/plugin abstractions, port function registry ideas |
| PydanticAI | https://github.com/pydantic/pydantic-ai | main | MIT | direct vendor small typed-agent schemas, port structured result patterns |
| crewAI | https://github.com/crewAIInc/crewAI | main | MIT-like notice | inspect exact terms per file before direct copy |
| FastMCP | https://github.com/jlowin/fastmcp | main | Apache-2.0 | direct vendor small MCP server helpers, port tool declaration ergonomics |
| Great Expectations | https://github.com/great-expectations/great_expectations | develop | Apache-2.0 | direct vendor small expectation ideas, port data contract vocabulary |
| Pandera | https://github.com/unionai-oss/pandera | main | MIT | direct vendor small schema ideas, port dataframe contract patterns |
| MLflow | https://github.com/mlflow/mlflow | master | Apache-2.0 | direct vendor small tracking model ideas, port experiment artifact registry |
| DVC | https://github.com/iterative/dvc | main | Apache-2.0 | direct vendor small data-version ideas, port dataset hash/lineage workflow |
| Qlib | https://github.com/microsoft/qlib | main | MIT | direct vendor small quant data abstractions, port alpha/research workflow ideas |
| OpenHands | https://github.com/All-Hands-AI/OpenHands | main | mixed notice in root license | inspect per-path before any direct copy |
| NautilusTrader | https://github.com/nautechsystems/nautilus_trader | develop | LGPL-3.0 | clean-room port only unless isolated as external dependency |
| Backtrader | https://github.com/mementum/backtrader | master | GPL-3.0 | no direct code copy |
| Freqtrade | https://github.com/freqtrade/freqtrade | develop | GPL-3.0 | no direct code copy |
| vectorbt | https://github.com/polakowo/vectorbt | master | Commons Clause condition | no direct code copy for this project |
| Open Interpreter | https://github.com/OpenInterpreter/open-interpreter | main | AGPL-3.0 | no direct code copy |
| AutoGen | https://github.com/microsoft/autogen | main | attribution notice in root license | inspect carefully; prefer clean-room design port |
| RQAlpha | https://github.com/ricequant/rqalpha | master | custom Chinese license notice | no direct code copy unless terms are reviewed |
| Claude Code | closed product | n/a | proprietary | product-mechanics clean-room only |
| Cursor/Windsurf/Devin/Copilot agent | closed products | n/a | proprietary | product-mechanics clean-room only |

## Highest-Value Mechanisms To Study Next

1. **Aider repo map and diff loop**
   - What to copy: repository symbol map, ranked context, patch/test/repair loop.
   - Mako landing: `quantagent/context_engine.py`, `quantagent/edit_loop.py`,
     `quantagent/repo_map.py`.
   - Why it matters: this raises code-edit quality immediately; fewer blind
     edits, better file selection, better repair loops.

2. **SWE-agent sandbox task harness**
   - What to copy: issue spec, environment contract, command observation,
     patch artifact, test result classification.
   - Mako landing: `quantagent/sandbox_runner.py`,
     `quantagent/task_runtime.py`, `mako sandbox run`.
   - Why it matters: turns "agent tried something" into a reproducible
     experiment with logs and pass/fail evidence.

3. **Cline/Roo permission and mode UX**
   - What to copy: per-tool allow/ask/deny, custom modes, auto-approval
     boundaries, browser/terminal/editor affordances.
   - Mako landing: `quantagent/permissions.py`,
     `quantagent/tool_policy.py`, `mako permissions`.
   - Why it matters: Mako needs to feel controllable before it gets more
     autonomous.

4. **Continue context providers**
   - What to copy: named context providers, rule files, prompt fragments,
     workspace indexing boundaries.
   - Mako landing: `quantagent/context_refs.py`,
     `quantagent/context_engine.py`, `mako context --ref`.
   - Why it matters: users should be able to say "use docs/tests/logs" and get
     deterministic context, not random repo scraping.

5. **opencode provider/session/runtime model**
   - What to copy: provider abstraction, session records, TUI-friendly event
     stream, tool-call normalization.
   - Mako landing: `quantagent/runtime_store.py`,
     `quantagent/provider_registry.py`, `quantagent/event_stream.py`.
   - Why it matters: this makes model/provider switching and audit replay
     boring, which is exactly what agent infrastructure needs.

6. **vn.py/Hummingbot broker connector shape**
   - What to copy: gateway naming, order/trade/account/position event shapes,
     adapter lifecycle, reconnect patterns.
   - Mako landing: `quantagent/broker_gateway.py`,
     `quantagent/quant_execution_gate.py`,
     `quantagent/quant_data_adapter.py`.
   - Why it matters: this is the shortest path from research evidence to
     live-ready execution evidence.
   - Status: first Mako-native normalization layer landed in
     `quantagent/broker_gateway.py` and is wired into `quant execution-gate`.

7. **MCP SDK / FastMCP protocol layer**
   - What to copy: typed MCP schemas, server/client lifecycle, tool declaration
     ergonomics, transport tests.
   - Mako landing: `quantagent/mcp_runtime.py`,
     `quantagent/mcp_gateway.py`, `quantagent/tool_manifest_v2.py`.
   - Why it matters: Mako should treat local quant data adapters and broker
     adapters as first-class MCP tools, not ad hoc CLI wrappers.
   - Status: MCP Python SDK protocol/tool-manager snippets are vendored under
     `third_party/mcp_python_sdk`.

8. **LangGraph / PydanticAI durable typed agents**
   - What to copy: graph state, typed outputs, retry edges, event streams.
   - Mako landing: `quantagent/task_graph.py`,
     `quantagent/result_schema.py`, `quantagent/orchestrator.py`.
   - Why it matters: it turns multi-step quant work into resumable typed state
     machines instead of long prompt chains.

9. **Great Expectations / Pandera data contracts**
   - What to copy: expectation vocabulary, dataframe schema contracts, failure
     reports, sample previews.
   - Mako landing: `quantagent/quant_data_contract.py`,
     `quantagent/quant_data_adapter.py`.
   - Why it matters: the local 300G data layer needs deterministic schema and
     freshness checks before alpha tests matter.
   - Status: selected Pandera and Great Expectations checks are vendored under
     `third_party/pandera` and `third_party/great_expectations`; the Mako-native
     runner landed in `quantagent/quant_expectations.py`.

10. **MLflow / DVC evidence lineage**
    - What to copy: run metadata, artifact registry, dataset hash lineage,
      parameter/result tracking.
    - Mako landing: `quantagent/evidence_ledger.py`,
      `quantagent/experiment_runner.py`, `quantagent/runtime_store.py`.
    - Why it matters: every PF/live-ready answer should point to exact inputs,
      params, artifacts, and hashes.

11. **Qlib quant research workflow**
    - What to copy: data-provider shape, alpha/research workflow, calendar and
      instrument abstractions.
    - Mako landing: `quantagent/quant_data_adapter.py`,
      `quantagent/quant_run_gate.py`, `quantagent/quant_bench.py`.
   - Why it matters: Qlib-like structure is a strong fit for A-share alpha
     research, while Mako keeps stricter leakage/live gates.

12. **Local A-share data-provider sampling**
    - What to copy: Qlib-style provider boundary and data-bundle access shape,
      but with local zip/7z streaming instead of database ingestion.
    - Mako landing: `quantagent/quant_data_sample.py`,
      `quantagent/quant_expectations.py`.
    - Why it matters: this is the bridge from the user's real 2061 daily,
      minute K, and tick trade data into reproducible evidence files.
    - Status: `mako quant data-sample` streams single-code samples from daily
      market zip, minute K zip, and tick 7z without full extraction.

## Quant-Specific Copy Priority

For the quant product, the best order is:

1. vn.py event shapes and gateway lifecycle, rewritten into Mako execution
   evidence files.
2. Hummingbot connector lifecycle ideas, rewritten as broker/exchange adapters.
3. NautilusTrader order/event model, clean-room only, as the target standard for
   backtest/live parity.
4. Zipline bundle/calendar/data portal ideas for deterministic historical data
   loading.

Avoid direct GPL/Commons-Clause ingestion. It is not worth poisoning the codebase
when the useful parts can be rewritten from public behavior and docs.

## Next Direct-Copy Batch

Copied in the 2026-05-24 batch:

- Aider: `third_party/aider/aider/repomap.py`
- SWE-agent: `third_party/swe_agent/sweagent/environment/swe_env.py`
- vn.py: `third_party/vnpy/vnpy/trader/{constant.py,object.py,event.py}`
- Hummingbot:
  `third_party/hummingbot/hummingbot/core/data_type/{common.py,in_flight_order.py}`
- MCP Python SDK:
  `third_party/mcp_python_sdk/src/mcp/{types,server,shared}/**`
- Pandera:
  `third_party/pandera/pandera/{api/base/checks.py,api/base/schema.py,dtypes.py,errors.py}`
- Great Expectations:
  `third_party/great_expectations/great_expectations/expectations/**`

Each batch should land under `third_party/<tool>/`, include the upstream license,
include a SHA256 manifest, and update `docs/UPSTREAM_ATTRIBUTION.md`.

Remaining candidate targets after per-file inspection:

- Aider: ignore/path ranking helpers and edit-format parsers.
- SWE-agent: task config schemas and result normalization helpers.
- opencode: small provider/session formatting helpers.
- Continue/Cline/Roo: config schemas, permission/mode state shapes, and small
  non-UI helpers.
