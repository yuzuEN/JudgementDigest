#!/usr/bin/env bash
# 在主機上部署這份程式碼：建映像 → 換掉容器 → 等 /api/health 四項都是真的模型 → 失敗就換回上一版。
# 手動：在主機的 repo 根目錄執行 bash deploy/server/deploy.sh
# CI：.github/workflows/deploy.yml 在主機的自架 runner 上執行同一支。
#
# 主機上的位置（CASEY_HOME，預設 ~/casey）：.env、artifacts/ 放這裡；docker-compose.yml 每次從 repo 複製過去。
set -euo pipefail

CASEY_HOME="${CASEY_HOME:-$HOME/casey}"
HEALTH_URL="http://127.0.0.1:7860/api/health"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-1200}"   # 秒；第一次要下載約 5 GB 的模型
KEEP_IMAGES=3                              # 除了 current、previous，再留最近幾版

repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
tag="$(git -C "$repo" rev-parse --short=12 HEAD 2>/dev/null || date +%Y%m%d%H%M%S)"
compose=(docker compose -f "$CASEY_HOME/docker-compose.yml")

[ -f "$CASEY_HOME/.env" ] || { echo "找不到 $CASEY_HOME/.env，先照 docs/部署.md 建立（範本 deploy/server/.env.example）" >&2; exit 1; }
mkdir -p "$CASEY_HOME/artifacts"

# /api/health 回應、而且民事、金額、刑事、刑度都是真的模型才算成功
healthy() {
  python3 - "$HEALTH_URL" <<'EOF'
import json, sys, urllib.request
try:
    h = json.load(urllib.request.urlopen(sys.argv[1], timeout=5))
except Exception:
    sys.exit(1)
want = {"civil": "model", "amount": "model", "criminal": "model", "criminal_sentence": "electra"}
bad = {k: h.get(k) for k, v in want.items() if h.get(k) != v}
if bad:
    print(f"health 回應了，但不是真的模型：{bad}", file=sys.stderr)
    sys.exit(2)
EOF
}

wait_healthy() {
  local waited=0 code
  while [ "$waited" -lt "$HEALTH_TIMEOUT" ]; do
    healthy && return 0 || code=$?
    [ "$code" = 2 ] && return 1          # 已經啟動但模型不對，不用再等
    sleep 5; waited=$((waited + 5))
  done
  echo "等了 ${HEALTH_TIMEOUT} 秒還沒好" >&2
  return 1
}

echo "== 建映像 casey:$tag"
docker build -f "$repo/deploy/server/Dockerfile" -t "casey:$tag" "$repo"

if docker image inspect casey:current > /dev/null 2>&1; then
  docker tag casey:current casey:previous
fi
cp "$repo/deploy/server/docker-compose.yml" "$CASEY_HOME/docker-compose.yml"
docker tag "casey:$tag" casey:current

echo "== 換成新版"
"${compose[@]}" up -d
if wait_healthy; then
  echo "== 部署成功：casey:$tag"
  curl -s "$HEALTH_URL"; echo
else
  echo "== 新版沒通過檢查，換回上一版" >&2
  "${compose[@]}" logs --tail 40 casey >&2 || true
  if docker image inspect casey:previous > /dev/null 2>&1; then
    docker tag casey:previous casey:current
    "${compose[@]}" up -d
    wait_healthy && echo "已換回上一版" >&2 || echo "上一版也沒通過檢查，請手動處理" >&2
  fi
  exit 1
fi

# 清掉舊映像：留 current、previous 和最近 KEEP_IMAGES 版
in_use="$(docker image inspect casey:current casey:previous --format '{{.Id}}' 2>/dev/null || true)"
docker images casey --format '{{.CreatedAt}}\t{{.Tag}}\t{{.ID}}' \
  | grep -vE $'\t(current|previous)\t' | sort -r | tail -n +$((KEEP_IMAGES + 1)) \
  | while IFS=$'\t' read -r _ old id; do
      grep -q "$id" <<< "$in_use" || docker rmi "casey:$old" > /dev/null || true
    done
docker image prune -f > /dev/null
