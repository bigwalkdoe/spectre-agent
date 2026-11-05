#!/bin/bash
set -euo pipefail

# Backup Encryption Script
# Encrypts backup files before storage

BACKUP_DIR="/backups"
ENCRYPTION_KEY_FILE="${ENCRYPTION_KEY_FILE:-/etc/spectre-suite/backup-key}"
ENCRYPTION_ALGORITHM="${ENCRYPTION_ALGORITHM:-aes-256-cbc}"
LOG_FILE="/var/log/backup-encryption.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

log() {
    echo "[$TIMESTAMP] $1" | tee -a "$LOG_FILE" || true
}

error() {
    echo "[$TIMESTAMP] ERROR: $1" | tee -a "$LOG_FILE" || true >&2
}

# Generate encryption key if not exists
generate_key() {
    log "Generating encryption key..."
    
    if [[ ! -f "$ENCRYPTION_KEY_FILE" ]]; then
        # Generate 32-byte random key
        openssl rand -out "$ENCRYPTION_KEY_FILE" 32
        
        # Set secure permissions
        chmod 600 "$ENCRYPTION_KEY_FILE"
        chown root:root "$ENCRYPTION_KEY_FILE"
        
        log "Encryption key generated securely"
    else
        log "Using existing encryption key"
    fi
}

# Encrypt a file
encrypt_file() {
    local input_file="$1"
    local output_file="$2"
    
    if [[ ! -f "$input_file" ]]; then
        error "Input file not found: $input_file"
        return 1
    fi
    
    log "Encrypting: $input_file -> $output_file"
    
    # Get key
    
    # Encrypt with AES-256-CBC
    openssl enc -aes-256-cbc -salt -pbkdf2 \
        -in "$input_file" \
        -out "$output_file" \
        -pass file:"$ENCRYPTION_KEY_FILE" 2>/dev/null || {
        error "Encryption failed for $input_file"
        return 1
    }
    
    # Set secure permissions on encrypted file
    chmod 600 "$output_file"
    
    log "Successfully encrypted: $output_file"
    return 0
}

# Encrypt backup directory
encrypt_backup_dir() {
    local backup_type="$1"
    local source_dir="$BACKUP_DIR/$backup_type"
    local dest_dir="$BACKUP_DIR/encrypted/$backup_type"
    
    if [[ ! -d "$source_dir" ]]; then
        error "Backup directory not found: $source_dir"
        return 1
    fi
    
    log "Encrypting backup directory: $source_dir -> $dest_dir"
    
    # Create destination directory
    mkdir -p "$dest_dir"
    
    # Encrypt each file
    for file in "$source_dir"/*; do
        if [[ -f "$file" ]]; then
            local filename
            filename=$(basename "$file")
            local encrypted_file="$dest_dir/${filename}.enc"
            
            encrypt_file "$file" "$encrypted_file"
            
            # Remove original file after encryption
            rm "$file"
        fi
    done
    
    log "Successfully encrypted backup directory: $dest_dir"
}

# Decrypt a file
decrypt_file() {
    local input_file="$1"
    local output_file="$2"
    
    if [[ ! -f "$input_file" ]]; then
        error "Input file not found: $input_file"
        return 1
    fi
    
    log "Decrypting: $input_file -> $output_file"
    
    # Get key
    
    # Decrypt with AES-256-CBC
    openssl enc -aes-256-cbc -d -salt -pbkdf2 \
        -in "$input_file" \
        -out "$output_file" \
        -pass file:"$ENCRYPTION_KEY_FILE" 2>/dev/null || {
        error "Decryption failed for $input_file"
        return 1
    }
    
    log "Successfully decrypted: $output_file"
    return 0
}

# Decrypt backup directory
decrypt_backup_dir() {
    local backup_type="$1"
    local source_dir="$BACKUP_DIR/encrypted/$backup_type"
    local dest_dir="$BACKUP_DIR/$backup_type"
    
    if [[ ! -d "$source_dir" ]]; then
        error "Encrypted backup directory not found: $source_dir"
        return 1
    fi
    
    log "Decrypting backup directory: $source_dir -> $dest_dir"
    
    # Create destination directory
    mkdir -p "$dest_dir"
    
    # Decrypt each file
    for file in "$source_dir"/*.enc; do
        if [[ -f "$file" ]]; then
            local filename
            filename=$(basename "$file" .enc)
            local decrypted_file="$dest_dir/$filename"
            
            decrypt_file "$file" "$decrypted_file"
            
            # Remove encrypted file after decryption
            rm "$file"
        fi
    done
    
    log "Successfully decrypted backup directory: $dest_dir"
}

# Encrypt backup with GPG
encrypt_with_gpg() {
    local input_file="$1"
    local output_file="$2"
    
    if [[ ! -f "$input_file" ]]; then
        error "Input file not found: $input_file"
        return 1
    fi
    
    log "Encrypting with GPG: $input_file -> $output_file"
    
    # Encrypt with GPG (requires GPG key)
    gpg --symmetric --cipher-algo AES256 \
        --armor \
        -o "$output_file" \
        "$input_file" 2>/dev/null || {
        error "GPG encryption failed for $input_file"
        return 1
    }
    
    log "Successfully encrypted with GPG: $output_file"
    return 0
}

# Main function
main() {
    local action="${1:-encrypt}"
    local backup_type="${2:-all}"
    
    log "=========================================="
    log "Backup Encryption Started"
    log "Action: $action"
    log "Backup type: $backup_type"
    log "=========================================="
    
    case "$action" in
        encrypt)
            generate_key
            
            case "$backup_type" in
                all)
                    for type in databases docker-volumes configurations projects; do
                        if [[ -d "$BACKUP_DIR/$type" ]] && [[ -n "$(ls -A "$BACKUP_DIR/$type" 2>/dev/null)" ]]; then
                            encrypt_backup_dir "$type"
                        fi
                    done
                    ;;
                *)
                    encrypt_backup_dir "$backup_type"
                    ;;
            esac
            ;;
        decrypt)
            case "$backup_type" in
                all)
                    for type in databases docker-volumes configurations projects; do
                        if [[ -d "$BACKUP_DIR/encrypted/$type" ]] && [[ -n "$(ls -A "$BACKUP_DIR/encrypted/$type" 2>/dev/null)" ]]; then
                        decrypt_backup_dir "$type"
                        fi
                    done
                    ;;
                *)
                    decrypt_backup_dir "$backup_type"
                    ;;
            esac
            ;;
        encrypt-file)
            encrypt_file "$2" "$3"
            ;;
        decrypt-file)
            decrypt_file "$2" "$3"
            ;;
        encrypt-gpg)
            encrypt_with_gpg "$2" "$3"
            ;;
        *)
            error "Unknown action: $action"
            echo "Usage: $0 [encrypt|decrypt|encrypt-file|decrypt-file|encrypt-gpg] [backup_type|file1 file2]"
            exit 1
            ;;
    esac
    
    log "=========================================="
    log "Backup Encryption Completed"
    log "=========================================="
    
    exit 0
}

# Run main function
main "$@"