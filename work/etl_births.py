# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pandas>=2.2",
# ]
# ///
"""把 raw/births_*.csv.gz 整理成 data/births_by_county.csv（UTF-8 with BOM）。

輸出欄位：year_roc, year, county, sex, mother_age, mother_nation, mother_education, births
- county：區域別的縣市部分（「新北市板橋區」→「新北市」），「台」統一為「臺」
- mother_age：「~」統一為「～」，並去掉空白（104–107 年寫成「15 ~ 19 歲」）
- 去掉出生數為 0 的列後，依上述欄位加總
- 只讀 raw/，不修改原始檔；不讀 sample_*.csv

用法：uv run work/etl_births.py
"""

import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "raw"
OUT_PATH = ROOT / "data" / "births_by_county.csv"

# 原始欄位（中文 / 英文）→ 輸出欄位
COLUMN_MAP = {
    "統計年度": "year_roc", "statistic_yyy": "year_roc",
    "按照別": "according", "according": "according",
    "區域別": "site_id", "site_id": "site_id",
    "出生者性別": "sex", "birth_sex": "sex",
    "生母原屬國籍或地區": "mother_nation", "mother_nation": "mother_nation",
    "生母年齡": "mother_age", "mother_age": "mother_age",
    "生母教育程度": "mother_education", "mother_education": "mother_education",
    "嬰兒出生數": "births", "birth_count": "births",
}
KEYS = ["year_roc", "year", "county", "sex", "mother_age", "mother_nation", "mother_education"]
COUNTY_RE = re.compile(r"^(..[縣市])")


def raw_files() -> list[Path]:
    return sorted(RAW_DIR.glob("births_*.csv.gz"))


def load_raw(path: Path) -> pd.DataFrame:
    """讀一個年度的原始檔，欄位名稱統一成英文代號。"""
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    df.columns = [c.strip().lstrip("﻿") for c in df.columns]
    unknown = set(df.columns) - COLUMN_MAP.keys()
    if unknown:
        raise ValueError(f"{path.name} 有無法辨識的欄位：{sorted(unknown)}")
    return df.rename(columns=COLUMN_MAP)


def to_county(site: str) -> str:
    site = site.strip().replace("台", "臺")
    m = COUNTY_RE.match(site)
    if not m:
        raise ValueError(f"無法從區域別取出縣市：{site!r}")
    return m.group(1)


def normalize_age(age: str) -> str:
    return re.sub(r"\s+", "", age).replace("~", "～")


def transform(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({
        "year_roc": df["year_roc"].str.strip().astype(int),
        "county": df["site_id"].map(to_county),
        "sex": df["sex"].str.strip(),
        "mother_age": df["mother_age"].map(normalize_age),
        "mother_nation": df["mother_nation"].str.strip(),
        "mother_education": df["mother_education"].str.strip(),
        "births": pd.to_numeric(df["births"].str.strip(), errors="raise").astype(int),
    })
    out["year"] = out["year_roc"] + 1911
    out = out[out["births"] != 0]
    return out.groupby(KEYS, as_index=False)["births"].sum()


def main() -> int:
    files = raw_files()
    if not files:
        print("raw/ 找不到 births_*.csv.gz", file=sys.stderr)
        return 1
    parts = []
    for path in files:
        part = transform(load_raw(path))
        print(f"{path.name}: {len(part):,} 列，出生數 {part['births'].sum():,}")
        parts.append(part)
    result = (
        pd.concat(parts, ignore_index=True)
        .groupby(KEYS, as_index=False)["births"].sum()
        .sort_values(KEYS, ignore_index=True)
    )[KEYS + ["births"]]
    OUT_PATH.parent.mkdir(exist_ok=True)
    result.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"→ {OUT_PATH.relative_to(ROOT)}：{len(result):,} 列")
    return 0


if __name__ == "__main__":
    sys.exit(main())
