#!/bin/bash
set -euo pipefail

# Performance Check Script
# Monitors system performance metrics and alerts on anomalies

LOG_FILE="/var/log/performance-check.log"
ALERT_THRESHOLD_CPU=80
ALERT_THRESHOLD_MEMORY=80
ALERT_THRESHOLD_DISK=85
LOGICAL volumes="/var/log/performance-check.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

log() {
    echo "[$TIMESTAMP] $1" | tee -a "$LOG_FILE" || true
}

# Get CPU usage
get_cpu_usage() {
    local cpu_usage
    cpu_usage=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)
    echo "${cpu_usage:-0}"
}

# Get memory usage
get_memory_usage() {
    local mem_info
    mem_info=$(free | grep Mem)
    local total
    total=$(echo "$mem_info" | awk '{print $2}')
    local used
    used=$(echo "$mem_info" | awk '{print $3}')
    local usage
    usage=$(echo "scale=2; $used * 100 / $total" | bc)
    echo "${usage:-0}"
}

# Get disk usage
get_disk_usage() {
    local disk_usage
    disk_usage=$(df / | tail -1 | awk '{print $5}' | sed 's/%//')
    echo "${disk_usage:-0}"
}

# Get load average
get_load_average() {
    local load
    load=$(cat /proc/loadavg | awk '{print $1}')
    echo "${load:-0}"
}

# Get active processes
get_active_processes() {
    local count
    count=$(ps aux --no-headers | wc -l)
    echo "${count:-0}"
}

# Check swap usage
get_swap_usage() {
    local swap_info
    swap_info=$(free | grep Swap)
    local total
    total=$(echo "$swap_info" | awk '{print $2}')
    local used
    used=$(echo "$swap_info" | awk '{print $3}')
    local usage=0
    if [[ "$total" -gt 0 ]]; then
        usage=$(echo "scale=2; $used * 100 / $total" | bc)
    fi
    echo "${usage:-0}"
}

# Get top consuming processes
get_top_processes() {
    echo "=== Top CPU Consumers ==="
    ps aux --sort=-%cpu | head -6 | awk '{printf "  %-45s %5.1f%%\n", $11, $3}'
    
    echo ""
    echo "=== Top Memory Consumers ==="
    ps aux --sort=-%mem | head -6 | awk '{printf "  %-45s %5.1f%%\n", $11, $4}'
}

# Get container stats
get_container_stats() {
    if command -v docker &> /dev/null; then
        echo "=== Docker Container Stats ==="
        docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" 2>/dev/null || echo "  Docker not running or no containers"
    else
        echo "  Docker not installed"
    fi
}

# Main performance check
main() {
    log "=========================================="
    log "Performance Check Started"
    log "=========================================="
    
    # Gather metrics
    local cpu_usage
    cpu_usage=$(get_cpu_usage)
    local memory_usage
    memory_usage=$(get_memory_usage)
    local disk_usage
    disk_usage=$(get_disk_usage)
    local load_avg
    load_avg=$(get_load_average)
    local active_procs
    active_procs=$(get_active_processes)
    local swap_usage
    swap_usage=$(get_swap_usage)
    
    log "CPU Usage: ${cpu_usage}%"
    log "Memory Usage: ${memory_usage}%"
    log "Disk Usage: ${disk_usage}%"
    log "Load Average: $load_avg"
    log "Active Processes: $active_procs"
    log "Swap Usage: ${swap_usage}%"
    
    # Check thresholds
    local alerts=0
    
    if (( $(echo "$cpu_usage > $ALERT_THRESHOLD_CPU" | bc -l) )); then
        log "WARNING: CPU usage ${cpu_usage}% exceeds threshold ${ALERT_THRESHOLD_CPU}%"
        alerts=$((alerts + 1))
    else
        log "OK: CPU usage within normal range (${cpu_usage}%)"
    fi
    
    if (( $(echo "$memory_usage > $ALERT_THRESHOLD_MEMORY" | bc -l) )); then
        log "WARNING: Memory usage ${memory_usage}% exceeds threshold ${ALERT_THRESHOLD_MEMORY}%"
        alerts=$((alerts + 1))
    else
        log "OK: Memory usage within normal range (${memory_usage}%)"
    fi
    
    if (( disk_usage > ALERT_THRESHOLD_DISK )); then
        log "WARNING: Disk usage ${disk_usage}% exceeds threshold ${ALERT_THRESHOLD_DISK}%"
        alerts=$((alerts + 1))
    else
        log "OK: Disk usage within normal range (${disk_usage}%)"
    fi
    
    # Get detailed stats
    get_top_processes
    get_container_stats
    
    log "=========================================="
    if [[ $alerts -gt 0 ]]; then
        log "Performance Check Completed: $alerts alert(s)"
        exit 1
    else
        log "Performance Check Completed: All metrics normal"
        exit 0
    fi
}

# Run main function
main "$@"