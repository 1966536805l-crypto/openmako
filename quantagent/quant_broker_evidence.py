from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import time
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class BrokerEvidenceTable:
    path: str
    role: str
    rows_loaded: int = 0
    columns: tuple[str, ...] = ()
    format: str = ""
    sha256: str = ""
    issues: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["columns"] = list(self.columns)
        payload["issues"] = list(self.issues)
        return payload


@dataclass(frozen=True)
class BrokerEvidenceImportResult:
    import_id: str
    project: str
    ok: bool
    output_dir: str
    source: str = ""
    broker_name: str = ""
    files: dict[str, str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    tables: tuple[BrokerEvidenceTable, ...] = ()
    warnings: tuple[str, ...] = ()
    execution_args: tuple[str, ...] = ()
    manifest_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "import_id": self.import_id,
            "project": self.project,
            "ok": self.ok,
            "output_dir": self.output_dir,
            "source": self.source,
            "broker_name": self.broker_name,
            "files": dict(self.files),
            "counts": dict(self.counts),
            "tables": [item.to_dict() for item in self.tables],
            "warnings": list(self.warnings),
            "execution_args": list(self.execution_args),
            "manifest_path": self.manifest_path,
        }


def import_broker_evidence(
    project: str | Path,
    paths: Iterable[str | Path],
    *,
    source: str = "",
    broker_name: str = "",
    output_dir: str | Path = "",
    max_files: int = 200,
    max_rows_per_file: int = 5000,
    redact_accounts: bool = True,
) -> BrokerEvidenceImportResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    import_id = "broker-import-" + str(int(time.time() * 1000))
    out_dir = _resolve_output_dir(project_path, output_dir, import_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    input_files = _discover_input_files(project_path, paths, max_files=max_files)
    tables: list[BrokerEvidenceTable] = []
    warnings: list[str] = []
    fills: list[dict[str, str]] = []
    orders: list[dict[str, str]] = []
    positions: list[dict[str, str]] = []
    accounts: list[dict[str, str]] = []
    broker_rows: list[dict[str, str]] = []

    if not input_files:
        warnings.append("no broker export files found")

    for path in input_files:
        loaded = _load_table(path, max_rows=max_rows_per_file)
        role = _classify_table(path, loaded.columns)
        table = BrokerEvidenceTable(
            path=str(path),
            role=role,
            rows_loaded=len(loaded.rows),
            columns=tuple(loaded.columns),
            format=loaded.format,
            sha256=_sha256_file(path),
            issues=tuple(loaded.issues),
        )
        tables.append(table)
        if loaded.issues:
            warnings.extend(f"{path.name}: {issue}" for issue in loaded.issues)
        if not loaded.rows:
            continue
        if role in {"fill", "settlement"}:
            fills.extend(_normalize_fills(loaded.rows, path))
        elif role == "order":
            orders.extend(_normalize_orders(loaded.rows, path))
        elif role == "position":
            positions.extend(_normalize_positions(loaded.rows, path))
        elif role == "account":
            accounts.extend(_normalize_accounts(loaded.rows, path, broker_name=broker_name, redact_accounts=redact_accounts))
        else:
            inferred_accounts = _normalize_accounts(loaded.rows, path, broker_name=broker_name, redact_accounts=redact_accounts)
            if inferred_accounts:
                accounts.extend(inferred_accounts)

        broker_rows.extend(_broker_rows_from_table(loaded.rows, path, broker_name=broker_name, source=source, redact_accounts=redact_accounts))

    if broker_name or source:
        broker_rows.append({"broker": broker_name or source, "account": "", "source_file": "operator"})
    for account in accounts:
        broker_rows.append({"broker": account.get("broker", broker_name), "account": account.get("account", ""), "source_file": account.get("source_file", "")})

    normalized_files: dict[str, str] = {}
    writers = {
        "fill": (fills, ("time", "code", "price", "qty", "order_id", "side", "trade_id", "status", "source_file", "source_row")),
        "order": (orders, ("time", "code", "order_id", "price", "qty", "traded", "status", "side", "source_file", "source_row")),
        "position": (positions, ("code", "quantity", "available", "cost_price", "pnl", "source_file", "source_row")),
        "account": (accounts, ("broker", "account", "balance", "available", "frozen", "currency", "source_file", "source_row")),
        "broker": (_dedupe_rows(broker_rows, ("broker", "account", "source_file")), ("broker", "account", "source_file")),
    }
    counts: dict[str, int] = {}
    for role, (rows, columns) in writers.items():
        counts[role] = len(rows)
        if not rows:
            continue
        path = out_dir / f"{role}.csv"
        _write_csv(path, rows, columns)
        normalized_files[role] = str(path)

    manifest_path = out_dir / "manifest.json"
    result = BrokerEvidenceImportResult(
        import_id=import_id,
        project=str(project_path),
        ok=bool(fills or orders or positions or accounts or broker_rows),
        output_dir=str(out_dir),
        source=source,
        broker_name=broker_name,
        files=normalized_files,
        counts=counts,
        tables=tuple(tables),
        warnings=tuple(_dedupe(warnings)),
        execution_args=_execution_args(normalized_files, source=source or broker_name),
        manifest_path=str(manifest_path),
    )
    manifest_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def render_broker_evidence_import(result: BrokerEvidenceImportResult) -> str:
    lines = [
        "# Broker Evidence Import",
        "",
        f"- ok: {str(result.ok).lower()}",
        f"- import_id: {result.import_id}",
        f"- output_dir: {result.output_dir}",
        f"- source: {result.source or '-'}",
        f"- broker_name: {result.broker_name or '-'}",
        f"- manifest: {result.manifest_path or '-'}",
        "",
        "## Normalized Files",
        "",
    ]
    if not result.files:
        lines.append("- none")
    for role in ("fill", "order", "position", "account", "broker"):
        if role in result.files:
            lines.append(f"- {role}: {result.files[role]} rows={result.counts.get(role, 0)}")
    lines.extend(["", "## Source Tables", ""])
    if not result.tables:
        lines.append("- none")
    for table in result.tables:
        columns = ",".join(table.columns[:12]) if table.columns else "-"
        lines.append(f"- {table.role or 'unknown'}: {table.path} rows={table.rows_loaded} format={table.format or '-'} columns={columns}")
    lines.extend(["", "## Execution Args", ""])
    if result.execution_args:
        lines.append("`" + " ".join(result.execution_args) + "`")
    else:
        lines.append("- none")
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {warning}" for warning in result.warnings) if result.warnings else lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def render_broker_evidence_import_json(result: BrokerEvidenceImportResult) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True)
class _LoadedTable:
    rows: tuple[dict[str, str], ...]
    columns: tuple[str, ...]
    format: str = ""
    issues: tuple[str, ...] = ()


def _discover_input_files(project: Path, raw_paths: Iterable[str | Path], *, max_files: int) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    allowed = {".csv", ".txt", ".tsv", ".xls", ".html", ".htm", ".json"}
    for raw in raw_paths:
        text = str(raw or "").strip()
        if not text:
            continue
        path = Path(text).expanduser()
        path = (path if path.is_absolute() else project / path).resolve(strict=False)
        candidates = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file()) if path.exists() else []
        for candidate in candidates:
            if len(result) >= max_files:
                return result
            if candidate in seen or candidate.suffix.lower() not in allowed:
                continue
            seen.add(candidate)
            result.append(candidate)
    return result


def _load_table(path: Path, *, max_rows: int) -> _LoadedTable:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _load_json(path, max_rows=max_rows)
    text, encoding = _read_text(path)
    if text is None:
        return _LoadedTable((), (), suffix.lstrip(".") or "file", ("unsupported binary spreadsheet; export CSV from broker client",))
    if suffix in {".html", ".htm"} or "<table" in text[:2000].lower():
        html_table = _load_html_table(text, max_rows=max_rows)
        if html_table.rows:
            return html_table
    table = _load_delimited_text(text, max_rows=max_rows)
    if table.rows or table.columns:
        return _LoadedTable(table.rows, table.columns, "text:" + encoding, table.issues)
    return _LoadedTable((), (), "text:" + encoding, ("no table header detected",))


def _read_text(path: Path) -> tuple[str | None, str]:
    raw = path.read_bytes()
    if b"\x00" in raw[:4096]:
        return None, "binary"
    for encoding in ("utf-8-sig", "gb18030", "big5", "utf-16", "utf-16le"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore"), "utf-8-ignore"


def _load_json(path: Path, *, max_rows: int) -> _LoadedTable:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _LoadedTable((), (), "json", (str(exc),))
    if isinstance(payload, list):
        items = [item for item in payload if isinstance(item, Mapping)]
    elif isinstance(payload, Mapping):
        inner = payload.get("rows") or payload.get("data") or payload.get("items")
        items = [item for item in inner if isinstance(item, Mapping)] if isinstance(inner, list) else [payload]
    else:
        items = []
    rows = tuple({str(key): "" if value is None else str(value) for key, value in item.items()} for item in items[:max_rows])
    columns = tuple(_ordered_columns(rows))
    issues = () if rows else ("json has no object rows",)
    return _LoadedTable(rows, columns, "json", issues)


class _SimpleTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_cell = False
        self.in_row = False
        self.current_cell: list[str] = []
        self.current_row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "tr":
            self.in_row = True
            self.current_row = []
        elif tag.lower() in {"td", "th"} and self.in_row:
            self.in_cell = True
            self.current_cell = []

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower in {"td", "th"} and self.in_cell:
            self.current_row.append(_clean_cell("".join(self.current_cell)))
            self.in_cell = False
        elif lower == "tr" and self.in_row:
            if any(cell for cell in self.current_row):
                self.rows.append(self.current_row)
            self.in_row = False


def _load_html_table(text: str, *, max_rows: int) -> _LoadedTable:
    parser = _SimpleTableParser()
    parser.feed(text)
    return _rows_to_table(parser.rows, max_rows=max_rows, fmt="html")


def _load_delimited_text(text: str, *, max_rows: int) -> _LoadedTable:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return _LoadedTable((), (), "text", ("empty text file",))
    best: tuple[int, str, int, list[list[str]]] | None = None
    delimiters = ("\t", ",", ";", "|")
    for delimiter in delimiters:
        parsed = list(csv.reader(lines, delimiter=delimiter))
        for idx, row in enumerate(parsed[:30]):
            score = _header_score(row)
            if len(row) >= 3:
                score += 1
            candidate = (score, delimiter, idx, parsed)
            if best is None or candidate[0] > best[0]:
                best = candidate
    if best is None:
        return _LoadedTable((), (), "text", ("no delimited rows",))
    score, delimiter, start, parsed_rows = best
    if score <= 0:
        return _LoadedTable((), (), "text", ("no recognizable broker columns",))
    return _rows_to_table(parsed_rows[start:], max_rows=max_rows, fmt="delimited:" + ("tab" if delimiter == "\t" else delimiter))


def _rows_to_table(rows: list[list[str]], *, max_rows: int, fmt: str) -> _LoadedTable:
    if not rows:
        return _LoadedTable((), (), fmt, ("empty table",))
    header_index = 0
    best_score = -1
    for idx, row in enumerate(rows[:30]):
        score = _header_score(row)
        if score > best_score:
            best_score = score
            header_index = idx
    if best_score <= 0:
        return _LoadedTable((), (), fmt, ("no recognizable broker columns",))
    columns = [_clean_header(cell) or f"column_{idx + 1}" for idx, cell in enumerate(rows[header_index])]
    data_rows: list[dict[str, str]] = []
    for source in rows[header_index + 1 : header_index + 1 + max_rows]:
        if not any(str(cell).strip() for cell in source):
            continue
        row: dict[str, str] = {}
        for idx, column in enumerate(columns):
            row[column] = _clean_cell(source[idx]) if idx < len(source) else ""
        data_rows.append(row)
    issues = () if data_rows else ("table has header but no data rows",)
    return _LoadedTable(tuple(data_rows), tuple(columns), fmt, issues)


def _classify_table(path: Path, columns: Iterable[str]) -> str:
    name = path.name.lower()
    raw_name = path.name
    cols = tuple(columns)
    if "交割" in raw_name or "delivery" in name or "settlement" in name:
        return "settlement"
    if ("委托" in raw_name or "order" in name or "entrust" in name) and _has(cols, ORDER_ID_ALIASES):
        return "order"
    if ("持仓" in raw_name or "position" in name or "holding" in name) and _has(cols, CODE_ALIASES):
        return "position"
    if ("资金" in raw_name or "account" in name or "asset" in name or "balance" in name) and (_has(cols, ACCOUNT_ALIASES) or _has(cols, BALANCE_ALIASES)):
        return "account"
    if ("成交" in raw_name or "fill" in name or "trade" in name or "deal" in name) and _has(cols, PRICE_ALIASES):
        return "fill"
    if _has(cols, ORDER_ID_ALIASES) and _has(cols, STATUS_ALIASES):
        return "order"
    if _has(cols, CODE_ALIASES) and _has(cols, POSITION_QTY_ALIASES):
        return "position"
    if _has(cols, ACCOUNT_ALIASES) or _has(cols, BALANCE_ALIASES):
        return "account"
    if _has(cols, PRICE_ALIASES) and _has(cols, FILL_QTY_ALIASES):
        return "fill"
    return "unknown"


def _normalize_fills(rows: Iterable[Mapping[str, str]], path: Path) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for row_num, row in enumerate(rows, start=1):
        code = _normalize_code(_get(row, CODE_ALIASES))
        price = _num(_get(row, PRICE_ALIASES))
        qty = _num(_get(row, FILL_QTY_ALIASES))
        if not code or not price or not qty:
            continue
        result.append(
            {
                "time": _join_date_time(_get(row, DATE_ALIASES), _get(row, TIME_ALIASES)),
                "code": code,
                "price": price,
                "qty": qty,
                "order_id": _get(row, ORDER_ID_ALIASES),
                "side": _normalize_side(_get(row, SIDE_ALIASES)),
                "trade_id": _get(row, TRADE_ID_ALIASES),
                "status": _get(row, STATUS_ALIASES),
                "source_file": str(path),
                "source_row": str(row_num),
            }
        )
    return result


def _normalize_orders(rows: Iterable[Mapping[str, str]], path: Path) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for row_num, row in enumerate(rows, start=1):
        code = _normalize_code(_get(row, CODE_ALIASES))
        order_id = _get(row, ORDER_ID_ALIASES)
        if not code or not order_id:
            continue
        result.append(
            {
                "time": _join_date_time(_get(row, DATE_ALIASES), _get(row, TIME_ALIASES)),
                "code": code,
                "order_id": order_id,
                "price": _num(_get(row, ORDER_PRICE_ALIASES)),
                "qty": _num(_get(row, ORDER_QTY_ALIASES)),
                "traded": _num(_get(row, TRADED_QTY_ALIASES)),
                "status": _normalize_status(_get(row, STATUS_ALIASES)),
                "side": _normalize_side(_get(row, SIDE_ALIASES)),
                "source_file": str(path),
                "source_row": str(row_num),
            }
        )
    return result


def _normalize_positions(rows: Iterable[Mapping[str, str]], path: Path) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for row_num, row in enumerate(rows, start=1):
        code = _normalize_code(_get(row, CODE_ALIASES))
        qty = _num(_get(row, POSITION_QTY_ALIASES))
        if not code or qty == "":
            continue
        result.append(
            {
                "code": code,
                "quantity": qty,
                "available": _num(_get(row, AVAILABLE_POSITION_ALIASES)),
                "cost_price": _num(_get(row, COST_PRICE_ALIASES)),
                "pnl": _num(_get(row, PNL_ALIASES)),
                "source_file": str(path),
                "source_row": str(row_num),
            }
        )
    return result


def _normalize_accounts(
    rows: Iterable[Mapping[str, str]],
    path: Path,
    *,
    broker_name: str,
    redact_accounts: bool,
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for row_num, row in enumerate(rows, start=1):
        account = _get(row, ACCOUNT_ALIASES)
        broker = _get(row, BROKER_ALIASES) or broker_name
        balance = _num(_get(row, BALANCE_ALIASES))
        available = _num(_get(row, AVAILABLE_CASH_ALIASES))
        if not account and not broker and balance == "" and available == "":
            continue
        result.append(
            {
                "broker": broker,
                "account": _redact_account(account) if redact_accounts else account,
                "balance": balance,
                "available": available,
                "frozen": _num(_get(row, FROZEN_ALIASES)),
                "currency": _get(row, CURRENCY_ALIASES),
                "source_file": str(path),
                "source_row": str(row_num),
            }
        )
    return result


def _broker_rows_from_table(
    rows: Iterable[Mapping[str, str]],
    path: Path,
    *,
    broker_name: str,
    source: str,
    redact_accounts: bool,
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for row in rows:
        broker = _get(row, BROKER_ALIASES) or broker_name or source
        account = _get(row, ACCOUNT_ALIASES)
        if broker or account:
            result.append({"broker": broker, "account": _redact_account(account) if redact_accounts else account, "source_file": str(path)})
    return result


def _execution_args(files: Mapping[str, str], *, source: str) -> tuple[str, ...]:
    args: list[str] = []
    if source:
        args.extend(["--execution-source", source])
    mapping = {
        "fill": "--fill",
        "broker": "--broker",
        "order": "--order",
        "position": "--position",
        "account": "--account",
    }
    for role, flag in mapping.items():
        if files.get(role):
            args.extend([flag, files[role]])
    return tuple(args)


def _resolve_output_dir(project: Path, output_dir: str | Path, import_id: str) -> Path:
    if str(output_dir or "").strip():
        path = Path(output_dir).expanduser()
        return (path if path.is_absolute() else project / path).resolve(strict=False)
    return project / ".quantagent" / "broker_evidence" / import_id


def _write_csv(path: Path, rows: Iterable[Mapping[str, str]], columns: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(columns)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in cols})


def _ordered_columns(rows: Iterable[Mapping[str, str]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                result.append(key)
    return result


def _dedupe_rows(rows: Iterable[Mapping[str, str]], keys: Iterable[str]) -> list[dict[str, str]]:
    key_list = list(keys)
    result: list[dict[str, str]] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        item = {key: str(row.get(key, "") or "") for key in key_list}
        marker = tuple(item[key] for key in key_list)
        if marker in seen or not any(marker):
            continue
        seen.add(marker)
        result.append(item)
    return result


def _get(row: Mapping[str, Any], aliases: Iterable[str]) -> str:
    by_norm = {_norm(key): key for key in row.keys()}
    for alias in aliases:
        key = by_norm.get(_norm(alias))
        if key is None:
            continue
        value = row.get(key)
        text = "" if value is None else str(value).strip()
        if text:
            return text
    return ""


def _has(columns: Iterable[str], aliases: Iterable[str]) -> bool:
    normalized = {_norm(column) for column in columns}
    return any(_norm(alias) in normalized for alias in aliases)


def _header_score(cells: Iterable[str]) -> int:
    normalized = {_norm(cell) for cell in cells if str(cell).strip()}
    score = 0
    for group in HEADER_ALIAS_GROUPS:
        if any(_norm(alias) in normalized for alias in group):
            score += 1
    return score


def _clean_header(value: str) -> str:
    return _clean_cell(value).replace("\ufeff", "")


def _clean_cell(value: str) -> str:
    return html.unescape(str(value or "")).replace("\xa0", " ").strip()


def _normalize_code(value: str) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-6:] if len(digits) >= 6 else digits


def _join_date_time(date_value: str, time_value: str) -> str:
    date_text = _normalize_date(date_value)
    time_text = str(time_value or "").strip()
    if date_text and time_text:
        if re.fullmatch(r"\d{6}", time_text):
            time_text = f"{time_text[:2]}:{time_text[2:4]}:{time_text[4:]}"
        return f"{date_text} {time_text}"
    if date_text:
        return date_text
    return time_text


def _normalize_date(value: str) -> str:
    text = str(value or "").strip().replace("/", "-").replace(".", "-")
    if not text:
        return ""
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return text


def _num(value: str) -> str:
    text = str(value or "").strip()
    if not text or text in {"--", "-", "无"}:
        return ""
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace(",", "").replace("，", "").replace("%", "")
    text = re.sub(r"[^\d.\-]", "", text)
    if not text or text in {"-", ".", "-."}:
        return ""
    try:
        number = float(text)
    except ValueError:
        return ""
    if negative:
        number = -number
    return f"{number:g}"


def _normalize_side(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"buy", "b", "买", "买入", "证券买入", "担保品买入", "融资买入"}:
        return "buy"
    if text in {"sell", "s", "卖", "卖出", "证券卖出", "担保品卖出", "融券卖出"}:
        return "sell"
    return str(value or "").strip()


def _normalize_status(value: str) -> str:
    text = str(value or "").strip()
    if text in {"已成", "全部成交", "成交", "已成交", "filled"}:
        return "filled"
    if text in {"部成", "部分成交", "partially_filled"}:
        return "partially_filled"
    if text in {"已撤", "撤单", "已撤单", "cancelled", "canceled"}:
        return "cancelled"
    return text


def _redact_account(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return "acct_sha256_" + digest


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dedupe(items: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return tuple(result)


def _norm(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "").replace("-", "").replace(" ", "").replace("　", "")


DATE_ALIASES = ("date", "trade_date", "business_date", "成交日期", "交易日期", "委托日期", "发生日期", "日期")
TIME_ALIASES = ("time", "timestamp", "datetime", "date_time", "trade_time", "fill_time", "成交时间", "委托时间", "时间")
CODE_ALIASES = ("code", "symbol", "vt_symbol", "local_symbol", "证券代码", "股票代码", "合约代码", "代码")
PRICE_ALIASES = ("price", "fill_price", "traded_price", "成交价", "成交价格", "成交均价", "价格")
ORDER_PRICE_ALIASES = PRICE_ALIASES + ("委托价", "委托价格", "申报价格")
FILL_QTY_ALIASES = ("qty", "quantity", "volume", "fill_volume", "traded", "成交数量", "成交量", "成交股数", "成交数量(股)", "成交量(股)", "数量")
ORDER_QTY_ALIASES = ("qty", "quantity", "volume", "委托数量", "委托股数", "申报数量", "数量")
TRADED_QTY_ALIASES = ("traded", "filled", "成交数量", "成交量", "已成交", "已成数量", "成交股数", "fill_volume")
POSITION_QTY_ALIASES = ("quantity", "volume", "position", "持仓", "持仓数量", "证券数量", "当前持仓", "股份余额", "股票余额")
AVAILABLE_POSITION_ALIASES = ("available", "可用", "可卖数量", "可用数量", "可用股份", "可用余额")
COST_PRICE_ALIASES = ("cost_price", "成本价", "持仓成本", "平均成本", "成本价格")
PNL_ALIASES = ("pnl", "profit", "浮动盈亏", "盈亏", "参考盈亏")
SIDE_ALIASES = ("side", "direction", "action", "offset", "买卖", "买卖方向", "方向", "操作", "买卖标志", "委托类别")
ORDER_ID_ALIASES = ("order_id", "orderid", "vt_orderid", "local_orderid", "委托编号", "合同编号", "订单号", "委托合同号", "合同序号")
TRADE_ID_ALIASES = ("trade_id", "tradeid", "vt_tradeid", "成交编号", "成交号", "成交合同号")
STATUS_ALIASES = ("status", "order_status", "state", "状态", "委托状态", "成交状态")
BROKER_ALIASES = ("broker", "broker_name", "gateway", "gateway_name", "券商", "证券公司", "营业部", "通道", "柜台")
ACCOUNT_ALIASES = ("account", "account_id", "accountid", "资金账号", "账户", "账户号", "客户号", "客户代码", "股东账号")
BALANCE_ALIASES = ("balance", "asset", "equity", "资金余额", "总资产", "资产总值", "账户权益", "证券市值")
AVAILABLE_CASH_ALIASES = ("available", "cash", "可用", "可用资金", "可取资金", "资金可用")
FROZEN_ALIASES = ("frozen", "冻结", "冻结资金", "资金冻结")
CURRENCY_ALIASES = ("currency", "币种", "货币")
HEADER_ALIAS_GROUPS = (
    DATE_ALIASES,
    TIME_ALIASES,
    CODE_ALIASES,
    PRICE_ALIASES,
    FILL_QTY_ALIASES,
    ORDER_QTY_ALIASES,
    ORDER_ID_ALIASES,
    TRADE_ID_ALIASES,
    STATUS_ALIASES,
    POSITION_QTY_ALIASES,
    ACCOUNT_ALIASES,
    BALANCE_ALIASES,
    SIDE_ALIASES,
)
