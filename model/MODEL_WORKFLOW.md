> 最新資料／類別政策：全國 2016–2025 候選 ≥150，固定 80 類罪名／102 類法條，不再逐折篩類別。共用分配與指令見 [NATIONAL150_SHARED_DATA.md](NATIONAL150_SHARED_DATA.md)。以下舊資料數字以新版說明為準。

# 模型訓練流程

主入口 `train_model.py`：固定 grid search 最佳參數 → 群組平衡 5-fold → 每折內部 VALID 選 epoch → 外層 TEST 評一次 → 彙整 TEST 平均與標準差。預設每個模型最多 3 epochs、FP32、TimeCV 關閉。

完整切分、圖示、資料角色及操作見 [OUTER_TEST_CV.md](OUTER_TEST_CV.md)。

模型仍是法律 ELECTRA CLS 768 → MLP 512 → 256 → 任務類別；只微調 encoder 最後兩層。max_length=512、batch=4、grad_accum=4、encoder LR=2e-5、head LR=1e-3、dropout=0.1。罪名與法條使用多標籤 BCE，推論至少一類；任務分開訓練。

Grid search 最佳設定已寫入 config；主程式只保留手動搜尋的註解範例，不會重新調參。TimeCV 保留獨立 time_cv.py，必須先完成主要五折才會在開啟時呼叫。舊巢狀搜尋不是現行主流程。

保留年度 2025 存為 holdout.jsonl，與外層各 fold 的 test.jsonl 分開。主要結果為外層 TEST 平均；需要保留年度評估時另行呼叫 test_evaluation.py。它不參與選 epoch，也不混入主平均。

FP16/BF16 為可選 autocast，預設 FP32。完整 GPU 加速倍數需實測。原估時表是舊資料比例的估算，新協定每折 TRAIN 較少，內部 VALID 也較少，另有訓練後外層 TEST 推論，不應直接視為新協定的實測耗時。
