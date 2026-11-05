#!/bin/bash
set -euo pipefail
# Comprehensive Security Integration Script
# Integrates all security features into a unified security framework

# Source distribution detection
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
# shellcheck disable=SC1091  # resolved at runtime
source "$PROJECT_ROOT/detect-distribution.sh"

# Initialize distribution settings
detect_distribution
set_package_manager

echo "Setting up Comprehensive Security Integration for $DISTRO_NAME..."

SECURITY_DIR="/etc/security-integration"
LOG_DIR="/var/log/security-integration"
CONFIG_DIR="$SECURITY_DIR/config"

# Create directories
sudo mkdir -p "$SECURITY_DIR" "$LOG_DIR" "$CONFIG_DIR"

# Install security tools
install_security_tools() {
    echo "Installing security tools..."
    
    local tools="fail2ban rkhunter chkrootkit aide"
    
    case "$PKG_MANAGER" in
        dnf)
                        # shellcheck disable=SC2086  # PKG_INSTALL is a command string, split intentionally
            $PKG_INSTALL $tools
            ;;
        apt)
                        # shellcheck disable=SC2086  # PKG_INSTALL is a command string, split intentionally
            $PKG_INSTALL $tools
            ;;
        pacman)
            # Arch has different package names
            $PKG_INSTALL fail2ban rkhunter aide
            # chkrootkit may need to be installed from AUR
            ;;
        zypper)
            $PKG_INSTALL fail2ban rkhunter aide
            ;;
    esac
}

# Configure Fail2Ban
configure_fail2ban() {
    echo "Configuring Fail2Ban..."
    
    # SSH auth log path differs by distribution
    case "$DISTRO" in
        rhel) AUTH_LOG="/var/log/secure" ;;
        *)    AUTH_LOG="/var/log/auth.log" ;;
    esac
    
    sudo bash -c 'cat > /etc/fail2ban/jail.local << "EOF"
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5
destemail = admin@example.com
sendername = Fail2Ban
action = %(action_)s

[sshd]
enabled = true
port = ssh
logpath = /var/log/auth.log
maxretry = 3

[apache-auth]
enabled = true
port = http,https
logpath = /var/log/apache*/error.log
maxretry = 3

[nginx-http-auth]
enabled = true
port = http,https
logpath = /var/log/nginx/error.log
maxretry = 3

[postfix]
enabled = true
port = smtp,ssmtp
logpath = /var/log/mail.log
maxretry = 3
 EOF'
    
    # Substitute the distro-aware SSH auth log path
    sudo sed -i "s#logpath = /var/log/auth.log#logpath = $AUTH_LOG#" /etc/fail2ban/jail.local
    
    sudo systemctl enable fail2ban
    sudo systemctl start fail2ban
}

# Configure AIDE (Advanced Intrusion Detection Environment)
configure_aide() {
    echo "Configuring AIDE..."
    
    if ! command -v aide >/dev/null 2>&1; then
        echo "AIDE not installed, skipping configuration"
        return 1
    fi
    
    # Initialize AIDE database
    sudo aide --init
    sudo mv /var/lib/aide/aide.db.new /var/lib/aide/aide.db
    
    # Create AIDE configuration
    sudo bash -c 'cat > /etc/aide.conf << "EOF"
# AIDE Configuration for Spectre Suite

# Database locations
database=file:/var/lib/aide/aide.db
database_out=file:/var/lib/aide/aide.db.new

# Define rules
All=p+a+rmd+sha256+c+b+s+f+u+g+sha1+m+c+md5+sha256+tiger+xattr
Norm=p+a+rmd+sha256+c+b+f+u+g+n+sha1+m+c+md5+sha256+tiger
NoI=p+a+rmd+sha256+c+b+f+u+g+n+sha1+m+c+md5+sha256+tiger+xattr

# Directories to monitor
/etc All
/usr/local/bin All
/usr/local/sbin All
/bin All
/sbin All
/usr/bin All
/usr/sbin All
/var/log All

# Exclude temporary directories
!/var/tmp
!/tmp
!/var/cache
!/dev
!/proc
!/sys
EOF'
}

# Configure security monitoring
configure_security_monitoring() {
    echo "Configuring security monitoring..."
    
    # Create security monitoring script
    cat > "$CONFIG_DIR/security-monitor.sh" << 'EOF'
#!/bin/bash
# Security Monitoring Script

LOG_FILE="/var/log/security-integration/monitor.log"
ALERT_FILE="/var/log/security-integration/alerts.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$LOG_FILE"
}

alert() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - ALERT: $1" >> "$ALERT_FILE"
    log "ALERT: $1"
}

# Check Fail2Ban status
check_fail2ban() {
    if command -v fail2ban-client >/dev/null 2>&1; then
        local banned
        banned=$(sudo fail2ban-client status sshd | grep "Banned IP list" | awk -F: '{print $2}')
        if [ -n "$banned" ]; then
            log "Fail2Ban banned IPs: $banned"
        fi
    fi
}

# Check AIDE integrity
check_aide() {
    if command -v aide >/dev/null 2>&1; then
        local aide_output
        aide_output=$(sudo aide --check 2>&1)
        if echo "$aide_output" | grep -q "differences found"; then
            alert "AIDE integrity check found differences"
            log "$aide_output"
        fi
    fi
}

# Check rootkits
check_rootkits() {
    if command -v rkhunter >/dev/null 2>&1; then
        local rkhunter_output
        rkhunter_output=$(sudo rkhunter --check --skip-keypress 2>&1)
        if echo "$rkhunter_output" | grep -q "Warning"; then
            alert "Rootkit scan found warnings"
            log "$rkhunter_output"
        fi
    fi
}

# Check for unauthorized users
check_users() {
    local current_users
    current_users=$(cat /etc/passwd | wc -l)
    local known_users
    known_users=$(cat /etc/security-integration/baseline.users 2>/dev/null | wc -l)
    
    if [ $current_users -gt $known_users ]; then
        alert "Unauthorized user accounts detected"
        log "Current users: $current_users, Baseline: $known_users"
    fi
}

# Check for suspicious processes
check_processes() {
    local suspicious
    suspicious=$(ps aux | grep -E "nc.*-l|/bin/sh.*-i|perl.*-e" | grep -v grep)
    if [ -n "$suspicious" ]; then
        alert "Suspicious processes detected"
        log "$suspicious"
    fi
}

# Main monitoring
log "Starting security monitoring check"
check_fail2ban
check_aide
check_rootkits
check_users
check_processes
log "Security monitoring check completed"
EOF
    
    sudo chmod +x "$CONFIG_DIR/security-monitor.sh"
    
    # Create user baseline
    cat /etc/passwd | sudo tee "$SECURITY_DIR/baseline.users" >/dev/null
}

# Create systemd service for security monitoring
create_security_service() {
    echo "Creating security monitoring service..."
    
    sudo bash -c 'cat > /etc/systemd/system/security-monitor.service << "EOF"
[Unit]
Description=System Security Monitoring
After=network.target

[Service]
Type=oneshot
ExecStart=/etc/security-integration/config/security-monitor.sh

[Install]
WantedBy=multi-user.target
EOF'
    
    sudo bash -c 'cat > /etc/systemd/system/security-monitor.timer << "EOF"
[Unit]
Description=Run security monitoring every 15 minutes

[Timer]
OnCalendar=*:0/15
Persistent=true

[Install]
WantedBy=timers.target
EOF'
    
    sudo systemctl daemon-reload
    sudo systemctl enable security-monitor.timer
    sudo systemctl start security-monitor.timer
}

# Create security dashboard integration
create_security_dashboard() {
    echo "Creating security dashboard integration..."
    
    # Create Prometheus exporter for security metrics
    cat > "$CONFIG_DIR/security-metrics.sh" << 'EOF'
#!/bin/bash
# Security Metrics Exporter for Prometheus

METRICS_FILE="/var/lib/node_exporter/textfile_collector/security_metrics.prom"

# Get security metrics
fail2ban_banned=$(sudo fail2ban-client status sshd 2>/dev/null | grep "Banned IP list" | awk -F: '{print $2}' | wc -w)
aide_alerts=$(sudo aide --check 2>&1 | grep "added\|removed\|changed" | wc -l || true)
last_security_scan=$(stat -c %Y /var/log/security-integration/monitor.log 2>/dev/null || echo 0)

cat > "$METRICS_FILE.$$" << EOF
# HELP security_fail2ban_banned_total Total number of IPs banned by Fail2Ban
# TYPE security_fail2ban_banned_total gauge
security_fail2ban_banned_total ${fail2ban_banned}

# HELP security_aide_alerts_total Total number of AIDE integrity alerts
# TYPE security_aide_alerts_total gauge
security_aide_alerts_total ${aide_alerts}

# HELP security_last_scan_timestamp Unix timestamp of last security scan
# TYPE security_last_scan_timestamp gauge
security_last_scan_timestamp ${last_security_scan}
EOF

mv "$METRICS_FILE.$$" "$METRICS_FILE"
EOF
    
    sudo chmod +x "$CONFIG_DIR/security-metrics.sh"
}

# Install and configure
install_security_tools
configure_fail2ban
configure_aide
configure_security_monitoring
create_security_service
create_security_dashboard

echo ""
echo "🔒 Comprehensive Security Integration completed for $DISTRO_NAME!"
echo ""
echo "📁 Configuration directory: $SECURITY_DIR"
echo "📁 Log directory: $LOG_DIR"
echo ""
echo "🛠️ Components installed:"
echo "  - Fail2Ban (Intrusion Prevention)"
echo "  - AIDE (File Integrity Monitoring)"
echo "  - RKHunter (Rootkit Detection)"
echo "  - Security Monitoring Service"
echo "  - Security Metrics Exporter"
echo ""
echo "📝 Next Steps:"
echo "  1. Review security configurations in $CONFIG_DIR"
echo "  2. Customize Fail2Ban rules for your environment"
echo "  3. Schedule regular AIDE scans"
echo "  4. Review security logs in $LOG_DIR"
echo "  5. Test IDS/IPS with scripts/security/install-ids-ips.sh"
echo "  6. Run advanced threat detection with scripts/security/advanced-threat-detection.sh"
echo ""
echo "⚠️  Security Best Practices:"
echo "  - Keep all security tools updated"
echo "  - Review alerts regularly"
echo "  - Update baselines after system changes"
echo "  - Test security procedures regularly"
echo "  - Implement backup and recovery procedures"
