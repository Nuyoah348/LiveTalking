#!/usr/bin/env bash
set -u

STATE_DIR="${PLATFORM_STATE_DIR:-/root/autodl-tmp/education-platform-runtime}"
PID_DIR="$STATE_DIR/pids"
[[ -d "$PID_DIR" ]] || { echo "No platform PID directory: $PID_DIR"; exit 0; }

names=(web digital-human api stt embedding llm)
for name in "${names[@]}"; do
  pid_file="$PID_DIR/$name.pid"
  [[ -f "$pid_file" ]] || continue
  pid="$(cat "$pid_file")"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  fi
done

for _ in {1..20}; do
  alive=0
  for name in "${names[@]}"; do
    pid_file="$PID_DIR/$name.pid"
    [[ -f "$pid_file" ]] || continue
    pid="$(cat "$pid_file")"
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
      alive=1
    fi
  done
  (( alive == 0 )) && break
  sleep 1
done

for name in "${names[@]}"; do
  pid_file="$PID_DIR/$name.pid"
  [[ -f "$pid_file" ]] || continue
  pid="$(cat "$pid_file")"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
done

echo "Education platform stopped."

