# backend/：API 伺服器

Python、FastAPI。接收瀏覽器遮名後的描述，追問缺少的事實，再呼叫民事、刑事模型與相似判決檢索，組成結果回傳。

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
| `criminal_service.py` | 刑事：讀模型（`artifacts/criminal_v1`）與檢索資料（`artifacts/retrieval_criminal_v1`），算罪名、法條、刑度、相似判決；刑度有 ELECTRA 時用 ELECTRA（下半部 `CriminalTermService`），沒有時用 SVM；沒有模型檔時回傳示例資料 |
| `followup.py` | 追問的固定題庫 |
| `llm/` | LLM 追問，見下面的「LLM」 |
| `quality.py` | 描述的品質檢查 |
| `mock.py` | 示例資料：沒有模型檔時的民事、刑事 |
| `settings.py` | 環境變數 |

## API

| 路徑 | 做什麼 | 目前 |
|---|---|---|
| `GET /api/health` | 各部分是真的模型還是示例資料 | |
| `GET /api/meta/options` | 問卷選項：糾紛類型（案由中類）、法院、證據 | 來自模型的訓練資料 |
| `POST /api/intake/mask` | 遮掉身分證字號、電話、電子郵件、地址、車牌、指定的名字 | 規則；網站改在瀏覽器遮名，這個 API 留給其他用途 |
| `POST /api/intake/followup` | 追問描述裡缺少的事實 | 固定題庫；`allow_llm: true` 且有設定 LLM 時用 LLM |
| `POST /api/intake/rewrite` | 把描述整理成判決書寫法：民事是原告主張，`case_type: criminal` 是犯罪事實 | LLM；不能用時回傳 `source: none` |
| `POST /api/civil/predict` | 民事勝訴機率 | 模型 |
| `POST /api/civil/report` | 結果頁的全部內容：相似判決的勝敗件數、機率與提示、金額範圍、相似判決、證據對照、常見抗辯 | 模型＋檢索 |
| `POST /api/criminal/predict` | 罪名、法條、刑度分布（`charges[].sentence`）、相似判決 | 罪名、法條、刑度：`criminal.models.service`；相似判決：`retrieval.criminal`（`mock`） |
| `POST /api/retrieval/search` | 相似判決，`type` 為 `civil`、`criminal`、`both` | 檢索（沒有檢索資料時為示例） |
| `GET /api/judgments/{source}/{case_id}/guide` | 判決導讀：段落與功能標示 | 民事為規則版（`labeler: rule-v0`）；刑事判決沒有導讀，列表附司法院原文網址 |

回應裡的 `mock`、`source`、`labeler` 說明結果是真的模型、規則，還是示例資料；前端據此標示「示例資料」。

## 模型與資料

讀 `artifacts/`（`config.py` 的 `ARTIFACTS_DIR`，可用環境變數 `JD_ARTIFACTS_DIR` 改）：

- `civil_winloss_v1/`：`python -m civil.models.service train` 產生
- `retrieval_civil_v4/`：`python -m retrieval.build` 產生
- `civil_amount_v1/`（選用）：`python -m civil.models.amount_service train` 產生
- `civil_winloss_v1/`、`civil_amount_v1/`、`retrieval_civil_v4/` 也可以從 Hugging Face 下載：`scripts/sync_civil_models.sh`（見根目錄 README 的「模型檔」）
- `criminal_v1/`、`retrieval_criminal_v1/`：刑事罪名、法條模型與相似判決檢索（PR #39，`python -m criminal.models.service`、`python -m retrieval.criminal` 產生）；`criminal_v1/` 可以從 Hugging Face 下載：`scripts/sync_criminal_models.sh`
- `criminal_term/`：刑度 ELECTRA（6 區間，和 SVM 相同），Kaggle `term-bucket-future-seed42-20261110` 的輸出（`best.pt`、`tokenizer/`、`encoder_config/`、`experiment_summary.json`）；沒有時刑度用 SVM。從 Hugging Face 下載：`scripts/sync_criminal_term.sh`（見根目錄 README 的「模型檔」）

`civil_winloss_v1/`、`retrieval_civil_v4/` 任一個不存在時，民事改回傳示例資料；沒有 `criminal_v1/` 時罪名、法條、刑度、相似判決改回傳示例資料。伺服器照樣能啟動。

模型的 `meta.json` 記錄訓練時的 `git_commit`（有沒 commit 的改動會加 `-dirty`）、`sklearn`、`python` 版本（`config.build_info()`）。讀模型時如果 `sklearn` 和目前安裝的不同，記錄裡會留一筆警告（`config.warn_if_other_sklearn()`）；舊的 meta 沒有這個欄位就不比對。

`civil_amount_v1/` 是獲償比例模型：有的話，結果頁的金額範圍是模型推估的「若為一部勝訴」（`amount_range.source` 是 `model`，`scope` 是 `partial_win`），相似判決的分布留著當對照。以下情況退回相似的勝訴判決的 10%–90% 分位數（`source` 是 `similar`）：

- 沒有模型檔、讀不出來（例如 `scikit-learn` 版本不同），或模型檔是舊格式、`civil/features.py` 的關鍵字改了沒重訓：啟動時在記錄裡留下警告，`/api/health` 的 `amount` 是 `similar`
- 使用者沒有自己選單一個案由，或法院和請求金額都沒填（評估裡這時模型比相似判決差）
- 這個案由的訓練件數少於 `MIN_AMOUNT_MODEL_CASES`（30 件，`backend/civil_service.py`）
- 模型這次預測出錯（記警告，結果頁其他部分照常）

描述看不出是糾紛時（`looks_like_dispute`），不論哪一種都不給金額範圍。`amount_range` 另外附 `n_wins`、`n_full_wins`：相似判決裡勝訴幾件、其中全部勝訴幾件，因為模型只回答「若為一部勝訴」。

刑期模型的注意事項：
- 只有分類頭（6 個區間），不估計月數；無期、死刑不在訓練資料裡。
- 權重的名稱是 `encoder.*`、`mlp.*`、`head.*`；少了任何一個（例如舊版的刑期模型）會拒絕載入。
- 送進模型前把【姓名】【地址】這類標記換成訓練資料的寫法（甲○○、○○市○○區…），見 `to_training_style()`。
- 有使用者確認過的整理文字時，前端送整理文字；沒有就送遮名後的原始描述。
- CPU 推論一筆約 0.3 秒；後端映像檔裝 CPU 版的 torch。`JD_BACKEND_MODE=mock` 可以強制使用示例資料。

## 相似判決的兩層

檢索語料有 158,330 件，但不是每一件都適合算統計（見 `retrieval/README.md`）：

- 勝敗件數、金額範圍、證據對照、常見抗辯：只用對審且有被告答辯的案件（前 30 件）
- `default_cases`：不分層的前 30 件裡有幾件被告未到庭，只用來另外說明，不算進比例
- 相似判決列表：全部案件都可以出現；去掉內容幾乎相同的制式判決，一造辯論最多 3 件並標示 `default_judgment`

資源（Docker）：後端記憶體約 1.1 GB，查詢約 0.65 秒。

## 模型參考

`signal` 由固定規則決定（`quality.win_signal`）：機率 0.5 以上是 `strong`，以下是 `weak`；少於 40 字或不像法律糾紛時是 `insufficient`。
切線來自 72 件模擬口語，真人測試後要再調整。這段不呼叫 LLM。

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
| `llm/gemini.py`、`llm/openai_client.py`、`llm/fake.py` | 各廠商的實作；`fake` 不連線、不花錢 |
| `llm/limits.py` | 用量上限（見下） |
| `llm/__init__.py` | 依 `JD_LLM_PROVIDER` 選擇廠商 |
| `llm/tasks.py` | 任務的 prompt 與結果檢查，不綁廠商；送出的文字都先遮名 |

- 沒有設定 `JD_LLM_PROVIDER` 時完全不呼叫外部服務
- 有設定時也要 `allow_llm: true` 才傳：打開確認頁只用固定題庫；使用者加好姓名、同意敏感個資的處理後，自己按按鈕才傳
- LLM 失敗、逾時或格式不對時，追問退回固定題庫，回應的 `source` 會是 `rules`，`fallback` 說明原因
- 整理敘述（`rewrite_claim`）的結果只有使用者確認後才會以 `search_text` 送回，用來搜尋相似判決；勝訴機率仍用原本的描述
- 整理後多出描述裡沒有的數字時，`added_numbers` 會列出來提醒使用者；這是提醒，不能保證抓到所有多加的事實
- 傳給 LLM 的文字最多 3,000 字；說明（`why`）提到法律或法院做法時，換成固定的說明
- 新增廠商：寫一個有 `generate_json` 的類別，在 `create_client` 加一行
- 廠商：`JD_LLM_PROVIDER=gemini`（`GEMINI_API_KEY`）或 `openai`（`OPENAI_API_KEY`，預設模型 gpt-4.1-mini，用 Structured Outputs 限定回傳格式）。確認頁的資料使用說明會依 `llm_vendor` 寫出內容傳給哪一家
- Gemini 只能用付費層：免費層的資料會用於改善 Google 的產品。OpenAI 的 API 資料預設不用於訓練模型
- 用量上限：每個 IP 每小時 10 次、全站每天 300 次（`JD_LLM_PER_IP_HOUR`、`JD_LLM_PER_DAY`），超過時改用固定題庫。
  次數記在記憶體，重啟歸零，只適用單一程序。Google／OpenAI 帳單另外設定預算提醒
- `docker logs` 的「LLM 用量」記錄模型與 token 數，不含案情內容

## 接上其他組的功能

- **刑事**：罪名、法條、刑度、相似判決都在 `criminal_service.py`（TF-IDF＋SVM，PR #39）；刑度用同一檔的 ELECTRA（2025 年判決測試：區間 0.763、差一區 0.973），沒有模型檔時用 SVM；`criminal_term/` 從 Hugging Face 下載（`scripts/sync_criminal_term.sh`），`criminal_v1/` 從 Hugging Face 下載（`scripts/sync_criminal_models.sh`），`retrieval_criminal_v1/` 還是另外傳，放進 `artifacts/`
- **LLM 追問**：已接上，見上面的「LLM」；送出的文字一律先經過 `retrieval.masking.mask()`
- **段落功能標註**：`civil.insights.guide_paragraphs()` 換成標註模型，`labeler` 改成模型名稱

測試：`python -m unittest tests.test_backend`（有模型、沒有模型兩種情況都測）。
