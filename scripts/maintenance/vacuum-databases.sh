#!/bin/bash
# PostgreSQL vacuum / analyze
#
# Replaces a script that had never once run, for three independent reasons:
#   1. It targeted guardrail-ai-postgres-1, a container from another project.
#   2. It connected as role "postgres", which does not exist here (POSTGRES_USER
#      is 'deon').
#   3. It logged to /var/log/pg-vacuum.log, which is not writable by the cron
#      user, so under `set -euo pipefail` it aborted on its very first echo --
#      before resolving anything, and without leaving a log to say so.
#
# REINDEX is not run by default. `REINDEX DATABASE` rebuilds every index in the
# database, which is not a daily maintenance task; on a monitoring stack the
# indexes are small. It is available behind an explicit flag for the rare occasion
# it is actually warranted.
set -euo pipefail


POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-postgres}"
REINDEX=0
LOG_FILE="${LOG_FILE:-}"

usage() {
    cat <<'EOF'
Usage: vacuum-databases.sh [--reindex] [--dry-run]

  --reindex   Also run REINDEX DATABASE on each database. This rebuilds every
               index and is expensive; it is not part of routine vacuuming.
  --dry-run   List the databases and the statements that would run.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --reindex) REINDEX=1 ;;
        --dry-run) DRY_RUN=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done
DRY_RUN=${DRY_RUN:-0}

# Same log fallback as the other scripts: /var/log needs root, and a script whose
# first write fails tells you nothing about why it did nothing.
if [ -z "$LOG_FILE" ]; then
    if mkdir -p /var/log 2>/dev/null && [ -w /var/log ]; then
        LOG_FILE=/var/log/pg-vacuum.log
    else
        LOG_FILE="${TMPDIR:-/tmp}/pg-vacuum.log"
    fi
fi

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

if ! docker inspect "$POSTGRES_CONTAINER" >/dev/null 2>&1; then
    log "FAIL: PostgreSQL container '$POSTGRES_CONTAINER' not found."
    log "      Set POSTGRES_CONTAINER, or start the stack."
    exit 1
fi

# Read the role and default database from the container rather than assuming.
PG_USER=$(docker exec "$POSTGRES_CONTAINER" sh -c 'printf %s "${POSTGRES_USER:-postgres}"')
PG_DB=$(docker exec "$POSTGRES_CONTAINER" sh -c 'printf %s "${POSTGRES_DB:-postgres}"')

psql_container() { docker exec "$POSTGRES_CONTAINER" psql -U "$PG_USER" -d "$1" -tAc "$2" 2>/dev/null; }

log "PostgreSQL vacuum/analyze -- container=$POSTGRES_CONTAINER role=$PG_USER default_db=$PG_DB"

if ! docker exec "$POSTGRES_CONTAINER" pg_isready -U "$PG_USER" -d "$PG_DB" >/dev/null 2>&1; then
    log "PostgreSQL is not accepting connections; skipping (it may be intentionally stopped)."
    exit 0
fi

mapfile -t databases < <(psql_container "$PG_DB" \
    "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname")

if [ "${#databases[@]}" -eq 0 ]; then
    log "FAIL: could not list databases as role '$PG_USER'."
    exit 1
fi
log "databases: ${databases[*]}"

if [ "$DRY_RUN" -eq 1 ]; then
    for db in "${databases[@]}"; do
        log "would run on '$db': VACUUM (ANALYZE); $([ "$REINDEX" -eq 1 ] && echo 'REINDEX DATABASE;')"
    done
    exit 0
fi

# Vacuum cannot run inside a transaction block, and ANALYZE is already implied by
# VACUUM (ANALYZE). The previous version ran ANALYZE, then VACUUM (ANALYZE), then
# a full REINDEX: the first two were redundant and the third dominated the runtime.
failed=0
for db in "${databases[@]}"; do
    log "vacuuming '$db'"
    if ! docker exec "$POSTGRES_CONTAINER" psql -U "$PG_USER" -d "$db" -c "VACUUM (ANALYZE);" >>"$LOG_FILE" 2>&1; then
        log "  FAIL: VACUUM failed on '$db' (see $LOG_FILE)"
        failed=$((failed + 1))
        continue
    fi
    if [ "$REINDEX" -eq 1 ]; then
        log "  reindexing '$db'"
        # Quoted: the database name is interpolated into SQL, and REINDEX DATABASE
        # does not accept a quoted identifier there.
        if ! docker exec "$POSTGRES_CONTAINER" psql -U "$PG_USER" -d "$db" \
            -c "REINDEX DATABASE \"$db\";" >>"$LOG_FILE" 2>&1; then
            log "  FAIL: REINDEX failed on '$db'"
            failed=$((failed + 1))
        fi
    fi
done

# Report the state the maintenance was for, so the log has a purpose beyond
# "done". Only tables with meaningful dead-tuple counts.
bloat=$(psql_container "$PG_DB" "
    SELECT schemaname || '.' || relname || '  ' || pg_size_pretty(pg_total_relation_size(relid))
        || '  dead=' || n_dead_tup
    FROM pg_stat_user_tables
    WHERE n_dead_tup > 1000
    ORDER BY n_dead_tup DESC
    LIMIT 10;")
if [ -n "$bloat" ]; then
    log "tables with >1000 dead tuples after vacuum:"
    printf '%s\n' "$bloat" | while read -r line; do log "  $line"; done
else
    log "no tables with significant dead tuples"
fi

if [ "$failed" -ne 0 ]; then
    log "VACUUM COMPLETED WITH $failed FAILURE(S)"
    exit 1
fi
log "vacuum/analyze completed for ${#databases[@]} database(s)"
