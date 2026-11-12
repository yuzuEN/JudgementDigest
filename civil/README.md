# civil/：民事

民事判決的文字資料集與模型：從原告主張（與被告答辯、案件特徵）推估勝訴機率與獲償金額。

一律在 repo 根目錄以模組方式執行（`python -m civil.…`）。資料與輸出的位置見根目錄的 `config.py`，
資料版本見 [docs/資料版本.md](../docs/資料版本.md)。

## dataset/：建立資料集的程式

| 檔案 | 內容 |
|---|---|
| `text.py` | 清理文字的規則（刪聲明、正規化、洩漏用語）。**建資料集和後端處理使用者輸入共用這一份** |
| `build_dataset.py` | 產生 `text_dataset_{版本}.csv`：`python -m civil.dataset.build_dataset v5` |
| `leak_check.py` | 資料集的自動洩漏檢查：`python -m civil.dataset.leak_check` |

## models/：模型的訓練與評估

| 檔案 | 內容 | 環境 |
|---|---|---|
| `tfidf.py` | TF-IDF（字元 1–3 gram）＋logistic regression，5 折 | `.venv` |
| `structured.py` | 結構化變數（律師、法人、反訴、案由、請求權、程序、法院、年份），以及文字＋結構化 | `.venv` |
| `ensemble.py` | 合併模型（TF-IDF、結構化、BERT、Longformer，權重只用驗證集決定）與 precision／recall 評估 | `.venv` |
| `amount.py` | 金額：預測獲償比例或判准金額，用誤差評估 | `.venv` |
| `train_bert.py` | BERT 微調（勝敗） | `.venv-bert`（GPU） |
| `train_longformer.py` | Longformer 微調（勝敗或金額），也可以單獨上傳到雲端 GPU 跑 | `.venv-bert`（GPU） |
| `train_bert_amount.py` | 金額任務的 BERT | `.venv-bert`（GPU） |
| `service.py` | **平台用的勝敗模型**：只用原告主張的 TF-IDF＋使用者填得出來的特徵（案由、法院、律師、對方是否為法人）。`evaluate` 做 5 折評估，`train` 存到 `artifacts/civil_winloss_v1/` | `.venv` |
| `amount_service.py` | **平台用的獲償比例模型**（兩階段的第二階段）：「若為一部勝訴，原告大約贏幾成」，給 10%–90% 的範圍。輸入同 `service.py`，再加請求金額和損害子項目。`evaluate`、`train`（→ `artifacts/civil_amount_v1/`）；`--rules db` 改讀資料庫裡的金額欄位 | `.venv` |

`features.py` 是金額的共用特徵（損害子項目的關鍵字），`amount.py` 和 `amount_service.py` 都從這裡讀；關鍵字改了要重訓金額模型，否則後端不會用舊模型。

平台模型的 `meta.json` 會記錄訓練時的 git commit 與 scikit-learn 版本，見 [backend/README.md](../backend/README.md) 的「模型與資料」。

目前結果（文字資料集 v5，46,683 件，5 折，機率 50% 為切線）：兩造的 TF-IDF＋Longformer＋結構化，勝訴 precision 0.787、recall 0.796，
敗訴 precision 0.686、recall 0.674；只用原告主張的 TF-IDF，勝訴 0.728、0.818，敗訴 0.661、0.538。詳見實驗輸出的 `pr_ensemble_v5.md`。

## insights.py：給使用者的參考

證據對照（相似勝訴判決提到哪些證據）、常見抗辯、判准金額範圍（相似勝訴判決的獲償比例 10%–90% 分位數）、判決導讀的段落標示。全部是關鍵字規則，結果只表示判決裡「提到」，不代表法院採信。

負責：（待填）
