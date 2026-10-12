# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""把 data/births_by_county.csv 整理成網頁可直接載入的 docs/data.js。

網頁用 <script src="data.js"> 載入（file:// 雙擊即可，不需伺服器），內容為：

    window.BIRTHS = {
      meta:   {...},                       // 來源、產生時間、欄位說明
      dims:   {year: [...], region: [...], county: [...], sex: [...],
               age: [...], nation: [...], edu: [...]},
      countyRegion: [...],                 // 第 i 個縣市所屬地區的代碼
      cols:   ["year", "county", "sex", "age", "nation", "edu", "births"],
      rows:   [[0, 3, 1, 2, 0, 4, 128], ...]  // 前 6 欄是 dims 的代碼，最後一欄是人數
    }

- 生母年齡併成 6 組，再依 (年, 縣市, 性別, 年齡組, 國籍, 教育程度) 加總
- 地區不放進 rows，由 countyRegion 從縣市推得

用法：uv run work/build_data.py
"""

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_PATH = ROOT / "data" / "births_by_county.csv"
OUT_PATH = ROOT / "docs" / "data.js"

REGIONS = {
    "北部": ["臺北市", "新北市", "基隆市", "桃園市", "新竹市", "新竹縣", "宜蘭縣"],
    "中部": ["苗栗縣", "臺中市", "彰化縣", "南投縣", "雲林縣"],
    "南部": ["嘉義市", "嘉義縣", "臺南市", "高雄市", "屏東縣"],
    "東部": ["花蓮縣", "臺東縣"],
    "離島": ["澎湖縣", "金門縣", "連江縣"],
}
AGE_GROUPS = {
    "未滿15歲": "未滿20歲", "15～19歲": "未滿20歲",
    "20～24歲": "20–24", "25～29歲": "25–29", "30～34歲": "30–34", "35～39歲": "35–39",
    "40～44歲": "40歲以上", "45～49歲": "40歲以上", "50歲以上": "40歲以上",
}
AGE_ORDER = ["未滿20歲", "20–24", "25–29", "30–34", "35–39", "40歲以上"]
SEX_ORDER = ["男", "女"]
NATION_ORDER = ["本國", "大陸地區", "港澳地區", "東南亞地區", "其他地區"]
EDU_ORDER = ["博士畢業", "碩士畢業", "大學畢業", "專科畢業", "高中畢業", "國中畢業", "國小畢業以下"]

EXPECTED_TOTALS = {113: 134856, 104: 213598}


def index_of(values: list[str], what: str):
    lookup = {v: i for i, v in enumerate(values)}

    def get(v: str) -> int:
        if v not in lookup:
            raise ValueError(f"未知的{what}：{v!r}")
        return lookup[v]

    return get


def build() -> dict:
    region_names = list(REGIONS)
    counties = [c for cs in REGIONS.values() for c in cs]
    county_region = [region_names.index(r) for r, cs in REGIONS.items() for _ in cs]

    with open(SRC_PATH, encoding="utf-8-sig", newline="") as f:
        src = list(csv.DictReader(f))
    years = sorted({int(r["year_roc"]) for r in src})

    year_i = index_of([str(y) for y in years], "年度")
    county_i = index_of(counties, "縣市")
    sex_i = index_of(SEX_ORDER, "性別")
    age_i = index_of(AGE_ORDER, "年齡組")
    nation_i = index_of(NATION_ORDER, "國籍")
    edu_i = index_of(EDU_ORDER, "教育程度")

    totals: dict[tuple, int] = defaultdict(int)
    for r in src:
        if r["mother_age"] not in AGE_GROUPS:
            raise ValueError(f"未知的生母年齡：{r['mother_age']!r}")
        key = (
            year_i(r["year_roc"]),
            county_i(r["county"]),
            sex_i(r["sex"]),
            age_i(AGE_GROUPS[r["mother_age"]]),
            nation_i(r["mother_nation"]),
            edu_i(r["mother_education"]),
        )
        totals[key] += int(r["births"])

    return {
        "meta": {
            "title": "嬰兒出生數按性別、生母原屬國籍（地區）、年齡及教育程度分（按登記）",
            "source": "https://data.gov.tw/dataset/32945",
            "provider": "內政部戶政司",
            "generated": datetime.now().isoformat(timespec="seconds"),
            "note": "year 為民國年；rows 前 6 欄為 dims 代碼，最後一欄為出生數",
        },
        "dims": {
            "year": years,
            "yearAD": [y + 1911 for y in years],
            "region": region_names,
            "county": counties,
            "sex": SEX_ORDER,
            "age": AGE_ORDER,
            "nation": NATION_ORDER,
            "edu": EDU_ORDER,
        },
        "countyRegion": county_region,
        "cols": ["year", "county", "sex", "age", "nation", "edu", "births"],
        "rows": [[*k, v] for k, v in sorted(totals.items())],
    }


def write(data: dict) -> None:
    # ensure_ascii：中文寫成 \uXXXX，不論瀏覽器用什麼編碼讀 data.js 都不會亂碼
    body = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
    body = body.replace("],[", "],\n[")  # 每列一行，方便 git diff，幾乎不增加大小
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(
        "// 由 work/build_data.py 產生，請勿手動修改\n"
        f"window.BIRTHS = {body};\n",
        encoding="utf-8",
        newline="\n",
    )


def check(path: Path) -> list[str]:
    """從寫出的 data.js 解析回來核對，確認網頁實際拿到的數字正確。"""
    text = path.read_text(encoding="utf-8")
    data = json.loads(text[text.index("{") : text.rindex("}") + 1])
    years = data["dims"]["year"]
    year_totals: dict[int, int] = defaultdict(int)
    for row in data["rows"]:
        year_totals[years[row[0]]] += row[-1]
    errors = []
    for y, expected in EXPECTED_TOTALS.items():
        got = year_totals.get(y)
        print(f"{y} 年全國合計：{got:,}（應為 {expected:,}）{'✓' if got == expected else '✗'}")
        if got != expected:
            errors.append(f"{y} 年合計 {got} ≠ {expected}")
    return errors


def main() -> int:
    data = build()
    write(data)
    print(f"→ {OUT_PATH.relative_to(ROOT)}：{len(data['rows']):,} 列，{OUT_PATH.stat().st_size / 1024:.0f} KB")
    errors = check(OUT_PATH)
    if errors:
        print("❌ " + "；".join(errors))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
