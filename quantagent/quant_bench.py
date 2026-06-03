from __future__ import annotations

import json
import shutil
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .evidence_ledger import record_evidence
from .experiment_runner import ExperimentSpec, run_experiment
from .quant_data_contract import validate_quant_data_contract
from .quant_leak_check import run_quant_leak_check
from .quant_priority import build_quant_priority_review


PASS = "pass"
FAIL = "fail"
ERROR = "error"


@dataclass(frozen=True)
class QuantBenchCase:
    id: str
    name: str
    category: str
    weight: int = 1
    expected: str = "pass"
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuantBenchResult:
    case_id: str
    name: str
    category: str
    classification: str
    score: int
    max_score: int
    message: str = ""
    duration_ms: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuantBenchRun:
    run_id: str
    project: str
    started_at: str
    finished_at: str
    results: tuple[QuantBenchResult, ...]
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "project": self.project,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "summary": score_quant_bench(self),
            "results": [result.to_dict() for result in self.results],
        }


def quant_bench_cases() -> tuple[QuantBenchCase, ...]:
    return (
        QuantBenchCase("contract_valid_trade_csv", "valid trade CSV passes data contract", "data_contract", 2),
        QuantBenchCase("contract_bad_schema", "bad schema blocks experiment input", "data_contract", 2),
        QuantBenchCase("contract_strict_dedup", "strict dedup mode blocks unmarked file", "data_contract", 2),
        QuantBenchCase("leak_negative_shift", "negative shift is a hard lookahead error", "leak_check", 3),
        QuantBenchCase("leak_forward_merge", "forward merge_asof is a hard lookahead error", "leak_check", 3),
        QuantBenchCase("leak_future_column", "future/target CSV column is flagged", "leak_check", 2),
        QuantBenchCase("leak_survivorship_bias", "survivorship bias from missing delisted stocks", "leak_check", 3),
        QuantBenchCase("split_blocks_single_year", "single year without explicit OOS is blocked", "split_check", 3),
        QuantBenchCase("split_duplicate_timestamps", "duplicate timestamps in same code/date", "data_quality", 2),
        QuantBenchCase("capacity_missing_evidence", "capacity claim without evidence file", "execution_gate", 3),
        QuantBenchCase("slippage_missing_evidence", "slippage claim without evidence file", "execution_gate", 3),
        QuantBenchCase("execution_time_outside_hours", "tick/fill data outside 09:30-15:00 triggers warning", "execution_gate", 2),
        QuantBenchCase("priority_blocks_live_pf", "live PF conclusion is blocked without evidence", "evidence_gate", 3),
        QuantBenchCase("priority_allows_evidence_backed", "evidence-backed PF/execution conclusion passes gate", "evidence_gate", 3),
        QuantBenchCase("experiment_records_artifacts", "experiment writes run artifacts and evidence ledger", "run_registry", 4),
        QuantBenchCase("experiment_blocks_bad_contract", "experiment refuses bad contract before registry write", "run_registry", 3),
        QuantBenchCase("judge_rejects_self_reported_metrics", "judge blocks self-reported metrics without runner_sha256", "metrics_trust", 4),
    )


def run_quant_bench(project: str | Path, *, keep_workspace: bool = False) -> QuantBenchRun:
    project_path = Path(project).expanduser().resolve(strict=False)
    started = datetime.now().isoformat(timespec="seconds")
    started_monotonic = time.monotonic()
    run_id = "qbench-" + uuid.uuid4().hex[:12]
    results: list[QuantBenchResult] = []
    with tempfile.TemporaryDirectory(prefix="mako quant bench ") as tmp:
        bench_root = Path(tmp)
        runners = _case_runners()
        for case in quant_bench_cases():
            case_started = time.monotonic()
            workspace = bench_root / case.id
            workspace.mkdir(parents=True, exist_ok=True)
            try:
                ok, message, details = runners[case.id](workspace)
                classification = PASS if ok else FAIL
            except Exception as exc:
                ok = False
                classification = ERROR
                message = f"{type(exc).__name__}: {exc}"
                details = {}
            results.append(
                QuantBenchResult(
                    case.id,
                    case.name,
                    case.category,
                    classification,
                    case.weight if ok else 0,
                    case.weight,
                    message=message,
                    duration_ms=_elapsed_ms(case_started),
                    details=details,
                )
            )
        if keep_workspace:
            out_dir = quant_bench_dir(project_path) / run_id
            if out_dir.exists():
                shutil.rmtree(out_dir)
            out_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(bench_root, out_dir)
    finished = datetime.now().isoformat(timespec="seconds")
    run = QuantBenchRun(run_id, str(project_path), started, finished, tuple(results), duration_ms=_elapsed_ms(started_monotonic))
    _write_quant_bench_run(project_path, run)
    return run


def score_quant_bench(run: QuantBenchRun) -> dict[str, Any]:
    max_score = sum(result.max_score for result in run.results)
    score = sum(result.score for result in run.results)
    passed = sum(1 for result in run.results if result.classification == PASS)
    failed = sum(1 for result in run.results if result.classification == FAIL)
    errors = sum(1 for result in run.results if result.classification == ERROR)
    by_category: dict[str, dict[str, int]] = {}
    for result in run.results:
        bucket = by_category.setdefault(result.category, {"score": 0, "max_score": 0, "passed": 0, "total": 0})
        bucket["score"] += result.score
        bucket["max_score"] += result.max_score
        bucket["passed"] += 1 if result.classification == PASS else 0
        bucket["total"] += 1
    for bucket in by_category.values():
        bucket["percent"] = round(bucket["score"] / bucket["max_score"] * 100) if bucket["max_score"] else 0
    return {
        "score": score,
        "max_score": max_score,
        "percent": round(score / max_score * 100) if max_score else 0,
        "total": len(run.results),
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "by_category": by_category,
    }


def render_quant_bench(run: QuantBenchRun) -> str:
    summary = score_quant_bench(run)
    lines = [
        "# QuantBench",
        "",
        f"- project: {run.project}",
        f"- run_id: {run.run_id}",
        f"- score: {summary['score']}/{summary['max_score']} ({summary['percent']}/100)",
        f"- cases: {summary['total']} total, {summary['passed']} passed, {summary['failed']} failed, {summary['errors']} errors",
        f"- duration_ms: {run.duration_ms}",
        "",
        "## Category Scores",
        "",
    ]
    for category, bucket in sorted(summary["by_category"].items()):
        lines.append(f"- {category}: {bucket['score']}/{bucket['max_score']} ({bucket['percent']}/100), {bucket['passed']}/{bucket['total']} passed")
    lines.extend(["", "## Results", ""])
    for result in run.results:
        lines.append(
            f"- [{result.classification}] {result.case_id} (+{result.score}/{result.max_score}, {result.duration_ms}ms): {result.message}"
        )
    return "\n".join(lines).rstrip() + "\n"


def render_quant_bench_json(run: QuantBenchRun) -> str:
    return json.dumps(run.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def quant_bench_dir(project: str | Path) -> Path:
    project_path = Path(project).expanduser().resolve(strict=False)
    base = project_path / "AI_协作交接"
    if not base.exists():
        base = project_path / ".quantagent"
    return base / "quant_bench"


def latest_quant_bench(project: str | Path) -> QuantBenchRun | None:
    root = quant_bench_dir(project)
    files = sorted(root.glob("qbench-*.json"))
    if not files:
        return None
    return _run_from_dict(json.loads(files[-1].read_text(encoding="utf-8")))


def _write_quant_bench_run(project: Path, run: QuantBenchRun) -> Path:
    root = quant_bench_dir(project)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{run.run_id}.json"
    path.write_text(render_quant_bench_json(run), encoding="utf-8")
    (root / f"{run.run_id}.md").write_text(render_quant_bench(run), encoding="utf-8")
    return path


def _case_runners() -> dict[str, Callable[[Path], tuple[bool, str, dict[str, Any]]]]:
    return {
        "contract_valid_trade_csv": _case_contract_valid_trade_csv,
        "contract_bad_schema": _case_contract_bad_schema,
        "contract_strict_dedup": _case_contract_strict_dedup,
        "leak_negative_shift": _case_leak_negative_shift,
        "leak_forward_merge": _case_leak_forward_merge,
        "leak_future_column": _case_leak_future_column,
        "leak_survivorship_bias": _case_leak_survivorship_bias,
        "split_blocks_single_year": _case_split_blocks_single_year,
        "split_duplicate_timestamps": _case_split_duplicate_timestamps,
        "capacity_missing_evidence": _case_capacity_missing_evidence,
        "slippage_missing_evidence": _case_slippage_missing_evidence,
        "execution_time_outside_hours": _case_execution_time_outside_hours,
        "priority_blocks_live_pf": _case_priority_blocks_live_pf,
        "priority_allows_evidence_backed": _case_priority_allows_evidence_backed,
        "experiment_records_artifacts": _case_experiment_records_artifacts,
        "experiment_blocks_bad_contract": _case_experiment_blocks_bad_contract,
        "judge_rejects_self_reported_metrics": _case_judge_rejects_self_reported_metrics,
    }


def _case_contract_valid_trade_csv(workspace: Path) -> tuple[bool, str, dict[str, Any]]:
    path = workspace / "valid_position_dedup.csv"
    _write_trade_csv(path)
    result = validate_quant_data_contract(path, strict_dedup=True)
    return result.ok, "valid dedup trade CSV accepted" if result.ok else "valid CSV rejected", result.to_dict()


def _case_contract_bad_schema(workspace: Path) -> tuple[bool, str, dict[str, Any]]:
    path = workspace / "bad_dedup.csv"
    path.write_text("entry_date,wrong_return\nnot-a-date,abc\n", encoding="utf-8")
    result = validate_quant_data_contract(path, kind="trade_csv")
    ok = not result.ok and _has_issue(result.to_dict(), "missing_required_column") and _has_issue(result.to_dict(), "invalid_date")
    return ok, "bad schema blocked" if ok else "bad schema was not blocked correctly", result.to_dict()


def _case_contract_strict_dedup(workspace: Path) -> tuple[bool, str, dict[str, Any]]:
    path = workspace / "sample.csv"
    _write_trade_csv(path)
    result = validate_quant_data_contract(path, strict_dedup=True)
    ok = not result.ok and _has_issue(result.to_dict(), "not_dedup_marked")
    return ok, "strict dedup file-name gate blocked unmarked file" if ok else "strict dedup gate did not block", result.to_dict()


def _case_leak_negative_shift(workspace: Path) -> tuple[bool, str, dict[str, Any]]:
    path = workspace / "strategy.py"
    path.write_text("df['feature'] = df['close'].shift(-1)\n", encoding="utf-8")
    result = run_quant_leak_check(path)
    ok = not result.ok and _has_finding(result.to_dict(), "negative_shift")
    return ok, "negative shift blocked" if ok else "negative shift missed", result.to_dict()


def _case_leak_forward_merge(workspace: Path) -> tuple[bool, str, dict[str, Any]]:
    path = workspace / "strategy.py"
    path.write_text("df = df.merge_asof(events, on='ts', direction='forward')\n", encoding="utf-8")
    result = run_quant_leak_check(path)
    ok = not result.ok and _has_finding(result.to_dict(), "forward_merge_asof")
    return ok, "forward merge_asof blocked" if ok else "forward merge_asof missed", result.to_dict()


def _case_leak_future_column(workspace: Path) -> tuple[bool, str, dict[str, Any]]:
    path = workspace / "features.csv"
    path.write_text("entry_date,net_return,future_return\n2025-01-01,0.01,0.02\n", encoding="utf-8")
    result = run_quant_leak_check(path)
    ok = result.ok and _has_finding(result.to_dict(), "suspicious_future_or_target_column")
    return ok, "future/target column warned" if ok else "future/target column was not warned", result.to_dict()


def _case_priority_blocks_live_pf(workspace: Path) -> tuple[bool, str, dict[str, Any]]:
    review = build_quant_priority_review(workspace, "报告 PF=2.1 已确认，可以实盘下单", audit=False)
    ok = not review.ok and review.action == "block"
    return ok, "unsupported live PF conclusion blocked" if ok else "unsupported live PF conclusion passed", review.to_dict()


def _case_priority_allows_evidence_backed(workspace: Path) -> tuple[bool, str, dict[str, Any]]:
    record_evidence(workspace, claim="dedup baseline", value="sample_position_dedup.csv", source="bench")
    record_evidence(workspace, claim="artifact hashes and row count", value="sha256 abc rows 2", source="bench")
    record_evidence(workspace, claim="yearly OOS split", value="years=2025,2026", source="bench")
    record_evidence(workspace, claim="broker fill slippage capacity", value="tick fill broker slippage capacity", source="bench")
    review = build_quant_priority_review(workspace, "报告 PF=2.1 已确认，可以实盘下单，含 09:30 成交滑点容量", audit=False)
    return review.ok, "evidence-backed quant conclusion passed" if review.ok else "evidence-backed conclusion blocked", review.to_dict()


def _case_experiment_records_artifacts(workspace: Path) -> tuple[bool, str, dict[str, Any]]:
    project = workspace
    comm = project / "AI_协作交接"
    comm.mkdir()
    path = comm / "sample_position_dedup.csv"
    _write_trade_csv(path)
    payload = run_experiment(project, ExperimentSpec(name="bench", input_path=path, threshold_col="t1_auction_return", threshold_lte=-9))
    run_dir = Path(str(payload.get("run_dir")))
    ok = (
        str(payload.get("run_id", "")).startswith("run-")
        and (run_dir / "spec.json").exists()
        and (run_dir / "result.json").exists()
        and bool(payload.get("data_contract", {}).get("ok"))
        and bool(payload.get("leak_check", {}).get("ok"))
    )
    return ok, "experiment recorded run artifacts and gates" if ok else "experiment artifact/evidence recording failed", payload


def _case_experiment_blocks_bad_contract(workspace: Path) -> tuple[bool, str, dict[str, Any]]:
    project = workspace
    path = project / "bad_position_dedup.csv"
    path.write_text("entry_date,wrong_return\nbad,abc\n", encoding="utf-8")
    try:
        run_experiment(project, ExperimentSpec(name="bad", input_path=path))
    except ValueError as exc:
        return "missing columns" in str(exc) or "data contract failed" in str(exc), "bad experiment input blocked", {"error": str(exc)}
    return False, "bad experiment input was accepted", {}


def _case_judge_rejects_self_reported_metrics(workspace: Path) -> tuple[bool, str, dict[str, Any]]:
    from .quant_judge import QuantJudgeSpec, run_quant_judge
    from .quant_run_gate import QuantGateRun, QuantRunSpec, QuantEvidenceBundle, QuantRunVerdict, QuantSplitCheck, PASS

    project = workspace
    comm = project / "AI_协作交接"
    comm.mkdir()
    path = comm / "fake_position_dedup.csv"
    _write_trade_csv(path)

    # Simulate a fake run with self-reported metrics (no runner_sha256)
    fake_experiment = {
        "run_id": "run-fake123",
        "input_sha256": "abc123",
        "spec_hash": "def456",
        "run_dir": str(comm / "fake_run"),
        "rows_before_filter": 100,
        "rows_after_filter": 100,
        "metrics": {
            "profit_factor": 999.9,  # Obviously fake
            "win_rate": 1.0,
            "avg_return": 0.5,
            "trades": 100,
        },
        "yearly": {"2025": {"profit_factor": 999.9, "trades": 100}},
        # CRITICAL: Missing runner_sha256 = self-reported
    }

    # Create a fake gate run with self-reported metrics
    fake_run = QuantGateRun(
        gate_id="qgate-fake",
        project=str(project),
        started_at="2026-01-01T00:00:00",
        finished_at="2026-01-01T00:00:01",
        spec=QuantRunSpec(name="fake", input_path=str(path)),
        split_check=QuantSplitCheck(ok=True, date_col="entry_date", rows=2, years=("2025", "2026"), year_counts={"2025": 1, "2026": 1}),
        data_contract={"ok": True},
        leak_check={"ok": True},
        experiment=fake_experiment,
        evidence_bundle=QuantEvidenceBundle(
            gate_id="qgate-fake",
            run_id="run-fake123",
            input_sha256="abc123",
            spec_hash="def456",
            data_contract_ok=True,
            leak_check_ok=True,
            split_ok=True,
            split_years=("2025", "2026"),
        ),
        verdict=QuantRunVerdict(PASS, True, True, False),
    )

    # Manually construct judge result to test metrics filtering
    from .quant_judge import _result_from_run, QuantJudgeSpec

    result = _result_from_run(
        project,
        "judge-test",
        QuantJudgeSpec(scenario="A", input_path=str(path)),
        path,
        fake_run,
        str(comm / "judge-test.json"),
        str(comm / "judge-test.md"),
    )

    # Judge should reject self-reported metrics (empty metrics dict)
    ok = not result.metrics or result.metrics.get("profit_factor") is None
    return ok, "self-reported metrics blocked" if ok else "self-reported metrics accepted", result.to_dict()


def _case_leak_survivorship_bias(workspace: Path) -> tuple[bool, str, dict[str, Any]]:
    # Test both code-based and data-based survivorship bias detection

    # Part 1: Code-based detection (existing)
    py_path = workspace / "strategy.py"
    py_path.write_text("# Only using stocks that survived to present day\ndf = df[df['code'].isin(current_universe)]\n", encoding="utf-8")
    code_result = run_quant_leak_check(py_path)
    code_ok = code_result.ok and _has_finding(code_result.to_dict(), "survivorship_bias")

    # Part 2: Data-based detection (new)
    from .quant_leak_check import check_survivorship_bias_data

    # Create strategy CSV with 120 stocks, none delisted
    strategy_path = workspace / "strategy_data.csv"
    strategy_lines = ["code,entry_date,net_return"]
    for i in range(120):
        strategy_lines.append(f"STOCK{i:03d},2025-01-01,0.01")
    strategy_path.write_text("\n".join(strategy_lines) + "\n", encoding="utf-8")

    # Create universe with all stocks marked as active (no delisted)
    universe_path = workspace / "universe.csv"
    universe_lines = ["code,delisted"]
    for i in range(150):
        universe_lines.append(f"STOCK{i:03d},false")
    universe_path.write_text("\n".join(universe_lines) + "\n", encoding="utf-8")

    data_finding = check_survivorship_bias_data(strategy_path, universe_path)
    data_ok = data_finding is not None and data_finding.code == "survivorship_bias_no_delisted"

    # Both detections should work
    ok = code_ok and data_ok
    message = "survivorship bias detected in code and data" if ok else f"detection incomplete: code={code_ok}, data={data_ok}"

    return ok, message, {
        "code_result": code_result.to_dict(),
        "data_finding": data_finding.to_dict() if data_finding else None,
    }


def _case_split_blocks_single_year(workspace: Path) -> tuple[bool, str, dict[str, Any]]:
    from .quant_run_gate import run_quant_split_check
    path = workspace / "single_year_dedup.csv"
    path.write_text(
        "code,entry_date,exit_date,net_return\n"
        "AAA,2025-01-01,2025-01-02,0.01\n"
        "BBB,2025-06-01,2025-06-02,0.02\n",
        encoding="utf-8",
    )
    result = run_quant_split_check(path, date_col="entry_date")
    ok = not result.ok and "two years" in result.reason.lower()
    return ok, "single year blocked" if ok else "single year accepted", result.to_dict()


def _case_split_duplicate_timestamps(workspace: Path) -> tuple[bool, str, dict[str, Any]]:
    path = workspace / "duplicate_dedup.csv"
    path.write_text(
        "code,entry_date,exit_date,net_return\n"
        "AAA,2025-01-01,2025-01-02,0.01\n"
        "AAA,2025-01-01,2025-01-02,0.02\n",  # Duplicate (code, entry_date)
        encoding="utf-8",
    )
    result = validate_quant_data_contract(path, kind="trade_csv", strict_dedup=True)
    # Should detect duplicate by (code, entry_date) key
    ok = not result.ok and _has_issue(result.to_dict(), "duplicate_trades")
    return ok, "duplicate timestamps blocked" if ok else "duplicate timestamps not detected", result.to_dict()


def _case_capacity_missing_evidence(workspace: Path) -> tuple[bool, str, dict[str, Any]]:
    from .quant_execution_gate import QuantExecutionEvidenceSpec, run_quant_execution_gate
    result = run_quant_execution_gate(
        workspace,
        QuantExecutionEvidenceSpec(
            tick_path="",
            fill_path="",
            broker_path="",
            capacity_path="",  # Missing capacity evidence
            execution_source="",
        ),
        required_evidence=("capacity",),
    )
    ok = not result.live_ready and any("capacity" in issue.code or "capacity" in issue.evidence_type for issue in result.issues)
    return ok, "missing capacity evidence blocked" if ok else "missing capacity accepted", result.to_dict()


def _case_slippage_missing_evidence(workspace: Path) -> tuple[bool, str, dict[str, Any]]:
    from .quant_execution_gate import QuantExecutionEvidenceSpec, run_quant_execution_gate
    result = run_quant_execution_gate(
        workspace,
        QuantExecutionEvidenceSpec(
            tick_path="",
            fill_path="",
            broker_path="",
            slippage_path="",  # Missing slippage evidence
            execution_source="",
        ),
        required_evidence=("slippage",),
    )
    ok = not result.live_ready and any("slippage" in issue.code or "slippage" in issue.evidence_type for issue in result.issues)
    return ok, "missing slippage evidence blocked" if ok else "missing slippage accepted", result.to_dict()


def _case_execution_time_outside_hours(workspace: Path) -> tuple[bool, str, dict[str, Any]]:
    from .quant_execution_gate import inspect_execution_artifact
    # Create tick data with times outside 09:30-15:00
    path = workspace / "tick_outside_hours.csv"
    path.write_text(
        "Time,Price,Volume\n"
        "2025-01-02 09:25:00,10.5,1000\n"  # Before 09:30
        "2025-01-02 09:30:00,10.6,1500\n"  # Valid
        "2025-01-02 14:59:00,10.7,2000\n"  # Valid
        "2025-01-02 15:00:00,10.8,1200\n"  # At/after 15:00
        "2025-01-02 15:30:00,10.9,800\n",   # After 15:00
        encoding="utf-8",
    )
    artifact, issues = inspect_execution_artifact(workspace, "tick", path)
    # Should have a WARN issue about time outside trading hours
    ok = any(issue.level == "warn" and issue.code == "time_outside_trading_hours" for issue in issues)
    return ok, "time outside 09:30-15:00 warned" if ok else "time outside hours not detected", {"artifact": artifact.to_dict(), "issues": [issue.to_dict() for issue in issues]}


def _write_trade_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "code,entry_date,exit_date,entry_price,exit_price,net_return,t1_auction_return\n"
        "AAA,2025-01-01,2025-01-02,10,11,0.01,-10\n"
        "BBB,2026-01-02,2026-01-03,20,22,0.02,-11\n",
        encoding="utf-8",
    )


def _has_issue(payload: dict[str, Any], code: str) -> bool:
    return any(item.get("code") == code for item in payload.get("issues", []))


def _has_finding(payload: dict[str, Any], code: str) -> bool:
    return any(item.get("code") == code for item in payload.get("findings", []))


def _run_from_dict(payload: dict[str, Any]) -> QuantBenchRun:
    return QuantBenchRun(
        run_id=str(payload.get("run_id") or ""),
        project=str(payload.get("project") or ""),
        started_at=str(payload.get("started_at") or ""),
        finished_at=str(payload.get("finished_at") or ""),
        duration_ms=int(payload.get("duration_ms") or 0),
        results=tuple(
            QuantBenchResult(
                case_id=str(item.get("case_id") or ""),
                name=str(item.get("name") or ""),
                category=str(item.get("category") or ""),
                classification=str(item.get("classification") or ""),
                score=int(item.get("score") or 0),
                max_score=int(item.get("max_score") or 0),
                message=str(item.get("message") or ""),
                duration_ms=int(item.get("duration_ms") or 0),
                details=dict(item.get("details") or {}),
            )
            for item in payload.get("results", [])
            if isinstance(item, dict)
        ),
    )


def _elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)
