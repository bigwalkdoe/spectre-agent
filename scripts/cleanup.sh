#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-.}"
SPECTRE_HOME="${SPECTRE_HOME:-$HOME/.spectre}"

echo "==> Cleaning up $TARGET..."

# Python cache
find "$TARGET" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
find "$TARGET" -type f -name '*.pyc' -delete 2>/dev/null || true
find "$TARGET" -type f -name '*.pyo' -delete 2>/dev/null || true
find "$TARGET" -type f -name '.coverage' -delete 2>/dev/null || true
find "$TARGET" -type d -name '.pytest_cache' -exec rm -rf {} + 2>/dev/null || true
find "$TARGET" -type d -name '.ruff_cache' -exec rm -rf {} + 2>/dev/null || true
find "$TARGET" -type d -name '.mypy_cache' -exec rm -rf {} + 2>/dev/null || true

# Node artifacts
find "$TARGET" -maxdepth 3 -type d -name 'node_modules' -exec rm -rf {} + 2>/dev/null || true
find "$TARGET" -type d -name '.next' -exec rm -rf {} + 2>/dev/null || true

# Build artifacts
find "$TARGET" -maxdepth 3 -type d -name 'dist' -exec rm -rf {} + 2>/dev/null || true
find "$TARGET" -maxdepth 3 -type d -name 'build' -exec rm -rf {} + 2>/dev/null || true
find "$TARGET" -maxdepth 3 -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
find "$TARGET" -maxdepth 2 -type d -name '.venv' -exec rm -rf {} + 2>/dev/null || true
find "$TARGET" -maxdepth 2 -type d -name 'venv' -exec rm -rf {} + 2>/dev/null || true

# Docker dangling images
podman image prune -f 2>/dev/null || true
docker image prune -f 2>/dev/null || true

# Rotate Spectre logs (keep last 5)
if [ -d "$SPECTRE_HOME/logs" ]; then
  find "$SPECTRE_HOME/logs" -name '*.log' -type f | sort -r | tail -n +6 | xargs rm -f 2>/dev/null || true
fi

echo "Cleanup complete."
