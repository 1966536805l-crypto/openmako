"""
Tick data extractor from T7 drive.

Extracts tick data from compressed archives on T7 drive based on CSV requests.
Supports both .rar (2022) and .7z (2023+) formats with caching mechanism.
"""

import csv
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from tqdm import tqdm
except ImportError:
    # Fallback if tqdm not available
    class tqdm:
        def __init__(self, iterable=None, total=None, desc=None, **kwargs):
            self.iterable = iterable
            self.total = total
            self.desc = desc
            self.n = 0

        def __iter__(self):
            return iter(self.iterable)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def update(self, n=1):
            self.n += n


class TickExtractor:
    """Extract tick data from T7 drive compressed archives."""

    # T7 drive paths for different years
    T7_BASE_2022 = "/Volumes/T7/股票数据/下载/A股_逐笔成交"
    T7_BASE_2023 = "/Volumes/T7/股票数据/Downloads"

    def __init__(self, cache_dir: str = "/tmp/tick_cache"):
        """
        Initialize tick extractor.

        Args:
            cache_dir: Directory to cache extracted tick data
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_tick_file_path(self, date: str) -> Optional[Path]:
        """
        Locate the compressed archive path on T7 drive for a given date.

        Args:
            date: Date string in format YYYY-MM-DD or YYYYMMDD

        Returns:
            Path to the compressed archive, or None if not found
        """
        # Normalize date format
        if len(date) == 8 and date.isdigit():
            # YYYYMMDD -> YYYY-MM-DD
            date = f"{date[:4]}-{date[4:6]}-{date[6:]}"

        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return None

        year = dt.year
        year_month = dt.strftime("%Y%m")

        # Determine base path and file extension based on year
        if year == 2022:
            base_path = Path(self.T7_BASE_2022) / str(year) / year_month
            # 2022 uses mixed .rar and .7z
            rar_file = base_path / f"{date}.rar"
            z7_file = base_path / f"{date}.7z"

            if rar_file.exists():
                return rar_file
            elif z7_file.exists():
                return z7_file
        elif year >= 2023:
            base_path = Path(self.T7_BASE_2023) / str(year) / year_month
            z7_file = base_path / f"{date}.7z"

            if z7_file.exists():
                return z7_file
        else:
            # For years before 2022, check the old structure
            base_path = Path(self.T7_BASE_2022) / str(year) / year_month
            rar_file = base_path / f"{date}.rar"

            if rar_file.exists():
                return rar_file

        return None

    def extract_archive(self, archive_path: Path, extract_dir: Path) -> bool:
        """
        Extract compressed archive to directory.

        Args:
            archive_path: Path to .rar or .7z file
            extract_dir: Directory to extract to

        Returns:
            True if extraction successful, False otherwise
        """
        extract_dir.mkdir(parents=True, exist_ok=True)

        suffix = archive_path.suffix.lower()

        try:
            if suffix == ".rar":
                # Try multiple unrar commands in order of preference
                commands = [
                    ["unrar", "x", "-o+", str(archive_path), str(extract_dir)],
                    ["unar", "-o", str(extract_dir), str(archive_path)],
                    # macOS ditto can handle some rar files
                    ["ditto", "-xk", str(archive_path), str(extract_dir)],
                ]

                for cmd in commands:
                    try:
                        result = subprocess.run(
                            cmd,
                            capture_output=True,
                            text=True,
                            timeout=300
                        )
                        if result.returncode == 0:
                            return True
                    except FileNotFoundError:
                        continue

                print(f"No suitable unrar tool found. Install with: brew install unar")
                return False

            elif suffix == ".7z":
                # Try multiple 7z commands
                commands = [
                    ["7z", "x", f"-o{extract_dir}", str(archive_path), "-y"],
                    ["7za", "x", f"-o{extract_dir}", str(archive_path), "-y"],
                    ["unar", "-o", str(extract_dir), str(archive_path)],
                ]

                for cmd in commands:
                    try:
                        result = subprocess.run(
                            cmd,
                            capture_output=True,
                            text=True,
                            timeout=300
                        )
                        if result.returncode == 0:
                            return True
                    except FileNotFoundError:
                        continue

                print(f"No suitable 7z tool found. Install with: brew install p7zip")
                return False
            else:
                return False

        except subprocess.TimeoutExpired as e:
            print(f"Extraction timeout for {archive_path}: {e}")
            return False

    def find_tick_csv(self, extract_dir: Path, code: str) -> Optional[Path]:
        """
        Find the tick CSV file for a specific stock code in extracted directory.

        Args:
            extract_dir: Directory containing extracted files
            code: Stock code (e.g., '000001', '300678')

        Returns:
            Path to the tick CSV file, or None if not found
        """
        # Common patterns for tick data files
        patterns = [
            f"*{code}*.csv",
            f"tick*{code}*.csv",
            f"{code}.csv",
        ]

        for pattern in patterns:
            matches = list(extract_dir.rglob(pattern))
            if matches:
                return matches[0]

        return None

    def filter_tick_data(
        self,
        csv_path: Path,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None
    ) -> List[List[str]]:
        """
        Read and filter tick data by time range.

        Args:
            csv_path: Path to tick CSV file
            start_time: Start time filter (HH:MM:SS or HH:MM)
            end_time: End time filter (HH:MM:SS or HH:MM)

        Returns:
            List of filtered rows (including header)
        """
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)

        if not rows:
            return []

        # Keep header
        header = rows[0]
        data_rows = rows[1:]

        # If no time filter, return all
        if not start_time and not end_time:
            return rows

        # Find time column (usually 'Time' or second column)
        time_col_idx = None
        for idx, col in enumerate(header):
            if 'time' in col.lower():
                time_col_idx = idx
                break

        if time_col_idx is None and len(header) > 1:
            time_col_idx = 1  # Default to second column

        if time_col_idx is None:
            return rows

        # Filter by time
        filtered = [header]
        for row in data_rows:
            if len(row) <= time_col_idx:
                continue

            time_str = row[time_col_idx]
            # Extract time part (format: "YYYY-MM-DD HH:MM:SS" or "HH:MM:SS")
            if ' ' in time_str:
                time_part = time_str.split(' ', 1)[1]
            else:
                time_part = time_str

            # Normalize to HH:MM:SS
            if len(time_part) == 5:  # HH:MM
                time_part = time_part + ":00"

            # Check time range
            if start_time and time_part < start_time:
                continue
            if end_time and time_part > end_time:
                continue

            filtered.append(row)

        return filtered

    def extract_tick_data(
        self,
        request_csv: str,
        output_dir: Optional[str] = None
    ) -> Dict[str, Path]:
        """
        Extract tick data based on CSV request file.

        Args:
            request_csv: Path to CSV file with columns: code, entry_date, start_time, end_time
            output_dir: Directory to save extracted tick data (default: cache_dir)

        Returns:
            Dictionary mapping request key to output CSV path
        """
        if output_dir is None:
            output_dir = str(self.cache_dir)

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Read request CSV
        with open(request_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            requests = list(reader)

        results = {}

        # Process each request with progress bar
        for req in tqdm(requests, desc="Extracting tick data"):
            code = req.get('code', '').strip()
            entry_date = req.get('entry_date', '').strip()
            start_time = req.get('start_time', '').strip() or None
            end_time = req.get('end_time', '').strip() or None

            if not code or not entry_date:
                continue

            # Generate output filename
            output_file = output_path / f"{code}_{entry_date.replace('-', '')}.csv"
            request_key = f"{code}_{entry_date}"

            # Check cache
            if output_file.exists():
                results[request_key] = output_file
                continue

            # Locate archive on T7
            archive_path = self.get_tick_file_path(entry_date)
            if not archive_path:
                print(f"Archive not found for {entry_date}")
                continue

            # Extract to temporary directory
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                # Extract archive
                if not self.extract_archive(archive_path, temp_path):
                    print(f"Failed to extract {archive_path}")
                    continue

                # Find tick CSV for this code
                tick_csv = self.find_tick_csv(temp_path, code)
                if not tick_csv:
                    print(f"Tick data not found for {code} in {archive_path}")
                    continue

                # Filter by time range
                filtered_data = self.filter_tick_data(tick_csv, start_time, end_time)

                # Write to output
                with open(output_file, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerows(filtered_data)

                results[request_key] = output_file

        return results


def extract_tick_data(request_csv: str, output_dir: Optional[str] = None) -> Dict[str, Path]:
    """
    Convenience function to extract tick data.

    Args:
        request_csv: Path to CSV file with columns: code, entry_date, start_time, end_time
        output_dir: Directory to save extracted tick data (default: /tmp/tick_cache)

    Returns:
        Dictionary mapping request key to output CSV path
    """
    extractor = TickExtractor()
    return extractor.extract_tick_data(request_csv, output_dir)


def get_tick_file_path(code: str, date: str) -> Optional[Path]:
    """
    Convenience function to find tick file path on T7 drive.

    Args:
        code: Stock code (not used for locating archive, but kept for API consistency)
        date: Date string in format YYYY-MM-DD or YYYYMMDD

    Returns:
        Path to the compressed archive, or None if not found
    """
    extractor = TickExtractor()
    return extractor.get_tick_file_path(date)
