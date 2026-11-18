#!/usr/bin/env bash
# 自動部署：主機自己去看 main 有沒有新的 commit，tests 通過才執行 deploy.sh。
# 由 systemd 的 casey-auto-deploy.timer 每 5 分鐘執行一次（開關見 auto-deploy-setup.sh）。
# GitHub 不能在主機上執行任何東西：這支只會讀取公開 repo 和公開的 tests 結果，不需要帳號或密鑰。
#
#   main 有新的 commit？ → 沒有：結束
#   這個 commit 的 tests？ → 還在跑：下次再看 / 失敗：記下來，不部署 / 通過：部署
#
# 同一個 commit 只處理一次（記在 ~/casey/auto-deploy.state），部署失敗不會一直重試；
# 要重試就刪掉那個檔案。紀錄：journalctl -u casey-auto-deploy
#
# 整支包在 main() 裡：執行途中 git 會更新這個檔案本身，bash 要先讀完整支才不會讀到改到一半的內容。

main() {
  set -euo pipefail
  local repo="${CASEY_REPO:-$HOME/JudgementDigest}"
  local casey_home="${CASEY_HOME:-$HOME/casey}"
  local api="https://api.github.com/repos/yuzuEN/JudgementDigest/actions/workflows/tests.yml/runs"
  local state="$casey_home/auto-deploy.state"

  # 手動部署或上一次還沒跑完時，這次就跳過
  exec 9>"$casey_home/.auto-deploy.lock"
  flock -n 9 || { echo "上一次部署還在跑，這次跳過"; return 0; }

  git -C "$repo" fetch -q origin main
  local sha
  sha="$(git -C "$repo" rev-parse origin/main)"
  if [ -f "$state" ] && [ "$(cut -d' ' -f1 "$state")" = "$sha" ]; then
    return 0   # 這個 commit 處理過了
  fi

  # 查這個 commit 在 main 上的 tests（公開資訊，不用登入；沒登入每小時可查 60 次，這裡只在有新 commit 時才查）
  local result
  result="$(curl -fsS -m 30 -H "Accept: application/vnd.github+json" \
      "$api?head_sha=$sha&event=push&branch=main&per_page=1" \
    | python3 -c 'import json,sys
runs = json.load(sys.stdin).get("workflow_runs") or []
print(runs[0]["status"] + " " + str(runs[0]["conclusion"]) if runs else "none none")')"
  local status="${result% *}" conclusion="${result#* }"
  local short="${sha:0:7}"

  if [ "$status" != completed ]; then
    echo "$short 的 tests 還沒跑完（$status），下次再看"
    return 0
  fi
  if [ "$conclusion" != success ]; then
    echo "$short 的 tests 沒通過（$conclusion），不部署"
    echo "$sha tests-$conclusion $(date -Is)" > "$state"
    return 0
  fi

  echo "== $short 的 tests 通過，開始部署"
  git -C "$repo" checkout -q -B main "$sha"   # 主機上的 repo 只用來部署，直接把 main 移到這個 commit
  if (cd "$repo" && bash deploy/server/deploy.sh); then
    echo "$sha deployed $(date -Is)" > "$state"
    echo "== $short 部署成功"
  else
    echo "$sha deploy-failed $(date -Is)" > "$state"
    echo "== $short 部署失敗，已換回上一版（刪掉 $state 可以重試）" >&2
    return 1
  fi
}

main "$@"
exit
