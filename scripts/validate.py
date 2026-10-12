# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""檢查 data/births_by_county.csv 與 raw/ 原始檔是否一致。

刻意只用標準函式庫（csv + gzip）直接加總原始檔，不共用 ETL 的程式碼，
避免 ETL 的錯誤在驗證時被同一段程式「抵銷」。

用法：uv run scripts/validate.py
"""

import csv
import gzip
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "raw"
OUT_PATH = ROOT / "data" / "births_by_county.csv"

EXPECTED_113_TOTAL = 134856
COUNTIES = {
    "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市",
    "基隆市", "新竹市", "嘉義市",
    "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義縣",
    "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣", "澎湖縣", "金門縣", "連江縣",
}
BIRTH_COLS = ("嬰兒出生數", "birth_count")


def raw_totals() -> dict[int, int]:
    """直接加總每個原始檔的出生數欄位，年度取自檔名。"""
    totals = {}
    for path in sorted(RAW_DIR.glob("births_*.csv.gz")):
        year = int(path.name.removeprefix("births_").removesuffix(".csv.gz"))
        with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            col = next(c for c in reader.fieldnames if c.lstrip("﻿") in BIRTH_COLS)
            totals[year] = sum(int(row[col]) for row in reader)
    return totals


def main() -> int:
    errors: list[str] = []

    if not OUT_PATH.read_bytes().startswith(b"\xef\xbb\xbf"):
        errors.append("輸出檔不是 UTF-8 with BOM")

    out_totals: dict[int, int] = defaultdict(int)
    counties: dict[int, set[str]] = defaultdict(set)
    ages: set[str] = set()
    with open(OUT_PATH, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            y, n = int(row["year_roc"]), int(row["births"])
            if int(row["year"]) != y + 1911:
                errors.append(f"西元年錯誤：{row}")
            if n <= 0:
                errors.append(f"出現出生數 ≤ 0 的列：{row}")
            out_totals[y] += n
            counties[y].add(row["county"])
            ages.add(row["mother_age"])

    # 1. 每年全國合計 = 原始檔直接加總
    raw = raw_totals()
    print(f"{'年度':>4}  {'原始檔加總':>10}  {'整理後合計':>10}")
    for y in sorted(raw.keys() | out_totals.keys()):
        r, o = raw.get(y), out_totals.get(y)
        mark = "✓" if r == o else "✗"
        print(f"{y:>4}  {r if r is not None else '—':>10,}  {o if o is not None else '—':>10,}  {mark}")
        if r != o:
            errors.append(f"{y} 年合計不符：原始 {r}，整理後 {o}")

    # 2. 113 年全國合計
    if out_totals.get(113) != EXPECTED_113_TOTAL:
        errors.append(f"113 年合計應為 {EXPECTED_113_TOTAL:,}，實際 {out_totals.get(113)}")

    # 3. 22 個縣市每年都有資料
    for y in sorted(counties):
        missing, extra = COUNTIES - counties[y], counties[y] - COUNTIES
        if missing or extra:
            errors.append(f"{y} 年縣市不符：缺少 {sorted(missing)}，多出 {sorted(extra)}")
    print(f"\n縣市：每年 {sorted({len(c) for c in counties.values()})} 個")

    # 附加：生母年齡寫法已統一
    bad_ages = sorted(a for a in ages if "~" in a or " " in a)
    if bad_ages:
        errors.append(f"生母年齡寫法未統一：{bad_ages}")
    print(f"生母年齡類別：{sorted(ages)}")

    if errors:
        print("\n❌ 檢查未通過：")
        for e in errors:
            print("  -", e)
        return 1
    print("\n🎉 全部通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
