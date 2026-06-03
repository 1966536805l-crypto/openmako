from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .broker_gateway import BrokerGatewaySpec, build_broker_gateway_snapshot
from .quant_execution_replay import run_quant_execution_replay


PASS = "pass"
WARN = "warn"
BLOCK = "block"


@dataclass(frozen=True)
class QuantExecutionEvidenceSpec:
    tick_path: str = ""
    fill_path: str = ""
    broker_path: str = ""
    order_path: str = ""
    position_path: str = ""
    account_path: str = ""
    slippage_path: str = ""
    capacity_path: str = ""
    execution_source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuantExecutionIssue:
    level: str
    code: str
    message: str
    path: str = ""
    evidence_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuantExecutionArtifact:
    evidence_type: str
    path: str
    exists: bool
    bytes: int = 0
    sha256: str = ""
    format: str = ""
    rows_sampled: int = 0
    columns: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["columns"] = list(self.columns)
        return payload


@dataclass(frozen=True)
class QuantExecutionGateResult:
    action: str
    ok: bool
    live_ready: bool
    execution_source: str = ""
    required_evidence: tuple[str, ...] = ("tick", "fill", "broker", "slippage", "capacity")
    artifacts: tuple[QuantExecutionArtifact, ...] = ()
    issues: tuple[QuantExecutionIssue, ...] = ()
    broker_gateway: dict[str, Any] = field(default_factory=dict)
    execution_replay: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "ok": self.ok,
            "live_ready": self.live_ready,
            "execution_source": self.execution_source,
            "required_evidence": list(self.required_evidence),
            "artifacts": [item.to_dict() for item in self.artifacts],
            "issues": [item.to_dict() for item in self.issues],
            "broker_gateway": self.broker_gateway,
            "execution_replay": self.execution_replay,
        }


def run_quant_execution_gate(
    project: str | Path,
    spec: QuantExecutionEvidenceSpec,
    *,
    required_evidence: tuple[str, ...] = ("tick", "fill", "broker", "slippage", "capacity"),
) -> QuantExecutionGateResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    paths = {
        "tick": spec.tick_path,
        "fill": spec.fill_path,
        "broker": spec.broker_path,
        "order": spec.order_path,
        "position": spec.position_path,
        "account": spec.account_path,
        "slippage": spec.slippage_path,
        "capacity": spec.capacity_path,
    }
    artifacts: list[QuantExecutionArtifact] = []
    issues: list[QuantExecutionIssue] = []
    for evidence_type, raw in paths.items():
        if not raw:
            if evidence_type in required_evidence:
                issues.append(QuantExecutionIssue(BLOCK, "missing_evidence_path", f"{evidence_type} evidence file is required", evidence_type=evidence_type))
            continue
        artifact, artifact_issues = inspect_execution_artifact(project_path, evidence_type, raw)
        artifacts.append(artifact)
        issues.extend(artifact_issues)
    broker_gateway: dict[str, Any] = {}
    execution_replay: dict[str, Any] = {}
    broker_snapshot = None
    if spec.broker_path or spec.fill_path or spec.order_path or spec.position_path or spec.account_path:
        broker_snapshot = build_broker_gateway_snapshot(
            project_path,
            BrokerGatewaySpec(
                broker_path=spec.broker_path,
                fill_path=spec.fill_path,
                order_path=spec.order_path,
                position_path=spec.position_path,
                account_path=spec.account_path,
                source=spec.execution_source,
            ),
        )
        broker_gateway = broker_snapshot.to_dict()
        for issue in broker_snapshot.issues:
            issues.append(
                QuantExecutionIssue(
                    issue.level,
                    "broker_gateway_" + issue.code,
                    issue.message,
                    path=issue.path,
                    evidence_type=issue.kind or "broker_gateway",
                )
            )
        if spec.fill_path and "fill" in required_evidence and not broker_snapshot.has_live_fill_evidence:
            issues.append(QuantExecutionIssue(BLOCK, "no_live_fill_evidence", "Fill evidence did not normalize into live fill records", evidence_type="fill"))
        if spec.broker_path and "broker" in required_evidence and not broker_snapshot.has_broker_provenance:
            issues.append(QuantExecutionIssue(BLOCK, "no_broker_provenance", "Broker evidence did not normalize into broker/account provenance", evidence_type="broker"))
        if broker_snapshot is not None and (spec.tick_path or spec.fill_path):
            replay = run_quant_execution_replay(
                project_path,
                tick_path=spec.tick_path,
                slippage_path=spec.slippage_path,
                capacity_path=spec.capacity_path,
                broker_snapshot=broker_snapshot,
            )
            execution_replay = replay.to_dict()
            replay_paths = {
                "tick": spec.tick_path,
                "fill": spec.fill_path,
                "order": spec.order_path,
                "position": spec.position_path,
                "slippage": spec.slippage_path,
                "capacity": spec.capacity_path,
            }
            for issue in replay.issues:
                issues.append(
                    QuantExecutionIssue(
                        issue.level,
                        "execution_replay_" + issue.code,
                        issue.message,
                        path=replay_paths.get(issue.evidence_type, ""),
                        evidence_type=issue.evidence_type or "execution_replay",
                    )
                )
    if not spec.execution_source.strip():
        issues.append(QuantExecutionIssue(BLOCK, "missing_execution_source", "Execution source/provenance is required"))
    present = {item.evidence_type for item in artifacts if item.exists}
    for evidence_type in required_evidence:
        if evidence_type not in present and not any(issue.code == "missing_evidence_path" and issue.evidence_type == evidence_type for issue in issues):
            issues.append(QuantExecutionIssue(BLOCK, "missing_evidence_file", f"{evidence_type} evidence file is missing", evidence_type=evidence_type))
    blocked = any(issue.level == BLOCK for issue in issues)
    live_ready = bool(not blocked and set(required_evidence).issubset(present) and spec.execution_source.strip())
    return QuantExecutionGateResult(
        action=PASS if live_ready else BLOCK,
        ok=live_ready,
        live_ready=live_ready,
        execution_source=spec.execution_source,
        required_evidence=required_evidence,
        artifacts=tuple(artifacts),
        issues=tuple(issues),
        broker_gateway=broker_gateway,
        execution_replay=execution_replay,
    )


def inspect_execution_artifact(project: Path, evidence_type: str, raw_path: str | Path) -> tuple[QuantExecutionArtifact, tuple[QuantExecutionIssue, ...]]:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = project / path
    path = path.resolve(strict=False)
    if not path.exists():
        return (
            QuantExecutionArtifact(evidence_type=evidence_type, path=str(path), exists=False),
            (QuantExecutionIssue(BLOCK, "file_not_found", "Evidence file does not exist", path=str(path), evidence_type=evidence_type),),
        )
    if path.is_dir():
        return (
            QuantExecutionArtifact(evidence_type=evidence_type, path=str(path), exists=True, bytes=0, format="directory"),
            (QuantExecutionIssue(BLOCK, "directory_not_file", "Evidence path must be a file, not a directory", path=str(path), evidence_type=evidence_type),),
        )
    size = path.stat().st_size
    artifact = QuantExecutionArtifact(
        evidence_type=evidence_type,
        path=str(path),
        exists=True,
        bytes=size,
        sha256=_sha256_file(path),
        format=_format_for(path),
    )
    issues: list[QuantExecutionIssue] = []
    if size == 0:
        issues.append(QuantExecutionIssue(BLOCK, "empty_file", "Evidence file is empty", path=str(path), evidence_type=evidence_type))
        return artifact, tuple(issues)
    if path.suffix.lower() == ".csv":
        artifact, csv_issues = _inspect_csv_artifact(path, artifact, evidence_type)
        issues.extend(csv_issues)
    elif path.suffix.lower() == ".json":
        artifact, json_issues = _inspect_json_artifact(path, artifact, evidence_type)
        issues.extend(json_issues)
    else:
        issues.append(QuantExecutionIssue(WARN, "opaque_file", "Evidence file was hashed but schema could not be inspected", path=str(path), evidence_type=evidence_type))
    return artifact, tuple(issues)


def render_quant_execution_gate(result: QuantExecutionGateResult) -> str:
    lines = [
        "# Quant Execution Gate",
        "",
        f"- action: {result.action}",
        f"- ok: {str(result.ok).lower()}",
        f"- live_ready: {str(result.live_ready).lower()}",
        f"- execution_source: {result.execution_source or '-'}",
        f"- required_evidence: {', '.join(result.required_evidence)}",
        f"- broker_gateway_ok: {str(bool(result.broker_gateway.get('ok'))).lower() if result.broker_gateway else '-'}",
        f"- broker_gateway_live_fills: {str(bool(result.broker_gateway.get('has_live_fill_evidence'))).lower() if result.broker_gateway else '-'}",
        f"- execution_replay_ok: {str(bool(result.execution_replay.get('ok'))).lower() if result.execution_replay else '-'}",
        f"- fills_explained: {result.execution_replay.get('fills_explained', '-') if result.execution_replay else '-'}",
        f"- order_lifecycle_ok: {str(bool(result.execution_replay.get('order_lifecycle_ok'))).lower() if result.execution_replay else '-'}",
        f"- broker_reconciliation_ok: {str(bool(result.execution_replay.get('broker_reconciliation_ok'))).lower() if result.execution_replay else '-'}",
        "",
        "## Artifacts",
        "",
    ]
    if not result.artifacts:
        lines.append("- none")
    for artifact in result.artifacts:
        columns = ",".join(artifact.columns) if artifact.columns else "-"
        lines.append(
            f"- {artifact.evidence_type}: {artifact.path} bytes={artifact.bytes} "
            f"sha256={artifact.sha256 or '-'} format={artifact.format or '-'} rows_sampled={artifact.rows_sampled} columns={columns}"
        )
    lines.extend(["", "## Issues", ""])
    if not result.issues:
        lines.append("- none")
    for issue in result.issues:
        suffix = f" path={issue.path}" if issue.path else ""
        lines.append(f"- [{issue.level}] {issue.code} {issue.evidence_type}{suffix}: {issue.message}".rstrip())
    return "\n".join(lines).rstrip() + "\n"


def _inspect_csv_artifact(
    path: Path,
    artifact: QuantExecutionArtifact,
    evidence_type: str,
    *,
    sample_rows: int = 200,
) -> tuple[QuantExecutionArtifact, tuple[QuantExecutionIssue, ...]]:
    issues: list[QuantExecutionIssue] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = tuple(name for name in (reader.fieldnames or ()) if name)
            rows = [row for _, row in zip(range(sample_rows), reader)]
    except UnicodeDecodeError:
        with path.open("r", encoding="gb18030", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = tuple(name for name in (reader.fieldnames or ()) if name)
            rows = [row for _, row in zip(range(sample_rows), reader)]
    if not columns:
        issues.append(QuantExecutionIssue(BLOCK, "missing_csv_header", "CSV evidence has no header", path=str(path), evidence_type=evidence_type))
    if not rows:
        issues.append(QuantExecutionIssue(BLOCK, "empty_csv_rows", "CSV evidence has no sampled rows", path=str(path), evidence_type=evidence_type))
    missing_groups = _missing_column_groups(evidence_type, columns)
    for group in missing_groups:
        issues.append(
            QuantExecutionIssue(
                BLOCK,
                "missing_required_column_group",
                "CSV evidence is missing one required column group: " + "/".join(group),
                path=str(path),
                evidence_type=evidence_type,
            )
        )
    # Check time range for tick/fill evidence
    if evidence_type in ("tick", "fill") and rows:
        # Default to stock, but auto-detection will override if futures patterns detected
        asset_type = "stock"
        time_issue = _check_trading_hours(rows, columns, evidence_type, str(path), asset_type)
        if time_issue:
            issues.append(time_issue)

    # Capacity-specific sample size validation
    if evidence_type == "capacity" and rows:
        capacity_issues = _validate_capacity_sample_size(path, columns, rows)
        issues.extend(capacity_issues)

    return (
        QuantExecutionArtifact(
            evidence_type=artifact.evidence_type,
            path=artifact.path,
            exists=artifact.exists,
            bytes=artifact.bytes,
            sha256=artifact.sha256,
            format="csv",
            rows_sampled=len(rows),
            columns=columns,
            metadata={"schema_family": evidence_type},
        ),
        tuple(issues),
    )


def _inspect_json_artifact(path: Path, artifact: QuantExecutionArtifact, evidence_type: str) -> tuple[QuantExecutionArtifact, tuple[QuantExecutionIssue, ...]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return artifact, (QuantExecutionIssue(BLOCK, "invalid_json", str(exc), path=str(path), evidence_type=evidence_type),)
    keys = tuple(sorted(str(key) for key in payload.keys())) if isinstance(payload, dict) else ()
    if not payload:
        issues = (QuantExecutionIssue(BLOCK, "empty_json", "JSON evidence is empty", path=str(path), evidence_type=evidence_type),)
    else:
        issues = ()
    return (
        QuantExecutionArtifact(
            evidence_type=artifact.evidence_type,
            path=artifact.path,
            exists=artifact.exists,
            bytes=artifact.bytes,
            sha256=artifact.sha256,
            format="json",
            rows_sampled=1,
            columns=keys,
            metadata={"json_type": type(payload).__name__},
        ),
        issues,
    )


def _missing_column_groups(evidence_type: str, columns: tuple[str, ...]) -> list[tuple[str, ...]]:
    lowered = {_norm(column) for column in columns}
    required = {
        "tick": (("time", "timestamp", "datetime", "日期"), ("price", "成交价", "价格"), ("volume", "qty", "成交量")),
        "fill": (("time", "timestamp", "datetime", "成交时间"), ("code", "symbol", "证券代码"), ("price", "fill_price", "成交价"), ("qty", "volume", "成交数量", "成交量")),
        "broker": (("broker", "account", "账户", "券商"),),
        "order": (("order_id", "orderid", "vt_orderid", "委托编号", "订单号"), ("code", "symbol", "证券代码"), ("qty", "quantity", "volume", "数量"), ("status", "state", "状态")),
        "position": (("code", "symbol", "证券代码"), ("quantity", "volume", "position", "持仓", "证券数量")),
        "account": (("account", "account_id", "accountid", "资金账号", "账户"),),
        "slippage": (("slippage", "slippage_bps", "滑点"),),
        "capacity": (("capacity", "max_notional", "成交额", "容量"),),
    }.get(evidence_type, ())
    missing: list[tuple[str, ...]] = []
    for group in required:
        if not any(_norm(item) in lowered for item in group):
            missing.append(group)
    return missing


def _format_for(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    return suffix or "file"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _norm(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "").replace("-", "").replace(" ", "")


def _check_trading_hours(rows: list[dict[str, Any]], columns: tuple[str, ...], evidence_type: str, path: str, asset_type: str = "stock") -> QuantExecutionIssue | None:
    """Check if tick/fill data timestamps are within trading hours.

    Trading hours by asset type:
    - stock: 09:30-15:00
    - futures_day: 09:00-15:15
    - futures_night: 21:00-23:00, 00:00-02:30, and 09:00-15:15 (day session also valid)
    """
    from datetime import datetime

    # Find time column
    time_col = None
    for col in columns:
        norm = _norm(col)
        if norm in ("time", "timestamp", "datetime", "日期", "成交时间"):
            time_col = col
            break

    if not time_col:
        return None

    # Define trading hours by asset type (in seconds for precise boundary checking)
    trading_hours = {
        "stock": [(9 * 3600 + 30 * 60, 15 * 3600 + 1)],  # 09:30:00 to 15:00:00 inclusive
        "futures_day": [(9 * 3600, 15 * 3600 + 15 * 60)],  # 09:00:00 to 15:14:59
        "futures_night": [(21 * 3600, 23 * 3600), (0, 2 * 3600 + 30 * 60), (9 * 3600, 15 * 3600 + 15 * 60)],  # Night + day sessions
    }

    # Auto-detect asset type based on time distribution
    detected_asset_type = _detect_asset_type(rows, time_col, asset_type)
    hours = trading_hours.get(detected_asset_type, trading_hours["stock"])

    out_of_hours_count = 0
    total_checked = 0

    for row in rows:
        time_str = row.get(time_col, "").strip()
        if not time_str:
            continue

        try:
            # Parse time - support formats like "2018-03-15 09:25:00" or "09:25:00"
            if " " in time_str:
                time_part = time_str.split(" ")[1]
            else:
                time_part = time_str

            # Extract hour, minute, and second
            time_parts = time_part.split(":")
            if len(time_parts) >= 2:
                hour = int(time_parts[0])
                minute = int(time_parts[1])
                second = int(time_parts[2]) if len(time_parts) >= 3 else 0

                # Convert to seconds for precise boundary checking
                time_seconds = hour * 3600 + minute * 60 + second
                in_hours = any(start <= time_seconds < end for start, end in hours)

                total_checked += 1
                if not in_hours:
                    out_of_hours_count += 1
        except (ValueError, IndexError):
            continue

    if total_checked > 0 and out_of_hours_count > 0:
        ratio = out_of_hours_count / total_checked
        hours_desc = _format_trading_hours(detected_asset_type)
        return QuantExecutionIssue(
            WARN,
            "time_outside_trading_hours",
            f"Found {out_of_hours_count}/{total_checked} ({ratio:.1%}) timestamps outside {hours_desc} trading hours (detected: {detected_asset_type})",
            path=path,
            evidence_type=evidence_type,
        )

    return None


def _detect_asset_type(rows: list[dict[str, Any]], time_col: str, default: str = "stock") -> str:
    """Auto-detect asset type based on time distribution in the data."""
    night_count = 0
    futures_only_hours_count = 0
    valid_stock_hours_count = 0
    total = 0

    for row in rows:
        time_str = row.get(time_col, "").strip()
        if not time_str:
            continue

        try:
            if " " in time_str:
                time_part = time_str.split(" ")[1]
            else:
                time_part = time_str

            time_parts = time_part.split(":")
            if len(time_parts) >= 2:
                hour = int(time_parts[0])
                minute = int(time_parts[1])
                second = int(time_parts[2]) if len(time_parts) >= 3 else 0
                time_seconds = hour * 3600 + minute * 60 + second

                total += 1

                # Night session: 21:00:00 to 22:59:59 or 00:00:00 to 02:29:59
                if (21 * 3600 <= time_seconds < 23 * 3600) or (0 <= time_seconds < 2 * 3600 + 30 * 60):
                    night_count += 1
                # Futures-only day hours: 09:00:00 to 09:29:59 or 15:00:01 to 15:14:59
                # Note: 15:00:00 is valid for stock (inclusive), so futures-only starts at 15:00:01
                elif (9 * 3600 <= time_seconds < 9 * 3600 + 30 * 60) or (15 * 3600 + 1 <= time_seconds < 15 * 3600 + 15 * 60):
                    futures_only_hours_count += 1
                # Valid stock hours: 09:30:00 to 15:00:00 (inclusive)
                elif 9 * 3600 + 30 * 60 <= time_seconds <= 15 * 3600:
                    valid_stock_hours_count += 1
        except (ValueError, IndexError):
            continue

    if total == 0:
        return default

    # If >10% of data is in night session, classify as futures_night
    if night_count / total > 0.1:
        return "futures_night"
    # Only classify as futures_day if >50% of data is in futures-only hours
    # This prevents misclassification when only a few timestamps are slightly out of stock hours
    elif futures_only_hours_count > 0 and futures_only_hours_count / total > 0.5:
        return "futures_day"

    return default


def _format_trading_hours(asset_type: str) -> str:
    """Format trading hours description for display."""
    hours_map = {
        "stock": "09:30-15:00",
        "futures_day": "09:00-15:15",
        "futures_night": "21:00-23:00/00:00-02:30",
    }
    return hours_map.get(asset_type, "09:30-15:00")


def _validate_capacity_sample_size(path: Path, columns: tuple[str, ...], rows: list[dict[str, Any]]) -> list[QuantExecutionIssue]:
    """Validate capacity CSV has sufficient sample size (rows and total notional)."""
    issues: list[QuantExecutionIssue] = []

    # Count total rows in file (not just sampled)
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            next(reader, None)  # Skip header
            total_rows = sum(1 for _ in reader)
    except UnicodeDecodeError:
        with path.open("r", encoding="gb18030", newline="") as handle:
            reader = csv.reader(handle)
            next(reader, None)  # Skip header
            total_rows = sum(1 for _ in reader)

    # Check minimum row count
    if total_rows < 100:
        issues.append(
            QuantExecutionIssue(
                WARN,
                "capacity_insufficient_sample_size",
                f"Capacity evidence has only {total_rows} rows, recommended minimum is 100 rows for reliable capacity estimation",
                path=str(path),
                evidence_type="capacity",
            )
        )

    # Find capacity/notional column
    capacity_col = None
    for col in columns:
        norm = _norm(col)
        if norm in ("capacity", "maxnotional", "成交额", "容量", "notional"):
            capacity_col = col
            break

    if capacity_col:
        # Calculate total notional from sampled rows
        total_notional = 0.0
        valid_values = 0

        for row in rows:
            value_str = row.get(capacity_col, "").strip()
            if not value_str:
                continue

            try:
                value = float(value_str)
                if value > 0:
                    total_notional += value
                    valid_values += 1
            except (ValueError, TypeError):
                continue

        # Estimate total notional for entire file if we only sampled
        if valid_values > 0 and total_rows > len(rows):
            estimated_total = total_notional * (total_rows / len(rows))
        else:
            estimated_total = total_notional

        # Check minimum notional threshold
        if estimated_total < 1000000:
            issues.append(
                QuantExecutionIssue(
                    WARN,
                    "capacity_insufficient_notional",
                    f"Capacity evidence total notional is {estimated_total:.0f}, recommended minimum is 1,000,000 for reliable capacity estimation",
                    path=str(path),
                    evidence_type="capacity",
                )
            )

    return issues

