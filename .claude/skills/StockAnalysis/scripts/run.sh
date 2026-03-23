#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="$($SCRIPT_DIR/resolve_python.sh)"

usage() {
  cat <<'TEXT'
用法:
  run.sh doctor
  run.sh status
  run.sh set-env KEY=VALUE [KEY=VALUE ...]
  run.sh init
  run.sh stock 股票代码 [市场]
  run.sh market 市场
  run.sh strategy 股票代码 策略名 [市场]
  run.sh list 市场 股票代码1 [股票代码2 ...]

说明:
  doctor/status 用于查看当前配置与能力状态
  set-env 用于把对话中拿到的配置值写入 .env
  stock/market/strategy/list 输出给宿主智能体使用的分析上下文
TEXT
}

if [ "$#" -lt 1 ]; then
  usage >&2
  exit 1
fi

MODE="$1"
shift

case "$MODE" in
  doctor|status)
    exec "$PYTHON_BIN" "$SCRIPT_DIR/skill_status.py"
    ;;
  set-env)
    if [ "$#" -lt 1 ]; then
      echo "用法: run.sh set-env KEY=VALUE [KEY=VALUE ...]" >&2
      exit 1
    fi
    args=()
    for pair in "$@"; do
      args+=(--set "$pair")
    done
    exec "$PYTHON_BIN" "$SCRIPT_DIR/set_env.py" "${args[@]}"
    ;;
  init)
    exec "$SCRIPT_DIR/init_env.sh" "$@"
    ;;
  stock)
    exec "$SCRIPT_DIR/analyze_stock.sh" "$@"
    ;;
  market)
    exec "$SCRIPT_DIR/analyze_market.sh" "$@"
    ;;
  strategy)
    exec "$SCRIPT_DIR/analyze_strategy.sh" "$@"
    ;;
  list)
    exec "$SCRIPT_DIR/analyze_list.sh" "$@"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    echo "未知模式: $MODE" >&2
    usage >&2
    exit 1
    ;;
esac
