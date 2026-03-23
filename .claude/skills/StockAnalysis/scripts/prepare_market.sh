#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="$($SCRIPT_DIR/ensure_venv.sh)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

MARKET="${1:-${DEFAULT_MARKET:-cn}}"

"$SCRIPT_DIR/fetch_market.sh" "$MARKET" > "$TMP_DIR/market.json"
"$PYTHON_BIN" "$SCRIPT_DIR/normalize_data.py" "$TMP_DIR/market.json" > "$TMP_DIR/normalized.json"
"$PYTHON_BIN" "$SCRIPT_DIR/build_analysis_context.py" --mode market --input "$TMP_DIR/normalized.json" --market "$MARKET" > "$TMP_DIR/context.json"
"$PYTHON_BIN" "$SCRIPT_DIR/build_host_prompt.py" --mode market --context "$TMP_DIR/context.json"
