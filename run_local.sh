#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${DIR}"

echo "🚀 准备启动 VoiceSpark 本地开发环境..."

# Check if uv is available
if command -v uv &>/dev/null; then
  UV_CMD="uv"
elif [ -f "$HOME/.local/bin/uv" ]; then
  UV_CMD="$HOME/.local/bin/uv"
else
  echo "ℹ️ 未找到 uv，使用标准 python3 venv..."
fi

if [ -n "${UV_CMD}" ]; then
  if [ ! -d ".venv" ]; then
    echo "📦 使用 uv 创建 Python 虚拟环境 (.venv)..."
    ${UV_CMD} venv .venv
  fi
  echo "📦 安装 / 更新 Python 依赖包..."
  ${UV_CMD} pip install -r requirements.txt
  PYTHON_EXEC=".venv/bin/python"
else
  if [ ! -d ".venv" ]; then
    python3 -m venv .venv
  fi
  source .venv/bin/activate
  pip install -r requirements.txt
  PYTHON_EXEC="python3"
fi

echo "=================================================="
echo "🎉 启动 VoiceSpark 服务..."
echo "👉 本地访问地址: http://localhost:8080"
echo "=================================================="

exec ${PYTHON_EXEC} -m uvicorn backend.main:app --host 0.0.0.0 --port 8080 --reload
