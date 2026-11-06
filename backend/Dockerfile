# 在 repo 根目錄建置：docker compose build（見 docker-compose.yml）
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY config.py ./
COPY civil civil
COPY retrieval retrieval
COPY backend backend
# 模型與檢索資料不放進映像檔，執行時掛載（docker-compose.yml 的 volumes）
ENV JD_ARTIFACTS_DIR=/app/artifacts
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
