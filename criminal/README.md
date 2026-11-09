# criminal/：刑事

刑事判決的資料集與模型：以犯罪事實為輸入，預測罪名、法條與刑期區間。

| 檔案 | 內容 |
|---|---|
| `models/service.py` | 平台模型：TF-IDF（字元 1–2 gram）＋LinearSVC＋機率校正，預測罪名、法條與 6 個刑度區間。後端 `backend/criminal_service.py` 讀它的模型檔 |
| `models/lay_terms.py` | 把口語換成判決書用語（偷→竊取、打→毆打…）；模型與檢索的輸入都先經過這一步 |
| `models/electra_bucket_gpu.py` | 刑度 ELECTRA（6 區間）的 Kaggle 訓練與 ONNX 匯出；後端程式已寫好，目前停用 |
| `dataset/facts.py` | 犯罪事實取得與本案罪名、法條遮蔽（PR #14） |
| `models/` 基準模型 | SVM、fastText、TextCNN、ELECTRA 與共用評估 `evaluate.py`（PR #16）；內外層 K-fold 選模（PR #15） |

產生 CAIL 格式資料集的程式還有寫死的路徑，整理後放進 `dataset/`。資料集檔案、模型檔不進 repo。

## 平台模型（`criminal_v1`）

```bash
python -m criminal.models.service train --data <CAIL 格式 .jsonl>                  # → artifacts/criminal_v1/
python -m criminal.models.service metrics --data <同一份 .jsonl> --lines <測試行號>   # 測試結果寫進 meta.json
python -m criminal.models.service evaluate --shared <共用實驗包資料夾>              # 共用包 fold_01：比較 LinearSVC 與 LR
```

- 罪名、法條：每類各一個 LinearSVC（class_weight balanced），在留下的 10% 訓練資料上用 Platt scaling 換成機率
- 刑度：6 類 LinearSVC，再用 LR 把分數換成機率。區間為拘役、罰金／1～6 個月／7～12 個月／1～3 年／3～10 年／10 年以上；只判罰金算進第一區，死刑、無期算進最後一區，有期徒刑併拘役不用
- 法條：從訓練資料裡這個罪名最常見的 3 條中，挑法條模型機率最高的；修法換過條號的（洗錢防制法第 14 條→第 19 條等）顯示現行條號並註明舊條號
- 目前的模型：全國 v2（2016–2025）隨機 30 萬筆訓練，罪名 89 類、法條 110 類；另外 1 萬筆測試，罪名 top-1 0.979、法條 micro-F1 0.954、刑度區間 accuracy 0.810（差一區以內 0.980）
- 限制：隨機單次切分，沒有做交叉驗證或 2025 測試；資料是自然分布（1～6 個月約占六成），和研究用的均衡樣本不能直接比。研究結果見根目錄 README

負責：資料集、事實遮蔽、基準模型、平台模型：丁瑞萱；ELECTRA 罪名／法條、模型融合：張芸菲

資料夾的分法見 [docs/repo結構.md](../docs/repo結構.md)。
