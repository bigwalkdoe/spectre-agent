#!/bin/bash
# ML Anomaly Detection + Auto-Remediation Pipeline
#
# 1. Detect anomalies with the ML detector (writes latest_detection.json)
# 2. If an anomaly is found, ask the free local LLM for a remediation plan
# 3. Validate and (optionally) apply safe fixes, then report to Alertmanager
#
# Free models: uses Ollama (local) by default. Configure via env:
#   ML_FIX_PROVIDER=ollama|openai-compatible
#   ML_FIX_MODEL=llama3.2
#   OLLAMA_HOST=http://localhost:11434
#   ML_FIX_WEBHOOK=http://localhost:9093/api/v1/alerts   (optional)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Resolve the report path to a writable location (mirrors the Python fallback).
DEFAULT_REPORT="/var/log/ml-anomaly/latest_detection.json"
if [ -w "$(dirname "$DEFAULT_REPORT" 2>/dev/null)" ]; then
    REPORT="${ML_DETECT_REPORT:-$DEFAULT_REPORT}"
    export ML_LOG_DIR="/var/log/ml-anomaly"
else
    REPORT="${ML_DETECT_REPORT:-/tmp/ml-anomaly/latest_detection.json}"
    export ML_LOG_DIR="/tmp/ml-anomaly"
fi

MODE="${ML_FIX_MODE:-report}"
WEBHOOK="${ML_FIX_WEBHOOK:-}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }

if [ ! -d "$SCRIPT_DIR/venv" ]; then
    log "Python venv not found at $SCRIPT_DIR/venv; using system python3"
    PY="$SCRIPT_DIR"
else
    PY="$SCRIPT_DIR/venv"
fi

PYBIN="$PY/bin/python"
if [ ! -x "$PYBIN" ]; then
    PYBIN="$(command -v python3)"
fi

log "=== ML Pipeline: detect ==="
"$PYBIN" "$SCRIPT_DIR/anomaly_detector.py" --mode detect --output "$REPORT" || {
    log "ERROR: anomaly detection failed"
    exit 1
}

if [ ! -f "$REPORT" ]; then
    log "ERROR: no detection report produced"
    exit 1
fi

IS_ANOMALY="$("$PYBIN" -c "import json,sys; print(json.load(open('$REPORT')).get('is_anomaly', False))")"

if [ "$IS_ANOMALY" != "True" ]; then
    log "No anomaly detected. Pipeline complete."
    exit 0
fi

log "=== ML Pipeline: fix (mode=$MODE) ==="
"$PYBIN" "$SCRIPT_DIR/ml_fix_engine.py" \
    --anomaly-report "$REPORT" \
    --mode "$MODE" \
    ${WEBHOOK:+--alertmanager-webhook "$WEBHOOK"}

log "=== ML Pipeline complete ==="
