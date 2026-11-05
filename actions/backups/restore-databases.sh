#!/bin/bash
set -euo pipefail

# Database Restore Script
# Restores PostgreSQL databases from backup files

BACKUP_DIR="${BACKUP_DIR:-/backups/databases}"
# Log to /var/log when writable (root), otherwise fall back to a local log so
# the script is usable by non-privileged users. Override with LOG_FILE.
if [[ -n "${LOG_FILE:-}" ]]; then
    :
elif [[ -w /var/log ]]; then
    LOG_FILE="/var/log/database-restore.log"
else
    LOG_FILE="${TMPDIR:-/tmp}/database-restore.log"
fi

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE" || true
}

error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" | tee -a "$LOG_FILE" || true >&2
}

# The database name to restore into.
#
# Archives are written as postgres_<database>_<YYYYmmdd>_<HHMMSS>.sql.gz, so the
# name can be read back off the archive instead of assumed. The previous default
# was "guardrail", a database that does not exist here, and the lookup pattern
# was postgres_guardrail_*.sql.gz, which matched nothing -- so `latest` reported
# no backup for a database that had been dumped successfully minutes earlier.
default_database_name() {
    local archive="${1:-}"
    if [ -n "$archive" ] && [ -f "$archive" ]; then
        local base
        base=$(basename "$archive" .sql.gz)
        local name
        name=$(printf '%s' "$base" | sed -E 's/^postgres_//; s/_[0-9]{8}_[0-9]{6}$//')
        [ -n "$name" ] && { printf '%s' "$name"; return; }
    fi
    # No archive, or an unrecognised name: ask the container.
    local container="${POSTGRES_CONTAINER:-postgres}"
    if docker inspect "$container" >/dev/null 2>&1; then
        docker exec "$container" sh -c 'printf %s "${POSTGRES_DB:-postgres}"' 2>/dev/null && return
    fi
    printf '%s' 'postgres'
}

# Find latest backup
find_latest_backup() {
    local backup_type="$1"
    local pattern

    case "$backup_type" in
        postgres|postgres_generic)
            pattern="postgres_*.sql.gz"
            ;;
        *)
            error "Unknown backup type: $backup_type"
            return 1
            ;;
    esac

    find "$BACKUP_DIR" -maxdepth 1 -name "$pattern" -printf "%T@ %p\n" 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2- || true
}

# Verify backup integrity
verify_backup() {
    local backup_file="$1"
    
    if [[ "$backup_file" == *.gz ]]; then
        gzip -t "$backup_file" 2>/dev/null || {
            error "Backup file is corrupted: $backup_file"
            return 1
        }
    fi
    
    log "Backup integrity verified: $backup_file"
    return 0
}

# Restore PostgreSQL database
restore_postgres() {
    local backup_file="$1"
    local database_name="${2:-$(default_database_name "$1")}"
    local restore_target="${3:-}"
    
    if [[ ! -f "$backup_file" ]]; then
        error "Backup file not found: $backup_file"
        return 1
    fi
    
    log "Starting PostgreSQL restore from: $backup_file"
    
    # Verify backup
    if ! verify_backup "$backup_file"; then
        return 1
    fi
    
    # Determine restore method
    if [[ -n "$restore_target" && "$restore_target" == "docker" ]]; then
        # Restore to Docker container
        log "Restoring to Docker container..."

        # Locate the running PostgreSQL container: prefer an exact name match,
        # otherwise fall back to any container running a PostgreSQL server
        # (exclude exporters/proxies that merely contain "postgres" in their name).
        # Resolve the container by name, not by matching the database name
        # against container names: they are unrelated, and the two only coincided
        # here because this database happens to be called "postgres".
        #
        # Precedence matters. POSTGRES_CONTAINER is honoured only when the caller
        # set it explicitly -- defaulting it to "postgres" would hijack restores
        # that target some other database, such as the restore drill, which runs
        # a throwaway container named after its own database. -a so a stopped
        # server is still found, which is the normal state during a restore.
        local pg_container="${POSTGRES_CONTAINER:-}"
        if [[ -n "$pg_container" ]] && ! docker inspect "$pg_container" >/dev/null 2>&1; then
            error "POSTGRES_CONTAINER='$pg_container' does not exist"
            return 1
        fi
        if [[ -z "$pg_container" ]] && docker inspect "$database_name" >/dev/null 2>&1; then
            # A container named exactly after the database is the unambiguous case.
            pg_container="$database_name"
        fi
        if [[ -z "$pg_container" ]]; then
            pg_container=$(docker ps -a --format '{{.Names}}' | grep -ix "postgres" | head -1)
        fi
        if [[ -z "$pg_container" ]]; then
            pg_container=$(docker ps -a --format '{{.Names}}' | grep -i "postgres" | grep -vi "exporter" | head -1)
        fi

        if [[ -z "$pg_container" ]]; then
            error "No PostgreSQL container found. Start the stack, or pass POSTGRES_CONTAINER."
            return 1
        fi
        log "Using PostgreSQL container: $pg_container"

        # Read the role from the container rather than assuming "postgres", which
        # does not exist in this stack (POSTGRES_USER is 'deon') and made every
        # restore fail with 'role postgres does not exist'.
        local pg_user
        pg_user=$(docker exec "$pg_container" sh -c 'printf %s "${POSTGRES_USER:-postgres}"' 2>/dev/null || printf 'postgres')

        if ! docker exec "$pg_container" pg_isready -U "$pg_user" -d "$database_name" >/dev/null 2>&1; then
            log "PostgreSQL in $pg_container is not accepting connections; starting it"
            docker start "$pg_container" >/dev/null
            for _ in $(seq 1 30); do
                docker exec "$pg_container" pg_isready -U "$pg_user" -d "$database_name" >/dev/null 2>&1 && break
                sleep 1
            done
        fi

        # Restore data
        gunzip -c "$backup_file" | docker exec -i "$pg_container" psql -U "$pg_user" -d "$database_name"

        log "PostgreSQL restore completed successfully"
    else
        # Restore to local PostgreSQL
        log "Restoring to local PostgreSQL..."
        
        # Check if PostgreSQL is running
        if ! pg_isready; then
            error "PostgreSQL is not running"
            return 1
        fi
        
        gunzip -c "$backup_file" | psql -U "${PGUSER:-postgres}" -d "$database_name"
        
        log "PostgreSQL restore completed successfully"
    fi
}

# Main restore function
main() {
    local restore_type="${1:-latest}"
    local database_name="${2:-$(default_database_name "$1")}"
    local restore_target="${3:-docker}"

    log "=========================================="
    log "Database Restore Started"
    log "Restore type: $restore_type"
    # Positional args shift meaning by mode, so the summary has to follow the
    # same shift: "specific" takes <backup_file> <database_name> <target>,
    # "latest" takes nothing and derives all three.
    if [ "$restore_type" = "specific" ]; then
        log "Backup file: ${2:-}"
        log "Database: ${3:-${2:-}}"
        log "Target: ${4:-docker}"
    else
        log "Database: $database_name"
        log "Target: $restore_target"
    fi
    log "=========================================="

    case "$restore_type" in
        latest)
            backup_file=$(find_latest_backup "postgres")
            if [[ -z "$backup_file" ]]; then
                error "No backup files found in $BACKUP_DIR"
                exit 1
            fi
            restore_postgres "$backup_file" "$database_name" "$restore_target"
            ;;
        specific)
            # Args: specific <backup_file> [database_name] [target]
            local backup_file="${2:-}"
            local specific_db="${3:-$database_name}"
            local specific_target="${4:-$restore_target}"
            if [[ ! -f "$backup_file" ]]; then
                error "Backup file not found: $backup_file"
                exit 1
            fi
            restore_postgres "$backup_file" "$specific_db" "$specific_target"
            ;;
        *)
            error "Unknown restore type: $restore_type"
            echo "Usage: $0 [latest|specific <backup_file> <database_name> <target:docker|local>]"
            exit 1
            ;;
    esac
    
    log "=========================================="
    log "Database Restore Completed"
    log "=========================================="
}

# Run main function
main "$@"