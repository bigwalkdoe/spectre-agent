#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/backend/gateway"

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

exec uvicorn gateway.main:app --reload --host 0.0.0.0 --port 8000
