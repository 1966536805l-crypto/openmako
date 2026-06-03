from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterable, Mapping

from .broker_gateway import BrokerFill, BrokerGatewaySnapshot, BrokerOrder, BrokerPosition


PASS = "pass"
WARN = "warn"
BLOCK = "block"


@dataclass(frozen=True)
class ExecutionReplayIssue:
    level: str
    code: str
    message: str
    evidence_type: str = ""
    row: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TickTrade:
    code: str
    time: str
    price: float
    volume: float
    source_row: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SlippageEvidence:
    code: str
    slippage_bps: float
    source_row: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapacityEvidence:
    code: str
    capacity: float
    source_row: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FillReplayCheck:
    fill_row: int
    code: str
    fill_time: str
    fill_price: float
    fill_quantity: float
    matched_tick_row: int = 0
    matched_tick_time: str = ""
    matched_tick_price: float = 0.0
    time_delta_seconds: float = 0.0
    price_delta_bps: float = 0.0
    allowed_slippage_bps: float = 0.0
    capacity: float = 0.0
    ok: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OrderLifecycleCheck:
    order_id: str
    code: str
    status: str
    requested_quantity: float = 0.0
    traded_quantity: float = 0.0
    fill_quantity: float = 0.0
    terminal: bool = False
    consistent: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BrokerReconciliationCheck:
    code: str
    fill_buy_quantity: float = 0.0
    fill_sell_quantity: float = 0.0
    net_fill_quantity: float = 0.0
    position_quantity: float = 0.0
    consistent: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuantExecutionReplayResult:
    action: str
    ok: bool
    tick_rows: int = 0
    fills_checked: int = 0
    fills_explained: int = 0
    order_lifecycle_ok: bool = False
    broker_reconciliation_ok: bool = False
    fill_replays: tuple[FillReplayCheck, ...] = ()
    order_lifecycle: tuple[OrderLifecycleCheck, ...] = ()
    broker_reconciliation: tuple[BrokerReconciliationCheck, ...] = ()
    issues: tuple[ExecutionReplayIssue, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "ok": self.ok,
            "tick_rows": self.tick_rows,
            "fills_checked": self.fills_checked,
            "fills_explained": self.fills_explained,
            "order_lifecycle_ok": self.order_lifecycle_ok,
            "broker_reconciliation_ok": self.broker_reconciliation_ok,
            "fill_replays": [item.to_dict() for item in self.fill_replays],
            "order_lifecycle": [item.to_dict() for item in self.order_lifecycle],
            "broker_reconciliation": [item.to_dict() for item in self.broker_reconciliation],
            "issues": [item.to_dict() for item in self.issues],
            "metadata": self.metadata,
        }


def run_quant_execution_replay(
    project: str | Path,
    *,
    tick_path: str = "",
    slippage_path: str = "",
    capacity_path: str = "",
    broker_snapshot: BrokerGatewaySnapshot,
    window_seconds: int = 60,
    default_slippage_bps: float = 10.0,
) -> QuantExecutionReplayResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    issues: list[ExecutionReplayIssue] = []
    ticks, tick_issues = _load_ticks(project_path, tick_path)
    slippage, slippage_issues = _load_slippage(project_path, slippage_path)
    capacity, capacity_issues = _load_capacity(project_path, capacity_path)
    issues.extend(tick_issues)
    issues.extend(slippage_issues)
    issues.extend(capacity_issues)

    fill_replays, fill_issues = _replay_fills(
        broker_snapshot.fills,
        ticks,
        slippage,
        capacity,
        window_seconds=window_seconds,
        default_slippage_bps=default_slippage_bps,
    )
    issues.extend(fill_issues)
    order_checks, order_issues = _check_order_lifecycle(broker_snapshot.orders, broker_snapshot.fills)
    issues.extend(order_issues)
    broker_checks, broker_issues = _check_broker_reconciliation(broker_snapshot.positions, broker_snapshot.fills)
    issues.extend(broker_issues)

    hard_blocks = any(issue.level == BLOCK for issue in issues)
    fills_checked = len(fill_replays)
    fills_explained = sum(1 for item in fill_replays if item.ok)
    order_lifecycle_ok = bool(order_checks) and all(item.consistent for item in order_checks)
    broker_reconciliation_ok = bool(broker_checks) and all(item.consistent for item in broker_checks)
    ok = bool(not hard_blocks and (fills_checked == 0 or fills_checked == fills_explained))
    return QuantExecutionReplayResult(
        action=PASS if ok else BLOCK,
        ok=ok,
        tick_rows=len(ticks),
        fills_checked=fills_checked,
        fills_explained=fills_explained,
        order_lifecycle_ok=order_lifecycle_ok,
        broker_reconciliation_ok=broker_reconciliation_ok,
        fill_replays=tuple(fill_replays),
        order_lifecycle=tuple(order_checks),
        broker_reconciliation=tuple(broker_checks),
        issues=tuple(issues),
        metadata={
            "window_seconds": window_seconds,
            "default_slippage_bps": default_slippage_bps,
            "slippage_codes": sorted(slippage),
            "capacity_codes": sorted(capacity),
        },
    )


def _replay_fills(
    fills: Iterable[BrokerFill],
    ticks: list[TickTrade],
    slippage: dict[str, SlippageEvidence],
    capacity: dict[str, CapacityEvidence],
    *,
    window_seconds: int,
    default_slippage_bps: float,
) -> tuple[list[FillReplayCheck], list[ExecutionReplayIssue]]:
    checks: list[FillReplayCheck] = []
    issues: list[ExecutionReplayIssue] = []
    ticks_by_code: dict[str, list[TickTrade]] = {}
    weak_ticks = [tick for tick in ticks if not tick.code]
    for tick in ticks:
        if tick.code:
            ticks_by_code.setdefault(_normalize_code(tick.code), []).append(tick)
    for code_ticks in ticks_by_code.values():
        code_ticks.sort(key=lambda item: _seconds_of_day(item.time))

    for fill in fills:
        code = _normalize_code(fill.code)
        candidates = ticks_by_code.get(code, ())
        if not candidates:
            if weak_ticks:
                issues.append(
                    ExecutionReplayIssue(
                        WARN,
                        "weak_tick_replay_no_code",
                        "Tick evidence has no code column; fill replay downgraded to schema/provenance evidence",
                        evidence_type="tick",
                        row=fill.source_row,
                    )
                )
            else:
                issues.append(ExecutionReplayIssue(BLOCK, "fill_has_no_tick_match", f"No tick evidence for fill code {fill.code}", evidence_type="tick", row=fill.source_row))
            continue
        fill_seconds = _seconds_of_day(fill.time)
        matched = min(candidates, key=lambda tick: abs(_seconds_of_day(tick.time) - fill_seconds))
        delta_seconds = abs(_seconds_of_day(matched.time) - fill_seconds)
        base_price = matched.price or fill.price
        price_delta_bps = abs(fill.price - matched.price) / base_price * 10000 if base_price else 0.0
        allowed = slippage.get(code).slippage_bps if code in slippage else default_slippage_bps
        cap = capacity.get(code).capacity if code in capacity else 0.0
        ok = delta_seconds <= window_seconds and price_delta_bps <= allowed and (cap <= 0 or fill.notional <= cap)
        checks.append(
            FillReplayCheck(
                fill_row=fill.source_row,
                code=fill.code,
                fill_time=fill.time,
                fill_price=fill.price,
                fill_quantity=fill.quantity,
                matched_tick_row=matched.source_row,
                matched_tick_time=matched.time,
                matched_tick_price=matched.price,
                time_delta_seconds=delta_seconds,
                price_delta_bps=price_delta_bps,
                allowed_slippage_bps=allowed,
                capacity=cap,
                ok=ok,
            )
        )
        if delta_seconds > window_seconds:
            issues.append(ExecutionReplayIssue(BLOCK, "fill_outside_tick_window", f"Fill is {delta_seconds:.0f}s away from nearest tick", evidence_type="tick", row=fill.source_row))
        if price_delta_bps > allowed:
            issues.append(ExecutionReplayIssue(BLOCK, "fill_price_exceeds_slippage", f"Fill price delta {price_delta_bps:.2f}bps exceeds allowed {allowed:.2f}bps", evidence_type="slippage", row=fill.source_row))
        if cap > 0 and fill.notional > cap:
            issues.append(ExecutionReplayIssue(BLOCK, "fill_notional_exceeds_capacity", f"Fill notional {fill.notional:.2f} exceeds capacity {cap:.2f}", evidence_type="capacity", row=fill.source_row))
    return checks, issues


def _check_order_lifecycle(orders: Iterable[BrokerOrder], fills: Iterable[BrokerFill]) -> tuple[list[OrderLifecycleCheck], list[ExecutionReplayIssue]]:
    order_list = list(orders)
    fill_list = list(fills)
    issues: list[ExecutionReplayIssue] = []
    if not order_list:
        if any(fill.order_id for fill in fill_list):
            issues.append(ExecutionReplayIssue(WARN, "missing_order_lifecycle_file", "Fills include order IDs but no order lifecycle evidence was supplied", evidence_type="order"))
        return [], issues
    fills_by_order: dict[str, float] = {}
    for fill in fill_list:
        if fill.order_id:
            fills_by_order[fill.order_id] = fills_by_order.get(fill.order_id, 0.0) + fill.quantity
    checks: list[OrderLifecycleCheck] = []
    for order in order_list:
        traded = order.traded if order.traded is not None else fills_by_order.get(order.order_id, 0.0)
        requested = order.quantity or 0.0
        fill_qty = fills_by_order.get(order.order_id, 0.0)
        status = _normalize_status(order.status, traded=traded, requested=requested)
        terminal = status in {"filled", "cancelled", "rejected"}
        consistent = terminal and (requested <= 0 or traded <= requested + 1e-9) and (not fill_qty or abs(fill_qty - traded) <= max(1e-9, requested * 1e-6))
        checks.append(
            OrderLifecycleCheck(
                order_id=order.order_id,
                code=order.code,
                status=status,
                requested_quantity=requested,
                traded_quantity=traded,
                fill_quantity=fill_qty,
                terminal=terminal,
                consistent=consistent,
            )
        )
        if not terminal:
            issues.append(ExecutionReplayIssue(BLOCK, "order_not_terminal", f"Order {order.order_id} is not terminal: {order.status or '-'}", evidence_type="order", row=order.source_row))
        if requested > 0 and traded > requested + 1e-9:
            issues.append(ExecutionReplayIssue(BLOCK, "order_overfilled", f"Order {order.order_id} traded more than requested", evidence_type="order", row=order.source_row))
        if fill_qty and abs(fill_qty - traded) > max(1e-9, requested * 1e-6):
            issues.append(ExecutionReplayIssue(BLOCK, "order_fill_quantity_mismatch", f"Order {order.order_id} traded quantity does not match fills", evidence_type="fill", row=order.source_row))
    return checks, issues


def _check_broker_reconciliation(positions: Iterable[BrokerPosition], fills: Iterable[BrokerFill]) -> tuple[list[BrokerReconciliationCheck], list[ExecutionReplayIssue]]:
    position_list = list(positions)
    fill_list = list(fills)
    if not position_list:
        return [], [ExecutionReplayIssue(WARN, "missing_position_reconciliation", "No position file supplied; broker position reconciliation skipped", evidence_type="position")]
    by_code: dict[str, dict[str, float]] = {}
    for fill in fill_list:
        code = _normalize_code(fill.code)
        item = by_code.setdefault(code, {"buy": 0.0, "sell": 0.0})
        if fill.side == "sell":
            item["sell"] += fill.quantity
        else:
            item["buy"] += fill.quantity
    checks: list[BrokerReconciliationCheck] = []
    issues: list[ExecutionReplayIssue] = []
    for position in position_list:
        code = _normalize_code(position.code)
        flow = by_code.get(code, {"buy": 0.0, "sell": 0.0})
        net = flow["buy"] - flow["sell"]
        consistent = position.quantity >= max(0.0, net) - 1e-9
        checks.append(
            BrokerReconciliationCheck(
                code=position.code,
                fill_buy_quantity=flow["buy"],
                fill_sell_quantity=flow["sell"],
                net_fill_quantity=net,
                position_quantity=position.quantity,
                consistent=consistent,
            )
        )
        if not consistent:
            issues.append(ExecutionReplayIssue(BLOCK, "position_less_than_net_fills", f"Position {position.quantity:.4f} is less than net fills {net:.4f}", evidence_type="position", row=position.source_row))
    return checks, issues


def _load_ticks(project: Path, raw_path: str) -> tuple[list[TickTrade], list[ExecutionReplayIssue]]:
    rows, issues = _load_csv_rows(project, raw_path, "tick")
    ticks: list[TickTrade] = []
    for index, row in enumerate(rows, start=1):
        price = _float_or_none(_get(row, PRICE_ALIASES))
        volume = _float_or_none(_get(row, VOLUME_ALIASES))
        time_value = _get(row, TIME_ALIASES)
        if not time_value or price is None or price <= 0 or volume is None or volume <= 0:
            issues.append(ExecutionReplayIssue(BLOCK, "invalid_tick_row", "Tick row missing time/price/volume", evidence_type="tick", row=index))
            continue
        ticks.append(TickTrade(_get(row, CODE_ALIASES), time_value, price, volume, index))
    return ticks, issues


def _load_slippage(project: Path, raw_path: str) -> tuple[dict[str, SlippageEvidence], list[ExecutionReplayIssue]]:
    rows, issues = _load_csv_rows(project, raw_path, "slippage")
    result: dict[str, SlippageEvidence] = {}
    for index, row in enumerate(rows, start=1):
        code = _normalize_code(_get(row, CODE_ALIASES))
        value = _float_or_none(_get(row, SLIPPAGE_ALIASES))
        if not code or value is None or value < 0:
            issues.append(ExecutionReplayIssue(BLOCK, "invalid_slippage_row", "Slippage row missing code/slippage_bps", evidence_type="slippage", row=index))
            continue
        result[code] = SlippageEvidence(code, value, index)
    return result, issues


def _load_capacity(project: Path, raw_path: str) -> tuple[dict[str, CapacityEvidence], list[ExecutionReplayIssue]]:
    rows, issues = _load_csv_rows(project, raw_path, "capacity")
    result: dict[str, CapacityEvidence] = {}
    for index, row in enumerate(rows, start=1):
        code = _normalize_code(_get(row, CODE_ALIASES))
        value = _float_or_none(_get(row, CAPACITY_ALIASES))
        if not code or value is None or value < 0:
            issues.append(ExecutionReplayIssue(BLOCK, "invalid_capacity_row", "Capacity row missing code/capacity", evidence_type="capacity", row=index))
            continue
        result[code] = CapacityEvidence(code, value, index)
    return result, issues


def _load_csv_rows(project: Path, raw_path: str, evidence_type: str) -> tuple[list[dict[str, str]], list[ExecutionReplayIssue]]:
    if not raw_path:
        return [], []
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = project / path
    path = path.resolve(strict=False)
    if not path.exists() or path.is_dir() or path.suffix.lower() != ".csv":
        return [], []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)], []
    except UnicodeDecodeError:
        with path.open("r", encoding="gb18030", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)], []
    except OSError as exc:
        return [], [ExecutionReplayIssue(BLOCK, "read_failed", str(exc), evidence_type=evidence_type)]


def _seconds_of_day(value: str) -> float:
    parsed = _parse_datetime(value)
    if parsed is None:
        return 0.0
    return parsed.hour * 3600 + parsed.minute * 60 + parsed.second + parsed.microsecond / 1_000_000


def _parse_datetime(value: str) -> time | None:
    text = str(value or "").strip().replace("/", "-")
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d %H:%M:%S", "%H:%M:%S", "%H%M%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text[:19], fmt)
            return parsed.time()
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text[:19])
        return parsed.time()
    except ValueError:
        return None


def _normalize_status(value: str, *, traded: float, requested: float) -> str:
    lowered = str(value or "").strip().lower()
    if lowered in {"filled", "alltraded", "全部成交", "已成", "成交"}:
        return "filled"
    if lowered in {"partial", "parttraded", "partial_filled", "部分成交"}:
        return "partial"
    if lowered in {"cancelled", "canceled", "撤单", "已撤"}:
        return "cancelled"
    if lowered in {"rejected", "拒单", "废单"}:
        return "rejected"
    if requested > 0 and traded >= requested:
        return "filled"
    if traded > 0:
        return "partial"
    return lowered or "unknown"


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
    text = str(value or "").strip().replace(",", "").replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalize_code(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[-6:] if len(digits) >= 6 else digits


def _norm(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "").replace("-", "").replace(" ", "")


CODE_ALIASES = ("code", "symbol", "vt_symbol", "local_symbol", "证券代码", "股票代码", "合约代码", "代码")
TIME_ALIASES = ("time", "timestamp", "datetime", "date_time", "trade_time", "fill_time", "成交时间", "委托时间", "日期", "时间")
PRICE_ALIASES = ("price", "fill_price", "traded_price", "成交价", "成交价格", "价格", "委托价格")
VOLUME_ALIASES = ("volume", "qty", "quantity", "成交量", "成交量(股)", "成交量（股）", "成交数量", "数量")
SLIPPAGE_ALIASES = ("slippage", "slippage_bps", "滑点", "滑点bps")
CAPACITY_ALIASES = ("capacity", "max_notional", "成交额", "容量", "最大成交额")
