#!/usr/bin/env bash
# 主機初始設定（Ubuntu Server 26.04 剛裝好時跑一次）：擴大硬碟、更新系統、安裝 Docker 與 Tailscale。
# 用法：把這個檔案複製到主機，執行 sudo bash setup-host.sh
# 之後接著跑 harden-host.sh（安全設定）。步驟見 docs/部署.md。
set -euo pipefail
user="${SUDO_USER:?請用 sudo 執行：sudo bash setup-host.sh}"
codename="$(. /etc/os-release && echo "$VERSION_CODENAME")"
export DEBIAN_FRONTEND=noninteractive

echo "== 1/5 把沒分配的硬碟空間加給系統（Ubuntu 安裝程式預設只分一部分給 LVM）"
lvextend -r -l +100%FREE /dev/ubuntu-vg/ubuntu-lv || echo "（已經用到最大，略過）"

echo "== 2/5 更新系統"
apt-get update
apt-get -y upgrade
apt-get install -y ca-certificates curl

echo "== 3/5 安裝 Docker（官方套件庫）"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $codename stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
# 讓 $user 不用 sudo 就能用 docker（docker 群組等同管理員權限，只加自己）
usermod -aG docker "$user"

echo "== 4/5 安裝 Tailscale（官方套件庫）"
curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/$codename.noarmor.gpg" \
  -o /usr/share/keyrings/tailscale-archive-keyring.gpg
curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/$codename.tailscale-keyring.list" \
  -o /etc/apt/sources.list.d/tailscale.list
apt-get update
apt-get install -y tailscale
systemctl enable --now tailscaled

echo "== 5/5 闔上螢幕（筆電）時不要休眠"
mkdir -p /etc/systemd/logind.conf.d
cat > /etc/systemd/logind.conf.d/server-lid.conf <<'EOF'
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
EOF

echo
echo "== 完成"
df -h / | tail -1
docker --version
tailscale version | head -1
if [ -f /var/run/reboot-required ]; then
  echo "系統更新需要重新開機，請執行：sudo reboot"
else
  echo "請執行 exit 再重新 ssh 登入，docker 群組才會生效。"
fi
