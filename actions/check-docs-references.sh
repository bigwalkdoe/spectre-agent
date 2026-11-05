#!/bin/bash
# Fails when the documentation tells a reader to run a script that is not in the
# repository.
#
# The README's quick start and security sections referenced 20-odd scripts under
# scripts/security, scripts/performance, scripts/network and scripts/maintenance
# that do not exist here. Anyone following the documented setup got "No such file
# or directory" on the first command. The drift was invisible because nothing
# checked it.
#
# Every scripts/ or cloud-deployment/ path mentioned in the docs must exist. To
# describe a capability that is genuinely not implemented here, describe it in
# prose without a path rather than documenting a command that cannot run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

docs=$(ls README.md docs/*.md 2>/dev/null)
if [ -z "$docs" ]; then
    echo "ERROR: no documentation files found to check" >&2
    exit 1
fi

# Match the paths a reader could paste into a shell. The final character class
# excludes "." so a path at the end of a sentence ("...audit-trail.sh.") is not
# captured with its full stop, which would look like a missing file.
pattern='(scripts|cloud-deployment)/[A-Za-z0-9._/-]*[A-Za-z0-9_/-]'

# shellcheck disable=SC2086  # word splitting into the file list is intended
missing=$(
    grep -rhoE "$pattern" $docs 2>/dev/null | sort -u | while read -r p; do
        [ -e "$p" ] || printf '%s\n' "$p"
    done
)

if [ -n "$missing" ]; then
    # shellcheck disable=SC2086  # as above
    while read -r p; do
        [ -n "$p" ] || continue
        # shellcheck disable=SC2086  # as above
        refs=$(grep -rlE "$p" $docs 2>/dev/null | tr '\n' ' ')
        echo "ERROR: documented path does not exist: $p" >&2
        echo "       referenced in: $refs" >&2
    done <<< "$missing"
    echo >&2
    echo "Describe unimplemented capabilities in prose, without a path." >&2
    exit 1
fi

echo "documentation references OK: every scripts/ and cloud-deployment/ path mentioned resolves"
