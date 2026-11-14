#!/usr/bin/env bash
# 在主機上安裝 GitHub Actions 自架 runner，給 .github/workflows/deploy.yml 自動部署用。
# runner 主動連到 GitHub 等工作，主機不用開任何 port。
#
# 用法（在主機上，用平常的帳號，不要用 sudo；中間 svc.sh 會自己問 sudo 密碼）：
#   bash install-runner.sh <註冊 token>
# token 在 GitHub repo → Settings → Actions → Runners → New self-hosted runner 頁面的 ./config.sh 那行，
# 一小時內有效、只能用來註冊這一台。說明見 docs/部署.md。
set -euo pipefail
token="${1:?用法：bash install-runner.sh <註冊 token>}"
repo_url="${RUNNER_REPO_URL:-https://github.com/yuzuEN/JudgementDigest}"
dir="$HOME/actions-runner"

[ "$(id -u)" != 0 ] || { echo "不要用 sudo 執行；runner 要用平常的帳號跑（要在 docker 群組裡）" >&2; exit 1; }
id -nG | grep -qw docker || { echo "目前的帳號不在 docker 群組，先跑 setup-host.sh 並重新登入" >&2; exit 1; }

version="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"].lstrip("v"))')"
echo "== 下載 runner $version"
mkdir -p "$dir"
cd "$dir"
curl -fsSL -o runner.tar.gz \
  "https://github.com/actions/runner/releases/download/v$version/actions-runner-linux-x64-$version.tar.gz"
tar xzf runner.tar.gz
rm runner.tar.gz

echo "== 註冊到 $repo_url（名稱 casey、標籤 casey）"
./config.sh --unattended --replace --url "$repo_url" --token "$token" \
  --name casey --labels casey --work _work

echo "== 裝成系統服務，開機自動啟動（會問 sudo 密碼）"
sudo ./svc.sh install "$USER"
sudo ./svc.sh start
sudo ./svc.sh status | head -5
