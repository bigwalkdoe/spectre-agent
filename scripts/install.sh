#!/usr/bin/env bash
set -euo pipefail

# Spectre Installer — Fedora Linux
# Installs Spectre system maintenance platform

SPECTRE_HOME="${HOME}/.config/spectre"
VENV_DIR="${SPECTRE_HOME}/venv"
PLUGIN_DIR="${SPECTRE_HOME}/plugins"

echo "=== Spectre Installer ==="
echo ""

# Check Python version
PYTHON=""
for candidate in python3.14 python3.13 python3.12 python3.11; do
    if command -v "$candidate" &>/dev/null; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "Error: Python 3.11+ not found."
    echo "Install with: sudo dnf install python3"
    exit 1
fi

PY_VERSION=$($PYTHON --version 2>&1 | grep -oP '\d+\.\d+')
echo "Found Python $PY_VERSION at $(which $PYTHON)"

# Check for required system tools
echo ""
echo "Checking system tools..."
for tool in git podman; do
    if command -v "$tool" &>/dev/null; then
        echo "  [ok] $tool"
    else
        echo "  [--] $tool (optional, not found)"
    fi
done

# Create directories
echo ""
echo "Creating directories..."
mkdir -p "$SPECTRE_HOME"
mkdir -p "$PLUGIN_DIR"
mkdir -p "${SPECTRE_HOME}/logs"

# Create virtual environment
echo ""
echo "Setting up Python virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    $PYTHON -m venv "$VENV_DIR"
    echo "Created venv at $VENV_DIR"
else
    echo "Venv already exists at $VENV_DIR"
fi

# Install package
echo ""
echo "Installing Spectre..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -e "${PROJECT_DIR}[dev]" -q

# Create symlink
SPECTRE_BIN="${VENV_DIR}/bin/spectre"
if [ -f "$SPECTRE_BIN" ]; then
    echo ""
    echo "Creating symlink at /usr/local/bin/spectre (requires sudo)..."
    sudo ln -sf "$SPECTRE_BIN" /usr/local/bin/spectre 2>/dev/null || true
    echo "Or add to PATH: export PATH=\"$VENV_DIR/bin:\$PATH\""
fi

# Install systemd service
echo ""
read -p "Install systemd user service? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    SYSTEMD_DIR="${HOME}/.config/systemd/user"
    mkdir -p "$SYSTEMD_DIR"
    cp "${PROJECT_DIR}/scripts/spectre.service" "$SYSTEMD_DIR/"
    systemctl --user daemon-reload
    echo "Systemd service installed. Start with:"
    echo "  systemctl --user start spectre"
    echo "  systemctl --user enable spectre"
fi

# Create default config
echo ""
if [ ! -f "${SPECTRE_HOME}/settings.yaml" ]; then
    echo "Creating default configuration..."
    cat > "${SPECTRE_HOME}/settings.yaml" << 'EOF'
profile: laptop

ollama:
  url: "http://localhost:11434"
  benchmark_model: "llama3.2:3b"

monitoring:
  interval_seconds: 30
  enabled: true

schedules:
  - name: "morning"
    schedule: "every 24h"
    enabled: true
  - name: "weekly"
    schedule: "every 168h"
    enabled: true

agents: {}

log_level: "INFO"
EOF
    echo "Configuration created at ${SPECTRE_HOME}/settings.yaml"
else
    echo "Configuration already exists, skipping."
fi

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Quick start:"
echo "  spectre doctor       # Run diagnostics"
echo "  spectre health       # System health metrics"
echo "  spectre status       # Overall status"
echo "  spectre --help       # All commands"
echo ""
echo "Daemon:"
echo "  spectre-daemon       # Start background monitoring"
echo "  make run-daemon      # Or via Makefile"
echo ""
echo "API:"
echo "  make run-api         # Start REST API on :8080"
