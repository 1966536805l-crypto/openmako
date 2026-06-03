#!/usr/bin/env python3
"""
Unit tests for tick_price_validator module.
"""

import csv
import tempfile
import unittest
from pathlib import Path

from quantagent.tick_price_validator import (
    InvalidPrice,
    ValidationResult,
    check_price_in_range,
    load_tick_data,
    validate_trade_prices,
    generate_validation_report,
    save_validation_json,
)
from datetime import time


class TestTickPriceValidator(unittest.TestCase):
    """Test cases for tick price validator."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_check_price_in_range_valid(self):
        """Test price validation within range."""
        tick_data = [
            {'Time': '2018-03-15 09:25:00', 'Price': 59.00, 'Volume': 100},
            {'Time': '2018-03-15 09:26:00', 'Price': 59.10, 'Volume': 200},
            {'Time': '2018-03-15 09:27:00', 'Price': 59.05, 'Volume': 150},
        ]

        is_valid, tick_min, tick_max = check_price_in_range(59.05, tick_data)
        self.assertTrue(is_valid)
        self.assertEqual(tick_min, 59.00)
        self.assertEqual(tick_max, 59.10)

    def test_check_price_in_range_invalid_high(self):
        """Test price validation above range."""
        tick_data = [
            {'Time': '2018-03-15 09:25:00', 'Price': 59.00, 'Volume': 100},
            {'Time': '2018-03-15 09:26:00', 'Price': 59.10, 'Volume': 200},
        ]

        is_valid, tick_min, tick_max = check_price_in_range(60.00, tick_data)
        self.assertFalse(is_valid)
        self.assertEqual(tick_min, 59.00)
        self.assertEqual(tick_max, 59.10)

    def test_check_price_in_range_invalid_low(self):
        """Test price validation below range."""
        tick_data = [
            {'Time': '2018-03-15 09:25:00', 'Price': 59.00, 'Volume': 100},
            {'Time': '2018-03-15 09:26:00', 'Price': 59.10, 'Volume': 200},
        ]

        is_valid, tick_min, tick_max = check_price_in_range(58.00, tick_data)
        self.assertFalse(is_valid)

    def test_check_price_in_range_with_time_window(self):
        """Test price validation with time window filter."""
        tick_data = [
            {'Time': '2018-03-15 09:20:00', 'Price': 58.00, 'Volume': 100},
            {'Time': '2018-03-15 09:25:00', 'Price': 59.00, 'Volume': 100},
            {'Time': '2018-03-15 09:26:00', 'Price': 59.10, 'Volume': 200},
            {'Time': '2018-03-15 09:40:00', 'Price': 60.00, 'Volume': 150},
        ]

        time_window = (time(9, 25), time(9, 35))
        is_valid, tick_min, tick_max = check_price_in_range(
            59.05, tick_data, time_window
        )
        self.assertTrue(is_valid)
        self.assertEqual(tick_min, 59.00)
        self.assertEqual(tick_max, 59.10)

    def test_check_price_in_range_empty_data(self):
        """Test price validation with empty tick data."""
        is_valid, tick_min, tick_max = check_price_in_range(59.05, [])
        self.assertFalse(is_valid)
        self.assertEqual(tick_min, 0.0)
        self.assertEqual(tick_max, 0.0)

    def test_load_tick_data(self):
        """Test loading tick data from CSV file."""
        # Create a test tick file
        tick_file = self.temp_path / "tick_trade_300678_20180315.csv"
        with open(tick_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Time', 'Price', 'Volume'])
            writer.writerow(['2018-03-15 09:25:00', '59.05', '100'])
            writer.writerow(['2018-03-15 09:26:00', '59.10', '200'])

        tick_data = load_tick_data(self.temp_path, '300678', '2018-03-15')
        self.assertEqual(len(tick_data), 2)
        self.assertEqual(tick_data[0]['Price'], 59.05)
        self.assertEqual(tick_data[1]['Price'], 59.10)

    def test_load_tick_data_missing_file(self):
        """Test loading tick data when file doesn't exist."""
        tick_data = load_tick_data(self.temp_path, '999999', '2018-03-15')
        self.assertEqual(len(tick_data), 0)

    def test_validate_trade_prices(self):
        """Test full trade price validation workflow."""
        # Create tick data file
        tick_file = self.temp_path / "tick_trade_300678_20180315.csv"
        with open(tick_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Time', 'Price', 'Volume'])
            writer.writerow(['2018-03-15 09:25:00', '59.00', '100'])
            writer.writerow(['2018-03-15 09:26:00', '59.10', '200'])
            writer.writerow(['2018-03-15 10:00:00', '59.20', '150'])

        # Create trades CSV
        trades_file = self.temp_path / "trades.csv"
        with open(trades_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['code', 'entry_date', 'exit_date', 'entry_price', 'exit_price'])
            writer.writerow(['300678', '2018-03-15', '2018-03-15', '59.05', '59.15'])  # Valid
            writer.writerow(['300678', '2018-03-15', '2018-03-15', '60.00', '59.20'])  # Invalid entry

        result = validate_trade_prices(
            trades_csv=trades_file,
            tick_dir=self.temp_path,
        )

        self.assertEqual(result.total_trades, 2)
        self.assertEqual(result.valid_entry_prices, 1)
        self.assertEqual(result.valid_exit_prices, 2)
        self.assertEqual(len(result.invalid_entries), 1)
        self.assertEqual(result.invalid_entries[0].code, '300678')
        self.assertEqual(result.invalid_entries[0].strategy_price, 60.00)

    def test_validation_result_to_dict(self):
        """Test ValidationResult serialization."""
        result = ValidationResult(
            total_trades=10,
            valid_entry_prices=8,
            valid_exit_prices=9,
            invalid_entries=(
                InvalidPrice(
                    code='300678',
                    date='2018-03-15',
                    strategy_price=60.0,
                    tick_min=59.0,
                    tick_max=59.1,
                    deviation_pct=1.5,
                    price_type='entry',
                    time_window='09:25-09:35'
                ),
            ),
            invalid_exits=(),
            missing_tick_data=('300678_2018-03-16',),
            validation_rate=85.0
        )

        result_dict = result.to_dict()
        self.assertEqual(result_dict['total_trades'], 10)
        self.assertEqual(result_dict['valid_entry_prices'], 8)
        self.assertEqual(len(result_dict['invalid_entries']), 1)
        self.assertEqual(result_dict['invalid_entries'][0]['code'], '300678')

    def test_generate_validation_report(self):
        """Test markdown report generation."""
        result = ValidationResult(
            total_trades=5,
            valid_entry_prices=4,
            valid_exit_prices=5,
            invalid_entries=(
                InvalidPrice(
                    code='300678',
                    date='2018-03-15',
                    strategy_price=60.0,
                    tick_min=59.0,
                    tick_max=59.1,
                    deviation_pct=1.5,
                    price_type='entry',
                    time_window='09:25-09:35'
                ),
            ),
            invalid_exits=(),
            missing_tick_data=(),
            validation_rate=90.0
        )

        report_path = self.temp_path / "report.md"
        generate_validation_report(result, report_path)

        self.assertTrue(report_path.exists())
        content = report_path.read_text(encoding='utf-8')
        self.assertIn('# Tick Price Validation Report', content)
        self.assertIn('Total Trades', content)
        self.assertIn('300678', content)

    def test_save_validation_json(self):
        """Test JSON report saving."""
        result = ValidationResult(
            total_trades=5,
            valid_entry_prices=4,
            valid_exit_prices=5,
            invalid_entries=(),
            invalid_exits=(),
            missing_tick_data=(),
            validation_rate=90.0
        )

        json_path = self.temp_path / "report.json"
        save_validation_json(result, json_path)

        self.assertTrue(json_path.exists())
        import json
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data['total_trades'], 5)
        self.assertEqual(data['validation_rate'], 90.0)


if __name__ == '__main__':
    unittest.main()
