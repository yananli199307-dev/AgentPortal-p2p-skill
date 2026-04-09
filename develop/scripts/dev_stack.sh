#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/develop/docker/docker-compose.generated.yml"
GEN_SCRIPT="$ROOT_DIR/develop/scripts/gen_envs.py"
BASE_PORT=18080

usage() {
  echo "Usage:"
  echo "  develop/scripts/dev_stack.sh start --count N [--with-lobster] [--lobster-image IMAGE]"
  echo "  develop/scripts/dev_stack.sh scale --count N [--with-lobster] [--lobster-image IMAGE]"
  echo "  develop/scripts/dev_stack.sh stop"
  echo "  develop/scripts/dev_stack.sh status"
  echo "  develop/scripts/dev_stack.sh logs [portal|bridge|lobster] [index]"
}

parse_args() {
  local default_count="${1:-2}"
  local count="$default_count"
  local with_lobster="false"
  local lobster_image="ghcr.io/openclaw/openclaw:latest"
  shift || true
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --count)
        count="${2:-$default_count}"
        shift 2
        ;;
      --with-lobster)
        with_lobster="true"
        shift
        ;;
      --lobster-image)
        lobster_image="${2:-$lobster_image}"
        shift 2
        ;;
      *)
        shift
        ;;
    esac
  done
  echo "$count|$with_lobster|$lobster_image"
}

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

ensure_compose() {
  local count="$1"
  local with_lobster="$2"
  local lobster_image="$3"
  if [ "$with_lobster" = "true" ]; then
    python3 "$GEN_SCRIPT" --count "$count" --with-lobster --lobster-image "$lobster_image"
  else
    python3 "$GEN_SCRIPT" --count "$count"
  fi
}

bootstrap_api_keys() {
  local count="$1"
  for i in $(seq 1 "$count"); do
    local host_port=$((BASE_PORT + i - 1))
    local env_file="$ROOT_DIR/develop/runtime/env${i}/gateway.env"
    local current_key
    current_key="$(python3 - <<PY
from pathlib import Path
text = Path("$env_file").read_text(encoding="utf-8").splitlines()
val = ""
for line in text:
    if line.startswith("AGENTP2P_API_KEY="):
        val = line.split("=", 1)[1].strip()
        break
print(val)
PY
)"
    if [ -n "$current_key" ] && [ "$current_key" != "CHANGE_ME" ]; then
      continue
    fi

    local portal_internal="http://portal${i}:8080"
    local payload
    payload=$(python3 - <<PY
import json
print(json.dumps({
  "portal_url": "${portal_internal}",
  "agent_name": "lobster-agent-${i}",
  "user_name": "dev-user-${i}"
}))
PY
)

    local resp
    resp=$(curl -sS -X POST "http://127.0.0.1:${host_port}/api/key/create" \
      -H "Content-Type: application/json" \
      -d "$payload")

    local api_key
    api_key=$(python3 - <<PY
import json
data=json.loads("""$resp""")
print(data.get("api_key",""))
PY
)

    if [ -z "$api_key" ]; then
      echo "Failed to bootstrap API key for env${i}: $resp"
      exit 1
    fi

    python3 - <<PY
from pathlib import Path
path = Path("$env_file")
text = path.read_text(encoding="utf-8")
text = text.replace("AGENTP2P_API_KEY=CHANGE_ME", "AGENTP2P_API_KEY=$api_key")
path.write_text(text, encoding="utf-8")
PY
  done

  compose up -d --force-recreate $(for i in $(seq 1 "$count"); do echo "bridge${i}"; done)
}

start_stack() {
  local count="$1"
  local with_lobster="$2"
  local lobster_image="$3"
  ensure_compose "$count" "$with_lobster" "$lobster_image"
  compose up -d --build --pull never --remove-orphans

  for i in $(seq 1 "$count"); do
    local host_port=$((BASE_PORT + i - 1))
    for _ in $(seq 1 20); do
      if curl -s "http://127.0.0.1:${host_port}/" >/dev/null 2>&1; then
        break
      fi
      sleep 1
    done
  done
  bootstrap_api_keys "$count"
  if [ "$with_lobster" = "true" ]; then
    echo "Patching Moonshot apiKey in lobster agent cache (OpenClaw may rewrite placeholder)..."
    sleep 8
    python3 "$GEN_SCRIPT" --patch-moonshot-only --count "$count" || true
    lob_list=""
    for i in $(seq 1 "$count"); do
      lob_list="$lob_list lobster${i}"
    done
    compose restart $lob_list || true
    sleep 6
    python3 "$GEN_SCRIPT" --patch-moonshot-only --count "$count" || true
  fi
  echo "Stack is ready."
  echo "Portal URLs:"
  for i in $(seq 1 "$count"); do
    local host_port=$((BASE_PORT + i - 1))
    echo "  - portal${i}: http://127.0.0.1:${host_port}"
  done
  if [ "$with_lobster" = "true" ]; then
    echo "Lobster dashboard/gateway URLs:"
    for i in $(seq 1 "$count"); do
      local lobster_port=$((18790 + i - 1))
      local env_file="$ROOT_DIR/develop/runtime/env${i}/gateway.env"
      local gateway_operator_token
      gateway_operator_token="$(python3 - <<PY
from pathlib import Path
text = Path("$env_file").read_text(encoding="utf-8").splitlines()
val = ""
for line in text:
    if line.startswith("OPENCLAW_GATEWAY_TOKEN="):
        val = line.split("=", 1)[1].strip()
        break
print(val)
PY
)"
      echo "  - lobster${i} dashboard: http://127.0.0.1:${lobster_port}"
      if [ -n "$gateway_operator_token" ]; then
        echo "    Control UI token: ${gateway_operator_token}"
        echo "    token url: http://127.0.0.1:${lobster_port}/?token=${gateway_operator_token}"
      fi
    done
  fi
}

case "${1:-}" in
  start)
    parsed="$(parse_args 2 "$@")"
    count="${parsed%%|*}"
    rest="${parsed#*|}"
    with_lobster="${rest%%|*}"
    lobster_image="${rest#*|}"
    start_stack "$count" "$with_lobster" "$lobster_image"
    ;;
  scale)
    parsed="$(parse_args 2 "$@")"
    count="${parsed%%|*}"
    rest="${parsed#*|}"
    with_lobster="${rest%%|*}"
    lobster_image="${rest#*|}"
    start_stack "$count" "$with_lobster" "$lobster_image"
    ;;
  stop)
    if [ -f "$COMPOSE_FILE" ]; then
      compose down --remove-orphans
    else
      echo "No generated compose file found."
    fi
    ;;
  status)
    if [ -f "$COMPOSE_FILE" ]; then
      compose ps
    else
      echo "No generated compose file found. Run start first."
    fi
    ;;
  logs)
    service_type="${2:-}"
    index="${3:-}"
    if [ -z "$service_type" ] || [ -z "$index" ]; then
      usage
      exit 1
    fi
    compose logs -f "${service_type}${index}"
    ;;
  *)
    usage
    exit 1
    ;;
esac
