#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$SKILL_DIR/.env"
ENV_EXAMPLE="$SKILL_DIR/.env.example"
PYTHON_BIN="$($SCRIPT_DIR/ensure_venv.sh 2>/dev/null || true)"

if [ -f "$ENV_FILE" ]; then
  set -a
  . "$ENV_FILE"
  set +a
fi

status_cmd() {
  local name="$1"
  local cmd="$2"
  if command -v "$cmd" >/dev/null 2>&1; then
    printf '  [OK] %s: %s\n' "$name" "$(command -v "$cmd")"
  else
    printf '  [缺失] %s\n' "$name"
  fi
}

status_key() {
  local label="$1"
  local value="$2"
  if [ -n "$value" ]; then
    printf '  [已配置] %s\n' "$label"
  else
    printf '  [未配置] %s\n' "$label"
  fi
}

first_csv_value() {
  local raw="$1"
  raw="${raw%%,*}"
  printf '%s' "$raw"
}

printf 'StockAnalysis 环境检查\n'
printf '=======================\n'

printf '\n[基础依赖]\n'
status_cmd "bash" bash
status_cmd "uv" uv
status_cmd "python3" python3
if [ -n "$PYTHON_BIN" ]; then
  printf "  [解析] StockAnalysis Python: %s\n" "$PYTHON_BIN"
else
  printf "  [解析失败] StockAnalysis Python\n"
fi
status_cmd "curl" curl

printf '\n[配置文件]\n'
if [ -f "$ENV_FILE" ]; then
  printf '  [OK] .env: %s\n' "$ENV_FILE"
else
  printf '  [未找到] .env: %s\n' "$ENV_FILE"
  if [ -f "$ENV_EXAMPLE" ]; then
    printf '  [参考模板] .env.example: %s\n' "$ENV_EXAMPLE"
  fi
fi

printf '\n[模型配置]\n'
status_key "OPENAI_API_KEY" "${OPENAI_API_KEY:-}"
status_key "OPENAI_BASE_URL" "${OPENAI_BASE_URL:-}"
printf '  OPENAI_MODEL: %s\n' "${OPENAI_MODEL:-未设置}"

printf '\n[数据源配置]\n'
printf '  QUOTE_PROVIDER: %s\n' "${QUOTE_PROVIDER:-yfinance}"
printf '  MARKET_PROVIDER: %s\n' "${MARKET_PROVIDER:-yfinance}"
printf '  NEWS_PROVIDER_PRIORITY: %s\n' "${NEWS_PROVIDER_PRIORITY:-tavily,serpapi,brave,bocha}"
printf '  DEFAULT_MARKET: %s\n' "${DEFAULT_MARKET:-cn}"
printf '  DEFAULT_STRATEGIES: %s\n' "${DEFAULT_STRATEGIES:-未设置}"
printf '  NEWS_MAX_AGE_DAYS: %s\n' "${NEWS_MAX_AGE_DAYS:-3}"
printf '  BIAS_THRESHOLD: %s\n' "${BIAS_THRESHOLD:-5}"
printf '  REQUEST_TIMEOUT: %s\n' "${REQUEST_TIMEOUT:-20}"
printf '  STOCK_ANALYSIS_PYTHON: %s\n' "${STOCK_ANALYSIS_PYTHON:-未设置}"
printf '  VENV_DIR: %s\n' "$SKILL_DIR/.venv"

printf '\n[新闻 Key]\n'
status_key "TAVILY_API_KEY" "${TAVILY_API_KEY:-}"
status_key "SERPAPI_API_KEY" "${SERPAPI_API_KEY:-}"
status_key "BRAVE_API_KEY / BRAVE_API_KEYS" "$(first_csv_value "${BRAVE_API_KEY:-${BRAVE_API_KEYS:-}}")"
status_key "BOCHA_API_KEY / BOCHA_API_KEYS" "$(first_csv_value "${BOCHA_API_KEY:-${BOCHA_API_KEYS:-}}")"

printf '\n[其他 Key]\n'
status_key "TUSHARE_TOKEN" "${TUSHARE_TOKEN:-}"

printf '\n[快速结论]\n'
news_ready=0
[ -n "${TAVILY_API_KEY:-}" ] && news_ready=1
[ -n "${SERPAPI_API_KEY:-}" ] && news_ready=1
[ -n "$(first_csv_value "${BRAVE_API_KEY:-${BRAVE_API_KEYS:-}}")" ] && news_ready=1
[ -n "$(first_csv_value "${BOCHA_API_KEY:-${BOCHA_API_KEYS:-}}")" ] && news_ready=1

if [ "$news_ready" -eq 1 ]; then
  printf '  - 新闻搜索: 可用\n'
else
  printf '  - 新闻搜索: 不可用，当前没有配置任何新闻 provider 的 Key\n'
fi

if [ -n "$PYTHON_BIN" ] && command -v curl >/dev/null 2>&1; then
  printf '  - 核心脚本运行条件: 基本满足\n'
else
  printf '  - 核心脚本运行条件: 不满足，请先配置可用 Python 或补齐 bash/python3/curl\n'
fi
