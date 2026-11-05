#!/bin/bash
set -euo pipefail

# Disk Space Check Script
# Monitors disk usage and alerts on low space

CRITICAL_THRESHOLD=90
WARNING_THRESHOLD=80
# This unit runs as deon, which cannot write /var/log, so every single log line
# came back as "tee: /var/log/disk-space-check.log: Permission denied" and the
# real output was buried in it. And the assignment was duplicated verbatim, which
# is why the wrong value survived the first one being wrong.
#
# Under a root-run unit /var/log would be right, so this stays overridable rather
# than hardcoding a home-directory path.
LOG_FILE="${DISK_SPACE_LOG:-${XDG_STATE_HOME:-$HOME/.local/state}/disk-space-check.log}"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

log() {
    # tee -a fails when the log directory is missing or unwritable. That is not a
    # reason to abandon the run: the caller's output has already gone to stdout
    # and is collected by journald, which is where this is actually read from.
    mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
    echo "[$TIMESTAMP] $1" | tee -a "$LOG_FILE" 2>/dev/null || echo "[$TIMESTAMP] $1"
}

# Get disk usage for a mount point
get_disk_usage() {
    local mount_point="$1"
    df "$mount_point" | tail -1 | awk '{print $5}' | sed 's/%//g'
}

# Get disk usage in human readable format
get_disk_usage_human() {
    local mount_point="$1"
    df -h "$mount_point" | tail -1 | awk '{print $4}'
}

# Get available space
get_available_space() {
    local mount_point="$1"
    df "$mount_point" | tail -1 | awk '{print $4}'
}

# Get inode usage
# btrfs does not track inode counts, so `df -i` prints "-" in the IUse% column
# rather than a number. The original version took $5 unfiltered and ran
# `[[ "" -ge 80 ]]`, so every scheduled run died on an arithmetic error -- under
# `set -euo pipefail` that aborted the script before the large-file scan, which
# is why the inode check silently never contributed anything.
#
# Return 0 for "-" and for anything non-numeric: on a filesystem that does not
# report inodes, inode exhaustion is not a real risk, so "0% used" is honest
# rather than a guess. The numeric comparison downstream is then always valid.
get_inode_usage() {
    local mount_point="$1"
    df -Pi "$mount_point" 2>/dev/null | tail -1 | awk '{print $5}' \
        | tr -dc '0-9' \
        | { read -r n || true; echo "${n:-0}"; }
}

# Find large files
find_large_files() {
    local size="${1:-100M}"
    log "Finding files larger than $size..."
    
    find /var/log -type f -size +"$size" -exec ls -lh {} \; 2>/dev/null | sort -k5 -r | head -10 || true
}

# Find large directories
find_large_directories() {
    local size="${1:-100M}"
    log "Finding directories larger than $size..."
    
    du -sh /* 2>/dev/null | sort -rh | head -10 || true
}

# Clean old logs

# Check Docker disk usage
check_docker_disk() {
    log "Checking Docker disk usage..."
    
    if command -v docker &> /dev/null; then
        local docker_usage
        docker_usage=$(docker system df 2>/dev/null | tail -5)
        log "$docker_usage"
        
        # Check for unused images
        local unused_images
        unused_images=$(docker images -f "dangling=true" -q 2>/dev/null)
        if [[ -n "$unused_images" ]]; then
            log "WARNING: Found unused Docker images:"
            echo "$unused_images" | while read -r img; do
                log "  - $img"
            done
        fi
    else
        log "INFO: Docker not installed"
    fi
}

# Main disk space check
main() {
    log "=========================================="
    log "Disk Space Check Started"
    log "=========================================="
    
    # Check root filesystem
    local root_usage
    root_usage=$(get_disk_usage "/")
    local root_available
    root_available=$(get_available_space "/")
    local root_human
    root_human=$(get_disk_usage_human "/")
    
    log "Root filesystem: ${root_human} (${root_usage}% used, ${root_available} available)"
    
    if [[ "$root_usage" -ge "$CRITICAL_THRESHOLD" ]]; then
        log "CRITICAL: Root filesystem is ${root_usage}% full"
        exit 2
    elif [[ "$root_usage" -ge "$WARNING_THRESHOLD" ]]; then
        log "WARNING: Root filesystem is ${root_usage}% full"
    else
        log "OK: Root filesystem usage is normal"
    fi
    
    # Check other mount points
    log ""
    log "Checking other filesystems..."
    
    for mount_point in /boot /var /home /tmp; do
        if mountpoint -q "$mount_point" 2>/dev/null; then
            local usage
            usage=$(get_disk_usage "$mount_point")
            local available
            available=$(get_available_space "$mount_point")
            local human
            human=$(get_disk_usage_human "$mount_point")
            
            log "  $mount_point: ${human} (${usage}% used, ${available} available)"
            
            if [[ "$usage" -ge "$CRITICAL_THRESHOLD" ]]; then
                log "  CRITICAL: $mount_point is ${usage}% full"
            elif [[ "$usage" -ge "$WARNING_THRESHOLD" ]]; then
                log "  WARNING: $mount_point is ${usage}% full"
            fi
        fi
    done
    
    # Check inode usage
    local root_inodes
    root_inodes=$(get_inode_usage "/")
    log ""
    log "Root inode usage: ${root_inodes}%"
    
    if [[ "$root_inodes" -ge "$CRITICAL_THRESHOLD" ]]; then
        log "CRITICAL: Root inode table is ${root_inodes}% full"
        exit 2
    elif [[ "$root_inodes" -ge "$WARNING_THRESHOLD" ]]; then
        log "WARNING: Root inode table is ${root_inodes}% full"
    fi
    
    # Find large files
    log ""
    log "Large files (>100M) in /var/log:"
    find_large_files "100M"
    
    # Find large directories
    log ""
    log "Largest directories:"
    find_large_directories "100M"
    
    # Check Docker
    check_docker_disk
    
    log "=========================================="
    log "Disk Space Check Completed"
    log "=========================================="
    
    exit 0
}

# Run main function
main "$@"