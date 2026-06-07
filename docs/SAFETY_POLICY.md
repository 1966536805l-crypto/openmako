# QuantAgent Safety Policy

Internal legacy QuantAgent policy note. This is not the current public v0.1 capability claim; the current public proof command is `./scripts/public_review_gate.sh`.

这套边界模仿 Claude Code 的核心思想，但面向量化项目重写：默认听从用户，只有当动作会破坏用户真实目标时才拦截。

## 核心原则

1. 用户目标优先：保护策略可信度、原始数据、账号资金、密钥和本机环境。
2. 分层授权：读操作放行，实验产物放行，项目数据/源码修改需要明确意图，高危系统操作拒绝。
3. 可审计：每次被拦截都给出原因和风险级别。
4. 结果门槛：PF、2025 衰退、09:30 成交、容量结论必须带证据上下文。

## 重要边界

这是策略护栏，不是系统级沙箱。`qagent` 会尽量在执行前识别写入、删除、账号资金、密钥和原始数据风险；它不能替代 chroot、容器、虚拟机、macOS sandbox、Linux namespace 或文件系统权限。

面向用户输入的字符串命令只走 `run_command(...)`，并且只执行策略明确 `ALLOW` 的命令：

- `L0_READ_OR_SAFE`: 低风险读命令或低影响验证。
- `L1_GUARDED_WRITE`: 写入目标能静态解析，且全部落在允许的 QuantAgent 输出目录内。

其他 `ASK`/`DENY` 决策都会被阻断；调用方不能用 `allow_risky=True` 让 user-facing shell 执行 review/deny 命令。内部工具优先使用 `run_command_args([...], shell=False)`，避免路径带空格、变量展开和 shell 拼接问题。

由于 shell 会在策略解析后继续处理元字符，user-facing shell 默认把命令替换、反引号、环境变量展开、输入重定向、管道、`;`、`&&`、`||`、后台 `&`、不可见空白等视为需要复核的语法。需要更复杂的内部流程时，应拆成参数化工具调用，而不是拼接一整段 shell。

`L5_HARDLINE` 是无条件阻断层，改写自 Hermes Agent 的 MIT-licensed dangerous-command guard。即使内部 argv 工具传入 `allow_risky=True`，也不能执行递归删除根目录/家目录、`mkfs`、写 raw block device、fork bomb、shutdown/reboot、`sudo -S` 等不可恢复命令。

命令 stdout/stderr 在进入模型上下文前会剥离 ANSI/control escape sequences。超过 `QUANTAGENT_TOOL_OUTPUT_MAX_CHARS` 的输出会写入 `.quantagent/tool_results/`，上下文里只保留 preview 和完整文件路径。可配置：

- `QUANTAGENT_TOOL_OUTPUT_MAX_CHARS`
- `QUANTAGENT_TOOL_OUTPUT_PREVIEW_CHARS`
- `QUANTAGENT_TOOL_OUTPUT_TURN_BUDGET_CHARS`

这些预算来自 Hermes Agent 的 tool output persistence 思路；当前实现只做 per-output persistence，turn budget 字段保留给后续 tool-loop 聚合预算。

`tool_loop` 和 `agent_v2` 的工具/命令执行现在统一经过 `quantagent/tool_execution.py`。每个结果都会携带 policy metadata、耗时、blocked 状态和错误类型；严格模式可以在进入 subprocess 前返回结构化 `policy_blocked` 结果。`quantagent/path_policy.py` 负责项目路径判定，读操作要求路径解析后仍在项目内，写操作只默认放行 `.quantagent` 和 `AI_协作交接` 输出目录，raw/tick 路径直接拒绝。

## 风险等级

- L0: 读文件、查看状态、运行低影响验证，默认允许。
- L1: 写入 `AI_协作交接`、`quantagent_results`、`.quantagent`，且写入目标可解析，默认允许。
- L2: 修改项目源码或数据衍生文件，需要明确意图。
- L3: 删除、移动、覆盖项目文件，需要人工复核。
- L4: 原始逐笔/tick 数据、账号、密钥、资金动作、主机级修改，默认保护。
- L5: 宽泛系统破坏动作，例如 `rm -rf /`、格式化磁盘，直接拒绝。

## 输入来源

跨 session 或内部工具转发来的 user-role 文本会加 `[Inter-session message]` 前缀，并标注 `isUser=false`。这改写自 OpenClaw 的 input provenance 设计，目的是防止内部转发内容伪装成当前会话的直接用户指令。metadata 会被压成单行安全标识，避免 header 注入。

## 量化结论边界

- 禁止把未去重 1253 笔污染样本当干净结论。
- PF 必须说明去重基准或证据来源。
- 09:30 执行结论必须说明滑点、成交额占比、容量假设。
- `(-9,-8]` 区间目前只作诊断信号，不能直接升级为主策略。
- 时间硬限制、冷却期、连续止损暂停已经多次证明有害，不能重复当优化方向。

## 本地命令

```bash
qagent safety --project "/path/to/your/quant/project"
qagent safety --check-command "rm -rf AI_协作交接/tick_raw"
qagent safety --check-claim "PF=2.1"
```

## 允许的默认写入目录

- `AI_协作交接`
- `AI_协作交接/quantagent_results`
- `.quantagent`

原始行情、逐笔、tick、Level2 数据路径默认只读。需要整理这类数据时，先复制到衍生数据目录，再记录来源、hash 和处理脚本。
