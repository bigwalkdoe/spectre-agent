#!/bin/bash
# Cache directory cleanup
#
# Removes cache files older than CACHE_MAX_AGE_DAYS. Ported from
# /home/deon/scripts/cleanup-cache.sh, which had no `set -euo pipefail`, logged to
# a hardcoded path outside this repository, and had no dry run.
#
# The age is deliberately long. A cache is cheap to rebuild, but a package
# manager's cache is not always cheap to re-fetch, and none of these directories
# is a place where deleting something is unrecoverable.
set -euo pipefail

CACHE_MAX_AGE_DAYS="${CACHE_MAX_AGE_DAYS:-90}"
LOG_FILE="${LOG_FILE:-${TMPDIR:-/tmp}/cleanup-cache.log}"
DRY_RUN=0

if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=1
fi

CACHE_DIRS=(
    "$HOME/.cache"
    "$HOME/.npm/_cacache"
    "$HOME/.pyenv/cache"
    "$HOME/.config/Code/cache"
    "$HOME/.config/Code - Insiders/cache"
    "$HOME/.local/share/Trash/files"
)

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

log "=== Cache Cleanup - $(date) ==="

total_freed=0
for dir in "${CACHE_DIRS[@]}"; do
    if [ ! -d "$dir" ]; then
        log "skipping $dir (not present)"
        continue
    fi

    before=$(dir_bytes "$dir")
    before_h=$(dir_human "$dir")
    count=$(find "$dir" -type f -mtime "+$CACHE_MAX_AGE_DAYS" 2>/dev/null | wc -l || true)

    if [ "$count" -eq 0 ]; then
        log "$dir: nothing older than ${CACHE_MAX_AGE_DAYS}d"
        continue
    fi

    if [ "$DRY_RUN" -eq 1 ]; then
        log "$dir: would delete $count file(s) older than ${CACHE_MAX_AGE_DAYS}d (currently $before_h)"
        continue
    fi

    log "$dir: deleting $count file(s) older than ${CACHE_MAX_AGE_DAYS}d"
    find "$dir" -type f -mtime "+$CACHE_MAX_AGE_DAYS" -delete 2>/dev/null || true

    after=$(dir_bytes "$dir")
    after_h=$(dir_human "$dir")
    freed=$((before - after))
    total_freed=$((total_freed + freed))
    log "$dir: $before_h -> $after_h (freed: $(numfmt --to=iec-i "$freed" 2>/dev/null || echo "${freed}B"))"
done

log "total freed: $(numfmt --to=iec-i "$total_freed" 2>/dev/null || echo "${total_freed}B")"
[ "$DRY_RUN" -eq 1 ] && log "dry run: nothing was deleted"
log "=== completed $(date) ==="
