from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .metrics import to_float
from .quant_checks import audit_csv_duplicates


ERROR = "error"
WARN = "warn"
INFO = "info"


@dataclass(frozen=True)
class DataContractIssue:
    level: str
    code: str
    message: str
    column: str = ""
    count: int = 0
    sample: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuantDataContractResult:
    path: str
    kind: str
    ok: bool
    rows: int
    columns: tuple[str, ...]
    sha256: str = ""
    issues: tuple[DataContractIssue, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "ok": self.ok,
            "rows": self.rows,
            "columns": list(self.columns),
            "sha256": self.sha256,
            "issues": [issue.to_dict() for issue in self.issues],
            "metadata": self.metadata,
        }


def validate_quant_data_contract(
    path: str | Path,
    *,
    kind: str = "auto",
    strict_dedup: bool = False,
) -> QuantDataContractResult:
    csv_path = Path(path).expanduser().resolve(strict=False)
    issues: list[DataContractIssue] = []
    if not csv_path.exists():
        return QuantDataContractResult(str(csv_path), kind, False, 0, (), issues=(DataContractIssue(ERROR, "missing_file", "CSV file does not exist"),))
    if csv_path.suffix.lower() != ".csv":
        return QuantDataContractResult(str(csv_path), kind, False, 0, (), issues=(DataContractIssue(ERROR, "not_csv", "Data contract currently supports CSV files only"),))

    try:
        fieldnames, rows = _read_csv(csv_path)
    except OSError as exc:
        return QuantDataContractResult(str(csv_path), kind, False, 0, (), issues=(DataContractIssue(ERROR, "read_failed", str(exc)),))

    detected_kind = _detect_kind(fieldnames, kind)
    issues.extend(_schema_issues(fieldnames, detected_kind))
    issues.extend(_row_quality_issues(rows, fieldnames, detected_kind))
    issues.extend(_duplicate_issues(csv_path))
    issues.extend(_baseline_issues(csv_path, len(rows), strict_dedup=strict_dedup))

    years = _years(rows, "entry_date" if "entry_date" in fieldnames else "date")
    metadata = {
        "detected_kind": detected_kind,
        "years": years,
        "year_count": len(years),
    }
    if detected_kind == "trade_csv" and len(years) == 1:
        issues.append(
            DataContractIssue(
                WARN,
                "single_year_sample",
                "Only one year is present; metric conclusions need OOS/yearly split evidence.",
                sample=years[0],
            )
        )

    ok = not any(issue.level == ERROR for issue in issues)
    return QuantDataContractResult(
        path=str(csv_path),
        kind=detected_kind,
        ok=ok,
        rows=len(rows),
        columns=tuple(fieldnames),
        sha256=_sha256_file(csv_path),
        issues=tuple(issues),
        metadata=metadata,
    )


def render_quant_data_contract(result: QuantDataContractResult) -> str:
    lines = [
        "# Quant Data Contract",
        "",
        f"- path: {result.path}",
        f"- kind: {result.kind}",
        f"- ok: {str(result.ok).lower()}",
        f"- rows: {result.rows}",
        f"- columns: {len(result.columns)}",
        f"- sha256: `{result.sha256}`" if result.sha256 else "- sha256: -",
        "",
        "## Issues",
        "",
    ]
    if not result.issues:
        lines.append("- none")
    for issue in result.issues:
        suffix = f" column={issue.column}" if issue.column else ""
        count = f" count={issue.count}" if issue.count else ""
        sample = f" sample={issue.sample}" if issue.sample else ""
        lines.append(f"- [{issue.level}] {issue.code}{suffix}{count}{sample}: {issue.message}")
    lines.extend(["", "## Metadata", "", "```json", json.dumps(result.metadata, ensure_ascii=False, indent=2, sort_keys=True), "```"])
    return "\n".join(lines).rstrip() + "\n"


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = [name for name in (reader.fieldnames or []) if name is not None]
        rows = list(reader)
    return fieldnames, rows


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _detect_kind(fieldnames: list[str], requested: str) -> str:
    if requested and requested != "auto":
        return requested
    fields = set(fieldnames)
    if {"entry_date", "net_return"}.issubset(fields):
        return "trade_csv"
    if {"date", "return"}.issubset(fields):
        return "return_series"
    return "generic_csv"


def _schema_issues(fieldnames: list[str], kind: str) -> list[DataContractIssue]:
    issues: list[DataContractIssue] = []
    if not fieldnames:
        return [DataContractIssue(ERROR, "missing_header", "CSV has no header")]
    duplicates = sorted({name for name in fieldnames if fieldnames.count(name) > 1})
    for column in duplicates:
        issues.append(DataContractIssue(ERROR, "duplicate_column", "Duplicate CSV column", column=column))
    required = {
        "trade_csv": ("entry_date", "net_return"),
        "return_series": ("date", "return"),
        "generic_csv": (),
    }.get(kind, ())
    missing = [column for column in required if column not in fieldnames]
    for column in missing:
        issues.append(DataContractIssue(ERROR, "missing_required_column", "Required column is missing", column=column))
    expected_trade = ("code", "entry_date", "exit_date", "entry_price", "exit_price", "net_return")
    if kind == "trade_csv":
        for column in expected_trade:
            if column not in fieldnames:
                issues.append(DataContractIssue(WARN, "missing_trade_column", "Expected trade audit column is missing", column=column))
    return issues


def _row_quality_issues(rows: list[dict[str, str]], fieldnames: list[str], kind: str) -> list[DataContractIssue]:
    issues: list[DataContractIssue] = []
    if not rows:
        return [DataContractIssue(ERROR, "empty_csv", "CSV has zero rows")]
    if kind == "trade_csv":
        issues.extend(_date_column_issues(rows, "entry_date"))
        if "exit_date" in fieldnames:
            issues.extend(_date_column_issues(rows, "exit_date"))
            bad_order = _bad_exit_order(rows)
            if bad_order:
                issues.append(DataContractIssue(ERROR, "exit_before_entry", "Exit date is before entry date", count=bad_order))
        issues.extend(_numeric_column_issues(rows, "net_return", required=True))
        for column in ("entry_price", "exit_price", "t1_auction_return"):
            if column in fieldnames:
                issues.extend(_numeric_column_issues(rows, column, required=False))
    elif kind == "return_series":
        issues.extend(_date_column_issues(rows, "date"))
        issues.extend(_numeric_column_issues(rows, "return", required=True))
    return issues


def _date_column_issues(rows: list[dict[str, str]], column: str) -> list[DataContractIssue]:
    missing = 0
    invalid = 0
    sample = ""
    for row in rows:
        value = str(row.get(column, "")).strip()
        if not value:
            missing += 1
            continue
        if _parse_date(value) is None:
            invalid += 1
            sample = sample or value
    issues: list[DataContractIssue] = []
    if missing:
        issues.append(DataContractIssue(ERROR, "missing_date", "Required date value is missing", column=column, count=missing))
    if invalid:
        issues.append(DataContractIssue(ERROR, "invalid_date", "Date value is not parseable", column=column, count=invalid, sample=sample))
    return issues


def _numeric_column_issues(rows: list[dict[str, str]], column: str, *, required: bool) -> list[DataContractIssue]:
    missing = 0
    invalid = 0
    valid = 0
    sample = ""
    for row in rows:
        raw = str(row.get(column, "")).strip()
        if not raw:
            missing += 1
            continue
        if to_float(raw) is None:
            invalid += 1
            sample = sample or raw
        else:
            valid += 1
    issues: list[DataContractIssue] = []
    level = ERROR if required else WARN
    if required and valid == 0:
        issues.append(DataContractIssue(ERROR, "no_valid_numeric_values", "No valid numeric values in required column", column=column))
    if missing and required:
        issues.append(DataContractIssue(ERROR, "missing_numeric", "Required numeric value is missing", column=column, count=missing))
    if invalid:
        issues.append(DataContractIssue(level, "invalid_numeric", "Numeric value is not parseable", column=column, count=invalid, sample=sample))
    return issues


def _duplicate_issues(path: Path) -> list[DataContractIssue]:
    issues: list[DataContractIssue] = []
    for finding in audit_csv_duplicates(path):
        level = ERROR if finding.level == "error" else WARN
        issues.append(DataContractIssue(level, "duplicate_trades", finding.detail))
    return issues


def _baseline_issues(path: Path, rows: int, *, strict_dedup: bool) -> list[DataContractIssue]:
    issues: list[DataContractIssue] = []
    lowered = path.name.lower()
    if rows == 1253:
        issues.append(DataContractIssue(ERROR, "polluted_1253_sample", "1253-row polluted baseline must not be used as clean evidence"))
    if "dedup" not in lowered and "tick_data_request" not in lowered:
        level = ERROR if strict_dedup else WARN
        issues.append(DataContractIssue(level, "not_dedup_marked", "File name does not indicate a deduplicated baseline"))
    return issues


def _bad_exit_order(rows: list[dict[str, str]]) -> int:
    bad = 0
    for row in rows:
        entry = _parse_date(str(row.get("entry_date", "")).strip())
        exit_ = _parse_date(str(row.get("exit_date", "")).strip())
        if entry is not None and exit_ is not None and exit_ < entry:
            bad += 1
    return bad


def _years(rows: list[dict[str, str]], column: str) -> list[str]:
    years: set[str] = set()
    for row in rows:
        parsed = _parse_date(str(row.get(column, "")).strip())
        if parsed is not None:
            years.add(f"{parsed.year:04d}")
    return sorted(years)


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None
