#!/usr/bin/env bash
set -euo pipefail

echo "==> Creating Python virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

echo "==> Installing essential tools..."
pip install --upgrade pip
pip install ruff mypy pytest pytest-asyncio httpx pre-commit

if command -v npm &>/dev/null; then
    echo "==> Installing Node.js tools..."
    npm install -g prettier eslint
fi

echo "==> Bootstrap complete."
