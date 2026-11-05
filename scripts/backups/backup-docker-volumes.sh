#!/bin/bash
# Docker Volume Backup Script
#
# Backs up the named volumes belonging to this Compose project.
#
# The previous version carried a hardcoded list of volume names from an unrelated
# project (guardrail-ai_*, server-layer-*) plus a second pass that grepped
# `docker volume ls` for other projects' volumes (modelink, pharmaiq). Nothing in
# that list existed here, so the first pass backed up nothing, and the second
# pass would have copied *other projects'* data into this project's backup
# directory. A hardcoded list also drifts the moment a volume is renamed.
#
# Volumes are now discovered from the Compose project label, so the set tracks
# docker-compose.monitoring.yml automatically.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

COMPOSE_FILE="${COMPOSE_FILE:-$PROJECT_ROOT/docker-compose.monitoring.yml}"
# Compose derives the project name from the directory holding the file unless
# COMPOSE_PROJECT_NAME is set, so mirror that rather than hardcoding it.
COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "$(dirname "$COMPOSE_FILE")")}"
BACKUP_DIR="${BACKUP_DIR:-/backups/docker-volumes}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
DATE=$(date +%Y%m%d_%H%M%S)

# /backups needs root. Fall back to a writable location rather than failing, and
# say so loudly, because a silent fallback means the operator does not know where
# the backups actually are.
if ! mkdir -p "$BACKUP_DIR" 2>/dev/null || [ ! -w "$BACKUP_DIR" ]; then
    BACKUP_DIR="${TMPDIR:-/tmp}/docker-volumes"
    mkdir -p "$BACKUP_DIR"
    echo "WARNING: falling back to $BACKUP_DIR (set BACKUP_DIR to override)" >&2
fi

# Which volumes to back up. Default: everything Compose created for this project.
if [ -n "${VOLUMES:-}" ]; then
    # shellcheck disable=SC2206  # deliberate word splitting: VOLUMES is a list
    volume_list=($VOLUMES)
else
    mapfile -t volume_list < <(
        docker volume ls \
            --filter "label=com.docker.compose.project=$COMPOSE_PROJECT" \
            --format '{{.Name}}' | sort
    )
fi

echo "Backing up Docker volumes for project '$COMPOSE_PROJECT' to $BACKUP_DIR"

# An empty discovery must be an error. A backup run that quietly backs up nothing
# and exits 0 is indistinguishable from a successful one until the day it matters.
if [ "${#volume_list[@]}" -eq 0 ]; then
    echo "ERROR: no volumes found for project '$COMPOSE_PROJECT'." >&2
    echo "  Is the stack running? Check with:" >&2
    echo "    docker volume ls --filter label=com.docker.compose.project=$COMPOSE_PROJECT" >&2
    exit 1
fi

failures=0
for volume in "${volume_list[@]}"; do
    if ! docker volume inspect "$volume" >/dev/null 2>&1; then
        echo "ERROR: volume '$volume' does not exist, cannot back it up" >&2
        failures=$((failures + 1))
        continue
    fi

    archive="$BACKUP_DIR/${volume}_${DATE}.tar.gz"
    echo "  backing up $volume -> $(basename "$archive")"

    # No `|| true`: a tar failure must not be reported as a successful backup.
    # :z relabels for SELinux; without it the bind mount is unreadable under
    # rootless podman, which would fail the write rather than the read.
    if ! docker run --rm \
        -v "$volume":/volume_data:ro,z \
        -v "$BACKUP_DIR":/backup:z \
        alpine sh -c "tar czf /backup/$(basename "$archive") -C /volume_data ."; then
        echo "ERROR: tar failed for $volume" >&2
        rm -f "$archive"
        failures=$((failures + 1))
        continue
    fi

    # Verify the archive is readable and has content. A zero-length or truncated
    # file is the failure mode that survives to restore time otherwise.
    if [ ! -s "$archive" ]; then
        echo "ERROR: $archive is empty after tar" >&2
        failures=$((failures + 1))
    elif ! tar -tzf "$archive" >/dev/null 2>&1; then
        echo "ERROR: $archive is not a readable gzip archive" >&2
        failures=$((failures + 1))
    else
        echo "    verified $(du -h "$archive" | cut -f1), $(tar -tzf "$archive" | wc -l) entries"
    fi
done

echo "Cleaning up volume backups older than $RETENTION_DAYS days..."
find "$BACKUP_DIR" -maxdepth 1 -type f -name '*.tar.gz' -mtime +"$RETENTION_DAYS" -delete

if [ "$failures" -ne 0 ]; then
    echo "Docker volume backup FAILED: $failures volume(s) did not back up cleanly" >&2
    exit 1
fi

echo "Docker volume backup completed: $DATE (${#volume_list[@]} volume(s))"
logger -p user.info "Docker volume backup completed successfully ($DATE)" 2>/dev/null || true
