#!/usr/bin/env bash
set -euo pipefail

SPECTRE_HOME="${SPECTRE_HOME:-$HOME/.spectre}"

echo "==> Updating Spectre..."

if [ -d "$SPECTRE_HOME/.git" ]; then
    git -C "$SPECTRE_HOME" pull --ff-only
fi

pip install --upgrade pip ruff mypy pytest pytest-asyncio httpx pre-commit 2>/dev/null || true

echo "==> Update complete."