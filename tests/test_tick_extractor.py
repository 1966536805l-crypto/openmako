"""
Test tick_extractor module.
"""

import csv
import tempfile
import unittest
from pathlib import Path

from quantagent.tick_extractor import TickExtractor, extract_tick_data, get_tick_file_path


class TestTickExtractor(unittest.TestCase):
    """Test TickExtractor class."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.extractor = TickExtractor(cache_dir=self.temp_dir)

    def test_get_tick_file_path_2022(self):
        """Test locating 2022 tick file path."""
        # Test with YYYY-MM-DD format
        path = self.extractor.get_tick_file_path("2022-01-04")
        if path:
            self.assertTrue(path.exists())
            self.assertIn("2022-01-04", str(path))

    def test_get_tick_file_path_2023(self):
        """Test locating 2023 tick file path."""
        # Test with YYYYMMDD format
        path = self.extractor.get_tick_file_path("20230103")
        if path:
            self.assertTrue(path.exists())
            self.assertIn("2023-01-03", str(path))

    def test_get_tick_file_path_invalid(self):
        """Test with invalid date."""
        path = self.extractor.get_tick_file_path("invalid-date")
        self.assertIsNone(path)

    def test_filter_tick_data(self):
        """Test filtering tick data by time range."""
        # Create sample CSV
        sample_csv = Path(self.temp_dir) / "sample_tick.csv"
        with open(sample_csv, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['TranID', 'Time', 'Price', 'Volume'])
            writer.writerow(['1', '2022-01-04 09:30:00', '10.5', '100'])
            writer.writerow(['2', '2022-01-04 10:00:00', '10.6', '200'])
            writer.writerow(['3', '2022-01-04 14:00:00', '10.7', '150'])
            writer.writerow(['4', '2022-01-04 15:00:00', '10.8', '300'])

        # Filter without time range
        result = self.extractor.filter_tick_data(sample_csv)
        self.assertEqual(len(result), 5)  # header + 4 rows

        # Filter with start time
        result = self.extractor.filter_tick_data(sample_csv, start_time="10:00:00")
        self.assertEqual(len(result), 4)  # header + 3 rows

        # Filter with end time
        result = self.extractor.filter_tick_data(sample_csv, end_time="14:00:00")
        self.assertEqual(len(result), 4)  # header + 3 rows

        # Filter with both
        result = self.extractor.filter_tick_data(
            sample_csv, start_time="10:00:00", end_time="14:00:00"
        )
        self.assertEqual(len(result), 3)  # header + 2 rows

    def test_convenience_functions(self):
        """Test convenience functions."""
        # Test get_tick_file_path
        path = get_tick_file_path("000001", "2022-01-04")
        if path:
            self.assertTrue(path.exists())

        # Test extract_tick_data with empty request
        request_csv = Path(self.temp_dir) / "request.csv"
        with open(request_csv, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['code', 'entry_date', 'start_time', 'end_time'])

        results = extract_tick_data(str(request_csv), self.temp_dir)
        self.assertEqual(len(results), 0)


if __name__ == '__main__':
    unittest.main()
