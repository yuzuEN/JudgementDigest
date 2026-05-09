# 司法院裁判書自動爬蟲

自動從[司法院裁判書查詢系統](https://judgment.judicial.gov.tw/FJUD/default.aspx)爬取裁判書，解析結構化資料並匯出 Excel。

## 功能

- 關鍵字搜尋，自動突破每次 500 筆的查詢上限
- 支援日期範圍篩選（以年為單位自動分批）
- 解析 20+ 個欄位：裁判字號、法院、當事人、主文、事實及理由、法官等
- 支援所有法院類型，包含憲法法庭特殊格式
- 匯出格式化 Excel，含法院分布統計摘要

## 環境需求

- Python 3.9+
- Google Chrome（版本需與 chromedriver 相符，`webdriver-manager` 會自動管理）

## 安裝

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

pip install -r requirements.txt
```

## 使用方式

### 一鍵完整流程（推薦）

```bash
python pipeline.py <keyword> -n <筆數> [選項]
```

| 參數 | 說明 |
|------|------|
| `<keyword>` | 搜尋關鍵字，例如 `借名登記`、`詐欺` |
| `-n <筆數>` | 目標爬取筆數，例如 `-n 1000` |
| `--start-year <年>` | 搜尋起始年（西元），預設 2015 |
| `--end-year <年>` | 搜尋結束年（西元），預設今年 |
| `--start-date <日期>` | 精確起始日期，格式 `YYYY/MM/DD`，會覆蓋 `--start-year` |
| `--end-date <日期>` | 精確結束日期，格式 `YYYY/MM/DD`，會覆蓋 `--end-year` |
| `--no-headless` | 顯示瀏覽器視窗，方便除錯觀察 |
| `-o <檔名>` | 指定輸出 Excel 檔名，預設自動加時間戳 |
| `--full-text` | Excel 含完整全文欄位（檔案較大） |
| `--skip-crawl` | 跳過爬取，只重新解析 + 匯出（更新 parser 後使用） |

依序執行爬取 → 解析 → 匯出 Excel，完成後在當前目錄產生 `judgments_借名登記_YYYYMMDD_HHMMSS.xlsx`。

**範例：**

```bash
# 基本用法：搜尋「借名登記」，目標 1000 筆
python pipeline.py 借名登記 -n 1000

# 限制年份範圍
python pipeline.py 借名登記 -n 1000 --start-year 2020 --end-year 2024

# 精確日期範圍
python pipeline.py 借名登記 -n 500 --start-date 2024/01/01 --end-date 2024/12/31

# 顯示瀏覽器視窗（除錯用）
python pipeline.py 借名登記 -n 100 --no-headless

# 跳過爬取，只重新解析 + 匯出
python pipeline.py 借名登記 --skip-crawl
```

---

### 分步執行

若需要個別控制每個步驟：

**步驟 1：爬取**

```bash
python crawl_batched.py <keyword> -n <筆數> [選項]
```

| 參數 | 說明 |
|------|------|
| `<keyword>` | 搜尋關鍵字 |
| `-n <筆數>` | 目標爬取筆數 |
| `--start-year <年>` | 搜尋起始年（西元） |
| `--end-year <年>` | 搜尋結束年（西元） |
| `--start-date <日期>` | 精確起始日期 `YYYY/MM/DD` |
| `--end-date <日期>` | 精確結束日期 `YYYY/MM/DD` |
| `--no-headless` | 顯示瀏覽器視窗 |

```bash
python crawl_batched.py 借名登記 -n 1000
python crawl_batched.py 借名登記 -n 1000 --start-year 2018 --end-year 2023
```

HTML 快取存於 `html_cache/`，爬取紀錄寫入 `judgments.db`。

**步驟 2：解析**

```bash
python html_parser.py [選項]
```

| 參數 | 說明 |
|------|------|
| （無參數） | 解析所有尚未解析的新紀錄 |
| `--reparse` | 清空已解析資料，重新解析全部（更新 parser 邏輯後使用） |
| `--file <路徑>` | 僅解析指定的單一 HTML 檔案（測試用） |

```bash
python html_parser.py            # 解析新增的紀錄
python html_parser.py --reparse  # 全部重新解析
```

**步驟 3：匯出 Excel**

```bash
python export_excel.py [選項]
```

| 參數 | 說明 |
|------|------|
| `-n <筆數>` | 匯出筆數，`0` 表示全部，預設 100 |
| `-k <關鍵字>` | 篩選關鍵字（比對裁判字號、主文） |
| `-c <法院>` | 篩選法院（部分比對，例如 `臺灣臺北`） |
| `--start-date <日期>` | 篩選裁判日期起 |
| `--end-date <日期>` | 篩選裁判日期迄 |
| `--full-text` | 含完整全文欄位（檔案較大） |
| `-o <檔名>` | 指定輸出檔名 |

```bash
python export_excel.py -n 0 -k 借名登記       # 匯出全部借名登記資料
python export_excel.py -n 100                  # 匯出最新 100 筆
python export_excel.py -n 0 -c 臺灣臺北       # 篩選臺北相關法院
python export_excel.py -n 0 --full-text        # 含全文欄位
```

---

### 補爬不完整的頁面

若某些裁判書頁面因網路問題只儲存到不完整的 HTML，可補爬：

```bash
python crawler.py --recrawl-stubs
```

## 專案結構

```
.
├── pipeline.py          # 完整流程：爬取 → 解析 → 匯出
├── crawl_batched.py     # 分批爬取，突破 500 筆上限（BFS 策略）
├── crawler.py           # 核心爬蟲（Selenium）
├── html_parser.py       # HTML 解析，結構化存入 SQLite
├── export_excel.py      # 匯出 Excel
├── requirements.txt
│
├── html_cache/          # 爬取的 HTML 快取（自動建立，不入版控）
└── judgments.db         # SQLite 資料庫（自動建立，不入版控）
```

## 運作原理

### 爬取流程

```
crawl_batched.py
  │  以年為單位分段（2026、2025、2024...）
  │  若某年碰到 500 筆上限 → 下一輪對切再抓
  │
  └── crawler.py（每段呼叫一次）
        │  輸入關鍵字 → 取得查詢 hash URL
        │
        ├── 策略 A：依法院分群連結逐一收集（主要）
        │     每個法院只導覽一次，Python 層做年度過濾
        │
        └── 策略 B：依年度 URL 翻頁（備援，當策略 A 無法取得法院連結時）
```

### 資料庫結構

| 資料表 | 內容 |
|--------|------|
| `crawl_records` | 爬取紀錄（URL、HTML 路徑、是否已解析） |
| `judgments` | 解析結果（裁判字號、法院、當事人、主文等 20+ 欄位） |

### 支援的解析欄位

裁判字號、裁判書連結、法院、裁判日期、案件類型、裁判種類、原告／聲請人、被告／相對人、上訴人、被上訴人（及各方代理人）、主文、事實、事實及理由、犯罪事實、理由、結論、適用法條、法官、書記官

## 注意事項

- 爬蟲速度受限於司法院伺服器，尖峰時段可能較慢或出現 timeout，程式會自動重試
- 首次執行時 `webdriver-manager` 會自動下載對應版本的 chromedriver
