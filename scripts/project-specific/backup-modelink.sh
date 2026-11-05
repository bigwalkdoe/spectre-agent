#!/bin/bash
set -euo pipefail
PROJECTS_ROOT="${PROJECTS_ROOT:-$HOME/projects}"
# Modelink Project Backup Script
# Custom backup configuration for Modelink project

BACKUP_DIR="/backups/projects/modelink"
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=14
PROJECT_DIR="$PROJECTS_ROOT/Modelink"

mkdir -p "$BACKUP_DIR"

echo "Starting Modelink project backup..."

# Backup project code (excluding unnecessary files)
echo "Backing up Modelink project code..."
tar czf "$BACKUP_DIR/modelink-code_$DATE.tar.gz" \
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
    -C "$HOME" "projects/Modelink"

# Backup Modelink Docker volumes if they exist
echo "Backing up Modelink Docker volumes..."
if docker volume inspect modelink_postgres_data >/dev/null 2>&1; then
    docker run --rm \
        -v modelink_postgres_data:/volume_data \
        -v "$BACKUP_DIR":/backup \
        alpine tar czf "/backup/modelink-postgres_$DATE.tar.gz" -C /volume_data . || true
fi

if docker volume inspect modelink_redis_data >/dev/null 2>&1; then
    docker run --rm \
        -v modelink_redis_data:/volume_data \
        -v "$BACKUP_DIR":/backup \
        alpine tar czf "/backup/modelink-redis_$DATE.tar.gz" -C /volume_data . || true
fi

# Backup configuration files
echo "Backing up Modelink configuration files..."
tar czf "$BACKUP_DIR/modelink-config_$DATE.tar.gz" \
    -C "$PROJECT_DIR" \
    docker-compose.yml \
    nginx.conf \
    k8s/ 2>/dev/null || true

# Cleanup old backups
echo "Cleaning up old Modelink backups..."
find "$BACKUP_DIR" -type f -mtime +$RETENTION_DAYS -delete

echo "Modelink project backup completed: $DATE"
logger -p user.info "Modelink project backup completed"
