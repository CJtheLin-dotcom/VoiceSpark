#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${DIR}"

echo "🚀 准备启动 VoiceSpark 本地开发环境..."

# Use virtualenv python
if [ -f ".venv/bin/python" ]; then
  PYTHON_EXEC=".venv/bin/python"
elif command -v python3 &>/dev/null; then
  PYTHON_EXEC="python3"
else
  echo "❌ 未找到 Python 环境"
  exit 1
fi

PORT="${1:-${PORT:-8085}}"

echo "=================================================="
echo "🎉 启动 VoiceSpark 服务..."
echo "👉 本地访问地址: http://localhost:${PORT}"
echo "=================================================="

exec ${PYTHON_EXEC} -m uvicorn backend.main:app --host 0.0.0.0 --port "${PORT}" --reload
