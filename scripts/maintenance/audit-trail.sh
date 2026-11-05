#!/bin/bash
set -euo pipefail

# Audit Trail Script
# Generates centralized audit logs for system activities

if [ -w "$(dirname /var/log/audit 2>/dev/null)" ]; then
    LOG_DIR="/var/log/audit"
else
    LOG_DIR="/tmp/audit"
fi
AUDIT_LOG="$LOG_DIR/audit.log"
TIMESTAMP_ISO=$(date -Iseconds)

log() {
    echo "[$TIMESTAMP_ISO] $1" | tee -a "$AUDIT_LOG"
}

error() {
    echo "[$TIMESTAMP_ISO] ERROR: $1" | tee -a "$AUDIT_LOG" >&2
}

# Initialize audit directory
init_audit() {
    mkdir -p "$LOG_DIR"
    chmod 750 "$LOG_DIR"
    chown root:audit "$LOG_DIR" 2>/dev/null || true
    
    # Create audit log if not exists
    if [[ ! -f "$AUDIT_LOG" ]]; then
        touch "$AUDIT_LOG"
        chmod 640 "$AUDIT_LOG"
        chown root:audit "$AUDIT_LOG" 2>/dev/null || true
    fi
}

# Log authentication events
log_authentication() {
    local event="$1"
    local user="$2"
    local host="$3"
    
    log "AUTH: $event - User: $user - Host: $host"
}

# Log sudo commands
log_sudo() {
    local user="$1"
    local command="$2"
    
    log "SUDO: User '$user' executed: $command"
}

# Log file access
log_file_access() {
    local file="$1"
    local action="$2"  # read, write, execute
    local user="$3"
    
    log "FILE: $action - File: $file - User: $user"
}

# Log configuration changes
log_config_change() {
    local config_file="$1"
    local change_type="$2"  # create, modify, delete
    local user="$3"
    
    log "CONFIG: $change_type - File: $config_file - User: $user"
}

# Log process execution
log_process() {
    local process="$1"
    local pid="$2"
    local user="$3"
    
    log "PROCESS: Started '$process' (PID: $pid) - User: $user"
}

# Log service events
log_service() {
    local service="$1"
    local action="$2"  # start, stop, restart, fail
    local user="$3"
    
    log "SERVICE: $action - Service: $service - User: $user"
}

# Log network connections
log_network() {
    local action="$1"  # connect, disconnect, port_open
    local source="$2"
    local dest="$3"
    local port="$4"
    
    log "NETWORK: $action - Source: $source - Dest: $dest:$port"
}

# Log security events
log_security() {
    local event="$1"
    local severity="$2"  # info, warning, critical
    local details="$3"
    
    log "SECURITY: [$severity] $event - Details: $details"
}

# Generate audit report
generate_report() {
    local report_type="${1:-daily}"
    local start_date
    start_date="${2:-$(date -d '1 day ago' +%Y-%m-%d)}"
    local end_date
    end_date="${3:-$(date +%Y-%m-%d)}"
    
    log "=========================================="
    log "Audit Report Generated"
    log "Type: $report_type"
    log "Period: $start_date to $end_date"
    log "=========================================="
    
    # Generate report based on type
    case "$report_type" in
        daily)
            log "Daily Audit Report"
            ;;
        weekly)
            log "Weekly Audit Report"
            ;;
        monthly)
            log "Monthly Audit Report"
            ;;
        custom)
            log "Custom Period Audit Report"
            ;;
    esac
    
    # Log summary statistics
    local total_events
    total_events=$(wc -l < "$AUDIT_LOG" 2>/dev/null || echo 0)
    local auth_events
    # shellcheck disable=SC2126  # grep -c exits 1 on no match; would abort under set -e
    auth_events=$(grep "^AUTH:" "$AUDIT_LOG" 2>/dev/null | wc -l || true)
    local sudo_events
    # shellcheck disable=SC2126  # grep -c exits 1 on no match; would abort under set -e
    sudo_events=$(grep "^SUDO:" "$AUDIT_LOG" 2>/dev/null | wc -l || true)
    local security_events
    # shellcheck disable=SC2126  # grep -c exits 1 on no match; would abort under set -e
    security_events=$(grep "^SECURITY:" "$AUDIT_LOG" 2>/dev/null | wc -l || true)
    
    log "Total Events: $total_events"
    log "Authentication Events: $auth_events"
    log "Sudo Events: $sudo_events"
    log "Security Events: $security_events"
    
    log "=========================================="
}

# Clear old audit logs
rotate_logs() {
    local retention_days="${1:-30}"
    
    log "Rotating audit logs (retention: $retention_days days)"
    
    find "$LOG_DIR" -name "*.log.*" -type f -mtime +"$retention_days" -delete 2>/dev/null || true
    log "Log rotation completed"
}

# Main function
main() {
    local action="${1:-log}"
    local event_type="${2:-}"
    local details="${3:-}"
    
    init_audit
    
    log "=========================================="
    log "Audit Trail Started"
    log "Action: $action"
    log "=========================================="
    
    case "$action" in
        log-auth)
            log_authentication "$event_type" "$details"
            ;;
        log-sudo)
            log_sudo "${details%% *}" "${details#* }"
            ;;
        log-file)
            log_file_access "$details" "${event_type:-read}" "${user:-unknown}"
            ;;
        log-config)
            log_config_change "$details" "${event_type:-modify}" "${user:-unknown}"
            ;;
        log-process)
            log_process "$details" "${event_type:-1}" "${user:-unknown}"
            ;;
        log-service)
            log_service "$details" "${event_type:-start}" "${user:-unknown}"
            ;;
        log-network)
            log_network "$event_type" "$details" "${event_type:-unknown}"
            ;;
        log-security)
            log_security "$details" "${event_type:-info}" "${details}"
            ;;
        report)
            generate_report "$event_type" "${details:-}" "${details:-}"
            ;;
        rotate)
            rotate_logs "$details"
            ;;
        *)
            error "Unknown action: $action"
            echo "Usage: $0 [log-auth|log-sudo|log-file|log-config|log-process|log-service|log-network|log-security|report|rotate] [details]"
            exit 1
            ;;
    esac
    
    log "=========================================="
    log "Audit Trail Completed"
    log "=========================================="
    
    exit 0
}

# Run main function
main "$@"