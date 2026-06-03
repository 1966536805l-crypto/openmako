# OpenMako

Evidence harness for coding agents.

OpenMako is for checking whether an AI coding agent actually improved across
runs, stayed inside the requested patch scope, and passed validation without
cheating by editing tests or hiding failures.

The current public snapshot is intentionally narrow. Its strongest supported
claim is not broad SWE-agent autonomy. It is a repeatable learning-effect and
CodingBench harness around agent repair runs.

## What It Proves Today

The focused public gate exercises a package-level JavaScript repair task:

- `no_learning` must fail the hidden task pack.
- `approved_learning` must solve the hidden task pack.
- repeat stability must stay at zero spread.
- changed files must stay on the exact target source module.
- protected-test and failure-log cheating must be classified as cheated.

Run the same gate locally:

```bash
python3 -m pytest -p no:cacheprovider \
  tests/test_agent_planner_contract.py::AgentPlannerContractTest::test_planner_no_seed_repairs_package_level_http_manifest_js_module \
  tests/test_external_benchmark_multimodule_regression.py::ExternalBenchmarkMultimoduleRegressionTest::test_package_level_http_manifest_js_trajectory_skill_reuses_on_hidden_tasks \
  -q
```

Expected local result on the public snapshot:

```text
2 passed
```

## What It Does Not Claim

- It does not prove broad unknown-repository SWE repair.
- It does not prove general NPM package repair.
- It does not replace Claude Code, Codex, Cursor, Devin, or other coding agents.
- It does not claim desktop L4/L5 autonomy.
- It does not trust an agent's final message without command, diff, and test evidence.

## Why It Exists

Most coding-agent demos show the happy path. OpenMako focuses on the failure
boundary: did the agent run the required validation, touch only allowed files,
reuse an approved repair skill only after eval-gated approval, and fail closed
when the evidence is missing?

Use OpenMako when the useful question is not just "can the agent do it?", but
"can I inspect what it did, replay the path, and see where the risk is?"

## Quick Start

```bash
git clone <your-openmako-repo-url> open-mako
cd open-mako
python3 -m pip install -e .
mako onboard
mako doctor
mako agent "audit this repo and propose a safe fix plan"
```

`mako` is the primary CLI. `openmako` is an alias. `qagent` remains for compatibility.

Default project is the current working directory. To pin a project:

```bash
export QUANTAGENT_PROJECT="/path/to/your/project"
mako doctor
```

## Why It Is Different

| Layer | OpenMako default |
| --- | --- |
| Readiness | `mako doctor` scores runtime, permissions, plugins, sandbox, task health, auth, and config hygiene |
| Agent state | Tasks, sessions, approvals, query events, skills, and subagents mirror into SQLite runtime records |
| Evidence | Tool results, quant runs, answer guard, and run artifacts carry hashes, paths, and replay metadata |
| Safety | Permission policy, shell semantics, external-content fences, model-error actions, and worktree isolation |
| Repair | Diff-first edit plans, checkpoints, test classification, isolated repair loops, and review bundles |
| Extension | Plugin registry plus plugin-scoped keyed state store and MCP stdio/HTTP/SSE runtime |
| **Planning** | **Extreme Planner: AI-powered code generation with local context building and explicit benchmark targets** |

## First Demo Path

```bash
mako demo fix
mako onboard --json
mako doctor --json
mako runtime status
mako agent-v3 "inspect this repo and identify the highest-risk next fix"
mako query-events --limit 20
```

The output to screenshot first is `mako demo fix`: it creates a tiny failing-test project, fixes it, runs tests green, and writes proof artifacts without a model call. `mako doctor` is the product's shortest proof that the runtime is not a toy.

## Extreme Planner (New)

OpenMako now includes **Extreme Planner**: AI-powered code generation with local context building. The current repository verifies the planner interfaces and safety hooks; success-rate and cost claims still require benchmark evidence.

**Key Features:**
- First-try success and cost targets are explicit, not yet proven by a full benchmark run
- 0 AI calls for context building (all local: semantic search, dependency analysis, convention extraction)
- Prompt caching support is designed to reduce repeated context cost when provider caching is available

**Quick Start:**
```bash
# Use extreme planner (default)
mako agent "add input validation to user registration"

# Compare with old planner
mako agent "same task" --planner cheap
```

**Learn More:**
- [Extreme Planner Guide](docs/EXTREME_PLANNER.md)
- [Migration Guide](docs/EXTREME_PLANNER_MIGRATION.md)

## Low-Friction Edit

For a known replacement, use one command. Without `--apply`, Mako only previews the diff:

```bash
mako fix "replace stale wording" --path README.md --old "old text" --new "new text"
mako fix "replace stale wording" --path README.md --old "old text" --new "new text" --apply
```

`mako fix` creates checkpoints and runs the default project test command, or the command passed after `--test`.

## Positioning

- Compared with Claude Code/Codex-style coding agents: OpenMako focuses on runtime auditability, task state, evidence, and operator controls around the agent.
- Compared with OpenHands/Devin-style autonomous agents: OpenMako is lighter, local-first, and optimized for inspectable terminal workflows.
- Compared with Aider-style patch tools: OpenMako keeps the patch path, but adds task registry, approvals, runtime ledger, subagents, and doctor checks.
- Compared with OpenClaw-style personal assistant runtimes: OpenMako is narrower and engineering-focused: local coding/data work first, multichannel personal assistant later.

See [docs/COMPARISON.md](docs/COMPARISON.md) and [docs/LAUNCH_PLAYBOOK.md](docs/LAUNCH_PLAYBOOK.md).

## Clean-Room Boundary

OpenMako does not copy Claude/closed-source code, prompts, constants, endpoints, or proprietary strings. MIT-licensed OpenClaw/Hermes ideas are adapted with attribution where used; closed-source agent ideas are implemented only as clean-room mechanisms.

## Agent Failure Autopsy

OpenMako can act as an agent failure lab for Claude Code, Codex, Devin, or any wrapper that leaves logs. The target is not repair rate. The target is trace-backed failure explanation: which event first failed, which edit or tool call preceded it, what failure class ended the run, and what earlier gate could have intercepted it.

The control-plane seam is `AgentBackend`: external agents stay replaceable, while OpenMako owns the event ledger, trajectory, permission gates, and autopsy output. The first backends are `local_shell_stub` for deterministic tests and `codex_wrapper` for Codex CLI `exec` runs.

```bash
mako agent-autopsy --project "/path/to/project" \
  --trajectory .quantagent/trajectory.jsonl \
  --query-events .quantagent/query_events.jsonl \
  --failure-file .quantagent/last_test_failure.txt \
  --source-agent codex \
  --command "python3 -m unittest" \
  --output openmako-autopsy.md
```

Wrapper mode captures a failing agent command without replacing the agent:

```bash
mako agent-autopsy --project "/path/to/project" \
  --source-agent claude-code \
  --title "Claude Code failed validation" \
  --output openmako-autopsy.md \
  --run -- <agent command>
```

The report is deterministic from `query_events`, `trajectory`, and supplied failure logs. If those sources do not prove causality, the autopsy reports missing evidence instead of inventing a reason.

## Fast Desktop Agent

`mako desktop-agent` is the direct local takeover path: it uses macOS screen, Accessibility, mouse, keyboard, and screenshot primitives instead of slow visual chat loops. It dry-runs by default; real screen control requires `--execute --reviewed`, writes `query_events` and `trajectory`, and aborts before the next action if the STOP file exists.

```bash
mako desktop-agent "打开 Safari 搜索 OpenMako 并截图"
mako desktop-agent "打开 Safari 搜索 OpenMako 并截图" --execute --reviewed --verify-after
touch .quantagent/desktop/agent/STOP
```

## Desktop Intelligence Loop

`mako desktop tokenize|decide|daemon` is the L3 bridge toward the planned L4 desktop-daemon contract in `docs/DESKTOP_DAEMON_L4.md`: tokenize turns screenshot/AX/OCR/SoM/grid state into stable desktop tokens with an observation id and screen hash, decide emits exactly one deterministic next action, and daemon runs the bounded observe-tokenize-decide-act-verify loop. The recommended local driver split is documented in `docs/DESKTOP_CONTROL_DRIVERS.md`: Peekaboo-style observation, DesktopCtl-style execution, and Screenbox-style structured state stay behind OpenMako permission gates. It dry-runs by default; real desktop side effects require `--execute --reviewed --allow-actions`, and missing gates are skipped with `needs` instead of asking mid-run. Targeted click/move actions are fenced to the observed token and rechecked before execution, the STOP file aborts before each daemon step, non-ok terminal exits write an autopsy artifact, and the poison-test surface covers missing gates, STOP, high-risk goals, stale targets, loop detection, action failure, and semantic verification failure.

```bash
mako desktop tokenize --include-grid --json
mako desktop decide "点击 Search" --json
mako desktop daemon "搜索 OpenMako" --max-steps 20
mako desktop daemon "搜索 OpenMako" --execute --reviewed --allow-actions --max-steps 20 --delay 1
```

## Desktop Daemon Queue

`mako desktop-daemon` is the operator-facing queue for unattended local desktop work. `run` can enqueue one goal and process it immediately, or process already queued goals. It still dry-runs by default; real side effects require `--execute --reviewed --allow-actions`. `status`, `stop`, and `resume` expose the control plane without touching the screen.

```bash
mako desktop-daemon run "观察屏幕并等待下一步" --max-steps 1
mako desktop-daemon enqueue "搜索 OpenMako" --max-steps 20
mako desktop-daemon run --execute --reviewed --allow-actions --max-tasks 1 --delay 1
mako desktop-daemon status
mako desktop-daemon stop --all
```

## Desktop Eval

`mako desktop-eval` is the L4/L5 scoring gate for local desktop autonomy. It runs bounded scenario suites, writes metrics and reports, and maps results to a level score. The command fails closed if the eval core is unavailable.

```bash
mako desktop-eval run --suite suite_l4 --duration-minutes 60
mako desktop-eval run --suite suite_l4 --duration-minutes 60 --execute --reviewed --allow-actions
mako desktop-eval list
```

## Overnight Desktop Agent

`mako desktop-overnight` is the bounded long-running loop for unattended local work. It observes the screen every round, performs at most one planned desktop action per round, verifies side effects with another screenshot, writes live state, records `query_events`/`trajectory`, and stops on the STOP file. It blocks high-risk goals such as payments, trading, credentials, destructive deletion, and message sending.

```bash
mako desktop-overnight "打开 Safari 搜索 OpenMako 并截图" --max-rounds 20
mako desktop-overnight "打开 Safari 搜索 OpenMako 并截图" --execute --reviewed --allow-actions --max-rounds 20 --max-minutes 480 --delay 30
touch .quantagent/desktop/agent/STOP
```

## Command Reference

- `status`: 读取当前项目状态、最新交接文件、基准数据文件
- `watch`: 检查交接目录最新文件；加 `--hooks` 可触发 hook
- `agent-autopsy`: 解剖 Claude Code/Codex/Devin 等 agent 的失败链路；读取 trajectory、query_events 和失败日志，输出 `openmako-autopsy.md`
- `audit`: 跑量化专用安全检查
- `quant check`: 量化优先证据门；PF/收益/滑点/容量/实盘结论缺 dedup、hash、分年/OOS、成交证据时阻断或降级
- `quant data-contract`: CSV 入口契约；检查 schema、日期/数值、重复、1253 污染样本、dedup 标记和分年风险
- `quant data-adapter`: 本地量化数据识别器；小样本扫描 CSV/zip/7z，识别 position、回测收益、日线行情、分钟 K、榜单事件、逐笔成交包
- `quant expectations`: Great Expectations/Pandera 风格 CSV expectation suite；检查日线/分钟/tick/fill/滑点/容量/持仓的列族、日期、数值、OHLC 和唯一性
- `quant data-sample`: 从本地 2061 日线 zip、分钟 K zip、逐笔 7z 按单票/日期流式抽样，写 `.quantagent/data_samples/*.csv` 并自动跑 expectations
- `quant execution-gate`: 真实执行证据门；必须接入 tick/fill/broker/slippage/capacity 文件并 hash/schema 检查，才允许 `live_ready=true`
- `quant leak-check`: lookahead/leakage 扫描；检查 CSV future/target 列、Python `shift(-1)`、forward asof、centered rolling 等
- `quant bench`: 跑内置 QuantBench；覆盖数据合约、泄漏扫描、量化证据门和实验产物写入，输出 markdown/json 分数
- `quant run/evidence/verdict/replay`: 量化强制状态机；同一份 spec 依次跑 data contract、leak check、yearly/OOS split、实验 artifact、evidence bundle 和最终 verdict
- `safety`: 查看安全边界，或预判命令/结论是否应该执行
- `report`: 生成一份交接报告草稿
- `run-p4`: 调用项目里的 P4 真实成交框架
- `context`: 生成模型上下文包
- `desktop`: 本地屏幕/键鼠控制面，支持 screenshot、grid、AX/OCR/SoM、tokenize/decide/daemon、文本找目标、web-search dry-run plan、reviewed click/type/hotkey 和执行日志
- `desktop-agent`: 直接接管本地屏幕的快速 agent；默认预览，`--execute --reviewed` 后按正常人手速执行，并支持 STOP 文件熔断
- `desktop-daemon`: 面向整夜任务的桌面 daemon 队列；支持 enqueue/run/status/stop/resume，真实动作仍要求 `--execute --reviewed --allow-actions`
- `desktop-eval`: L4/L5 桌面自治评测入口；运行 suite、写 metrics/report，并把结果映射到等级分
- `desktop-overnight`: 有边界的一整晚桌面 agent；每轮 observe/act/verify，写 state、query_events、trajectory，STOP 文件熔断，并阻断支付/交易/凭证/破坏性删除等高风险目标
- `query-events`: 查看 agent/query runtime 事件流
- `runtime`: OpenClaw/Hermes 风格主账本视图；统一查看 SQLite sessions、task runs、approvals、tool invocations、query events，并支持消息搜索/export
- `approval`: 查看/恢复/批准/拒绝 ASK 级工具调用，持久化 approval_id 和 fingerprint；`allow_always` 只对同一 fingerprint 生效并检查 `expires_at`
- `mcp`: 读取 `.quantagent/mcp_servers.json`，列出 stdio/HTTP/SSE MCP server/tools，并安全调用工具；支持 process-local manager、session-scoped lease、initialize、idle cleanup 和 env whitelist
- `agent-profile`: 查看 OpenCode 风格的 Plan/Build/Audit/Quant agent profiles、permission matrix、config layering 和项目 instructions
- `subagent`: 启动/刷新/查看/停止本地子 agent，记录 parent task、child session、profile、fork/isolated context artifact、可选 worktree isolation、review summary、进度和终态
- `index`: 构建/搜索/诊断轻量 codebase index，使用 file hash、chunks、symbols、imports、依赖图和 BM25 检索
- `checkpoint`: 对 edit/test/tool 前后的文件状态做可跨命令恢复的 checkpoint，支持 list/show/restore
- `transcript`: 回放 tool-call transcript，包含输入、policy、approval、checkpoint、输出预览、耗时和失败类型
- `resume`: 恢复最新 session、指定 task/subagent 或 last failure；也能写入/查看长任务 compact resume snapshot
- `skills`: 查看内置/项目量化 skill，用 `--match` 预览自动启用项，或用 `--install` 安装本地 `SKILL.md`
- `plugins`: 查看 metadata-only 插件注册表；`--json` 输出 manifest hash/policy hash/diagnostics，`--refresh` 写入生成态 registry，并校验权限、hook 和 env requirements
- `state`: 写入压缩项目状态 `PROJECT_STATE_COMPACT`
- `todo`: 维护 P 阶段研究看板；也能维护绑定 task runtime 的 pending/in_progress/completed checklist
- `task`: 维护研究任务，并可启动/刷新/停止本地后台 agent/shell 任务、查看输出；任务元数据会兼容写 JSON 并镜像进 SQLite runtime store
- `review`: 生成双模型审计请求
- `consensus`: 生成/检查 3 次 ChatGPT 一致性确认门禁；它用于降低研究幻觉，不等于真实独立安全审批
- `model-test`: 测试 OpenAI-compatible 模型连通性
- `ask`: 带项目上下文询问模型
- `chat`: 打开 Claude Code 风格的橙色终端聊天界面，回复带左侧竖线、token 用量、状态栏、思考摘要，并自动追加到 `CHAT_REVIEW_STREAM.md`
- `run-next`: 自动安全循环，更新状态、审计、验证，并行调用 researcher/auditor/data_engineer 三角色，输出可机器读取的 next_action_queue、role_consensus、role_conflicts
- `validate`: 跑验证流水线并写日志
- `doctor`: 给 Mako 自身做 readiness 评分；`--json` 可输出 runtime DB、插件、auth、shell completion 等诊断
- `onboard`: 输出项目路径、doctor 分数、模型认证状态和下一步命令；`--json` 可用于安装脚本和 CI smoke check
- `ux status`: 统一查看 context token 状态、最新 session、pending approval、tool-call transcript、diff review、checkpoint、query events
- `loop`: 跑一轮本地确定性 Agent loop
- `edit plan` / `edit run` / `edit auto` / `edit repair`: 生成预览门禁 patch plan，并按 plan 执行 diff-first exact replacement、模型 repair candidate、隔离多轮修复、checkpoint、测试和失败分类
- `isolation`: 创建/列出/运行/删除 copy-on-write 工作区隔离副本，让测试或子任务先在副本里跑，并通过 review/apply-review 审查合回源项目
- `experiment`: 标准化跑实验，输出 JSON + MD 并登记
- `registry`: 查看实验登记簿
- `audit --deep`: QuantAuditor 深度审计

## 研究命令例子

```bash
mako experiment --scenario A --threshold -9
mako experiment --scenario D --threshold -9
mako registry --latest
mako audit --deep
mako quant check "报告 PF=2.1 已确认，可以实盘" --no-audit
mako quant data-contract AI_协作交接/sample_position_dedup.csv --strict-dedup
mako quant data-adapter "/path/to/2061票更新至4.30" "/path/to/分钟K线-股票241" "/path/to/A股_逐笔成交"
mako quant expectations daily.csv --kind market_bar_csv --json
mako quant data-sample "/path/to/2061票更新至4.30" --code 000001 --kind market_bar --start 2026-04-24 --end 2026-04-24 --json
mako quant data-sample "/path/to/分钟K线-股票241" --code 600000 --kind minute_bar --freq 1m --date 2026-05-21 --json
mako quant data-sample "/path/to/A股_逐笔成交" --code 000001 --kind tick_trade --date 2013-03-01 --max-rows 100 --json
mako quant execution-gate --tick tick.csv --fill fill.csv --broker broker.csv --slippage slippage.csv --capacity capacity.csv --execution-source "broker export 2026-05-20"

# Tick validation workflow example
mako quant data-sample "/path/to/逐笔成交" --code 000001 --kind tick_trade --date 2026-05-27 --max-rows 10000
# Output: .quantagent/data_samples/tick_trade_000001_20260527.csv
mako quant execution-gate \
  --tick .quantagent/data_samples/tick_trade_000001_20260527.csv \
  --fill broker_fills.csv \
  --broker broker_info.csv \
  --order order_lifecycle.csv \
  --position positions.csv \
  --slippage slippage_evidence.csv \
  --capacity capacity_evidence.csv \
  --execution-source "broker export 2026-05-27"
# Output: live_ready=true if all validations pass
mako quant broker-gateway --broker broker.csv --fill fill.csv --json
mako quant leak-check . --max-files 500
mako quant bench
mako quant bench --json
mako quant run AI_协作交接/sample_position_dedup.csv --threshold-col t1_auction_return --threshold -9
mako quant run AI_协作交接/sample_position_dedup.csv --tick tick.csv --fill fill.csv --broker broker.csv --slippage slippage.csv --capacity capacity.csv --execution-source "broker export"
mako quant evidence
mako quant verdict --answer "PF research report only"
mako quant replay
mako quant full-audit --project . --scenario A --input AI_协作交接/sample_position_dedup.csv --threshold-col t1_auction_return --threshold -9
mako quant full-audit --project . --scenario B --input positions.csv --tick tick.csv --fill fill.csv --broker broker.csv --execution-source "broker export 2026-05-20" --json
mako consensus --new "逐笔到货后运行 P4 真实成交验证"
mako model-test --model gpt-5.5
mako ask --model gpt-5.5 "用三句话总结当前项目状态"
mako
mako "现在项目下一步做什么"
mako --project "/path/to/your/quant/project"
mako skills --match "P4逐笔验证滑点容量证据hash" --show
mako skills --project "/path/to/your/quant/project" --install "./my-skill"
mako skills --project "/path/to/your/quant/project" --match "capacity liquidity" --show
mako query-events --project "/path/to/your/quant/project" --limit 20
mako agent-autopsy --project "/path/to/your/project" --trajectory .quantagent/trajectory.jsonl --query-events .quantagent/query_events.jsonl --failure-file .quantagent/last_test_failure.txt --source-agent codex --command "python3 -m unittest" --output openmako-autopsy.md
mako agent-autopsy --project "/path/to/your/project" --source-agent claude-code --output openmako-autopsy.md --run -- <agent command>
mako runtime --project "/path/to/your/quant/project" status
mako runtime --project "/path/to/your/quant/project" search "PF evidence"
mako runtime --project "/path/to/your/quant/project" export
mako ux --project "/path/to/your/quant/project" status --task "修复测试失败" --limit 8
mako ux --project "/path/to/your/quant/project" status --no-context-pack --json
mako desktop shot
mako desktop live
mako desktop live --once --no-color
mako desktop open terminal
mako desktop open terminal --kind terminal --cwd .
mako desktop open Safari --kind app --execute --reviewed
mako desktop open "https://example.com" --kind url --browser Safari --execute --reviewed
mako desktop grid --cols 12 --rows 8
mako desktop ax --depth 4 --limit 300
mako desktop ocr
mako desktop som --include-grid
mako desktop tokenize --include-grid --json
mako desktop decide "点击 Search" --json
mako desktop daemon "搜索 OpenMako" --max-steps 20
mako desktop find "Search" --source both --refresh-ax
mako desktop find "Run backtest" --source all --refresh-som
mako desktop web-search "NVDA earnings evidence" --engine duckduckgo
mako desktop web-search "NVDA earnings evidence" --engine duckduckgo --execute --reviewed --verify-after
mako desktop find-click "Run tests" --execute --reviewed --verify-after
mako desktop som-click M001 --som AI_协作交接/desktop/som_xxx.json
mako approval --project "/path/to/your/quant/project" list
mako approval --project "/path/to/your/quant/project" approve apr_xxx --allow-always
mako agent-profile --project "/path/to/your/quant/project" list
mako agent-profile --project "/path/to/your/quant/project" show plan
mako agent-profile --project "/path/to/your/quant/project" check plan edit
mako agent-profile --project "/path/to/your/quant/project" instructions
mako mcp --project "/path/to/your/quant/project" list
mako mcp --project "/path/to/your/quant/project" tools
mako mcp --project "/path/to/your/quant/project" call fake echo --args-json '{"text":"hi"}'
mako mcp --project "/path/to/your/quant/project" call fake echo --agent-profile audit --args-json '{"text":"hi"}'
mako mcp --project "/path/to/your/quant/project" status
mako subagent --project "/path/to/your/quant/project" start "扫描测试失败原因" --context-mode fork --profile audit --no-validation --isolate-worktree
mako subagent --project "/path/to/your/quant/project" list --refresh
mako index --project "/path/to/your/quant/project" build
mako index --project "/path/to/your/quant/project" search "slippage capacity root cause"
mako index --project "/path/to/your/quant/project" diagnose
mako checkpoint --project "/path/to/your/quant/project" create quantagent/cli.py --reason "before CLI refactor"
mako checkpoint --project "/path/to/your/quant/project" show chk_xxx --include-text
mako transcript --project "/path/to/your/quant/project" list
mako transcript --project "/path/to/your/quant/project" show inv_xxx
mako resume --project "/path/to/your/quant/project" last-failure
mako resume --project "/path/to/your/quant/project" compact session SESSION_ID
mako resume --project "/path/to/your/quant/project" list
mako resume --project "/path/to/your/quant/project" show resume-xxx --include-body
mako todo --project "/path/to/your/quant/project" --task-id qa-0001 --set-plan 1 in_progress --title "复现失败"
mako session --project "/path/to/your/quant/project" --search "traceback slippage"
mako session --project "/path/to/your/quant/project" --export SESSION_ID --format markdown
mako task --project "/path/to/your/quant/project" --title "status agent" --run-agent "检查当前项目状态" --no-validation
mako task --project "/path/to/your/quant/project" --allow-risky --title "unit tests" --run-shell python3 -m unittest discover -s tests
mako task --project "/path/to/your/quant/project" --refresh
mako task --project "/path/to/your/quant/project" --output qrt-0001
mako plugins --project "/path/to/your/quant/project" --json
mako edit-loop --project "/path/to/your/project" --plan-json "./change_set.json" --test python3 -m unittest discover -s tests
mako edit --project "/path/to/your/project" plan "修复 CLI approval 命令" --path quantagent/cli.py --test python3 -m unittest discover -s tests --out .quantagent/patch_plan.json
mako edit --project "/path/to/your/project" run .quantagent/patch_plan.json --apply
mako edit --project "/path/to/your/project" run .quantagent/patch_plan.json --apply --agent-profile plan
mako edit --project "/path/to/your/project" auto "替换阈值" config.py --old "THRESHOLD = 1" --new "THRESHOLD = 2" --test python3 -m py_compile config.py
mako edit --project "/path/to/your/project" auto "替换阈值" config.py --old "THRESHOLD = 1" --new "THRESHOLD = 2" --apply --reviewed --test python3 -m py_compile config.py
mako edit --project "/path/to/your/project" repair .quantagent/patch_plan.json --failure-file .quantagent/last_test_failure.txt
mako edit --project "/path/to/your/project" repair .quantagent/patch_plan.json --failure-file .quantagent/last_test_failure.txt --isolated-loop --max-rounds 3
mako isolation --project "/path/to/your/project" create --reason "before risky repair"
mako isolation --project "/path/to/your/project" run --allow-risky -- python3 -m unittest discover -s tests
mako isolation --project "/path/to/your/project" review iso-xxx --diff
mako isolation --project "/path/to/your/project" apply-review review-xxx --reviewed
mako run-next
mako doctor --project "/path/to/your/quant/project"
mako doctor --project "/path/to/your/quant/project" --json
mako chat --long --save-report
mako chat --deep-context --long --save-report
mako chat --no-stream-file
mako safety --check-command "rm -rf AI_协作交接/tick_raw"
mako safety --check-claim "PF=2.1"
```

## Comprehensive Quantitative Audit: `quant full-audit`

`mako quant full-audit` runs an end-to-end audit pipeline that integrates:

1. **Auto Evidence Discovery** (`quant_auto_evidence`): Scans project directories for strategy code, data files, and execution evidence
2. **Data Contract Validation** (`quant_data_contract`): Verifies CSV schema, deduplication, and data quality
3. **Leak Check** (`quant_leak_check`): Detects future data leakage in strategy code
4. **Split Check** (`quant_run_gate`): Validates out-of-sample (OOS) ratio ≥ 20% for statistical validity
5. **Execution Gate** (`quant_execution_gate`): Validates broker evidence (tick, fill, order, account data), trading hours, slippage, and capacity
6. **Judge Verdict** (`quant_judge`): Final pass/block decision based on all evidence

**Basic Usage** (research-only, no broker evidence):

```bash
mako quant full-audit \
  --project . \
  --scenario A \
  --input AI_协作交接/sample_position_dedup.csv \
  --threshold-col t1_auction_return \
  --threshold -9
```

**Live-Ready Audit** (with broker evidence):

```bash
mako quant full-audit \
  --project . \
  --scenario B \
  --input positions.csv \
  --tick tick.csv \
  --fill fill.csv \
  --broker broker.csv \
  --slippage slippage.csv \
  --capacity capacity.csv \
  --execution-source "broker export 2026-05-20" \
  --json
```

**Output**:

- **Markdown Report**: `.quantagent/audit/audit-{timestamp}/audit-{timestamp}.md`
- **JSON Report**: `.quantagent/audit/audit-{timestamp}/audit-{timestamp}.json`

**Key Fields**:

- `research_ready`: True if data contract, leak check, and split check pass (suitable for research reports)
- `live_ready`: True if `research_ready` AND execution gate passes with broker evidence (suitable for live trading)
- `action`: `"pass"` or `"block"`
- `failure_reason`: Human-readable explanation if blocked
- `warnings`: Non-blocking issues (e.g., capacity < 1M CNY, slippage assumptions)

**Design Rationale**: See [docs/DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md) for detailed explanations of:
- Why `runner_sha256` prevents metric forgery
- Why OOS must be ≥ 20% (statistical validity)
- Why capacity threshold is 100 rows / 1M CNY
- Why slippage is mandatory
- Why broker evidence is required for live trading

`edit-loop --plan-json` accepts multi-file candidate change sets and runs the
test command after each candidate. Failed candidates restore every file they
touched unless `--keep-failed` is used. Plan shape:

```json
{
  "candidates": [
    {
      "name": "fix import and test",
      "edits": [
        {"path": "app.py", "old": "from old import x", "new": "from new import x"},
        {"path": "tests/test_app.py", "old": "old expectation", "new": "new expectation"}
      ]
    }
  ]
}
```

`edit plan` 生成的是更高层的 patch planner 输出：目标文件、风险、测试命令和候选 edits。`edit run` 默认不会直接应用带 `preview_required` 的计划，必须显式 `--apply`，这样可以避免模型或脚本没有预览就大改文件。执行后会记录每轮测试失败分类：`syntax/import/assertion/path/env/policy/timeout/unknown`。

`edit run` 现在还支持 diff-first patch plan：计划 JSON 可包含 `unified_diff` 字段。执行前会自动写 `.quantagent/checkpoints/chk-*.json`，apply 后如果提供 `test_command` 会继续跑测试并记录 `after_test_run` hook 和失败分类。失败后可用 `mako checkpoint restore CHK_ID` 跨命令恢复。这个路径适合 Aider/Sweep 风格的“先生成可审阅 diff，再 apply/test/repair”。

`edit auto` 是保守的代码执行闭环入口：读取文件、验证 `old` 出现次数、生成 unified diff，默认只预览；只有同时传 `--apply --reviewed` 才会应用、打 checkpoint、跑测试，并把失败归类为 `syntax/import/assertion/path/env/policy/timeout/unknown`。它现在是确定性 old/new patch loop，不会自己凭空生成大段改动；模型驱动 repair candidates 是下一步。

`edit repair` 会把 patch plan、测试失败输出、目标文件列表和文件预览交给模型，请它只返回 JSON repair candidates。默认模式只解析候选 unified diff 或 exact replacements，不直接应用；加 `--isolated-loop` 后会创建隔离 worktree，在副本中按“模型候选 -> apply -> test -> 分类失败 -> 下一轮”最多 N 轮执行。通过或耗尽轮次后都会生成 isolation review，源项目仍不被自动写。

`isolation` 提供 worktree isolation：把项目复制到 `AI_协作交接/quantagent_isolated_worktrees/iso-*/workspace` 或 legacy `.quantagent/quantagent_isolated_worktrees`，排除 `.git`、`.quantagent`、运行时任务、虚拟环境、缓存、node_modules 和隔离目录本身。`isolation run` 的命令在副本里执行，源项目不被写；在 macOS 且 `/usr/bin/sandbox-exec` 可用时，默认会套 OS sandbox，写入限制在隔离 workspace 内，网络默认 deny，并在结果里记录 sandbox backend/network policy；不可用时回退到 worktree/host 执行并明确标记网络策略未被 OS 强制。`isolation review` 生成源项目与副本之间的 unified diff；`apply-review --reviewed` 才会把 changed/new/deleted 文件合回源项目。

`index diagnose` 会检查轻量索引健康：缺失索引会自动重建，已有索引会比对当前文件 hash，报告 stale/missing/unindexed 文件和重复符号；`dependency_graph()` 可给 agent 提供按文件聚合的 imports。代码索引还提供 deterministic lexical vector / semantic fingerprint 的 `similar_code_chunks()`、`related_files()`，以及非完整 LSP 的 `editor_diagnostics()`：用 `py_compile` 捕获 Python 语法错误，扫描 TODO/FIXME，并做轻量 unresolved import 诊断。

`resume compact` 会把 session/task/subagent 压成可持久化的 resume snapshot，写入 `AI_协作交接/quantagent_resume_snapshots/resume-*.json`，里面包含 summary、恢复命令、压缩指标、artifacts 和必要上下文。`resume list/show` 用于长任务断点恢复，避免只靠聊天窗口里的最后几条消息。

### Quant evidence pipeline

实验入口现在会先跑 data contract 和 leak-check。data contract 失败或发现 hard lookahead pattern 时不写 registry；成功后会写 `quantagent_runs/run-*/spec.json`、`result.json`、`audit.json`、`report.md`，并自动把 dedup baseline、artifact hash/row count、yearly/OOS split 和 PF 指标写入 evidence ledger，供 `quant check` 和 `answer-guard` 使用。

`mako quant bench` 会用合成样本回归验证这条量化底线：坏 schema 必须阻断、未标 dedup 在 strict 模式必须阻断、`shift(-1)` 和 forward `merge_asof` 必须阻断、future/target 列必须提示、无证据实盘/PF 结论必须阻断、有证据结论必须放行，并确认实验入口写入 run artifact 和 evidence ledger。

`mako quant run` 是更严格的默认量化状态机：一份 `QuantRunSpec` 必须通过 CSV contract、leak check、yearly/OOS split，才会执行实验并写入 run artifact、evidence bundle 和 verdict。`research_ready=true` 只允许带 `run_id/input_sha256/spec_hash/split` 引用研究结论；`live_ready=true` 现在还必须通过 `quant execution-gate` 的 tick/fill/broker/slippage/capacity 文件证据，单独写 `--execution-source` 只会记录来源，不会放行实盘。`live_ready=false` 时任何“实盘/下单/成交/滑点/容量已证明”的回答都会被 `answer-guard` 和 `agent-v3` 的 `quant_run_gate` 阻断。

`mako quant data-adapter` 是本地量化数据入口层。它不会全量解压大文件，只读取 zip 目录和首个 CSV 小样本，当前能识别 `2061票更新至4.30` 的前/后/不复权日线库、`分钟K线-股票241` 的 2000-2025 和 2026 分钟包、`A股_逐笔成交` 的日度 7z 包，以及 `榜单数据` 下的涨停/炸板/龙虎榜/热榜事件 CSV。

Agent v3/chat 路径现在会在量化任务需要 PF/收益/实盘等证据、且项目里还没有最新 QuantRunGate 时，保守地自动寻找 `position/dedup/return` CSV。如果 header 符合 `entry_date,net_return` 或 `date,return`，会自动触发一次 `quant run` 并把 gate_id、input_path 和 evidence bundle 写入 observation；找不到候选 CSV 时仍然阻断材料结论。

Hook lifecycle 已经覆盖主路径关键节点：`before_context_build`、`after_context_build`、`before_model_call`、`after_model_call`、`before_tool_call`、`permission_request`、`after_tool_call`、`before_patch_apply`、`after_test_run`、`before_agent_finalize`、`after_agent_finalize`。现在也接受 Claude Code 风格别名：`UserPromptSubmit`、`PreToolUse`、`PostToolUse`、`PostToolUseFailure`、`Stop`、`SubagentStart`、`SubagentStop`、`PreCompact`、`PermissionRequest`、`SessionStart`、`SessionEnd`、`Notification`、`Setup`、`TaskCompleted`、`ConfigChange`、`WorktreeCreate`、`WorktreeRemove`。profile 里可以声明 shell hooks，`mako hooks list/run` 可查看或手动触发；hook stdin/stdout 使用 JSON envelope，支持 matcher、priority、timeout、fail_open/fail_closed。

`rules` 和 `review --diff` 借鉴 Cursor 的 rules/Bugbot 工作流。规则从 `.quantagent/rules/*.md`、`.cursor/rules/*.md`、`AGENTS.md`、`QUANTAGENT.md` 读取，支持轻量 frontmatter：`description`、`globs`、`alwaysApply`。`mako review --diff --path src/foo.py` 会汇总匹配规则、TODO/FIXME、Python 语法错误和 git/no-git diff，输出以 findings 开头的 deterministic review。

`context --ref` 借鉴 Continue 的 context providers，可点名收集上下文而不是只靠大包扫描：

```bash
mako context --ref @diff --ref @repo-map --ref @problems
mako context --ref @file:quantagent/cli.py --ref @rules:quantagent/cli.py
```

支持 `@diff`、`@file:path`、`@folder:path`、`@tree:path`、`@search:query`、`@problems`、`@repo-map`、`@terminal[:task_id]`、`@rules[:path]`、`@memory[:query]`、`@docs[:path]`、`@os`、`@related:path`。chat 里直接写这些 `@...` 也会把对应上下文拼进 prompt；常用 slash 命令包括 `/map`、`/diff`、`/problems`、`/rules`、`/tokens`、`/architect`、`/read-only`。

`architect plan` 借鉴 Aider 的 architect/editor 分工：先产出架构计划、目标文件、风险、测试命令和 editor contract，再交给 edit/repair/subagent 去执行。`pr plan` 借鉴 GitHub coding agent 的 PR 工作流，生成 branch/base/checklist/test artifact；`runner plan` 生成远程 ephemeral runner 规格，记录 setup/run commands、网络 allowlist、secrets 和超时，但不会自动上传或执行远程任务。

长期记忆现在有 sidecar 审批队列：

```bash
mako memory --propose-text "P4 evidence must include script hash and broker provenance."
mako memory --proposals
mako memory --approve-proposal memprop-...
```

它会先从文本/session/report/tool-loop 中提炼候选记忆，只有人工 approve 后才写入 `memory.db`，避免 agent 随手污染长期记忆。

从 Claude deep notes 里落地的量化可信执行底座：

- `run_artifacts.py`: 用 `data_hash/params/code_version/library_versions/seed` 等 spec 生成稳定 run-id，写入 `AI_协作交接/quantagent_runs/run-*/spec.json`、`result.json`、`report.md`、`audit.json`、`logs/`，并用 spec-lock 防止边跑边改参数污染结果。
- `verdict_gate.py`: verdict 只有 `PASS`、`FAIL`、`INCONCLUSIVE` 三态；灰区必须阻断晋级，不能被当作通过。
- `redaction.py`: 大数组、大日志、大结果进模型前先摘要；日志按指纹折叠 count/first_seen/last_seen/examples，避免逐笔/盘口/回测 warning 淹没上下文。

MCP 最小配置放在项目 `.quantagent/mcp_servers.json`：

```json
{
  "mcp_servers": {
    "fake": {
      "command": "python3",
      "args": ["tools/fake_mcp_server.py"],
      "timeout": 5,
      "idle_ttl": 60,
      "env_whitelist": ["PATH", "HOME"]
    }
  }
}
```

当前 MCP runtime 支持 stdio JSON-RPC 的 `initialize`、`notifications/initialized`、`tools/list` 和 `tools/call`。默认 catalog/call 主路径通过进程内 `McpManager` 复用 initialized session；`session_scoped=false` 才退回 one-shot 兼容模式。库层 `open_mcp_session()` 可启动 long-lived session，一次 initialize 后复用多次调用，并支持 idle cleanup。`transport=http|sse` 可以通过 `url` 接 HTTP/SSE JSON-RPC MCP endpoint。错误里的 token/API key 会脱敏，调用会写入 SQLite tool invocation envelope、query events 和可回放 transcript。

Subagent 的 `context_mode` 现在会真正落地成 context artifact 并传给 worker：

```text
fork = 继承最新 session 摘要/最近消息 + 当前 context pack
isolated = 不继承父会话，只给项目 instructions
profile = 传入 agent-v2，每一步 tool/command 都走对应 permission matrix
```

context artifact 会写到 `quantagent_tasks/subagent_contexts/sub-*.md`，同时作为 child session 的 system message 和 child task evidence。

如果 `subagent start --isolate-worktree`，child worker 会把 runtime project 指向隔离副本，源项目只保存 task/subagent 元数据；子任务结束后刷新会自动创建 isolation review，并把 review JSON 加进 artifacts，便于 parent 汇总审查。

Agent profiles 借鉴 OpenCode/Claude Code 的治理模型，但字段是 Mako 自己的 clean-room 实现。除了 JSON config，默认只会加载 `~/.quantagent/agents/*.md` 和项目 `.quantagent/agents/*.md`。为避免默认摄取其他产品命名空间里的 agent prompt，`~/.claude/agents/*.md` 和项目 `.claude/agents/*.md` 只有在显式设置 `QUANTAGENT_LOAD_CLAUDE_AGENTS=1` 时才会作为迁移兼容路径读取。Markdown agent 使用 YAML-ish frontmatter + body-as-prompt，支持 `tools`、`disallowedTools`、`permissionMode`、`maxTurns`、`skills`、`mcpServers`、`hooks`、`memory`、`effort`、`background`、`isolation`、`color` 等字段。`isolation: worktree` 的 subagent 会自动跑在隔离副本里。

Agent profiles 的 permission DSL 也支持 OpenCode 风格分组：`read/edit/glob/grep/list/bash/task/external_directory/todowrite/webfetch/websearch/lsp/skill/question/doom_loop/mcp`，并支持 nested bash/MCP pattern，例如 `bash: {"*": "ask", "git diff*": "allow", "git push*": "deny"}`。

配置按以下优先级 merge，后者覆盖前者，非冲突字段保留：

```text
builtin defaults
~/.quantagent/config.json
~/.quantagent/quantagent.json
project .quantagent/config.json
project .quantagent/quantagent.json
QUANTAGENT_CONFIG_JSON
QUANTAGENT_AGENT
CLI override
QUANTAGENT_MANAGED_CONFIG / project .quantagent/managed_config.json
```

内置 profiles：

```text
plan = 只读规划，edit/file_write/file_edit/apply_patch/experiment/run_p4 deny
build = 默认编码，读允许，edit/shell/MCP ask，py_compile/test allow
audit = 只读审计 subagent，不能改状态
quant-auditor = 量化证据审计 subagent，能读证据和审计，不能改代码、跑实验或交易
```

`default_agent` 必须是 primary agent；如果配置成 subagent 或不存在，Mako 会回退到 `build`。

项目指令按优先级读取：`~/.quantagent/AGENTS.md`、`~/.quantagent/instructions/*.md`、项目 `QUANTAGENT.md`、`AGENTS.md`、`AI_协作交接/PROJECT_MEMORY.md`、`.quantagent/instructions/*.md`。这些指令用于把 OpenCode/Claude Code 风格的工程规则、量化规则和 skill snapshot 收进同一条上下文链。

MCP server 可以配置 OpenCode/Gatelet 风格的权限和参数 guard。`permissions` 支持通配符，显式 `deny` 的工具不会出现在 catalog 里；`ask` 会创建可恢复 approval；`guards` 可以给参数加默认值、强制字段值或拒绝敏感字段：

```json
{
  "mcp_servers": {
    "calendar": {
      "command": "python3",
      "args": ["tools/calendar_mcp.py"],
      "permissions": {
        "list_*": "allow",
        "create_event": "ask",
        "delete_*": "deny"
      },
      "guards": {
        "create_event": {
          "defaults": {"calendarId": "primary"},
          "must_equal": {"calendarId": "primary"},
          "deny_fields": ["password", "token"]
        }
      }
    }
  }
}
```

首次进入一个 workspace 时，交互式 CLI 会先显示信任确认：

```text
Accessing workspace:

 /path/to/your/quant/project

Quick safety check: Is this a project you created or one you trust?
```

按 Enter/`1` 会把该目录加入本机信任列表；输入 `2` 会在读取、编辑或执行该 workspace 前退出。非交互脚本不会默认信任新 workspace；自动化必须用 `--trust-workspace` 显式信任，或用 `--no-trust-prompt` 跳过提示。

信任确认后进入 `mako` 交互聊天时，会显示 Claude Code 风格的启动页：Mako 版本、当前模型、provider、workspace 路径，以及认证变量冲突或 `.zshrc` 缺失 source 文件等环境告警。聊天内可用 `/model` 查看模型，或 `/model <name>` 切换当前模型。

Starter 包本身没有内置 `p4_real_execution_framework.py` 时，`mako validate --project .` 会把 P4 help 检查标记为 skip；真实项目放入该脚本后会自动执行 `--help` 探测。

## run-next 输出

`mako run-next` 不执行真实实验、不改策略数据，只做安全循环和报告写入。生成的 `AUTO_RUN_*.json` 顶层包含：

- `next_action_queue.allowed_safe_actions`: 现在可排队的只读审计、验证、报告和证据收集动作，包含 `owner_role`
- `next_action_queue.blocked_material_actions`: 仍被阻塞的实验、P4 执行、数据变更、策略变更或结论动作，包含 `owner_role`
- `next_action_queue.required_evidence`: 放行材料动作前必须补齐的证据、hash、去重确认、验证结果或三次 ChatGPT APPROVE，包含 `owner_role`
- `role_consensus`: 三角色 verdict、共享行动/阻塞/证据需求和计数
- `role_conflicts`: verdict 分歧、批准与阻塞并存、动作分类冲突等结构化冲突

Markdown 报告用于人工交接；JSON 是下游自动编排的稳定接口。

## Token 控制

先跑免费预检，确认要带多少上下文、先做哪些本地检查，再决定是否调用模型：

```bash
mako cheap --project . "修复失败测试"
mako cheap --project . "修复失败测试" --json
```

`mako cheap` 只读本地项目，输出 `model_calls: 0`、context 档位、预估 token 压力、repo-map 状态、免费优先命令和最后才需要的 paid next step。

`mako chat` 会自动判断上下文档位，目标是避免短问题也烧大包 token：

- light: 短问、命令、状态、用法，`QUANTAGENT_CHAT_CONTEXT_TOKENS=6000`
- standard: 分析、代码、审计、策略、P4、逐笔、回测、PF 等关键词，`QUANTAGENT_LONG_CONTEXT_TOKENS=18000`
- deep: 完整复盘、全量上下文、交接、最终报告，或显式 `--deep-context`，`QUANTAGENT_DEEP_CONTEXT_TOKENS=80000`

每次回答的 reasoning summary 会写明 context router 选了哪一档和原因。

聊天请求期间会显示公开运行轨迹：

- context 档位和触发原因
- active skills，这次自动套用了哪些量化工作流
- skill snapshot id，agent-v2 会把本次命中的 skills、prompt hash 和来源写入 SQLite runtime store
- estimated input tokens / budget
- elapsed seconds 心跳，避免误以为卡死
- provider 返回后显示 actual usage；如果网关不返回 usage，则标记 unavailable
- 终端默认逐行轻微输出，避免一次性刷一大屏；`QUANTAGENT_TYPE_DELAY_MS=0` 可关闭
- 默认回答保持短小，一次推进一个小步骤；大型报告用 `--long --save-report`
- 思考心跳默认按 120Hz 目标刷新，约 8ms 一跳；觉得太快或太耗 CPU 可以设置 `QUANTAGENT_SPINNER_INTERVAL_MS=16` 或 `120`

聊天框里可以直接跑本地安全工具：

```text
/help
/validate
/audit
/doctor
/skills P4逐笔验证滑点容量证据hash
/watch
/state
/run-next 只做逐笔到货前的安全准备检查
```

这些 slash 命令是本地工具调用，不会先走模型闲聊。`/run-next` 会调用角色编排模型，可能消耗 token。

只有需要完整复盘或写大型报告时才用：

```bash
mako chat --deep-context --long --save-report
```

## 执行安全边界

`quantagent.tools.run_command(...)` 是兼容用户输入字符串的策略门，不是 OS sandbox。它会先调用 `assess_command(...)`，只有 `L0_READ_OR_SAFE` 和 `L1_GUARDED_WRITE` 这类明确 `ALLOW` 的命令会真正进入 `shell=True`；`ASK`/`DENY` 会直接返回 blocked，即使调用方传入 `allow_risky=True` 也不会放行 user-facing shell。

新内部工具应使用 `run_command_args([...])`。该路径用 `subprocess.run(..., shell=False)` 执行 argv，减少命令注入、变量展开和路径空格解析风险。

## 自测

Mako starter 的 smoke/self-test 不需要额外依赖：

```bash
python3 -m unittest discover -s tests
```

## 前十个借鉴点已落地

1. Agent loop: `quantagent/agent_loop.py`
2. Tool registry: `quantagent/tool_registry.py`
3. Permission guard: `quantagent/guards.py`, `quantagent/tools.py`
4. Project memory: `quantagent/project.py`, `quantagent/context_pack.py`
5. Validation pipeline: `quantagent/validation.py`
6. Context compression: `quantagent/state.py`
7. Todo system: `quantagent/todo.py`
8. Multi-agent review: `quantagent/multi_agent.py`
9. Structured tool results: `quantagent/result_schema.py`
10. Hook mechanism: `quantagent/hooks.py`
11. Experiment runner: `quantagent/experiment_runner.py`
12. Result registry: `quantagent/result_registry.py`
13. Quant auditor: `quantagent/quant_auditor.py`
14. Claude-like safety policy: `quantagent/safety.py`, `docs/SAFETY_POLICY.md`
15. OpenAI-compatible model client: `quantagent/model_client.py`, `docs/OPENAI_COMPATIBLE_SETUP.md`
16. Three-agent consensus gate: `quantagent/consensus.py`
17. Hallucination guard: `docs/HALLUCINATION_GUARD.md`
18. Terminal chat UI: `quantagent/chat_ui.py`
19. Context engine: `quantagent/context_pack.py`, `docs/CONTEXT_ENGINE.md`
20. Role orchestration and auto loop: `quantagent/orchestrator.py`, `quantagent/auto_runner.py`
21. Built-in and project-installed quant skills: `quantagent/skills.py`
22. Chat slash tools and doctor scorecard: `quantagent/chat_ui.py`, `quantagent/doctor.py`
23. SQLite runtime store for task/session/query/skill snapshot mirrors: `quantagent/runtime_store.py`
24. Plugin registry metadata and diagnostics: `quantagent/plugin_runtime.py`
25. Prioritized hook runner: `quantagent/hook_runner.py`
26. Resumable approvals and tool invocation envelopes: `quantagent/approvals.py`, `quantagent/tool_execution.py`
27. Minimal stdio MCP runtime: `quantagent/mcp_runtime.py`
28. Subagent lifecycle store: `quantagent/subagents.py`
29. Preview-gated patch planner/executor and repair classification: `quantagent/edit_loop.py`
30. OpenClaw-style lifecycle hooks: `quantagent/lifecycle_hooks.py`, `quantagent/hook_runner.py`
31. Hermes-style session search/export metadata: `quantagent/sessions.py`, `quantagent/runtime_store.py`
32. Cursor-style lightweight codebase index and checkpoints: `quantagent/code_index.py`, `quantagent/checkpoints.py`
33. Tool-call transcript replay: `quantagent/tool_transcript.py`, `quantagent/runtime_store.py`
34. Claude Code-style task-bound checklist: `quantagent/todo.py`, `quantagent/task_state.py`
35. OpenClaw-style long-lived MCP leases and env whitelist: `quantagent/mcp_runtime.py`
36. OpenCode-style agent profiles, permission matrix, config layering, and instructions: `quantagent/agent_profiles.py`
37. Aider/Sweep-style diff-first patch path: `quantagent/edit_loop.py`
38. Systematic debugging and TDD skills: `quantagent/skills.py`
39. Long-task compact/resume snapshots: `quantagent/resume.py`, `quantagent/trajectory_compact.py`
40. Code index diagnostics and dependency graph: `quantagent/code_index.py`
41. Plugin manifest policy validation: `quantagent/plugin_runtime.py`
42. Unified UX status surface for context/session/tools/approvals/reviews/checkpoints: `quantagent/ux_status.py`
42. Conservative auto patch/test loop: `quantagent/edit_loop.py`
43. Worktree isolation runner: `quantagent/worktree_isolation.py`
44. MCP HTTP/SSE transport and process-local manager: `quantagent/mcp_runtime.py`
45. Model-driven isolated repair loop: `quantagent/edit_loop.py`
46. Market OSS copy map and license gate: `docs/MARKET_TOOL_COPY_SCAN.md`
46. Ten-lane clean-room agent porting board: `docs/AGENT_PORTING_SWARM.md`
47. Direct-vendored Aider/SWE-agent/vn.py/Hummingbot source batch:
    `third_party/aider`, `third_party/swe_agent`, `third_party/vnpy`,
    `third_party/hummingbot`
48. vn.py/Hummingbot-style broker gateway normalization for fills/orders/accounts:
    `quantagent/broker_gateway.py`, wired into `quantagent/quant_execution_gate.py`
49. Great Expectations/Pandera-style quant expectation suites for market/tick/fill
    CSV evidence: `quantagent/quant_expectations.py`
50. Real local data sampler for 2061 daily bars, minute K zips, and tick 7z:
    `quantagent/quant_data_sample.py`

## 设计原则

1. 结果必须可复现。
2. 每次改动必须验证。
3. 任何 PF 提升都先假设可能是数据污染。
4. 真实成交优先于漂亮回测。
5. 禁止使用未去重的 1253 笔旧样本做结论。

## Next Port Notes

- `docs/CLAUDE_SRC_ABSORPTION_PLAN.md`: clean-room mechanism blueprint from the
  local source review, mapped to OpenMako modules and tests.
- `docs/SOURCE_COPY_BORROW_MATRIX.md`: what can be copied, ported, or only
  studied from OpenClaw, Hermes, and Claude-like source.
- `docs/AGENT_PORTING_SWARM.md`: 10-lane legal porting board for OpenHands,
  SWE-agent, Aider, browser-use, Goose, LangGraph, and closed-product mechanics.
- `docs/OPENMAKO_NEXT_PORTS.md`: prioritized OpenClaw/Hermes-inspired backlog.
- `.quantagent/skills/subagent-two-stage-review/SKILL.md`: parent/worker review workflow.
- `.quantagent/plugin_template/openmako.plugin.json`: governed plugin manifest template.
