#!/bin/bash
set -euo pipefail

# Network Security Hardening Script
# Applies network security best practices

LOG_FILE="/var/log/network-security.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

log() {
    echo "[$TIMESTAMP] $1" | tee -a "$LOG_FILE" || true
}

error() {
    echo "[$TIMESTAMP] ERROR: $1" | tee -a "$LOG_FILE" || true >&2
}

# Check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        error "Please run as root"
        exit 1
    fi
}

# Harden SSH configuration
harden_ssh() {
    log "Hardening SSH configuration..."
    
    local sshd_conf="/etc/ssh/sshd_config"
    
    # Backup current config
    cp "$sshd_conf" "${sshd_conf}.backup.$(date +%Y%m%d)"
    
    # Disable password authentication
    sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' "$sshd_conf"
    sed -i 's/^PasswordAuthentication yes/PasswordAuthentication no/' "$sshd_conf"
    
    # Enable key-based authentication
    sed -i 's/#PubkeyAuthentication yes/PubkeyAuthentication yes/' "$sshd_conf"
    sed -i 's/^PubkeyAuthentication no/PubkeyAuthentication yes/' "$sshd_conf"
    
    # Limit SSH to specific users
    sed -i 's/#AllowUsers/AllowUsers/' "$sshd_conf"
    
    # Disable root login
    sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin no/' "$sshd_conf"
    sed -i 's/^PermitRootLogin yes/PermitRootLogin no/' "$sshd_conf"
    
    # Set login grace time
    sed -i 's/^LoginGraceTime 120/LoginGraceTime 60/' "$sshd_conf"
    
    # Disable X11 forwarding
    sed -i 's/#X11Forwarding yes/X11Forwarding no/' "$sshd_conf"
    sed -i 's/^X11Forwarding yes/X11Forwarding no/' "$sshd_conf"
    
    # Set MaxAuthTries
    sed -i 's/^MaxAuthTries 3/MaxAuthTries 3/' "$sshd_conf"
    
    log "SSH configuration hardened"
}

# Configure firewall rules
configure_firewall() {
    log "Configuring firewall..."
    
    if command -v ufw &> /dev/null; then
        # Reset UFW
        ufw --force reset
        
        # Allow essential services
        ufw allow 22/tcp  # SSH
        ufw allow 80/tcp  # HTTP
        ufw allow 443/tcp # HTTPS
        ufw allow 9090/tcp # Prometheus
        ufw allow 3002/tcp # Grafana
        ufw allow 8081/tcp # Web Dashboard
        
        # Deny all incoming by default
        ufw default deny incoming
        
        # Allow all outgoing
        ufw default allow outgoing
        
        # Enable firewall
        ufw --force enable
        
        log "UFW firewall configured"
        
    elif command -v firewall-cmd &> /dev/null; then
        # Reset firewalld
        firewall-cmd --runtime-to-permanent
        
        # Add essential services
        firewall-cmd --permanent --add-service=ssh
        firewall-cmd --permanent --add-service=http
        firewall-cmd --permanent --add-service=https
        firewall-cmd --permanent --add-port=9090/tcp
        firewall-cmd --permanent --add-port=3002/tcp
        firewall-cmd --permanent --add-port=8081/tcp
        
        # Set default deny for incoming
        firewall-cmd --permanent --direct --add-rule ipv4 filter INPUT 0 -i lo -j ACCEPT
        firewall-cmd --permanent --direct --add-rule ipv4 filter INPUT 0 -m state --state ESTABLISHED,RELATED -j ACCEPT
        
        # Enable firewall
        firewall-cmd --permanent --direct --add-rule ipv4 filter FORWARD 0 -j DROP
        
        firewall-cmd --runtime-to-permanent
        
        log "firewalld configured"
    else
        log "INFO: No firewall detected (ufw or firewalld)"
    fi
}

# Configure IP forwarding and routing
configure_routing() {
    log "Configuring IP forwarding..."
    
    # Enable IP forwarding
    echo 1 > /proc/sys/net/ipv4/ip_forward
    
    # Persist setting
    echo "net.ipv4.ip_forward = 1" >> /etc/sysctl.conf
    
    log "IP forwarding configured"
}

# Configure SYN flood protection
configure_syn_flood() {
    log "Configuring SYN flood protection..."
    
    # Enable SYN cookies
    echo 1 > /proc/sys/net/ipv4/tcp_syncookies
    
    # Increase SYN backlog
    echo 4096 > /proc/sys/net/ipv4/tcp_max_syn_backlog
    
    # Persist settings
    cat >> /etc/sysctl.conf << EOF
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_max_syn_backlog = 4096
net.ipv4.tcp_synack_retries = 2
net.ipv4.tcp_syn_retries = 5
EOF
    
    log "SYN flood protection configured"
}

# Configure rate limiting
configure_rate_limiting() {
    log "Configuring rate limiting..."
    
    # Add iptables rules for rate limiting
    iptables -A INPUT -p tcp --dport 22 -m state --state NEW -m recent --set
    iptables -A INPUT -p tcp --dport 22 -m state --state NEW -m recent --update --seconds 60 --hitcount 4 -j DROP
    
    # Persist iptables rules
    if command -v iptables-save &> /dev/null; then
        iptables-save > /etc/iptables/rules.v4 2>/dev/null || true
    fi
    
    log "Rate limiting configured"
}

# Disable unnecessary services
disable_unnecessary_services() {
    log "Disabling unnecessary services..."
    
    # List services to disable (customize as needed)
    local services=("avahi-daemon" "bluetooth" "cups" "avahi-daemon.socket" "bluetooth.target" "bluetooth.target")
    
    for service in "${services[@]}"; do
        if systemctl list-unit-files | grep -q "$service"; then
            systemctl disable "$service" 2>/dev/null || true
            log "Disabled: $service"
        fi
    done
    
    log "Unnecessary services disabled"
}

# Generate security report
generate_report() {
    log "=========================================="
    log "Network Security Hardening Report"
    log "=========================================="
    
    log "Firewall Status:"
    if command -v ufw &> /dev/null; then
        ufw status verbose
    elif command -v firewall-cmd &> /dev/null; then
        firewall-cmd --list-all
    fi
    
    log ""
    log "SSH Configuration:"
    grep -E "^(PasswordAuthentication|PubkeyAuthentication|PermitRootLogin|X11Forwarding)" /etc/ssh/sshd_config 2>/dev/null || echo "  SSH config not found"
    
    log ""
    log "Open Ports:"
    if command -v ss &> /dev/null; then
        ss -tlnp
    elif command -v netstat &> /dev/null; then
        netstat -tlnp
    fi
    
    log "=========================================="
}

# Main function
main() {
    check_root
    
    log "=========================================="
    log "Network Security Hardening Started"
    log "=========================================="
    
    # Apply hardening measures
    harden_ssh
    configure_firewall
    configure_routing
    configure_syn_flood
    configure_rate_limiting
    disable_unnecessary_services
    
    # Generate report
    generate_report
    
    log "=========================================="
    log "Network Security Hardening Completed"
    log "=========================================="
    
    exit 0
}

# Run main function
main "$@"