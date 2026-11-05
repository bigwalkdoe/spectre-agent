#!/bin/bash
set -euo pipefail

# Off-Site Backup Setup Script
# Configures rsync/S3/B2 remote backup destinations

CONFIG_DIR="/etc/spectre-suite"
BACKUP_CONFIG="${CONFIG_DIR}/backup-config.yml"
LOG_FILE="/var/log/backup-setup.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log "ERROR: This script must be run as root"
        exit 1
    fi
}

install_deps() {
    log "Installing dependencies..."
    if command -v apt-get &>/dev/null; then
        apt-get update && apt-get install -y rsync rclone restic awscli
    elif command -v dnf &>/dev/null; then
        dnf install -y rsync rclone restic awscli
    elif command -v yum &>/dev/null; then
        yum install -y epel-release && yum install -y rsync rclone restic awscli
    elif command -v pacman &>/dev/null; then
        pacman -S --noconfirm rsync rclone restic aws-cli
    fi
}

setup_rsync() {
    log "Setting up rsync backup..."
    read -rp "Remote rsync host (user@host): " RSYNC_HOST
    read -rp "Remote backup path: " RSYNC_PATH
    read -rp "SSH port [22]: " RSYNC_PORT
    RSYNC_PORT=${RSYNC_PORT:-22}
    
    cat >> "$BACKUP_CONFIG" <<EOF

# Rsync off-site backup
remote_backup:
  enabled: true
  type: "rsync"
  host: "${RSYNC_HOST}"
  path: "${RSYNC_PATH}"
  port: ${RSYNC_PORT}
  options: "-avz --delete --progress"
  schedule: "0 4 * * *"
EOF
    
    log "Testing SSH connection..."
    if ssh -p "$RSYNC_PORT" -o BatchMode=yes -o ConnectTimeout=10 "$RSYNC_HOST" "mkdir -p '$RSYNC_PATH'"; then
        log "Rsync destination configured successfully"
    else
        log "WARNING: SSH connection failed. Set up key-based auth manually."
    fi
}

setup_s3() {
    log "Setting up AWS S3 backup..."
    read -rp "S3 bucket name: " S3_BUCKET
    read -rp "AWS region [us-east-1]: " S3_REGION
    S3_REGION=${S3_REGION:-us-east-1}
    read -rp "AWS access key ID: " AWS_ACCESS_KEY_ID
    read -rsp "AWS secret access key: " AWS_SECRET_ACCESS_KEY
    echo
    
    cat >> "$BACKUP_CONFIG" <<EOF

# S3 off-site backup
remote_backup:
  enabled: true
  type: "s3"
  bucket: "${S3_BUCKET}"
  region: "${S3_REGION}"
  access_key_id: "${AWS_ACCESS_KEY_ID}"
  secret_access_key: "${AWS_SECRET_ACCESS_KEY}"
  prefix: "backups/"
  schedule: "0 4 * * *"
EOF
    
    if aws s3 ls "s3://${S3_BUCKET}" >/dev/null 2>&1; then
        log "S3 bucket accessible"
    else
        log "WARNING: Cannot access S3 bucket. Check credentials."
    fi
}

setup_b2() {
    log "Setting up Backblaze B2 backup..."
    read -rp "B2 bucket name: " B2_BUCKET
    read -rp "B2 key ID: " B2_KEY_ID
    read -rsp "B2 application key: " B2_APP_KEY
    echo
    
    cat >> "$BACKUP_CONFIG" <<EOF

# B2 off-site backup
remote_backup:
  enabled: true
  type: "b2"
  bucket: "${B2_BUCKET}"
  key_id: "${B2_KEY_ID}"
  application_key: "${B2_APP_KEY}"
  prefix: "backups/"
  schedule: "0 4 * * *"
EOF
    
    if rclone lsd "b2:${B2_BUCKET}" >/dev/null 2>&1; then
        log "B2 bucket accessible"
    else
        log "WARNING: Cannot access B2 bucket. Run 'rclone config' to set up."
    fi
}

setup_rclone() {
    log "Setting up generic rclone remote..."
    read -rp "Rclone remote name: " RCLONE_REMOTE
    read -rp "Remote path (remote:path): " RCLONE_PATH
    
    cat >> "$BACKUP_CONFIG" <<EOF

# Generic rclone backup
remote_backup:
  enabled: true
  type: "rclone"
  remote: "${RCLONE_REMOTE}"
  path: "${RCLONE_PATH}"
  schedule: "0 4 * * *"
EOF
}

create_backup_script() {
    log "Creating off-site backup script..."
    cat > /usr/local/bin/backup-offsite.sh <<'SCRIPT'
#!/bin/bash
set -euo pipefail

CONFIG_FILE="/etc/spectre-suite/backup-config.yml"
BACKUP_DIR="/backups"
LOG_FILE="/var/log/backup-offsite.log"
TIMESTAMP=$(date '+%Y-%m-%d_%H-%M-%S')

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

load_config() {
    if [[ ! -f "$CONFIG_FILE" ]]; then
        log "ERROR: Config file not found: $CONFIG_FILE"
        exit 1
    fi
    eval $(python3 -c "
import yaml, sys
with open('$CONFIG_FILE') as f:
    config = yaml.safe_load(f)
rb = config.get('remote_backup', {})
if rb.get('enabled'):
    for k, v in rb.items():
        if isinstance(v, str):
            print(f'export RB_{k.upper()}=\"{v}\"')
        else:
            print(f'export RB_{k.upper()}={v}')
")
}

run_rsync() {
    log "Starting rsync backup to ${RB_HOST}:${RB_PATH}"
    rsync ${RB_OPTIONS} -e "ssh -p ${RB_PORT}" \
        "$BACKUP_DIR/" "${RB_HOST}:${RB_PATH}/" \
        2>&1 | tee -a "$LOG_FILE"
    log "Rsync backup completed"
}

run_s3() {
    log "Starting S3 backup to s3://${RB_BUCKET}/${RB_PREFIX}"
    AWS_ACCESS_KEY_ID="$RB_ACCESS_KEY_ID" \
    AWS_SECRET_ACCESS_KEY="$RB_SECRET_ACCESS_KEY" \
    aws s3 sync "$BACKUP_DIR/" "s3://${RB_BUCKET}/${RB_PREFIX}/" \
        --region "$RB_REGION" --delete \
        2>&1 | tee -a "$LOG_FILE"
    log "S3 backup completed"
}

run_b2() {
    log "Starting B2 backup to b2://${RB_BUCKET}/${RB_PREFIX}"
    rclone sync "$BACKUP_DIR/" "b2:${RB_BUCKET}/${RB_PREFIX}" \
        --b2-key-id "$RB_KEY_ID" \
        --b2-application-key "$RB_APPLICATION_KEY" \
        --progress 2>&1 | tee -a "$LOG_FILE"
    log "B2 backup completed"
}

run_rclone() {
    log "Starting rclone backup to ${RB_REMOTE}:${RB_PATH}"
    rclone sync "$BACKUP_DIR/" "${RB_REMOTE}:${RB_PATH}" --progress \
        2>&1 | tee -a "$LOG_FILE"
    log "Rclone backup completed"
}

main() {
    load_config
    
    case "${RB_TYPE}" in
        rsync) run_rsync ;;
        s3) run_s3 ;;
        b2) run_b2 ;;
        rclone) run_rclone ;;
        *) log "ERROR: Unknown backup type: ${RB_TYPE}"; exit 1 ;;
    esac
    
    log "Off-site backup completed successfully"
}

main "$@"
SCRIPT
    chmod +x /usr/local/bin/backup-offsite.sh
}

setup_cron() {
    # The schedule is fixed at 0 4 * * *, matching the schedule: entries written
    # into the config above. This previously accepted an optional $1 that no
    # caller ever passed, so the parameter was dead (shellcheck SC2120).
    local schedule="0 4 * * *"
    log "Setting up cron job: $schedule"
    (crontab -l 2>/dev/null | grep -v "backup-offsite.sh"; echo "$schedule root /usr/local/bin/backup-offsite.sh") | crontab -
}

main() {
    check_root
    mkdir -p "$CONFIG_DIR"
    
    cat > "$BACKUP_CONFIG" <<EOF
# Off-site backup configuration
# Generated by setup-offsite-backup.sh on $(date)

EOF
    
    echo "Select backup destination:"
    echo "  1) rsync (SSH)"
    echo "  2) AWS S3"
    echo "  3) Backblaze B2"
    echo "  4) Generic rclone"
    read -rp "Choice [1-4]: " choice
    
    install_deps
    
    case "$choice" in
        1) setup_rsync ;;
        2) setup_s3 ;;
        3) setup_b2 ;;
        4) setup_rclone ;;
        *) log "Invalid choice"; exit 1 ;;
    esac
    
    create_backup_script
    setup_cron
    
    log "Off-site backup configured!"
    log "Config: $BACKUP_CONFIG"
    log "Script: /usr/local/bin/backup-offsite.sh"
    log "Test run: /usr/local/bin/backup-offsite.sh"
}

main "$@"