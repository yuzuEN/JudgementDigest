#!/usr/bin/env bash
# 主機安全設定（setup-host.sh 之後跑一次；重跑也沒關係）：
#   0. 避免 NVIDIA 顯示卡（nouveau）喚醒時卡死整台機器
#   1. SSH 只接受金鑰，不接受密碼（先確認自己的金鑰登得進去再跑）
#   2. Docker 容器連不到家裡區網與 tailnet（只能連外部網路：HF、Gemini），開機自動套用
#   3. 紀錄（journald）存在硬碟上，最多保留 30 天、1 GB
# 用法：把這個檔案複製到主機，執行 sudo bash harden-host.sh；跑完重新開機。說明見 docs/部署.md。
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "請用 sudo 執行：sudo bash harden-host.sh"; exit 1; }

echo "== 0/3 避免 NVIDIA 顯示卡（nouveau）喚醒時卡死整台機器"
# nouveau 讓顯示卡進入省電後，喚醒時可能卡死，連帶 SSH、sudo 都卡住（2026-11-14 在 yuktoy 實際發生）。
# 不讓顯示卡進入省電；fwupd（自動檢查韌體更新）伺服器用不到，就是它去開顯示卡觸發的，也停掉。
# 沒有 NVIDIA 顯示卡的機器加這個參數也沒有影響。
if ! grep -q 'nouveau.runpm=0' /etc/default/grub; then
  sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT="\(.*\)"/GRUB_CMDLINE_LINUX_DEFAULT="\1 nouveau.runpm=0"/' /etc/default/grub
  update-grub
fi
grep '^GRUB_CMDLINE_LINUX_DEFAULT' /etc/default/grub
systemctl mask --now fwupd.service fwupd-refresh.timer fwupd-refresh.service 2>/dev/null || true

echo "== 1/3 SSH 只接受金鑰"
# 檔名用 00- 開頭：sshd 以先讀到的設定為準，才會蓋過安裝時產生的 50-cloud-init.conf
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\n' > /etc/ssh/sshd_config.d/00-no-password.conf
systemctl reload ssh
sshd -T | grep -iE '^(passwordauthentication|kbdinteractiveauthentication)'

echo "== 2/3 容器連不到區網與 tailnet"
# 規則放在 raw 表的 PREROUTING：封包從容器網卡出來、還沒決定路由前就擋掉。
# （以前主機裝了 Tailscale 時，放在 DOCKER-USER（FORWARD）會被排在前面的 ts-forward 先放行；放 raw 表不受這種順序影響。）
# 只看從容器網卡（docker0、br-*）進來的封包，主機自己的連線（SSH）不受影響。
# ts-casey 也在容器網卡上：它的 tailnet 連線走外部網路（直連或 DERP 中繼），不需要連區網，所以照樣擋。
# 副作用：同一個區網裡的裝置連 casey 不能直連，會走 DERP 中繼（多約 200 ms），外面的使用者不受影響。
cat > /usr/local/sbin/casey-egress.sh <<'EOF'
#!/bin/sh
set -e
add() { iptables -t raw -C PREROUTING "$@" 2>/dev/null || iptables -t raw -I PREROUTING "$@"; }
for ifc in docker0 br-+; do
  for net in 10.0.0.0/8 192.168.0.0/16 100.64.0.0/10 169.254.0.0/16; do
    add -i "$ifc" -d "$net" -j DROP
  done
done
EOF
chmod 755 /usr/local/sbin/casey-egress.sh

# 上面擋掉了容器連家裡的路由器，也擋掉了容器用路由器查 DNS（docker build 時 npm、pip 會連不上網）。
# 執行中的平台走 docker 內建的 DNS，不受影響；建置用的容器會照抄主機的 DNS（路由器），所以改用公開的 DNS。
if [ ! -s /etc/docker/daemon.json ]; then
  echo '{ "dns": ["1.1.1.1", "8.8.8.8"] }' > /etc/docker/daemon.json
  systemctl restart docker
elif ! grep -q '"dns"' /etc/docker/daemon.json; then
  echo "注意：/etc/docker/daemon.json 已經有其他設定，請手動加上 \"dns\": [\"1.1.1.1\", \"8.8.8.8\"]，再 systemctl restart docker"
fi

cat > /etc/systemd/system/casey-egress.service <<'EOF'
[Unit]
Description=Block Docker containers from LAN and tailnet
After=docker.service network-online.target
Requires=docker.service
PartOf=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/casey-egress.sh

[Install]
WantedBy=docker.service
EOF
systemctl daemon-reload
systemctl enable casey-egress.service
systemctl restart casey-egress.service
iptables -t raw -S PREROUTING | grep -E 'docker0|br-'

echo "== 3/3 紀錄存在硬碟上，最多保留 30 天、1 GB"
# 平台的存取紀錄（IP、路徑、狀態碼）由 docker 交給 journald（docker-compose.yml 的 logging）。
# 存在硬碟上，重開機、重新部署都還在；超過 30 天或 1 GB 的舊紀錄自動刪除（隱私頁也這樣寫，改了要一起改）。
# 這是整台主機的 journald 設定，系統紀錄也一樣保留 30 天。
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/casey.conf <<'EOF2'
[Journal]
Storage=persistent
SystemMaxUse=1G
MaxRetentionSec=30day
EOF2
systemctl restart systemd-journald

echo
echo "== 完成。顯示卡的設定要重新開機才會生效，請執行：sudo reboot"
