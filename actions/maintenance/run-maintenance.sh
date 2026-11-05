#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECTS_ROOT="${PROJECTS_ROOT:-$HOME/projects}"
# Main Maintenance Orchestration Script
# Runs all maintenance tasks and generates reports

MAINTENANCE_LOG="/var/log/maintenance.log"
DATE=$(date +%Y%m%d_%H%M%S)

echo "==========================================" >> "$MAINTENANCE_LOG"
echo "Starting System Maintenance: $DATE" >> "$MAINTENANCE_LOG"
echo "==========================================" >> "$MAINTENANCE_LOG"

# Make scripts executable
# shellcheck disable=SC2086  # intentional glob
chmod +x $SCRIPT_DIR/*.sh

# Run system cleanup
echo "Running system cleanup..." >> "$MAINTENANCE_LOG"
set +e
"$SCRIPT_DIR/cleanup-system.sh" >> "$MAINTENANCE_LOG" 2>&1
CLEANUP_STATUS=$?
set -e

# Run log cleanup
echo "Running log cleanup..." >> "$MAINTENANCE_LOG"
set +e
sudo "$SCRIPT_DIR/cleanup-logs.sh" 2>&1 | sudo tee -a "$MAINTENANCE_LOG" >/dev/null || true
LOG_STATUS=$?
set -e

# Run health check
echo "Running system health check..." >> "$MAINTENANCE_LOG"
set +e
"$SCRIPT_DIR/system-health-check.sh" >> "$MAINTENANCE_LOG" 2>&1
HEALTH_STATUS=$?
set -e

# Generate summary
echo "==========================================" >> "$MAINTENANCE_LOG"
echo "Maintenance Summary - $DATE" >> "$MAINTENANCE_LOG"
echo "System cleanup: $([ $CLEANUP_STATUS -eq 0 ] && echo 'SUCCESS' || echo 'FAILED')" >> "$MAINTENANCE_LOG"
echo "Log cleanup: $([ $LOG_STATUS -eq 0 ] && echo 'SUCCESS' || echo 'FAILED')" >> "$MAINTENANCE_LOG"
echo "Health check: $([ $HEALTH_STATUS -eq 0 ] && echo 'SUCCESS' || echo 'FAILED')" >> "$MAINTENANCE_LOG"
echo "Current disk usage:" >> "$MAINTENANCE_LOG"
df -h / >> "$MAINTENANCE_LOG"
echo "==========================================" >> "$MAINTENANCE_LOG"

# Send notification if any maintenance failed
if [ $CLEANUP_STATUS -ne 0 ] || [ $LOG_STATUS -ne 0 ] || [ $HEALTH_STATUS -ne 0 ]; then
    logger -p user.error "System maintenance completed with errors - check $MAINTENANCE_LOG"
    if [ -n "$DISPLAY" ]; then
        notify-send "Maintenance Error" "Some maintenance tasks failed - check logs" -u critical
    fi
else
    logger -p user.info "System maintenance completed successfully"
    if [ -n "$DISPLAY" ]; then
        notify-send "Maintenance Complete" "All maintenance tasks completed successfully"
    fi
fi

echo "System maintenance completed: $DATE"
