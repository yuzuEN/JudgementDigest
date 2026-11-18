#!/usr/bin/env bash
# 從 Hugging Face 私人 repo 下載民事模型（勝敗 civil_winloss_v1、獲償比例 civil_amount_v1）
# 與相似判決檢索（retrieval_civil_v5，約 3.1 GB）到 artifacts/。三個都有，民事結果頁才會用真實資料。
# 要先加入 JudgementDigest 組織並 hf auth login；沒改過的檔案會沿用快取，不會重新下載。
#
#   bash scripts/sync_civil_models.sh                         # 最新版
#   JD_HF_REVISION=<commit> bash scripts/sync_civil_models.sh # 部署時固定某一版
#
# 下載位置跟著 config.py：有設 JD_ARTIFACTS_DIR 就放那裡，否則放 repo 根目錄的 artifacts/。
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# 每個資料夾各下載一次：hf 0.x 的 --include 寫好幾次時只有最後一個有效（1.x 則全部有效），分開寫兩種版本都對
for folder in civil_winloss_v1 civil_amount_v1 retrieval_civil_v5; do
  hf download JudgementDigest/judgementdigest-artifacts \
    --revision "${JD_HF_REVISION:-main}" \
    --include "$folder/**" \
    --local-dir "${JD_ARTIFACTS_DIR:-$project_root/artifacts}" \
    "$@"
done
