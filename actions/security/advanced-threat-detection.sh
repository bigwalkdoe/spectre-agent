#!/bin/bash
set -euo pipefail
# Advanced Threat Detection Script
# Implements sophisticated threat detection and automated response

# Source distribution detection
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
# shellcheck disable=SC1091  # resolved at runtime
source "$PROJECT_ROOT/detect-distribution.sh"

# Initialize distribution settings
detect_distribution
set_package_manager

echo "Starting Advanced Threat Detection for $DISTRO_NAME..."

# Configuration
LOG_DIR="/var/log/security"
ALERT_LOG="$LOG_DIR/threat-alerts.log"
MONITOR_LOG="$LOG_DIR/threat-monitoring.log"
QUARANTINE_DIR="/var/quarantine"
THRESHOLD_FILE="$LOG_DIR/baselines.txt"

# Create necessary directories
sudo mkdir -p "$LOG_DIR" "$QUARANTINE_DIR"
sudo touch "$ALERT_LOG" "$MONITOR_LOG" "$THRESHOLD_FILE"

# Baseline establishment
establish_baseline() {
    echo "Establishing security baselines..."
    
    # Network baseline
    sudo netstat -tuln | sudo tee "$THRESHOLD_FILE.network.tmp" >/dev/null
    sudo ss -tuln | sudo tee -a "$THRESHOLD_FILE.network.tmp" >/dev/null
    
    # Process baseline
    ps aux > "$THRESHOLD_FILE.process.tmp"
    
    # File system baseline (critical directories)
    sudo find /etc /usr/bin /usr/sbin -type f \( -perm -4000 -o -perm -2000 \) | sudo tee "$THRESHOLD_FILE.suid.tmp" >/dev/null
    
    # User baseline
    cat /etc/passwd > "$THRESHOLD_FILE.users.tmp"
    cat /etc/group > "$THRESHOLD_FILE.groups.tmp"
    
    echo "Baselines established at $(date)" | sudo tee -a "$THRESHOLD_FILE"
    
    # Combine baselines
    sudo mv "$THRESHOLD_FILE".*.tmp "$THRESHOLD_FILE".* 2>/dev/null || true
}

# Anomaly detection
detect_network_anomalies() {
    echo "Detecting network anomalies..."
    
    local alerts=0
    
    # Check for unusual open ports
    local current_ports
    current_ports=$(sudo netstat -tuln | awk '{print $4}' | grep -E ':[0-9]+' | cut -d: -f2 | sort -u)
    local baseline_ports
    baseline_ports=$(cat "$THRESHOLD_FILE.network" 2>/dev/null | awk '{print $4}' | grep -E ':[0-9]+' | cut -d: -f2 | sort -u)
    
    # Check for new ports
    for port in $current_ports; do
        if ! echo "$baseline_ports" | grep -q "^$port$"; then
            echo "ALERT: New port open - $port" | sudo tee -a "$ALERT_LOG"
            ((alerts++))
        fi
    done
    
    # Check for suspicious connections
    local suspicious
    suspicious=$(sudo netstat -an | grep ESTABLISHED | awk '{print $5}' | cut -d: -f1 | sort | uniq -c | sort -rn | head -5)
    local suspicious_total
    suspicious_total=$(echo "$suspicious" | awk '{sum+=$1} END {print sum+0}')
    if [ "${suspicious_total:-0}" -gt 100 ]; then
        echo "ALERT: High number of connections from single IPs" | sudo tee -a "$ALERT_LOG"
        ((alerts++))
    fi
    
    # Check for connections to known bad IPs (basic list)
    local bad_ips="192.168.1.100 10.0.0.50" # Example - should use real threat intelligence
    for ip in $bad_ips; do
        if sudo netstat -an | grep -q "$ip"; then
            echo "ALERT: Connection to known bad IP - $ip" | sudo tee -a "$ALERT_LOG"
            ((alerts++))
        fi
    done
    
    return $alerts
}

# Process anomaly detection
detect_process_anomalies() {
    echo "Detecting process anomalies..."
    
    local alerts=0
    
    # Check for processes with high CPU usage
    local high_cpu
    high_cpu=$(ps aux --sort=-%cpu | head -10 | awk '{if ($3 > 80) print}')
    if [ -n "$high_cpu" ]; then
        echo "WARNING: Processes with high CPU usage detected" | sudo tee -a "$ALERT_LOG"
        echo "$high_cpu" | sudo tee -a "$ALERT_LOG"
        ((alerts++))
    fi
    
    # Check for processes with high memory usage
    local high_mem
    high_mem=$(ps aux --sort=-%mem | head -10 | awk '{if ($4 > 80) print}')
    if [ -n "$high_mem" ]; then
        echo "WARNING: Processes with high memory usage detected" | sudo tee -a "$ALERT_LOG"
        echo "$high_mem" | sudo tee -a "$ALERT_LOG"
        ((alerts++))
    fi
    
    # Check for suspicious process names
    local suspicious_names="reverse_shell backdoor keylogger malware"
    for name in $suspicious_names; do
        if pgrep -f "$name" >/dev/null 2>&1; then
            echo "ALERT: Suspicious process detected - $name" | sudo tee -a "$ALERT_LOG"
            ((alerts++))
        fi
    done
    
    # Check for processes with no executable path
    local no_path
    no_path=$(ps aux | awk '{if ($11 == "" || $11 == "?" && $2 != 1 && $2 != 2) print}')
    if [ -n "$no_path" ]; then
        echo "WARNING: Processes with no executable path detected" | sudo tee -a "$ALERT_LOG"
        echo "$no_path" | sudo tee -a "$ALERT_LOG"
        ((alerts++))
    fi
    
    return $alerts
}

# File system integrity monitoring
monitor_file_integrity() {
    echo "Monitoring file system integrity..."
    
    local alerts=0
    
    # Check for new SUID/SGID files
    local current_suid
    current_suid=$(sudo find /etc /usr/bin /usr/sbin -type f \( -perm -4000 -o -perm -2000 \) 2>/dev/null)
    local baseline_suid
    baseline_suid=$(cat "$THRESHOLD_FILE.suid" 2>/dev/null)
    
    if [ "$current_suid" != "$baseline_suid" ]; then
        echo "ALERT: SUID/SGID files have changed!" | sudo tee -a "$ALERT_LOG"
        echo "Current SUID files:" | sudo tee -a "$ALERT_LOG"
        echo "$current_suid" | sudo tee -a "$ALERT_LOG"
        ((alerts++))
    fi
    
    # Check for changes in critical configuration files
    local critical_files="/etc/passwd /etc/shadow /etc/group /etc/sudoers /etc/ssh/sshd_config"
    for file in $critical_files; do
        if [ -f "$file" ]; then
            local checksum
            checksum=$(sudo md5sum "$file" | awk '{print $1}')
            local baseline_checksum
            baseline_checksum=$(grep "$file" "$THRESHOLD_FILE.checksums" 2>/dev/null | awk '{print $2}')
            
            if [ "$checksum" != "$baseline_checksum" ] && [ -n "$baseline_checksum" ]; then
                echo "ALERT: Critical file changed - $file" | sudo tee -a "$ALERT_LOG"
                ((alerts++))
            fi
        fi
    done
    
    # Check for new files in suspicious locations
    local suspicious_dirs="/tmp /var/tmp /dev/shm"
    for dir in $suspicious_dirs; do
        local new_files
        new_files=$(sudo find "$dir" -type f -mmin -60 2>/dev/null)
        if [ -n "$new_files" ]; then
            echo "WARNING: New files in suspicious directory - $dir" | sudo tee -a "$ALERT_LOG"
            echo "$new_files" | sudo tee -a "$ALERT_LOG"
            ((alerts++))
        fi
    done
    
    return $alerts
}

# Log analysis
analyze_logs() {
    echo "Analyzing system logs..."
    
    local alerts=0
    
    # Check for failed login attempts
    local failed_logins
    failed_logins=$(sudo grep "Failed password" /var/log/auth.log /var/log/secure 2>/dev/null | tail -100 | wc -l)
    if [ "$failed_logins" -gt 10 ]; then
        echo "ALERT: High number of failed login attempts - $failed_logins" | sudo tee -a "$ALERT_LOG"
        ((alerts++))
    fi
    
    # Check for sudo usage
    local sudo_usage
    sudo_usage=$(sudo grep "sudo:" /var/log/auth.log /var/log/secure 2>/dev/null | tail -50)
    if [ -n "$sudo_usage" ]; then
        echo "INFO: Recent sudo activity" | sudo tee -a "$MONITOR_LOG"
        echo "$sudo_usage" | sudo tee -a "$MONITOR_LOG"
    fi
    
    # Check for kernel errors
    local kernel_errors
    kernel_errors=$(sudo dmesg | grep -i "error\|fail" | tail -20)
    if [ -n "$kernel_errors" ]; then
        echo "WARNING: Kernel errors detected" | sudo tee -a "$ALERT_LOG"
        echo "$kernel_errors" | sudo tee -a "$ALERT_LOG"
        ((alerts++))
    fi
    
    # Check for unusual system calls (using auditd if available)
    if command -v aureport >/dev/null 2>&1; then
        local audit_failures
        audit_failures=$(sudo aureport --failed 2>/dev/null | tail -20)
        if [ -n "$audit_failures" ]; then
            echo "WARNING: Audit system failures detected" | sudo tee -a "$ALERT_LOG"
            echo "$audit_failures" | sudo tee -a "$ALERT_LOG"
            ((alerts++))
        fi
    fi
    
    return $alerts
}

# Automated threat response
automated_response() {
    local threat_level=$1
    
    case $threat_level in
        1) # Low threat
            echo "Low threat level - logging only"
            ;;
        2) # Medium threat
            echo "Medium threat level - blocking suspicious IPs"
            # Add IP blocking logic here
            ;;
        3) # High threat
            echo "High threat level - activating incident response"
            # Activate incident response procedures
            # Send alerts, lock down system, preserve evidence
            ;;
    esac
}

# Main monitoring loop
main_monitoring() {
    echo "Starting continuous threat monitoring..."
    echo "Monitoring started at $(date)" | sudo tee -a "$MONITOR_LOG"
    
    local total_alerts=0
    
    # Establish baselines if not exists
    if [ ! -f "$THRESHOLD_FILE" ]; then
        establish_baseline
    fi
    
    # Run detection modules
    detect_network_anomalies
    ((total_alerts += $?))
    
    detect_process_anomalies
    ((total_alerts += $?))
    
    monitor_file_integrity
    ((total_alerts += $?))
    
    analyze_logs
    ((total_alerts += $?))
    
    # Determine threat level
    local threat_level=1
    if [ $total_alerts -gt 5 ]; then
        threat_level=2
    elif [ $total_alerts -gt 10 ]; then
        threat_level=3
    fi
    
    # Automated response
    automated_response $threat_level
    
    echo "Monitoring cycle completed. Total alerts: $total_alerts, Threat level: $threat_level" | sudo tee -a "$MONITOR_LOG"
    echo "Monitoring completed at $(date)" | sudo tee -a "$MONITOR_LOG"
    
    return $total_alerts
}

# Report generation
generate_report() {
    echo "Generating threat detection report..."
    
    local report_file
    report_file="/tmp/threat-report-$(date +%Y%m%d-%H%M%S).txt"
    
    cat > "$report_file" << EOF
THREAT DETECTION REPORT
========================
Date: $(date)
Hostname: $(hostname)
Distribution: $DISTRO_NAME

ALERT SUMMARY
-------------
Total alerts: $(wc -l < "$ALERT_LOG")
Recent alerts:
$(tail -20 "$ALERT_LOG")

MONITORING SUMMARY
------------------
$(tail -50 "$MONITOR_LOG")

BASELINE STATUS
---------------
Baseline file: $THRESHOLD_FILE
Last updated: $(stat -c %y "$THRESHOLD_FILE" 2>/dev/null || echo "N/A")

RECOMMENDATIONS
---------------
1. Review all alerts in detail
2. Update baselines if changes are expected
3. Investigate any suspicious activity
4. Review and update threat detection rules
EOF
    
    echo "Report generated: $report_file"
    cat "$report_file"
}

# Command line argument handling
case "${1:-monitor}" in
    baseline)
        establish_baseline
        ;;
    monitor)
        main_monitoring
        ;;
    report)
        generate_report
        ;;
    continuous)
        while true; do
            main_monitoring
            sleep 300 # 5 minutes
        done
        ;;
    *)
        echo "Usage: $0 {baseline|monitor|report|continuous}"
        echo "  baseline  - Establish security baselines"
        echo "  monitor   - Run threat detection scan"
        echo "  report    - Generate threat detection report"
        echo "  continuous - Run continuous monitoring"
        exit 1
        ;;
esac
