from __future__ import annotations

import csv
import re
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class QuantDataArtifact:
    kind: str
    path: str
    format: str
    bytes: int = 0
    rows_sampled: int = 0
    columns: tuple[str, ...] = ()
    member_count: int = 0
    sample_members: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["columns"] = list(self.columns)
        payload["sample_members"] = list(self.sample_members)
        return payload


@dataclass(frozen=True)
class QuantDataAdapterResult:
    roots: tuple[str, ...]
    artifacts: tuple[QuantDataArtifact, ...]
    files_scanned: int = 0
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "roots": list(self.roots),
            "files_scanned": self.files_scanned,
            "artifacts": [item.to_dict() for item in self.artifacts],
            "warnings": list(self.warnings),
        }


def discover_quant_data(
    project: str | Path,
    roots: Iterable[str | Path] = (),
    *,
    max_files: int = 5000,
    sample_zip_members: int = 20,
) -> QuantDataAdapterResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    resolved_roots = tuple(_resolve_roots(project_path, roots))
    artifacts: list[QuantDataArtifact] = []
    warnings: list[str] = []
    files_scanned = 0
    for root in resolved_roots:
        if not root.exists():
            warnings.append(f"root not found: {root}")
            continue
        files = _iter_candidate_files(root)
        for path in files:
            files_scanned += 1
            if files_scanned > max_files:
                warnings.append(f"max_files reached: {max_files}")
                return QuantDataAdapterResult(tuple(str(item) for item in resolved_roots), tuple(artifacts), files_scanned, tuple(warnings))
            try:
                artifact = inspect_quant_data_file(path, sample_zip_members=sample_zip_members)
            except (OSError, zipfile.BadZipFile, UnicodeDecodeError, csv.Error) as exc:
                warnings.append(f"inspect failed: {path}: {exc}")
                continue
            if artifact.kind != "unknown":
                artifacts.append(artifact)
    return QuantDataAdapterResult(tuple(str(item) for item in resolved_roots), tuple(artifacts), files_scanned, tuple(warnings))


def inspect_quant_data_file(path: str | Path, *, sample_zip_members: int = 20) -> QuantDataArtifact:
    file_path = Path(path).expanduser().resolve(strict=False)
    suffix = file_path.suffix.lower()
    if suffix == ".zip":
        return _inspect_zip(file_path, sample_zip_members=sample_zip_members)
    if suffix == ".7z":
        return _inspect_7z(file_path)
    if suffix == ".csv":
        return _inspect_csv(file_path)
    return QuantDataArtifact("unknown", str(file_path), suffix.lstrip(".") or "file", bytes=_size(file_path))


def render_quant_data_adapter(result: QuantDataAdapterResult) -> str:
    lines = [
        "# Quant Data Adapter",
        "",
        f"- files_scanned: {result.files_scanned}",
        f"- artifacts: {len(result.artifacts)}",
        "",
        "## Roots",
        "",
    ]
    lines.extend(f"- {root}" for root in result.roots) if result.roots else lines.append("- none")
    lines.extend(["", "## Artifacts", ""])
    if not result.artifacts:
        lines.append("- none")
    for artifact in result.artifacts:
        detail = f"bytes={artifact.bytes} format={artifact.format}"
        if artifact.member_count:
            detail += f" members={artifact.member_count}"
        if artifact.rows_sampled:
            detail += f" rows_sampled={artifact.rows_sampled}"
        if artifact.columns:
            detail += " columns=" + ",".join(artifact.columns[:12])
        lines.append(f"- {artifact.kind}: {artifact.path} {detail}")
        if artifact.sample_members:
            lines.append("  samples: " + "; ".join(artifact.sample_members[:5]))
    lines.extend(["", "## Warnings", ""])
    if not result.warnings:
        lines.append("- none")
    for warning in result.warnings:
        lines.append(f"- {warning}")
    return "\n".join(lines).rstrip() + "\n"


def _resolve_roots(project: Path, roots: Iterable[str | Path]) -> list[Path]:
    explicit = [Path(root).expanduser() for root in roots if str(root).strip()]
    if explicit:
        return [(item if item.is_absolute() else project / item).resolve(strict=False) for item in explicit]
    home = Path.home()
    candidates = [
        project,
        home / "Desktop" / "2061票更新至4.30",
        home / "Desktop" / "榜单数据",
        home / "Downloads" / "榜单数据",
        home / "Downloads" / "分钟K线-股票241",
        home / "Downloads" / "A股_逐笔成交",
    ]
    return [item.resolve(strict=False) for item in candidates if item.exists()]


def _iter_candidate_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        if not _skip_metadata_file(root):
            yield root
        return
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".csv", ".zip", ".7z"} and not _skip_metadata_file(path):
            yield path


def _inspect_zip(path: Path, *, sample_zip_members: int) -> QuantDataArtifact:
    with zipfile.ZipFile(path) as zf:
        names = [name for name in zf.namelist() if not name.endswith("/")]
        csv_names = [name for name in names if name.lower().endswith(".csv")]
        sample_members = tuple(csv_names[:sample_zip_members])
        columns: tuple[str, ...] = ()
        rows_sampled = 0
        if csv_names:
            columns, rows_sampled = _read_zip_csv_sample(zf, csv_names[0])
    return QuantDataArtifact(
        kind=_classify_archive(path, sample_members, columns),
        path=str(path),
        format="zip",
        bytes=_size(path),
        rows_sampled=rows_sampled,
        columns=columns,
        member_count=len(names),
        sample_members=sample_members,
        metadata={"csv_members": len(csv_names)},
    )


def _inspect_7z(path: Path) -> QuantDataArtifact:
    return QuantDataArtifact(
        kind="tick_trade_7z_daily" if _looks_like_daily_7z(path) else "archive_7z",
        path=str(path),
        format="7z",
        bytes=_size(path),
        metadata={"date": _date_from_name(path.name) or ""},
    )


def _inspect_csv(path: Path) -> QuantDataArtifact:
    columns, rows_sampled = _read_csv_sample(path)
    return QuantDataArtifact(
        kind=_classify_csv(path, columns),
        path=str(path),
        format="csv",
        bytes=_size(path),
        rows_sampled=rows_sampled,
        columns=columns,
    )


def _read_zip_csv_sample(zf: zipfile.ZipFile, member: str, *, rows: int = 5) -> tuple[tuple[str, ...], int]:
    with zf.open(member) as raw:
        text = raw.read(64 * 1024)
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            decoded = text.decode(encoding)
            break
        except UnicodeDecodeError:
            decoded = ""
    reader = csv.DictReader(decoded.splitlines())
    columns = tuple(name for name in (reader.fieldnames or ()) if name)
    sampled = sum(1 for _, _ in zip(range(rows), reader))
    return columns, sampled


def _read_csv_sample(path: Path, *, rows: int = 20) -> tuple[tuple[str, ...], int]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = tuple(name for name in (reader.fieldnames or ()) if name)
            sampled = sum(1 for _, _ in zip(range(rows), reader))
            return columns, sampled
    except UnicodeDecodeError:
        with path.open("r", encoding="gb18030", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = tuple(name for name in (reader.fieldnames or ()) if name)
            sampled = sum(1 for _, _ in zip(range(rows), reader))
            return columns, sampled


def _skip_metadata_file(path: Path) -> bool:
    return path.name.startswith("._") or path.name == ".DS_Store"


def _classify_archive(path: Path, sample_members: tuple[str, ...], columns: tuple[str, ...]) -> str:
    text = f"{path} {' '.join(sample_members[:3])}"
    if "分钟" in text or any(freq in text for freq in ("1分钟", "5分钟", "15分钟", "30分钟", "60分钟")):
        return "minute_kline_zip"
    if any(name in text for name in ("不复权", "前复权", "后复权")):
        return "market_bar_zip"
    if {"日期", "开盘", "最高", "最低", "收盘"}.issubset(set(columns)):
        return "market_bar_zip"
    if "榜单" in text or "龙虎榜" in text or "热榜" in text:
        return "board_event_zip"
    return "zip_csv_archive" if sample_members else "zip_archive"


def _classify_csv(path: Path, columns: tuple[str, ...]) -> str:
    fields = set(columns)
    if {"entry_date", "net_return"}.issubset(fields):
        return "position_dedup_csv" if "dedup" in path.name.lower() else "position_csv"
    if {"date", "return"}.issubset(fields):
        return "backtest_return_csv"
    if {"TranID", "Time", "Price", "Volume"}.issubset(fields):
        return "tick_trade_csv"
    if {"日期", "开盘", "最高", "最低", "收盘"}.issubset(fields):
        return "minute_kline_csv" if "分钟" in str(path) else "market_bar_csv"
    if "榜单" in str(path) or "龙虎榜" in str(path) or "热榜" in str(path):
        return "board_event_csv"
    return "unknown"


def _looks_like_daily_7z(path: Path) -> bool:
    return bool(_date_from_name(path.name)) or "逐笔" in str(path)


def _date_from_name(name: str) -> str:
    match = re.search(r"(20\d{2}-\d{2}-\d{2})", name)
    return match.group(1) if match else ""


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0
