#!/usr/bin/env python3
"""
將大型 Kaggle CSV 切成可供智慧藥盒 Django 網站匯入的小檔案。

預設限制：
- 每個分割檔最多 50,000 筆資料列
- 每個分割檔最多 20 MiB（網站上限為 25 MiB）
- 輸出 UTF-8 with BOM
- 保留 CSV 標題與正確引號／換行
- 新增 source_row_number，保留原始 CSV 的資料列位置

使用：
    python split_kaggle_csv.py "C:\\Users\\User\\Downloads\\medicine_dataset.csv"

只取前 10,000 筆真實資料作展示：
    python split_kaggle_csv.py "C:\\path\\medicine_dataset.csv" --max-total-rows 10000
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path
from typing import BinaryIO


def increase_csv_field_limit() -> None:
    """避免極長文字欄位觸發 csv.field_size_limit 錯誤。"""
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def encode_csv_row(
    writer: csv.DictWriter,
    buffer: io.StringIO,
    row: dict[str, object],
) -> bytes:
    buffer.seek(0)
    buffer.truncate(0)
    writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="切分大型 Kaggle CSV，輸出符合 Django 25 MiB／100,000 列限制的檔案。"
    )
    parser.add_argument(
        "csv_path",
        nargs="?",
        help="來源 CSV 完整路徑；未提供時會互動詢問。",
    )
    parser.add_argument(
        "--rows-per-file",
        type=int,
        default=50_000,
        help="每個輸出檔最多資料列數，預設 50000。",
    )
    parser.add_argument(
        "--max-mb",
        type=float,
        default=20.0,
        help="每個輸出檔最大 MiB，預設 20（網站上限是 25）。",
    )
    parser.add_argument(
        "--max-total-rows",
        type=int,
        default=None,
        help="只輸出前 N 筆真實資料；省略代表切分完整資料集。",
    )
    return parser.parse_args()


def normalize_path(value: str) -> Path:
    value = value.strip().strip('"').strip("'")
    return Path(value).expanduser().resolve()


def main() -> int:
    args = parse_args()

    raw_path = args.csv_path
    if not raw_path:
        raw_path = input("請貼上 Kaggle CSV 的完整路徑：\n> ")

    source_path = normalize_path(raw_path)

    if not source_path.exists():
        print(f"錯誤：找不到檔案：{source_path}", file=sys.stderr)
        return 1

    if not source_path.is_file() or source_path.suffix.lower() != ".csv":
        print("錯誤：來源必須是 .csv 檔案。", file=sys.stderr)
        return 1

    if args.rows_per_file < 1 or args.rows_per_file > 99_000:
        print("錯誤：--rows-per-file 必須介於 1 到 99000。", file=sys.stderr)
        return 1

    if args.max_mb <= 0 or args.max_mb >= 25:
        print("錯誤：--max-mb 必須大於 0 且小於 25。", file=sys.stderr)
        return 1

    if args.max_total_rows is not None and args.max_total_rows < 1:
        print("錯誤：--max-total-rows 必須大於 0。", file=sys.stderr)
        return 1

    increase_csv_field_limit()

    max_bytes = int(args.max_mb * 1024 * 1024)
    output_dir = source_path.with_name(f"{source_path.stem}_parts")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file: BinaryIO | None = None
    part_number = 0
    rows_in_part = 0
    total_rows = 0
    current_bytes = 0
    part_summaries: list[tuple[Path, int, int]] = []

    try:
        # errors="replace" 與目前 Django 匯入器的行為一致。
        with source_path.open(
            "r",
            encoding="utf-8-sig",
            errors="replace",
            newline="",
        ) as source:
            sample = source.read(65_536)
            source.seek(0)

            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel

            reader = csv.DictReader(source, dialect=dialect)
            if not reader.fieldnames:
                print("錯誤：CSV 第一列沒有欄位名稱。", file=sys.stderr)
                return 1

            original_fields = [
                field.strip() if field is not None else ""
                for field in reader.fieldnames
            ]
            if not all(original_fields):
                print("錯誤：CSV 含有空白欄位名稱。", file=sys.stderr)
                return 1

            source_row_field = "source_row_number"
            if source_row_field in original_fields:
                source_row_field = "original_source_row_number"

            output_fields = [*original_fields, source_row_field]

            row_buffer = io.StringIO(newline="")
            row_writer = csv.DictWriter(
                row_buffer,
                fieldnames=output_fields,
                extrasaction="ignore",
                lineterminator="\n",
            )

            header_data = encode_csv_row(
                row_writer,
                row_buffer,
                {field: field for field in output_fields},
            )
            bom = b"\xef\xbb\xbf"

            def close_part() -> None:
                nonlocal output_file, rows_in_part, current_bytes
                if output_file is None:
                    return
                path = Path(output_file.name)
                output_file.close()
                size = path.stat().st_size
                part_summaries.append((path, rows_in_part, size))
                print(
                    f"完成：{path.name}｜{rows_in_part:,} 筆｜"
                    f"{size / 1024 / 1024:.2f} MiB"
                )
                output_file = None
                rows_in_part = 0
                current_bytes = 0

            def open_part() -> None:
                nonlocal output_file, part_number, current_bytes
                part_number += 1
                output_path = output_dir / (
                    f"{source_path.stem}_part_{part_number:03d}.csv"
                )
                output_file = output_path.open("wb")
                output_file.write(bom)
                output_file.write(header_data)
                current_bytes = len(bom) + len(header_data)

            for source_row_number, raw_row in enumerate(reader, start=2):
                if (
                    args.max_total_rows is not None
                    and total_rows >= args.max_total_rows
                ):
                    break

                # csv.DictReader 在某些異常列可能產生 None key。
                row = {
                    str(key).strip(): ("" if value is None else value)
                    for key, value in raw_row.items()
                    if key is not None
                }
                row[source_row_field] = str(source_row_number)
                encoded_row = encode_csv_row(row_writer, row_buffer, row)

                if len(encoded_row) + len(bom) + len(header_data) > max_bytes:
                    print(
                        f"錯誤：來源第 {source_row_number} 列本身就超過 "
                        f"{args.max_mb:g} MiB，無法正常切分。",
                        file=sys.stderr,
                    )
                    return 1

                needs_new_part = (
                    output_file is None
                    or rows_in_part >= args.rows_per_file
                    or (
                        rows_in_part > 0
                        and current_bytes + len(encoded_row) > max_bytes
                    )
                )

                if needs_new_part:
                    close_part()
                    open_part()

                assert output_file is not None
                output_file.write(encoded_row)
                current_bytes += len(encoded_row)
                rows_in_part += 1
                total_rows += 1

        close_part()

    finally:
        if output_file is not None and not output_file.closed:
            output_file.close()

    if not part_summaries:
        print("錯誤：來源 CSV 沒有資料列。", file=sys.stderr)
        return 1

    print("\n切分完成")
    print(f"來源：{source_path}")
    print(f"輸出資料夾：{output_dir}")
    print(f"總資料列：{total_rows:,}")
    print(f"分割檔數：{len(part_summaries)}")
    print("\n請依 part_001、part_002、part_003 的順序逐一上傳到 Django。")

    invalid = [
        path
        for path, rows, size in part_summaries
        if rows > 100_000 or size > 25 * 1024 * 1024
    ]
    if invalid:
        print("警告：以下檔案仍超過網站限制：", file=sys.stderr)
        for path in invalid:
            print(f"- {path}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
