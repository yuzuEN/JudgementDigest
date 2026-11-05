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

目前結果（文字資料集 v5，46,683 件，5 折）：兩造的 TF-IDF＋BERT＋Longformer AUC 0.829、
TF-IDF＋Longformer＋結構化 0.827；只用原告主張的 TF-IDF 0.769。詳見實驗輸出的 `pr_ensemble_v5.md`。

負責：（待填）
