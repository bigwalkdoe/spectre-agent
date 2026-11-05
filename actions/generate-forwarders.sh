#!/usr/bin/env bash
# Generate transitional forwarder shims for every registered job.
#
# Usage: ./actions/generate-forwarders.sh <target-dir>
#
# Writes a 3-line forwarder at <target-dir>/<job-name> (flattening the
# slash namespace to a hyphenated basename is NOT done — the job name keeps
# its slash, so the target dir must support nested paths, e.g. a checkout
# root or /home/deon/scripts).
#
# Each shim execs `spectre run <job> "$@"`, so a scheduler still pointing at
# an old absolute path begins recording provenance through the CLI immediately,
# before anything is repointed. Safe to re-run; overwrites existing shims.
set -euo pipefail

TARGET="${1:?usage: $0 <target-dir>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${SPECTRE_PYTHON:-$ROOT/.venv/bin/python}"

mkdir -p "$TARGET"

"$PYTHON" - "$ROOT" "$TARGET" <<'PY'
import json, os, sys
root, target = sys.argv[1], sys.argv[2]
data = json.load(open(os.path.join(root, "packages/dispatch/registry_data.json")))
for job in data:
    name = job["name"]
    dest = os.path.join(target, name + ".sh") if False else os.path.join(target, name)
    # keep nested dirs for namespaced jobs
    os.makedirs(os.path.dirname(dest), exist_ok=True) if os.path.dirname(dest) else None
    with open(dest, "w") as f:
        f.write("#!/usr/bin/env bash\n")
        f.write("# transitional forwarder — pre-merge absolute paths land here\n")
        f.write(f'exec spectre run {name} "$@"\n')
    os.chmod(dest, 0o755)
    print(f"wrote {dest}")
PY
