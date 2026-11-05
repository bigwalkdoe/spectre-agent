#!/bin/bash
# Label repository scripts that a *system* systemd unit executes.
#
# Why this exists
# ---------------
# This repository lives in the user's home directory. Both user-level and
# system-level timers execute scripts from it. Those two cases are not
# equivalent under SELinux, and the difference is invisible until a unit fails:
#
#   * ~/.config/systemd/user/*.service runs as deon in the unconfined_u domain,
#     which is permitted to execute user_home_t. These have always worked.
#
#   * /etc/systemd/system/*.service is exec'd by PID 1 in system_u/init_t before
#     the uid switch to deon. That domain is not permitted to execute
#     user_home_t, so the unit fails at 203/EXEC with "Unable to locate
#     executable ... Permission denied" -- even though the file is rwxr-xr-x,
#     owned by deon, and every parent directory is traversable.
#
# disk-space-check and security-scan both failed this way on every scheduled run.
# disk-space-check had been failing since at least the previous day and
# security-scan had never succeeded once, so a weekly security scan was
# reporting nothing at all.
#
# Only scripts referenced by an installed /etc/systemd/system/*.service
# ExecStart are labelled. Labelling every *.sh in the repository used to fight
# Docker: compose mounts ./prometheus with :z, which relabels that directory
# container_file_t, and the checker then failed even though the only scheduled
# consumers of those exporter scripts are user-level cron jobs. Narrowing the
# set makes the check describe what PID 1 actually needs to execute.
#
# Why `restorecon -R` is not enough
# ---------------------------------
# No SELinux fcontext rule covers a checkout under $HOME, so there is no policy
# default for restorecon to apply and it silently changes nothing. The label has
# to be set explicitly, and it has to be `shell_exec_t`: a type the system
# domain is allowed to execute. `user_home_t` is correct for data and wrong for
# code.
#
# The user's own `.local/bin` and home files are untouched -- this only touches
# repository scripts referenced by system units.
#
# Usage:  sudo ./scripts/systemd/label-exec-context.sh [--check]
#         --check reports the current labels and exits non-zero if any
#         system-unit script is not executable by the system domain. Safe to
#         run unprivileged.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXEC_TYPE="shell_exec_t"
CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

# Discover only scripts an installed system unit actually execs. User units do
# not need this label, and labelling every *.sh would relabel scripts that
# Docker mounts with :z (and are never run by PID 1).
mapfile -t targets < <(
    for unit in /etc/systemd/system/*.service; do
        [ -r "$unit" ] || continue
        while IFS= read -r line; do
            path=${line#ExecStart=}
            path=${path%% *}
            case "$path" in
                "$REPO_ROOT"/*.sh)
                    [ -f "$path" ] && printf '%s\n' "$path"
                    ;;
            esac
        done < <(grep -E '^ExecStart=' "$unit" 2>/dev/null || true)
    done | sort -u
)

if [ "${#targets[@]}" -eq 0 ]; then
    echo "No repository shell scripts are referenced by installed system units."
    exit 0
fi

# The directories only need to be traversable, which user_home_t already
# permits. Labelling directories was the mistake that produced a half-applied
# state, so they are left alone.
if [ "$CHECK_ONLY" -eq 0 ]; then
    if ! command -v semanage >/dev/null 2>&1; then
        echo "ERROR: semanage not found. Install policycoreutils-python-utils." >&2
        exit 1
    fi
    echo "Applying SELinux fcontext rule: $REPO_ROOT/**/*.sh -> $EXEC_TYPE"
    semanage fcontext -a -t "$EXEC_TYPE" "$REPO_ROOT(/.*)?\.sh" 2>/dev/null \
        || semanage fcontext -m -t "$EXEC_TYPE" "$REPO_ROOT(/.*)?\.sh"
    restorecon -RFv "${targets[@]}" >/dev/null
    echo "Applied to ${#targets[@]} system-unit script(s)."
else
    echo "Checking exec labels for system-unit scripts under $REPO_ROOT ..."
fi

# Report the SELinux user component too. `chcon -t` rewrites only the type and
# leaves the user as whatever it was, which is how directories ended up
# system_u while their files were unconfined_u -- a mixed state that looks fixed
# if you only read the type column.
bad=0
declare -A user_seen=()
for t in "${targets[@]}"; do
    label=$(ls -Zd "$t" 2>/dev/null | awk '{print $1}')
    [ -n "$label" ] || continue
    type=$(printf '%s' "$label" | cut -d: -f3)
    selinux_user=$(printf '%s' "$label" | cut -d: -f1)
    user_seen["$selinux_user"]=1
    if [ "$type" != "$EXEC_TYPE" ]; then
        echo "  NOT EXECUTABLE BY SYSTEM DOMAIN: $t"
        echo "      label: $label (expected type $EXEC_TYPE)"
        bad=1
    fi
done

echo
echo "SELinux users seen across system-unit scripts: ${!user_seen[*]}"

if [ "$bad" -ne 0 ]; then
    echo
    echo "RESULT: at least one script is not executable by a system systemd unit."
    echo "Fix:    sudo $0"
    exit 1
fi

echo "RESULT: all ${#targets[@]} system-unit script(s) labelled $EXEC_TYPE."
echo "System units will now exec them. Verify with:"
echo "  systemctl start disk-space-check.service security-scan.service"