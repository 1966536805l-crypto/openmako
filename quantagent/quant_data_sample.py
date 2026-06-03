from __future__ import annotations

import csv
import json
import re
import subprocess
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .quant_expectations import run_quant_expectations


@dataclass(frozen=True)
class QuantDataSampleSpec:
    root: str
    code: str
    kind: str = "auto"
    freq: str = "1m"
    adjust: str = "前复权"
    date: str = ""
    start: str = ""
    end: str = ""
    max_rows: int = 1000
    output_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuantDataSampleResult:
    ok: bool
    spec: QuantDataSampleSpec
    source_path: str = ""
    source_member: str = ""
    output_path: str = ""
    rows_written: int = 0
    columns: tuple[str, ...] = ()
    expectation_kind: str = ""
    expectations: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["columns"] = list(self.columns)
        payload["warnings"] = list(self.warnings)
        return payload


def sample_local_quant_data(project: str | Path, spec: QuantDataSampleSpec) -> QuantDataSampleResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    root = Path(spec.root).expanduser()
    if not root.is_absolute():
        root = project_path / root
    root = root.resolve(strict=False)
    if not root.exists():
        return QuantDataSampleResult(False, spec, warnings=(f"root not found: {root}",))
    kind = _detect_request_kind(root, spec)
    output_path = _output_path(project_path, spec, kind)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "market_bar":
        result = _sample_market_zip(root, spec, output_path)
    elif kind == "minute_bar":
        result = _sample_minute_zip(root, spec, output_path)
    elif kind == "tick_trade":
        result = _sample_tick_7z(root, spec, output_path)
    else:
        return QuantDataSampleResult(False, spec, warnings=(f"unsupported sample kind: {kind}",))
    if not result.ok:
        return result
    expectation_kind = {
        "market_bar": "market_bar_csv",
        "minute_bar": "minute_bar_csv",
        "tick_trade": "tick_trade_csv",
    }.get(kind, "generic_csv")
    expectations = run_quant_expectations(result.output_path, kind=expectation_kind, sample_rows=min(max(1, spec.max_rows), 5000), hash_bytes=4 * 1024 * 1024)
    return QuantDataSampleResult(
        ok=bool(result.ok and expectations.ok),
        spec=spec,
        source_path=result.source_path,
        source_member=result.source_member,
        output_path=result.output_path,
        rows_written=result.rows_written,
        columns=result.columns,
        expectation_kind=expectation_kind,
        expectations=expectations.to_dict(),
        warnings=result.warnings,
    )


def render_quant_data_sample(result: QuantDataSampleResult) -> str:
    lines = [
        "# Quant Data Sample",
        "",
        f"- ok: {str(result.ok).lower()}",
        f"- kind: {result.spec.kind}",
        f"- code: {result.spec.code}",
        f"- source_path: {result.source_path or '-'}",
        f"- source_member: {result.source_member or '-'}",
        f"- output_path: {result.output_path or '-'}",
        f"- rows_written: {result.rows_written}",
        f"- columns: {len(result.columns)}",
        f"- expectation_kind: {result.expectation_kind or '-'}",
        f"- expectations_ok: {str(bool(result.expectations.get('ok'))).lower() if result.expectations else '-'}",
        "",
        "## Columns",
        "",
        "- " + ", ".join(result.columns) if result.columns else "- none",
        "",
        "## Warnings",
        "",
    ]
    lines.extend(f"- {warning}" for warning in result.warnings) if result.warnings else lines.append("- none")
    findings = result.expectations.get("findings") if isinstance(result.expectations, dict) else None
    lines.extend(["", "## Expectation Findings", ""])
    if not findings:
        lines.append("- none")
    else:
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            column = f" column={finding.get('column')}" if finding.get("column") else ""
            count = f" count={finding.get('count')}" if finding.get("count") else ""
            lines.append(f"- [{finding.get('level')}] {finding.get('code')}{column}{count}: {finding.get('message')}")
    return "\n".join(lines).rstrip() + "\n"


def _sample_market_zip(root: Path, spec: QuantDataSampleSpec, output_path: Path) -> QuantDataSampleResult:
    source = _find_market_zip(root, spec.adjust)
    if source is None:
        return QuantDataSampleResult(False, spec, warnings=(f"market zip not found under {root}",))
    with zipfile.ZipFile(source) as zf:
        member = _find_zip_member(zf, spec.code)
        if not member:
            return QuantDataSampleResult(False, spec, source_path=str(source), warnings=(f"code not found in zip: {spec.code}",))
        columns, rows = _read_zip_rows(zf, member, max_rows=max(1, spec.max_rows), start=spec.start, end=spec.end)
    rows_written = _write_rows(output_path, columns, rows)
    return QuantDataSampleResult(
        ok=rows_written > 0,
        spec=spec,
        source_path=str(source),
        source_member=member,
        output_path=str(output_path),
        rows_written=rows_written,
        columns=tuple(columns),
        warnings=() if rows_written else ("no rows matched filters",),
    )


def _sample_minute_zip(root: Path, spec: QuantDataSampleSpec, output_path: Path) -> QuantDataSampleResult:
    source = _find_minute_zip(root, spec)
    if source is None:
        return QuantDataSampleResult(False, spec, warnings=(f"minute zip not found under {root}",))
    freq = _freq_name(spec.freq)
    with zipfile.ZipFile(source) as zf:
        member = _find_zip_member(zf, spec.code, required_fragment=freq)
        if not member:
            member = _find_zip_member(zf, spec.code)
        if not member:
            return QuantDataSampleResult(False, spec, source_path=str(source), warnings=(f"code not found in zip: {spec.code}",))
        columns, rows = _read_zip_rows(zf, member, max_rows=max(1, spec.max_rows), start=spec.start or spec.date, end=spec.end or spec.date)
    rows_written = _write_rows(output_path, columns, rows)
    return QuantDataSampleResult(
        ok=rows_written > 0,
        spec=spec,
        source_path=str(source),
        source_member=member,
        output_path=str(output_path),
        rows_written=rows_written,
        columns=tuple(columns),
        warnings=() if rows_written else ("no rows matched filters",),
    )


def _sample_tick_7z(root: Path, spec: QuantDataSampleSpec, output_path: Path) -> QuantDataSampleResult:
    if not spec.date:
        return QuantDataSampleResult(False, spec, warnings=("tick_trade sampling requires --date YYYY-MM-DD",))
    source = _find_tick_7z(root, spec.date)
    if source is None:
        return QuantDataSampleResult(False, spec, warnings=(f"tick 7z not found for date: {spec.date}",))
    member = _find_7z_member(source, spec.code)
    if not member:
        return QuantDataSampleResult(False, spec, source_path=str(source), warnings=(f"code not found in 7z: {spec.code}",))
    rows, columns, warning = _extract_7z_csv_rows(source, member, max_rows=max(1, spec.max_rows))
    rows = _prefix_tick_time_with_date(rows, columns, spec.date)
    rows_written = _write_rows(output_path, columns, rows)
    warnings = tuple(item for item in (warning, "no rows matched filters" if rows_written == 0 else "") if item)
    return QuantDataSampleResult(
        ok=rows_written > 0,
        spec=spec,
        source_path=str(source),
        source_member=member,
        output_path=str(output_path),
        rows_written=rows_written,
        columns=tuple(columns),
        warnings=warnings,
    )


def _prefix_tick_time_with_date(rows: list[dict[str, str]], columns: list[str], date_text: str) -> list[dict[str, str]]:
    if not date_text:
        return rows
    time_column = next((column for column in columns if _normalize_tick_time_column(column)), "")
    if not time_column:
        return rows
    patched: list[dict[str, str]] = []
    for row in rows:
        updated = dict(row)
        raw = str(updated.get(time_column) or "").strip()
        if raw and _looks_time_only(raw):
            updated[time_column] = f"{date_text[:10]} {_normalize_tick_time_value(raw)}"
        patched.append(updated)
    return patched


def _normalize_tick_time_column(column: str) -> bool:
    return str(column).strip().lower() in {"time", "成交时间", "时间"}


def _looks_time_only(value: str) -> bool:
    text = value.strip()
    return bool(re.fullmatch(r"\d{1,2}:\d{2}:\d{2}(?:\.\d+)?", text) or re.fullmatch(r"\d{6}(?:\.\d+)?", text))


def _normalize_tick_time_value(value: str) -> str:
    text = value.strip()
    if re.fullmatch(r"\d{6}(?:\.\d+)?", text):
        whole, _, fractional = text.partition(".")
        normalized = f"{whole[:2]}:{whole[2:4]}:{whole[4:6]}"
        return normalized + (f".{fractional}" if fractional else "")
    return text


def _find_market_zip(root: Path, adjust: str) -> Path | None:
    if root.is_file() and root.suffix.lower() == ".zip":
        return root
    preferred = str(adjust or "前复权")
    zips = sorted(root.rglob("*.zip"), key=lambda item: (preferred not in item.name, len(str(item))))
    for path in zips:
        if preferred in path.name:
            return path
    for path in zips:
        if any(token in path.name for token in ("前复权", "后复权", "不复权")):
            return path
    return zips[0] if zips else None


def _find_minute_zip(root: Path, spec: QuantDataSampleSpec) -> Path | None:
    if root.is_file() and root.suffix.lower() == ".zip":
        return root
    date_text = spec.date or spec.start
    if date_text:
        direct = root / "2026" / "每日数据" / f"{date_text[:10]}.zip"
        if direct.exists():
            return direct
    if date_text.startswith("2026"):
        zips = sorted((root / "2026").glob("2026_*.zip")) if (root / "2026").exists() else []
        return zips[-1] if zips else None
    historical = root / "2000-2025" / "1分钟(2000-2025).zip"
    if historical.exists():
        return historical
    zips = sorted(root.rglob("*.zip"))
    minute = [path for path in zips if "分钟" in path.name or "每日数据" in str(path)]
    return minute[-1] if minute else (zips[-1] if zips else None)


def _find_tick_7z(root: Path, date_text: str) -> Path | None:
    if root.is_file() and root.suffix.lower() == ".7z":
        return root
    target = f"{date_text[:10]}.7z"
    matches = list(root.rglob(target))
    return matches[0] if matches else None


def _find_zip_member(zf: zipfile.ZipFile, code: str, *, required_fragment: str = "") -> str:
    normalized_code = _normalize_code(code)
    best = ""
    for name in zf.namelist():
        if not name.lower().endswith(".csv"):
            continue
        if required_fragment and required_fragment not in name:
            continue
        if normalized_code and normalized_code in _normalize_code(name):
            return name
        if normalized_code and Path(name).stem.endswith(normalized_code):
            best = best or name
    return best


def _read_zip_rows(zf: zipfile.ZipFile, member: str, *, max_rows: int, start: str = "", end: str = "") -> tuple[list[str], list[dict[str, str]]]:
    with zf.open(member) as raw:
        data = raw.read()
    text = _decode_bytes(data)
    reader = csv.DictReader(text.splitlines())
    columns = [name for name in (reader.fieldnames or []) if name]
    rows: list[dict[str, str]] = []
    for row in reader:
        if _row_in_range(row, start=start, end=end):
            rows.append(dict(row))
        if len(rows) >= max_rows:
            break
    return columns, rows


def _find_7z_member(path: Path, code: str) -> str:
    normalized_code = _normalize_code(code)
    try:
        proc = subprocess.run(["bsdtar", "-tf", str(path)], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    for line in proc.stdout.splitlines():
        if not line.lower().endswith(".csv"):
            continue
        if normalized_code in _normalize_code(line):
            return line.strip()
    return ""


def _extract_7z_csv_rows(path: Path, member: str, *, max_rows: int) -> tuple[list[dict[str, str]], list[str], str]:
    try:
        proc = subprocess.run(["bsdtar", "-xOf", str(path), member], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], [], str(exc)
    if proc.returncode != 0:
        return [], [], _decode_bytes(proc.stderr) or "bsdtar extraction failed"
    text = _decode_bytes(proc.stdout)
    reader = csv.DictReader(text.splitlines())
    columns = [name for name in (reader.fieldnames or []) if name]
    rows = [dict(row) for _, row in zip(range(max_rows), reader)]
    return rows, columns, ""


def _write_rows(path: Path, columns: list[str], rows: list[dict[str, str]]) -> int:
    if not columns:
        path.write_text("", encoding="utf-8")
        return 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return len(rows)


def _row_in_range(row: dict[str, str], *, start: str, end: str) -> bool:
    if not start and not end:
        return True
    value = ""
    for key in ("日期", "date", "datetime", "time", "Time", "成交时间"):
        if row.get(key):
            value = str(row.get(key) or "")[:10]
            break
    if not value:
        return True
    normalized = value.replace("/", "-")
    if start and normalized < start[:10]:
        return False
    if end and normalized > end[:10]:
        return False
    return True


def _detect_request_kind(root: Path, spec: QuantDataSampleSpec) -> str:
    if spec.kind and spec.kind != "auto":
        return spec.kind.replace("_csv", "").replace("_zip", "")
    text = str(root)
    if "逐笔" in text or root.suffix.lower() == ".7z":
        return "tick_trade"
    if "分钟" in text or _freq_name(spec.freq) in text:
        return "minute_bar"
    if "2061票" in text or any(token in text for token in ("前复权", "后复权", "不复权")):
        return "market_bar"
    return "market_bar"


def _output_path(project: Path, spec: QuantDataSampleSpec, kind: str) -> Path:
    if spec.output_path:
        path = Path(spec.output_path).expanduser()
        return path if path.is_absolute() else project / path
    code = _normalize_code(spec.code) or "unknown"
    date_part = spec.date or spec.start or "sample"
    name = f"{kind}_{code}_{date_part[:10].replace('-', '')}.csv"
    return project / ".quantagent" / "data_samples" / name


def _freq_name(freq: str) -> str:
    text = str(freq or "1m").lower()
    mapping = {
        "1m": "1分钟",
        "1min": "1分钟",
        "1分钟": "1分钟",
        "5m": "5分钟",
        "5min": "5分钟",
        "5分钟": "5分钟",
        "15m": "15分钟",
        "15min": "15分钟",
        "15分钟": "15分钟",
        "30m": "30分钟",
        "30min": "30分钟",
        "30分钟": "30分钟",
        "60m": "60分钟",
        "60min": "60分钟",
        "60分钟": "60分钟",
    }
    return mapping.get(text, str(freq or "1分钟"))


def _normalize_code(value: str) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-6:] if len(digits) >= 6 else digits


def _decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
