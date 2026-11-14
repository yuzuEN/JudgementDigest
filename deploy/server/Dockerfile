# 上線用的映像：前端（nginx）和後端（uvicorn）放在同一個容器，對外只開 7860。
# 主機上用 deploy/server/deploy.sh 建置與換版（CI 也是跑這支）；說明見 docs/部署.md。
# 本機試跑（在 repo 根目錄）：docker build -f deploy/server/Dockerfile -t casey .
# 本機開發照舊用根目錄的 docker-compose.yml。

# ── 前端：和 frontend/Dockerfile 相同的建置 ──
FROM node:20-alpine AS frontend
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ── 後端 + nginx ──
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends nginx \
    && rm -rf /var/lib/apt/lists/*
# 用一般使用者（uid 1000）執行，不用 root
RUN useradd -m -u 1000 user
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY config.py ./
COPY civil civil
COPY criminal criminal
COPY retrieval retrieval
COPY backend backend
COPY scripts/sync_civil_models.sh scripts/sync_criminal_models.sh scripts/sync_criminal_term.sh scripts/
COPY deploy/server/nginx.conf deploy/server/start.sh deploy/server/
COPY --from=frontend /app/dist static
# Windows 取出的檔案可能是 CRLF，shell 腳本在 Linux 會跑不起來；順便確認下載模型用的 hf 指令在（transformers 會一起裝 huggingface_hub）
RUN sed -i 's/\r$//' scripts/*.sh deploy/server/start.sh \
    && chmod +x scripts/*.sh deploy/server/start.sh \
    && hf --help > /dev/null

USER user
# 模型下載到 /home/user/artifacts（docker-compose.yml 掛主機的資料夾，重啟不用重新下載）
ENV HOME=/home/user \
    JD_ARTIFACTS_DIR=/home/user/artifacts \
    TOKENIZERS_PARALLELISM=false \
    HF_HUB_DISABLE_PROGRESS_BARS=1 \
    PYTHONUNBUFFERED=1
EXPOSE 7860
CMD ["deploy/server/start.sh"]
