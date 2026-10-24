#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export STACK_STATE_DIR="${STACK_STATE_DIR:-$repo_dir/Docker/build/stack}"
export BUILDX_CONFIG="${BUILDX_CONFIG:-$STACK_STATE_DIR/buildx}"
mkdir -p "$repo_dir/Docker/build" "$STACK_STATE_DIR/init"
chmod 755 "$repo_dir/Docker/build" "$STACK_STATE_DIR" "$STACK_STATE_DIR/init"
cp "$repo_dir/Docker/init/01-schema.sql" "$STACK_STATE_DIR/init/01-schema.sql"
cat > "$STACK_STATE_DIR/init/02-local-user-column.sql" <<'SQL'
ALTER TABLE users ADD COLUMN IF NOT EXISTS provider_id VARCHAR(255);
SQL
chmod 644 "$STACK_STATE_DIR/init/"*.sql

# Keep proxy trust verification enabled; certificates are public trust material.
cert_bundle="${SSL_CERT_FILE:-/etc/ssl/certs/ca-certificates.crt}"
if [ ! -s "$cert_bundle" ]; then
  echo 'Set SSL_CERT_FILE to a valid CA bundle before building.' >&2
  exit 1
fi
cp "$cert_bundle" "$STACK_STATE_DIR/ca-bundle.pem"
chmod 644 "$STACK_STATE_DIR/ca-bundle.pem"
if [ -s /etc/ssl/certs/java/cacerts ]; then
  cp /etc/ssl/certs/java/cacerts "$STACK_STATE_DIR/java-cacerts"
else
  : > "$STACK_STATE_DIR/java-cacerts"
fi
python3 - "$STACK_STATE_DIR" <<'PY'
import json, os, secrets, socket, sys
from pathlib import Path
from urllib.parse import urlsplit
state = Path(sys.argv[1])
runtime = state / 'runtime.env'
if not runtime.exists():
    runtime.write_text('JWT_SECRET=' + secrets.token_urlsafe(64) + '\n')
    runtime.chmod(0o600)
proxy = urlsplit(os.environ.get('HTTPS_PROXY', ''))
lines = []
if proxy.hostname:
    for scheme in ('http', 'https'):
        lines += [f'systemProp.{scheme}.proxyHost={proxy.hostname}',
                  f'systemProp.{scheme}.proxyPort={proxy.port or 80}']
lines.append('systemProp.http.nonProxyHosts=localhost|127.*')
(state / 'gradle.properties').write_text('\n'.join(lines) + '\n')
hosts = {}
for name in ('HTTPS_PROXY', 'HTTP_PROXY'):
    host = urlsplit(os.environ.get(name, '')).hostname
    if host:
        hosts[host] = socket.gethostbyname(host)
services = {}
if hosts:
    services['server'] = {'build': {'extra_hosts': hosts}}
    services['embedding'] = {'build': {'extra_hosts': hosts}, 'extra_hosts': hosts}
# JSON is also valid YAML. Reuse the configured proxy; do not bypass egress rules.
(state / 'proxy.compose.yml').write_text(json.dumps({'services': services}))
PY
compose=(docker compose --project-name docker --env-file "$STACK_STATE_DIR/runtime.env" -f "$repo_dir/Docker/docker-compose.yml" -f "$repo_dir/Docker/docker-compose.stack.yml" -f "$STACK_STATE_DIR/proxy.compose.yml")
"${compose[@]}" config --quiet
if [ "${1:-}" = --build ]; then
  "${compose[@]}" build
elif [ -n "${1:-}" ]; then
  echo 'Usage: bash Docker/stack-up.sh [--build]' >&2
  exit 1
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
for attempt in {1..30}; do
  if "${compose[@]}" exec -T postgres pg_isready -U ssafy -d travel_db >/dev/null 2>&1; then
    "${compose[@]}" exec -T postgres psql -v ON_ERROR_STOP=1 -U ssafy -d travel_db -c 'ALTER TABLE users ADD COLUMN IF NOT EXISTS provider_id VARCHAR(255);'
    break
  fi
  sleep 1
done
"${compose[@]}" ps
echo 'Containers started. First BGE-M3 model download can take several minutes; use Docker/stack-status.sh to check readiness.'
