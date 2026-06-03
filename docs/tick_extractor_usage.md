# Tick Data Extractor

Extract tick data from T7 drive compressed archives.

## Installation

Install required extraction tools:

```bash
# For macOS
brew install p7zip unar

# For Linux
sudo apt-get install p7zip-full unar
```

## Usage

### Python API

```python
from quantagent.tick_extractor import TickExtractor, extract_tick_data, get_tick_file_path

# Initialize extractor
extractor = TickExtractor(cache_dir="/tmp/tick_cache")

# Find archive path for a date
archive_path = extractor.get_tick_file_path("2022-01-04")
print(f"Archive: {archive_path}")

# Extract tick data from CSV request
results = extract_tick_data("tick_data_request.csv", output_dir="/tmp/tick_cache")
for key, path in results.items():
    print(f"{key}: {path}")
```

### Command Line

```bash
# Extract first 5 requests from CSV
python3 test_tick_extraction.py tick_data_request_test.csv --limit 5

# Extract all requests
python3 test_tick_extraction.py tick_data_request_all_695.csv --limit 695

# Custom output directory
python3 test_tick_extraction.py request.csv --output-dir /path/to/output
```

## Request CSV Format

The request CSV should have the following columns:

- `code`: Stock code (e.g., "000001", "300678")
- `entry_date`: Date in YYYY-MM-DD or YYYYMMDD format
- `start_time`: Optional start time filter (HH:MM:SS or HH:MM)
- `end_time`: Optional end time filter (HH:MM:SS or HH:MM)

Example:

```csv
code,entry_date,start_time,end_time
000001,2022-01-04,09:30:00,15:00:00
000002,2022-01-05,09:30:00,15:00:00
300678,2023-01-03,10:00:00,14:00:00
```

## T7 Drive Structure

The extractor expects the following directory structure on T7 drive:

### 2022 and earlier
```
/Volumes/T7/股票数据/下载/A股_逐笔成交/
  2022/
    202201/
      2022-01-04.rar
      2022-01-05.rar
      ...
```

### 2023 and later
```
/Volumes/T7/股票数据/Downloads/
  2023/
    202301/
      2023-01-03.7z
      2023-01-04.7z
      ...
```

## Features

- Automatic archive format detection (.rar for 2022, .7z for 2023+)
- Multiple extraction tool support (unrar, 7z, unar)
- Time range filtering for tick data
- Caching mechanism to avoid re-extraction
- Progress bar for batch extraction
- Robust error handling

## Output Format

Extracted tick data is saved as CSV files with naming pattern:
```
{code}_{YYYYMMDD}.csv
```

Example: `000001_20220104.csv`

The CSV contains filtered tick data with columns like:
- TranID
- Time
- Price
- Volume
- SaleOrderVolume
- BuyOrderVolume
- Type
- etc.

## Testing

Run unit tests:

```bash
python3 -m unittest tests.test_tick_extractor -v
```

## Notes

- Extraction requires T7 drive to be mounted at `/Volumes/T7/`
- Large archives may take several minutes to extract
- Extracted data is cached in `/tmp/tick_cache` by default
- Time filtering is applied after extraction to reduce output size
