# JudgementDigest：刑事及民事類案判決參考平台

面臨法律糾紛時，民眾往往不清楚自身的法律風險，也不知道下一步該怎麼做。自行上網搜尋或詢問生成式 AI，可能得到不存在的判決或沒有依據的說法。

本系統以**全國地方法院的真實判決**為基礎：使用者描述案情或提供起訴書（狀）事實，系統找出**相似的真實判決**，並推估可能的結果，作為規劃後續法律協助的參考。

> **這不是什麼**：本平台不是 AI 律師，不提供法律意見，也不預測個案一定會怎麼判。所有結果都是「類似案件**如果打到判決**，通常怎麼判」的統計參考，並附上真實判決的字號供查證。和解、撤回、調解成立的案件沒有判決書，不在資料內。

## 功能

| | 輸入 | 輸出 | 第一版（目前） |
|---|---|---|---|
| **民事結果參考** | 原告主張＋使用者填得出來的案件特徵 | 相似判決的勝敗件數、模型參考（機率放在模型細節） | 🟢 相似判決統計；只用原告主張的 TF-IDF＋案件特徵 |
| **民事金額範圍** | 請求金額＋相似的勝訴判決 | 判准金額的 80% 範圍 | 🟢 相似判決的獲償比例 |
| **相似判決檢索**（刑事、民事共用） | 案情描述 | 最相似的真實判決（字號、結果、刑期／判准金額） | 🟢 民事；🟢 刑事（每個罪名最多 1,500 件） |
| **證據對照、常見抗辯** | 相似判決＋使用者有的證據 | 相似判決提到哪些證據（提到 ≠ 採信）、被告常見的抗辯 | 🟢 關鍵字規則 |
| **輸入補全** | 案情描述 | 固定問卷＋追問缺漏的事實，送出前遮名預覽；把描述整理成判決書寫法，確認後用來搜尋 | 🟢 固定題庫；使用者同意後可用 LLM 追問與整理（Gemini） |
| **判決導讀** | 相似判決 | 標出爭點、證據、法院判斷等段落 | 🟡 規則初步標示；待段落功能標註 |
| **刑事** | 犯罪事實 | 罪名、法條、刑期區間 | 🟢 TF-IDF＋LinearSVC＋機率校正（`criminal/models/service.py`）；刑度用法律 ELECTRA（`artifacts/criminal_term`，沒有時用 SVM） |
| **說明與報告** | 結果頁 | 名詞與糾紛類型說明、下載 PDF | 🟢 |
| **法官論理傾向分析** | 段落功能標註 | 法官事實認定與論理的傾向（民眾版不呈現） | ⬜ 規劃中 |

🟢 已接上真正的模型或資料　🟡 先用規則版　⬜ 示例資料或尚未開始。示例資料在網頁上都會標示。

## 系統架構

```mermaid
%%{init: {"htmlLabels": false, "flowchart": {"htmlLabels": false, "wrappingWidth": 400}}}%%
flowchart LR
    U([使用者]) --> FE["① 輸入補全<br/>固定問卷，同意後可用 LLM 追問、整理敘述<br/>遮名後才送出"]
    FE --> IN["結構化輸入<br/>案由、事實<br/>請求金額、證據"]

    subgraph BE["② 預測與檢索"]
        CIV["民事勝訴機率模型"]
        RET["相似判決檢索"]
        AMT["金額範圍<br/>證據對照、常見抗辯"]
        ANN["判決導讀<br/>目前以規則標示"]
        CRI["刑事模型<br/>罪名／法條／刑期"]
        RET --> AMT & ANN
    end

    subgraph DATA["③ 資料（離線）"]
        CR["爬蟲<br/>全國地院判決"] --> ST["段落切分＋結構化<br/>事實、判決結果<br/>金額、刑期"]
        ST --> DS[("結構化資料集")]
        TAG["段落功能標註（開發中）<br/>LLM 輔助＋法律系驗證"]
    end

    IN --> CIV & RET & CRI
    DS --> CIV & RET
    DS -.-> CRI
    TAG -.-> ANN
    CIV & AMT & ANN & CRI --> OUT["④ 結果頁<br/>相似判決＋推估結果<br/>限制說明"]
    OUT --> U
```

虛線是還沒接上的部分。

## 資料

- 來源：[司法院裁判書查詢系統](https://judgment.judicial.gov.tw/FJUD/default.aspx)，全國地方法院判決（含簡易庭）
- 規模：民事資料庫 236,009 筆判決（2022 年 1 月至 2026 年 4 月）；其中檢索語料 158,327 件、模型訓練 46,683 件。刑事：全國地院第一審判決 2016–2025（有罪、單一被告），CAIL 格式資料集 v2 共 1,132,585 筆；研究用均衡抽樣 10 萬筆（罪名 80 類、法條 102 類），平台模型用隨機 30 萬筆，刑事檢索語料 88,376 件
- 處理：以規則切分段落，擷取事實、判決結果、金額、刑期、法官等欄位，欄位定義見 [docs/欄位說明.md](docs/欄位說明.md)
- 刑事另從[司法院資料開放平臺](https://opendata.judicial.gov.tw/)取得全國地院刑事判決（`data_pipeline/opendata_*.py`）
- 資料庫、HTML 原檔與模型權重不放在 repo 裡（檔案太大，且含當事人資訊）

## 目前結果

**民事**（文字資料集 v5：46,683 件對審、通常程序的一審判決，5 折交叉驗證）

- 指標都以機率 50% 為切線，勝訴、敗訴分開算。勝訴約占六成，全猜勝訴的勝訴 recall 是 100%，但敗訴一件也抓不到，所以兩類都要看
- **平台第一版**：只用原告主張的 TF-IDF＋案件特徵。勝訴 precision 0.733、recall 0.811（F1 0.770）；敗訴 precision 0.659、recall 0.553（F1 0.601）；校準誤差 0.021。什麼都不填時，敗訴 recall 降到 0.494、校準誤差 0.045（`python -m civil.models.service evaluate`）
- 研究用的模型：兩造主張都有時（TF-IDF＋Longformer＋結構化）勝訴 precision 0.787、recall 0.796；敗訴 precision 0.686、recall 0.674。平台拿不到被告答辯，所以沒有使用
- 以上都是用法官整理過的主張測的。72 件模擬的民眾口語描述（模型沒看過的真實案件，勝敗各半，改寫時不知道結果；還不是真人測試）：勝訴 precision 0.815、recall 0.611；敗訴 precision 0.689、recall 0.861。平均機率 0.46，實際約 0.60，所以偏向判敗訴
- 金額：只能給範圍，約 64% 的預測落在實際金額的 2 倍以內
- 輸入寫得越短越不準：只給前 150 字時，勝訴 recall 從 0.807 降到 0.638，敗訴 precision 從 0.655 降到 0.548，所以前端要先把事實問完整

**刑事**（研究：10 萬筆均衡樣本，5 折交叉驗證；2025 年判決不參與訓練與選 epoch，另外當未來資料測試。數字為 test／2025）

| 模型 | 罪名 micro-F1 | 法條 micro-F1 | 刑期 CAIL 分數 |
|---|---|---|---|
| TF-IDF＋SVM | 0.924／0.897 | 0.886／0.776 | 0.727／0.688 |
| fastText | 0.924／0.908 | 0.887／0.788 | 0.698／0.660 |
| TextCNN | 0.905／0.892 | 0.864／0.770 | 0.717／0.680 |
| ELECTRA（6 層） | 0.858／0.836 | 0.799／0.709 | 0.763／0.713 |

- 刑期 CAIL 分數依預測和實際刑期的對數差距給分（滿分 1）
- 罪名、法條以 SVM、fastText 最好；刑期以 ELECTRA 最好
- 2025 的法條掉最多，主因是 2024 年洗錢防制法修法換條號（第 14 條→第 19 條）。新舊條號合併後，SVM 的 2025 法條 micro-F1 從 0.776 升到 0.820
- 刑期加入罪名有幫助：SVM 加上預測的罪名，CAIL 分數 0.727→0.755；加上正確罪名是 0.770
- 事實裡的本案罪名、法條遮成「××」。補強遮蔽規則後（PR #14）重跑 SVM，各指標變動都在 0.01 以內
- **平台模型**（`criminal_v1`：SVM＋機率校正，隨機 30 萬筆訓練，另外 1 萬筆測試）：罪名 top-1 0.979、法條 micro-F1 0.954、6 個刑度區間 accuracy 0.810（差一區以內 0.980）。訓練資料多、資料是自然分布、拘役和罰金併成一區，所以比研究數字高，兩者不能直接比；沒有做交叉驗證或 2025 測試

## Repo 結構

```
JudgementDigest/
├── config.py          資料庫、資料集、模型檔的路徑（可用環境變數改）
├── data_pipeline/     資料蒐集與處理：爬蟲、開放資料、HTML 解析、民事與刑事結構化欄位
├── civil/             民事：dataset/（建資料集的程式）、models/（勝訴機率、金額）、insights.py（證據、抗辯、金額範圍）
├── criminal/          刑事：dataset/（事實取得與遮蔽）、models/（平台模型 service.py、基準模型）
├── retrieval/         相似判決檢索：engine.py（共用）、civil.py、build.py、masking.py（遮名）
├── annotation/        段落功能標註：標註手冊 v0.3、LLM 標註（annotate.py）、抽樣與抽查
├── backend/           API 伺服器（FastAPI）
├── frontend/          網頁（React＋Vite）
├── scripts/           輔助工具（瀏覽資料庫）
├── docs/              爬蟲用法、欄位說明、資料版本、刑事結構化規則、repo 結構
├── docker-compose.yml
└── tests/
```

資料庫、HTML 原檔、資料集 CSV、模型權重都不放在 repo 裡（太大，且含當事人資訊），repo 只放程式。
資料怎麼產生、放在哪裡見 [docs/資料版本.md](docs/資料版本.md)；各資料夾的內容與負責人見 [docs/repo結構.md](docs/repo結構.md)。

## 快速開始

### 用 Docker 啟動整個平台

```bash
docker compose up --build
```

開 http://localhost:8080 。8080 被占用時改用別的 port：`JD_PORT=8180 docker compose up --build`。

模型與檢索資料（`artifacts/`）不在 repo 裡，由組內另外分享：

| 情況 | 民事顯示 | 適合 |
|---|---|---|
| 只下載 repo | 示例資料（頁面會標示），流程照樣走得完 | 開發前端、後端、跑測試 |
| 把分享的 `artifacts/` 放在 repo 根目錄 | 真實的模型與判決 | 測試真實結果、部署 |

不用改設定，後端啟動時會自己判斷。

#### 模型檔（Hugging Face）

模型檔放在 Hugging Face 的私人 repo [`yunn030123/judgementdigest-artifacts`](https://huggingface.co/yunn030123/judgementdigest-artifacts)，每個資料夾對應 `artifacts/` 底下的同名資料夾。目前有：

| 資料夾 | 內容 | 同步指令 |
|---|---|---|
| `criminal_term/` | 刑度 ELECTRA（約 410 MB） | `scripts/sync_criminal_term.sh` |

其他資料夾（民事模型、民事檢索、刑事 SVM、刑事檢索）還在組內另外傳。上傳方式見 [`docs/模型檔上傳.md`](docs/模型檔上傳.md)。

第一次使用：

1. 請管理者把你加進 repo 所在的 HF 組織（repo 是私人的，組織成員才看得到）。
2. 安裝 Hugging Face CLI 並登入（token 在 https://huggingface.co/settings/tokens 建立，選 Read 權限）：
   ```bash
   pip install -U "huggingface_hub[cli]"
   hf auth login
   ```
3. 在 repo 根目錄執行：
   ```bash
   scripts/sync_criminal_term.sh
   ```
   檔案會下載到 `artifacts/criminal_term/`。再執行一次只會下載有改過的檔案，所以模型更新後重跑同一個指令就好。

要固定某一版時，把版本傳進去（可以是 commit、tag 或分支）：`scripts/sync_criminal_term.sh --revision <commit>`。只想看會下載什麼：`scripts/sync_criminal_term.sh --dry-run`。

下載完要重啟後端才會讀到新模型：`docker compose up -d --force-recreate backend`（本機開發則重開 `uvicorn`）。`/api/health` 的 `criminal_sentence` 是 `electra` 表示有讀到。

更新模型的人：上傳到同一個 repo 的同名資料夾（`hf upload yunn030123/judgementdigest-artifacts <本機資料夾> criminal_term --commit-message "..."`），並在 PR 或群組說明換了什麼、分數多少。

要用 LLM 追問時，把 `.env.example` 複製成 `.env` 並填入自己的 key；沒有 `.env` 時追問會用固定題庫。

### 本機開發

需要 Python 3.9 以上、Node.js 20 以上。所有指令都在 repo 根目錄執行。

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate      # macOS / Linux
pip install -r requirements.txt -r backend/requirements.txt

python -m unittest discover -s tests -t .     # 離線測試

uvicorn backend.main:app --reload             # 後端，API 文件在 http://127.0.0.1:8000/docs
cd frontend && npm install && npm run dev     # 前端（另開一個終端機），http://localhost:5173
```

要用真正的模型，先準備資料（見 [docs/資料版本.md](docs/資料版本.md)），再建立模型檔：

```bash
python -m civil.models.service evaluate       # 5 折評估
python -m civil.models.service train          # → artifacts/civil_winloss_v1/
python -m civil.models.amount_service train   # → artifacts/civil_amount_v1/（選用：金額範圍改用模型推估）
python -m retrieval.build                     # → artifacts/retrieval_civil_v3/（要有 judgments.db，約 35 分鐘）
```

爬取與資料處理：

```bash
python data_pipeline/crawl_monthly.py --court 臺灣臺北地方法院 --case-type 民事 --judgment-type 判決 --year 2025
python data_pipeline/html_parser.py
python scripts/browse_db.py
```

- 爬取與建立資料庫的完整用法：[docs/crawler.md](docs/crawler.md)
- 資料庫欄位：[docs/欄位說明.md](docs/欄位說明.md)
- 刑事結構化規則：[docs/criminal/structure.md](docs/criminal/structure.md)

## 限制

- 結果只代表「打到判決」的案件；約 26–29% 的通常程序民事案件以和解、撤回、調解結束，沒有判決書
- 模型讀的是法官整理過的事實，口語描述的機率會偏低、分不太出輸贏；訓練時加入短版文字沒有改善（見 `retrieval/README.md`）
- 相似判決用字元 TF-IDF 比對。使用者確認過 LLM 整理的文字時用整理後的文字，否則用原本的描述；整理可能多加事實，所以要使用者確認，也會提醒多出來的數字
- 遮名是規則版，判決裡的第三人姓名和車牌仍可能漏掉，正式公開前要再處理
- 法院「為什麼採信」很難自動判斷；證據比對只說「相似判決提到哪些證據」，不代表法院會採信
- 法官事實認定論理傾向分析仍在規劃中；法官層級的結果會附樣本數與限制說明，民眾版只呈現法院與案件類型層級
- 平台不保存使用者輸入的資料

## 授權

[MIT](LICENSE)
