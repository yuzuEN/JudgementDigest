#!/usr/bin/env bash
# 打開／關掉自動部署（auto-deploy.sh 每 5 分鐘檢查一次 main）。預設是關的。
# 用法（在主機上）：
#   sudo bash ~/JudgementDigest/deploy/server/auto-deploy-setup.sh on      # 打開
#   sudo bash ~/JudgementDigest/deploy/server/auto-deploy-setup.sh off     # 關掉
#   bash ~/JudgementDigest/deploy/server/auto-deploy-setup.sh status       # 看狀態（不用 sudo）
# 自動部署用執行 sudo 的那個帳號跑（要在 docker 群組裡），repo 在它的 ~/JudgementDigest。
set -euo pipefail

case "${1:-}" in
  status)
    systemctl is-enabled casey-auto-deploy.timer 2>/dev/null || echo "沒有安裝"
    systemctl list-timers casey-auto-deploy.timer --no-pager 2>/dev/null || true
    cat "${CASEY_HOME:-$HOME/casey}/auto-deploy.state" 2>/dev/null || echo "（還沒處理過任何 commit）"
    exit 0 ;;
  on|off) ;;
  *) echo "用法：sudo bash $0 on|off|status" >&2; exit 1 ;;
esac

[ "$(id -u)" = 0 ] || { echo "請用 sudo 執行：sudo bash $0 $1" >&2; exit 1; }

if [ "$1" = off ]; then
  systemctl disable --now casey-auto-deploy.timer 2>/dev/null || true
  echo "== 自動部署已關掉（網站本身不受影響）"
  exit 0
fi

user="${SUDO_USER:?請用 sudo 執行，不要直接用 root 登入}"
home="$(getent passwd "$user" | cut -d: -f6)"
id -nG "$user" | grep -qw docker || { echo "$user 不在 docker 群組裡" >&2; exit 1; }
[ -d "$home/JudgementDigest/.git" ] || { echo "找不到 $home/JudgementDigest，先 git clone" >&2; exit 1; }

cat > /etc/systemd/system/casey-auto-deploy.service <<EOF
[Unit]
Description=CasEY 自動部署（main 的 tests 通過就部署）
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
User=$user
WorkingDirectory=$home
ExecStart=/bin/bash $home/JudgementDigest/deploy/server/auto-deploy.sh
TimeoutStartSec=30min
EOF

cat > /etc/systemd/system/casey-auto-deploy.timer <<'EOF'
[Unit]
Description=每 5 分鐘檢查一次要不要自動部署

[Timer]
OnBootSec=5min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now casey-auto-deploy.timer
echo "== 自動部署已打開。紀錄：journalctl -u casey-auto-deploy -f"
