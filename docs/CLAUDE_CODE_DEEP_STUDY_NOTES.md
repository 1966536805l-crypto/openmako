# Claude Code Deep Study Notes For QuantAgent

本文件是对 Claude Code 源码的高层架构学习笔记。不复制源码，不运行未知包，只提炼适合 QuantAgent 的设计。

## 已确认值得学习的核心模式

### 1. Tool Orchestration

Claude Code 不是简单地按顺序执行所有工具。它会把工具调用分成两类：

- concurrency-safe: 读文件、搜索、状态查询等可以并发。
- exclusive: 写文件、执行命令、改状态等必须串行。

QuantAgent 对应落地：

- 数据读取、CSV 统计、报告扫描可以并发。
- 回测、写 registry、写状态、删改文件必须串行。
- 后续应给每个工具加 `concurrency_safe` 字段。

### 2. Streaming Tool Executor

它支持工具调用边流式生成边进入队列，而不是等模型完整输出后再执行。关键思想不是“快”，而是：

- 工具状态可追踪：queued/executing/completed/yielded。
- 出错后能取消兄弟任务，避免错误结果继续污染上下文。
- 结果按工具出现顺序回填，避免模型误读。

QuantAgent 对应落地：

- 每个实验任务应有状态机：queued/running/passed/failed/aborted.
- 一组实验里如果基准数据审计失败，后续实验直接取消。
- 结果写入顺序固定：audit -> experiment -> validation -> registry。

### 3. Hook System

Hook 不只是通知。它可以：

- 在工具执行前拦截。
- 在工具执行后追加上下文。
- 在失败后触发修复/记录。
- 在压缩、会话开始、会话结束、文件变化时触发动作。

QuantAgent 对应落地：

- PreExperiment: 检查数据是否 dedup、字段是否完整。
- PostExperiment: 自动跑 QuantAuditor。
- FailureHook: 自动写失败报告和可复现命令。
- FileChangedHook: 交接目录出现新文件时重建 context pack。

### 4. Context Compaction

它不是粗暴总结，而是带预算和恢复机制：

- 到阈值才压缩。
- 压缩前去掉图片/重复附件等低价值内容。
- 压缩后恢复关键文件、技能、计划、工具列表。
- 连续失败有熔断，避免无限重试。

QuantAgent 对应落地：

- `PROJECT_STATE_COMPACT.md` 不能只是流水账，要分层保留：
  - 不可违背规则
  - 当前基准
  - 已废弃方向
  - 待验证假设
  - 最新可复现实验
- 逐笔数据到来后，context pack 必须避免塞大 CSV，只放 schema、覆盖率和结果路径。

### 5. Session Memory

它用后台子代理周期性提取会话记忆，并且有触发阈值：

- token 增长达到阈值。
- 工具调用次数达到阈值。
- 最后一轮没有工具调用时更适合提取。

QuantAgent 对应落地：

- 每跑 N 个实验，自动更新 `PROJECT_STATE_COMPACT`.
- 每新增一个重要结论，自动写入 `KNOWN_CONCLUSIONS`.
- 每废弃一个方向，写入 `REJECTED_IDEAS`.

### 6. Agent Summary

它给后台 agent 做短状态摘要，用 3-5 个词描述当前动作。这点很小，但很实用。

QuantAgent 对应落地：

- 长实验运行时显示：
  - `reading baseline`
  - `checking duplicates`
  - `running threshold grid`
  - `writing registry`
- 以后终端界面可以显示多个子任务的实时短状态。

### 7. Diagnostic Registry

LSP 诊断不是直接刷屏，而是进入 registry：

- 去重。
- 限流。
- 按严重度排序。
- 跨轮次避免重复提示。

QuantAgent 对应落地：

- QuantDiagnosticRegistry:
  - 数据重复诊断
  - 未来函数诊断
  - PF 异常诊断
  - 2025 衰退诊断
  - 成交容量诊断
- 相同问题只提示一次，除非文件或结果变了。

### 8. Permission Rule Sources

权限规则有来源层级：配置、命令、会话、用户设置、策略设置。它不是一个简单 allow/deny。

QuantAgent 对应落地：

- 风控规则也要分来源：
  - hard_rule: 永久禁用，比如 1253 污染样本。
  - project_rule: 当前策略阶段规则，比如先 P4 再优化。
  - session_rule: 本次临时允许，比如只读某个大目录。
  - experiment_rule: 本实验特有约束。

### 9. Forked Subagents

它的 fork 思路很强：

- 子代理继承父上下文。
- 子代理有明确 directive。
- 子代理禁止继续乱分叉。
- 输出格式强制结构化。
- 独立 worktree 可隔离修改。

QuantAgent 对应落地：

- `researcher`: 跑实验。
- `auditor`: 专门找错。
- `data_engineer`: 检查字段/单位/覆盖率。
- `execution_checker`: 逐笔成交验证。
- 子 agent 输出必须包含：Scope/Result/Files/Issues/Verdict。

### 10. Tool Search / Deferred Tools

工具太多时，不一次性全部塞给模型，而是按需搜索/加载。它用工具名、描述、MCP 前缀等做检索。

QuantAgent 对应落地：

- 先不要把所有量化工具都暴露。
- 根据任务动态选：
  - 回测任务 -> backtest tools
  - 逐笔任务 -> tick tools
  - 风控任务 -> risk tools
  - 图表任务 -> plotting tools
- 大幅减少模型上下文浪费。

### 11. Todo Verification Nudge

Todo 全部完成时，如果没有验证任务，它会提醒必须验证。这是非常适合量化的机制。

QuantAgent 对应落地：

- Todo 完成前必须有至少一个验证项：
  - py_compile
  - sample count check
  - PF recompute
  - 2025 split
  - audit pass
- 否则不允许标记为 done。

### 12. Tool Result Storage / Compression

大工具结果不能无限塞上下文，要能落盘、摘要、引用路径。

QuantAgent 对应落地：

- 大 CSV 不进上下文。
- 大实验结果只进 summary，完整 JSON/CSV 写 registry。
- 后续模型只看 result id 和摘要，需要时再打开文件。

## 暂时不该借鉴

- 封号/限制规避相关内容。
- 官方遥测外发机制。
- 复杂远程会话和移动端桥接。
- 直接运行或改造泄露包。
- 为了兼容 Claude 协议去硬改 GPT 网关。

## QuantAgent 下一批升级优先级

1. `tool_concurrency`: 给工具加并发安全标签，读类并发，写类串行。
2. `experiment_state_machine`: 每个实验有 queued/running/passed/failed/aborted。
3. `quant_diagnostic_registry`: 诊断去重、限流、严重度排序。
4. `verification_nudge`: Todo 完成前强制至少一次验证。
5. `tool_result_storage`: 大结果落盘，context 只放摘要和路径。
6. `deferred_quant_tools`: 按任务动态加载回测/逐笔/风控/绘图工具。
7. `subagent_contracts`: 给 researcher/auditor/data_engineer/execution_checker 定义固定输出格式。
8. `post_experiment_hooks`: 实验后自动 QuantAuditor + registry。
9. `context_budget`: context pack 加 token/字符预算。
10. `failure_replay`: 失败时自动保存可复现命令和输入文件。

## Claude Independent Review Additions

这一节来自另一模型对本笔记的架构复核，已筛掉不适合量化落地的部分。

### A. Run-ID 内容寻址

所有实验都应该用稳定 hash 生成 run-id，而不是简单时间戳。hash 输入至少包括：

- data_hash
- params
- code_version
- fee/slippage model
- seed
- library versions

作用：

- 相同实验直接命中缓存，不重复跑。
- 两次结果不同可以定位是哪一维变化。
- 并行实验不会互相覆盖。

### B. Spec-Lock 实验规格冻结

实验执行前先生成 spec 文件和 hash。执行中如果参数、费率、滑点、资金曲线规则变化，本次 run 必须作废。

量化里很常见的污染是边跑边调参数，最后忘了结果来自哪套假设。Spec-Lock 专门堵这个洞。

### C. 兄弟任务取消传播

同一 baseline 的一组网格实验中，只要前置 audit 发现数据污染，整批实验都应该取消。

例如：

- 发现使用 1253 污染样本
- 发现成交额单位错误
- 发现 entry/exit 时间线错误

不要等所有实验跑完后才发现全废。

### D. Verdict 三态门控

审计结果不能只有 pass/fail，还必须有：

- PASS
- FAIL
- INCONCLUSIVE

其中 INCONCLUSIVE 必须阻断晋级。量化里最危险的是灰区被默认为通过。

### E. 数据 Freshness 与失效级联

每个数据文件和实验结果都要带：

- data_revision
- captured_at
- source
- schema_hash

一旦逐笔数据补抓、修订或字段单位确认变化，下游结果自动标记 stale。

### F. Pre-LLM Redaction

所有进入模型的大结果先瘦身：

- 大数组 -> 分位数、计数、极值
- 逐笔数据 -> schema、覆盖率、hash、抽样
- PnL 序列 -> 关键拐点、最大回撤区间
- 日志 -> 折叠后的 warning 统计

原则：大数据永远落盘，模型只看摘要和路径。

### G. 日志级去重折叠

回测和逐笔验证会产生大量重复 warning。需要按指纹折叠：

- code_location
- message_template
- severity

输出：

- count
- first_seen
- last_seen
- examples

### H. 数据源 Adapter Capability

不同数据源不要在策略里硬编码 vendor 分支。每个 adapter 声明能力：

- has_tick
- has_amount
- has_queue_position
- tick_granularity
- has_fees
- has_order_book

execution_checker 根据 capability 决定能验证到什么程度。

### I. Per-Run 隔离目录

每个实验写入：

```text
runs/<run-id>/
  spec.json
  result.json
  report.md
  audit.json
  logs/
```

不要让多个实验共享可变输出文件。

## 新的前三优先级

1. `run_id + per_run_dir`: 解决重复劳动和结果追溯。
2. `verdict_gate`: 用 PASS/FAIL/INCONCLUSIVE 阻断灰区放行。
3. `pre_llm_redaction`: 防止逐笔/盘口大对象污染上下文。
