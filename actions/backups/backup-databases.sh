#!/bin/bash
set -euo pipefail

# Database Backup Script
# Backs up PostgreSQL and Redis. Neo4j only if this deployment has it.
#
# The previous version could not have worked here. It defaulted the container
# names to another project's (guardrail-ai-postgres-1, guardrail-ai-redis-1,
# guardrail-ai-neo4j-1), connected as a role "postgres" that does not exist in
# this stack, and dumped a database named "guardrail" that does not exist either.
# Under `set -euo pipefail` the very first pg_dump aborted the script, so no
# database was ever backed up and the success marker was never written -- while
# a stale marker from an earlier run still satisfied the staleness check.
#
# Every target is now discovered rather than assumed, each dump is verified, and
# the run fails loudly if a configured target did not back up.

BACKUP_DIR="${BACKUP_DIR:-/backups/databases}"
# Kept outside BACKUP_DIR on purpose: the retention step below deletes every
# file in that directory older than the retention window, so a marker stored
# there would be swept away and look like "no successful backup" on day 8.
BACKUP_STATE_DIR="${BACKUP_STATE_DIR:-/backups/backup-state}"
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS="${RETENTION_DAYS:-7}"

# Container names are environment-specific; these match container_name in
# docker-compose.monitoring.yml and can be overridden per deployment.
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-postgres}"
REDIS_CONTAINER="${REDIS_CONTAINER:-redis}"
NEO4J_CONTAINER="${NEO4J_CONTAINER:-neo4j}"

mkdir -p "$BACKUP_DIR" "$BACKUP_STATE_DIR" 2>/dev/null || true
if [ ! -w "$BACKUP_DIR" ] || [ ! -w "$BACKUP_STATE_DIR" ]; then
    echo "ERROR: BACKUP_DIR ($BACKUP_DIR) or BACKUP_STATE_DIR ($BACKUP_STATE_DIR) is not writable." >&2
    echo "  Set both to writable paths; the staleness check reads the marker from" >&2
    echo "  BACKUP_STATE_DIR, so a silently redirected marker disables alerting." >&2
    exit 1
fi

# Record that a run started. The exporter reports this alongside the success
# marker so a failed or never-run backup is distinguishable from a stale one,
# which a single "last success" metric cannot express.
date +%s > "$BACKUP_STATE_DIR/last-db-backup-attempt.tmp" \
    && mv -f "$BACKUP_STATE_DIR/last-db-backup-attempt.tmp" "$BACKUP_STATE_DIR/last-db-backup-attempt" \
    || true

failures=0
note_failure() { echo "ERROR: $*" >&2; failures=$((failures + 1)); }
container_exists() { docker inspect "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------- PostgreSQL
echo "Backing up PostgreSQL databases..."

if ! container_exists "$POSTGRES_CONTAINER"; then
    note_failure "PostgreSQL container '$POSTGRES_CONTAINER' not found"
else
    # Read the credentials this container was actually started with rather than
    # assuming: POSTGRES_USER is 'deon' here, and a hardcoded -U postgres fails
    # with 'role postgres does not exist'.
    PG_USER=$(docker exec "$POSTGRES_CONTAINER" sh -c 'printf %s "${POSTGRES_USER:-postgres}"')
    PG_DB=$(docker exec "$POSTGRES_CONTAINER" sh -c 'printf %s "${POSTGRES_DB:-postgres}"')

    # Dump every non-template database. Enumerating them means a database added
    # later is covered without editing this script, and it avoids dumping a
    # hardcoded name that may not exist.
    mapfile -t databases < <(
        docker exec "$POSTGRES_CONTAINER" \
            psql -U "$PG_USER" -d "${PG_DB:-postgres}" -tAc \
            "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname" \
            2>/dev/null || true
    )

    if [ "${#databases[@]}" -eq 0 ]; then
        note_failure "could not list databases as role '$PG_USER'"
    else
        echo "  found ${#databases[@]} database(s): ${databases[*]}"
        for db in "${databases[@]}"; do
            db=${db//[[:space:]]/}
            [ -n "$db" ] || continue
            archive="$BACKUP_DIR/postgres_${db}_${DATE}.sql.gz"

            if ! docker exec "$POSTGRES_CONTAINER" \
                pg_dump -U "$PG_USER" -d "$db" 2>/tmp/pg_dump_err.$$ | gzip > "$archive"; then
                note_failure "pg_dump failed for database '$db': $(head -1 /tmp/pg_dump_err.$$)"
                rm -f "$archive"
                rm -f /tmp/pg_dump_err.$$
                continue
            fi
            rm -f /tmp/pg_dump_err.$$

            # A dump of an empty database is still a few KB of schema, so check
            # that it is real gzip and non-trivial rather than merely present.
            if [ ! -s "$archive" ] || ! gzip -t "$archive" 2>/dev/null; then
                note_failure "dump for '$db' is empty or not valid gzip"
                rm -f "$archive"
            else
                echo "    $db -> $(basename "$archive") ($(du -h "$archive" | cut -f1))"
            fi
        done
    fi
fi

# --------------------------------------------------------------------- Redis
echo "Backing up Redis data..."

if ! container_exists "$REDIS_CONTAINER"; then
    note_failure "Redis container '$REDIS_CONTAINER' not found"
else
    # The compose command is `redis-server --requirepass ${REDIS_PASSWORD}`, and
    # the password is passed on the command line rather than as an environment
    # variable, so it has to be read back from the container. Without it
    # `redis-cli --rdb` fails with NOAUTH and the previous version never produced
    # a Redis backup. An explicit REDIS_PASSWORD in the environment wins.
    if [ -z "${REDIS_PASSWORD:-}" ]; then
        REDIS_PASSWORD=$(docker inspect "$REDIS_CONTAINER" \
            --format '{{range .Config.Cmd}}{{println .}}{{end}}' 2>/dev/null \
            | awk 'take { print; exit } $0 == "--requirepass" { take = 1 }' || true)
    fi

    redis_auth=()
    if [ -n "${REDIS_PASSWORD:-}" ]; then
        redis_auth=(-a "$REDIS_PASSWORD" --no-auth-warning)
        echo "  authenticating with the password from the container command line"
    fi

    if docker exec "$REDIS_CONTAINER" redis-cli "${redis_auth[@]}" --rdb /tmp/backup.rdb >/dev/null 2>&1 \
        && docker cp "$REDIS_CONTAINER":/tmp/backup.rdb "$BACKUP_DIR/redis_backup_$DATE.rdb" >/dev/null 2>&1; then
        docker exec "$REDIS_CONTAINER" rm -f /tmp/backup.rdb >/dev/null 2>&1 || true
        if [ -s "$BACKUP_DIR/redis_backup_$DATE.rdb" ]; then
            echo "    redis -> redis_backup_$DATE.rdb ($(du -h "$BACKUP_DIR/redis_backup_$DATE.rdb" | cut -f1))"
        else
            note_failure "Redis RDB came back empty"
            rm -f "$BACKUP_DIR/redis_backup_$DATE.rdb"
        fi
    else
        note_failure "redis-cli --rdb or docker cp failed for '$REDIS_CONTAINER'"
    fi
    unset REDIS_PASSWORD redis_auth
fi

# -------------------------------------------------------------------- Neo4j
# Not part of docker-compose.monitoring.yml. Backed up only if the deployment
# actually runs it, so its absence is not an error.
if container_exists "$NEO4J_CONTAINER"; then
    echo "Backing up Neo4j data..."
    if docker exec "$NEO4J_CONTAINER" neo4j-admin database dump --to-path=/tmp/backup neo4j >/dev/null 2>&1 \
        && docker cp "$NEO4J_CONTAINER":/tmp/backup "$BACKUP_DIR/neo4j_dump_$DATE" >/dev/null 2>&1; then
        docker exec "$NEO4J_CONTAINER" rm -rf /tmp/backup >/dev/null 2>&1 || true
        tar -czf "$BACKUP_DIR/neo4j_dump_$DATE.tar.gz" -C "$BACKUP_DIR" "neo4j_dump_$DATE"
        rm -rf "$BACKUP_DIR/neo4j_dump_$DATE"
        echo "    neo4j -> neo4j_dump_$DATE.tar.gz"
    else
        note_failure "Neo4j dump failed"
    fi
else
    echo "Skipping Neo4j (container '$NEO4J_CONTAINER' not present in this deployment)"
fi

# Cleanup old backups
echo "Cleaning up old backups (older than $RETENTION_DAYS days)..."
find "$BACKUP_DIR" -type f -mtime +"$RETENTION_DAYS" -delete

if [ "$failures" -ne 0 ]; then
    # Deliberately no success marker: a partial or failed run must leave the
    # previous marker in place so the staleness check keeps firing, and must not
    # claim a fresh success that would silence it.
    echo "Database backup FAILED: $failures target(s) did not back up cleanly" >&2
    exit 1
fi

echo "Database backup completed: $DATE"
# Written only after every dump and the retention step have succeeded, and only
# reached because the script runs under `set -e`. The exporter reads this instead
# of the mtime of $BACKUP_DIR: the directory mtime also advances when retention
# deletes an old file, so it reported "recent successful backup" even when
# nothing had been backed up.
date +%s > "$BACKUP_STATE_DIR/last-db-backup-success.tmp" \
    && mv -f "$BACKUP_STATE_DIR/last-db-backup-success.tmp" "$BACKUP_STATE_DIR/last-db-backup-success"
logger -p user.info "Database backup completed successfully" 2>/dev/null || true
