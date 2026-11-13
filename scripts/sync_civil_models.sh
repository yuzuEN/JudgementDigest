#!/usr/bin/env bash
# 從 Hugging Face 私人 repo 下載民事模型（勝敗 civil_winloss_v1、獲償比例 civil_amount_v1）
# 與相似判決檢索（retrieval_civil_v3，約 2.6 GB）到 artifacts/。三個都有，民事結果頁才會用真實資料。
# 要先加入 JudgementDigest 組織並 hf auth login；沒改過的檔案會沿用快取，不會重新下載。
#
#   bash scripts/sync_civil_models.sh                         # 最新版
#   JD_HF_REVISION=<commit> bash scripts/sync_civil_models.sh # 部署時固定某一版
#
# 下載位置跟著 config.py：有設 JD_ARTIFACTS_DIR 就放那裡，否則放 repo 根目錄的 artifacts/。
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
hf download JudgementDigest/judgementdigest-artifacts \
  --revision "${JD_HF_REVISION:-main}" \
  --include 'civil_winloss_v1/**' \
  --include 'civil_amount_v1/**' \
  --include 'retrieval_civil_v3/**' \
  --local-dir "${JD_ARTIFACTS_DIR:-$project_root/artifacts}" \
  "$@"
