#!/bin/bash
set -euo pipefail

# Backup Verification Script
# Verifies backup integrity and completeness

BACKUP_DIR="/backups"
LOG_FILE="/var/log/backup-verification.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

log() {
    echo "[$TIMESTAMP] $1" | tee -a "$LOG_FILE" || true
}

error() {
    echo "[$TIMESTAMP] ERROR: $1" | tee -a "$LOG_FILE" || true >&2
}

# Verify file integrity using checksum
verify_checksum() {
    local file="$1"
    local checksum_file="$2"
    
    if [[ ! -f "$file" ]]; then
        error "File not found: $file"
        return 1
    fi
    
    if [[ ! -f "$checksum_file" ]]; then
        log "No checksum file found, generating checksum for: $file"
        sha256sum "$file" > "$checksum_file"
        return 0
    fi
    
    local current_checksum
    current_checksum=$(sha256sum "$file" | awk '{print $1}')
    local stored_checksum
    stored_checksum=$(cat "$checksum_file" | awk '{print $1}')
    
    if [[ "$current_checksum" == "$stored_checksum" ]]; then
        log "OK: Checksum verified for $file"
        return 0
    else
        error "Checksum mismatch for $file"
        return 1
    fi
}

# Verify gzip integrity
verify_gzip() {
    local file="$1"
    
    if [[ ! "$file" == *.gz ]]; then
        return 0
    fi
    
    if gzip -t "$file" 2>/dev/null; then
        log "OK: Gzip integrity verified: $file"
        return 0
    else
        error "Gzip integrity check failed: $file"
        return 1
    fi
}

# Verify tar integrity
verify_tar() {
    local file="$1"
    
    if [[ ! "$file" == *.tar.gz ]]; then
        return 0
    fi
    
    if tar -tzf "$file" > /dev/null 2>&1; then
        log "OK: Tar integrity verified: $file"
        return 0
    else
        error "Tar integrity check failed: $file"
        return 1
    fi
}

# Verify backup age
verify_backup_age() {
    local backup_file="$1"
    local max_age_hours="${2:-26}"  # Default: 26 hours (1 day)
    
    local file_age_hours
    file_age_hours=$(( ($(date +%s) - $(stat -c %Y "$backup_file")) / 3600 ))
    
    if [[ $file_age_hours -le $max_age_hours ]]; then
        log "OK: Backup age OK (${file_age_hours}h <= ${max_age_hours}h): $backup_file"
        return 0
    else
        error "Backup too old (${file_age_hours}h > ${max_age_hours}h): $backup_file"
        return 1
    fi
}

# Verify backup size
verify_backup_size() {
    local backup_file="$1"
    local min_size="${2:-1}"  # Default: 1KB
    
    local file_size
    file_size=$(stat -c %s "$backup_file" 2>/dev/null || echo 0)
    local min_size_bytes
    min_size_bytes=$((min_size * 1024))
    
    if [[ $file_size -ge $min_size_bytes ]]; then
        log "OK: Backup size OK (${file_size} bytes >= ${min_size_bytes} bytes): $backup_file"
        return 0
    else
        error "Backup too small (${file_size} bytes < ${min_size_bytes} bytes): $backup_file"
        return 1
    fi
}

# Verify database backup
verify_database_backup() {
    local backup_file="$1"
    
    log "Verifying database backup: $backup_file"
    
    # Check file exists
    if [[ ! -f "$backup_file" ]]; then
        error "Database backup file not found: $backup_file"
        return 1
    fi
    
    # Verify gzip
    verify_gzip "$backup_file" || return 1
    
    # Verify checksum if available
    local checksum_file="${backup_file}.sha256"
    if [[ -f "$checksum_file" ]]; then
        verify_checksum "$backup_file" "$checksum_file" || return 1
    fi
    
    # Verify age
    verify_backup_age "$backup_file" || return 1
    
    # Verify size
    verify_backup_size "$backup_file" || return 1
    
    log "Database backup verified: $backup_file"
    return 0
}

# Verify Docker volume backup
verify_docker_volume_backup() {
    local backup_file="$1"
    
    log "Verifying Docker volume backup: $backup_file"
    
    # Check file exists
    if [[ ! -f "$backup_file" ]]; then
        error "Docker volume backup file not found: $backup_file"
        return 1
    fi
    
    # Verify tar
    verify_tar "$backup_file" || return 1
    
    # Verify checksum if available
    local checksum_file="${backup_file}.sha256"
    if [[ -f "$checksum_file" ]]; then
        verify_checksum "$backup_file" "$checksum_file" || return 1
    fi
    
    # Verify age
    verify_backup_age "$backup_file" || return 1
    
    # Verify size (Docker volumes should be substantial)
    verify_backup_size "$backup_file" 102400 || return 1  # 100KB minimum
    
    log "Docker volume backup verified: $backup_file"
    return 0
}

# Generate checksum for backup

# Main verification function
main() {
    local backup_type="${1:-all}"
    
    log "=========================================="
    log "Backup Verification Started"
    log "Backup type: $backup_type"
    log "=========================================="
    
    local failures=0
    local successes=0
    
    case "$backup_type" in
        databases)
            for backup_file in "$BACKUP_DIR"/databases/*.gz; do
                if [[ -f "$backup_file" ]]; then
                    if verify_database_backup "$backup_file"; then
                        successes=$((successes + 1))
                    else
                        failures=$((failures + 1))
                    fi
                fi
            done
            ;;
        docker-volumes)
            for backup_file in "$BACKUP_DIR"/docker-volumes/*.tar.gz; do
                if [[ -f "$backup_file" ]]; then
                    if verify_docker_volume_backup "$backup_file"; then
                        successes=$((successes + 1))
                    else
                        failures=$((failures + 1))
                    fi
                fi
            done
            ;;
        configurations)
            for backup_file in "$BACKUP_DIR"/configurations/*; do
                if [[ -f "$backup_file" ]]; then
                    verify_checksum "$backup_file" || failures=$((failures + 1))
                    successes=$((successes + 1))
                fi
            done
            ;;
        all)
            # Verify databases
            for backup_file in "$BACKUP_DIR"/databases/*.gz; do
                if [[ -f "$backup_file" ]]; then
                    if verify_database_backup "$backup_file"; then
                        successes=$((successes + 1))
                    else
                        failures=$((failures + 1))
                    fi
                fi
            done
            
            # Verify Docker volumes
            for backup_file in "$BACKUP_DIR"/docker-volumes/*.tar.gz; do
                if [[ -f "$backup_file" ]]; then
                    if verify_docker_volume_backup "$backup_file"; then
                        successes=$((successes + 1))
                    else
                        failures=$((failures + 1))
                    fi
                fi
            done
            
            # Verify configurations
            for backup_file in "$BACKUP_DIR"/configurations/*; do
                if [[ -f "$backup_file" ]]; then
                    verify_checksum "$backup_file" || failures=$((failures + 1))
                    successes=$((successes + 1))
                fi
            done
            
            # Verify projects
            for backup_file in "$BACKUP_DIR"/projects/*; do
                if [[ -f "$backup_file" ]]; then
                    verify_checksum "$backup_file" || failures=$((failures + 1))
                    successes=$((successes + 1))
                fi
            done
            ;;
        *)
            error "Unknown backup type: $backup_type"
            echo "Usage: $0 [databases|docker-volumes|configurations|projects|all]"
            exit 1
            ;;
    esac
    
    log "=========================================="
    log "Backup Verification Completed"
    log "Successes: $successes"
    log "Failures: $failures"
    log "=========================================="
    
    if [[ $failures -gt 0 ]]; then
        exit 1
    fi
    
    exit 0
}

# Run main function
main "$@"