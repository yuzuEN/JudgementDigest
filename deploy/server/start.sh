#!/usr/bin/env bash
# 容器的啟動流程：從 HF 下載模型 → 啟動後端 → 後端載入完才開 nginx（在那之前連不上，不會給半套的網站）。
# 後端或 nginx 任一個停掉，整個容器就結束，由 docker 的 restart 重新啟動。
#
# 環境變數（主機的 ~/casey/.env，範本 deploy/server/.env.example）：
#   HF_TOKEN        能讀 JudgementDigest/judgementdigest-artifacts 的 token；沒設就不下載，用示例資料
#   JD_HF_REVISION  模型 repo 的 commit，固定上線的模型版本；沒設會下載最新版並警告
#   JD_LLM_PROVIDER、GEMINI_API_KEY 等：同根目錄的 .env.example
set -euo pipefail
cd /app

if [ -n "${HF_TOKEN:-}" ]; then
  if [ -z "${JD_HF_REVISION:-}" ]; then
    echo "警告：沒有設定 JD_HF_REVISION，下載的是模型 repo 最新的版本。正式上線請固定 commit（見 docs/部署.md）。" >&2
  fi
  echo "下載模型到 $JD_ARTIFACTS_DIR（revision ${JD_HF_REVISION:-main}）"
  bash scripts/sync_civil_models.sh > /dev/null
  bash scripts/sync_criminal_models.sh > /dev/null
  bash scripts/sync_criminal_term.sh > /dev/null
  echo "模型下載完成"
else
  echo "警告：沒有設定 HF_TOKEN，不下載模型；$JD_ARTIFACTS_DIR 裡沒有的模型會改用示例資料。" >&2
fi

# 執行時不需要連 HF（刑度模型的斷詞器、設定都在 artifacts 裡）
export HF_HUB_OFFLINE=1

# 只跑一個程序：LLM 用量上限記在這個程序的記憶體裡（backend/llm/limits.py），不要加 --workers
uvicorn backend.main:app --host 127.0.0.1 --port 8000 &
backend_pid=$!

health="http://127.0.0.1:8000/api/health"
until python -c "import urllib.request; urllib.request.urlopen('$health', timeout=3)" 2> /dev/null; do
  if ! kill -0 "$backend_pid" 2> /dev/null; then
    echo "後端啟動失敗，看上面的錯誤訊息" >&2
    exit 1
  fi
  sleep 2
done
# 記下這次上線用的是真的模型還是示例資料（驗收時看這一行）
echo "health: $(python -c "import urllib.request; print(urllib.request.urlopen('$health').read().decode())")"

nginx -c /app/deploy/server/nginx.conf -e stderr -g 'daemon off;' &

# 任一個結束就讓容器結束
wait -n
echo "後端或 nginx 停止了，容器結束" >&2
exit 1
