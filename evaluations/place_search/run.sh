#!/usr/bin/env bash
set -euo pipefail

legacy_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
exec bash "$legacy_dir/../../Evaluation/datasets/v1.3.0/run.sh" "$@"
