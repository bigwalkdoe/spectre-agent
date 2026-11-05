#!/usr/bin/env bash
# Host-side installation for the spectre consolidation.
#
# Run as root:  sudo ./actions/install-host.sh
#
# What it does:
#   1. Repairs the spectre venv interpreter symlink (python3.14 -> python3).
#   2. Installs a `spectre` launcher into /usr/local/bin.
#   3. Disables the dead fedora-optimize timer/service (source gone; it was
#      silently skipping via ConditionPathExists).
#   4. Replaces the tracked maintenance .sh copies in /usr/local/bin with
#      transitional forwarder shims, so schedulers start recording provenance.
#      Non-script binaries (aws, k6, ...) are left untouched.
#   5. Does NOT delete anything else; pruning is left to the operator.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "error: must run as root (sudo $0)" >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO_ROOT/.venv"
PYTHON="$VENV/bin/python"

echo "==> repairing venv interpreter"
if [ -L "$VENV/bin/python3.14" ] && [ ! -e "$VENV/bin/python3.14" ]; then
    ln -sf "$VENV/bin/python3" "$VENV/bin/python3.14"
fi
"$PYTHON" --version

echo "==> installing spectre launcher"
# Install the package into the venv (editable) so the `spectre` entry point exists.
# pip is not shipped in this venv; fall back to uv (full path, since root's PATH
# may not include ~/.local/bin).
UV="${UV:-/home/deon/.local/bin/uv}"
if ! "$PYTHON" -c "import spectre" 2>/dev/null; then
    if [ -x "$UV" ]; then
        "$UV" pip install -e "$REPO_ROOT" --python "$PYTHON"
    else
        echo "error: neither pip nor uv available to install spectre" >&2
        exit 1
    fi
fi
cat > /usr/local/bin/spectre <<LAUNCHER
#!/bin/sh
exec "$REPO_ROOT/.venv/bin/spectre" "\$@"
LAUNCHER
chmod 0755 /usr/local/bin/spectre

echo "==> disabling dead fedora-optimize timer/service"
systemctl disable --now fedora-optimize.timer 2>/dev/null || true
systemctl disable --now fedora-optimize.service 2>/dev/null || true

echo "==> installing forwarder shims for tracked maintenance scripts"
# Only replace files that are one of the repo's registered actions.
"$PYTHON" - "$REPO_ROOT" <<'PY'
import json, os, sys
root = sys.argv[1]
data = json.load(open(os.path.join(root, "spectre/dispatch/registry_data.json")))
names = {j["name"] for j in data}
bin_dir = "/usr/local/bin"
for name in sorted(names):
    # registered jobs use slash namespaces (backups/backup-all); the legacy
    # /usr/local/bin layout is flat, so only the leaf basename is a candidate
    leaf = name.split("/")[-1]
    for candidate in (leaf, leaf + ".sh", name.replace("/", "-")):
        path = os.path.join(bin_dir, candidate)
        if os.path.exists(path) and not os.path.islink(path):
            # overwrite the tracked copy with a forwarder
            with open(path, "w") as f:
                f.write("#!/usr/bin/env bash\n")
                f.write("# transitional forwarder\n")
                f.write(f'exec spectre run {name} "$@"\n')
            os.chmod(path, 0o755)
            print(f"  shimmed {path} -> spectre run {name}")
PY

# ~/.local/bin/spectre has a stale shebang pointing at a missing python3.14;
# remove it so /usr/local/bin/spectre wins on PATH.
if [ -e /home/deon/.local/bin/spectre ]; then
    rm -f /home/deon/.local/bin/spectre
fi

echo "==> done. Run 'spectre actions verify' to confirm."
