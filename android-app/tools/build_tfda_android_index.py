from __future__ import annotations

import argparse
import gzip
import json
import re
import zipfile
from pathlib import Path


FIELDS = ("許可證字號", "中文品名", "英文品名", "適應症", "用法用量", "主成分略述")


def clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with zipfile.ZipFile(args.archive) as source:
        name = next(item for item in source.namelist() if item.lower().endswith(".json"))
        records = json.loads(source.read(name).decode("utf-8-sig"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with gzip.open(args.output, "wt", encoding="utf-8", newline="\n") as output:
        for record in records:
            values = [clean(record.get(field)) for field in FIELDS]
            if not values[0] or not (values[1] or values[2]):
                continue
            output.write("\t".join(value.replace("\t", " ") for value in values) + "\n")
            written += 1
    print(f"wrote {written} TFDA records to {args.output}")


if __name__ == "__main__":
    main()
