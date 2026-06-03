"""
Unit tests for tick_slippage_calculator.
"""

import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from quantagent.tick_slippage_calculator import (
    SlippageCase,
    SlippageDistribution,
    SlippageReport,
    calculate_slippage,
    find_executable_price,
)


class TestFindExecutablePrice(unittest.TestCase):
    """Test find_executable_price function."""

    def test_buy_direction_finds_sell_tick(self):
        """Buy order should match against sell ticks (Type='S')."""
        tick_data = pd.DataFrame({
            'Time': pd.to_datetime(['2018-03-15 09:30:00', '2018-03-15 09:30:01']),
            'Price': [59.05, 59.10],
            'Volume': [100, 200],
            'Type': ['B', 'S']
        })
        signal_time = datetime(2018, 3, 15, 9, 30, 0)

        price, delay = find_executable_price(tick_data, signal_time, 'buy', 100)

        self.assertEqual(price, 59.10)
        self.assertEqual(delay, 1000)  # 1 second delay

    def test_sell_direction_finds_buy_tick(self):
        """Sell order should match against buy ticks (Type='B')."""
        tick_data = pd.DataFrame({
            'Time': pd.to_datetime(['2018-03-15 09:30:00', '2018-03-15 09:30:01']),
            'Price': [59.05, 59.10],
            'Volume': [100, 200],
            'Type': ['B', 'S']
        })
        signal_time = datetime(2018, 3, 15, 9, 30, 0)

        price, delay = find_executable_price(tick_data, signal_time, 'sell', 100)

        self.assertEqual(price, 59.05)
        self.assertEqual(delay, 0)

    def test_no_future_ticks_returns_last_price(self):
        """When no future ticks exist, return last available price."""
        tick_data = pd.DataFrame({
            'Time': pd.to_datetime(['2018-03-15 09:29:00']),
            'Price': [59.00],
            'Volume': [100],
            'Type': ['B']
        })
        signal_time = datetime(2018, 3, 15, 9, 30, 0)

        price, delay = find_executable_price(tick_data, signal_time, 'buy', 100)

        self.assertEqual(price, 59.00)
        self.assertEqual(delay, 0)

    def test_empty_tick_data(self):
        """Empty tick data should return 0."""
        tick_data = pd.DataFrame()
        signal_time = datetime(2018, 3, 15, 9, 30, 0)

        price, delay = find_executable_price(tick_data, signal_time, 'buy', 100)

        self.assertEqual(price, 0.0)
        self.assertEqual(delay, 0)


class TestSlippageDataClasses(unittest.TestCase):
    """Test slippage data classes."""

    def test_slippage_case_to_dict(self):
        """SlippageCase should serialize to dict."""
        case = SlippageCase(
            trade_id=1,
            code='300678',
            signal_time='2018-03-15 09:30:00',
            signal_price=59.05,
            executable_price=59.10,
            direction='buy',
            volume=100.0,
            slippage_bps=8.46,
            slippage_pct=0.000846,
            tick_delay_ms=1000
        )

        result = case.to_dict()

        self.assertEqual(result['trade_id'], 1)
        self.assertEqual(result['code'], '300678')
        self.assertEqual(result['slippage_bps'], 8.46)

    def test_slippage_distribution_to_dict(self):
        """SlippageDistribution should serialize to dict."""
        dist = SlippageDistribution(
            range_0_10bps=10,
            range_10_20bps=5,
            range_20_50bps=3,
            range_50_100bps=1,
            range_over_100bps=0
        )

        result = dist.to_dict()

        self.assertEqual(result['range_0_10bps'], 10)
        self.assertEqual(result['range_10_20bps'], 5)

    def test_slippage_report_to_dict(self):
        """SlippageReport should serialize to dict."""
        report = SlippageReport(
            total_trades=10,
            average_slippage_bps=15.5,
            median_slippage_bps=12.0,
            std_slippage_bps=5.0,
            min_slippage_bps=5.0,
            max_slippage_bps=30.0,
            distribution=SlippageDistribution(),
            assumed_slippage_bps=20.0,
            slippage_underestimated=False,
            slippage_overestimated=True
        )

        result = report.to_dict()

        self.assertEqual(result['total_trades'], 10)
        self.assertEqual(result['average_slippage_bps'], 15.5)
        self.assertTrue(result['slippage_overestimated'])


class TestCalculateSlippage(unittest.TestCase):
    """Test calculate_slippage function."""

    def test_calculate_slippage_with_sample_data(self):
        """Calculate slippage with sample trades and tick data."""
        with TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create sample trades CSV
            trades_csv = tmppath / 'trades.csv'
            trades_df = pd.DataFrame({
                'code': ['300678'],
                'entry_date': ['2018-03-15'],
                'entry_price': [59.05],
                't1_auction_return': [0.02],
                'direction': [1],
                'volume': [100]
            })
            trades_df.to_csv(trades_csv, index=False)

            # Create sample tick CSV
            tick_dir = tmppath / 'ticks'
            tick_dir.mkdir()
            tick_csv = tick_dir / 'tick_trade_300678_20180315.csv'
            tick_df = pd.DataFrame({
                'Time': ['2018-03-15 09:30:00', '2018-03-15 09:30:01'],
                'Price': [59.05, 59.10],
                'Volume': [100, 200],
                'Type': ['B', 'S']
            })
            tick_df.to_csv(tick_csv, index=False)

            # Calculate slippage
            report = calculate_slippage(
                trades_csv=trades_csv,
                tick_dir=tick_dir,
                assumed_slippage_bps=20.0
            )

            self.assertEqual(report.total_trades, 1)
            self.assertGreater(report.average_slippage_bps, 0)
            self.assertIsInstance(report.distribution, SlippageDistribution)

    def test_missing_trades_file_raises_error(self):
        """Missing trades file should raise FileNotFoundError."""
        with TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            tick_dir = tmppath / 'ticks'
            tick_dir.mkdir()

            with self.assertRaises(FileNotFoundError):
                calculate_slippage(
                    trades_csv=tmppath / 'nonexistent.csv',
                    tick_dir=tick_dir
                )

    def test_missing_tick_dir_raises_error(self):
        """Missing tick directory should raise FileNotFoundError."""
        with TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            trades_csv = tmppath / 'trades.csv'
            trades_df = pd.DataFrame({
                'code': ['300678'],
                'entry_date': ['2018-03-15'],
                'entry_price': [59.05]
            })
            trades_df.to_csv(trades_csv, index=False)

            with self.assertRaises(FileNotFoundError):
                calculate_slippage(
                    trades_csv=trades_csv,
                    tick_dir=tmppath / 'nonexistent'
                )

    def test_empty_result_when_no_matching_ticks(self):
        """Should return empty report when no tick files match."""
        with TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create sample trades CSV
            trades_csv = tmppath / 'trades.csv'
            trades_df = pd.DataFrame({
                'code': ['300678'],
                'entry_date': ['2018-03-15'],
                'entry_price': [59.05]
            })
            trades_df.to_csv(trades_csv, index=False)

            # Create empty tick directory
            tick_dir = tmppath / 'ticks'
            tick_dir.mkdir()

            report = calculate_slippage(
                trades_csv=trades_csv,
                tick_dir=tick_dir
            )

            self.assertEqual(report.total_trades, 0)
            self.assertEqual(report.average_slippage_bps, 0.0)


if __name__ == '__main__':
    unittest.main()
