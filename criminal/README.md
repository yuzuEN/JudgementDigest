# criminal/：刑事

刑事判決的資料集與模型：以犯罪事實為輸入，預測罪名、法條與刑期區間。

- `models/service.py`：平台用的罪名、法條、刑度模型（TF-IDF＋logistic regression），後端 `backend/criminal_service.py` 讀它的模型檔

預定內容：

- `dataset/`：犯罪事實取得與遮蔽（`facts.py`，PR #14）、產生 CAIL 格式資料集的程式。產生的資料集檔案不進 repo
- `models/`：罪名、法條、刑期模型（PR #15、#16 的 `model/`）

負責：（待填）

資料夾的分法見 [docs/repo結構.md](../docs/repo結構.md)。
