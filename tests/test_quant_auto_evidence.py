from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from quantagent.cli import main
from quantagent.quant_auto_evidence import find_strategy_input_candidate, profile_strategy_input, run_quant_auto_evidence


class QuantAutoEvidenceTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="mako quant auto evidence ")

    def write_strategy_csv(self, project: Path) -> Path:
        path = project / "sample_position_dedup.csv"
        path.write_text(
            "code,entry_date,exit_date,entry_price,exit_price,net_return,t1_auction_return\n"
            "000001,2025-01-03,2025-01-04,10.0,10.2,0.020,-10\n"
            "000001,2026-04-24,2026-04-25,11.0,11.3,0.027,-11\n",
            encoding="utf-8",
        )
        return path

    def write_strategy_output_csv(self, root: Path) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        path = root / "preferred_rule_t1_portfolio_trades.csv"
        path.write_text(
            "strategy,event_date,code,entry_date,exit_date,entry_price,exit_price,net_return\n"
            "preferred,20250102,000001.SZ,2025-01-03,2025-01-04,10.0,10.2,0.020\n"
            "preferred,20260423,000001.SZ,2026-04-24,2026-04-25,11.0,11.3,0.027\n",
            encoding="utf-8",
        )
        return path

    def write_market_and_minute_data(self, project: Path) -> None:
        daily_root = project / "2061票更新至4.30"
        daily_root.mkdir()
        with zipfile.ZipFile(daily_root / "前复权.zip", "w") as zf:
            zf.writestr(
                "前复权/000001.csv",
                "日期,代码,开盘价,最高价,最低价,收盘价,成交量（股）\n"
                "2026-04-24,000001,11.0,11.5,10.8,11.3,120000\n",
            )
        minute_root = project / "分钟K线-股票241" / "2026" / "每日数据"
        minute_root.mkdir(parents=True)
        with zipfile.ZipFile(minute_root / "2026-04-24.zip", "w") as zf:
            zf.writestr(
                "2026-04-24/1分钟/sz000001.csv",
                "日期,开盘,最高,最低,收盘,成交量(股),成交额(元)\n"
                "2026-04-24 09:30:00,11.0,11.1,10.9,11.05,20000,221000\n",
            )

    def write_execution_files(self, project: Path) -> None:
        (project / "tick.csv").write_text("time,price,volume\n09:30:00,11.0,1000\n", encoding="utf-8")
        (project / "fill.csv").write_text("time,code,price,qty\n09:31:00,000001,11.1,500\n", encoding="utf-8")
        (project / "broker.csv").write_text("broker,account\nlocal_broker,acct1\n", encoding="utf-8")
        (project / "slippage.csv").write_text("code,slippage_bps\n000001,3.2\n", encoding="utf-8")
        (project / "capacity.csv").write_text("code,capacity\n000001,1000000\n", encoding="utf-8")

    def write_broker_evidence_bundle(self, project: Path) -> dict[str, Path]:
        bundle = project / ".quantagent" / "broker_evidence" / "mobile_screenshot_20260521_20260522"
        bundle.mkdir(parents=True)
        files = {
            "tick": bundle / "tick.csv",
            "fill": bundle / "fill.csv",
            "broker": bundle / "broker.csv",
            "order": bundle / "order.csv",
            "position": bundle / "position.csv",
            "account": bundle / "account.csv",
            "slippage": bundle / "slippage.csv",
            "capacity": bundle / "capacity.csv",
        }
        files["tick"].write_text("time,code,price,volume\n09:31:00,000001,11.1,1000\n", encoding="utf-8")
        files["fill"].write_text("time,code,price,qty,order_id,side,trade_id,status\n09:31:00,000001,11.1,500,order-1,buy,trade-1,filled\n", encoding="utf-8")
        files["broker"].write_text("broker,account\nlocal_broker,acct1\n", encoding="utf-8")
        files["order"].write_text("time,code,order_id,price,qty,traded,status,side\n09:30:59,000001,order-1,11.1,500,500,filled,buy\n", encoding="utf-8")
        files["position"].write_text("code,quantity,available,cost_price,pnl\n000001,500,500,11.1,0\n", encoding="utf-8")
        files["account"].write_text("broker,account,balance,available,frozen,currency\nlocal_broker,acct1,100000,94450,0,CNY\n", encoding="utf-8")
        files["slippage"].write_text("code,slippage_bps\n000001,5\n", encoding="utf-8")
        files["capacity"].write_text("code,capacity\n000001,1000000\n", encoding="utf-8")
        return files

    def test_auto_evidence_research_ready_with_local_data_samples(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_strategy_csv(project)
            self.write_market_and_minute_data(project)

            result = run_quant_auto_evidence(project, "这个策略咋样")

            self.assertTrue(result.research_ready, result.to_dict())
            self.assertFalse(result.live_ready)
            self.assertTrue(result.data_samples)
            self.assertTrue(any(item["role"] == "strategy_input" and item["ok"] for item in result.expectations))
            self.assertEqual(result.position_kind, "position_dedup_csv")
            self.assertTrue(Path(result.output_json).exists())

    def test_auto_evidence_finds_external_strategy_root_and_direct_samples_data_roots(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            strategy_root = project / "external_strategies"
            strategy_path = self.write_strategy_output_csv(strategy_root)
            self.write_market_and_minute_data(project)

            result = run_quant_auto_evidence(
                project,
                "这个策略咋样",
                strategy_roots=[strategy_root],
                data_roots=[project / "2061票更新至4.30", project / "分钟K线-股票241"],
                max_files=1,
            )

            self.assertTrue(result.research_ready, result.to_dict())
            self.assertEqual(Path(result.position_path).resolve(strict=False), strategy_path.resolve(strict=False))
            self.assertTrue(any("not dedup-marked" in warning for warning in result.warnings))
            self.assertEqual({item["spec"]["kind"] for item in result.data_samples}, {"market_bar", "minute_bar"})

    def test_auto_evidence_cli_accepts_explicit_input(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            strategy = self.write_strategy_csv(project)
            self.write_market_and_minute_data(project)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(["--no-trust-prompt", "quant", "--project", tmp, "auto-evidence", "这个策略咋样", "--input", str(strategy), "--json"])
            payload = json.loads(stdout.getvalue())

            self.assertEqual(rc, 0)
            self.assertEqual(Path(payload["position_path"]).resolve(strict=False), strategy.resolve(strict=False))
            self.assertTrue(payload["research_ready"])

    def test_strategy_profile_keeps_code_date_from_same_row(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            path = project / "multi_position_dedup.csv"
            path.write_text(
                "code,entry_date,exit_date,entry_price,exit_price,net_return\n"
                "000001,2025-01-03,2025-01-04,10,10.1,0.01\n"
                "300678,2026-04-24,2026-04-25,20,20.4,0.02\n",
                encoding="utf-8",
            )
            candidate = find_strategy_input_candidate(project)
            assert candidate is not None

            profile = profile_strategy_input(candidate)

            self.assertEqual(profile.sample_date, "2026-04-24")
            self.assertEqual(profile.code, "300678")

    def test_auto_evidence_live_ready_when_execution_files_exist(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_strategy_csv(project)
            self.write_market_and_minute_data(project)
            self.write_execution_files(project)

            result = run_quant_auto_evidence(project, "这个策略能实盘吗")

            self.assertTrue(result.research_ready, result.to_dict())
            self.assertTrue(result.live_ready, result.to_dict())
            self.assertEqual(result.action, "pass")
            self.assertEqual(set(result.execution_evidence), {"tick", "fill", "broker", "slippage", "capacity"})

    def test_auto_evidence_discovers_broker_evidence_bundle(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_strategy_csv(project)
            self.write_market_and_minute_data(project)
            files = self.write_broker_evidence_bundle(project)

            result = run_quant_auto_evidence(project, "这个策略咋样")

            self.assertTrue(result.research_ready, result.to_dict())
            self.assertEqual(set(files), set(result.execution_evidence))
            for key, path in files.items():
                resolved = str(path.resolve(strict=False))
                self.assertEqual(result.execution_evidence[key], resolved)
                self.assertEqual(result.run_spec[f"{key}_path"], resolved)
            self.assertEqual(result.run_spec["execution_source"], "auto-evidence local execution files")
            self.assertTrue(result.live_ready, result.to_dict())

    def test_auto_evidence_cli_json(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_strategy_csv(project)
            self.write_market_and_minute_data(project)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(["--no-trust-prompt", "quant", "--project", tmp, "auto-evidence", "这个策略咋样", "--json"])
            payload = json.loads(stdout.getvalue())

            self.assertEqual(rc, 0)
            self.assertTrue(payload["research_ready"])
            self.assertFalse(payload["live_ready"])
            self.assertTrue(payload["data_samples"])


if __name__ == "__main__":
    unittest.main()
