#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$SKILL_DIR/.env"
SYSTEM_ONLY=0
if [ "${1:-}" = "--system" ]; then
  SYSTEM_ONLY=1
fi

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

if [ "$SYSTEM_ONLY" -eq 0 ] && [ -x "$SKILL_DIR/.venv/bin/python" ]; then
  printf '%s\n' "$SKILL_DIR/.venv/bin/python"
  exit 0
fi

if [ -n "${STOCK_ANALYSIS_PYTHON:-}" ]; then
  if resolved="$(resolve_candidate "$STOCK_ANALYSIS_PYTHON")"; then
    printf '%s\n' "$resolved"
    exit 0
  fi
fi

candidates=(
  python3.13
  python3.12
  /usr/local/bin/python3.13
  /usr/local/bin/python3.12
  /usr/bin/python3.13
  /usr/bin/python3.12
  python3.11
  /usr/local/bin/python3.11
  /usr/bin/python3.11
  python3.10
  /usr/local/bin/python3.10
  /usr/bin/python3.10
  python3
  /usr/local/bin/python3
  /usr/bin/python3
  python
)

for candidate in "${candidates[@]}"; do
  if resolved="$(resolve_candidate "$candidate")"; then
    printf '%s\n' "$resolved"
    exit 0
  fi
done

echo "未找到可用的 Python 解释器。请在 .env 中设置 STOCK_ANALYSIS_PYTHON=/path/to/python，或安装 python3.12+/python3。" >&2
exit 1
