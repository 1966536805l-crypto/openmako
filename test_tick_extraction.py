#!/usr/bin/env python3
"""
Test script to extract tick data from T7 drive.

Usage:
    python3 test_tick_extraction.py [request_csv] [--limit N]
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from quantagent.tick_extractor import TickExtractor


def main():
    parser = argparse.ArgumentParser(description='Extract tick data from T7 drive')
    parser.add_argument(
        'request_csv',
        nargs='?',
        default='tick_data_request_test.csv',
        help='Path to request CSV file'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=5,
        help='Limit number of requests to process (default: 5)'
    )
    parser.add_argument(
        '--output-dir',
        default='/tmp/tick_cache',
        help='Output directory for extracted tick data'
    )

    args = parser.parse_args()

    # Check if request CSV exists
    request_path = Path(args.request_csv)
    if not request_path.exists():
        print(f"Error: Request CSV not found: {request_path}")
        return 1

    # Read and limit requests
    import csv
    with open(request_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        requests = list(reader)[:args.limit]

    if not requests:
        print("No requests to process")
        return 0

    # Create limited request file
    limited_csv = Path('/tmp/tick_request_limited.csv')
    with open(limited_csv, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['code', 'entry_date', 'start_time', 'end_time'])
        writer.writeheader()
        writer.writerows(requests)

    print(f"Processing {len(requests)} requests from {request_path}")
    print(f"Output directory: {args.output_dir}")
    print()

    # Extract tick data
    extractor = TickExtractor(cache_dir=args.output_dir)
    results = extractor.extract_tick_data(str(limited_csv), args.output_dir)

    # Print results
    print(f"\nExtraction complete. Processed {len(results)} requests:")
    for key, path in results.items():
        file_size = path.stat().st_size if path.exists() else 0
        print(f"  {key}: {path} ({file_size:,} bytes)")

    if len(results) < len(requests):
        print(f"\nWarning: {len(requests) - len(results)} requests failed")

    return 0


if __name__ == '__main__':
    sys.exit(main())
