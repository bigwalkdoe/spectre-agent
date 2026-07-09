#!/usr/bin/env bash
# Spectre Bootstrap — installs the full Spectre Engineering OS on a new machine
set -euo pipefail

SPECTRE_HOME="${SPECTRE_HOME:-$HOME/.spectre}"
SPECTRE_REPO="${SPECTRE_REPO:-bigwalkdoe/spectre}"
OPENCODE_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"

echo "==> Spectre Bootstrap v0.2.0"

# --- Clone Spectre ---
if [ ! -d "$SPECTRE_HOME" ]; then
    echo "==> Cloning Spectre from $SPECTRE_REPO..."
    git clone "https://github.com/$SPECTRE_REPO.git" "$SPECTRE_HOME"
else
    echo "==> Spectre already exists at $SPECTRE_HOME, pulling updates..."
    git -C "$SPECTRE_HOME" pull --ff-only
fi

# --- Link OpenCode config ---
if [ -d "$OPENCODE_CONFIG_DIR" ]; then
    mkdir -p "$OPENCODE_CONFIG_DIR/agents"
    cp -n "$SPECTRE_HOME/../.config/opencode/opencode.json" "$OPENCODE_CONFIG_DIR/opencode.json" 2>/dev/null || true
    cp -n "$SPECTRE_HOME/../.config/opencode/agents"/*.md "$OPENCODE_CONFIG_DIR/agents/" 2>/dev/null || true
    echo "==> OpenCode config linked"
else
    echo "==> OpenCode config dir missing — install opencode first, then re-run"
fi

# --- Source shell integration ---
SHELL_RC="$HOME/.bashrc"
if [ -f "$SHELL_RC" ] && ! grep -q "spectre" "$SHELL_RC" 2>/dev/null; then
    echo "" >> "$SHELL_RC"
    echo "# Spectre Engineering OS" >> "$SHELL_RC"
    echo "[ -f \$HOME/.bashrc.d/spectre ] && source \$HOME/.bashrc.d/spectre" >> "$SHELL_RC"
    echo "==> Shell integration added to $SHELL_RC"
fi

# --- Install system deps ---
if command -v dnf &>/dev/null; then
    echo "==> Installing system dependencies..."
    sudo dnf install -y git python3-pip nodejs npm podman podman-compose 2>/dev/null || true
fi

# --- Install Python tools ---
pip3 install --user --upgrade ruff mypy pytest pytest-asyncio httpx pre-commit 2>/dev/null || true

# --- Install Node tools ---
npm install -g prettier eslint 2>/dev/null || true

# --- Run security check on Spectre itself ---
echo "==> Running initial security scan..."
bash "$SPECTRE_HOME/scripts/security.sh" "$SPECTRE_HOME" || true

echo "==> Bootstrap complete!"
echo "==> Restart your shell or run: source \$HOME/.bashrc.d/spectre"
