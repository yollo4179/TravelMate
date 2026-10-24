#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export STACK_STATE_DIR="${STACK_STATE_DIR:-$repo_dir/Docker/build/stack}"
docker compose --project-name docker --env-file "$STACK_STATE_DIR/runtime.env" -f "$repo_dir/Docker/docker-compose.yml" -f "$repo_dir/Docker/docker-compose.stack.yml" -f "$STACK_STATE_DIR/proxy.compose.yml" ps
for service in travel-postgres travelmate-redis travelmate-server travelmate-embedding; do
  docker inspect --format '{{.Name}}: {{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$service"
done
