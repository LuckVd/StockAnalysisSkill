#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$SKILL_DIR/.env"
ENV_EXAMPLE="$SKILL_DIR/.env.example"

if [ ! -f "$ENV_EXAMPLE" ]; then
  echo "错误：未找到模板文件 $ENV_EXAMPLE" >&2
  exit 1
fi

if [ -f "$ENV_FILE" ]; then
  echo "已存在 .env 文件：$ENV_FILE"
  echo "未做覆盖。你可以直接编辑它，或先手动删除后再重新执行 init。"
  exit 0
fi

cp "$ENV_EXAMPLE" "$ENV_FILE"
echo "已创建 .env 文件：$ENV_FILE"
echo "下一步建议："
echo "1. 填写至少一个新闻搜索 Key，例如 TAVILY_API_KEY / SERPAPI_API_KEY / BRAVE_API_KEY / BOCHA_API_KEY"
echo "2. 如需自定义模型，填写 OPENAI_API_KEY、OPENAI_BASE_URL、OPENAI_MODEL"
echo "3. 执行 scripts/run.sh doctor 检查配置状态"
