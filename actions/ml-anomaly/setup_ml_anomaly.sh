#!/bin/bash
set -euo pipefail
# Setup script for ML-based anomaly detection + free-LLM remediation.

# Source distribution detection
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
# shellcheck disable=SC1091  # resolved at runtime
source "$PROJECT_ROOT/detect-distribution.sh"

# Initialize distribution settings
detect_distribution
set_package_manager

echo "Setting up ML-based Anomaly Detection for $DISTRO_NAME..."

# Install Python dependencies
echo "Installing Python dependencies..."
$PKG_INSTALL python3 python3-pip python3-venv

# Create virtual environment
echo "Creating Python virtual environment..."
cd "$SCRIPT_DIR"
python3 -m venv venv
# shellcheck disable=SC1091  # resolved at runtime
source venv/bin/activate

# Install Python packages
echo "Installing ML libraries..."
pip install --upgrade pip
pip install numpy pandas scikit-learn scipy matplotlib seaborn joblib prometheus-client requests

# Install fix engine dependency (local free LLM via Ollama)
echo "Setting up free local LLM (Ollama) for remediation..."
if command -v ollama >/dev/null 2>&1; then
    OLLAMA_MODEL="${ML_FIX_MODEL:-llama3.2}"
    echo "Pulling Ollama model: $OLLAMA_MODEL (free, open-weight, runs locally)"
    if ! ollama list 2>/dev/null | grep -q "$OLLAMA_MODEL"; then
        ollama pull "$OLLAMA_MODEL" || echo "WARN: could not pull $OLLAMA_MODEL; run 'ollama pull $OLLAMA_MODEL' later"
    fi
    if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
        echo "Starting Ollama service..."
        ollama serve >/var/log/ml-anomaly/ollama.log 2>&1 &
        sleep 5
    fi
else
    echo "WARN: ollama not found. Install Ollama (https://ollama.com) to enable free-model remediation."
    echo "      The fix engine will still run in report-only mode and degrade gracefully."
fi

# Create necessary directories
echo "Creating directories for ML anomaly detection..."
sudo mkdir -p /var/log/ml-anomaly
sudo mkdir -p /var/lib/ml-anomaly/models
sudo mkdir -p /var/lib/ml-anomaly/metrics
sudo mkdir -p /var/lib/ml-anomaly/remediation

# Set permissions
sudo chown -R "$USER:$USER" /var/log/ml-anomaly
sudo chown -R "$USER:$USER" /var/lib/ml-anomaly

# Continuous detection service
sudo tee /etc/systemd/system/ml-anomaly-detection.service >/dev/null <<EOF
[Unit]
Description=ML-based Anomaly Detection
After=network.target docker.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$SCRIPT_DIR
Environment=PATH=$SCRIPT_DIR/venv/bin
ExecStart=$SCRIPT_DIR/venv/bin/python $SCRIPT_DIR/anomaly_detector.py --mode continuous
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Training service
sudo tee /etc/systemd/system/ml-anomaly-training.service >/dev/null <<EOF
[Unit]
Description=ML Anomaly Detection Training
After=network.target

[Service]
Type=oneshot
User=$USER
WorkingDirectory=$SCRIPT_DIR
Environment=PATH=$SCRIPT_DIR/venv/bin
ExecStart=$SCRIPT_DIR/venv/bin/python $SCRIPT_DIR/anomaly_detector.py --mode train --training-samples 100

[Install]
WantedBy=multi-user.target
EOF

# Training timer (weekly)
sudo tee /etc/systemd/system/ml-anomaly-training.timer >/dev/null <<EOF
[Unit]
Description=Weekly ML Anomaly Detection Model Training

[Timer]
OnCalendar=weekly
Persistent=true

[Install]
WantedBy=timers.target
EOF

# Single detection service
sudo tee /etc/systemd/system/ml-anomaly-detect.service >/dev/null <<EOF
[Unit]
Description=ML Anomaly Detection (Single Check)
After=network.target

[Service]
Type=oneshot
User=$USER
WorkingDirectory=$SCRIPT_DIR
Environment=PATH=$SCRIPT_DIR/venv/bin
ExecStart=$SCRIPT_DIR/venv/bin/python $SCRIPT_DIR/anomaly_detector.py --mode detect

[Install]
WantedBy=multi-user.target
EOF

# Fix-engine pipeline service (detect -> free-LLM remediation)
sudo tee /etc/systemd/system/ml-anomaly-fix.service >/dev/null <<EOF
[Unit]
Description=ML Anomaly Detection + Free-LLM Remediation Pipeline
After=network.target docker.service ml-anomaly-detection.service

[Service]
Type=oneshot
User=$USER
WorkingDirectory=$SCRIPT_DIR
Environment=PATH=$SCRIPT_DIR/venv/bin
Environment=ML_FIX_MODE=report
ExecStart=$SCRIPT_DIR/run_ml_pipeline.sh

[Install]
WantedBy=multi-user.target
EOF

# Fix pipeline timer (every 15 minutes)
sudo tee /etc/systemd/system/ml-anomaly-fix.timer >/dev/null <<EOF
[Unit]
Description=ML Anomaly + Remediation Pipeline (every 15 min)

[Timer]
OnCalendar=*:0/15
Persistent=true

[Install]
WantedBy=timers.target
EOF

# Prometheus exporter
sudo tee "$SCRIPT_DIR/ml_metrics_exporter.py" >/dev/null <<'EXPORTER'
#!/usr/bin/env python3
"""
Prometheus exporter for ML anomaly detection metrics
"""

from prometheus_client import start_http_server, Gauge, Counter
import json
import time
import os
from datetime import datetime

ANOMALY_DETECTIONS = Counter('ml_anomaly_detections_total', 'Total number of anomaly detections')
ANOMALY_SCORES = Gauge('ml_anomaly_latest_score', 'Latest anomaly score')
MODEL_TRAINING_TIME = Gauge('ml_model_training_duration_seconds', 'Duration of model training')
MODEL_ACCURACY = Gauge('ml_model_accuracy', 'Model accuracy metric')
SYSTEM_METRICS = Gauge('ml_system_metric', 'Current system metric', ['metric_name'])

def export_ml_metrics():
    metrics_file = '/var/log/ml-anomaly/latest_detection.json'
    if os.path.exists(metrics_file):
        with open(metrics_file, 'r') as f:
            data = json.load(f)
        if data.get('is_anomaly'):
            ANOMALY_DETECTIONS.inc()
        if 'anomaly_score' in data:
            ANOMALY_SCORES.set(data['anomaly_score'])
        if 'individual_results' in data:
            for detector_name, result in data['individual_results'].items():
                if result and 'anomaly_score' in result:
                    SYSTEM_METRICS.labels(metric_name=f'{detector_name}_score').set(result['anomaly_score'])

def main():
    start_http_server(8090)
    print("ML metrics exporter started on port 8090")
    while True:
        export_ml_metrics()
        time.sleep(60)

if __name__ == '__main__':
    main()
EXPORTER

# Metrics exporter service
sudo tee /etc/systemd/system/ml-metrics-exporter.service >/dev/null <<EOF
[Unit]
Description=ML Anomaly Detection Metrics Exporter
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$SCRIPT_DIR
Environment=PATH=$SCRIPT_DIR/venv/bin
ExecStart=$SCRIPT_DIR/venv/bin/python $SCRIPT_DIR/ml_metrics_exporter.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ml-anomaly-detection.service
sudo systemctl enable ml-anomaly-training.timer
sudo systemctl start ml-anomaly-training.timer
sudo systemctl enable ml-metrics-exporter.service
sudo systemctl enable ml-anomaly-fix.timer
sudo systemctl start ml-anomaly-fix.timer

echo ""
echo "ML-based Anomaly Detection setup completed!"
echo ""
echo "Installation directories:"
echo "  - Scripts: $SCRIPT_DIR"
echo "  - Logs: /var/log/ml-anomaly"
echo "  - Models: /var/lib/ml-anomaly/models"
echo "  - Metrics: /var/lib/ml-anomaly/metrics"
echo ""
echo "Services:"
echo "  - ml-anomaly-detection.service: Continuous monitoring"
echo "  - ml-anomaly-training.timer: Weekly model training"
echo "  - ml-metrics-exporter.service: Prometheus metrics on port 8090"
echo "  - ml-anomaly-fix.timer: Detect + free-LLM remediation every 15 min"
echo ""
echo "Free-model remediation:"
echo "  - Provider: Ollama (local, open-weight, zero cost)"
echo "  - Mode: report (safe default). Set ML_FIX_MODE=apply to auto-apply safe fixes."
echo "  - Only allow-listed, reversible commands are auto-applied."
echo ""
echo "Commands:"
echo "  - Start continuous monitoring: sudo systemctl start ml-anomaly-detection"
echo "  - Run single detection: sudo systemctl start ml-anomaly-detect"
echo "  - Train models manually: sudo systemctl start ml-anomaly-training"
echo "  - Run fix pipeline (dry-run): sudo ML_FIX_MODE=dry-run $SCRIPT_DIR/run_ml_pipeline.sh"
echo "  - View logs: sudo journalctl -u ml-anomaly-detection -f"
echo "  - View metrics: curl http://localhost:8090/metrics"
echo ""
echo "Important:"
echo "  - Models need at least 10 training samples for initial training"
echo "  - Training happens automatically weekly, or manually via service"
echo "  - Continuous monitoring starts after initial training"
echo "  - Tune anomaly thresholds based on your system behavior"
echo "  - Remediation is report-only by default; review before enabling apply mode"
