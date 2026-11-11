#!/usr/bin/env bash
# Sync the latest published ELECTRA bundle; cached unchanged files are reused.
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
hf download yunn030123/judgementdigest-artifacts \
  --revision main \
  --include 'criminal_term/**' \
  --local-dir "$project_root/artifacts" \
  "$@"
