# 刑事判決預測模型

CAIL 格式資料集（罪名、法條、刑期三個任務）的基準模型與共用評估。所有模型都用 `evaluate.py` 讀資料、切分、算分數，分數才能互相比較。

| 檔案 | 內容 | 適用資料量 | 需要 |
|---|---|---|---|
| `evaluate.py` | 共用讀取、切分、評分（只依賴 numpy） | — | numpy |
| `svm_baseline.py` | TF-IDF（字 1–2 gram）＋ LinearSVC，10-fold | 台北 v1.x（約 5 萬筆） | scikit-learn |
| `svm_learning_curve.py` | 同上，固定測試集、訓練資料逐步增加 | 全國，最多約 20 萬筆 | scikit-learn |
| `fasttext_gpu.py` | fastText 架構（PyTorch），每個任務各一個模型，驗證集提早停止 | 全國全部（約 90 萬筆訓練） | scikit-learn、PyTorch、GPU |
| `svm_shared.py` | TF-IDF ＋ LinearSVC，在共用實驗包（芸菲 share_national150_100k_5fold）上跑 5 折 | 共用包 10 萬筆 | scikit-learn |
| `textcnn_gpu.py` | TextCNN（字向量＋寬 2–5 字的卷積），每個任務各一個模型，驗證集提早停止 | 全國全部 | scikit-learn、PyTorch、GPU |
| `electra_term_gpu.py` | 法律 ELECTRA 刑期（設定同芸菲 PR #15 的罪名、法條），輸出頭與評分同 TextCNN | 共用包 10 萬筆 | PyTorch、transformers、GPU |

安裝：`pip install -r models/requirements.txt`（PyTorch 依 GPU 環境另外裝；Kaggle 已內建）。

## 資料格式

CAIL 格式 `.jsonl`（或含一個 `.jsonl` 的 `.zip`），每行 `{"fact": 遮蔽後的事實, "meta": {...}}`：

- `accusation`、`relevant_articles`：罪名、法條（多標籤）；`relevant_articles_merged`：修法換條號合併後的法條（v2 起）
- `term_of_imprisonment`：`imprisonment`（有期徒刑月數）、`death_penalty`、`life_imprisonment`
- `fold`：0–9，依 jid／裁判字號雜湊固定分組
- `task_validity`：`accusation`、`article`、`imprisonment` 三個任務的標籤是否可用（v2 起）。**不合格的任務標籤是空的，要從該任務排除，不能當成負例。** 舊版沒有這個欄位時，罪名、法條有標籤就算可用，刑期看 `term_task`。

台北 v1.x 的 fold 用裁判字號、全國 v2 用 jid 計算，兩份資料的 fold 不能混用比較。

## 切分

- **開發、調參數**：`holdout_split`。測試集 = fold 0 隨機 5 萬筆；驗證集 = 其他 fold 另抽 5 萬筆；訓練 = 其他 fold 的其餘部分（取前 n 筆為巢狀子集，學習曲線用）。只用驗證集挑參數與 epoch，測試集只在最後算一次。
- **正式結果**：10-fold，測試 fold 輪流 0–9、整個 fold 當測試集，報告平均 ± 標準差。
- **時間切**（額外分析）：例如 2016–2023 訓練、2024–2025 測試，看模型能不能預測未來的案件。

## 評分

- 罪名、法條：micro-F1、macro-F1（所有類別平均）、其餘 macro（扣掉訓練集前十大類別）。預測規則：分數 > 0（或機率 > 0.5）為有，一個都沒有時取最高的。
- 刑期：區間 accuracy（1–2、3–6、7–12、13–36、37–120、>120 個月、無期／死刑）、CAIL 分數（|log(y+1) − log(ŷ+1)| 越小越高，滿分 1）。

## 在 Kaggle 執行

把 `evaluate.py` 和要跑的模型腳本放在同一個資料夾（上傳到資料集，或在 notebook 用 `%%writefile` 寫出），例如：

```
!python -W ignore fasttext_gpu.py --data /kaggle/input/<資料集>/cail_v2.jsonl --sizes 50000 --epochs 1
!python -W ignore fasttext_gpu.py --data /kaggle/input/<資料集>/cail_v2.jsonl --out /kaggle/working/fasttext.md
```

**共用實驗包**（`--shared <資料夾>`）：每一輪用 `shared_fold_assignments.csv` 的 train 訓練、valid 挑 epoch，評該輪 test 與 2025 holdout，類別用 `fixed_classes.json` 的固定清單；`fasttext_gpu.py`、`textcnn_gpu.py` 加 `--shared`，SVM 用 `svm_shared.py`。這包依標籤分布平衡抽樣，分數不能和全國資料的直接比，只在同一包的模型之間比較。

`textcnn_gpu.py` 參數用法相同。正式 10-fold：`--sizes all --test-fold k --test-n 0`，k 依序跑 0–9。結果檔開頭會寫上程式雜湊與所有參數，方便對照是哪一版、怎麼跑的。

## 目前結果（舊版全國 v2，2026-10）

測試集為 fold 0 隨機 5 萬筆，同一份訓練資料：

| 模型 | 訓練筆數 | 罪名 micro／macro | 法條 micro／macro | 刑期 CAIL |
|---|---|---|---|---|
| SVM（加權重） | 5 萬 | 0.931／0.714 | 0.893／0.530 | 0.797 |
| SVM（加權重） | 20 萬 | 0.937／0.782 | 0.902／0.610 | 0.809 |
| fastText（三任務一起訓練，lr 0.01） | 20 萬 | 0.933／0.732 | 0.896／0.560 | 0.751 |

SVM 在 40 萬筆以上 12 小時跑不完；fastText 三任務分開訓練的版本待資料定案後重跑。
