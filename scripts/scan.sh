#!/usr/bin/env bash
set -euo pipefail

# Run the full Spectre Agent scan and emit human-readable output.
# Usage: scripts/scan.sh [--json]

cd "$(dirname "$0")/.."
if [ ! -d .venv ]; then
    python -m venv .venv
    .venv/bin/pip install -e ".[dev]" >/dev/null
fi
.venv/bin/spectre scan --all "$@"
