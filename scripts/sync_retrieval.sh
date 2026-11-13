#!/usr/bin/env bash
# Download published retrieval bundles into the platform's existing artifacts directory.
set -euo pipefail
case "${1:-}" in
  civil) patterns=('retrieval_civil_v3/**') ;;
  criminal) patterns=('retrieval_criminal_v1/**') ;;
  all) patterns=('retrieval_civil_v3/**' 'retrieval_criminal_v1/**') ;;
  *) echo "Usage: bash scripts/sync_retrieval.sh civil|criminal|all [hf download options]" >&2; exit 2 ;;
esac
shift
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
include_args=()
for pattern in "${patterns[@]}"; do
  include_args+=(--include "$pattern")
done
hf download JudgementDigest/judgementdigest-artifacts \
  --revision main \
  "${include_args[@]}" \
  --local-dir "$project_root/artifacts" \
  "$@"
