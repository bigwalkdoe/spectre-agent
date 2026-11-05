#!/bin/bash
# Temporary directory cleanup
#
# Removes files older than TEMP_MAX_AGE_DAYS from the configured temporary
# directories. Ported from /home/deon/scripts/cleanup-temp.sh, which had no
# `set -euo pipefail`, logged to a hardcoded path outside this repository, and had
# no dry run -- so the only way to see what it would delete was to let it delete.
set -euo pipefail


TEMP_MAX_AGE_DAYS="${TEMP_MAX_AGE_DAYS:-7}"
LOG_FILE="${LOG_FILE:-${TMPDIR:-/tmp}/cleanup-temp.log}"
DRY_RUN=0
TEMP_DIRS=(
    "${HOME}/temp"
    "/tmp"
)

if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=1
fi

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

log "=== Temp Directory Cleanup - $(date) ==="

total_freed=0
for dir in "${TEMP_DIRS[@]}"; do
    if [ ! -d "$dir" ] || [ ! -w "$dir" ]; then
        log "skipping $dir (missing or not writable)"
        continue
    fi

    before=$(dir_bytes "$dir")
    before_h=$(dir_human "$dir")

    # Count before deleting, so a dry run can report honestly and a real run can
    # say what it removed rather than only what it freed.
    count=$(find "$dir" -type f -mtime "+$TEMP_MAX_AGE_DAYS" 2>/dev/null | wc -l || true)
    if [ "$count" -eq 0 ]; then
        log "$dir: nothing older than ${TEMP_MAX_AGE_DAYS}d"
        continue
    fi

    if [ "$DRY_RUN" -eq 1 ]; then
        log "$dir: would delete $count file(s) older than ${TEMP_MAX_AGE_DAYS}d (currently $before_h)"
        # Read the list into a variable rather than piping into head: head closes
        # the pipe, find dies of SIGPIPE, and `set -o pipefail` turns that into a
        # non-zero exit -- so the script aborted during its own dry run.
        sample=$(find "$dir" -type f -mtime "+$TEMP_MAX_AGE_DAYS" 2>/dev/null | sed -n '1,10p')
        printf '%s\n' "$sample" | while read -r f; do
            [ -n "$f" ] && log "    $f"
        done
        remaining=$((count > 10 ? count - 10 : 0))
        [ "$remaining" -gt 0 ] && log "    ... and $remaining more"
        continue
    fi

    log "$dir: deleting $count file(s) older than ${TEMP_MAX_AGE_DAYS}d"
    # 2>/dev/null because /tmp holds entries this user does not own; find reports
    # those as errors and they are not failures of this script.
    find "$dir" -type f -mtime "+$TEMP_MAX_AGE_DAYS" -delete 2>/dev/null || true
    find "$dir" -type d -mtime "+$TEMP_MAX_AGE_DAYS" -empty -delete 2>/dev/null || true

    after=$(dir_bytes "$dir")
    after_h=$(dir_human "$dir")
    freed=$((before - after))
    total_freed=$((total_freed + freed))
    log "$dir: $before_h -> $after_h (freed: $(numfmt --to=iec-i "$freed" 2>/dev/null || echo "${freed}B"))"
done

log "freed in total: $(numfmt --to=iec-i "$total_freed" 2>/dev/null || echo "${total_freed}B")"
[ "$DRY_RUN" -eq 1 ] && log "dry run: nothing was deleted"
log "=== completed $(date) ==="
