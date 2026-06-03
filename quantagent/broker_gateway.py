from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping


PASS = "pass"
WARN = "warn"
BLOCK = "block"


@dataclass(frozen=True)
class BrokerGatewaySpec:
    broker_path: str = ""
    fill_path: str = ""
    order_path: str = ""
    position_path: str = ""
    account_path: str = ""
    source: str = ""
    gateway: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BrokerGatewayIssue:
    level: str
    code: str
    message: str
    kind: str = ""
    path: str = ""
    row: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BrokerGatewayArtifact:
    kind: str
    path: str
    exists: bool
    bytes: int = 0
    sha256: str = ""
    format: str = ""
    rows_sampled: int = 0
    columns: tuple[str, ...] = ()
    records_normalized: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["columns"] = list(self.columns)
        return payload


@dataclass(frozen=True)
class BrokerFill:
    code: str
    time: str
    price: float
    quantity: float
    side: str = ""
    order_id: str = ""
    trade_id: str = ""
    status: str = ""
    source_row: int = 0

    @property
    def notional(self) -> float:
        return float(self.price * self.quantity)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["notional"] = self.notional
        return payload


@dataclass(frozen=True)
class BrokerOrder:
    code: str
    order_id: str
    time: str = ""
    side: str = ""
    price: float | None = None
    quantity: float | None = None
    traded: float | None = None
    status: str = ""
    source_row: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BrokerPosition:
    code: str
    quantity: float
    available: float | None = None
    cost_price: float | None = None
    pnl: float | None = None
    source_row: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BrokerAccount:
    account_id: str
    broker: str = ""
    balance: float | None = None
    available: float | None = None
    frozen: float | None = None
    currency: str = ""
    source_row: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BrokerGatewaySnapshot:
    spec: BrokerGatewaySpec
    artifacts: tuple[BrokerGatewayArtifact, ...] = ()
    broker_names: tuple[str, ...] = ()
    account_ids: tuple[str, ...] = ()
    fills: tuple[BrokerFill, ...] = ()
    orders: tuple[BrokerOrder, ...] = ()
    positions: tuple[BrokerPosition, ...] = ()
    accounts: tuple[BrokerAccount, ...] = ()
    issues: tuple[BrokerGatewayIssue, ...] = ()

    @property
    def has_broker_provenance(self) -> bool:
        return bool(self.broker_names or self.account_ids or self.accounts or self.spec.gateway)

    @property
    def has_live_fill_evidence(self) -> bool:
        return any(item.code and item.time and item.price > 0 and item.quantity > 0 for item in self.fills)

    @property
    def ok(self) -> bool:
        if any(issue.level == BLOCK for issue in self.issues):
            return False
        return bool(
            self.has_broker_provenance
            or self.has_live_fill_evidence
            or self.orders
            or self.positions
            or self.accounts
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec": self.spec.to_dict(),
            "ok": self.ok,
            "has_broker_provenance": self.has_broker_provenance,
            "has_live_fill_evidence": self.has_live_fill_evidence,
            "artifacts": [item.to_dict() for item in self.artifacts],
            "broker_names": list(self.broker_names),
            "account_ids": list(self.account_ids),
            "fills": [item.to_dict() for item in self.fills],
            "orders": [item.to_dict() for item in self.orders],
            "positions": [item.to_dict() for item in self.positions],
            "accounts": [item.to_dict() for item in self.accounts],
            "issues": [item.to_dict() for item in self.issues],
        }


def build_broker_gateway_snapshot(
    project: str | Path,
    spec: BrokerGatewaySpec,
    *,
    sample_rows: int = 500,
) -> BrokerGatewaySnapshot:
    project_path = Path(project).expanduser().resolve(strict=False)
    artifacts: list[BrokerGatewayArtifact] = []
    issues: list[BrokerGatewayIssue] = []
    broker_names: set[str] = set()
    account_ids: set[str] = set()
    fills: list[BrokerFill] = []
    orders: list[BrokerOrder] = []
    positions: list[BrokerPosition] = []
    accounts: list[BrokerAccount] = []

    files = (
        ("broker", spec.broker_path),
        ("fill", spec.fill_path),
        ("order", spec.order_path),
        ("position", spec.position_path),
        ("account", spec.account_path),
    )
    for kind, raw_path in files:
        if not raw_path:
            continue
        artifact, rows, load_issues = _load_table(project_path, kind, raw_path, sample_rows=sample_rows)
        artifacts.append(artifact)
        issues.extend(load_issues)
        if load_issues or not rows:
            continue
        if kind == "fill":
            normalized, normalize_issues = _normalize_fills(rows, artifact.path)
            fills.extend(normalized)
            issues.extend(normalize_issues)
            artifacts[-1] = _artifact_with_count(artifact, len(normalized))
        elif kind == "order":
            normalized, normalize_issues = _normalize_orders(rows, artifact.path)
            orders.extend(normalized)
            issues.extend(normalize_issues)
            artifacts[-1] = _artifact_with_count(artifact, len(normalized))
        elif kind == "position":
            normalized, normalize_issues = _normalize_positions(rows, artifact.path)
            positions.extend(normalized)
            issues.extend(normalize_issues)
            artifacts[-1] = _artifact_with_count(artifact, len(normalized))
        elif kind == "account":
            normalized = _normalize_accounts(rows, artifact.path)
            accounts.extend(normalized)
            artifacts[-1] = _artifact_with_count(artifact, len(normalized))
        elif kind == "broker":
            names, ids, normalized_accounts = _normalize_broker_provenance(rows, artifact.path)
            broker_names.update(names)
            account_ids.update(ids)
            accounts.extend(normalized_accounts)
            artifacts[-1] = _artifact_with_count(artifact, len(names) + len(ids) + len(normalized_accounts))

    if spec.gateway:
        broker_names.add(spec.gateway)
    for account in accounts:
        if account.broker:
            broker_names.add(account.broker)
        if account.account_id:
            account_ids.add(account.account_id)

    if spec.fill_path and not any(issue.kind == "fill" and issue.level == BLOCK for issue in issues) and not fills:
        issues.append(BrokerGatewayIssue(BLOCK, "no_normalized_fills", "Fill file did not contain any normalized fills", kind="fill", path=str(_resolve(project_path, spec.fill_path))))
    if spec.broker_path and not any(issue.kind == "broker" and issue.level == BLOCK for issue in issues) and not (broker_names or account_ids):
        issues.append(BrokerGatewayIssue(BLOCK, "no_broker_provenance", "Broker file did not contain broker/account provenance", kind="broker", path=str(_resolve(project_path, spec.broker_path))))

    return BrokerGatewaySnapshot(
        spec=spec,
        artifacts=tuple(artifacts),
        broker_names=tuple(sorted(broker_names)),
        account_ids=tuple(sorted(account_ids)),
        fills=tuple(fills),
        orders=tuple(orders),
        positions=tuple(positions),
        accounts=tuple(accounts),
        issues=tuple(issues),
    )


def render_broker_gateway_snapshot(snapshot: BrokerGatewaySnapshot) -> str:
    lines = [
        "# Broker Gateway Snapshot",
        "",
        f"- ok: {str(snapshot.ok).lower()}",
        f"- source: {snapshot.spec.source or '-'}",
        f"- gateway: {snapshot.spec.gateway or '-'}",
        f"- has_broker_provenance: {str(snapshot.has_broker_provenance).lower()}",
        f"- has_live_fill_evidence: {str(snapshot.has_live_fill_evidence).lower()}",
        f"- broker_names: {', '.join(snapshot.broker_names) if snapshot.broker_names else '-'}",
        f"- account_ids: {', '.join(snapshot.account_ids) if snapshot.account_ids else '-'}",
        f"- fills: {len(snapshot.fills)}",
        f"- orders: {len(snapshot.orders)}",
        f"- positions: {len(snapshot.positions)}",
        f"- accounts: {len(snapshot.accounts)}",
        "",
        "## Artifacts",
        "",
    ]
    if not snapshot.artifacts:
        lines.append("- none")
    for artifact in snapshot.artifacts:
        columns = ",".join(artifact.columns) if artifact.columns else "-"
        lines.append(
            f"- {artifact.kind}: {artifact.path} bytes={artifact.bytes} sha256={artifact.sha256 or '-'} "
            f"format={artifact.format or '-'} rows_sampled={artifact.rows_sampled} "
            f"records_normalized={artifact.records_normalized} columns={columns}"
        )
    lines.extend(["", "## Issues", ""])
    if not snapshot.issues:
        lines.append("- none")
    for issue in snapshot.issues:
        row = f" row={issue.row}" if issue.row else ""
        path = f" path={issue.path}" if issue.path else ""
        lines.append(f"- [{issue.level}] {issue.code} {issue.kind}{row}{path}: {issue.message}".rstrip())
    return "\n".join(lines).rstrip() + "\n"


def _load_table(
    project: Path,
    kind: str,
    raw_path: str | Path,
    *,
    sample_rows: int,
) -> tuple[BrokerGatewayArtifact, list[dict[str, str]], list[BrokerGatewayIssue]]:
    path = _resolve(project, raw_path)
    if not path.exists():
        return (
            BrokerGatewayArtifact(kind=kind, path=str(path), exists=False),
            [],
            [BrokerGatewayIssue(BLOCK, "file_not_found", "Broker gateway file does not exist", kind=kind, path=str(path))],
        )
    if path.is_dir():
        return (
            BrokerGatewayArtifact(kind=kind, path=str(path), exists=True, format="directory"),
            [],
            [BrokerGatewayIssue(BLOCK, "directory_not_file", "Broker gateway path must be a file", kind=kind, path=str(path))],
        )
    artifact = BrokerGatewayArtifact(
        kind=kind,
        path=str(path),
        exists=True,
        bytes=path.stat().st_size,
        sha256=_sha256_file(path),
        format=path.suffix.lower().lstrip(".") or "file",
    )
    if artifact.bytes == 0:
        return artifact, [], [BrokerGatewayIssue(BLOCK, "empty_file", "Broker gateway file is empty", kind=kind, path=str(path))]
    if path.suffix.lower() == ".csv":
        return _load_csv_table(path, artifact, kind, sample_rows=sample_rows)
    if path.suffix.lower() == ".json":
        return _load_json_table(path, artifact, kind, sample_rows=sample_rows)
    return artifact, [], [BrokerGatewayIssue(WARN, "opaque_file", "File was hashed but not parsed as table evidence", kind=kind, path=str(path))]


def _load_csv_table(
    path: Path,
    artifact: BrokerGatewayArtifact,
    kind: str,
    *,
    sample_rows: int,
) -> tuple[BrokerGatewayArtifact, list[dict[str, str]], list[BrokerGatewayIssue]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = tuple(name for name in (reader.fieldnames or ()) if name)
            rows = [dict(row) for _, row in zip(range(sample_rows), reader)]
    except UnicodeDecodeError:
        with path.open("r", encoding="gb18030", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = tuple(name for name in (reader.fieldnames or ()) if name)
            rows = [dict(row) for _, row in zip(range(sample_rows), reader)]
    loaded = BrokerGatewayArtifact(
        kind=artifact.kind,
        path=artifact.path,
        exists=artifact.exists,
        bytes=artifact.bytes,
        sha256=artifact.sha256,
        format="csv",
        rows_sampled=len(rows),
        columns=columns,
    )
    issues: list[BrokerGatewayIssue] = []
    if not columns:
        issues.append(BrokerGatewayIssue(BLOCK, "missing_header", "CSV has no header", kind=kind, path=str(path)))
    if not rows:
        issues.append(BrokerGatewayIssue(BLOCK, "empty_rows", "CSV has no sampled rows", kind=kind, path=str(path)))
    return loaded, rows, issues


def _load_json_table(
    path: Path,
    artifact: BrokerGatewayArtifact,
    kind: str,
    *,
    sample_rows: int,
) -> tuple[BrokerGatewayArtifact, list[dict[str, str]], list[BrokerGatewayIssue]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return artifact, [], [BrokerGatewayIssue(BLOCK, "invalid_json", str(exc), kind=kind, path=str(path))]
    rows: list[Mapping[str, Any]]
    if isinstance(payload, list):
        rows = [item for item in payload if isinstance(item, Mapping)]
    elif isinstance(payload, Mapping):
        inner = payload.get(kind) or payload.get(kind + "s") or payload.get("rows") or payload.get("data")
        if isinstance(inner, list):
            rows = [item for item in inner if isinstance(item, Mapping)]
        else:
            rows = [payload]
    else:
        rows = []
    sampled = rows[:sample_rows]
    columns = tuple(sorted({str(key) for row in sampled for key in row.keys()}))
    loaded = BrokerGatewayArtifact(
        kind=artifact.kind,
        path=artifact.path,
        exists=artifact.exists,
        bytes=artifact.bytes,
        sha256=artifact.sha256,
        format="json",
        rows_sampled=len(sampled),
        columns=columns,
    )
    if not sampled:
        return loaded, [], [BrokerGatewayIssue(BLOCK, "empty_rows", "JSON has no object rows", kind=kind, path=str(path))]
    return loaded, [{str(key): "" if value is None else str(value) for key, value in row.items()} for row in sampled], []


def _normalize_fills(rows: Iterable[Mapping[str, str]], path: str) -> tuple[list[BrokerFill], list[BrokerGatewayIssue]]:
    fills: list[BrokerFill] = []
    issues: list[BrokerGatewayIssue] = []
    for index, row in enumerate(rows, start=1):
        code = _get(row, CODE_ALIASES)
        time = _get(row, TIME_ALIASES)
        price = _float_or_none(_get(row, PRICE_ALIASES))
        quantity = _float_or_none(_get(row, QUANTITY_ALIASES))
        missing = []
        if not code:
            missing.append("code")
        if not time:
            missing.append("time")
        if price is None or price <= 0:
            missing.append("price")
        if quantity is None or quantity <= 0:
            missing.append("quantity")
        if missing:
            issues.append(BrokerGatewayIssue(BLOCK, "invalid_fill_row", "Fill row missing " + ",".join(missing), kind="fill", path=path, row=index))
            continue
        fills.append(
            BrokerFill(
                code=code,
                time=time,
                price=price,
                quantity=quantity,
                side=_normalize_side(_get(row, SIDE_ALIASES)),
                order_id=_get(row, ORDER_ID_ALIASES),
                trade_id=_get(row, TRADE_ID_ALIASES),
                status=_get(row, STATUS_ALIASES),
                source_row=index,
            )
        )
    return fills, issues


def _normalize_orders(rows: Iterable[Mapping[str, str]], path: str) -> tuple[list[BrokerOrder], list[BrokerGatewayIssue]]:
    orders: list[BrokerOrder] = []
    issues: list[BrokerGatewayIssue] = []
    for index, row in enumerate(rows, start=1):
        code = _get(row, CODE_ALIASES)
        order_id = _get(row, ORDER_ID_ALIASES)
        if not code or not order_id:
            issues.append(BrokerGatewayIssue(WARN, "weak_order_row", "Order row missing code or order_id", kind="order", path=path, row=index))
            continue
        orders.append(
            BrokerOrder(
                code=code,
                order_id=order_id,
                time=_get(row, TIME_ALIASES),
                side=_normalize_side(_get(row, SIDE_ALIASES)),
                price=_float_or_none(_get(row, PRICE_ALIASES)),
                quantity=_float_or_none(_get(row, QUANTITY_ALIASES)),
                traded=_float_or_none(_get(row, ("traded", "filled", "成交数量", "已成交", "filled_volume"))),
                status=_get(row, STATUS_ALIASES),
                source_row=index,
            )
        )
    return orders, issues


def _normalize_positions(rows: Iterable[Mapping[str, str]], path: str) -> tuple[list[BrokerPosition], list[BrokerGatewayIssue]]:
    positions: list[BrokerPosition] = []
    issues: list[BrokerGatewayIssue] = []
    for index, row in enumerate(rows, start=1):
        code = _get(row, CODE_ALIASES)
        quantity = _float_or_none(_get(row, ("quantity", "volume", "position", "持仓", "持仓数量", "证券数量", "当前持仓")))
        if not code or quantity is None:
            issues.append(BrokerGatewayIssue(WARN, "weak_position_row", "Position row missing code or quantity", kind="position", path=path, row=index))
            continue
        positions.append(
            BrokerPosition(
                code=code,
                quantity=quantity,
                available=_float_or_none(_get(row, ("available", "可用", "可卖数量", "可用数量"))),
                cost_price=_float_or_none(_get(row, ("cost_price", "成本价", "持仓成本", "平均成本"))),
                pnl=_float_or_none(_get(row, ("pnl", "profit", "浮动盈亏", "盈亏"))),
                source_row=index,
            )
        )
    return positions, issues


def _normalize_accounts(rows: Iterable[Mapping[str, str]], path: str) -> list[BrokerAccount]:
    accounts: list[BrokerAccount] = []
    for index, row in enumerate(rows, start=1):
        account_id = _get(row, ACCOUNT_ALIASES)
        broker = _get(row, BROKER_ALIASES)
        if not account_id and not broker:
            continue
        accounts.append(
            BrokerAccount(
                account_id=account_id,
                broker=broker,
                balance=_float_or_none(_get(row, ("balance", "asset", "equity", "资金余额", "总资产", "账户权益"))),
                available=_float_or_none(_get(row, ("available", "cash", "可用", "可用资金"))),
                frozen=_float_or_none(_get(row, ("frozen", "冻结", "冻结资金"))),
                currency=_get(row, ("currency", "币种")),
                source_row=index,
            )
        )
    return accounts


def _normalize_broker_provenance(rows: Iterable[Mapping[str, str]], path: str) -> tuple[set[str], set[str], list[BrokerAccount]]:
    names: set[str] = set()
    ids: set[str] = set()
    accounts: list[BrokerAccount] = []
    for row in rows:
        broker = _get(row, BROKER_ALIASES)
        account_id = _get(row, ACCOUNT_ALIASES)
        if broker:
            names.add(broker)
        if account_id:
            ids.add(account_id)
    accounts.extend(_normalize_accounts(rows, path))
    return names, ids, accounts


def _artifact_with_count(artifact: BrokerGatewayArtifact, count: int) -> BrokerGatewayArtifact:
    return BrokerGatewayArtifact(
        kind=artifact.kind,
        path=artifact.path,
        exists=artifact.exists,
        bytes=artifact.bytes,
        sha256=artifact.sha256,
        format=artifact.format,
        rows_sampled=artifact.rows_sampled,
        columns=artifact.columns,
        records_normalized=count,
    )


def _resolve(project: Path, raw_path: str | Path) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = project / path
    return path.resolve(strict=False)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _get(row: Mapping[str, Any], aliases: Iterable[str]) -> str:
    by_norm = {_norm(key): key for key in row.keys()}
    for alias in aliases:
        key = by_norm.get(_norm(alias))
        if key is None:
            continue
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _float_or_none(value: str) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace(",", "").replace("%", "")
    try:
        return float(text)
    except ValueError:
        return None


def _normalize_side(value: str) -> str:
    lowered = str(value or "").strip().lower()
    if lowered in {"buy", "long", "b", "买", "买入", "多"}:
        return "buy"
    if lowered in {"sell", "short", "s", "卖", "卖出", "空"}:
        return "sell"
    return str(value or "").strip()


def _norm(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "").replace("-", "").replace(" ", "")


CODE_ALIASES = ("code", "symbol", "vt_symbol", "local_symbol", "证券代码", "股票代码", "合约代码", "代码")
TIME_ALIASES = ("time", "timestamp", "datetime", "date_time", "trade_time", "fill_time", "成交时间", "委托时间", "日期", "时间")
PRICE_ALIASES = ("price", "fill_price", "traded_price", "成交价", "成交价格", "价格", "委托价格")
QUANTITY_ALIASES = ("qty", "quantity", "volume", "fill_volume", "traded", "成交数量", "成交量", "数量")
SIDE_ALIASES = ("side", "direction", "action", "offset", "买卖", "买卖方向", "方向")
ORDER_ID_ALIASES = ("order_id", "orderid", "vt_orderid", "local_orderid", "委托编号", "合同编号", "订单号")
TRADE_ID_ALIASES = ("trade_id", "tradeid", "vt_tradeid", "成交编号", "成交号")
STATUS_ALIASES = ("status", "order_status", "state", "状态", "委托状态")
BROKER_ALIASES = ("broker", "broker_name", "gateway", "gateway_name", "券商", "通道", "柜台")
ACCOUNT_ALIASES = ("account", "account_id", "accountid", "资金账号", "账户", "账户号")
