#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECTS_ROOT="${PROJECTS_ROOT:-$HOME/projects}"
# Main Security Orchestration Script

# This ran as deon from a system unit, so /var/log was unwritable and every
# write below failed silently under set -e only because they were part of a
# command substitution chain. Moved to XDG_STATE_HOME to match
# check-disk-space.sh, and still overridable for a root-run unit.
SECURITY_LOG="${SECURITY_HARDENING_LOG:-${XDG_STATE_HOME:-$HOME/.local/state}/security-hardening.log}"
mkdir -p "$(dirname "$SECURITY_LOG")" 2>/dev/null || true
DATE=$(date +%Y%m%d_%H%M%S)

echo "==========================================" >> "$SECURITY_LOG"
echo "Security Hardening - $DATE" >> "$SECURITY_LOG"
echo "==========================================" >> "$SECURITY_LOG"

# Make scripts executable
# shellcheck disable=SC2086  # intentional glob
chmod +x $SCRIPT_DIR/*.sh

# Run dependency vulnerability scanning
echo "Running dependency vulnerability scanning..." >> "$SECURITY_LOG"
set +e
"$SCRIPT_DIR/scan-dependencies.sh" >> "$SECURITY_LOG" 2>&1
DEP_STATUS=$?
set -e

# Run Docker security hardening
echo "Running Docker security hardening..." >> "$SECURITY_LOG"
set +e
sudo "$SCRIPT_DIR/docker-security-hardening.sh" 2>&1 | sudo tee -a "$SECURITY_LOG" >/dev/null || true
DOCKER_STATUS=$?
set -e

# Run API security hardening
echo "Running API security hardening..." >> "$SECURITY_LOG"
set +e
"$SCRIPT_DIR/api-security-hardening.sh" >> "$SECURITY_LOG" 2>&1
API_STATUS=$?
set -e

# Run API security monitoring
echo "Running API security monitoring..." >> "$SECURITY_LOG"
set +e
"$SCRIPT_DIR/monitor-api-security.sh" >> "$SECURITY_LOG" 2>&1
MONITOR_STATUS=$?
set -e

# Generate summary
echo "==========================================" >> "$SECURITY_LOG"
echo "Security Hardening Summary - $DATE" >> "$SECURITY_LOG"
echo "Dependency scanning: $([ $DEP_STATUS -eq 0 ] && echo 'SUCCESS' || echo 'FAILED')" >> "$SECURITY_LOG"
echo "Docker security: $([ $DOCKER_STATUS -eq 0 ] && echo 'SUCCESS' || echo 'FAILED')" >> "$SECURITY_LOG"
echo "API security: $([ $API_STATUS -eq 0 ] && echo 'SUCCESS' || echo 'FAILED')" >> "$SECURITY_LOG"
echo "API monitoring: $([ $MONITOR_STATUS -eq 0 ] && echo 'SUCCESS' || echo 'FAILED')" >> "$SECURITY_LOG"
echo "==========================================" >> "$SECURITY_LOG"

# Send notification if any security hardening failed
if [ $DEP_STATUS -ne 0 ] || [ $DOCKER_STATUS -ne 0 ] || [ $API_STATUS -ne 0 ] || [ $MONITOR_STATUS -ne 0 ]; then
    logger -p user.error "Security hardening completed with errors - check $SECURITY_LOG"
    # ${DISPLAY:-} rather than "$DISPLAY": a systemd unit has no session
    # environment, so under `set -u` a bare reference aborts the whole run. The
    # check itself is right -- these notifications are desktop-only and this job
    # is headless -- it just has to tolerate the variable being absent. Every
    # real signal goes to `logger` on the line above, so nothing is lost.
    if [ -n "${DISPLAY:-}" ] && command -v notify-send >/dev/null 2>&1; then
        notify-send "Security Hardening Error" "Some security tasks failed - check logs" -u critical || true
    fi
else
    logger -p user.info "Security hardening completed successfully"
    if [ -n "${DISPLAY:-}" ] && command -v notify-send >/dev/null 2>&1; then
        notify-send "Security Hardening Complete" "All security tasks completed successfully" || true
    fi
fi

echo "Security hardening orchestration completed: $DATE"
