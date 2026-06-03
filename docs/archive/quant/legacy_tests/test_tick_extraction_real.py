#!/usr/bin/env python3
"""
测试真实tick数据提取和验证

Archived quant demo script. This is not part of the focused OpenMako v0.1
public evidence gate.
"""
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from quantagent.tick_extractor import TickExtractor

def main():
    # 读取tick请求文件的前5条
    request_file = Path.home() / "Desktop/智能动态仓位系统/AI_协作交接_DISABLED_MEMORY_20260526_2039/tick_data_request_all_695.csv"

    if not request_file.exists():
        print(f"❌ Request file not found: {request_file}")
        return 1

    print(f"📄 Reading request file: {request_file}")

    # 读取前5条
    import csv
    requests = []
    with open(request_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i >= 5:
                break
            requests.append(row)

    print(f"✅ Found {len(requests)} requests to process\n")

    # 创建提取器
    output_dir = Path("/tmp/tick_cache_test")
    output_dir.mkdir(parents=True, exist_ok=True)

    extractor = TickExtractor(output_dir=output_dir)

    # 逐个提取
    for i, req in enumerate(requests, 1):
        code = req['code']
        entry_date = req['entry_date']  # YYYYMMDD格式
        start_time = req.get('start_time', '09:25:00')
        end_time = req.get('end_time', '09:35:00')

        print(f"\n[{i}/5] Processing: {code} on {entry_date}")
        print(f"  Time window: {start_time} - {end_time}")

        # 定位tick文件
        tick_path = extractor.get_tick_file_path(entry_date)

        if not tick_path or not tick_path.exists():
            print(f"  ❌ Tick file not found: {tick_path}")
            continue

        print(f"  ✅ Found tick file: {tick_path}")
        print(f"  📦 Size: {tick_path.stat().st_size / 1024 / 1024:.1f} MB")

        # 提取tick数据
        try:
            output_path = extractor.extract_tick_data(
                code=code,
                date=entry_date,
                start_time=start_time,
                end_time=end_time
            )

            if output_path and output_path.exists():
                # 统计行数
                with open(output_path, 'r') as f:
                    lines = sum(1 for _ in f) - 1  # 减去header
                print(f"  ✅ Extracted {lines} tick rows to: {output_path.name}")
            else:
                print(f"  ⚠️  No tick data extracted")

        except Exception as e:
            print(f"  ❌ Extraction failed: {e}")

    print(f"\n{'='*60}")
    print(f"✅ Test completed. Output directory: {output_dir}")
    print(f"{'='*60}")

    return 0

if __name__ == "__main__":
    sys.exit(main())
