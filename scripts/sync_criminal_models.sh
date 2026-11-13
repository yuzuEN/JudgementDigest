#!/usr/bin/env bash
# 從 Hugging Face 私人 repo 下載刑事罪名、法條、刑度 SVM（criminal_v1）到 artifacts/。
# 要先加入 JudgementDigest 組織並 hf auth login；沒改過的檔案會沿用快取，不會重新下載。
#
#   bash scripts/sync_criminal_models.sh                         # 最新版
#   JD_HF_REVISION=<commit> bash scripts/sync_criminal_models.sh # 部署時固定某一版
#
# 刑度 ELECTRA（criminal_term）用 scripts/sync_criminal_term.sh；刑事檢索（retrieval_criminal_v1）還在組內另外傳。
# 下載位置跟著 config.py：有設 JD_ARTIFACTS_DIR 就放那裡，否則放 repo 根目錄的 artifacts/。
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
hf download JudgementDigest/judgementdigest-artifacts \
  --revision "${JD_HF_REVISION:-main}" \
  --include 'criminal_v1/**' \
  --local-dir "${JD_ARTIFACTS_DIR:-$project_root/artifacts}" \
  "$@"
