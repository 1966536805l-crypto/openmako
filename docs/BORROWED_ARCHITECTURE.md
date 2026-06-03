# 安全借鉴清单

这份清单把 Claude Code 里值得学习的部分抽象成 QuantAgent 设计，不复制实现代码。

## 1. Agent Loop

好的点：模型输出不直接等于最终答案，而是经过工具执行、结果回填、再次判断。

QuantAgent 对应设计：

- `agent_loop.py`: 统一任务入口。
- `context_pack.py`: 每轮先生成可审计上下文。
- 后续加入 `actions` 后，所有行动都必须留下日志。

## 2. Context Pack

好的点：启动时自动收集项目规则、近期消息、配置、文件状态。

QuantAgent 对应设计：

- 自动读 `CLAUDE.md`
- 自动读最新 `AI_协作交接/*.md`
- 自动列出基准 CSV 和 P4/P5/P6 脚本
- 输出 `QUANTAGENT_CONTEXT_PACK.md`

## 3. Tool Registry

好的点：工具不是散落在各处，而是有统一注册、风险分级、执行边界。

QuantAgent 对应设计：

- `tool_registry.py`: 工具名、说明、风险级别。
- `tools.py`: 统一执行命令并先过 guard。
- 未来可加入 `requires_confirmation` 和 `allowed_paths`。

## 4. Guard Rails

好的点：越自动越需要边界，尤其是 shell 和文件写入。

QuantAgent 对应设计：

- 拦截明显危险命令。
- 拦截量化项目里的污染样本和常见错误引用。
- PF 没有去重上下文时提示风险。

## 5. Validation Pipeline

好的点：改完不是结束，验证通过才算结束。

QuantAgent 对应设计：

- `validation.py`: 统一验证 P4/P5/P6 脚本。
- `validate` 命令会写入 `QUANTAGENT_JOURNAL.md`。
- 后续逐步加入回测 smoke test、字段检查、逐笔覆盖率检查。

## 6. Journal Trail

好的点：每次状态变化要有可追踪记录。

QuantAgent 对应设计：

- `journal.py`: 追加式日志。
- 关键实验、审计、验证都写入交接目录。

## 不借鉴

- 不运行泄露包。
- 不复制源码。
- 不做封号规避。
- 不把遥测/远程会话作为默认能力。
- 不把模型协议绑死在某一家供应商上。

## 当前实现映射

- Agent loop: `quantagent/agent_loop.py`
- Tool registry: `quantagent/tool_registry.py`
- Permission guard: `quantagent/guards.py`
- Project memory: `quantagent/project.py`
- Validation pipeline: `quantagent/validation.py`
- Context compression: `quantagent/state.py`
- Todo system: `quantagent/todo.py`
- Multi-agent review request: `quantagent/multi_agent.py`
- Structured results: `quantagent/result_schema.py`
- Hook mechanism: `quantagent/hooks.py`
