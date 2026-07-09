#!/usr/bin/env bash
set -euo pipefail

SPECTRE_HOME="${SPECTRE_HOME:-$HOME/.spectre}"
BACKUP_ROOT="${SPECTRE_BACKUP_DIR:-$HOME/spectre-backups}"
backup_dir="$BACKUP_ROOT/$(date +%Y%m%d-%H%M%S)"

trap 'echo "Backup failed: $BASH_COMMAND (line $LINENO)" >&2' ERR

mkdir -p "$backup_dir"

echo "==> Backing up Spectre config..."
cp -r "$SPECTRE_HOME" "$backup_dir/.spectre"

if [ -n "${SPECTRE_BACKUP_REPOS:-}" ]; then
    while IFS= read -r -d '' repo; do
        repo_name="${repo##*/}"
        echo "==> Backing up $repo_name..."
        cp -r "$repo" "$backup_dir/$repo_name"
    done < <(printf '%s\0' $SPECTRE_BACKUP_REPOS)
fi

echo "Backup saved to: $backup_dir"
