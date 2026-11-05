#!/bin/bash
# Downloads directory cleanup
#
# Removes files older than DOWNLOADS_MAX_AGE_DAYS from ~/Downloads. Ported from
# /home/deon/scripts/cleanup-downloads.sh, which had no `set -euo pipefail`, logged
# to a hardcoded path outside this repository, and had no dry run.
#
# This is the only script here that deletes something a person may care about:
# ~/Downloads holds installers, receipts and occasionally a document nobody else
# has. The default age is therefore long, the directory is overridable, and
# --dry-run is the first thing the usage message suggests.
set -euo pipefail

DOWNLOADS_DIR="${DOWNLOADS_DIR:-$HOME/Downloads}"
DOWNLOADS_MAX_AGE_DAYS="${DOWNLOADS_MAX_AGE_DAYS:-30}"
LOG_FILE="${LOG_FILE:-${TMPDIR:-/tmp}/cleanup-downloads.log}"
DRY_RUN=0

case "${1:-}" in
    --dry-run) DRY_RUN=1 ;;
    ""|--help|-h)
        cat <<EOF
Usage: $(basename "$0") [DAYS] [--dry-run]

  DAYS         delete files older than this many days (default $DOWNLOADS_MAX_AGE_DAYS)
  --dry-run    list what would be deleted, delete nothing

Directory: $DOWNLOADS_DIR
EOF
        [ "${1:-}" = "" ] && exit 0
        exit 0
        ;;
    *) DOWNLOADS_MAX_AGE_DAYS="$1" ;;
esac

mkdir -p "$(dirname "$LOG_FILE")"
log() { echo "$*" | tee -a "$LOG_FILE"; }

# du exits non-zero on a directory holding entries this user cannot read, even
# though it still prints a total. `|| echo 0` therefore appended a second line to
# the capture, and the arithmetic below operated on a two-line string. Take the
# first line, and treat anything non-numeric as zero.
dir_bytes() {
    local value
    value=$(du -sb "$1" 2>/dev/null | awk 'NR==1 {print $1}') || true
    case "$value" in
        ''|*[!0-9]*) printf '0' ;;
        *) printf '%s' "$value" ;;
    esac
}

dir_human() {
    local value
    value=$(du -sh "$1" 2>/dev/null | awk 'NR==1 {print $1}') || true
    printf '%s' "${value:-?}"
}

if [ ! -d "$DOWNLOADS_DIR" ]; then
    log "not present: $DOWNLOADS_DIR"
    exit 0
fi

log "=== Downloads Cleanup - $(date) ==="
log "directory: $DOWNLOADS_DIR, deleting files older than ${DOWNLOADS_MAX_AGE_DAYS}d"

before=$(dir_bytes "$DOWNLOADS_DIR")
before_h=$(dir_human "$DOWNLOADS_DIR")
candidates=$(find "$DOWNLOADS_DIR" -maxdepth 1 -type f -mtime "+$DOWNLOADS_MAX_AGE_DAYS" 2>/dev/null)
count=$(printf '%s' "$candidates" | grep -c . || true)

if [ "$count" -eq 0 ]; then
    log "nothing older than ${DOWNLOADS_MAX_AGE_DAYS}d; $before_h untouched"
    exit 0
fi

if [ "$DRY_RUN" -eq 1 ]; then
    log "would delete $count file(s):"
    printf '%s\n' "$candidates" | while read -r f; do
        [ -n "$f" ] && log "    $f"
    done
    log "dry run: nothing was deleted"
    exit 0
fi

deleted=0
printf '%s\n' "$candidates" | while read -r f; do
    [ -n "$f" ] || continue
    # -print before -delete so the log records exactly what went, rather than only
    # a byte count that cannot be traced back to a file.
    if find "$f" -maxdepth 0 -print -delete 2>/dev/null; then
        deleted=$((deleted + 1))
    fi
done

after=$(dir_bytes "$DOWNLOADS_DIR")
after_h=$(dir_human "$DOWNLOADS_DIR")
freed=$((before - after))
log "deleted $count file(s): $before_h -> $after_h (freed: $(numfmt --to=iec-i "$freed" 2>/dev/null || echo "${freed}B"))"
log "=== completed $(date) ==="
