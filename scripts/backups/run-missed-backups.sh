#!/bin/bash
# Catch up on backups that were missed while the workstation was asleep or off.
#
# The regular schedule lives in cron. cron does not run missed jobs, so a 01:00
# database backup is simply lost if the machine is asleep then. The systemd
# timer that runs this script uses Persistent=true and fires after wake/boot.
# This script makes that firing cheap: it checks health first and only runs a
# full backup when something is actually stale.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HEALTH_CHECK="$SCRIPT_DIR/check-backup-health.sh"
BACKUP_ALL="$SCRIPT_DIR/backup-all.sh"

log() { echo "[backup-catchup] $*"; }

# A per-user runtime lock. XDG_RUNTIME_DIR is cleared at logout; /tmp is a
# fallback for environments where it is unset.
RUNTIME_DIR="${XDG_RUNTIME_DIR:-${TMPDIR:-/tmp}}"
mkdir -p "$RUNTIME_DIR"
exec 9>"$RUNTIME_DIR/spectre-suite-backup-catchup.lock"
if ! flock -n 9; then
    log "another catch-up run is already in progress; skipping"
    exit 0
fi

# The timer and cron can otherwise overlap. This is deliberately a best-effort
# check: cron does not take the lock above, so look for its processes directly.
if pgrep -f "$PROJECT_ROOT/scripts/backups/(backup-all|backup-databases|backup-docker-volumes|backup-configurations)[.]sh" >/dev/null 2>&1; then
    log "a scheduled backup is already running; skipping"
    exit 0
fi

# The health check is the decision point. It is cheap and reads only archives
# and markers, so a healthy system does no backup work at all.
if "$HEALTH_CHECK"; then
    log "backups are healthy; nothing to do"
    exit 0
fi

# A stale system may have just booted. Give Docker a short window to come up
# rather than failing the catch-up on a race with the daemon.
if ! command -v docker >/dev/null 2>&1; then
    log "docker is not installed; cannot run backups"
    exit 1
fi
for _ in $(seq 1 30); do
    if docker info >/dev/null 2>&1; then
        break
    fi
    sleep 2
done
if ! docker info >/dev/null 2>&1; then
    log "docker is not ready; cannot run backups"
    exit 1
fi

# Keep orchestration logs with the user's state rather than losing them in
# /tmp. backup-all.sh honours BACKUP_LOG when it is already set.
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/spectre-suite"
mkdir -p "$LOG_DIR"
export BACKUP_LOG="${BACKUP_LOG:-$LOG_DIR/backup.log}"

log "backups are stale; running full backup"
backup_status=0
"$BACKUP_ALL" || backup_status=$?

# A backup that ran is not the same as a backup that worked. Re-run the same
# structural check the alerting uses, and let systemd record a failure if the
# archives are still not usable.
health_status=0
"$HEALTH_CHECK" || health_status=$?

if [ "$backup_status" -ne 0 ] || [ "$health_status" -ne 0 ]; then
    log "catch-up backup did not restore health (backup=$backup_status health=$health_status)"
    exit 1
fi
log "catch-up backup completed and health check passes"
