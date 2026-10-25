#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/stack-common.sh"
if [ ! -f "$state_dir/runtime.env" ]; then
  echo 'Run bash Docker/stack-up.sh successfully before checking stack status.' >&2
  exit 1
fi
"${compose[@]}" ps
for service in travel-postgres travelmate-search-postgres travelmate-redis travelmate-server travelmate-embedding travelmate-kafka travelmate-kafka-ui; do
  docker inspect --format '{{.Name}}: {{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$service"
done
