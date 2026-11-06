> 此為先前巢狀驗證流程，已停止作為目前實驗主流程；現行流程見 CROSS_VALIDATION.md。

# 平衡 K-fold 與巢狀時間驗證

目前以罪名為主，法條共用流程。預設 **5-fold**，可用 `--folds 10`。以下命令在 Taiwan 或 `JudgementDigest/model/` 目錄執行，先啟用已安裝 requirements 的 Python 環境。資料集與訓練權重只存本機。

## 內層如何平衡

先將同案、同文件、完全相同事實（去除頭尾空白）的紀錄建立連通群組，間接連結亦歸在同組。群組不可拆分。分配時同時最小化三種分佈差異，三者等權：

- 多標籤罪名／法條筆數：一筆多罪會計入每個罪名，不只取主要罪名。
- 裁判月份筆數：各折都混合1–12月；多年資料按月序合併，不把某月固定當成某一折。
- 總資料筆數。

使用固定 seed 的貪婪演算法，先分配帶有罕見標籤的群組，再依標準化平方差選擇折；筆數亦有容量限制。這是近似平衡，不保證數學上的最優或每類完全等量。少於折數的少數罪名、大群組與罪名共現會限制可達平衡。開發紀錄必須有有效的 ISO `judgment_date`，且年份與 `meta.year` 一致；缺漏會報錯，不猜月份。

分層只使用當下開發範圍的原始標籤與日期，分類頭的類別另由每折 TRAIN 頻率 ≥30 決定。VALID只保留該折訓練類別交集，篩完無標籤的案件排除；pos_weight 也只依該折 TRAIN 計算。標籤篩選可能使原本平衡的折數略有差異。

## 建議：外層 Time CV、內層 K-fold

| 外層 | 內層5-fold與完整重訓範圍 | 外層一次性驗證 |
|---|---|---|
| valid_2019 | 2018 | 2019 |
| valid_2020 | 2018–2019 | 2020 |
| valid_2021 | 2018–2020 | 2021 |
| valid_2022 | 2018–2021 | 2022 |
| valid_2023 | 2018–2022 | 2023 |
| valid_2024 | 2018–2023 | 2024 |

2025保留為獨立最終 TEST，不會寫入任一內層或外層資料檔。此指令只實作巢狀驗證；最終全開發集模型與2025測試另行執行。

每個外層依序：

1. 只用過去年份建立內層群組與平衡切分；外層年份與更晚資料不能改變內層分配。
2. 每個候選 config 跑完整內層 K-fold，各折從同一預訓練 encoder 重新開始。每個 epoch 用內層 VALID 選 checkpoint、early stopping。
3. 以內層平均 Macro-F1 選候選設定，不挑最高分的單一 fold；平手保留最先提供的候選。僅一套 config 時，用其內層結果決定重訓輪數。
4. 取勝出設定各折最佳 epoch 的中位數、向上取整，作為完整過去年份重訓的固定 epochs。
5. 重新初始化模型，使用完整過去年份與重新建立的訓練類別訓練。重訓不讀 VALID、不 early stopping，保存最後一輪 checkpoint。
6. 重訓結束後才在下一年外層資料評分一次。外層分數不參與這一輪的設定或 epoch 選擇。

外層若與較早訓練資料有同案／文件／相同事實連通關係，排除較晚的外層紀錄，保留過去訓練資料。

```bash
# 準備：預設5-fold；需要10-fold時加 --folds 10 並選新目錄
python -m judgment_bert.nested_cv prepare \
  --data /本機路徑/CAIL格式_刑事判決_2018-2025_v1.3_新萃取.jsonl \
  --task accusation --output data/nested_v1.3_accusation_5fold

# 訓練：單一設定；data_dir/output 由 runner 依折覆寫
python -m judgment_bert.nested_cv train \
  --prepared data/nested_v1.3_accusation_5fold \
  --configs configs/accusation_cv_electra.json \
  --output runs/nested_v1.3_accusation_5fold

# 多組設定比較：--configs config_A.json config_B.json
# 單獨跑一個外層：加 --outer valid_2019

python -m judgment_bert.nested_cv summarize \
  --prepared data/nested_v1.3_accusation_5fold \
  --output runs/nested_v1.3_accusation_5fold
```

法條改成 `--task article`、`--configs configs/article_electra.json`，並使用獨立 output。刑期未納入這個巢狀入口，不變更組員的刑期設計。

單一 config、5-fold與6個外層，總共會正式訓練 **30個內層模型＋6個重訓模型＝36次**；10-fold為66次。多候選會再增加內層次數。所有折不承接其他折的權重。候選模型需用相同的資料折進行比較。單獨執行各折時，runner會先核對同一output的設定與資料計畫；彙整時再次核對實際run_config，拒絕混合不同設定的折。

## 輸出與稽核

每個外層的 prepared 目錄包含：

- `inner/fold_XX/`：train、valid、空的test檔、資料manifest與source-line分配表。
- `inner/cv_manifest.json`：分層前後筆數、各折月份／來源標籤分佈，以及篩選後實際 validation targets 統計。
- `refit/`：完整過去train、空的valid檔、外層下一年資料與manifest。
- 根目錄 `nested_manifest.json`：來源SHA256、保留TEST年份、全部外層與筆數。

為沿用共用訓練器，`refit/test.jsonl` 存的是**外層驗證年**，不是2025最終TEST；manifest明列 `evaluation_role=outer_valid`，log顯示 `[OUTER_VALID]`。內部 `metrics.json` 的 `test` 欄位在這個模式代表外層評分，巢狀彙整會改以 `outer_valid` 呈現。

run 目錄保存各候選的內層結果、`selection.json`（勝出設定、內層分數與epoch規則）、重訓checkpoint與 `nested_summary.json`。彙整檢查資料manifest、固定epoch與無中途VALID選模；拒絕 tiny-smoke。缺少外層時 `complete=false`，不將部分結果當作完整巢狀驗證。

分數為各外層年份的未加權平均與樣本標準差，不是pooled OOF指標。各折／年份的類別由各自TRAIN建立，因此類別範圍可不同；需連同類別數、排除筆數與逐年結果解讀。不要用2025結果反覆挑設定。

現有來源資料曾經上游全年度頻率篩選或固定法條白名單處理（見Taiwan既有資料分析報告）；本流程隔離模型端的分折、類別建立與選模，但不能恢復上游已排除的樣本。因此不能宣稱整條資料管線完全沒有未來選樣資訊；嚴格時間研究需另匯出未做全年度篩選的候選資料。

prepared 或單個run目錄已存在時拒絕覆寫。重建用新目錄；已有完成的其他外層時，可用 `--outer` 執行尚未建立的外層。未實作中途checkpoint續訓或部分候選自動續跑。

## 原本的非巢狀入口

仍支援 `judgment_bert.cross_validation`：

```bash
# 2018–2024混合做平衡5-fold，2025獨立保留
python -m judgment_bert.cross_validation prepare \
  --data /本機路徑/資料.jsonl --task accusation \
  --mode kfold --output data/balanced_accusation_5fold

python -m judgment_bert.cross_validation train \
  --prepared data/balanced_accusation_5fold \
  --config configs/accusation_cv_electra.json --output runs/balanced_accusation_5fold
```

`--mode time` 則只跑逐年訓練／VALID選checkpoint，不含內層K-fold；它與本頁建議的巢狀外層一次性評分不同。舊版已產生的10-fold資料不會自動變成平衡切分，應從原始JSONL以新目錄重建。

## 驗證狀態

已準備本機v1.3罪名的6個外層、每層5個內層fold與重訓資料。平衡前處理後，原始月份計數各折最多差1筆；各折套用TRAIN類別篩選後最多差6筆。已驗證群組防洩漏、年份隔離、候選選擇與固定epoch流程，並用隨機tiny model跑通內層與重訓評分。這些不是正式模型效果；完整ELECTRA巢狀訓練尚未執行。
