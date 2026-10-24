#!/usr/bin/env bash
set -euo pipefail
dataset_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
mode="${1:---check}"
readonly_mount=',readonly'
case "$mode" in
  --check) arguments=(python /dataset/build_dataset.py --check) ;;
  --test) arguments=(python -m unittest discover -s /dataset/tests -v) ;;
  --build) arguments=(python /dataset/build_dataset.py); readonly_mount='' ;;
  *) echo 'Usage: bash run.sh [--check|--test|--build]' >&2; exit 1 ;;
esac
if command -v cygpath >/dev/null 2>&1; then
  dataset_dir=$(cygpath -m "$dataset_dir")
  export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
fi
docker run --rm --user "$(id -u):$(id -g)" --env PYTHONDONTWRITEBYTECODE=1 \
  --mount "type=bind,source=$dataset_dir,target=/dataset$readonly_mount" \
  python:3.12-slim-bookworm "${arguments[@]}"
