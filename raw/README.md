# raw/ 原始資料

**資料來源**：政府資料開放平臺「嬰兒出生數按性別、生母原屬國籍（地區）、年齡及教育程度分（按登記）」，內政部戶政司提供
<https://data.gov.tw/dataset/32945>

由 `scripts/download.py` 下載，內容未經任何修改（欄位名稱、編碼 UTF-8 with BOM、CRLF 換行皆為原樣），只以 gzip 壓縮以符合 repo 檔案大小限制。

## 檔案

| 檔案 | 民國年（西元） | 原始列數（不含標題列） |
|---|---|---|
| `births_104.csv.gz` | 104（2015） | 233,100 |
| `births_105.csv.gz` | 105（2016） | 233,100 |
| `births_106.csv.gz` | 106（2017） | 233,100 |
| `births_107.csv.gz` | 107（2018） | 233,100 |
| `births_108.csv.gz` | 108（2019） | 233,100 |
| `births_109.csv.gz` | 109（2020） | 231,840 |
| `births_110.csv.gz` | 110（2021） | 231,840 |
| `births_111.csv.gz` | 111（2022） | 231,840 |
| `births_112.csv.gz` | 112（2023） | 231,840 |
| `births_113.csv.gz` | 113（2024） | 231,840 |
| `births_114.csv.gz` | 114（2025） | 231,840 |
| `sample_births_113.csv` | 113（2024） | 2,000（樣本） |

`sample_births_113.csv` **只是樣本**：`births_113.csv.gz` 原檔的標題列加前 2,000 筆資料，原封不動未壓縮，方便直接打開查看原始格式。分析請用完整的 `.csv.gz`。

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
