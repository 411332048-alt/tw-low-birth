# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "requests>=2.32",
# ]
# ///
"""下載「嬰兒出生數按性別、生母原屬國籍（地區）、年齡及教育程度分（按登記）」各年度原始資料。

1. 先從 data.gov.tw 資料集 32945 的 metadata 取得每年 CSV 的下載連結。
2. 沒有 CSV 可用的年度，改用戶政司 API（ODRP028）逐頁抓取後合併成 CSV。

原始檔保持原樣（不改欄位名稱），下載後以 gzip 壓縮成 raw/births_{民國年}.csv.gz，
確認解壓後與原檔逐位元組相同才刪除未壓縮檔。另外產生未壓縮的樣本
raw/sample_births_113.csv（標題列 + 前 2000 筆資料）與 raw/README.md。

用法：
    uv run scripts/download.py                  # 下載 + 壓縮 + 產生樣本與 README
    uv run scripts/download.py --skip-download  # 只壓縮 raw/ 裡現有的 CSV、重建樣本與 README
"""

import csv
import gzip
import io
import re
import sys
import time
import zipfile
from datetime import date
from pathlib import Path

import requests

DATASET_META_URL = "https://data.gov.tw/api/v2/rest/dataset/32945"
RIS_API_URL = "https://www.ris.gov.tw/rs-opendata/api/v1/datastore/ODRP028/{year}"
RAW_DIR = Path(__file__).resolve().parent.parent / "raw"
FIRST_YEAR = 90  # 最早嘗試的民國年，API 回「查無資料」就跳過
CURRENT_YEAR = date.today().year - 1911
FILE_LIMIT_MB = 50  # 單一檔案上限
SAMPLE_YEAR = 113
SAMPLE_ROWS = 2000

RIS_INTERVAL = 1  # 戶政司 API 每次請求間隔（秒）
RIS_RETRY_WAIT = 10  # 失敗後等待秒數
RIS_MAX_RETRIES = 5

session = requests.Session()
session.headers["User-Agent"] = "tw-low-birth-bi-homework/1.0"


def year_of_csv(content: bytes) -> int | None:
    """從 CSV 內容第一筆資料的「統計年度」判斷年度；不是有效 CSV 則回傳 None。"""
    head = b"\n".join(content.split(b"\n", 2)[:2])  # 標題列 + 第一筆
    try:
        text = head.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 2 or not rows[1] or not rows[1][0].strip().isdigit():
        return None
    return int(rows[1][0])


def unzip_csv(content: bytes) -> bytes | None:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        return zf.read(names[0]) if len(names) == 1 else None


def download_from_datagov() -> set[int]:
    """下載 data.gov.tw 上列出的各年度 CSV，回傳成功取得的年度。"""
    meta = session.get(DATASET_META_URL, timeout=60).json()["result"]
    resources = [r for r in meta["distribution"] if r["resourceFormat"] == "CSV"]
    # 直接 CSV 優先於 zip（112 年同時有兩種）
    resources.sort(key=lambda r: r["resourceDownloadUrl"].lower().endswith(".zip"))

    done: set[int] = set()
    for r in resources:
        url = r["resourceDownloadUrl"]
        label = re.match(r"\d+", r["resourceDescription"])
        label_year = int(label.group()) if label else None
        if label_year in done:
            print(f"[data.gov.tw] {label_year} 已取得，略過重複資源 {url}")
            continue
        try:
            resp = session.get(url, timeout=300)
            resp.raise_for_status()
            content = resp.content
            if content[:2] == b"PK":
                content = unzip_csv(content)
                if content is None:
                    raise ValueError("zip 內找不到唯一的 CSV")
        except (requests.RequestException, ValueError, zipfile.BadZipFile) as e:
            print(f"[data.gov.tw] 標示 {label_year} 年下載失敗：{e}")
            continue

        # 以檔案內容的「統計年度」為準，避免資源描述標錯年
        year = year_of_csv(content)
        if year is None:
            print(f"[data.gov.tw] 標示 {label_year} 年的檔案不是有效 CSV，略過")
            continue
        if label_year is not None and year != label_year:
            print(f"[data.gov.tw] 注意：資源標示 {label_year} 年，內容實為 {year} 年")
        if year in done:
            print(f"[data.gov.tw] {year} 已取得，略過重複資源")
            continue
        (RAW_DIR / f"births_{year}.csv").write_bytes(content)
        done.add(year)
        print(f"[data.gov.tw] {year} 年 OK（{len(content) / 1e6:.1f} MB）")
    return done


_last_ris_request = 0.0


def ris_get(year: int, page: int) -> dict:
    """呼叫戶政司 API：一次一個請求、間隔 1 秒，失敗等 10 秒重試。"""
    global _last_ris_request
    url = RIS_API_URL.format(year=year)
    for attempt in range(1, RIS_MAX_RETRIES + 1):
        wait = RIS_INTERVAL - (time.monotonic() - _last_ris_request)
        if wait > 0:
            time.sleep(wait)
        _last_ris_request = time.monotonic()
        try:
            resp = session.get(url, params={"page": page}, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            msg = data.get("responseMessage", "")
            if "查無資料" in msg:
                return data
            if "responseData" not in data:  # 例如「連線數已達上限」
                raise RuntimeError(msg or "回應缺少 responseData")
            return data
        except (requests.RequestException, ValueError, RuntimeError) as e:
            print(f"  [API] {year} 第 {page} 頁失敗（第 {attempt} 次）：{e}；{RIS_RETRY_WAIT} 秒後重試")
            time.sleep(RIS_RETRY_WAIT)
    raise RuntimeError(f"{year} 第 {page} 頁重試 {RIS_MAX_RETRIES} 次仍失敗")


def download_from_ris(year: int) -> bool:
    first = ris_get(year, 1)
    if "responseData" not in first:
        print(f"[API] {year} 年：{first.get('responseMessage')}")
        return False
    total_pages = int(first["totalPage"])
    rows = list(first["responseData"])
    for page in range(2, total_pages + 1):
        rows.extend(ris_get(year, page)["responseData"])
        print(f"  [API] {year} 年 {page}/{total_pages} 頁", end="\r")

    expected = int(first["totalDataSize"])
    if len(rows) != expected:
        print(f"[API] 警告：{year} 年取得 {len(rows)} 筆，API 標示 {expected} 筆")
    fieldnames = list(rows[0].keys())  # 欄位名稱保持 API 原樣
    with open(RAW_DIR / f"births_{year}.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[API] {year} 年 OK（{total_pages} 頁，{len(rows)} 筆）")
    return True


def compress_csv(src: Path) -> Path:
    """把 CSV 壓成 .csv.gz，確認解壓後與原檔完全相同，再刪除原檔。"""
    original = src.read_bytes()
    dst = src.with_suffix(".csv.gz")
    # mtime=0 讓同樣內容每次壓出相同位元組，重跑不會在 git 產生無意義的差異
    dst.write_bytes(gzip.compress(original, compresslevel=9, mtime=0))
    if gzip.decompress(dst.read_bytes()) != original:
        dst.unlink()
        raise RuntimeError(f"{dst.name} 解壓後與原檔不符，保留 {src.name}")
    src.unlink()
    print(f"[gzip] {src.name} → {dst.name}（{len(original) / 1e6:.1f} → {dst.stat().st_size / 1e6:.1f} MB）")
    return dst


def count_rows(content: bytes) -> int:
    """資料列數（不含標題列）。"""
    return sum(1 for _ in csv.reader(io.StringIO(content.decode("utf-8-sig")))) - 1


def write_sample(year: int = SAMPLE_YEAR, n_rows: int = SAMPLE_ROWS) -> Path:
    """原封不動擷取標題列 + 前 n_rows 筆資料（保留 BOM 與 CRLF）。"""
    content = gzip.decompress((RAW_DIR / f"births_{year}.csv.gz").read_bytes())
    lines = content.splitlines(keepends=True)[: n_rows + 1]
    dst = RAW_DIR / f"sample_births_{year}.csv"
    dst.write_bytes(b"".join(lines))
    return dst


def write_readme(row_counts: dict[int, int]) -> None:
    years = sorted(row_counts)
    table = "\n".join(
        f"| `births_{y}.csv.gz` | {y}（{y + 1911}） | {row_counts[y]:,} |" for y in years
    )
    text = f"""# raw/ 原始資料

**資料來源**：政府資料開放平臺「嬰兒出生數按性別、生母原屬國籍（地區）、年齡及教育程度分（按登記）」，內政部戶政司提供
<https://data.gov.tw/dataset/32945>

由 `scripts/download.py` 下載，內容未經任何修改（欄位名稱、編碼 UTF-8 with BOM、CRLF 換行皆為原樣），只以 gzip 壓縮以符合 repo 檔案大小限制。

## 檔案

| 檔案 | 民國年（西元） | 原始列數（不含標題列） |
|---|---|---|
{table}
| `sample_births_{SAMPLE_YEAR}.csv` | {SAMPLE_YEAR}（{SAMPLE_YEAR + 1911}） | {SAMPLE_ROWS:,}（樣本） |

`sample_births_{SAMPLE_YEAR}.csv` **只是樣本**：`births_{SAMPLE_YEAR}.csv.gz` 原檔的標題列加前 {SAMPLE_ROWS:,} 筆資料，原封不動未壓縮，方便直接打開查看原始格式。分析請用完整的 `.csv.gz`。

## 解壓縮

命令列（Git Bash / macOS / Linux）：

```sh
gunzip -k raw/births_113.csv.gz   # -k 保留 .gz，產生 births_113.csv
```

Windows 可用 7-Zip 解壓。程式不需要先解壓，可直接讀 `.csv.gz`：

```python
import pandas as pd
df = pd.read_csv("raw/births_113.csv.gz", encoding="utf-8-sig")  # 依副檔名自動解壓
```

```python
import csv, gzip
with gzip.open("raw/births_113.csv.gz", "rt", encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))
```
"""
    (RAW_DIR / "README.md").write_text(text, encoding="utf-8", newline="\n")


def finalize() -> None:
    """壓縮所有未壓縮的年度 CSV，產生樣本與 README，並列出摘要。"""
    for src in sorted(RAW_DIR.glob("births_*.csv")):
        compress_csv(src)

    files = sorted(RAW_DIR.glob("births_*.csv.gz"), key=lambda p: int(p.name.split("_")[1].split(".")[0]))
    row_counts: dict[int, int] = {}
    print(f"\n{'年度':>4}  {'列數':>8}  {'壓縮後':>8}  檔案")
    for p in files:
        year = int(p.name.split("_")[1].split(".")[0])
        row_counts[year] = count_rows(gzip.decompress(p.read_bytes()))
        print(f"{year:>4}  {row_counts[year]:>8,}  {p.stat().st_size / 1e6:>5.1f} MB  {p.name}")

    if SAMPLE_YEAR in row_counts:
        write_sample()
    write_readme(row_counts)

    all_files = [p for p in RAW_DIR.iterdir() if p.is_file()]
    total = sum(p.stat().st_size for p in all_files)
    print(f"raw/ 共 {len(all_files)} 個檔案，總計 {total / 1e6:.1f} MB")
    too_big = [p.name for p in all_files if p.stat().st_size > FILE_LIMIT_MB * 1e6]
    if too_big:
        print(f"⚠ 以下檔案超過 {FILE_LIMIT_MB} MB：{too_big}")


def main() -> int:
    RAW_DIR.mkdir(exist_ok=True)
    if "--skip-download" not in sys.argv[1:]:
        done = download_from_datagov()
        missing = [y for y in range(FIRST_YEAR, CURRENT_YEAR + 1) if y not in done]
        print(f"\ndata.gov.tw 取得：{sorted(done)}；改用 API 嘗試：{missing}")
        for year in missing:
            if download_from_ris(year):
                done.add(year)
    finalize()
    return 0


if __name__ == "__main__":
    sys.exit(main())
