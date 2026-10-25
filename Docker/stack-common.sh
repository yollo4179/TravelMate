#!/usr/bin/env bash
# Shared paths for Linux, macOS and Windows Git Bash. Source from stack scripts.
repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
state_dir="${STACK_STATE_DIR:-$repo_dir/Docker/build/stack}"
compose_repo_dir="$repo_dir"
if command -v cygpath >/dev/null 2>&1; then
  # Docker Desktop is a Windows executable: give it native paths and keep
  # container paths such as /stack out of MSYS automatic path conversion.
  compose_repo_dir=$(cygpath -m "$repo_dir")
  STACK_STATE_DIR=$(cygpath -m "$state_dir")
  export STACK_STATE_DIR
  BUILDX_CONFIG=$(cygpath -m "${BUILDX_CONFIG:-$state_dir/buildx}")
  export BUILDX_CONFIG
  export MSYS_NO_PATHCONV=1
  export MSYS2_ARG_CONV_EXCL='*'
else
  export STACK_STATE_DIR="$state_dir"
  export BUILDX_CONFIG="${BUILDX_CONFIG:-$state_dir/buildx}"
fi
compose=(docker compose --project-name docker --env-file "$STACK_STATE_DIR/runtime.env"
  -f "$compose_repo_dir/Docker/docker-compose.yml"
  -f "$compose_repo_dir/Docker/docker-compose.stack.yml"
  -f "$compose_repo_dir/Docker/docker-compose.kafka.yml"
  -f "$STACK_STATE_DIR/proxy.compose.yml")
