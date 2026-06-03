from __future__ import annotations

import shlex


DANGEROUS_COMMAND_PATTERNS = [
    "rm -rf /",
    "rm -rf ~",
    "diskutil erase",
    "mkfs",
    "dd if=",
    "launchctl load",
    "chmod -R 777 /",
    "sudo rm",
]


QUANT_FORBIDDEN_PATTERNS = [
    "agent2_scenario_A_0p2_0p2_position.csv",
    "agent2_scenario_D_0p3_0p3_position.csv",
    "1253",
    "exit_price reuse",
    "09:25 buy",
]


def command_risk(command: str) -> list[str]:
    lowered = command.lower()
    issues = [p for p in DANGEROUS_COMMAND_PATTERNS if p in lowered]
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = []
    if tokens[:2] == ["rm", "-rf"] and len(tokens) <= 3:
        issues.append("broad rm -rf")
    return sorted(set(issues))


def quant_text_risk(text: str) -> list[str]:
    lowered = text.lower()
    issues: list[str] = []
    for pattern in QUANT_FORBIDDEN_PATTERNS:
        if pattern.lower() in lowered:
            issues.append(f"check forbidden or risky reference: {pattern}")
    if "pf=" in lowered and "dedup" not in lowered and "去重" not in lowered:
        issues.append("PF mentioned without dedup context")
    if "open price" in lowered and "slippage" not in lowered:
        issues.append("entry price mentioned without slippage context")
    return issues

