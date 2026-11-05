#!/bin/bash
# Install a per-user systemd timer that catches up backups missed during sleep.
#
# The timer is persistent: systemd fires it after boot or wake if the 05:00
# check was skipped. The wrapper it runs is a no-op when backups are healthy.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
USER_UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_NAME="spectre-backup-catchup.service"
TIMER_NAME="spectre-backup-catchup.timer"
WRAPPER="$PROJECT_ROOT/scripts/backups/run-missed-backups.sh"

usage() {
    cat <<EOF
Usage: $(basename "$0") [--print|--uninstall]

  --print      Print the generated units without installing them.
  --uninstall  Stop, disable, and remove the installed timer and service.
EOF
}

service_unit() {
    cat <<EOF
[Unit]
Description=Spectre Suite missed-backup catch-up
Documentation=file://$PROJECT_ROOT/README.md
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_ROOT
ExecStart=$WRAPPER
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
EOF
}

timer_unit() {
    cat <<EOF
[Unit]
Description=Spectre Suite daily missed-backup check
Documentation=file://$PROJECT_ROOT/README.md

[Timer]
OnCalendar=*-*-* 05:00:00
Persistent=true
RandomizedDelaySec=10m
Unit=$SERVICE_NAME

[Install]
WantedBy=timers.target
EOF
}

case "${1:-}" in
    --print)
        echo "# $SERVICE_NAME"
        service_unit
        echo
        echo "# $TIMER_NAME"
        timer_unit
        exit 0
        ;;
    --uninstall)
        if command -v systemctl >/dev/null 2>&1; then
            systemctl --user stop "$TIMER_NAME" 2>/dev/null || true
            systemctl --user disable "$TIMER_NAME" 2>/dev/null || true
        fi
        rm -f "$USER_UNIT_DIR/$TIMER_NAME" "$USER_UNIT_DIR/$SERVICE_NAME"
        if command -v systemctl >/dev/null 2>&1; then
            systemctl --user daemon-reload 2>/dev/null || true
        fi
        echo "Removed $TIMER_NAME and $SERVICE_NAME from $USER_UNIT_DIR"
        exit 0
        ;;
    -h|--help)
        usage
        exit 0
        ;;
    "")
        ;;
    *)
        echo "unknown argument: $1" >&2
        usage >&2
        exit 2
        ;;
esac

if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemctl is not available; cannot install a user timer" >&2
    exit 1
fi
if ! systemctl --user show-environment >/dev/null 2>&1; then
    echo "systemd user manager is not available; cannot install a user timer" >&2
    exit 1
fi
if [ ! -x "$WRAPPER" ]; then
    echo "catch-up wrapper is missing or not executable: $WRAPPER" >&2
    exit 1
fi

mkdir -p "$USER_UNIT_DIR"
service_unit > "$USER_UNIT_DIR/$SERVICE_NAME"
timer_unit > "$USER_UNIT_DIR/$TIMER_NAME"

systemctl --user daemon-reload
systemctl --user enable --now "$TIMER_NAME"

if command -v loginctl >/dev/null 2>&1; then
    linger=$(loginctl show-user "$USER" -p Linger --value 2>/dev/null || true)
    if [ "$linger" != "yes" ]; then
        echo "WARNING: user lingering is disabled for $USER." >&2
        echo "  The timer only runs while this user's systemd manager is active." >&2
        echo "  Enable it with: sudo loginctl enable-linger $USER" >&2
    fi
fi

echo "Installed $TIMER_NAME"
systemctl --user --no-pager list-timers "$TIMER_NAME" || true
