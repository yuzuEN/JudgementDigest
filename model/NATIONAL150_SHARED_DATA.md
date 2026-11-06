# 全國 ≥150 固定類別與共用五折

依目前使用者決定，在 2016–2025 全國 921,522 筆合格候選中，罪名與法條各篩來源頻率 ≥150。得到罪名 80 類、法條 102 類；移除低頻 active labels 後，任一任務為空即排除，剩 919,092 筆再均衡抽取 100,000 筆。全期類別篩選包含 2025，不能宣稱整條選樣流程是純歷史回溯。

`sample_balanced.py` 以 `--min-label-frequency 150 --frequency-through-year 2025` 重現。輸出 `fixed_classes.json` 與抽樣來源行號／雜湊／分佈報告；原始低頻標籤保存在 sampling_original_* 稽核欄位，不作 active target。

```sh
python sample_balanced.py --source /path/cail_v2.jsonl --output data/new_national150 --size 100000 --seed 42 --min-label-frequency 150 --frequency-through-year 2025
```

主入口 config 現在預設 `first_year=2016`、`min_label_freq=150`、`class_list=data/source/fixed_classes.json`。資料 JSONL 與該清單需一併提供。當 class_list 指定時，150 是來源類別資格門檻，**不是每 fold TRAIN 門檻**；prepare() 保留完整固定清單與順序，不因該 fold 出現不到 150 次而移除類別。仍記錄實際 TRAIN 頻率作稽核。

原每折 TRAIN ≥30 的路徑保留作相容用途：不提供 class_list 時維持原行為。設定或共用清單的來源門檻不一致會拒絕執行。

## 讓罪名、法條與 baseline 共用同一切分

先準備罪名五折：

```sh
python -m judgment_bert.cross_validation prepare --data data/new_national150/shared_100k.jsonl --output data/acc_shared --mode kfold_test --folds 5 --first-year 2016 --test-year 2025 --min-label-freq 150 --class-list data/new_national150/fixed_classes.json
```

法條明確重用已準備的分配，不重新按法條分折：

```sh
python -m judgment_bert.cross_validation prepare --data data/new_national150/shared_100k.jsonl --output data/art_shared --task article --mode kfold_test --folds 5 --first-year 2016 --test-year 2025 --min-label-freq 150 --class-list data/new_national150/fixed_classes.json --split-plan data/acc_shared
```

`--split-plan` 驗證來源 JSONL 雜湊、種子／年份／模式／折數，並確認同案／相同 fact 不跨角色及保留年度隔離。主入口也可使用 `--class-list` 與 `--split-plan`。

給 baseline 的交付包另有 `shared_fold_assignments.csv`，以 sample_line_1based 和 jid 對應 10 萬筆原始記錄，各 fold_01 至 fold_05 欄位標記 train／valid／test／holdout／purged。baseline 必須使用相同角色，而非再呼叫來源 meta.fold、fold // 2 或隨機 holdout_split。固定 class_list 的 label order 與至少一類預測規則也需一致。

## 本機新版資料驗證（非訓練成績）

每折約 64,800 TRAIN、7,200 INTERNAL VALID、18,000 OUTER TEST，2025 HOLDOUT 為 9,984 筆。所有 fold 都有同一份 80 類罪名／102 類法條，兩任務分配完全相同。四個角色間同案、文件、相同 fact 重疊為 0。2025 原 9,999 筆，其中 15 筆與較早資料相連而排除。

512 tokens 完整涵蓋新樣本的 74.605%；平均 436.07、中位數 355、P95 955 tokens。以實際 ELECTRA tokenizer 未截斷量測，包含兩個特殊 token。舊版 95／96 類、73.869% 涵蓋率等數字屬不同樣本／政策，不要混用。

資料集、分配 CSV、固定清單、原始來源及權重未放入 GitHub；僅提交程式、合成測試和彙總文件。
