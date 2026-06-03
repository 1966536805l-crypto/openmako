from __future__ import annotations

import json
from pathlib import Path

from .quant_checks import AuditFinding, audit_csv_duplicates, audit_known_project_rules


REQUIRED_TRADE_COLUMNS = {
    "code",
    "entry_date",
    "entry_time",
    "exit_date",
    "entry_price",
    "exit_price",
    "net_return",
    "t1_auction_return",
}


def audit_trade_csv(path: Path) -> list[AuditFinding]:
    import csv

    findings = audit_csv_duplicates(path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
        rows = list(reader)

    missing = sorted(REQUIRED_TRADE_COLUMNS - fields)
    if missing:
        findings.append(
            AuditFinding("warn", "Missing expected trade columns", ", ".join(missing), path)
        )
    if "dedup" not in path.name and "tick_data_request" not in path.name:
        findings.append(
            AuditFinding(
                "warn",
                "CSV name does not indicate dedup",
                "Strategy conclusions should use *_dedup.csv files only.",
                path,
            )
        )
    if len(rows) == 1253:
        findings.append(
            AuditFinding(
                "error",
                "Polluted original 1253-row sample",
                "Do not use this file for conclusions.",
                path,
            )
        )
    if rows and {"entry_date", "exit_date"}.issubset(fields):
        bad_dates = 0
        for row in rows:
            if str(row.get("exit_date", "")) < str(row.get("entry_date", "")):
                bad_dates += 1
        if bad_dates:
            findings.append(
                AuditFinding("error", "Exit date before entry date", f"{bad_dates} rows", path)
            )
    return findings


def audit_experiment_result(path: Path) -> list[AuditFinding]:
    data = json.loads(path.read_text(encoding="utf-8"))
    findings: list[AuditFinding] = []
    input_path = str(data.get("input_path", ""))
    metrics = data.get("metrics", {})
    yearly = data.get("yearly", {})
    trades = metrics.get("trades", 0)
    pf = metrics.get("profit_factor")

    if "dedup" not in input_path:
        findings.append(
            AuditFinding("error", "Experiment input not dedup-marked", input_path, path)
        )
    if not trades:
        findings.append(AuditFinding("error", "Experiment has zero trades", path=path, detail=""))
    if pf is not None and pf > 3.0:
        findings.append(
            AuditFinding(
                "warn",
                "Very high PF needs adversarial review",
                f"PF={pf}; verify sample, slippage, and duplicate handling.",
                path,
            )
        )
    if "2025" not in yearly:
        findings.append(
            AuditFinding("warn", "Missing 2025 split", "2025 degradation must be visible.", path)
        )
    if data.get("threshold_col") == "t1_auction_return" and data.get("threshold_lte") is None:
        findings.append(
            AuditFinding("warn", "Auction threshold not set", "Key candidate should test <= -9.", path)
        )
    return findings


def audit_target(project: Path, target: Path | None = None) -> list[AuditFinding]:
    findings = audit_known_project_rules(project)
    if target:
        if target.suffix.lower() == ".csv":
            findings.extend(audit_trade_csv(target))
        elif target.suffix.lower() == ".json":
            findings.extend(audit_experiment_result(target))
        else:
            findings.append(AuditFinding("warn", "Unsupported audit target", str(target), target))
        return findings

    comm = project / "AI_协作交接"
    for path in sorted(comm.glob("*position_dedup.csv")):
        findings.extend(audit_trade_csv(path))
    registry_dir = comm / "quantagent_results"
    if registry_dir.exists():
        for path in sorted(registry_dir.glob("*.json")):
            if path.name != "registry.json":
                findings.extend(audit_experiment_result(path))
    return findings

