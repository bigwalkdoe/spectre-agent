#!/bin/bash
set -euo pipefail

# Configuration Backup Script
# Backs up system and application configurations

BACKUP_DIR="${BACKUP_DIR:-/backups/configurations}"
# Directory containing project configs to back up. Override per environment.
PROJECTS_DIR="${PROJECTS_DIR:-$PROJECTS_ROOT}"
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=30

mkdir -p "$BACKUP_DIR"

echo "Backing up system configurations..."

# System configurations
echo "Backing up systemd configurations..."
sudo mkdir -p "$BACKUP_DIR/systemd_$DATE"
sudo cp -r /etc/systemd/system/. "$BACKUP_DIR/systemd_$DATE/" 2>/dev/null || true
sudo tar czf "$BACKUP_DIR/systemd_configs_$DATE.tar.gz" -C /etc systemd/system 2>/dev/null || true

# Docker configurations
echo "Backing up Docker configurations..."
sudo tar czf "$BACKUP_DIR/docker_configs_$DATE.tar.gz" -C /etc docker 2>/dev/null || true

# SSH configuration
echo "Backing up SSH configuration..."
sudo cp /etc/ssh/sshd_config "$BACKUP_DIR/sshd_config_$DATE" 2>/dev/null || true

# Firewall configuration
echo "Backing up firewall configuration..."
sudo firewall-cmd --list-all 2>/dev/null | sudo tee "$BACKUP_DIR/firewall_config_$DATE.txt" >/dev/null || true

# Fail2Ban configuration
echo "Backing up Fail2Ban configuration..."
sudo cp /etc/fail2ban/jail.local "$BACKUP_DIR/fail2ban_jail_$DATE" 2>/dev/null || true

# DNF configuration
echo "Backing up DNF configuration..."
sudo cp /etc/dnf/dnf5-automatic.conf "$BACKUP_DIR/dnf-automatic_$DATE" 2>/dev/null || true

# Project configurations
# NOTE: Only non-secret configs are included. .env files (which may contain
# credentials) are deliberately excluded to avoid leaking secrets into backups.
echo "Backing up project configurations..."
if [[ -d "$PROJECTS_DIR/Guardrail-AI" ]]; then
    tar czf "$BACKUP_DIR/projects_config_$DATE.tar.gz" \
        -C "$PROJECTS_DIR" Guardrail-AI/dk-compose.yml 2>/dev/null || true
fi

# Cleanup old backups
echo "Cleaning up old configuration backups (older than $RETENTION_DAYS days)..."
find "$BACKUP_DIR" -maxdepth 1 -type f -mtime +"$RETENTION_DAYS" -delete
# Only prune timestamped backup directories we created (systemd_*, *_$DATE style).
find "$BACKUP_DIR" -maxdepth 1 -type d -name '*_[0-9][0-9][0-9][0-9]*' -mtime +"$RETENTION_DAYS" -exec rm -rf {} + 2>/dev/null || true

echo "Configuration backup completed: $DATE"
logger -p user.info "Configuration backup completed successfully" 2>/dev/null || true
