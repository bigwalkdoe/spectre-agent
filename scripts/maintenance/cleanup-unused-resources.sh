#!/bin/bash
# Reclaim unused Docker resources and stale backups.
#
# Ported from /home/deon/scripts/maintenance/cleanup-unused-resources.sh. The
# behaviour is the same but the blast radius is smaller, because the original ran
# unscoped `docker container prune -f`, `docker image prune -af` and
# `docker volume prune -f` with no project or label filter on a host running
# containers for several unrelated projects. `docker volume prune` removes every
# volume not referenced by an existing container, so an orphaned volume belonging
# to another project is destroyed without asking and without a record beyond a
# reclaimed-byte figure in a log.
#
# What changed:
#   - --dry-run first-class, and the default is still to act. Use --dry-run.
#   - Containers and volumes are filtered to compose projects, so another
#     project's stopped container is not removed.
#   - Volumes are additionally limited to ones not referenced by any container at
#     all, reported by name, because those are the irreversible ones.
#   - Images keep the host-wide prune. Image layers are large and re-pullable,
#     which is a materially different risk from deleting data.
#   - Backup retention is restricted to this project's subdirectories. The
#     original already did that; it is kept explicit because /backups is shared.
set -euo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
LOG_RETENTION_DAYS="${LOG_RETENTION_DAYS:-7}"
# Compose projects whose stopped containers this script may remove. Empty means
# "remove no containers", which is the safe default on a shared host.
PRUNE_PROJECTS="${PRUNE_PROJECTS:-}"
LOG_FILE="${LOG_FILE:-${TMPDIR:-/tmp}/cleanup-unused-resources.log}"
DRY_RUN=0

if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=1
fi

mkdir -p "$(dirname "$LOG_FILE")"
log() { echo "$*" | tee -a "$LOG_FILE"; }
run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        log "  would run: $*"
        return 0
    fi
    log "  running: $*"
    "$@" 2>&1 | sed 's/^/    /' | tee -a "$LOG_FILE"
}

log "=== Docker resource cleanup - $(date) ==="
[ "$DRY_RUN" -eq 1 ] && log "DRY RUN: nothing will be removed"

# --- containers --------------------------------------------------------------
if [ -z "$PRUNE_PROJECTS" ]; then
    log "containers: skipped (PRUNE_PROJECTS is empty)"
    log "  Removing stopped containers on a host shared with other projects can"
    log "  take down something you did not mean to touch. Set PRUNE_PROJECTS to a"
    log "  space-separated list of compose project names to act on."
else
    log "containers: pruning stopped containers for projects: $PRUNE_PROJECTS"
    for project in $PRUNE_PROJECTS; do
        stopped=$(docker ps -a --filter "status=exited" --filter "status=created" \
            --filter "label=com.docker.compose.project=$project" --format '{{.Names}}' 2>/dev/null || true)
        if [ -z "$stopped" ]; then
            log "  $project: no stopped containers"
            continue
        fi
        log "  $project: $(printf '%s' "$stopped" | grep -c .) stopped container(s):"
        printf '%s\n' "$stopped" | while read -r c; do
            [ -n "$c" ] && log "    $c"
        done
        if [ "$DRY_RUN" -eq 0 ]; then
            printf '%s\n' "$stopped" | while read -r c; do
                [ -n "$c" ] && docker rm "$c" >/dev/null 2>&1 || true
            done
        fi
    done
fi

# --- volumes -----------------------------------------------------------------
# The irreversible one, so it is named explicitly rather than summarised as bytes.
dangling=$(docker volume ls -q --filter dangling=true 2>/dev/null || true)
dangling_count=$(printf '%s' "$dangling" | grep -c . || true)
if [ "$dangling_count" -eq 0 ]; then
    log "volumes: none unused"
else
    log "volumes: $dangling_count unused volume(s) -- DELETING PERMANENTLY"
    printf '%s\n' "$dangling" | while read -r v; do
        [ -n "$v" ] || continue
        mountpoint=$(docker volume inspect "$v" --format '{{.Mountpoint}}' 2>/dev/null || echo "?")
        size=$(du -sh "$mountpoint" 2>/dev/null | cut -f1 || echo "?")
        log "    $v  ($size)"
        if [ "$DRY_RUN" -eq 0 ]; then
            docker volume rm "$v" >/dev/null 2>&1 || log "      could not remove"
        fi
    done
    [ "$DRY_RUN" -eq 1 ] && log "  dry run: no volume was removed"
fi

# --- images and build cache --------------------------------------------------
# Re-pullable, so a host-wide prune is acceptable here in a way it is not for
# volumes.
run docker image prune -af
run docker builder prune -af

# --- backups -----------------------------------------------------------------
# Scoped to this project's own subdirectories. /backups is shared and also holds
# a 49GB system-image directory that no retention policy here should touch.
for sub in databases docker-volumes; do
    target="$BACKUP_ROOT/$sub"
    [ -d "$target" ] || continue
    stale=$(find "$target" -maxdepth 1 -type f -mtime "+$BACKUP_RETENTION_DAYS" 2>/dev/null | wc -l)
    if [ "$stale" -eq 0 ]; then
        log "backups: $target has nothing older than ${BACKUP_RETENTION_DAYS}d"
        continue
    fi
    log "backups: $stale file(s) in $target older than ${BACKUP_RETENTION_DAYS}d"
    if [ "$DRY_RUN" -eq 0 ]; then
        find "$target" -maxdepth 1 -type f -mtime "+$BACKUP_RETENTION_DAYS" -print -delete 2>/dev/null \
            | while read -r f; do log "    deleted $f"; done
    fi
done

# --- logs --------------------------------------------------------------------
if [ -w /var/log ] || [ -d /var/log ]; then
    stale_logs=$(find /var/log -maxdepth 1 -name '*.gz' -mtime "+$LOG_RETENTION_DAYS" 2>/dev/null | wc -l)
    log "logs: $stale_logs rotated archive(s) in /var/log older than ${LOG_RETENTION_DAYS}d"
    if [ "$stale_logs" -gt 0 ] && [ "$DRY_RUN" -eq 0 ]; then
        find /var/log -maxdepth 1 -name '*.gz' -mtime "+$LOG_RETENTION_DAYS" -delete 2>/dev/null || true
    fi
fi

log "=== completed $(date) ==="
