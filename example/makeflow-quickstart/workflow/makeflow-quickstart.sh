#!/usr/bin/env bash
set -euo pipefail

manager_port="${VINE_MANAGER_PORTS%%,*}"
mkdir -p outputs

makeflow \
  --batch-type vine \
  --project-name "${VINE_MANAGER_NAME}" \
  --port "${manager_port}" \
  --makeflow-log ../logs/makeflow.log \
  --batch-log ../logs/makeflow.batch.log \
  workflow.makeflow

if [[ ! -s outputs/capitol.anim.gif ]]; then
  echo "[makeflow-quickstart] Expected output was not created: outputs/capitol.anim.gif" >&2
  exit 1
fi
