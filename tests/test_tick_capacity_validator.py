"""
Tests for tick_capacity_validator module.
"""

import csv
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from quantagent.tick_capacity_validator import (
    CapacityReport,
    MarketLiquidity,
    calculate_market_liquidity,
    find_tick_file,
    load_tick_data,
    load_trades,
    validate_capacity,
)


class TestCalculateMarketLiquidity(unittest.TestCase):
    def test_empty_tick_data(self):
        target_time = datetime(2018, 3, 15, 10, 0, 0)
        liquidity = calculate_market_liquidity([], target_time, 5)

        self.assertEqual(liquidity.total_volume, 0.0)
        self.assertEqual(liquidity.total_amount, 0.0)
        self.assertEqual(liquidity.trade_count, 0)
        self.assertEqual(liquidity.avg_trade_volume, 0.0)

    def test_single_tick_in_window(self):
        target_time = datetime(2018, 3, 15, 10, 0, 0)
        tick_data = [
            {
                "Time": "2018-03-15 10:00:00",
                "Volume": "100",
                "Price": "50.0"
            }
        ]

        liquidity = calculate_market_liquidity(tick_data, target_time, 5)

        self.assertEqual(liquidity.total_volume, 100.0)
        self.assertEqual(liquidity.total_amount, 5000.0)
        self.assertEqual(liquidity.trade_count, 1)
        self.assertEqual(liquidity.avg_trade_volume, 100.0)

    def test_multiple_ticks_in_window(self):
        target_time = datetime(2018, 3, 15, 10, 0, 0)
        tick_data = [
            {"Time": "2018-03-15 09:58:00", "Volume": "100", "Price": "50.0"},
            {"Time": "2018-03-15 10:00:00", "Volume": "200", "Price": "51.0"},
            {"Time": "2018-03-15 10:02:00", "Volume": "150", "Price": "50.5"},
        ]

        liquidity = calculate_market_liquidity(tick_data, target_time, 5)

        self.assertEqual(liquidity.total_volume, 450.0)
        self.assertEqual(liquidity.total_amount, 100*50 + 200*51 + 150*50.5)
        self.assertEqual(liquidity.trade_count, 3)
        self.assertEqual(liquidity.avg_trade_volume, 150.0)

    def test_ticks_outside_window(self):
        target_time = datetime(2018, 3, 15, 10, 0, 0)
        tick_data = [
            {"Time": "2018-03-15 09:00:00", "Volume": "100", "Price": "50.0"},
            {"Time": "2018-03-15 11:00:00", "Volume": "200", "Price": "51.0"},
        ]

        liquidity = calculate_market_liquidity(tick_data, target_time, 5)

        self.assertEqual(liquidity.total_volume, 0.0)
        self.assertEqual(liquidity.trade_count, 0)


class TestFindTickFile(unittest.TestCase):
    def test_find_standard_pattern(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tick_dir = Path(tmpdir)
            tick_file = tick_dir / "tick_trade_300678_20180315.csv"
            tick_file.touch()

            found = find_tick_file(tick_dir, "300678", "2018-03-15")
            self.assertIsNotNone(found)
            self.assertEqual(found.name, "tick_trade_300678_20180315.csv")

    def test_find_alternative_pattern(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tick_dir = Path(tmpdir)
            tick_file = tick_dir / "300678_20180315_tick.csv"
            tick_file.touch()

            found = find_tick_file(tick_dir, "300678", "2018-03-15")
            self.assertIsNotNone(found)

    def test_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tick_dir = Path(tmpdir)
            found = find_tick_file(tick_dir, "300678", "2018-03-15")
            self.assertIsNone(found)


class TestValidateCapacity(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tick_dir = Path(self.tmpdir) / "ticks"
        self.tick_dir.mkdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir)

    def create_trades_csv(self, trades):
        trades_file = Path(self.tmpdir) / "trades.csv"
        with open(trades_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["code", "date", "time", "volume"])
            writer.writeheader()
            writer.writerows(trades)
        return trades_file

    def create_tick_csv(self, code, date, ticks):
        date_clean = date.replace("-", "")
        tick_file = self.tick_dir / f"tick_trade_{code}_{date_clean}.csv"
        with open(tick_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["Time", "Volume", "Price"])
            writer.writeheader()
            writer.writerows(ticks)
        return tick_file

    def test_empty_trades(self):
        trades_file = self.create_trades_csv([])
        report = validate_capacity(trades_file, self.tick_dir)

        self.assertEqual(report.total_trades, 0)
        self.assertEqual(report.capacity_ok_conservative, 0)
        self.assertEqual(report.capacity_ok_aggressive, 0)

    def test_trade_within_conservative_capacity(self):
        # Strategy trades 50 shares
        trades = [
            {
                "code": "300678",
                "date": "2018-03-15",
                "time": "2018-03-15 10:00:00",
                "volume": "50"
            }
        ]
        trades_file = self.create_trades_csv(trades)

        # Market has 1000 shares in window (50/1000 = 5% < 10%)
        ticks = []
        base_time = datetime(2018, 3, 15, 9, 58, 0)
        for i in range(10):
            tick_time = base_time + timedelta(seconds=i * 30)
            ticks.append({
                "Time": tick_time.strftime("%Y-%m-%d %H:%M:%S"),
                "Volume": "100",
                "Price": "50.0"
            })

        self.create_tick_csv("300678", "2018-03-15", ticks)

        report = validate_capacity(trades_file, self.tick_dir)

        self.assertEqual(report.total_trades, 1)
        self.assertEqual(report.capacity_ok_conservative, 1)
        self.assertEqual(report.capacity_ok_aggressive, 1)
        self.assertEqual(len(report.insufficient_capacity_conservative), 0)

    def test_trade_exceeds_conservative_capacity(self):
        # Strategy trades 150 shares
        trades = [
            {
                "code": "300678",
                "date": "2018-03-15",
                "time": "2018-03-15 10:00:00",
                "volume": "150"
            }
        ]
        trades_file = self.create_trades_csv(trades)

        # Market has 1000 shares in window (150/1000 = 15% > 10% but < 20%)
        # Time window is 5 minutes centered on 10:00:00, so 09:58:00 to 10:02:00
        # Create ticks within this window
        ticks = []
        base_time = datetime(2018, 3, 15, 9, 58, 0)
        for i in range(10):
            tick_time = base_time + timedelta(seconds=i * 30)
            ticks.append({
                "Time": tick_time.strftime("%Y-%m-%d %H:%M:%S"),
                "Volume": "100",
                "Price": "50.0"
            })

        self.create_tick_csv("300678", "2018-03-15", ticks)

        report = validate_capacity(trades_file, self.tick_dir)

        self.assertEqual(report.total_trades, 1)
        self.assertEqual(report.capacity_ok_conservative, 0)
        self.assertEqual(report.capacity_ok_aggressive, 1)
        self.assertEqual(len(report.insufficient_capacity_conservative), 1)
        self.assertEqual(len(report.insufficient_capacity_aggressive), 0)

        issue = report.insufficient_capacity_conservative[0]
        self.assertEqual(issue.code, "300678")
        self.assertEqual(issue.strategy_volume, 150.0)
        # 9 ticks fall within the 5-minute window (09:58:00 to 10:02:00)
        self.assertEqual(issue.market_volume, 900.0)
        self.assertAlmostEqual(issue.ratio, 150.0/900.0, places=4)

    def test_trade_exceeds_aggressive_capacity(self):
        # Strategy trades 250 shares
        trades = [
            {
                "code": "300678",
                "date": "2018-03-15",
                "time": "2018-03-15 10:00:00",
                "volume": "250"
            }
        ]
        trades_file = self.create_trades_csv(trades)

        # Market has 1000 shares in window (250/1000 = 25% > 20%)
        ticks = []
        base_time = datetime(2018, 3, 15, 9, 58, 0)
        for i in range(10):
            tick_time = base_time + timedelta(seconds=i * 30)
            ticks.append({
                "Time": tick_time.strftime("%Y-%m-%d %H:%M:%S"),
                "Volume": "100",
                "Price": "50.0"
            })

        self.create_tick_csv("300678", "2018-03-15", ticks)

        report = validate_capacity(trades_file, self.tick_dir)

        self.assertEqual(report.total_trades, 1)
        self.assertEqual(report.capacity_ok_conservative, 0)
        self.assertEqual(report.capacity_ok_aggressive, 0)
        self.assertEqual(len(report.insufficient_capacity_conservative), 1)
        self.assertEqual(len(report.insufficient_capacity_aggressive), 1)

    def test_missing_tick_data(self):
        trades = [
            {
                "code": "999999",
                "date": "2018-03-15",
                "time": "2018-03-15 10:00:00",
                "volume": "100"
            }
        ]
        trades_file = self.create_trades_csv(trades)

        report = validate_capacity(trades_file, self.tick_dir)

        # Trade is counted but not validated (no tick data)
        self.assertEqual(report.total_trades, 1)
        self.assertEqual(report.capacity_ok_conservative, 0)
        self.assertEqual(report.capacity_ok_aggressive, 0)


if __name__ == "__main__":
    unittest.main()
