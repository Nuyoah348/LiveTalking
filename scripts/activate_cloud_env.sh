#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PROJECT_ROOT="$ROOT_DIR"
ENV_PREFIX="${PLATFORM_ENV_PREFIX:-/root/autodl-tmp/envs/education-platform}"

if [[ ! -x "$ENV_PREFIX/bin/python" ]]; then
  echo "Virtual environment not found: $ENV_PREFIX" >&2
  return 1 2>/dev/null || exit 1
fi

export PATH="$ENV_PREFIX/bin:$PATH"
export DEEPTUTOR_HOME="${DEEPTUTOR_HOME:-$ROOT_DIR/education}"
export PYTHONPATH="$ROOT_DIR/education${PYTHONPATH:+:$PYTHONPATH}"

if [[ -f "$ROOT_DIR/scripts/model_paths.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/scripts/model_paths.env"
  set +a
fi

echo "Education platform environment activated: $ENV_PREFIX"
echo "Python: $(python --version 2>&1)"
echo "Node: $(node --version 2>&1)"
