#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [[ -n "${OUTPUT:-}" ]]; then set -- --output "$OUTPUT" "$@"; fi
if [[ -n "${DEVICE:-}" ]]; then set -- --device "$DEVICE" "$@"; fi
exec "${PYTHON:-python}" train_model.py \
  --config configs/accusation_experiment.json "$@"
