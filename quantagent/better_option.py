from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .quant_priority import build_quant_priority_review, is_quant_task


@dataclass(frozen=True)
class BetterOptionHint:
    available: bool
    message: str = ""
    reason: str = ""
    action: str = "none"
    requires_confirmation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def suggest_better_option(task: str, *, goal: str = "", mode: str = "") -> BetterOptionHint:
    text = " ".join([task, goal, mode]).lower()
    if is_quant_task(text):
        review = build_quant_priority_review(Path("."), task, answer=goal, audit=False)
        if review.action in {"block", "warn"}:
            return BetterOptionHint(
                True,
                "更优解提示：先走量化证据门，补 dedup baseline、artifact/hash、分年/OOS、滑点/容量/成交证据，再给结论。",
                "量化任务已被识别；无证据的指标或执行结论会被降级为未知/未验证。",
                "quant_priority_gate",
                False,
            )
    if any(token in text for token in ("score", "多少分", "line count", "行数", "tests", "测试数", "价格", "日期")):
        return BetterOptionHint(
            True,
            "更优解提示：先用命令或来源验证数据，再回答具体数字。",
            "数据不确定不能当事实说；验证成本低且更符合准确性目标。",
            "verify_before_answer",
            False,
        )
    if any(token in text for token in ("implement", "fix", "修改", "实现", "修复", "开干")):
        return BetterOptionHint(
            True,
            "更优解提示：用 agent-v3 默认路径执行，自动经过 mode routing、goal/data guard、runtime context 和轨迹记录。",
            "这比旧 tool-loop 更接近目标，并且不扩大风险。",
            "use_agent_v3",
            False,
        )
    if any(token in text for token in ("全抄", "copy claude", "claudecode", "源码直接")):
        return BetterOptionHint(
            True,
            "更优解提示：做 clean-room 复刻架构，不复制闭源代码文本。",
            "这样能学到能力边界，同时避免许可证和来源风险。",
            "clean_room_port",
            False,
        )
    return BetterOptionHint(False)


def apply_better_option_prefix(answer: str, hint: BetterOptionHint) -> str:
    if not hint.available or not hint.message:
        return answer
    if answer.startswith(hint.message):
        return answer
    return hint.message + "\n\n" + answer.lstrip()


def render_better_option_hint(hint: BetterOptionHint) -> str:
    if not hint.available:
        return "No better option hint.\n"
    lines = [
        "# Better Option Hint",
        "",
        f"- action: {hint.action}",
        f"- requires_confirmation: {str(hint.requires_confirmation).lower()}",
        f"- message: {hint.message}",
        f"- reason: {hint.reason}",
    ]
    return "\n".join(lines) + "\n"
