from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .evidence_ledger import record_evidence
from .metrics import compute_metrics, date_month, date_year, group_metrics, to_float
from .quant_data_contract import validate_quant_data_contract
from .quant_leak_check import run_quant_leak_check
from .result_registry import register_result
from .run_artifacts import create_run_spec, write_run_result


@dataclass
class ExperimentSpec:
    name: str
    input_path: Path
    return_col: str = "net_return"
    date_col: str = "entry_date"
    threshold_col: str | None = None
    threshold_lte: float | None = None


def resolve_default_input(project: Path, scenario: str) -> Path:
    comm = project / "AI_协作交接"
    scenario_key = scenario.upper()
    if scenario_key == "A":
        return comm / "agent2_scenario_A_0p2_0p2_position_dedup.csv"
    if scenario_key == "D":
        return comm / "agent2_scenario_D_0p3_0p3_position_dedup.csv"
    raise ValueError(f"unknown scenario: {scenario}")


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_fieldnames(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [name for name in (reader.fieldnames or []) if name is not None]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def apply_filters(rows: list[dict[str, str]], spec: ExperimentSpec) -> list[dict[str, str]]:
    filtered = rows
    if spec.threshold_col and spec.threshold_lte is not None:
        filtered = [
            row
            for row in filtered
            if (value := to_float(row.get(spec.threshold_col))) is not None
            and value <= spec.threshold_lte
        ]
    return filtered


def metrics_to_dict(value) -> dict[str, Any]:
    data = asdict(value)
    return data


def validate_csv_schema(fieldnames: list[str], spec: ExperimentSpec) -> None:
    required = [spec.return_col, spec.date_col]
    if spec.threshold_lte is not None and not spec.threshold_col:
        raise ValueError("CSV schema invalid: threshold_col is required when threshold_lte is set")
    if spec.threshold_col:
        required.append(spec.threshold_col)

    available = set(fieldnames)
    missing = [name for name in required if name not in available]
    if missing:
        raise ValueError(
            "CSV schema invalid: missing columns "
            + ", ".join(missing)
            + f"; available columns: {', '.join(fieldnames) or '(none)'}"
        )


def run_experiment(project: Path, spec: ExperimentSpec) -> dict[str, Any]:
    fieldnames = read_fieldnames(spec.input_path)
    validate_csv_schema(fieldnames, spec)
    contract = validate_quant_data_contract(spec.input_path)
    if not contract.ok:
        failed = "; ".join(f"{issue.code}: {issue.message}" for issue in contract.issues if issue.level == "error")
        raise ValueError(f"data contract failed: {failed}")
    leak_check = run_quant_leak_check(spec.input_path)
    if not leak_check.ok:
        failed = "; ".join(f"{finding.code}: {finding.message}" for finding in leak_check.findings if finding.level == "error")
        raise ValueError(f"quant leak check failed: {failed}")
    rows = read_rows(spec.input_path)
    filtered = apply_filters(rows, spec)
    returns = [value for row in filtered if (value := to_float(row.get(spec.return_col))) is not None]
    if not returns:
        raise ValueError(
            f"experiment has no valid trades after filtering: rows_after_filter={len(filtered)}, "
            f"return_col={spec.return_col}"
        )
    full = compute_metrics(returns)
    yearly = group_metrics(filtered, spec.return_col, lambda row: date_year(row.get(spec.date_col, "")))
    monthly = group_metrics(filtered, spec.return_col, lambda row: date_month(row.get(spec.date_col, "")))
    input_sha256 = sha256_file(spec.input_path)
    runner_sha256 = sha256_file(Path(__file__).resolve())
    run_spec = create_run_spec(
        project,
        spec.name,
        {
            "data_hash": input_sha256,
            "input_path": str(spec.input_path),
            "params": {
                "return_col": spec.return_col,
                "date_col": spec.date_col,
                "threshold_col": spec.threshold_col,
                "threshold_lte": spec.threshold_lte,
            },
            "rows_before_filter": len(rows),
        },
        code_version=runner_sha256,
    )
    payload = {
        "name": spec.name,
        "run_id": run_spec.run_id,
        "run_dir": run_spec.run_dir,
        "spec_hash": run_spec.spec_hash,
        "input_path": str(spec.input_path),
        "input_sha256": input_sha256,
        "runner_path": str(Path(__file__).resolve()),
        "runner_sha256": runner_sha256,
        "rows_before_filter": len(rows),
        "rows_after_filter": len(filtered),
        "return_col": spec.return_col,
        "date_col": spec.date_col,
        "threshold_col": spec.threshold_col,
        "threshold_lte": spec.threshold_lte,
        "metrics": metrics_to_dict(full),
        "yearly": {key: metrics_to_dict(value) for key, value in yearly.items()},
        "monthly": {key: metrics_to_dict(value) for key, value in monthly.items()},
        "data_contract": contract.to_dict(),
        "leak_check": leak_check.to_dict(),
    }
    summary = render_experiment_summary(payload)
    lock = write_run_result(
        project,
        run_spec.run_id,
        result=payload,
        report=summary,
        audit={"data_contract": contract.to_dict(), "leak_check": leak_check.to_dict()},
    )
    payload["spec_lock"] = lock.to_dict()
    summary = render_experiment_summary(payload)
    write_run_result(
        project,
        run_spec.run_id,
        result=payload,
        report=summary,
        audit={"data_contract": contract.to_dict(), "leak_check": leak_check.to_dict()},
    )
    entry = register_result(
        project,
        kind="experiment",
        name=spec.name,
        payload=payload,
        markdown=summary,
        summary=one_line_summary(payload),
        tags=["experiment", "dedup" if "dedup" in spec.input_path.name else "check_dedup"],
    )
    payload["registry_entry"] = asdict(entry)
    _record_experiment_evidence(project, payload, source=entry.json_path)
    return payload


def fmt_pf(value: float | None) -> str:
    return "inf" if value is None else f"{value:.4f}"


def one_line_summary(payload: dict[str, Any]) -> str:
    metrics = payload["metrics"]
    return (
        f"{payload['name']}: trades={metrics['trades']} "
        f"PF={fmt_pf(metrics['profit_factor'])} "
        f"avg={metrics['avg_return']:.4%}"
    )


def render_experiment_summary(payload: dict[str, Any]) -> str:
    metrics = payload["metrics"]
    lines = [
        f"# Experiment: {payload['name']}",
        "",
        f"- run_id: {payload.get('run_id', '-')}",
        f"- input: {payload['input_path']}",
        f"- rows_before_filter: {payload['rows_before_filter']}",
        f"- rows_after_filter: {payload['rows_after_filter']}",
        f"- return_col: {payload['return_col']}",
        f"- threshold: {payload['threshold_col']} <= {payload['threshold_lte']}",
        f"- data_contract_ok: {str(payload.get('data_contract', {}).get('ok', False)).lower()}",
        f"- leak_check_ok: {str(payload.get('leak_check', {}).get('ok', False)).lower()}",
        "",
        "## Full Metrics",
        f"- input_sha256: `{payload['input_sha256']}`",
        f"- runner_sha256: `{payload['runner_sha256']}`",
        f"- trades: {metrics['trades']}",
        f"- win_rate: {metrics['win_rate']:.2%}",
        f"- avg_return: {metrics['avg_return']:.4%}",
        f"- total_return_units: {metrics['total_return_units']:.4f}",
        f"- profit_factor: {fmt_pf(metrics['profit_factor'])}",
        f"- max_drawdown_units: {metrics['max_drawdown_units']:.4f}",
        "",
        "## Yearly Metrics",
    ]
    for year, item in payload["yearly"].items():
        lines.append(
            f"- {year}: trades={item['trades']}, PF={fmt_pf(item['profit_factor'])}, "
            f"avg={item['avg_return']:.4%}, total={item['total_return_units']:.4f}"
        )
    lines.append("")
    lines.append("## Machine JSON")
    lines.append("```json")
    lines.append(json.dumps(payload, ensure_ascii=False, indent=2))
    lines.append("```")
    return "\n".join(lines) + "\n"


def _record_experiment_evidence(project: Path, payload: dict[str, Any], *, source: str) -> None:
    input_path = str(payload.get("input_path") or "")
    input_name = Path(input_path).name.lower()
    if "dedup" in input_name:
        record_evidence(
            project,
            claim="dedup baseline",
            value=input_path,
            evidence_type="experiment_result",
            source=source,
            path=input_path,
            tool="experiment",
            metadata={"run_id": payload.get("run_id")},
        )
    record_evidence(
        project,
        claim="artifact hashes and row count",
        value=f"input_sha256={payload.get('input_sha256')} runner_sha256={payload.get('runner_sha256')} rows={payload.get('rows_after_filter')}",
        evidence_type="experiment_result",
        source=source,
        path=input_path,
        tool="experiment",
        metadata={"run_id": payload.get("run_id"), "spec_hash": payload.get("spec_hash")},
    )
    yearly = payload.get("yearly") if isinstance(payload.get("yearly"), dict) else {}
    if len(yearly) > 1:
        record_evidence(
            project,
            claim="yearly OOS split",
            value="years=" + ",".join(sorted(str(key) for key in yearly)),
            evidence_type="experiment_result",
            source=source,
            path=input_path,
            tool="experiment",
            metadata={"run_id": payload.get("run_id")},
        )
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    record_evidence(
        project,
        claim="experiment metrics profit_factor",
        value=fmt_pf(metrics.get("profit_factor")),
        evidence_type="experiment_result",
        source=source,
        path=input_path,
        tool="experiment",
        metadata={"run_id": payload.get("run_id"), "metrics": metrics},
    )
