#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-.}"
exit_code=0

echo "==> Running tests in $TARGET..."

cd "$TARGET"

if [ -f pyproject.toml ]; then
    echo "--- Python tests ---"
    if python -m pytest tests/ -v --tb=short --no-header --cov=src/ --cov-report=term-missing 2>/dev/null; then
        echo "Python tests: PASSED"
    else
        echo "Python tests: FAILED"
        exit_code=1
    fi
fi

if [ -f package.json ]; then
    echo "--- JavaScript/TypeScript tests ---"
    if npm test -- --run 2>/dev/null || npx vitest run 2>/dev/null || npx jest --passWithNoTests 2>/dev/null; then
        echo "JS/TS tests: PASSED"
    else
        echo "JS/TS tests: FAILED"
        exit_code=1
    fi
fi

exit "$exit_code"