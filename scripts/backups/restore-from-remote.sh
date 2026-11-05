#!/bin/bash
set -euo pipefail

# Remote Backup Restore Script
# Restores data from off-site backup locations (S3, B2, rsync)

REMOTE_BACKUP_SERVER="${REMOTE_BACKUP_SERVER:-backup.example.com}"
REMOTE_BACKUP_PORT="${REMOTE_BACKUP_PORT:-2222}"
REMOTE_BACKUP_USER="${REMOTE_BACKUP_USER:-backup}"
LOG_FILE="/var/log/remote-restore.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE" || true
}

error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" | tee -a "$LOG_FILE" || true >&2
}

# List available backups on remote server
list_remote_backups() {
    log "Listing backups on remote server: $REMOTE_BACKUP_SERVER:$REMOTE_BACKUP_PORT"
    
    rsync -avz -e "ssh -p $REMOTE_BACKUP_PORT" \
        "$REMOTE_BACKUP_USER@$REMOTE_BACKUP_SERVER:/backups/" \
        --list-only \
        --exclude='.gitkeep' \
        --delete-excluded \
        /dev/null 2>&1 || {
        error "Failed to list remote backups"
        return 1
    }
}

# Download backup from remote server
download_backup() {
    local backup_type="$1"
    local local_dest="$2"
    
    log "Downloading $backup_type from remote server..."
    
    mkdir -p "$local_dest"
    
    rsync -avz --progress -e "ssh -p $REMOTE_BACKUP_PORT" \
        "$REMOTE_BACKUP_USER@$REMOTE_BACKUP_SERVER:/backups/$backup_type/" \
        "$local_dest/" || {
        error "Failed to download backup from remote server"
        return 1
    }
    
    log "Backup downloaded successfully to: $local_dest"
}

# Restore from S3 bucket
restore_from_s3() {
    local bucket="$1"
    local prefix="$2"
    local restore_type="$3"  # databases, docker-volumes, configurations
    
    log "Restoring from S3 bucket: $bucket/$prefix"
    
    # Check if AWS CLI is available
    if ! command -v aws &> /dev/null; then
        error "AWS CLI not installed. Install with: sudo apt-get install awscli"
        return 1
    fi
    
    # Download backup
    local temp_dir
    temp_dir=$(mktemp -d)
    aws s3 sync "s3://$bucket/$prefix/" "$temp_dir/" \
        --exclude '*.gz' \
        --exclude '*.tar.gz' \
        --include '*' \
        || {
        error "Failed to sync from S3"
        rm -rf "$temp_dir"
        return 1
    }
    
    # Find and restore latest backup
    local backup_file
    backup_file=$(find "$temp_dir" -maxdepth 1 -name "*$restore_type*$(date +%Y%m%d)*.gz" | sort -r | head -1)
    
    if [[ -z "$backup_file" ]]; then
        backup_file=$(find "$temp_dir" -maxdepth 1 -name "*$restore_type*.gz" | sort -r | head -1)
    fi
    
    if [[ -n "$backup_file" ]]; then
        log "Found backup: $backup_file"
        local dest_dir
        dest_dir="/tmp/restore_$(basename "$backup_file" .gz)"
        mkdir -p "$dest_dir"
        gunzip -c "$backup_file" > "$dest_dir/restore.sql"
        
        # Restore to appropriate location
        if [[ "$restore_type" == "databases" ]]; then
            restore_database_from_sql "$dest_dir/restore.sql"
        elif [[ "$restore_type" == "docker-volumes" ]]; then
            restore_docker_volumes_from_tar "$dest_dir"
        fi
        
        rm -rf "$temp_dir"
        log "Restore from S3 completed"
    else
        error "No backup file found in S3 bucket"
        rm -rf "$temp_dir"
        return 1
    fi
}

# Restore from Backblaze B2
restore_from_b2() {
    local bucket_name="$1"
    local prefix="$2"
    local restore_type="$3"
    
    log "Restoring from B2 bucket: $bucket_name/$prefix"
    
    # Check if B2 CLI is available
    if ! command -v b2 &> /dev/null; then
        error "B2 CLI not installed. Install with: pip install b2"
        return 1
    fi
    
    # Download backup
    local temp_dir
    temp_dir=$(mktemp -d)
    b2 sync "ftp://$bucket_name" "$temp_dir/$prefix" \
        --exclude '*.gz' \
        --exclude '*.tar.gz' \
        || {
        error "Failed to sync from B2"
        rm -rf "$temp_dir"
        return 1
    }
    
    # Find and restore latest backup
    local backup_file
    backup_file=$(find "$temp_dir" -maxdepth 1 -name "*$restore_type*$(date +%Y%m%d)*.gz" | sort -r | head -1)
    
    if [[ -z "$backup_file" ]]; then
        backup_file=$(find "$temp_dir" -maxdepth 1 -name "*$restore_type*.gz" | sort -r | head -1)
    fi
    
    if [[ -n "$backup_file" ]]; then
        log "Found backup: $backup_file"
        local dest_dir
        dest_dir="/tmp/restore_$(basename "$backup_file" .gz)"
        mkdir -p "$dest_dir"
        gunzip -c "$backup_file" > "$dest_dir/restore.sql"
        
        # Restore to appropriate location
        if [[ "$restore_type" == "databases" ]]; then
            restore_database_from_sql "$dest_dir/restore.sql"
        elif [[ "$restore_type" == "docker-volumes" ]]; then
            restore_docker_volumes_from_tar "$dest_dir"
        fi
        
        rm -rf "$temp_dir"
        log "Restore from B2 completed"
    else
        error "No backup file found in B2 bucket"
        rm -rf "$temp_dir"
        return 1
    fi
}

# Restore database from SQL file
restore_database_from_sql() {
    local sql_file="$1"
    
    log "Restoring database from SQL file: $sql_file"
    
    # Determine restore target
    local restore_target="${RESTORE_TARGET:-docker}"
    
    if [[ "$restore_target" == "docker" ]]; then
        # Get the database name from the SQL file. The previous fallback was
        # "guardrail", a database from another project that does not exist here,
        # so a dump without an explicit CREATE DATABASE header restored into
        # nothing. Fall back to the container's own POSTGRES_DB instead.
        local db_name
        db_name=$(grep -m1 "CREATE DATABASE" "$sql_file" 2>/dev/null | sed 's/.*CREATE DATABASE \([^ ]*\).*/\1/' || true)
        if [ -z "$db_name" ]; then
            db_name=$(docker exec "${POSTGRES_CONTAINER:-postgres}" \
                sh -c 'printf %s "${POSTGRES_DB:-postgres}"' 2>/dev/null || printf 'postgres')
        fi

        # A database name is not a container name. Resolve the container the way
        # restore-databases.sh does rather than assuming the two match, and use
        # `docker inspect` so a stopped server is still recognised.
        local pg_container="${POSTGRES_CONTAINER:-}"
        if [ -n "$pg_container" ] && ! docker inspect "$pg_container" >/dev/null 2>&1; then
            pg_container=""
        fi
        if [ -z "$pg_container" ] && docker inspect "$db_name" >/dev/null 2>&1; then
            pg_container="$db_name"
        fi
        if [ -z "$pg_container" ]; then
            pg_container=$(docker ps -a --format '{{.Names}}' | grep -ix "postgres" | head -1)
        fi
        if [ -z "$pg_container" ]; then
            error "No PostgreSQL container found for database '$db_name'"
            return 1
        fi

        # Read the role from the container: POSTGRES_USER is not "postgres" here,
        # and assuming it fails with 'role postgres does not exist'.
        local pg_user
        pg_user=$(docker exec "$pg_container" sh -c 'printf %s "${POSTGRES_USER:-postgres}"' 2>/dev/null || printf 'postgres')

        log "Restoring database '$db_name' into container '$pg_container' as role '$pg_user'"

        # Restore data
        gunzip -c "$sql_file" | docker exec -i "$pg_container" psql -U "$pg_user" -d "$db_name"
        
        log "Database restore completed"
    else
        # Restore to local PostgreSQL
        if ! pg_isready; then
            error "PostgreSQL is not running"
            return 1
        fi
        
        gunzip -c "$sql_file" | psql -U "${PGUSER:-postgres}"
        log "Local database restore completed"
    fi
}

# Restore Docker volumes from tar
restore_docker_volumes_from_tar() {
    local tar_dir="$1"
    
    log "Restoring Docker volumes from tar archive"
    
    # Extract tar archive
    local extract_dir
    extract_dir=$(mktemp -d)
    tar -xzf "$tar_dir/volumes.tar.gz" -C "$extract_dir"
    
    # Restore each volume
    for volume_path in "$extract_dir"/*/; do
        local volume_name
        volume_name=$(basename "$volume_path")
        log "Restoring volume: $volume_name"
        
        # Stop and remove existing container
        docker stop "$volume_name" 2>/dev/null || true
        docker rm "$volume_name" 2>/dev/null || true
        
        # Create new container
        docker run -d \
            --name "$volume_name" \
            -v "$volume_path:/data" \
            alpine:latest \
            sleep infinity
        
        log "Volume $volume_name restored"
    done
    
    rm -rf "$extract_dir"
    log "Docker volume restore completed"
}

# Main restore function
main() {
    local restore_source="${1:-remote}"
    local backup_type="${2:-databases}"
    local bucket_or_server="${3:-}"
    
    log "=========================================="
    log "Remote Backup Restore Started"
    log "Source: $restore_source"
    log "Backup type: $backup_type"
    log "=========================================="
    
    case "$restore_source" in
        rsync)
            # Restore from remote server via rsync
            if [[ -z "$bucket_or_server" ]]; then
                error "Server not specified"
                exit 1
            fi
            download_backup "$backup_type" "/tmp/restore_$(date +%Y%m%d_%H%M%S)"
            ;;
        s3)
            # Restore from S3
            if [[ -z "$bucket_or_server" ]]; then
                error "Bucket name not specified"
                exit 1
            fi
            restore_from_s3 "$bucket_or_server" "" "$backup_type"
            ;;
        b2)
            # Restore from B2
            if [[ -z "$bucket_or_server" ]]; then
                error "Bucket name not specified"
                exit 1
            fi
            restore_from_b2 "$bucket_or_server" "" "$backup_type"
            ;;
        *)
            error "Unknown restore source: $restore_source"
            echo "Usage: $0 [rsync|s3|b2] [backup_type] [bucket/server]"
            echo "  backup_type: databases, docker-volumes, configurations"
            exit 1
            ;;
    esac
    
    log "=========================================="
    log "Remote Backup Restore Completed"
    log "=========================================="
}

# Run main function
main "$@"