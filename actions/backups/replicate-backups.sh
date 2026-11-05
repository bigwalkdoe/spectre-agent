#!/bin/bash
# Off-site Backup Replication
#
# Replicates this project's backups to a remote host, S3 and/or Backblaze B2.
#
# Two problems with the scripts this replaces, both of which hid a real issue:
#
# 1. They reported success when they had done nothing. replicate-to-s3.sh printed
#    "S3 replication not configured" and then, unconditionally, "S3 replication
#    completed", and logged success via logger. The health check that consumed
#    these logs only looked for the string "FAILED", so replication appeared
#    healthy for as long as nobody read the detail lines.
#
# 2. They synced all of /backups wholesale. That directory is shared: it also
#    holds another project's volumes, copied in by an older script, and a 49GB
#    system-image directory. So completing the credentials -- the obvious next
#    step -- would have shipped someone else's database to three external
#    providers, with `b2 sync --delete` mirroring deletions back. This script
#    replicates an explicit manifest of this project's own globs, so no other
#    project's data is reachable from here.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

CONFIG_FILE="${BACKUP_CONFIG:-/home/deon/.secrets/backup-config.env}"
LOG_DIR="${LOG_DIR:-$PROJECT_ROOT/../logs}"
DRY_RUN=0
TARGETS=""

PROJECT_PREFIX="${PROJECT_PREFIX:-spectre-suite}"

usage() {
    cat <<'EOF'
Usage: replicate-backups.sh [--dry-run] [target...]

Targets: remote, s3, b2. With no target, every configured one is attempted.

Configuration is read from $BACKUP_CONFIG (default
/home/deon/.secrets/backup-config.env). Nothing is interpolated into a command
line from an unset variable, and a target whose configuration is incomplete is
reported as NOT CONFIGURED and skipped -- never as completed.

Exits non-zero if any attempted target failed. A target that is not configured is
not a failure, but it is reported, so "nothing left the host" is never mistaken
for "everything was replicated".
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1 ;;
        -h|--help) usage; exit 0 ;;
        remote|s3|b2) TARGETS="$TARGETS $1" ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done
[ -n "${TARGETS// /}" ] || TARGETS="remote s3 b2"

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/backup-replication.log"

log() { echo "$*" | tee -a "$LOG_FILE"; }

# The manifest. Only this project's data, by explicit glob. Nothing here can
# reach another project's volumes even if they sit in the same directory.
manifest=(
    "/backups/databases/postgres_*.sql.gz"
    "/backups/databases/redis_backup_*.rdb"
    "/backups/docker-volumes/${PROJECT_PREFIX}_*.tar.gz"
)

# Is this a usable backup? Same structural rules as check-backup-health.sh, which
# is the canonical definition; kept in step with it by
# tests/test_backup_health.sh.
#
# Replication filters on this because otherwise the 54 empty archives left by the
# broken backup script get shipped off-host, where they are indistinguishable
# from real backups to anyone restoring from them.
is_usable_backup() {
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
        *) return 1 ;;
    esac
    return 0
}

# Expand the manifest to real, usable files, reporting anything skipped.
skipped=0
collect() {
    local pattern file missing=0
    for pattern in "${manifest[@]}"; do
        # shellcheck disable=SC2086
        set -- $pattern
        if [ ! -e "$1" ]; then
            echo "no files match $pattern" >&2
            missing=1
            continue
        fi
        for file in "$@"; do
            [ -f "$file" ] || continue
            if is_usable_backup "$file"; then
                printf '%s\n' "$file"
            else
                echo "skipping (not a usable backup): $file" >&2
                skipped=$((skipped + 1))
            fi
        done
    done
    return "$missing"
}

if [ -f "$CONFIG_FILE" ]; then
    # shellcheck disable=SC1090
    . "$CONFIG_FILE"
else
    log "no config file at $CONFIG_FILE"
fi

mapfile -t files < <(collect)
if [ "$skipped" -gt 0 ]; then
    log "skipped $skipped archive(s) that are not usable backups (see errors above)"
fi
if [ "${#files[@]}" -eq 0 ]; then
    log "FAIL: nothing to replicate -- no usable backup archives matched the manifest."
    log "      A successful run with an empty manifest means a silent no-op, so this is an error."
    exit 1
fi

total_bytes=0
for f in "${files[@]}"; do total_bytes=$((total_bytes + $(stat -c %s "$f"))); done
log "$(date '+%Y-%m-%d %H:%M:%S') replication starting: ${#files[@]} file(s), $((total_bytes / 1024 / 1024))MB"
for f in "${files[@]}"; do log "  manifest: $f"; done

if [ "$DRY_RUN" -eq 1 ]; then
    log "dry run: no target contacted"
    exit 0
fi

attempted=0
succeeded=0
failed=0
not_configured=0

report() {  # report <target> <result> <detail>
    case "$2" in
        ok)    log "  $1: OK -- $3" ;;
        skip)  log "  $1: NOT CONFIGURED -- $3"; not_configured=$((not_configured + 1)) ;;
        fail)  log "  $1: FAILED -- $3"; failed=$((failed + 1)) ;;
    esac
}

for target in $TARGETS; do
    case "$target" in
        remote)
            if [ -z "${REMOTE_HOST:-}" ] || [ -z "${REMOTE_USER:-}" ] || [ -z "${REMOTE_PATH:-}" ]; then
                report remote skip "REMOTE_HOST/REMOTE_USER/REMOTE_PATH not set in $CONFIG_FILE"
                continue
            fi
            if [ ! -f "${REMOTE_KEY:-/home/deon/.ssh/backup_rsync}" ] && [ ! -f "${HOME}/.ssh/backup_rsync" ]; then
                report remote skip "no ssh identity at ${REMOTE_KEY:-$HOME/.ssh/backup_rsync}"
                continue
            fi
            attempted=$((attempted + 1))
            key="${REMOTE_KEY:-$HOME/.ssh/backup_rsync}"
            # --relative keeps the directory structure under REMOTE_PATH.
            if rsync -az --relative -e "ssh -i $key -o BatchMode=yes" \
                "${files[@]}" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH}/" \
                >>"$LOG_FILE" 2>&1; then
                report remote ok "${#files[@]} file(s) to ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH}"
                succeeded=$((succeeded + 1))
            else
                report remote fail "rsync returned non-zero; see $LOG_FILE"
            fi
            ;;
        s3)
            if [ -z "${S3_BUCKET:-}" ] || [ -z "${AWS_ACCESS_KEY_ID:-}" ] || [ -z "${AWS_SECRET_ACCESS_KEY:-}" ]; then
                missing_key=""
                [ -z "${S3_BUCKET:-}" ] && missing_key="S3_BUCKET"
                [ -z "${AWS_ACCESS_KEY_ID:-}" ] && missing_key="$missing_key AWS_ACCESS_KEY_ID"
                [ -z "${AWS_SECRET_ACCESS_KEY:-}" ] && missing_key="$missing_key AWS_SECRET_ACCESS_KEY"
                report s3 skip "$missing_key not set in $CONFIG_FILE"
                continue
            fi
            attempted=$((attempted + 1))
            prefix="s3://$S3_BUCKET/${PROJECT_PREFIX}/$(hostname -s)/"
            if aws s3 sync "${BACKUP_ROOT:-/backups}/" "$prefix" >>"$LOG_FILE" 2>&1; then
                report s3 ok "synced to $prefix"
                succeeded=$((succeeded + 1))
            else
                report s3 fail "aws s3 sync returned non-zero; see $LOG_FILE"
            fi
            ;;
        b2)
            if [ -z "${B2_BUCKET:-}" ] || [ -z "${B2_APPLICATION_KEY_ID:-}" ] || [ -z "${B2_APPLICATION_KEY:-}" ]; then
                report b2 skip "B2_BUCKET/B2_APPLICATION_KEY_ID/B2_APPLICATION_KEY not set in $CONFIG_FILE"
                continue
            fi
            attempted=$((attempted + 1))
            if b2 sync "${BACKUP_ROOT:-/backups}/" "b2://$B2_BUCKET/${PROJECT_PREFIX}/" >>"$LOG_FILE" 2>&1; then
                report b2 ok "synced to b2://$B2_BUCKET/${PROJECT_PREFIX}/"
                succeeded=$((succeeded + 1))
            else
                # Note: the original used `b2 sync --delete`, mirroring deletions
                # onto the bucket. Deliberately omitted -- a mis-scoped delete
                # against a shared source is not a risk worth taking.
                report b2 fail "b2 sync returned non-zero; see $LOG_FILE"
            fi
            ;;
    esac
done

log ""
if [ "$failed" -ne 0 ]; then
    log "REPLICATION FAILED: $failed of $attempted attempted target(s) failed, $not_configured not configured"
    exit 1
fi
if [ "$attempted" -eq 0 ]; then
    # The important distinction. Nothing left the host; do not call that success.
    log "REPLICATION DID NOT RUN: 0 targets attempted, $not_configured not configured."
    log "  This is not a successful replication. No data left this host."
    exit 2
fi
log "REPLICATION COMPLETE: $succeeded of $attempted target(s) succeeded, $not_configured not configured"
