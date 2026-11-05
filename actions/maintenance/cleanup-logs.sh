#!/bin/bash
set -euo pipefail
# Log Cleanup Script
# Manages log rotation and cleanup

echo "Starting log maintenance..."

# Rotate and compress old logs
echo "Rotating application logs..."
find /var/log -name "*.log" -size +100M -exec gzip {} \; 2>/dev/null || true

# Clean very old compressed logs (older than 90 days)
echo "Cleaning old compressed logs..."
find /var/log -name "*.gz" -mtime +90 -delete 2>/dev/null || true

# Clean Docker container logs
echo "Cleaning Docker container logs..."
docker ps -q | xargs -I {} docker inspect {} --format='{{.LogPath}}' | xargs -I {} sh -c 'truncate -s 0 {}' 2>/dev/null || true

# Clean systemd journal logs
echo "Cleaning systemd journal logs..."
sudo journalctl --vacuum-size=500M

# Check disk space after cleanup
echo "Disk usage after log cleanup:"
df -h / | tail -1

echo "Log maintenance completed!"
logger -p user.info "Log maintenance cleanup completed"
