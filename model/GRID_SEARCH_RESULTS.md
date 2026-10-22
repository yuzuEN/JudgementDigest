# 罪名模型 Grid Search 結果

搜尋已於2026-10-21 16:35完成，啟動時間14:39，總耗時約116分鐘。本次只用固定的2018資料fold調參，沒有啟動後續10-fold或Time CV。

TRAIN 4,331筆、VALID 1,081筆、19類。原2018資料以罪名、月份與筆數平衡分為5-fold，固定fold 01作VALID，其餘作TRAIN；各候選共用同一切分、seed=42、最多5 epochs、patience=2。以VALID最佳checkpoint Macro-F1選設定。

| Encoder LR | Dropout | 最佳VALID Macro-F1 | 最佳epoch |
|---|---:|---:|---:|
| 1e-5 | 0.1 | 54.22% | 5 |
| **2e-5** | **0.1** | **64.71%** | **5** |
| 1e-5 | 0.2 | 55.53% | 5 |
| 2e-5 | 0.2 | 62.25% | 5 |

最佳候選為candidate_02，同輪VALID Micro-F1為85.21%。已將encoder LR=2e-5、dropout=0.1寫入 `configs/accusation_cv_electra.json` 作預設；主入口不再執行搜尋，呼叫範例保留為註解。維持相同最大epochs與early-stopping規則，不把調參模型權重帶入各fold。

模型為法律ELECTRA的CLS→512→256→類別數MLP，只微調最後兩層。其餘設定為head LR=1e-3、max_length=512、batch=4、grad_accum=4、weight decay=0.01、pos_weight cap=10、threshold=0.5；此次使用MPS FP32，沒有混合精度。

來源為 `CAIL格式_刑事判決_2018-2025_v1.3_新萃取.jsonl`，SHA256 `d03aa666ee87f072fa533dd07763483a7f834dcd3eb54b9ac839a51dd05ff356`。2025未參與搜尋或評分。

這是固定小樣本fold、有限候選範圍下的調參結果，不是獨立測試或CV平均成績；4組到第5輪仍選到最佳值，不代表已證明5輪足夠收斂。未來約20萬筆資料須重新建立類別與權重；當前設定只是起點，不保證仍為最佳。

完整逐epoch結果及checkpoint／log留存本機 `Taiwan/reports/罪名模型_GridSearch_2018_20261021.md` 與對應runs目錄；PR只提供本份彙總，不包含資料集、權重或個案紀錄。
