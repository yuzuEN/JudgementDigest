> 現行主入口已改為每折內部 VALID 選模、外層 TEST 評分，見 [OUTER_TEST_CV.md](OUTER_TEST_CV.md)。以下保留舊協定的紀錄／指令／估算，不代表新協定的訓練結果。

> 現行主入口為 `train_model.py`，Grid Search不再預設呼叫，Time CV獨立且預設關閉；操作見 [MODEL_WORKFLOW.md](MODEL_WORKFLOW.md)。以下保留單獨重現搜尋與CV的指令。

# 單一 fold Grid Search → 固定設定10-fold／時間分析

目前主流程不做巢狀驗證。先以一份固定TRAIN／VALID fold搜尋超參數，鎖定最佳設定後，分別重新訓練10-fold（主要結果）與Time CV（額外分析）。2025保留為獨立最終TEST，以下指令均不評估它。

## 1. 固定一個調參fold

預設範例使用既有2018資料的固定fold：`data/nested_v1.3_accusation_5fold/valid_2019/inner/fold_01`，TRAIN=4,331、VALID=1,081。這只是借用已建立的單一資料切分，不執行舊巢狀runner，也不接續其checkpoint。

使用2018調參可避免為2019以後的時間分析使用未來年份選設定。若改用2018–2024混合fold調參，程式會在Time分析標記 `time_uses_future_tuning=true`，此時只能解讀為固定設定的跨年比較，不是嚴格模擬過去預測未來。

`configs/accusation_grid.json` 的預設範例：encoder LR為1e-5／2e-5、dropout為0.1／0.2，共4組。其餘沿用 `accusation_cv_electra.json`，最多5 epochs、patience 2、固定seed。Grid JSON可自訂其他訓練參數候選，但不能更換資料、輸出位置、seed或評估控制旗標。

```bash
python -m judgment_bert.grid_search tune \
  --data-dir data/nested_v1.3_accusation_5fold/valid_2019/inner/fold_01 \
  --config configs/accusation_cv_electra.json \
  --grid configs/accusation_grid.json \
  --output runs/accusation_grid
```

先驗證所有候選設定，再逐組從預訓練encoder重新訓練。依固定VALID的最佳checkpoint Macro-F1選設定；平手保留先列的組合。輸出每組實際run_config、資料manifest與分數，並產生 `search_summary.json`、`best_config.json`。

選出的 **設定** 才會進入後續CV，不帶入調參模型權重。`selected_epoch` 只是搜尋紀錄；目前保留相同的最大epochs與early-stopping規則，各評估fold依自己的VALID選checkpoint，沒有強制固定為調參fold的最佳epoch。

## 2. 主要結果：平衡10-fold

```bash
python -m judgment_bert.cross_validation prepare \
  --data /本機路徑/CAIL格式_刑事判決_2018-2025_v1.3_新萃取.jsonl \
  --task accusation --mode kfold --folds 10 \
  --output data/flat_v1.3_accusation_10fold

python -m judgment_bert.grid_search evaluate \
  --search runs/accusation_grid \
  --prepared data/flat_v1.3_accusation_10fold \
  --output runs/accusation_main_10fold --role main
```

2018–2024以同案／同文件／相同事實建立不可拆分群組，同時近似平衡多標籤罪名、月份與筆數。每折混合各月份，按固定seed分配；少數標籤及大群組不能保證完全等量。須有有效ISO `judgment_date`，且與 `meta.year` 一致。

每折只以自己的TRAIN頻率≥30建立類別，pos_weight也只來自TRAIN；VALID只保留該折類別交集，空標籤案件排除。這可能使篩選後分佈略有差異。每折重新初始化，跑完10次後彙整平均與樣本標準差，不是在同一模型上連續訓練10次，也不是模型權重平均。

共用前處理CLI仍預設5-fold；本主實驗準備指令明確指定10-fold。舊版非平衡10-fold檔案不會自動轉換，須用新目錄重建。

## 3. 額外分析：同設定的Time CV

```bash
python -m judgment_bert.cross_validation prepare \
  --data /本機路徑/CAIL格式_刑事判決_2018-2025_v1.3_新萃取.jsonl \
  --task accusation --mode time \
  --output data/flat_v1.3_accusation_time

python -m judgment_bert.grid_search evaluate \
  --search runs/accusation_grid \
  --prepared data/flat_v1.3_accusation_time \
  --output runs/accusation_time_analysis --role time
```

依序2018→2019、2018–2019→2020，直到2018–2023→2024，共6個時間切分。它們都使用同一份搜尋後設定，不再逐年跑內層K-fold或grid search。每個年份仍重新訓練並用自己的VALID選checkpoint，因此這是時間驗證分析，不是完全未參與checkpoint選擇的最終測試。

## 輸出、檢查與限制

- `flat_protocol.json` 記錄搜尋來源、鎖定設定、評估資料及主要／額外角色。拒絕未完成的搜尋、被修改的best_config、不同來源／任務、混合不同超參數或資料計畫的fold。
- 每折保存checkpoint、實際設定、資料manifest及metrics；`cv_summary.json`彙整各折最佳VALID指標。少折時 `complete=false`。可使用既有 `cross_validation summarize` 重新計算原始彙整。
- 這是**非巢狀評估**：調參樣本可能再次出現在10-fold中，因此平均分數可能有選模偏樂觀，應在報告揭露，並保留2025作最終獨立測試。各折類別空間亦可能不同，平均不是固定共用類別的pooled OOF分數。
- 既有來源有上游全年度篩選／白名單的選樣限制，本流程無法恢復已排除樣本。不能宣稱整條資料管線完全沒有未來選樣資訊。
- 所有資料、權重、log存本機，不加入版控。新流程拒絕覆寫既有搜尋／run。刑期由其他組員處理，不更改分組。

4組候選＋主要10-fold＋時間分析6次，合計20次模型訓練。這些模型資料量不同，不能單靠模型數精確估時；10-fold使用較完整資料，仍可能耗時很長。Time分析可另行啟動。

先前巢狀程式保留供重現，操作見 [NESTED_CV.md](NESTED_CV.md)；已停止的實驗輸出保留，未刪除。
