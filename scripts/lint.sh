#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-.}"
exit_code=0

cd "$TARGET"

if [ -f pyproject.toml ]; then
    echo "=== Python lint ==="
    ruff format --check . || { echo "FAIL: ruff format"; exit_code=1; }
    ruff check . || { echo "FAIL: ruff check"; exit_code=1; }
    mypy src/ --strict || { echo "FAIL: mypy"; exit_code=1; }
fi

if [ -f package.json ]; then
    echo "=== JavaScript/TypeScript lint ==="
    npx prettier --check . 2>/dev/null || { echo "FAIL: prettier"; exit_code=1; }
    npx eslint src/ --max-warnings=0 2>/dev/null || { echo "FAIL: eslint"; exit_code=1; }
fi

exit "$exit_code"