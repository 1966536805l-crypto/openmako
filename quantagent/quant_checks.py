from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AuditFinding:
    level: str
    title: str
    detail: str
    path: Path | None = None


def audit_csv_duplicates(path: Path) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    if not path.exists() or path.suffix.lower() != ".csv":
        return findings

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except OSError as exc:
        return [AuditFinding("error", "CSV read failed", str(exc), path)]

    if not rows:
        return findings

    key_candidates = [
        ("symbol", "entry_date", "return"),
        ("ts_code", "entry_date", "return"),
        ("code", "entry_date", "return"),
        ("stock", "entry_date", "return"),
        ("code", "entry_date"),
        ("symbol", "entry_date"),
        ("ts_code", "entry_date"),
        ("stock", "entry_date"),
    ]
    fields = set(rows[0].keys())
    key = next((k for k in key_candidates if set(k).issubset(fields)), None)
    if not key:
        return findings

    seen: set[tuple[str, ...]] = set()
    duplicates = 0
    for row in rows:
        value = tuple(str(row.get(col, "")) for col in key)
        if value in seen:
            duplicates += 1
        seen.add(value)

    if duplicates:
        findings.append(
            AuditFinding(
                "error",
                "Duplicate trades detected",
                f"{path.name}: {duplicates} duplicate rows by {key}",
                path,
            )
        )
    return findings


def audit_known_project_rules(project: Path) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    comm = project / "AI_协作交接"
    required = [
        comm / "agent2_scenario_A_0p2_0p2_position_dedup.csv",
        comm / "agent2_scenario_D_0p3_0p3_position_dedup.csv",
    ]
    for path in required:
        if not path.exists():
            findings.append(
                AuditFinding(
                    "warn",
                    "Missing dedup baseline",
                    f"Expected baseline not found: {path}",
                    path,
                )
            )

    polluted = [
        comm / "agent2_scenario_A_0p2_0p2_position.csv",
        comm / "agent2_scenario_D_0p3_0p3_position.csv",
    ]
    for path in polluted:
        if path.exists():
            findings.append(
                AuditFinding(
                    "warn",
                    "Polluted original baseline present",
                    "Do not use original 1253-trade file for conclusions. Use *_dedup.csv only.",
                    path,
                )
            )

    return findings


def audit_project(project: Path) -> list[AuditFinding]:
    findings = audit_known_project_rules(project)
    for path in project.glob("**/*_dedup.csv"):
        findings.extend(audit_csv_duplicates(path))
    return findings

