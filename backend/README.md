# backend/：API 伺服器

Python、FastAPI。接收使用者輸入，遮名後追問缺少的事實，再呼叫民事模型與相似判決檢索，組成結果回傳。

```bash
uvicorn backend.main:app --reload      # 在 repo 根目錄執行
```

API 文件（可以直接在網頁上試）：http://127.0.0.1:8000/docs

## 檔案

| 檔案 | 內容 |
|---|---|
| `main.py` | 路由（全部在 `/api` 底下） |
| `schemas.py` | 輸入輸出格式；前端的 `frontend/src/api/types.ts` 和它一一對應 |
| `civil_service.py` | 民事：讀模型與檢索資料，算勝訴機率、相似判決、金額範圍、證據對照、常見抗辯、判決導讀 |
| `followup.py` | 追問的固定題庫（之後改成 LLM） |
| `mock.py` | 示例資料：刑事、以及沒有模型檔時的民事 |
| `settings.py` | 環境變數 |

## API

| 路徑 | 做什麼 | 目前 |
|---|---|---|
| `GET /api/health` | 各部分是真的模型還是示例資料 | |
| `GET /api/meta/options` | 問卷選項：糾紛類型（案由中類）、法院、證據 | 來自模型的訓練資料 |
| `POST /api/intake/mask` | 遮掉身分證字號、電話、電子郵件、地址、指定的名字 | 規則 |
| `POST /api/intake/followup` | 追問描述裡缺少的事實 | 固定題庫（`source: rules`） |
| `POST /api/civil/predict` | 民事勝訴機率 | 模型 |
| `POST /api/civil/report` | 結果頁的全部內容：機率、金額範圍、相似判決、證據對照、常見抗辯 | 模型＋檢索 |
| `POST /api/criminal/predict` | 罪名、法條、刑期分布、相似判決 | **示例資料**（刑事組開發中） |
| `POST /api/retrieval/search` | 相似判決，`type` 為 `civil`、`criminal`、`both` | 民事真的；刑事示例 |
| `GET /api/judgments/{source}/{case_id}/guide` | 判決導讀：段落與功能標示 | 民事為規則版（`labeler: rule-v0`） |

回應裡的 `mock`、`source`、`labeler` 說明結果是真的模型、規則，還是示例資料；前端據此標示「示例資料」。

## 模型與資料

讀 `artifacts/`（`config.py` 的 `ARTIFACTS_DIR`，可用環境變數 `JD_ARTIFACTS_DIR` 改）：

- `civil_winloss_v1/`：`python -m civil.models.service train` 產生
- `retrieval_civil_v3/`：`python -m retrieval.build` 產生

任一個不存在時，民事改回傳示例資料，伺服器照樣能啟動。`JD_BACKEND_MODE=mock` 可以強制使用示例資料。

## 相似判決的兩層

檢索語料有 158,327 件，但不是每一件都適合算統計（見 `retrieval/README.md`）：

- 金額範圍、證據對照、常見抗辯：只用對審且有被告答辯的案件（前 30 件）
- 相似判決列表：全部案件都可以出現；去掉內容幾乎相同的制式判決，一造辯論最多 3 件並標示 `default_judgment`

資源（Docker）：後端記憶體約 1.1 GB，查詢約 0.65 秒。

## 描述的品質檢查

只提醒，不擋送出：

- 沒有任何糾紛用語或金額（`quality.py`）：提醒內容看起來不像法律糾紛。模型和檢索什麼內容都會給結果
- 沒選糾紛類型：用最相似的 30 件對審判決投票，比例超過 0.4 才採用並告知使用者，否則列出可能的類型。
  72 件口語測試中全部採用只對 47%，比例超過 0.4 的 23 件對 21 件

## LLM

`llm/` 是一層薄薄的介面，廠商由環境變數決定（`.env.example`）：

| 檔案 | 內容 |
|---|---|
| `llm/base.py` | 共用介面 `generate_json` 與 `LLMError` |
| `llm/gemini.py`、`llm/fake.py` | 各廠商的實作；`fake` 不連線、不花錢 |
| `llm/__init__.py` | 依 `JD_LLM_PROVIDER` 選擇廠商 |
| `llm/tasks.py` | 任務的 prompt 與結果檢查，不綁廠商；送出的文字都先遮名 |

- 沒有設定 `JD_LLM_PROVIDER` 時完全不呼叫外部服務
- LLM 失敗、逾時或格式不對時，追問退回固定題庫，回應的 `source` 會是 `rules`
- 新增廠商：寫一個有 `generate_json` 的類別，在 `create_client` 加一行
- Gemini 只能用付費層：免費層的資料會用於改善 Google 的產品

## 接上其他組的功能

- **刑事**：在 `main.py` 的 `/api/criminal/predict` 把 `mock.criminal_report()` 換成刑事模型，回傳格式照 `schemas.CriminalReport`
- **LLM 追問**：已接上，見下面的「LLM」；送出的文字一律先經過 `retrieval.masking.mask()`
- **段落功能標註**：`civil.insights.guide_paragraphs()` 換成標註模型，`labeler` 改成模型名稱

測試：`python -m unittest tests.test_backend`（有模型、沒有模型兩種情況都測）。
