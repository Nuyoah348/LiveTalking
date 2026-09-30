#!/usr/bin/env bash
set -u

STATE_DIR="${PLATFORM_STATE_DIR:-/root/autodl-tmp/education-platform-runtime}"
PID_DIR="$STATE_DIR/pids"
if [[ -f "$STATE_DIR/runtime.env" ]]; then
  # shellcheck disable=SC1091
  source "$STATE_DIR/runtime.env"
fi
DEEPTUTOR_WEB_PORT="${DEEPTUTOR_WEB_PORT:-6006}"

declare -A URLS=(
  [llm]="http://127.0.0.1:8000/health"
  [api]="http://127.0.0.1:8001/health/live"
  [embedding]="http://127.0.0.1:8002/health"
  [stt]="http://127.0.0.1:8003/health"
  [digital-human]="http://127.0.0.1:8010/"
  [web]="http://127.0.0.1:$DEEPTUTOR_WEB_PORT/"
)

failed=0
for name in llm embedding stt api digital-human web; do
  pid_file="$PID_DIR/$name.pid"
  if [[ ! -f "$pid_file" ]]; then
    printf '%-15s stopped (no PID file)\n' "$name"
    failed=1
    continue
  fi
  pid="$(cat "$pid_file")"
  if [[ ! "$pid" =~ ^[0-9]+$ ]] || ! kill -0 "$pid" 2>/dev/null; then
    printf '%-15s stopped (stale PID file)\n' "$name"
    failed=1
    continue
  fi
  if curl --fail --silent --max-time 3 "${URLS[$name]}" >/dev/null 2>&1; then
    printf '%-15s healthy (PID %s)\n' "$name" "$pid"
  else
    printf '%-15s running, health check pending (PID %s)\n' "$name" "$pid"
    failed=1
  fi
done

exit "$failed"

