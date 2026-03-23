#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="$($SCRIPT_DIR/ensure_venv.sh)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

if [ "$#" -lt 1 ]; then
  echo "用法: prepare_stock.sh 股票代码 [市场]" >&2
  exit 1
fi

SYMBOL="$1"
MARKET="${2:-auto}"

if [ "$MARKET" = "auto" ]; then
  upper_symbol="$(printf '%s' "$SYMBOL" | tr '[:lower:]' '[:upper:]')"
  if printf '%s' "$upper_symbol" | grep -Eq '(^[0-9]{6}$)|\.(SS|SZ)$'; then
    MARKET="cn"
  elif printf '%s' "$upper_symbol" | grep -Eq '(^HK[0-9]+$)|\.(HK)$|(^[0-9]{1,5}$)'; then
    MARKET="hk"
  else
    MARKET="us"
  fi
fi

"$SCRIPT_DIR/fetch_quotes.sh" "$SYMBOL" > "$TMP_DIR/quotes.json"
NEWS_ARG="$("$PYTHON_BIN" - <<'PY' "$TMP_DIR/quotes.json" "$SYMBOL"
import json, sys
with open(sys.argv[1], 'r', encoding='utf-8') as f:
    data = json.load(f)
symbol = sys.argv[2]
name = None
for item in data.get('symbols') or []:
    if (item.get('symbol') or '').lower() == symbol.lower():
        name = item.get('name')
        break
print(f"{symbol}::{name}" if name else symbol)
PY
)"
"$SCRIPT_DIR/fetch_news.sh" "$NEWS_ARG" > "$TMP_DIR/news.json"
"$SCRIPT_DIR/fetch_market.sh" "$MARKET" > "$TMP_DIR/market.json"
"$PYTHON_BIN" "$SCRIPT_DIR/normalize_data.py" "$TMP_DIR/quotes.json" "$TMP_DIR/news.json" "$TMP_DIR/market.json" > "$TMP_DIR/normalized.json"
REQUESTED_MARKET="$MARKET"
MARKET_SOURCE="auto"
if [ $# -ge 2 ] && [ "$2" != "auto" ]; then
  REQUESTED_MARKET="$2"
  MARKET_SOURCE="explicit"
fi
"$PYTHON_BIN" "$SCRIPT_DIR/build_analysis_context.py" --mode stock --input "$TMP_DIR/normalized.json" --symbol "$SYMBOL" --market "$MARKET" --requested-market "$REQUESTED_MARKET" --market-source "$MARKET_SOURCE" > "$TMP_DIR/context.json"
"$PYTHON_BIN" "$SCRIPT_DIR/build_host_prompt.py" --mode stock --context "$TMP_DIR/context.json"
