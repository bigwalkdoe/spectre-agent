#!/bin/bash
set -euo pipefail

# Projects Backup Script
# Backs up critical project directories

BACKUP_DIR="${BACKUP_DIR:-/backups/projects}"
PROJECTS_ROOT="${PROJECTS_ROOT:-$PROJECTS_ROOT}"
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=14

mkdir -p "$BACKUP_DIR"

echo "Backing up project directories..."

# Critical projects to backup
PROJECTS=(
    "$PROJECTS_ROOT/Guardrail-AI"
    "$PROJECTS_ROOT/Modelink"
)

for project in "${PROJECTS[@]}"; do
    project_name=$(basename "$project")
    echo "Backing up project: $project_name"

    # Exclude node_modules, .git, build artifacts, and any secret material
    # (.env files, secrets/ directories) so credentials never land in backups.
    tar czf "$BACKUP_DIR/${project_name}_$DATE.tar.gz" \
        --exclude='node_modules' \
        --exclude='.git' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='.venv' \
        --exclude='venv' \
        --exclude='dist' \
        --exclude='build' \
        --exclude='.next' \
        --exclude='.cache' \
        --exclude='.env' \
        --exclude='.env.*' \
        --exclude='secrets' \
        -C "$PROJECTS_ROOT" "$(basename "$project")"
done

# Backup scripts directory
echo "Backing up scripts directory..."
tar czf "$BACKUP_DIR/scripts_$DATE.tar.gz" -C "$PROJECTS_ROOT/.." scripts

# Cleanup old backups
echo "Cleaning up old project backups (older than $RETENTION_DAYS days)..."
find "$BACKUP_DIR" -type f -mtime +"$RETENTION_DAYS" -delete

echo "Project backup completed: $DATE"
logger -p user.info "Project backup completed successfully" 2>/dev/null || true
