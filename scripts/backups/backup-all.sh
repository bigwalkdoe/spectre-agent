#!/bin/bash
set -euo pipefail

# Main Backup Orchestration Script
# Runs all backup scripts and generates a summary report

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -n "${BACKUP_LOG:-}" ]]; then
    :
elif [[ -w /var/log ]]; then
    BACKUP_LOG="/var/log/backup.log"
else
    BACKUP_LOG="${TMPDIR:-/tmp}/backup.log"
fi
DATE=$(date +%Y%m%d_%H%M%S)

{
    echo "=========================================="
    echo "Starting comprehensive backup: $DATE"
    echo "=========================================="
} >> "$BACKUP_LOG"

# Make scripts executable
chmod +x "$SCRIPT_DIR"/*.sh

run_step() {
    local name="$1"
    shift
    echo "Running $name..." >> "$BACKUP_LOG"
    set +e
    "$@" >> "$BACKUP_LOG" 2>&1
    local status=$?
    set -e
    echo "$name exit status: $status" >> "$BACKUP_LOG"
    return $status
}

DB_STATUS=0; VOL_STATUS=0; CONFIG_STATUS=0; PROJECT_STATUS=0

run_step "database backups" "$SCRIPT_DIR/backup-databases.sh" || DB_STATUS=$?
run_step "Docker volume backups" "$SCRIPT_DIR/backup-docker-volumes.sh" || VOL_STATUS=$?
run_step "configuration backups" "$SCRIPT_DIR/backup-configurations.sh" || CONFIG_STATUS=$?

# Run project backups (daily only)
DAY_OF_WEEK=$(date +%u)
if [ "$DAY_OF_WEEK" = "7" ]; then  # Sunday
    run_step "weekly project backups" "$SCRIPT_DIR/backup-projects.sh" || PROJECT_STATUS=$?
else
    echo "Skipping project backups (weekly only)" >> "$BACKUP_LOG"
    PROJECT_STATUS=0
fi

# Generate summary
{
    echo "=========================================="
    echo "Backup Summary - $DATE"
    echo "Database backups: $([ $DB_STATUS -eq 0 ] && echo 'SUCCESS' || echo 'FAILED')"
    echo "Volume backups: $([ $VOL_STATUS -eq 0 ] && echo 'SUCCESS' || echo 'FAILED')"
    echo "Configuration backups: $([ $CONFIG_STATUS -eq 0 ] && echo 'SUCCESS' || echo 'FAILED')"
    echo "Project backups: $([ $PROJECT_STATUS -eq 0 ] && echo 'SUCCESS' || echo 'FAILED')"
    echo "Total disk usage:"
    du -sh "${BACKUP_DIR:-/backups}" 2>/dev/null || true
    echo "=========================================="
} >> "$BACKUP_LOG"

# Send notification if any backup failed
if [ "$DB_STATUS" -ne 0 ] || [ "$VOL_STATUS" -ne 0 ] || [ "$CONFIG_STATUS" -ne 0 ] || [ "$PROJECT_STATUS" -ne 0 ]; then
    logger -p user.error "Backup completed with errors - check $BACKUP_LOG" 2>/dev/null || true
    if [ -n "${DISPLAY:-}" ]; then
        notify-send "Backup Error" "Some backups failed - check logs" -u critical
    fi
    echo "Backup orchestration completed with failures: $DATE"
    exit 1
fi

logger -p user.info "All backups completed successfully" 2>/dev/null || true
if [ -n "${DISPLAY:-}" ]; then
    notify-send "Backup Complete" "All backups completed successfully"
fi

echo "Backup orchestration completed: $DATE"
exit 0
