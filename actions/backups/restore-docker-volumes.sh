#!/bin/bash
# Docker Volume Restore Script
#
# Restores named volumes from archives written by backup-docker-volumes.sh.
#
# The previous version could not have worked. It searched for
# guardrail-ai_*_data_*.tar.gz archives that nothing produces, and then located
# volumes inside the archive with `find -maxdepth 1 -type d -name "*/data"` --
# a pattern that is two levels deep and can never match at maxdepth 1, so the
# restore loop never ran and the script reported success having restored nothing.
# Even if it had matched, it untarred into a temporary host directory and started
# a throwaway `alpine sleep infinity` container, never writing to the real named
# volume.
#
# Archives are <volume>_<YYYYmmdd_HHMMSS>.tar.gz with the volume's contents at the
# archive root. This script derives the target volume from the archive name,
# stops the Compose services using that volume, writes into the real volume, and
# verifies the result.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

COMPOSE_FILE="${COMPOSE_FILE:-$PROJECT_ROOT/docker-compose.monitoring.yml}"
# Needed to map a real volume name back to the name Compose declares it under.
COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "$(dirname "$COMPOSE_FILE")")}"
BACKUP_DIR="${BACKUP_DIR:-/backups/docker-volumes}"
LOG_FILE="${LOG_FILE:-/var/log/docker-volume-restore.log}"

# Same fallback as the backup script: /var/log and /backups need root.
if ! mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || ! touch "$LOG_FILE" 2>/dev/null; then
    LOG_FILE="${TMPDIR:-/tmp}/docker-volume-restore.log"
    touch "$LOG_FILE"
fi

log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }
error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" | tee -a "$LOG_FILE" >&2; }

usage() {
    cat <<'EOF'
Usage: restore-docker-volumes.sh <command> [args]

  list                     Show available archives, newest first
  verify <archive>         Check an archive is a readable gzip tarball
  latest [volume]          Restore the newest archive (optionally for one volume)
  restore <volume> [archive]
                           Restore a specific volume, by default its newest archive

Archive names are <volume>_<YYYYmmdd_HHMMSS>.tar.gz and hold the volume's
contents at the archive root.
EOF
}

# Newest archive per volume. Prints "<volume> <path>".
#
# The volume name is everything before the _YYYYmmdd_HHMMSS stamp, which is two
# underscore-separated fields. Stripping only the last field (${base%_*}) left
# the date attached, so every lookup missed and `restore <volume>` reported "no
# archive" for volumes that plainly existed.
archives_by_volume() {
    find "$BACKUP_DIR" -maxdepth 1 -type f -name '*.tar.gz' -printf '%T@ %p\n' 2>/dev/null \
        | sort -rn \
        | while read -r _ path; do
            base=$(basename "$path" .tar.gz)
            volume=$(printf '%s' "$base" | sed -E 's/_[0-9]{8}_[0-9]{6}$//')
            printf '%s\t%s\n' "$volume" "$path"
        done | awk -F'\t' '!seen[$1]++'
}

verify_archive() {
    local archive="$1"
    if [ ! -f "$archive" ]; then
        error "archive not found: $archive"
        return 1
    fi
    if ! tar -tzf "$archive" >/dev/null 2>&1; then
        error "archive is corrupt or not gzip: $archive"
        return 1
    fi
    log "verified $archive ($(tar -tzf "$archive" | wc -l) entries)"
}

# Which Compose services mount this volume, so only those get stopped.
#
# `compose config` reports a named volume by its *declared* name ("postgres-data")
# while the real Docker volume carries the project prefix
# ("spectre-suite_postgres-data"). Comparing the two directly
# silently matched nothing, which meant a restore would clear and rewrite a live
# database directory without stopping the database first.
services_using_volume() {
    local volume="$1"
    docker compose -f "$COMPOSE_FILE" config --format json 2>/dev/null \
        | python3 -c "
import json, sys
cfg = json.load(sys.stdin)
target = sys.argv[1]
prefix = sys.argv[2] + '_'
# Accept either spelling so this works for a prefixed or bare volume name.
declared = {target, target[len(prefix):] if target.startswith(prefix) else target}
for name, svc in (cfg.get('services') or {}).items():
    for mount in svc.get('volumes') or []:
        src = mount.get('source') if isinstance(mount, dict) else str(mount).split(':')[0]
        if src and src.split('/')[-1] in declared:
            print(name)
            break
" "$volume" "$COMPOSE_PROJECT" 2>/dev/null || true
}

# Write the archive into the real named volume. The volume must already be
# populated-by-restore, not wrapped in a temporary container: an alpine container
# mounting a host temp directory shares no storage with the named volume.
restore_one_volume() {
    local volume="$1" archive="$2"

    verify_archive "$archive" || return 1

    if ! docker volume inspect "$volume" >/dev/null 2>&1; then
        log "volume '$volume' does not exist; creating it"
        docker volume create "$volume" >/dev/null
    fi

    local services
    mapfile -t services < <(services_using_volume "$volume")
    if [ "${#services[@]}" -gt 0 ]; then
        log "stopping services using $volume: ${services[*]}"
        docker compose -f "$COMPOSE_FILE" stop "${services[@]}" >/dev/null
    fi

    # Extracting into a live volume without clearing it merges old and new files.
    # Clear first so the restore is exact rather than a union of two states.
    log "clearing $volume before restore"
    docker run --rm -v "$volume":/volume_data:z --entrypoint sh alpine -c 'rm -rf /volume_data/* /volume_data/..?* /volume_data/.[!.]* 2>/dev/null || true'

    log "restoring $volume from $(basename "$archive")"
    if ! docker run --rm \
        -v "$volume":/volume_data:z \
        -v "$(dirname "$archive")":/backup:ro,z \
        alpine sh -c "tar xzf /backup/$(basename "$archive") -C /volume_data"; then
        error "extract failed for $volume"
        [ "${#services[@]}" -gt 0 ] && docker compose -f "$COMPOSE_FILE" up -d "${services[@]}" >/dev/null
        return 1
    fi

    local entries
    entries=$(docker run --rm -v "$volume":/volume_data:ro,z --entrypoint sh alpine \
        -c 'find /volume_data -mindepth 1 | wc -l')
    log "restored $volume: $entries entries present"

    if [ "${#services[@]}" -gt 0 ]; then
        log "restarting ${services[*]}"
        docker compose -f "$COMPOSE_FILE" up -d "${services[@]}" >/dev/null
    fi
}

main() {
    local cmd="${1:-}"
    case "$cmd" in
        list)
            local found=0
            while IFS=$'\t' read -r volume path; do
                [ -n "$volume" ] || continue
                echo "  $(basename "$path")  ->  $volume"
                found=1
            done < <(archives_by_volume)
            [ "$found" -eq 1 ] || { echo "no archives in $BACKUP_DIR" >&2; exit 1; }
            ;;
        verify)
            [ -n "${2:-}" ] || { error "verify needs an archive"; usage >&2; exit 2; }
            verify_archive "$2"
            ;;
        latest)
            if [ -n "${2:-}" ]; then
                local path
                path=$(archives_by_volume | awk -F'\t' -v v="$2" '$1==v{print $2; exit}')
                [ -n "$path" ] || { error "no archive for volume '$2' in $BACKUP_DIR"; exit 1; }
                restore_one_volume "$2" "$path"
            else
                local any=0 volume path
                while IFS=$'\t' read -r volume path; do
                    [ -n "$volume" ] || continue
                    restore_one_volume "$volume" "$path"
                    any=1
                done < <(archives_by_volume)
                [ "$any" -eq 1 ] || { error "no archives in $BACKUP_DIR"; exit 1; }
            fi
            ;;
        restore)
            local volume="${2:-}" archive="${3:-}"
            [ -n "$volume" ] || { error "restore needs a volume name"; usage >&2; exit 2; }
            if [ -z "$archive" ]; then
                archive=$(archives_by_volume | awk -F'\t' -v v="$volume" '$1==v{print $2; exit}')
                [ -n "$archive" ] || { error "no archive for volume '$volume' in $BACKUP_DIR"; exit 1; }
            fi
            restore_one_volume "$volume" "$archive"
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
    log "docker volume restore finished"
}

main "$@"
