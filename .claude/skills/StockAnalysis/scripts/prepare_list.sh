#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="$($SCRIPT_DIR/ensure_venv.sh)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

if [ "$#" -lt 2 ]; then
  echo "用法: prepare_list.sh 市场 股票代码1 [股票代码2 ...]" >&2
  exit 1
fi

MARKET="$1"
shift
SYMBOLS=("$@")

"$SCRIPT_DIR/fetch_quotes.sh" "${SYMBOLS[@]}" > "$TMP_DIR/quotes.json"
mapfile -t NEWS_ARGS < <("$PYTHON_BIN" - <<'PY' "$TMP_DIR/quotes.json" "${SYMBOLS[@]}"
import json, sys
with open(sys.argv[1], 'r', encoding='utf-8') as f:
    data = json.load(f)
want = {s.lower(): s for s in sys.argv[2:]}
for item in data.get('symbols') or []:
    symbol = item.get('symbol') or ''
    if symbol.lower() in want:
        name = item.get('name')
        print(f"{want[symbol.lower()]}::{name}" if name else want[symbol.lower()])
PY
)
"$SCRIPT_DIR/fetch_news.sh" "${NEWS_ARGS[@]}" > "$TMP_DIR/news.json"
"$SCRIPT_DIR/fetch_market.sh" "$MARKET" > "$TMP_DIR/market.json"
"$PYTHON_BIN" "$SCRIPT_DIR/normalize_data.py" "$TMP_DIR/quotes.json" "$TMP_DIR/news.json" "$TMP_DIR/market.json" > "$TMP_DIR/normalized.json"
"$PYTHON_BIN" "$SCRIPT_DIR/build_host_prompt.py" --mode list --input "$TMP_DIR/normalized.json" --market "$MARKET" --symbols "${SYMBOLS[@]}"
