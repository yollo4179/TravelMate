#!/usr/bin/env bash
set -euo pipefail
wait_timeout="${STACK_WAIT_TIMEOUT:-600}"
if ! [[ "$wait_timeout" =~ ^[0-9]+$ ]]; then
  echo 'STACK_WAIT_TIMEOUT must be a non-negative integer (seconds).' >&2
  exit 1
fi
names=(travel-postgres travelmate-search-postgres travelmate-redis travelmate-server travelmate-embedding travelmate-kafka travelmate-kafka-ui)
deadline=$((SECONDS + wait_timeout))
last=''
while true; do
  states=''
  all_healthy=true
  failed=false
  for name in "${names[@]}"; do
    state=$(docker inspect --format '{{if .State.Running}}{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}{{else}}{{.State.Status}}{{end}}' "$name" 2>/dev/null) || state=missing
    states+="$name: $state | "
    [ "$state" = healthy ] || all_healthy=false
    case "$state" in missing|exited|dead) failed=true ;; esac
  done
  if [ "$states" != "$last" ]; then
    echo "${states% | }"
    last="$states"
  fi
  if [ "$all_healthy" = true ]; then
    echo 'All seven application and infrastructure services passed Docker healthchecks.'
    exit 0
  fi
  if [ "$failed" = true ]; then
    echo 'Required container is not running. Run stack-up.sh successfully first, then inspect startup errors.' >&2
    exit 1
  fi
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo 'Readiness timed out; not all required services are healthy.' >&2
    exit 1
  fi
  sleep 2
done
