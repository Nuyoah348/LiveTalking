#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PROJECT_ROOT="$ROOT_DIR"
ENV_PREFIX="${PLATFORM_ENV_PREFIX:-/root/autodl-tmp/envs/education-platform}"
if [[ ! -x "$ENV_PREFIX/bin/python" && -x "$ROOT_DIR/.venv/bin/python" ]]; then
  ENV_PREFIX="$ROOT_DIR/.venv"
fi
if [[ ! -x "$ENV_PREFIX/bin/python" ]]; then
  echo "Python environment not found: $ENV_PREFIX" >&2
  exit 1
fi
export PATH="$ENV_PREFIX/bin:$PATH"

if [[ -f "$ROOT_DIR/scripts/model_paths.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/scripts/model_paths.env"
  set +a
fi

LLM_PORT=8000
DEEPTUTOR_API_PORT=8001
EMBEDDING_PORT=8002
STT_PORT=8003
DIGITAL_HUMAN_PORT=8010
DEEPTUTOR_WEB_PORT="${DEEPTUTOR_WEB_PORT:-6006}"
LLM_MAX_MODEL_LEN="${LLM_MAX_MODEL_LEN:-16384}"
LLM_GPU_MEMORY_UTILIZATION="${LLM_GPU_MEMORY_UTILIZATION:-0.70}"
LLM_MAX_NUM_SEQS="${LLM_MAX_NUM_SEQS:-4}"
QWEN_SERVED_MODEL_NAME="${QWEN_SERVED_MODEL_NAME:-Qwen3-8B}"
DIGITAL_HUMAN_AVATAR="${DIGITAL_HUMAN_AVATAR:-teacher-tutor}"
DIGITAL_HUMAN_TTS="${DIGITAL_HUMAN_TTS:-edgetts}"
START_TIMEOUT_SECONDS="${PLATFORM_START_TIMEOUT_SECONDS:-600}"

STATE_DIR="${PLATFORM_STATE_DIR:-/root/autodl-tmp/education-platform-runtime}"
PID_DIR="$STATE_DIR/pids"
LOG_DIR="$STATE_DIR/logs"
mkdir -p "$PID_DIR" "$LOG_DIR"

export DEEPTUTOR_HOME="${DEEPTUTOR_HOME:-$ROOT_DIR/education}"
export PYTHONPATH="$ROOT_DIR/education:$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
export DEEPTUTOR_API_BASE_URL="http://127.0.0.1:$DEEPTUTOR_API_PORT"
export DIGITAL_HUMAN_API_BASE_URL="http://127.0.0.1:$DIGITAL_HUMAN_PORT"
export NEXT_PUBLIC_API_BASE=""
export BACKEND_PORT="$DEEPTUTOR_API_PORT"
export EMBEDDING_DEVICE="${EMBEDDING_DEVICE:-cpu}"
export STT_DEVICE="${STT_DEVICE:-cpu}"

cat >"$STATE_DIR/runtime.env" <<EOF
PROJECT_ROOT=$ROOT_DIR
PLATFORM_STATE_DIR=$STATE_DIR
DEEPTUTOR_WEB_PORT=$DEEPTUTOR_WEB_PORT
EOF

is_running() {
  local name="$1" pid_file="$PID_DIR/$1.pid" pid
  [[ -f "$pid_file" ]] || return 1
  pid="$(cat "$pid_file")"
  [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null
}

start_service() {
  local name="$1"
  shift
  if is_running "$name"; then
    echo "$name is already running (PID $(cat "$PID_DIR/$name.pid"))" >&2
    return 1
  fi
  rm -f "$PID_DIR/$name.pid"
  : >"$LOG_DIR/$name.log"
  nohup setsid "$@" >>"$LOG_DIR/$name.log" 2>&1 </dev/null &
  local pid=$!
  echo "$pid" >"$PID_DIR/$name.pid"
  sleep 1
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "$name failed to start; inspect $LOG_DIR/$name.log" >&2
    tail -n 40 "$LOG_DIR/$name.log" >&2 || true
    return 1
  fi
  echo "Started $name (PID $pid)"
}

wait_for_url() {
  local name="$1" url="$2" deadline=$((SECONDS + START_TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    if curl --fail --silent --show-error --max-time 3 "$url" >/dev/null 2>&1; then
      echo "$name is ready: $url"
      return 0
    fi
    if ! is_running "$name"; then
      echo "$name stopped before becoming ready; inspect $LOG_DIR/$name.log" >&2
      tail -n 60 "$LOG_DIR/$name.log" >&2 || true
      return 1
    fi
    sleep 2
  done
  echo "$name did not become ready within ${START_TIMEOUT_SECONDS}s" >&2
  tail -n 60 "$LOG_DIR/$name.log" >&2 || true
  return 1
}

cleanup_failed_start() {
  echo "Startup failed; stopping services started by this launcher." >&2
  bash "$ROOT_DIR/scripts/stop_platform.sh" >/dev/null 2>&1 || true
}
trap cleanup_failed_start ERR

for command in curl node npm setsid; do
  command -v "$command" >/dev/null || { echo "Missing command: $command" >&2; exit 1; }
done
python -c "import fastapi, funasr, sentence_transformers, uvicorn, vllm" >/dev/null

test -s "$QWEN_MODEL_PATH/config.json" || { echo "Missing Qwen model: $QWEN_MODEL_PATH" >&2; exit 1; }
test -s "$EMBEDDING_MODEL_PATH/config.json" || { echo "Missing BGE-M3 model: $EMBEDDING_MODEL_PATH" >&2; exit 1; }
test -s "$STT_MODEL_PATH/config.yaml" || { echo "Missing SenseVoice model: $STT_MODEL_PATH" >&2; exit 1; }
test -s "$WAV2LIP_MODEL_PATH" || { echo "Missing Wav2Lip model: $WAV2LIP_MODEL_PATH" >&2; exit 1; }

if [[ ! -f "$ROOT_DIR/education/web/.next/BUILD_ID" ]]; then
  echo "Building the Next.js frontend (first start only)..."
  npm --prefix "$ROOT_DIR/education/web" run build
fi

start_service llm python -m vllm.entrypoints.openai.api_server \
  --host 127.0.0.1 --port 8000 \
  --model "$QWEN_MODEL_PATH" --served-model-name "$QWEN_SERVED_MODEL_NAME" \
  --dtype bfloat16 --max-model-len "$LLM_MAX_MODEL_LEN" \
  --gpu-memory-utilization "$LLM_GPU_MEMORY_UTILIZATION" \
  --max-num-seqs "$LLM_MAX_NUM_SEQS" --trust-remote-code --disable-log-requests
start_service embedding python -m uvicorn scripts.model_services.embedding_server:app \
  --host 127.0.0.1 --port 8002 --workers 1
start_service stt python -m uvicorn scripts.model_services.sensevoice_server:app \
  --host 127.0.0.1 --port 8003 --workers 1

wait_for_url llm "http://127.0.0.1:$LLM_PORT/health"
wait_for_url embedding "http://127.0.0.1:$EMBEDDING_PORT/health"
wait_for_url stt "http://127.0.0.1:$STT_PORT/health"

start_service api python -m uvicorn deeptutor.api.main:app \
  --host 127.0.0.1 --port 8001 --workers 1

AVATAR_ARGS=(
  --transport webrtc --model wav2lip --avatar_id "$DIGITAL_HUMAN_AVATAR"
  --listenhost 127.0.0.1 --listenport 8010 --tts "$DIGITAL_HUMAN_TTS"
  --llm_provider local --llm_base_url "http://127.0.0.1:8000/v1"
  --llm_model "$QWEN_SERVED_MODEL_NAME"
)
if [[ -n "${DIGITAL_HUMAN_TTS_SERVER:-}" ]]; then
  AVATAR_ARGS+=(--TTS_SERVER "$DIGITAL_HUMAN_TTS_SERVER")
fi
start_service digital-human python "$ROOT_DIR/app.py" "${AVATAR_ARGS[@]}"
start_service web node "$ROOT_DIR/education/web/node_modules/next/dist/bin/next" start \
  -H 0.0.0.0 -p "$DEEPTUTOR_WEB_PORT"

wait_for_url api "http://127.0.0.1:$DEEPTUTOR_API_PORT/health/live"
wait_for_url digital-human "http://127.0.0.1:$DIGITAL_HUMAN_PORT/"
wait_for_url web "http://127.0.0.1:$DEEPTUTOR_WEB_PORT/"

trap - ERR
echo
echo "Education platform is running."
echo "AutoDL custom service: map container port $DEEPTUTOR_WEB_PORT (default 6006)."
echo "Logs: $LOG_DIR"
bash "$ROOT_DIR/scripts/status_platform.sh"

