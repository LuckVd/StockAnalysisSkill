#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$SKILL_DIR/.env"
VENV_DIR="$SKILL_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python"
STAMP_FILE="$VENV_DIR/.stockanalysis-sync-stamp"
PYPROJECT_FILE="$SKILL_DIR/pyproject.toml"

if [ -f "$ENV_FILE" ]; then
  set -a
  . "$ENV_FILE"
  set +a
fi

resolve_candidate() {
  local candidate="$1"
  if [ -z "$candidate" ]; then
    return 1
  fi
  if [[ "$candidate" == */* ]]; then
    [ -x "$candidate" ] || return 1
    printf '%s\n' "$candidate"
    return 0
  fi
  command -v "$candidate" 2>/dev/null || return 1
}

if [ -n "${STOCK_ANALYSIS_PYTHON:-}" ]; then
  if resolved="$(resolve_candidate "$STOCK_ANALYSIS_PYTHON")"; then
    printf '%s\n' "$resolved"
    exit 0
  fi
fi

if [ -x "$VENV_PY" ] && [ -f "$STAMP_FILE" ] && [ "$STAMP_FILE" -nt "$PYPROJECT_FILE" ]; then
  printf '%s\n' "$VENV_PY"
  exit 0
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "未找到 uv。请先安装 uv，或在 .env 中设置 STOCK_ANALYSIS_PYTHON 指向已安装依赖的解释器。" >&2
  exit 1
fi

BASE_PY="$($SCRIPT_DIR/resolve_python.sh --system)"
if [ ! -x "$VENV_PY" ]; then
  uv venv "$VENV_DIR" --python "$BASE_PY" >/dev/null
fi
uv sync --directory "$SKILL_DIR" --python "$VENV_PY" >/dev/null
: > "$STAMP_FILE"
printf '%s\n' "$VENV_PY"
