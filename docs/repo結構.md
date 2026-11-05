# Repo 結構說明

這份文件說明 JudgementDigest 的資料夾怎麼分、每個檔案放哪裡、誰負責。之後新增程式時，請照這裡的分法放。

## 分法的原則

1. **模型與資料集依領域分**：`civil/`、`criminal/` 各自獨立，對應組內民事、刑事的分工，兩邊改自己的資料夾，比較不會衝突。
2. **系統部分依層次分**：`backend/`（API 伺服器）、`frontend/`（網頁）分開，語言、工具、部署方式都不同。
3. **共用的東西放在獨立資料夾**：資料蒐集與處理（`data_pipeline/`）、相似判決檢索（`retrieval/`）民刑都會用到。
4. **程式進 repo，資料不進**：資料庫、HTML 原檔、資料集 CSV／JSONL、模型權重、實驗輸出都不進 repo（太大，且含當事人資訊），放在共用的雲端空間，以版本命名。`dataset/` 資料夾放的是**建立資料集的程式**，不是資料本身。

## 結構

```
JudgementDigest/
├── README.md              系統介紹
├── requirements.txt
├── config.py              資料庫、資料集、實驗輸出、模型檔的路徑（可用環境變數改）
│
├── data_pipeline/         ── 資料蒐集與處理（民刑共用，見下方說明）
│
├── civil/                 ── 民事
│   ├── dataset/           建立文字資料集的程式（原告主張、被告答辯、標籤）
│   └── models/            勝訴機率、獲償金額模型的訓練與評估
│
├── criminal/              ── 刑事
│   ├── dataset/           犯罪事實取得與遮蔽、產生 CAIL 格式資料集的程式
│   └── models/            罪名、法條、刑期模型的訓練與評估
│
├── retrieval/             ── 相似判決檢索（民刑共用）
│   ├── engine.py          建索引、存檔、查前 k 件、顯示時遮名
│   ├── civil.py           民事設定：用原告主張建索引、依案由篩選、顯示勝敗與金額
│   ├── criminal.py        刑事設定：用遮蔽後的事實建索引、依罪名篩選、顯示罪名與刑期
│   └── evaluate.py        兩邊各自的評估方式
│
├── annotation/            ── 段落功能標註（判決導讀、法官論理傾向分析的基礎）
│
├── backend/               ── API 伺服器（Python、FastAPI）
│   ├── main.py
│   ├── routers/           civil.py、criminal.py、retrieval.py
│   ├── schemas.py         輸入輸出格式
│   ├── masking.py         送出前遮名
│   └── llm.py             LLM 追問（呼叫付費 API）
│
├── frontend/              ── 網頁（問卷、結果頁）
├── scripts/               ── 輔助工具（Datasette 瀏覽資料庫）
├── docs/                  ── 文件
│   ├── crawler.md         爬蟲與資料處理的完整用法
│   ├── 欄位說明.md         資料庫各欄位的定義
│   ├── 心證層欄位規格.md
│   ├── repo結構.md         本文件
│   ├── 資料版本.md          資料庫與資料集的版本、怎麼產生
│   └── criminal/          刑事結構化規則（structure.md）、白名單、標準化問題與萃取報告
└── tests/                 ── 測試
```

`criminal/`、`annotation/`、`backend/`、`frontend/` 目前只有一份 README，程式之後依上面的分法放進去。`civil/`、`retrieval/` 已經有程式（`retrieval/criminal.py` 待刑事組加入）。每個資料夾的 README 寫明內容、怎麼執行、負責人。

## `data_pipeline/` 為什麼不再分子資料夾

裡面的程式彼此以同資料夾的模組名稱 import（`from structure_tasks import …`），刑事工具也依賴這個前提：

- `compare_law_extraction.py` 會從 git 歷史取出舊版程式、以模組名稱動態載入比較
- `refresh_modeldata.py`、`rebuild_fallback_outputs.py` 以檔名在同一個資料夾計算程式雜湊

分成子資料夾就要全部改成套件式 import，這些機制會失效，所以放在同一層，依檔名分類：

| 類別 | 檔案 |
|---|---|
| 爬蟲 | `crawler.py`、`crawl_batched.py`、`crawl_monthly.py`、`crawl_simple_courts.py` |
| 開放資料（刑事全國） | `opendata_download.py`、`opendata_convert.py` |
| 解析 | `html_parser.py` |
| 民事結構化 | `structuring.py`、`backfill_structured.py`、`refresh_judges.py` |
| 刑事結構化 | `structure_tasks.py`、`appendix_parser.py`、`build_offenses.py`、`normalize.py`、`driving_charge.py`、`law_fallback.py`、`law_frequency.py`、`law_label_validation.py`、`merge.py` |
| 刑事模型資料 | `build_structured_review.py`、`export_structured_db.py`、`refresh_modeldata.py`、`rebuild_fallback_outputs.py`、`compare_law_extraction.py` |
| 匯出、一鍵流程 | `export_excel.py`、`pipeline.py` |

## 執行方式

**一律在 repo 根目錄執行**。資料庫（`judgments.db`）、HTML（`html_cache/`）、日誌、爬取進度檔都用相對於目前目錄的路徑：

```bash
python data_pipeline/crawl_monthly.py --year 2025 ...
python data_pipeline/html_parser.py
python scripts/browse_db.py
python -m unittest discover -s tests -t .
```

`tests/__init__.py` 會把 `data_pipeline/` 加進 `sys.path`，測試照原本的模組名稱 import。

## API（規劃）

| 路徑 | 做什麼 | 負責 |
|---|---|---|
| `POST /civil/predict` | 民事勝訴機率、獲償金額範圍 | 民事 |
| `POST /criminal/predict` | 罪名、法條、刑期區間 | 刑事 |
| `POST /retrieval/search` | 相似判決；`type` 為 `civil`、`criminal` 或 `both` | 檢索 |

使用者的案件是民事、刑事還是兩者都有（例如車禍：刑事過失傷害、民事損害賠償），在問卷或後端判斷，不是檢索的工作。兩者都有時，結果頁分成刑事、民事兩區。

## 負責人

| 資料夾 | 負責 |
|---|---|
| `data_pipeline/`（爬蟲、民事結構化） | （待填） |
| `data_pipeline/`（開放資料、刑事結構化） | （待填） |
| `civil/` | （待填） |
| `criminal/` | （待填） |
| `retrieval/` | `engine.py`：（待填）；`civil.py`、`criminal.py`：各領域負責人 |
| `annotation/` | （待填） |
| `backend/`、`frontend/` | （待填） |

## 之後要搬進來的檔案

| 來源 | 檔案 | 搬到 |
|---|---|---|
| PR #14 | `facts.py` | `criminal/dataset/` |
| PR #15、#16 | `model/` | `criminal/models/` |

PR #14–16 照現在的位置合併即可，合併後再另外搬。民事的資料集、模型與檢索程式已經搬進 `civil/`、`retrieval/`；實驗輸出、資料、單次比較用的程式不進 repo。資料庫與模型檔的路徑寫在 `config.py`。
