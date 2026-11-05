#!/bin/bash
# Backup Health Check
#
# Verifies that backups exist, are non-empty, are readable archives, and are
# recent. Exits non-zero listing everything wrong.
#
# The check this replaces only grepped a replication log for the string "FAILED".
# That is not a health check. It passed continuously through 81 empty archives:
# the S3 replication script prints "replication completed" unconditionally after
# reporting missing credentials, so there was never a "FAILED" to find, and a
# log line cannot tell you whether a 45-byte file is a backup. This inspects the
# artifacts themselves.
set -uo pipefail   # deliberately not -e: we want to report every problem, not stop at the first

BACKUP_DIR="${BACKUP_DIR:-/backups/databases}"
VOLUME_BACKUP_DIR="${VOLUME_BACKUP_DIR:-/backups/docker-volumes}"
BACKUP_STATE_DIR="${BACKUP_STATE_DIR:-/backups/backup-state}"
# A backup older than this is stale. Matches the BackupStale alert's 24h threshold.
MAX_AGE_SECONDS="${MAX_AGE_SECONDS:-86400}"
# Only a floor for gzip-of-nothing (~20-30 bytes). Deliberately low: a valid
# PostgreSQL dump of a schema-only database is ~390 bytes and an empty Redis cache
# is ~170 bytes, so a size threshold set by intuition reports perfectly good
# backups as broken. Real emptiness is established structurally, by validate_archive.
MIN_ARCHIVE_BYTES="${MIN_ARCHIVE_BYTES:-32}"

# --purge-hollow deletes the archives this check has identified as carrying no
# data. It uses the same structural validation as the report, never a size
# threshold: a legitimate 396-byte dump and a 59-byte empty shell differ by their
# contents, not their length, and a size-based purge would take the real backup
# with it. Explicit flag because it is irreversible.
PURGE_HOLLOW=0
for arg in "$@"; do
    case "$arg" in
        --purge-hollow) PURGE_HOLLOW=1 ;;
        --dry-run) PURGE_HOLLOW=1; DRY_RUN=1 ;;
        -h|--help)
            cat <<EOF
Usage: $(basename "$0") [--purge-hollow] [--dry-run]

  --purge-hollow  Delete archives that are valid but carry no backup data.
  --dry-run       Report what --purge-hollow would delete, and delete nothing.
EOF
            exit 0
            ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done
DRY_RUN=${DRY_RUN:-0}

problems=0
problem() { echo "  FAIL: $*"; problems=$((problems + 1)); }
ok()      { echo "  ok:   $*"; }

now=$(date +%s)

# Is this file a real backup rather than a valid archive of nothing?
#
# `gzip -t` and `tar -tzf` both succeed on an archive of an empty directory, so
# "is it a valid archive" is not the question. The question is whether it has the
# structure of a backup of the thing it claims to be:
#   .sql.gz  -- a real pg_dump carries the "PostgreSQL database dump" header. A
#               failed dump is empty or an error string, and gzips to ~50 bytes.
#   .tar.gz  -- must list at least one member.
#   .rdb     -- must start with the REDIS magic. An empty cache is legitimately
#               tiny but is still a real RDB.
#
# Known limit: a tarball of an empty directory lists "." and therefore passes.
# For a volume backup, "valid archive with no data" is indistinguishable from a
# legitimately empty volume, and guessing a size threshold produces false
# failures on real small backups. Volume coverage is therefore established by the
# success marker and recency above, not by the contents of the tarball.
validate_archive() {
    local file="$1"
    case "$file" in
        *.tar.gz|*.tgz)
            tar -tzf "$file" >/dev/null 2>&1 || return 1
            [ -n "$(tar -tzf "$file" 2>/dev/null | head -1)" ] || return 1
            ;;
        *.sql.gz)
            gzip -t "$file" 2>/dev/null || return 1
            gzip -dc "$file" 2>/dev/null | head -20 | grep -q "PostgreSQL database dump" || return 1
            ;;
        *.rdb)
            head -c 5 "$file" 2>/dev/null | grep -q "REDIS" || return 1
            ;;
        *.gz)
            gzip -t "$file" 2>/dev/null || return 1
            ;;
    esac
    return 0
}

# check_archive <file> <kind>
check_archive() {
    local file="$1" kind="$2" size age

    if [ ! -f "$file" ]; then
        problem "$kind: missing ($file)"
        return
    fi
    size=$(stat -c %s "$file")
    if [ "$size" -lt "$MIN_ARCHIVE_BYTES" ]; then
        problem "$kind: $file is ${size}B, under the ${MIN_ARCHIVE_BYTES}B floor -- gzip of nothing, not a backup"
        return
    fi
    if ! validate_archive "$file"; then
        problem "$kind: $file is a valid archive but not a usable backup (wrong internal structure for its type)"
        return
    fi
    age=$((now - $(stat -c %Y "$file")))
    if [ "$age" -gt "$MAX_AGE_SECONDS" ]; then
        problem "$kind: $file is $((age / 3600))h old, over the $((MAX_AGE_SECONDS / 3600))h limit"
        return
    fi
    ok "$kind: $(basename "$file") ($((size / 1024))KB, $((age / 60))m old)"
}

echo "Backup health check"
echo "  database backups : $BACKUP_DIR"
echo "  volume backups   : $VOLUME_BACKUP_DIR"
echo "  markers          : $BACKUP_STATE_DIR"
echo "  max age          : $((MAX_AGE_SECONDS / 3600))h"
echo ""

# --- markers -----------------------------------------------------------------
# Checked before the archives: if the last successful run is recent there is no
# point reporting on individual files, and a fresh marker with broken archives
# means something wrote the marker without backing anything up.
if [ -f "$BACKUP_STATE_DIR/last-db-backup-success" ]; then
    marker=$(cat "$BACKUP_STATE_DIR/last-db-backup-success" 2>/dev/null || echo 0)
    case "$marker" in
        ''|*[!0-9]*) problem "success marker is not a timestamp: '$marker'" ;;
        *)
            marker_age=$((now - marker))
            if [ "$marker_age" -gt "$MAX_AGE_SECONDS" ]; then
                problem "last successful backup was $((marker_age / 3600))h ago"
            else
                ok "last successful backup $((marker_age / 60))m ago"
            fi
            ;;
    esac
else
    problem "no success marker at $BACKUP_STATE_DIR/last-db-backup-success -- no run has ever completed"
fi

# --- most recent archive of each kind ----------------------------------------
if [ -d "$BACKUP_DIR" ]; then
    for pattern_label in "postgres_*.sql.gz:PostgreSQL" "redis_backup_*.rdb:Redis"; do
        pattern="${pattern_label%%:*}"
        label="${pattern_label##*:}"
        newest=$(find "$BACKUP_DIR" -maxdepth 1 -name "$pattern" -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
        if [ -z "$newest" ]; then
            problem "$label: no archive matching $pattern in $BACKUP_DIR"
        else
            check_archive "$newest" "$label"
        fi
    done
else
    problem "database backup directory does not exist: $BACKUP_DIR"
fi

if [ -d "$VOLUME_BACKUP_DIR" ]; then
    # Scoped to this project's volumes on purpose. The directory also holds
    # archives of other projects' volumes, copied here by an older script, and
    # their presence is not evidence that this project is being backed up.
    pattern="spectre-suite_*.tar.gz"
    newest=$(find "$VOLUME_BACKUP_DIR" -maxdepth 1 -name "$pattern" -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
    if [ -z "$newest" ]; then
        problem "volumes: no archive matching $pattern in $VOLUME_BACKUP_DIR"
    else
        check_archive "$newest" "volumes"
    fi
else
    problem "volume backup directory does not exist: $VOLUME_BACKUP_DIR"
fi

# --- archives of ours that exist but carry nothing ---------------------------
# Scoped to this project's own name patterns, and validated structurally rather
# than by size. Two reasons: the volume directory also holds another project's
# archives, whose problems are not ours to report as ours; and a small file is
# not automatically a broken one.
#
# A directory full of hollow archives is worse than an empty directory, because
# it looks like coverage -- that is the state this check was written for, 81 of
# them at 45-59 bytes each.
hollow=0
checked=0
purged=0
for pattern_label in \
    "$BACKUP_DIR:postgres_*.sql.gz" \
    "$BACKUP_DIR:redis_backup_*.rdb" \
    "$VOLUME_BACKUP_DIR:spectre-suite_*.tar.gz"; do
    dir="${pattern_label%%:*}"
    pattern="${pattern_label##*:}"
    [ -d "$dir" ] || continue
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        checked=$((checked + 1))
        if [ "$(stat -c %s "$f")" -lt "$MIN_ARCHIVE_BYTES" ] || ! validate_archive "$f"; then
            # validate_archive has already proven this carries no backup data, so
            # removing it cannot destroy a backup that merely looks small -- which
            # a size-based purge would, since a legitimate schema-only dump is
            # 396 bytes and a hollow one is 59.
            if [ "$PURGE_HOLLOW" -eq 1 ]; then
                if [ "$DRY_RUN" -eq 1 ]; then
                    echo "  would purge $f ($(stat -c %s "$f")B, no backup data)"
                elif rm -f "$f"; then
                    echo "  purged $f"
                    purged=$((purged + 1))
                else
                    problem "could not remove hollow archive: $f"
                fi
                continue
            fi
            problem "hollow archive: $f ($(stat -c %s "$f")B, not a usable backup)"
            hollow=$((hollow + 1))
        fi
    done < <(find "$dir" -maxdepth 1 -name "$pattern" -type f 2>/dev/null)
done

# Record the verdict where the exporter can pick it up. A cron job that only
# exits non-zero is still a silent failure: nothing consumes the exit code, which
# is exactly how 81 empty archives went unnoticed. This is what lets
# BackupHealthCheckFailed alert on it.
mkdir -p "$BACKUP_STATE_DIR"
if [ "$PURGE_HOLLOW" -eq 1 ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "DRY RUN: nothing was deleted"
    else
        echo "  purged $purged hollow archive(s) of $checked checked"
    fi
    # Re-check, so the verdict reflects the state after a purge rather than the
    # census that motivated it.
    if "$0" >/dev/null 2>&1; then
        echo "ok $now" > "$BACKUP_STATE_DIR/last-backup-health"
        echo "BACKUP HEALTH: OK after purge"
        exit 0
    fi
    echo "failed $now purge-incomplete" > "$BACKUP_STATE_DIR/last-backup-health"
    echo "BACKUP HEALTH: still failing after purge"
    exit 1
fi
if [ "$problems" -ne 0 ]; then
    echo "failed $now $problems" > "$BACKUP_STATE_DIR/last-backup-health"
    echo "BACKUP HEALTH: FAILED ($problems problem(s), $hollow hollow of $checked archive(s) checked)"
    exit 1
fi
echo "ok $now" > "$BACKUP_STATE_DIR/last-backup-health"
echo "BACKUP HEALTH: OK ($checked archive(s) validated)"
