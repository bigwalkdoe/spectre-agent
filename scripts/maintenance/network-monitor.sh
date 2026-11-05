#!/bin/bash
set -euo pipefail

# Network Monitor Script
# Monitors network connectivity and performance

LOG_FILE="/var/log/network-monitor.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
PING_TIMEOUT=3
PING_COUNT=3

log() {
    echo "[$TIMESTAMP] $1" | tee -a "$LOG_FILE" || true
}

# Check internet connectivity
check_internet() {
    log "Checking internet connectivity..."
    
    if ping -c "$PING_COUNT" -W "$PING_TIMEOUT" 8.8.8.8 > /dev/null 2>&1; then
        log "OK: Internet connectivity OK"
        return 0
    else
        log "WARNING: Internet connectivity check failed"
        return 1
    fi
}

# Check DNS resolution
check_dns() {
    log "Checking DNS resolution..."
    
    local dns_servers_str="${DNS_SERVERS:-8.8.8.8 8.8.4.4 1.1.1.1}"
    local -a dns_servers
    read -r -a dns_servers <<< "$dns_servers_str"
    
    for dns in "${dns_servers[@]}"; do
        if nslookup google.com "$dns" > /dev/null 2>&1; then
            log "OK: DNS server $dns is responding"
            return 0
        fi
    done
    
    log "WARNING: All DNS servers failed to respond"
    return 1
}

# Check port connectivity
check_port() {
    local host="$1"
    local port="$2"
    
    log "Checking port $port on $host..."
    
    if nc -z -w 2 "$host" "$port" 2>/dev/null; then
        log "OK: Port $port on $host is open"
        return 0
    else
        log "WARNING: Port $port on $host is closed or unreachable"
        return 1
    fi
}

# Check Docker network
check_docker_network() {
    log "Checking Docker network..."
    
    if command -v docker &> /dev/null; then
        if docker network ls > /dev/null 2>&1; then
            log "OK: Docker network is operational"
            return 0
        else
            log "WARNING: Docker network check failed"
            return 1
        fi
    else
        log "INFO: Docker not installed, skipping Docker network check"
        return 0
    fi
}

# Check firewall status
check_firewall() {
    log "Checking firewall status..."
    
    if command -v ufw &> /dev/null; then
        local status
        status=$(ufw status | grep Status | awk '{print $2}')
        if [[ "$status" == "active" ]]; then
            log "OK: UFW firewall is active"
            return 0
        else
            log "WARNING: UFW firewall is not active"
            return 1
        fi
    elif command -v firewall-cmd &> /dev/null; then
        local status
        status=$(firewall-cmd --state 2>/dev/null || echo "inactive")
        if [[ "$status" == "running" ]]; then
            log "OK: firewalld is active"
            return 0
        else
            log "WARNING: firewalld is not active"
            return 1
        fi
    else
        log "INFO: No firewall detected"
        return 0
    fi
}

# Check network interface
check_network_interface() {
    log "Checking network interface..."
    
    if command -v ip &> /dev/null; then
        local interfaces
        interfaces=$(ip addr show | grep "inet " | grep -v "127.0.0.1" | awk '{print $2}' | cut -d/ -f1)
        
        for iface in $interfaces; do
            local speed
            speed=$(ip link show "$iface" 2>/dev/null | grep -oP 'speed \K\d+' || echo "unknown")
            log "OK: Interface $iface is up (speed: ${speed}Mbit)"
        done
    else
        log "INFO: IP command not available"
        return 0
    fi
}

# Check bandwidth usage
check_bandwidth() {
    log "Checking bandwidth usage..."
    
    if command -v nload &> /dev/null; then
        nload -s 2>/dev/null | head -5
    elif command -v iftop &> /dev/null; then
        iftop -n -P -c 1 2>/dev/null | head -5
    else
        log "INFO: nload or iftop not installed, skipping bandwidth check"
    fi
}

# Main network check
main() {
    log "=========================================="
    log "Network Monitor Started"
    log "=========================================="
    
    local failures=0
    
    # Run checks
    check_internet || failures=$((failures + 1))
    check_dns || failures=$((failures + 1))
    check_network_interface
    check_docker_network
    check_firewall
    check_bandwidth
    
    # Check common ports on localhost
    check_port "localhost" "22"
    check_port "localhost" "80"
    check_port "localhost" "443"
    check_port "localhost" "3000"
    check_port "localhost" "5432"
    check_port "localhost" "6379"
    check_port "localhost" "9090"
    check_port "localhost" "3002"
    check_port "localhost" "9093"
    
    log "=========================================="
    if [[ $failures -gt 0 ]]; then
        log "Network Monitor Completed: $failures check(s) failed"
        exit 1
    else
        log "Network Monitor Completed: All checks passed"
        exit 0
    fi
}

# Run main function
main "$@"