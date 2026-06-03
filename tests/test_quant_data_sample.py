from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from quantagent.cli import main
from quantagent.quant_data_sample import QuantDataSampleSpec, _prefix_tick_time_with_date, sample_local_quant_data


class QuantDataSampleTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="mako quant data sample ")

    def test_samples_daily_market_zip_by_code_and_date(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            root = project / "2061票更新至4.30" / "每只股票一个文件"
            root.mkdir(parents=True)
            zip_path = root / "前复权.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr(
                    "前复权/000001_行情数据.csv",
                    "日期,代码,开盘价,最高价,最低价,收盘价,成交量（股）\n"
                    "2026-04-23,000001,10,11,9,10.5,1000\n"
                    "2026-04-24,000001,10.5,11.5,10,11,1200\n",
                )

            result = sample_local_quant_data(
                project,
                QuantDataSampleSpec(root=str(root), code="000001", kind="market_bar", start="2026-04-24", end="2026-04-24"),
            )

            self.assertTrue(result.ok, result.to_dict())
            self.assertEqual(result.rows_written, 1)
            self.assertEqual(result.expectation_kind, "market_bar_csv")
            self.assertTrue(Path(result.output_path).exists())

    def test_samples_minute_zip_by_code_and_freq(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            root = project / "分钟K线-股票241" / "2026" / "每日数据"
            root.mkdir(parents=True)
            zip_path = root / "2026-05-21.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr(
                    "2026-05-21/1分钟/sh600000.csv",
                    "日期,开盘,最高,最低,收盘,成交量(股),成交额(元)\n"
                    "2026-05-21 09:30:00,8.31,8.31,8.31,8.31,20000,166200\n"
                    "2026-05-21 09:31:00,8.31,8.36,8.31,8.36,174000,1451653\n",
                )

            result = sample_local_quant_data(
                project,
                QuantDataSampleSpec(root=str(project / "分钟K线-股票241"), code="600000", kind="minute_bar", date="2026-05-21", freq="1m"),
            )

            self.assertTrue(result.ok, result.to_dict())
            self.assertEqual(result.rows_written, 2)
            self.assertEqual(result.expectation_kind, "minute_bar_csv")
            self.assertIn("sh600000.csv", result.source_member)

    def test_data_sample_cli_json(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            root = project / "daily"
            root.mkdir()
            zip_path = root / "不复权.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr(
                    "不复权/000002.csv",
                    "日期,代码,开盘价,最高价,最低价,收盘价,成交量（股）\n"
                    "2026-04-24,000002,20,21,19,20.5,1000\n",
                )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(
                    [
                        "--no-trust-prompt",
                        "quant",
                        "--project",
                        tmp,
                        "data-sample",
                        str(root),
                        "--code",
                        "000002",
                        "--kind",
                        "market_bar",
                        "--adjust",
                        "不复权",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

            self.assertEqual(rc, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["rows_written"], 1)
            self.assertTrue(payload["expectations"]["ok"])

    def test_prefixes_tick_time_only_values_with_archive_date(self) -> None:
        rows = [{"Time": "09:30:00", "Price": "11.0"}, {"Time": "093100", "Price": "11.1"}]

        patched = _prefix_tick_time_with_date(rows, ["Time", "Price"], "2013-03-01")

        self.assertEqual(patched[0]["Time"], "2013-03-01 09:30:00")
        self.assertEqual(patched[1]["Time"], "2013-03-01 09:31:00")
        self.assertEqual(rows[0]["Time"], "09:30:00")


if __name__ == "__main__":
    unittest.main()
