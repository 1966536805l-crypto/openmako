from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from quantagent.agent_loop_v3 import build_agent_v3_plan, run_agent_loop_v3
from quantagent.answer_guard import guard_answer
from quantagent.broker_gateway import BrokerGatewaySpec, build_broker_gateway_snapshot
from quantagent.cli import main
from quantagent.quant_data_adapter import discover_quant_data
from quantagent.quant_execution_gate import QuantExecutionEvidenceSpec, run_quant_execution_gate
from quantagent.mode_router import route_agent_mode
from quantagent.quant_run_gate import (
    QuantRunSpec,
    latest_quant_gate_run,
    render_quant_gate_run,
    replay_quant_gate,
    run_quant_gate,
    run_quant_split_check,
)


class QuantRunGateTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="mako quant gate ")

    def write_trade_csv(self, project: Path, *, one_year: bool = False) -> Path:
        path = project / "sample_position_dedup.csv"
        second_year = "2025" if one_year else "2026"
        path.write_text(
            "entry_date,net_return,t1_auction_return\n"
            "2025-01-01,0.01,-10\n"
            f"{second_year}-01-02,0.02,-11\n",
            encoding="utf-8",
        )
        return path

    def write_execution_files(self, project: Path) -> dict[str, Path]:
        files = {
            "tick": project / "tick.csv",
            "fill": project / "fill.csv",
            "broker": project / "broker.csv",
            "slippage": project / "slippage.csv",
            "capacity": project / "capacity.csv",
        }
        files["tick"].write_text("time,price,volume\n09:30:00,10.0,1000\n", encoding="utf-8")
        files["fill"].write_text("time,code,price,qty\n09:31:00,000001,10.1,500\n", encoding="utf-8")
        files["broker"].write_text("broker,account\nlocal_broker,acct1\n", encoding="utf-8")
        files["slippage"].write_text("code,slippage_bps\n000001,3.2\n", encoding="utf-8")
        files["capacity"].write_text("code,capacity\n000001,1000000\n", encoding="utf-8")
        return files

    def test_quant_gate_run_creates_research_ready_bundle(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            path = self.write_trade_csv(project)

            run = run_quant_gate(
                project,
                QuantRunSpec(name="gate", input_path=str(path), threshold_col="t1_auction_return", threshold_lte=-9),
            )
            latest = latest_quant_gate_run(project)

            self.assertTrue(run.verdict.ok)
            self.assertTrue(run.evidence_bundle.research_ready)
            self.assertFalse(run.evidence_bundle.live_ready)
            self.assertTrue(run.evidence_bundle.evidence_ids)
            self.assertIsNotNone(latest)
            self.assertEqual(latest.gate_id, run.gate_id)
            self.assertIn("# Quant Run Gate", render_quant_gate_run(run))

    def test_execution_gate_requires_real_files_for_live_ready(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            missing = run_quant_execution_gate(project, QuantExecutionEvidenceSpec(execution_source="broker export"))
            files = self.write_execution_files(project)
            ready = run_quant_execution_gate(
                project,
                QuantExecutionEvidenceSpec(
                    tick_path=str(files["tick"]),
                    fill_path=str(files["fill"]),
                    broker_path=str(files["broker"]),
                    slippage_path=str(files["slippage"]),
                    capacity_path=str(files["capacity"]),
                    execution_source="broker export",
                ),
            )

            self.assertFalse(missing.live_ready)
            self.assertTrue(any(issue.code == "missing_evidence_path" for issue in missing.issues))
            self.assertTrue(ready.live_ready)
            self.assertEqual(ready.action, "pass")
            self.assertTrue(ready.broker_gateway["has_live_fill_evidence"])
            self.assertTrue(ready.broker_gateway["has_broker_provenance"])

    def test_broker_gateway_normalizes_vnpy_style_evidence(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            broker = project / "broker.csv"
            fill = project / "fills.csv"
            broker.write_text("gateway_name,accountid,balance,available\nCTP_SIM,acct-1,100000,80000\n", encoding="utf-8")
            fill.write_text(
                "datetime,symbol,direction,price,volume,vt_orderid,vt_tradeid,status\n"
                "2026-05-20 09:31:00,000001,buy,10.1,500,order-1,trade-1,filled\n",
                encoding="utf-8",
            )

            snapshot = build_broker_gateway_snapshot(
                project,
                BrokerGatewaySpec(broker_path=str(broker), fill_path=str(fill), source="broker export", gateway="CTP_SIM"),
            )

            self.assertTrue(snapshot.ok)
            self.assertTrue(snapshot.has_broker_provenance)
            self.assertTrue(snapshot.has_live_fill_evidence)
            self.assertEqual(snapshot.fills[0].code, "000001")
            self.assertEqual(snapshot.fills[0].notional, 5050.0)

    def test_broker_gateway_cli_json(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            files = self.write_execution_files(project)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(
                    [
                        "--no-trust-prompt",
                        "quant",
                        "--project",
                        tmp,
                        "broker-gateway",
                        "--broker",
                        str(files["broker"]),
                        "--fill",
                        str(files["fill"]),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

            self.assertEqual(rc, 0)
            self.assertTrue(payload["has_live_fill_evidence"])
            self.assertEqual(payload["fills"][0]["notional"], 5050.0)

    def test_quant_run_live_ready_uses_execution_gate_not_source_string(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            path = self.write_trade_csv(project)
            source_only = run_quant_gate(project, QuantRunSpec(name="gate", input_path=str(path), execution_source="broker export"))
            files = self.write_execution_files(project)
            with_files = run_quant_gate(
                project,
                QuantRunSpec(
                    name="gate",
                    input_path=str(path),
                    execution_source="broker export",
                    tick_path=str(files["tick"]),
                    fill_path=str(files["fill"]),
                    broker_path=str(files["broker"]),
                    slippage_path=str(files["slippage"]),
                    capacity_path=str(files["capacity"]),
                ),
            )

            self.assertTrue(source_only.evidence_bundle.research_ready)
            self.assertFalse(source_only.evidence_bundle.live_ready)
            self.assertTrue(with_files.evidence_bundle.live_ready)

    def test_quant_live_status_reports_missing_and_ready_evidence(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            path = self.write_trade_csv(project)
            run_quant_gate(project, QuantRunSpec(name="gate", input_path=str(path), execution_source="broker export"))

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                missing_rc = main(["--no-trust-prompt", "quant", "--project", tmp, "live-status", "--json"])
            missing_payload = json.loads(stdout.getvalue())

            files = self.write_execution_files(project)
            run_quant_gate(
                project,
                QuantRunSpec(
                    name="gate",
                    input_path=str(path),
                    execution_source="broker export",
                    tick_path=str(files["tick"]),
                    fill_path=str(files["fill"]),
                    broker_path=str(files["broker"]),
                    slippage_path=str(files["slippage"]),
                    capacity_path=str(files["capacity"]),
                ),
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                ready_rc = main(["--no-trust-prompt", "quant", "--project", tmp, "live-status", "--json"])
            ready_payload = json.loads(stdout.getvalue())

            self.assertEqual(missing_rc, 1)
            self.assertFalse(missing_payload["live_ready"])
            self.assertIn("fill", missing_payload["missing_evidence"])
            self.assertIn("broker", missing_payload["missing_evidence"])
            self.assertEqual(ready_rc, 0)
            self.assertTrue(ready_payload["live_ready"])
            self.assertEqual(ready_payload["missing_evidence"], [])
            self.assertIn("fill", ready_payload["present_evidence"])

    def test_data_adapter_discovers_local_zip_and_csv_formats(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            position = self.write_trade_csv(project)
            zip_path = project / "1分钟(2000-2025).zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("1分钟/sz000001.csv", "日期,开盘,最高,最低,收盘,成交量\n2026-01-01,1,2,1,2,100\n")

            result = discover_quant_data(project, [position, zip_path])
            kinds = {item.kind for item in result.artifacts}

            self.assertIn("position_dedup_csv", kinds)
            self.assertIn("minute_kline_zip", kinds)

    def test_split_check_blocks_single_year_without_explicit_oos(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            path = self.write_trade_csv(project, one_year=True)

            split = run_quant_split_check(path)

            self.assertFalse(split.ok)
            self.assertIn("two years", split.reason)

    def test_split_check_accepts_compact_yyyymmdd_dates(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "compact_position_dedup.csv"
            path.write_text(
                "entry_date,exit_date,net_return\n"
                "20250103,20250104,0.01\n"
                "20260424,20260425,0.02\n",
                encoding="utf-8",
            )

            split = run_quant_split_check(path)

            self.assertTrue(split.ok, split.to_dict())
            self.assertEqual(split.years, ("2025", "2026"))

    def test_quant_gate_cli_run_evidence_verdict_and_replay(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            path = self.write_trade_csv(project)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                run_rc = main(
                    [
                        "--no-trust-prompt",
                        "quant",
                        "--project",
                        tmp,
                        "run",
                        str(path),
                        "--threshold-col",
                        "t1_auction_return",
                        "--threshold",
                        "-9",
                    ]
                )
            run_output = stdout.getvalue()

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                evidence_rc = main(["--no-trust-prompt", "quant", "--project", tmp, "evidence", "--json"])
            evidence_payload = json.loads(stdout.getvalue())

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                verdict_rc = main(["--no-trust-prompt", "quant", "--project", tmp, "verdict", "--answer", "PF research report only"])

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                live_rc = main(["--no-trust-prompt", "quant", "--project", tmp, "verdict", "--answer", "PF=2.0 可以实盘"])
            live_output = stdout.getvalue()

            replay = replay_quant_gate(project)

            self.assertEqual(run_rc, 0)
            self.assertIn("research_ready: true", run_output)
            self.assertEqual(evidence_rc, 0)
            self.assertTrue(evidence_payload["research_ready"])
            self.assertEqual(verdict_rc, 0)
            self.assertEqual(live_rc, 1)
            self.assertIn("requires broker/fill", live_output)
            self.assertTrue(replay.verdict.ok)

    def test_answer_guard_requires_gate_and_blocks_live_without_execution_source(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            no_gate = guard_answer(project, "PF research report is confirmed.", task="quant report")
            path = self.write_trade_csv(project)
            run_quant_gate(project, QuantRunSpec(name="gate", input_path=str(path)))
            research = guard_answer(project, "Research report is available from quant run gate evidence.", task="quant report")
            live = guard_answer(project, "PF=2.0 is safe to trade live.", task="quant report")

            self.assertFalse(no_gate.ok)
            self.assertTrue(any("QuantRunGate evidence is required" in item.reason for item in no_gate.findings))
            self.assertTrue(research.ok, research.answer)
            self.assertFalse(live.ok)
            self.assertTrue(any("QuantRunGate blocked" in item.reason for item in live.findings))

    def test_agent_v3_plan_inserts_quant_run_gate(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            route = route_agent_mode(project, "报告 PF 和回撤")
            plan = build_agent_v3_plan("报告 PF 和回撤", route, include_validation=False)

            self.assertIn("quant_evidence_gate", [step.name for step in plan])
            self.assertIn("quant_run_gate", [step.name for step in plan])

    def test_agent_v3_auto_triggers_quant_run_when_position_csv_exists(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_trade_csv(project)

            result = run_agent_loop_v3(project, "这个策略 PF 怎么样", include_validation=False)
            gate_obs = next(item for item in result.observations if item.name == "quant_run_gate")

            self.assertTrue(gate_obs.data["auto_run"]["triggered"])
            self.assertTrue(gate_obs.data["evidence_bundle"]["research_ready"])

    def test_split_check_blocks_insufficient_oos_sample_size(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "insufficient_oos.csv"
            # Total 10 rows: 9 in-sample (2025-01-01 to 2025-01-09), 1 OOS (2025-01-10)
            # OOS ratio: 1/10 = 10% < 20%
            rows = ["entry_date,net_return"]
            for day in range(1, 10):
                rows.append(f"2025-01-{day:02d},0.01")
            rows.append("2025-01-10,0.02")
            path.write_text("\n".join(rows), encoding="utf-8")

            split = run_quant_split_check(path, oos_start="2025-01-10")

            self.assertFalse(split.ok)
            self.assertIn("OOS sample size insufficient", split.reason)
            self.assertIn("1/10", split.reason)
            self.assertIn("< 20%", split.reason)
            self.assertEqual(split.oos_rows, 1)
            self.assertEqual(split.in_sample_rows, 9)

    def test_split_check_blocks_insufficient_in_sample_size(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "insufficient_in_sample.csv"
            # Total 10 rows: 4 in-sample (2025-01-01 to 2025-01-04), 6 OOS (2025-01-05 to 2025-01-10)
            # in-sample ratio: 4/10 = 40% < 50%
            rows = ["entry_date,net_return"]
            for day in range(1, 11):
                rows.append(f"2025-01-{day:02d},0.01")
            path.write_text("\n".join(rows), encoding="utf-8")

            split = run_quant_split_check(path, oos_start="2025-01-05")

            self.assertFalse(split.ok)
            self.assertIn("in-sample size insufficient", split.reason)
            self.assertIn("4/10", split.reason)
            self.assertIn("< 50%", split.reason)
            self.assertEqual(split.oos_rows, 6)
            self.assertEqual(split.in_sample_rows, 4)

    def test_split_check_accepts_sufficient_sample_sizes(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "sufficient_samples.csv"
            # Total 10 rows: 6 in-sample (2025-01-01 to 2025-01-06), 4 OOS (2025-01-07 to 2025-01-10)
            # in-sample ratio: 6/10 = 60% >= 50%
            # OOS ratio: 4/10 = 40% >= 20%
            rows = ["entry_date,net_return"]
            for day in range(1, 11):
                rows.append(f"2025-01-{day:02d},0.01")
            path.write_text("\n".join(rows), encoding="utf-8")

            split = run_quant_split_check(path, oos_start="2025-01-07")

            self.assertTrue(split.ok, split.reason)
            self.assertEqual(split.reason, "split has yearly/OOS coverage")
            self.assertEqual(split.oos_rows, 4)
            self.assertEqual(split.in_sample_rows, 6)

    def test_split_check_accepts_exact_threshold_sample_sizes(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "exact_threshold.csv"
            # Total 10 rows: 5 in-sample, 2 OOS (exactly 20%)
            # in-sample ratio: 5/10 = 50% (exactly at threshold)
            # OOS ratio: 2/10 = 20% (exactly at threshold)
            rows = ["entry_date,net_return"]
            for day in range(1, 8):
                rows.append(f"2025-01-{day:02d},0.01")
            for day in range(8, 10):
                rows.append(f"2025-01-{day:02d},0.02")
            path.write_text("\n".join(rows), encoding="utf-8")

            split = run_quant_split_check(path, oos_start="2025-01-08")

            self.assertTrue(split.ok, split.reason)
            self.assertEqual(split.oos_rows, 2)
            self.assertEqual(split.in_sample_rows, 7)

    def test_split_check_skips_validation_when_no_explicit_oos(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "multi_year_no_oos.csv"
            # Multi-year data without explicit OOS range should pass without sample size checks
            path.write_text(
                "entry_date,net_return\n"
                "2025-01-01,0.01\n"
                "2026-01-02,0.02\n",
                encoding="utf-8",
            )

            split = run_quant_split_check(path)

            self.assertTrue(split.ok)
            self.assertEqual(split.oos_rows, 0)
            self.assertEqual(split.in_sample_rows, 0)

    def test_split_check_oos_exactly_20_percent_passes(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "oos_exactly_20_percent.csv"
            # Total 10 rows: 8 in-sample, 2 OOS (exactly 20.0%)
            rows = ["entry_date,net_return"]
            for day in range(1, 9):
                rows.append(f"2025-01-{day:02d},0.01")
            for day in range(9, 11):
                rows.append(f"2025-01-{day:02d},0.02")
            path.write_text("\n".join(rows), encoding="utf-8")

            split = run_quant_split_check(path, oos_start="2025-01-09")

            self.assertTrue(split.ok, split.reason)
            self.assertEqual(split.oos_rows, 2)
            self.assertEqual(split.in_sample_rows, 8)

    def test_split_check_oos_19_9_percent_fails(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "oos_19_9_percent.csv"
            # Total 1000 rows: 801 in-sample, 199 OOS (19.9%)
            rows = ["entry_date,net_return"]
            # Generate 801 in-sample rows (2025-01-01 to 2025-12-31, cycling)
            for i in range(801):
                month = (i % 12) + 1
                day = (i % 28) + 1
                rows.append(f"2025-{month:02d}-{day:02d},0.01")
            # Generate 199 OOS rows (2026-01-01 to 2026-12-31, cycling)
            for i in range(199):
                month = (i % 12) + 1
                day = (i % 28) + 1
                rows.append(f"2026-{month:02d}-{day:02d},0.02")
            path.write_text("\n".join(rows), encoding="utf-8")

            split = run_quant_split_check(path, oos_start="2026-01-01")

            self.assertFalse(split.ok)
            self.assertIn("OOS sample size insufficient", split.reason)
            self.assertEqual(split.oos_rows, 199)
            self.assertEqual(split.in_sample_rows, 801)

    def test_split_check_in_sample_exactly_50_percent_passes(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "in_sample_exactly_50_percent.csv"
            # Total 10 rows: 5 in-sample (exactly 50.0%), 5 OOS
            rows = ["entry_date,net_return"]
            for day in range(1, 11):
                rows.append(f"2025-01-{day:02d},0.01")
            path.write_text("\n".join(rows), encoding="utf-8")

            split = run_quant_split_check(path, oos_start="2025-01-06")

            self.assertTrue(split.ok, split.reason)
            self.assertEqual(split.oos_rows, 5)
            self.assertEqual(split.in_sample_rows, 5)

    def test_split_check_in_sample_49_9_percent_fails(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "in_sample_49_9_percent.csv"
            # Total 1000 rows: 499 in-sample (49.9%), 501 OOS
            rows = ["entry_date,net_return"]
            # Generate 499 in-sample rows (2025-01-01 to 2025-12-31, cycling)
            for i in range(499):
                month = (i % 12) + 1
                day = (i % 28) + 1
                rows.append(f"2025-{month:02d}-{day:02d},0.01")
            # Generate 501 OOS rows (2026-01-01 to 2026-12-31, cycling)
            for i in range(501):
                month = (i % 12) + 1
                day = (i % 28) + 1
                rows.append(f"2026-{month:02d}-{day:02d},0.02")
            path.write_text("\n".join(rows), encoding="utf-8")

            split = run_quant_split_check(path, oos_start="2026-01-01")

            self.assertFalse(split.ok)
            self.assertIn("in-sample size insufficient", split.reason)
            self.assertEqual(split.oos_rows, 501)
            self.assertEqual(split.in_sample_rows, 499)

    def test_split_check_oos_0_percent_fails(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "oos_0_percent.csv"
            # Total 10 rows: 10 in-sample, 0 OOS (0%)
            rows = ["entry_date,net_return"]
            for day in range(1, 11):
                rows.append(f"2025-01-{day:02d},0.01")
            path.write_text("\n".join(rows), encoding="utf-8")

            # OOS start is after all data, so 0 OOS rows
            split = run_quant_split_check(path, oos_start="2025-02-01")

            self.assertFalse(split.ok)
            # When OOS is 0, has_explicit_oos is False, so it fails with "need at least two years"
            self.assertIn("need at least two years", split.reason)
            self.assertEqual(split.oos_rows, 0)
            self.assertEqual(split.in_sample_rows, 10)

    def test_split_check_oos_100_percent_fails(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "oos_100_percent.csv"
            # Total 10 rows: 0 in-sample, 10 OOS (100%)
            rows = ["entry_date,net_return"]
            for day in range(1, 11):
                rows.append(f"2025-01-{day:02d},0.01")
            path.write_text("\n".join(rows), encoding="utf-8")

            split = run_quant_split_check(path, oos_start="2025-01-01")

            self.assertFalse(split.ok)
            # When in-sample is 0, has_explicit_oos is False, so it fails with "need at least two years"
            self.assertIn("need at least two years", split.reason)
            self.assertEqual(split.oos_rows, 10)
            self.assertEqual(split.in_sample_rows, 0)

    def test_runner_sha256_required_for_research_ready(self) -> None:
        """Test that runner_sha256 presence controls research_ready flag."""
        with self.make_project() as tmp:
            project = Path(tmp)
            path = self.write_trade_csv(project)

            run = run_quant_gate(
                project,
                QuantRunSpec(name="gate", input_path=str(path), threshold_col="t1_auction_return", threshold_lte=-9),
            )

            # With proper experiment run, runner_sha256 should be present
            self.assertTrue(run.evidence_bundle.runner_sha256)
            self.assertTrue(run.evidence_bundle.research_ready)

    def test_empty_runner_sha256_blocks_research_ready(self) -> None:
        """Test that empty string runner_sha256 blocks research_ready."""
        with self.make_project() as tmp:
            project = Path(tmp)
            path = self.write_trade_csv(project)

            # Create a bundle with empty runner_sha256
            from quantagent.quant_run_gate import QuantEvidenceBundle

            bundle = QuantEvidenceBundle(
                gate_id="test-gate",
                run_id="test-run",
                input_sha256="abc123",
                spec_hash="def456",
                data_contract_ok=True,
                leak_check_ok=True,
                split_ok=True,
                runner_sha256="",  # Empty string
            )

            # research_ready should be False due to empty runner_sha256
            self.assertFalse(bundle.research_ready)

    def test_missing_runner_sha256_blocks_research_ready(self) -> None:
        """Test that missing runner_sha256 (default empty) blocks research_ready."""
        with self.make_project() as tmp:
            project = Path(tmp)

            # Create a bundle without runner_sha256 (defaults to empty string)
            from quantagent.quant_run_gate import QuantEvidenceBundle

            bundle = QuantEvidenceBundle(
                gate_id="test-gate",
                run_id="test-run",
                input_sha256="abc123",
                spec_hash="def456",
                data_contract_ok=True,
                leak_check_ok=True,
                split_ok=True,
                # runner_sha256 not provided, defaults to ""
            )

            # research_ready should be False
            self.assertFalse(bundle.research_ready)
            self.assertEqual(bundle.runner_sha256, "")

    def test_valid_runner_sha256_enables_research_ready(self) -> None:
        """Test that valid runner_sha256 enables research_ready when all other conditions met."""
        with self.make_project() as tmp:
            project = Path(tmp)

            from quantagent.quant_run_gate import QuantEvidenceBundle

            bundle = QuantEvidenceBundle(
                gate_id="test-gate",
                run_id="test-run",
                input_sha256="abc123",
                spec_hash="def456",
                data_contract_ok=True,
                leak_check_ok=True,
                split_ok=True,
                runner_sha256="a1b2c3d4e5f6",  # Valid signature
            )

            # research_ready should be True
            self.assertTrue(bundle.research_ready)

    def test_runner_sha256_computed_from_experiment_runner(self) -> None:
        """Test that runner_sha256 is computed from experiment_runner.py file."""
        with self.make_project() as tmp:
            project = Path(tmp)
            path = self.write_trade_csv(project)

            run = run_quant_gate(
                project,
                QuantRunSpec(name="gate", input_path=str(path), threshold_col="t1_auction_return", threshold_lte=-9),
            )

            # runner_sha256 should be a valid SHA256 hash (64 hex characters)
            self.assertTrue(run.evidence_bundle.runner_sha256)
            self.assertEqual(len(run.evidence_bundle.runner_sha256), 64)
            self.assertTrue(all(c in "0123456789abcdef" for c in run.evidence_bundle.runner_sha256))


if __name__ == "__main__":
    unittest.main()
