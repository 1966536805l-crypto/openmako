from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from quantagent.cli import main
from quantagent.quant_expectations import run_quant_expectations


class QuantExpectationsTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="mako quant expectations ")

    def test_market_bar_chinese_schema_passes(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "daily.csv"
            path.write_text(
                "日期,代码,开盘,最高,最低,收盘,成交量,成交额\n"
                "2026-04-24,000001,10,11,9,10.5,100000,1050000\n",
                encoding="utf-8",
            )

            report = run_quant_expectations(path, kind="market_bar_csv", hash_bytes=128)

            self.assertTrue(report.ok)
            self.assertEqual(report.kind, "market_bar_csv")
            self.assertEqual(report.metadata["distinct_codes_sampled"], 1)
            self.assertFalse(report.hash_partial)
            self.assertGreater(report.hash_bytes, 0)

    def test_market_bar_ohlc_violation_blocks(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "bad_daily.csv"
            path.write_text(
                "日期,代码,开盘,最高,最低,收盘,成交量\n"
                "2026-04-24,000001,10,9,8,10.5,100000\n",
                encoding="utf-8",
            )

            report = run_quant_expectations(path, kind="market_bar_csv")
            codes = {finding.code for finding in report.findings}

            self.assertFalse(report.ok)
            self.assertIn("ohlc_bounds_inconsistent", codes)

    def test_tick_trade_schema_passes_with_vendor_aliases(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "tick.csv"
            path.write_text(
                "TranID,Time,Price,Volume,Type\n"
                "1,09:30:00,10.01,100,B\n",
                encoding="utf-8",
            )

            report = run_quant_expectations(path, kind="tick_trade_csv")

            self.assertTrue(report.ok)
            self.assertEqual(report.rows_sampled, 1)
            self.assertEqual(report.metadata["min_date"], "")
            self.assertEqual(report.metadata["max_date"], "")

    def test_expectations_cli_json_blocks_bad_data(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "tick.csv"
            path.write_text("Time,Price,Volume\n09:30:00,0,100\n", encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(
                    [
                        "--no-trust-prompt",
                        "quant",
                        "--project",
                        tmp,
                        "expectations",
                        str(path),
                        "--kind",
                        "tick_trade_csv",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

            self.assertEqual(rc, 1)
            self.assertFalse(payload["ok"])
            self.assertIn("value_below_min", {item["code"] for item in payload["findings"]})


if __name__ == "__main__":
    unittest.main()
