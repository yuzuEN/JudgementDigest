> 最新資料／類別政策：全國 2016–2025 候選 ≥150，固定 80 類罪名／102 類法條，不再逐折篩類別。共用分配與指令見 [NATIONAL150_SHARED_DATA.md](NATIONAL150_SHARED_DATA.md)。以下舊資料數字以新版說明為準。

# Taiwan 判決預測模型

由 `BERT-base-prediction/Taiwan` 整理而來的程式快照（2026-10-21）。每次執行只訓練一個任務：罪名、法條或刑期；各自使用 encoder、分類頭與 checkpoint，沒有 MTL 權重共享。本目錄包含程式與設定，不包含資料集、預訓練權重、訓練結果或個案紀錄。

## 現行主入口

使用 [`train_model.py`](train_model.py)，採每折內部 VALID 選 epoch、外層 TEST 報平均（完整說明：[OUTER_TEST_CV.md](OUTER_TEST_CV.md)）。預設5-fold、每折最多3 epochs、FP32、`time_cv=false`。主模型外層TEST全部完成後，只有開啟Time CV才呼叫獨立 [`judgment_bert/time_cv.py`](judgment_bert/time_cv.py)。Grid Search已完成，呼叫保留為註解，最佳encoder LR=2e-5、dropout=0.1已寫入預設config；不需先重新搜尋。

完整操作與流程見 [MODEL_WORKFLOW.md](MODEL_WORKFLOW.md)，搜尋結果見 [GRID_SEARCH_RESULTS.md](GRID_SEARCH_RESULTS.md)，4萬／10萬／20萬筆的折數與epoch估時見 [TRAINING_ESTIMATES.md](TRAINING_ESTIMATES.md)。

```bash
python train_model.py --print-config
# 正式訓練時替換資料與新的輸出目錄；預設不跑額外Time CV
python train_model.py --data /本機路徑/資料.jsonl --output runs/new_data_5fold
# 可加 --folds 10、--epochs 3、--precision bf16；需要額外時間分析才加 --time-cv
```

## 目前架構

現有 `configs/accusation_electra.json`、`configs/article_electra.json` 使用以下設定。雖然類別名稱是 `SingleTaskBert`，encoder 實際由設定決定，目前兩份設定均為法律 ELECTRA。

```text
判決事實 fact
  → 與 encoder 相同的 tokenizer
  → 前 512 tokens（含 CLS/SEP，超長截斷）
  → hfl/chinese-legal-electra-base-discriminator
  → CLS 向量（768 維）
  → Linear(768,512) → ReLU → Dropout(0.1)
  → Linear(512,256) → ReLU → Dropout(0.1)
  → Linear(256,類別數) → logits
```

凍結 embeddings 與前十層 encoder，只微調最後兩層及分類頭。類別數由資料的 `manifest.json` 讀取，不寫死。

| 任務 | 標籤與 loss | 推論 |
|---|---|---|
| 罪名 accusation | 多標籤；BCEWithLogitsLoss | sigmoid > 0.5；皆未達門檻時取最高分 |
| 法條 article | 多標籤；BCEWithLogitsLoss | sigmoid > 0.5；皆未達門檻時取最高分 |
| 刑期 imprisonment | 單標籤多分類；CrossEntropyLoss | argmax（softmax 可用於呈現機率） |

目前罪名／法條：batch 4、梯度累積 4（有效 batch 16）；AdamW，encoder LR 2e-5、分類頭 LR 1e-3、weight decay 0.01、梯度裁剪 1.0。主入口最多 3 epochs，驗證 Macro-F1 連續 2 輪未改善即停止，保存最佳權重。warmup_ratio=0，未啟用 LR scheduler。多標籤 pos_weight 僅依訓練集計算，逐類上限 10。seed=42。

程式另外支援 BERT-base、CLS／mean／attention pooling、linear／MLP head、full／last_n／frozen 微調，以及全文 chunk 的 mean／attention 聚合；這些是可選變體，並非上述兩份設定的預設。直接執行 CLI 而未載入 config 時，預設為 BERT-base、linear head、full 微調。

## 檔案

| 路徑 | 用途 |
|---|---|
| `judgment_bert/model.py` | encoder、pooling、分類頭、凍結與分塊聚合 |
| `judgment_bert/encoding.py` | tokenization、Dataset、padding 與 chunk collator |
| `judgment_bert/train.py` | 設定讀取、訓練、驗證、選模與輸出 |
| `judgment_bert/data.py` | CAIL JSONL 前處理、年份切分、標籤篩選、刑期分組及去重 |
| `judgment_bert/analyze.py` | 前處理共用的資料讀取，以及 token 長度統計 |
| `configs/` | 現有罪名／法條實驗設定 |
| `evaluate.py` | 與 PR #16 對齊的 NumPy 共用切分／評分；at_least_one 與 multilabel_scores |
| `judgment_bert/test_evaluation.py` | 所有 fold 完成後，以 VALID 最佳 checkpoint 評估同一保留年度 TEST |
| `../tests/test_model*.py` | 不依賴 torch 的切分、刑期邊界、實驗流程與共用評分測試，既有 CI 會執行 |
| `tests/` | 需要 torch 的架構、AMP、設定與 checkpoint 評估測試，使用合成資料 |

## 安裝與執行

以下命令都在 `JudgementDigest/model/` 執行。模型相依套件獨立於爬蟲環境；Python 3.10+ 建議。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

# 只查看設定，不下載模型或讀取資料集
python -m judgment_bert.train --config configs/accusation_electra.json --print-config

# 已在本機準備好資料後才執行訓練
bash run_accusation_electra.sh --data /本機路徑/資料.jsonl --output runs/new_data_5fold
bash run_article_electra.sh

# 測試不下載預訓練權重；使用本機建立的 tiny encoder/tokenizer
python -m unittest discover -s tests -v
```

設定中的 `data_dir` 與 `output` 相對於執行時的工作目錄。罪名設定指向 `data/prepared_v1.2_closed/accusation`，法條指向 `data/prepared_v1.3_closed/article`；資料需自行準備或以 `--data-dir /本機路徑` 指定。CLI 同名參數優先於 config。

本份法條設定將來源的 `device=mps` 改為 `auto`，依 CUDA → MPS → CPU 選擇；將 `evaluate_test=true` 改為 `false`，測試集評估須明確加入 `--evaluate-test`。其餘設定沿用來源。正式訓練首次使用會下載 encoder 與 tokenizer。

## 資料與切分

來源是含 `fact` 與 `meta` 的 CAIL 格式 JSONL；須有 `meta.year`。罪名使用 `meta.accusation`，法條使用保留法律名稱的 `meta.relevant_articles`，兩者均為字串陣列。刑期使用 `term_task`、`sentence_kind`、`term_of_imprisonment`；拘役選項另讀取 `detention_days` 與 `reextraction` 的安全萃取資訊。

```bash
python -m judgment_bert.data \
  --data /本機路徑/CAIL資料.jsonl \
  --task accusation --output data/prepared_v1.2_closed/accusation
```

法條改用 `--task article` 與對應 output。前處理輸出 `train.jsonl`、`valid.jsonl`、`test.jsonl`、`manifest.json`；已存在的 split 不覆寫。預設按年份切分：2018–2023 訓練、2024 驗證、2025 測試（程式會將所有 ≤2023 的年份歸入訓練，來源資料需自行確認年份範圍）。一般前處理不使用原始 `meta.fold`；K-fold 與 time CV 另由 `cross_validation.py` 產生。

罪名／法條以訓練集頻率 ≥30 建立固定類別，所有 split 只保留這些標籤，移除標籤為空的案件；不要求另一任務標籤有效，也沒有額外事實長度門檻。同案跨集合時保留較早集合，預設亦移除與較早集合事實全文完全相同的資料。這不包含近似文字去重。

## 刑期狀態

刑期輸出設計尚在討論，沒有新增正式訓練 config。預設維持原 Taiwan 的 11 類：≤6、>6–12、>12–18、>18–24、>24–30、>30–36、>36–60、>60–<120、≥120 月，加上無期徒刑與死刑。只保留 `term_task=true` 且刑種合格的資料，拘役與混合刑預設排除。

可用 `--mtl-bins` 重現舊 MTL：先 `int(months)` 再分組，保留 ≥120 月為末組。可用 `--include-detention` 將安全萃取的單被告拘役獨立加入第 12 類；須有正的有限日數、`term_reason=detention_not_prison`、`defendant_status=單被告`。**尚未實作將拘役日數換算成月後合併分組，也尚未實作新的短刑期細分。** 兩個選項供刑期前處理使用。

## 輸出與版控

每次訓練的獨立 output 目錄會保存 `best.pt`、tokenizer、encoder config、實際 `run_config.json`、資料 manifest 與指標。已含 `best.pt` 的目錄會拒絕覆寫。預設只以 VALID 選模，TEST 評估須明確啟用。

本目錄 `.gitignore` 排除本機 `data/`、`runs/`、`reports/`、JSONL、CSV 與模型權重，避免將資料集及訓練產物加入版控。這份程式快照不會隨原 Taiwan 目錄自動同步。

## 既有研究入口

直接操作單fold搜尋、固定設定CV的舊入口仍保留，見 [CROSS_VALIDATION.md](CROSS_VALIDATION.md)。目前主程式直接使用已選設定，不再先跑搜尋。先前巢狀訓練已取消，程式及結果保留供重現，見 [NESTED_CV.md](NESTED_CV.md)。

## 與 baseline 共用評估與 CI

統一使用 `model/` 作為模型目錄。本次納入 PR #16 的 `models/evaluate.py` 與其離線測試，保留原本函式介面並置於 `model/evaluate.py`；baseline 的訓練檔仍由 PR #16 在合併後移入，沒有在兩個 PR 各複製一套。ELECTRA 呼叫相同的 `at_least_one` 與 `multilabel_scores`：sigmoid 分數嚴格大於 0.5 為正例；若皆未達門檻，選最高分一類。相同最高分時採類別順序的第一個。

新執行的訓練／VALID／TEST 均使用至少一類規則，metrics 另記錄 prediction_policy。正在執行的歷史 run 不改既有 VALID 選模規則，避免 fold 間混用；其事後 TEST 明確採新規則並另存結果。改變預測規則無須重訓權重，但不能把舊 VALID 分數宣稱為新規則結果。

NumPy-only 測試已移到根目錄 `tests/`，由現有 CI 的 `python -m unittest discover -s tests -t . -v` 執行；不在爬蟲 CI 安裝 torch。模型測試仍可在安裝 model/requirements.txt 後，於 model/ 執行 `python -m unittest discover -s tests -v`。

獨立最終 TEST 評估（不重新訓練、不使用 TEST 選 checkpoint）：

```sh
python -m judgment_bert.test_evaluation --prepared runs/experiment/prepared_main --runs runs/experiment/main --output runs/experiment/test_2025
```

此工具要求各 fold 的 TEST 記錄與類別順序完全相同，且所有 VALID 結果已完成。TEST 成績另存 test_summary.json 與 TEST_RESULTS.md；平均及樣本標準差描述不同模型在同一批 TEST 的表現，不是五份獨立 TEST。

目前資料的來源 fold 分佈、96 類原因與評估設計差異見 [EVALUATION_ALIGNMENT.md](EVALUATION_ALIGNMENT.md)。

本次變更：每折四份開發資料再切約 10% 作內部 VALID，留下的原 fold 作外層 TEST；2025 另存 holdout.jsonl。>=150 次固定類別清單目前僅提出建議，沒有自動變更類別政策。
