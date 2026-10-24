#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/stack-common.sh"
case "${1:-}" in
  ''|--build) ;;
  *) echo 'Usage: bash Docker/stack-up.sh [--build]' >&2; exit 1 ;;
esac
if ! docker compose version >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  echo 'Start Docker Desktop (Linux containers) and check Docker Compose v2 is available.' >&2
  exit 1
fi
mkdir -p "$repo_dir/Docker/build" "$state_dir/init"
chmod 755 "$repo_dir/Docker/build" "$state_dir" "$state_dir/init"
cp "$repo_dir/Docker/init/01-schema.sql" "$state_dir/init/01-schema.sql"
# The base Compose mounts this file inside the read-only init directory.
# Precreate the target so Docker never has to write into that directory.
if [ -f "$repo_dir/Docker/migrations/20261013_add_planning_context.sql" ]; then
  cp "$repo_dir/Docker/migrations/20261013_add_planning_context.sql" "$state_dir/init/02-planning-context.sql"
fi
cat > "$state_dir/init/02-local-user-column.sql" <<'SQL'
ALTER TABLE users ADD COLUMN IF NOT EXISTS provider_id VARCHAR(255);
SQL
chmod 644 "$state_dir/init/"*.sql

# A custom CA is optional. Ordinary machines use the bootstrap image's default
# Linux CA store, so Windows does not need /etc/ssl/certs or a host Python install.
export STACK_CUSTOM_CA=0
if [ -n "${SSL_CERT_FILE:-}" ]; then
  if [ ! -s "$SSL_CERT_FILE" ]; then
    echo 'SSL_CERT_FILE is set but does not point to a readable CA bundle. Fix or unset it.' >&2
    exit 1
  fi
  cp "$SSL_CERT_FILE" "$state_dir/ca-bundle.pem"
  export STACK_CUSTOM_CA=1
fi
if [ -s /etc/ssl/certs/java/cacerts ]; then
  cp /etc/ssl/certs/java/cacerts "$state_dir/java-cacerts"
else
  : > "$state_dir/java-cacerts"
fi

bootstrap=(docker run --rm --user "$(id -u):$(id -g)"
  --mount "type=bind,source=$STACK_STATE_DIR,target=/stack"
  --mount "type=bind,source=$compose_repo_dir/Docker/stack-bootstrap.py,target=/bootstrap.py,readonly"
  --env STACK_CUSTOM_CA --env HTTP_PROXY --env HTTPS_PROXY)
# Some cloud proxy names only resolve on the host. Carry the existing mapping
# into the helper and generated overlay without requiring host Python.
if command -v getent >/dev/null 2>&1; then
  for proxy_url in "${HTTPS_PROXY:-}" "${HTTP_PROXY:-}"; do
    [ -n "$proxy_url" ] || continue
    authority="${proxy_url#*://}"
    authority="${authority%%/*}"
    authority="${authority##*@}"
    proxy_host="${authority%%:*}"
    proxy_ip=$(getent ahostsv4 "$proxy_host" | awk 'NR == 1 {print $1}' || true)
    if [ -n "$proxy_ip" ]; then bootstrap+=(--add-host "$proxy_host:$proxy_ip"); fi
  done
fi
if [ "$(uname -s)" = Linux ] && [ -n "${HTTPS_PROXY:-}${HTTP_PROXY:-}" ]; then
  bootstrap+=(--env STACK_BUILD_NETWORK=host)
fi
"${bootstrap[@]}" python:3.12-slim-bookworm python /bootstrap.py
"${compose[@]}" config --quiet
if [ "${1:-}" = --build ]; then
  "${compose[@]}" build
else
  # Reuse installed images on normal startup; rebuild explicitly after source changes.
  missing=()
  for service in server embedding; do
    if ! docker image inspect "travelmate-$service:local" >/dev/null 2>&1; then
      missing+=("$service")
    fi
  done
  if [ "${#missing[@]}" -gt 0 ]; then "${compose[@]}" build "${missing[@]}"; fi
fi
"${compose[@]}" up -d
# Apply the non-destructive local compatibility migration to retained volumes too.
db_ready=false
for attempt in {1..30}; do
  if "${compose[@]}" exec -T postgres pg_isready -U ssafy -d travel_db >/dev/null 2>&1; then
    "${compose[@]}" exec -T postgres psql -v ON_ERROR_STOP=1 -U ssafy -d travel_db -c 'ALTER TABLE users ADD COLUMN IF NOT EXISTS provider_id VARCHAR(255);'
    db_ready=true
    break
  fi
  sleep 1
done
if [ "$db_ready" != true ]; then
  echo 'PostgreSQL did not become ready; inspect the postgres logs before retrying.' >&2
  exit 1
fi
"${compose[@]}" ps
echo 'Containers started. First BGE-M3 model download can take several minutes; use Docker/stack-status.sh to check readiness.'
