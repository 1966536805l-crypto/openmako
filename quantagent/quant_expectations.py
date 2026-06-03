from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from .metrics import to_float


PASS = "pass"
WARN = "warn"
BLOCK = "block"


@dataclass(frozen=True)
class QuantExpectationSpec:
    path: str
    kind: str = "auto"
    sample_rows: int = 5000
    hash_bytes: int = 16 * 1024 * 1024

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuantExpectationCheck:
    name: str
    expectation_type: str
    column: str = ""
    severity: str = BLOCK
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuantExpectationFinding:
    level: str
    code: str
    message: str
    expectation: str = ""
    column: str = ""
    count: int = 0
    sample: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuantExpectationReport:
    path: str
    kind: str
    ok: bool
    rows_sampled: int
    columns: tuple[str, ...]
    file_bytes: int = 0
    sha256_head: str = ""
    hash_bytes: int = 0
    hash_partial: bool = False
    checks: tuple[QuantExpectationCheck, ...] = ()
    findings: tuple[QuantExpectationFinding, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "ok": self.ok,
            "rows_sampled": self.rows_sampled,
            "columns": list(self.columns),
            "file_bytes": self.file_bytes,
            "sha256_head": self.sha256_head,
            "hash_bytes": self.hash_bytes,
            "hash_partial": self.hash_partial,
            "checks": [item.to_dict() for item in self.checks],
            "findings": [item.to_dict() for item in self.findings],
            "metadata": self.metadata,
        }


def run_quant_expectations(path: str | Path, *, kind: str = "auto", sample_rows: int = 5000, hash_bytes: int = 16 * 1024 * 1024) -> QuantExpectationReport:
    csv_path = Path(path).expanduser().resolve(strict=False)
    if not csv_path.exists():
        return QuantExpectationReport(
            path=str(csv_path),
            kind=kind,
            ok=False,
            rows_sampled=0,
            columns=(),
            findings=(QuantExpectationFinding(BLOCK, "missing_file", "Expectation input file does not exist"),),
        )
    if csv_path.is_dir():
        return QuantExpectationReport(
            path=str(csv_path),
            kind=kind,
            ok=False,
            rows_sampled=0,
            columns=(),
            findings=(QuantExpectationFinding(BLOCK, "directory_not_file", "Expectation input must be a CSV file, not a directory"),),
        )
    if csv_path.suffix.lower() != ".csv":
        return QuantExpectationReport(
            path=str(csv_path),
            kind=kind,
            ok=False,
            rows_sampled=0,
            columns=(),
            findings=(QuantExpectationFinding(BLOCK, "not_csv", "Expectation runner currently supports CSV files"),),
        )
    try:
        columns, rows = _read_csv_sample(csv_path, max_rows=max(1, sample_rows))
    except OSError as exc:
        return QuantExpectationReport(
            path=str(csv_path),
            kind=kind,
            ok=False,
            rows_sampled=0,
            columns=(),
            findings=(QuantExpectationFinding(BLOCK, "read_failed", str(exc)),),
        )
    detected_kind = _detect_kind(columns, kind)
    suite = built_in_expectation_suite(detected_kind)
    findings = _run_suite(suite, columns, rows)
    if not columns:
        findings.append(QuantExpectationFinding(BLOCK, "missing_header", "CSV has no header", expectation="table_has_header"))
    if not rows:
        findings.append(QuantExpectationFinding(BLOCK, "empty_rows", "CSV has no sampled rows", expectation="table_row_count_between"))
    metadata = _metadata_for(rows, columns, detected_kind)
    file_bytes, digest, hashed = _sha256_head(csv_path, max_bytes=max(0, hash_bytes))
    blocked = any(item.level == BLOCK for item in findings)
    return QuantExpectationReport(
        path=str(csv_path),
        kind=detected_kind,
        ok=not blocked,
        rows_sampled=len(rows),
        columns=tuple(columns),
        file_bytes=file_bytes,
        sha256_head=digest,
        hash_bytes=hashed,
        hash_partial=hashed < file_bytes,
        checks=tuple(suite),
        findings=tuple(findings),
        metadata=metadata,
    )


def built_in_expectation_suite(kind: str) -> tuple[QuantExpectationCheck, ...]:
    groups = _required_groups(kind)
    checks: list[QuantExpectationCheck] = [
        QuantExpectationCheck("table_has_required_column_groups", "table_has_column_group", params={"groups": groups}),
    ]
    for role in _date_roles(kind):
        checks.append(QuantExpectationCheck(f"{role}_parseable_date", "column_values_parseable_date", column=role))
    for role in _numeric_roles(kind):
        checks.append(QuantExpectationCheck(f"{role}_numeric", "column_values_numeric", column=role))
    for role in _nonnegative_roles(kind):
        checks.append(QuantExpectationCheck(f"{role}_nonnegative", "column_values_between", column=role, params={"min": 0}))
    if kind in {"market_bar_csv", "minute_bar_csv"}:
        checks.append(QuantExpectationCheck("ohlc_bounds_consistent", "ohlc_bounds_consistent"))
        checks.append(QuantExpectationCheck("code_date_unique", "compound_columns_unique", severity=WARN, params={"roles": ("code", "date")}))
    if kind in {"tick_trade_csv", "fill_csv"}:
        checks.append(QuantExpectationCheck("positive_execution_price", "column_values_between", column="price", params={"min_exclusive": 0}))
        checks.append(QuantExpectationCheck("positive_execution_volume", "column_values_between", column="volume", params={"min_exclusive": 0}))
    if kind == "trade_csv":
        checks.append(QuantExpectationCheck("entry_return_unique", "compound_columns_unique", severity=WARN, params={"roles": ("code", "entry_date")}))
    return tuple(checks)


def render_quant_expectations(report: QuantExpectationReport) -> str:
    lines = [
        "# Quant Expectations",
        "",
        f"- path: {report.path}",
        f"- kind: {report.kind}",
        f"- ok: {str(report.ok).lower()}",
        f"- rows_sampled: {report.rows_sampled}",
        f"- columns: {len(report.columns)}",
        f"- file_bytes: {report.file_bytes}",
        f"- sha256_head: `{report.sha256_head}`" if report.sha256_head else "- sha256_head: -",
        f"- hash_partial: {str(report.hash_partial).lower()}",
        "",
        "## Checks",
        "",
    ]
    for check in report.checks:
        column = f" column={check.column}" if check.column else ""
        lines.append(f"- [{check.severity}] {check.name}: {check.expectation_type}{column}")
    lines.extend(["", "## Findings", ""])
    if not report.findings:
        lines.append("- none")
    for finding in report.findings:
        column = f" column={finding.column}" if finding.column else ""
        count = f" count={finding.count}" if finding.count else ""
        sample = f" sample={finding.sample}" if finding.sample else ""
        expectation = f" expectation={finding.expectation}" if finding.expectation else ""
        lines.append(f"- [{finding.level}] {finding.code}{expectation}{column}{count}{sample}: {finding.message}")
    lines.extend(["", "## Metadata", "", "```json", json.dumps(report.metadata, ensure_ascii=False, indent=2, sort_keys=True), "```"])
    return "\n".join(lines).rstrip() + "\n"


def _run_suite(suite: Iterable[QuantExpectationCheck], columns: list[str], rows: list[dict[str, str]]) -> list[QuantExpectationFinding]:
    findings: list[QuantExpectationFinding] = []
    aliases = _column_aliases(columns)
    for check in suite:
        if check.expectation_type == "table_has_column_group":
            for group in check.params.get("groups", ()):
                if not _role_column(aliases, group):
                    findings.append(
                        QuantExpectationFinding(
                            check.severity,
                            "missing_required_column_group",
                            "Missing one required column group: " + "/".join(_aliases_for_role(str(group))),
                            expectation=check.name,
                            column=str(group),
                        )
                    )
        elif check.expectation_type == "column_values_parseable_date":
            column = _role_column(aliases, check.column)
            if column:
                findings.extend(_date_findings(rows, column, check))
        elif check.expectation_type == "column_values_numeric":
            column = _role_column(aliases, check.column)
            if column:
                findings.extend(_numeric_findings(rows, column, check, required=True))
        elif check.expectation_type == "column_values_between":
            column = _role_column(aliases, check.column)
            if column:
                findings.extend(_between_findings(rows, column, check))
        elif check.expectation_type == "compound_columns_unique":
            role_columns = [_role_column(aliases, role) for role in check.params.get("roles", ())]
            if all(role_columns):
                findings.extend(_compound_unique_findings(rows, [str(item) for item in role_columns], check))
        elif check.expectation_type == "ohlc_bounds_consistent":
            ohlc = {role: _role_column(aliases, role) for role in ("open", "high", "low", "close")}
            if all(ohlc.values()):
                findings.extend(_ohlc_findings(rows, {key: str(value) for key, value in ohlc.items()}, check))
    return findings


def _read_csv_sample(path: Path, *, max_rows: int) -> tuple[list[str], list[dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = [name for name in (reader.fieldnames or []) if name is not None]
            rows = [dict(row) for _, row in zip(range(max_rows), reader)]
    except UnicodeDecodeError:
        with path.open("r", encoding="gb18030", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = [name for name in (reader.fieldnames or []) if name is not None]
            rows = [dict(row) for _, row in zip(range(max_rows), reader)]
    return columns, rows


def _detect_kind(columns: list[str], requested: str) -> str:
    if requested and requested != "auto":
        return requested
    aliases = _column_aliases(columns)
    if _role_column(aliases, "entry_date") and _role_column(aliases, "return"):
        return "trade_csv"
    if _role_column(aliases, "date") and _role_column(aliases, "return"):
        return "return_series"
    if _role_column(aliases, "time") and _role_column(aliases, "price") and _role_column(aliases, "volume") and not _role_column(aliases, "open"):
        return "tick_trade_csv"
    if _role_column(aliases, "date") and all(_role_column(aliases, role) for role in ("open", "high", "low", "close", "volume")):
        return "market_bar_csv"
    if _role_column(aliases, "code") and _role_column(aliases, "slippage"):
        return "slippage_csv"
    if _role_column(aliases, "code") and _role_column(aliases, "capacity"):
        return "capacity_csv"
    if _role_column(aliases, "broker") or _role_column(aliases, "account"):
        return "broker_csv"
    return "generic_csv"


def _required_groups(kind: str) -> tuple[str, ...]:
    return {
        "trade_csv": ("entry_date", "return"),
        "return_series": ("date", "return"),
        "market_bar_csv": ("date", "code", "open", "high", "low", "close", "volume"),
        "minute_bar_csv": ("date", "open", "high", "low", "close", "volume"),
        "tick_trade_csv": ("time", "price", "volume"),
        "fill_csv": ("time", "code", "price", "volume"),
        "broker_csv": ("broker_or_account",),
        "slippage_csv": ("code", "slippage"),
        "capacity_csv": ("code", "capacity"),
        "position_csv": ("code", "position"),
    }.get(kind, ())


def _date_roles(kind: str) -> tuple[str, ...]:
    return {
        "trade_csv": ("entry_date",),
        "return_series": ("date",),
        "market_bar_csv": ("date",),
        "minute_bar_csv": ("date",),
        "tick_trade_csv": ("time",),
        "fill_csv": ("time",),
    }.get(kind, ())


def _numeric_roles(kind: str) -> tuple[str, ...]:
    return {
        "trade_csv": ("return",),
        "return_series": ("return",),
        "market_bar_csv": ("open", "high", "low", "close", "volume"),
        "minute_bar_csv": ("open", "high", "low", "close", "volume"),
        "tick_trade_csv": ("price", "volume"),
        "fill_csv": ("price", "volume"),
        "slippage_csv": ("slippage",),
        "capacity_csv": ("capacity",),
        "position_csv": ("position",),
    }.get(kind, ())


def _nonnegative_roles(kind: str) -> tuple[str, ...]:
    return {
        "market_bar_csv": ("volume",),
        "minute_bar_csv": ("volume",),
        "tick_trade_csv": ("volume",),
        "fill_csv": ("volume",),
        "capacity_csv": ("capacity",),
    }.get(kind, ())


def _date_findings(rows: list[dict[str, str]], column: str, check: QuantExpectationCheck) -> list[QuantExpectationFinding]:
    missing = 0
    invalid = 0
    sample = ""
    future = 0
    today = date.today()
    for row in rows:
        value = str(row.get(column, "")).strip()
        if not value:
            missing += 1
            continue
        parsed = _parse_date(value)
        if parsed is None:
            invalid += 1
            sample = sample or value
            continue
        if parsed.date() > today:
            future += 1
            sample = sample or value
    findings: list[QuantExpectationFinding] = []
    if missing:
        findings.append(QuantExpectationFinding(check.severity, "missing_date", "Date value is missing", expectation=check.name, column=column, count=missing))
    if invalid:
        findings.append(QuantExpectationFinding(check.severity, "invalid_date", "Date value is not parseable", expectation=check.name, column=column, count=invalid, sample=sample))
    if future:
        findings.append(QuantExpectationFinding(WARN, "future_date", "Date value is after today; verify data snapshot freshness and clock", expectation=check.name, column=column, count=future, sample=sample))
    return findings


def _numeric_findings(rows: list[dict[str, str]], column: str, check: QuantExpectationCheck, *, required: bool) -> list[QuantExpectationFinding]:
    missing = 0
    invalid = 0
    valid = 0
    sample = ""
    for row in rows:
        value = str(row.get(column, "")).strip()
        if not value:
            missing += 1
            continue
        if to_float(value) is None:
            invalid += 1
            sample = sample or value
        else:
            valid += 1
    findings: list[QuantExpectationFinding] = []
    if required and valid == 0:
        findings.append(QuantExpectationFinding(check.severity, "no_valid_numeric_values", "No valid numeric values in required column", expectation=check.name, column=column))
    if required and missing:
        findings.append(QuantExpectationFinding(check.severity, "missing_numeric", "Required numeric value is missing", expectation=check.name, column=column, count=missing))
    if invalid:
        findings.append(QuantExpectationFinding(check.severity, "invalid_numeric", "Numeric value is not parseable", expectation=check.name, column=column, count=invalid, sample=sample))
    return findings


def _between_findings(rows: list[dict[str, str]], column: str, check: QuantExpectationCheck) -> list[QuantExpectationFinding]:
    below = 0
    above = 0
    invalid = 0
    sample = ""
    min_value = check.params.get("min")
    max_value = check.params.get("max")
    min_exclusive = check.params.get("min_exclusive")
    max_exclusive = check.params.get("max_exclusive")
    for row in rows:
        raw = str(row.get(column, "")).strip()
        if not raw:
            continue
        value = to_float(raw)
        if value is None:
            invalid += 1
            sample = sample or raw
            continue
        if min_value is not None and value < float(min_value):
            below += 1
            sample = sample or raw
        if max_value is not None and value > float(max_value):
            above += 1
            sample = sample or raw
        if min_exclusive is not None and value <= float(min_exclusive):
            below += 1
            sample = sample or raw
        if max_exclusive is not None and value >= float(max_exclusive):
            above += 1
            sample = sample or raw
    findings: list[QuantExpectationFinding] = []
    if invalid:
        findings.append(QuantExpectationFinding(check.severity, "invalid_numeric", "Numeric value is not parseable", expectation=check.name, column=column, count=invalid, sample=sample))
    if below:
        findings.append(QuantExpectationFinding(check.severity, "value_below_min", "Numeric value is below allowed minimum", expectation=check.name, column=column, count=below, sample=sample))
    if above:
        findings.append(QuantExpectationFinding(check.severity, "value_above_max", "Numeric value is above allowed maximum", expectation=check.name, column=column, count=above, sample=sample))
    return findings


def _compound_unique_findings(rows: list[dict[str, str]], columns: list[str], check: QuantExpectationCheck) -> list[QuantExpectationFinding]:
    seen: set[tuple[str, ...]] = set()
    duplicates = 0
    sample = ""
    for row in rows:
        key = tuple(str(row.get(column, "")).strip() for column in columns)
        if any(not item for item in key):
            continue
        if key in seen:
            duplicates += 1
            sample = sample or "|".join(key)
        seen.add(key)
    if not duplicates:
        return []
    return [
        QuantExpectationFinding(
            check.severity,
            "compound_key_not_unique",
            "Compound key has duplicate sampled rows",
            expectation=check.name,
            column=",".join(columns),
            count=duplicates,
            sample=sample,
        )
    ]


def _ohlc_findings(rows: list[dict[str, str]], columns: Mapping[str, str], check: QuantExpectationCheck) -> list[QuantExpectationFinding]:
    bad = 0
    sample = ""
    for row in rows:
        values = {role: to_float(str(row.get(column, "")).strip()) for role, column in columns.items()}
        if any(value is None for value in values.values()):
            continue
        open_ = float(values["open"])
        high = float(values["high"])
        low = float(values["low"])
        close = float(values["close"])
        if high < low or open_ > high or open_ < low or close > high or close < low:
            bad += 1
            sample = sample or json.dumps({role: values[role] for role in ("open", "high", "low", "close")}, ensure_ascii=False, sort_keys=True)
    if not bad:
        return []
    return [
        QuantExpectationFinding(
            BLOCK,
            "ohlc_bounds_inconsistent",
            "OHLC violates low <= open/close <= high",
            expectation=check.name,
            column=",".join(columns.values()),
            count=bad,
            sample=sample,
        )
    ]


def _metadata_for(rows: list[dict[str, str]], columns: list[str], kind: str) -> dict[str, Any]:
    aliases = _column_aliases(columns)
    date_column = _role_column(aliases, "entry_date") or _role_column(aliases, "date") or _role_column(aliases, "time")
    dates: list[datetime] = []
    if date_column:
        for row in rows:
            raw_date = str(row.get(date_column, "")).strip()
            if _looks_time_only(raw_date):
                continue
            parsed = _parse_date(raw_date)
            if parsed is not None:
                dates.append(parsed)
    codes: set[str] = set()
    code_column = _role_column(aliases, "code")
    if code_column:
        for row in rows:
            value = str(row.get(code_column, "")).strip()
            if value:
                codes.add(value)
    return {
        "detected_kind": kind,
        "date_column": date_column or "",
        "min_date": min(dates).date().isoformat() if dates else "",
        "max_date": max(dates).date().isoformat() if dates else "",
        "distinct_codes_sampled": len(codes),
        "sample_limited": True,
    }


def _sha256_head(path: Path, *, max_bytes: int) -> tuple[int, str, int]:
    file_bytes = path.stat().st_size
    if max_bytes <= 0:
        return file_bytes, "", 0
    digest = hashlib.sha256()
    hashed = 0
    with path.open("rb") as handle:
        while hashed < max_bytes:
            chunk = handle.read(min(1024 * 1024, max_bytes - hashed))
            if not chunk:
                break
            digest.update(chunk)
            hashed += len(chunk)
    return file_bytes, digest.hexdigest(), hashed


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("/", "-").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S", "%Y%m%d %H:%M:%S", "%H:%M:%S", "%H%M%S"):
        try:
            parsed = datetime.strptime(normalized, fmt)
            if fmt in {"%H:%M:%S", "%H%M%S"}:
                return datetime.combine(date.today(), parsed.time())
            return parsed
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _looks_time_only(value: str) -> bool:
    text = str(value or "").strip()
    return bool(re.fullmatch(r"\d{1,2}:\d{2}:\d{2}(?:\.\d+)?", text) or re.fullmatch(r"\d{6}(?:\.\d+)?", text))


def _column_aliases(columns: Iterable[str]) -> dict[str, str]:
    return {_norm(column): column for column in columns}


def _role_column(aliases: Mapping[str, str], role: str) -> str:
    if role == "broker_or_account":
        return _role_column(aliases, "broker") or _role_column(aliases, "account")
    for alias in _aliases_for_role(role):
        column = aliases.get(_norm(alias))
        if column:
            return column
    return ""


def _aliases_for_role(role: str) -> tuple[str, ...]:
    return {
        "date": ("date", "datetime", "timestamp", "日期", "交易日期", "时间"),
        "entry_date": ("entry_date", "entrydate", "date", "日期", "买入日期", "开仓日期"),
        "time": ("time", "timestamp", "datetime", "date_time", "trade_time", "成交时间", "时间", "日期"),
        "code": ("code", "symbol", "vt_symbol", "证券代码", "股票代码", "代码", "合约代码"),
        "open": ("open", "open_price", "开盘", "开盘价"),
        "high": ("high", "high_price", "最高", "最高价"),
        "low": ("low", "low_price", "最低", "最低价"),
        "close": ("close", "close_price", "收盘", "收盘价"),
        "price": ("price", "成交价", "成交价格", "价格", "fill_price"),
        "volume": ("volume", "qty", "quantity", "成交量", "成交量(股)", "成交量（股）", "成交数量", "数量", "fill_volume"),
        "amount": ("amount", "成交额", "成交额(元)", "成交额（元）", "turnover", "notional"),
        "return": ("return", "net_return", "收益", "收益率", "涨幅", "涨跌幅"),
        "broker": ("broker", "broker_name", "gateway", "gateway_name", "券商", "通道"),
        "account": ("account", "account_id", "accountid", "资金账号", "账户", "账户号"),
        "slippage": ("slippage", "slippage_bps", "滑点", "滑点bps"),
        "capacity": ("capacity", "max_notional", "成交额", "容量", "最大成交额"),
        "position": ("position", "quantity", "volume", "持仓", "持仓数量", "证券数量"),
    }.get(role, (role,))


def _norm(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "").replace("-", "").replace(" ", "")
