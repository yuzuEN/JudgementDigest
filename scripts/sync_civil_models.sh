#!/usr/bin/env bash
# 從 Hugging Face 私人 repo 下載民事模型（勝敗 civil_winloss_v1、獲償比例 civil_amount_v1、被告端 civil_defense_v1）
# 與相似判決檢索（retrieval_civil_v7，約 3.1 GB）到 artifacts/。勝敗模型和檢索都有，民事結果頁才會用真實資料；
# civil_defense_v1 還沒上傳時會略過，被告的查詢改用原告端模型；
# retrieval_civil_defense_v2（被告答辯的檢索索引，約 600 MB）也是選用的，沒有時被告只用對方的主張找相似判決。
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
  --include 'civil_defense_v1/**' \
  --include 'retrieval_civil_defense_v2/**' \
  --include 'retrieval_civil_v7/**' \
  --local-dir "${JD_ARTIFACTS_DIR:-$project_root/artifacts}" \
  "$@"
