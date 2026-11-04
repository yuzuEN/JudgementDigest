# backend/：API 伺服器

Python、FastAPI。接收使用者輸入，遮名後呼叫 LLM 追問，再呼叫民事、刑事模型與相似判決檢索，組成結果回傳。

**尚未放入程式。** 預定內容：

- `main.py`
- `routers/`：`civil.py`、`criminal.py`、`retrieval.py`
- `schemas.py`：輸入輸出格式
- `masking.py`：送出前遮名
- `llm.py`：LLM 追問（付費 API 金鑰只放在伺服器端）

負責：（待填）

資料夾的分法見 [docs/repo結構.md](../docs/repo結構.md)。
