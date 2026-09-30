#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/root/education-platform}"
MODEL_STORE="${MODEL_STORE:-/root/autodl-tmp/education-platform-models}"
HF_BIN="${HF_BIN:-/root/.local/bin/hf}"
MODELSCOPE_BIN="${MODELSCOPE_BIN:-/root/.local/bin/modelscope}"
HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

if [[ ! -x "$HF_BIN" ]]; then
  echo "Missing Hugging Face CLI: $HF_BIN" >&2
  exit 1
fi
if [[ ! -x "$MODELSCOPE_BIN" ]]; then
  echo "Missing ModelScope CLI: $MODELSCOPE_BIN" >&2
  exit 1
fi

mkdir -p "$MODEL_STORE"

"$MODELSCOPE_BIN" download Qwen/Qwen3-8B \
  --local-dir "$MODEL_STORE/Qwen3-8B" \
  --max-workers 8

"$MODELSCOPE_BIN" download BAAI/bge-m3 \
  --local-dir "$MODEL_STORE/bge-m3" \
  --max-workers 8 \
  --exclude 'onnx/*'

"$MODELSCOPE_BIN" download iic/SenseVoiceSmall \
  --local-dir "$MODEL_STORE/SenseVoiceSmall" \
  --max-workers 8

mkdir -p "$MODEL_STORE/wav2lip"
WAV2LIP_URL="$HF_ENDPOINT/CherryOnes/LiveTalking/resolve/main/wav2lip.pth"
if command -v aria2c >/dev/null 2>&1; then
  aria2c \
    --allow-overwrite=true \
    --auto-file-renaming=false \
    --continue=true \
    --max-connection-per-server=16 \
    --split=16 \
    --min-split-size=1M \
    --file-allocation=none \
    --dir="$MODEL_STORE/wav2lip" \
    --out=wav2lip.pth \
    "$WAV2LIP_URL"
else
  HF_ENDPOINT="$HF_ENDPOINT" HF_HUB_DISABLE_XET=1 "$HF_BIN" download \
    CherryOnes/LiveTalking wav2lip.pth \
    --local-dir "$MODEL_STORE/wav2lip"
fi

if [[ -e "$PROJECT_ROOT/models" && ! -L "$PROJECT_ROOT/models" ]]; then
  echo "Refusing to replace non-symlink model directory: $PROJECT_ROOT/models" >&2
  exit 1
fi

ln -sfn "$MODEL_STORE" "$PROJECT_ROOT/models"
ln -sfn "$MODEL_STORE/wav2lip/wav2lip.pth" "$MODEL_STORE/wav2lip.pth"

test -s "$PROJECT_ROOT/models/Qwen3-8B/config.json"
test -s "$PROJECT_ROOT/models/bge-m3/config.json"
test -s "$PROJECT_ROOT/models/SenseVoiceSmall/config.yaml"
test -s "$PROJECT_ROOT/models/wav2lip.pth"

echo "All model files are ready under $PROJECT_ROOT/models"
