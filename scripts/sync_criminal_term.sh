#!/usr/bin/env bash
# 從 Hugging Face 私人 repo 下載刑度模型（法律 ELECTRA，criminal_term）到 artifacts/。沒改過的檔案會沿用快取。
#
#   bash scripts/sync_criminal_term.sh                         # 最新版
#   JD_HF_REVISION=<commit> bash scripts/sync_criminal_term.sh # 部署時固定某一版
#
# 下載位置跟著 config.py：有設 JD_ARTIFACTS_DIR 就放那裡，否則放 repo 根目錄的 artifacts/。
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
hf download JudgementDigest/judgementdigest-artifacts \
  --revision "${JD_HF_REVISION:-main}" \
  --include 'criminal_term/**' \
  --local-dir "${JD_ARTIFACTS_DIR:-$project_root/artifacts}" \
  "$@"
