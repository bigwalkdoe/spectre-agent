#!/bin/bash
set -euo pipefail
# IDS/IPS Installation and Configuration Script
# Supports Suricata (network IDS/IPS) and OSSEC (host-based IDS)

# Source distribution detection
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
# shellcheck disable=SC1091  # resolved at runtime
source "$PROJECT_ROOT/detect-distribution.sh"

# Initialize distribution settings
detect_distribution

# Primary network interface for Suricata (override with SURICATA_INTERFACE)
SURICATA_INTERFACE="${SURICATA_INTERFACE:-$(ip route show default 2>/dev/null | awk 'NR==1 {print $5}')}"
SURICATA_INTERFACE="${SURICATA_INTERFACE:-eth0}"
set_package_manager

echo "Installing IDS/IPS for $DISTRO_NAME..."

# Install required dependencies
echo "Installing dependencies..."
case "$PKG_MANAGER" in
    dnf)
        $PKG_INSTALL epel-release 2>/dev/null || true
        $PKG_INSTALL libpcap-devel libnet-devel pcre-devel yaml-devel file-devel zlib-devel jansson-devel nss-devel libcap-ng-devel python3-pip
        ;;
    apt)
        $PKG_UPDATE
        $PKG_INSTALL libpcap-dev libnet-dev libpcre3-dev libyaml-dev pkg-config zlib1g-dev libjansson-dev libnss3-dev libcap-ng-dev python3-pip
        ;;
    pacman)
        $PKG_UPDATE
        $PKG_INSTALL libpcap libnet libpcre yaml file zlib jansson nss libcap-ng python-pip
        ;;
    zypper)
        $PKG_INSTALL libpcap-devel libnet-devel libpcre-devel yaml-devel file-devel zlib-devel jansson-devel nss-devel libcap-ng-devel python3-pip
        ;;
esac

# Install Suricata IDS/IPS
install_suricata() {
    if command -v suricata >/dev/null 2>&1; then
        echo "Suricata is already installed"
        return 0
    fi

    echo "Installing Suricata IDS/IPS..."
    
    case "$PKG_MANAGER" in
        dnf)
            # Try package manager first
            $PKG_INSTALL suricata 2>/dev/null || {
                # Build from source
                echo "Building Suricata from source..."
                wget https://suricata.io/downloads/suricata-7.0.0.tar.gz
                tar -xzf suricata-7.0.0.tar.gz
                cd suricata-7.0.0
                ./configure --prefix=/usr --sysconfdir=/etc --localstatedir=/var
                make
                sudo make install
                sudo ldconfig
                cd ..
                rm -rf suricata-7.0.0*
            }
            ;;
        apt)
            $PKG_INSTALL suricata
            ;;
        pacman)
            $PKG_INSTALL suricata
            ;;
        zypper)
            $PKG_INSTALL suricata
            ;;
        *)
            echo "Cannot install Suricata automatically for $PKG_MANAGER"
            return 1
            ;;
    esac
    
    # Download and update Suricata rules
    echo "Downloading Suricata rules..."
    sudo suricata-update
    sudo suricata-update enable-source et/open
    
    return 0
}

# Install OSSEC HIDS
install_ossec() {
    if [ -d /var/ossec ]; then
        echo "OSSEC is already installed"
        return 0
    fi

    echo "Installing OSSEC HIDS..."
    
    case "$PKG_MANAGER" in
        dnf)
            $PKG_INSTALL ossec-hids-server 2>/dev/null || {
                echo "Building OSSEC from source..."
                wget https://github.com/ossec/ossec-hids/archive/3.7.0.tar.gz
                tar -xzf 3.7.0.tar.gz
                cd ossec-hids-3.7.0
                ./install.sh
                cd ..
                rm -rf ossec-hids-3.7.0*
            }
            ;;
        apt)
            $PKG_INSTALL ossec-hids-server
            ;;
        pacman)
            # OSSEC not in main repos, install from AUR or build from source
            echo "OSSEC not available in Pacman repos. Please install manually from AUR or source."
            return 1
            ;;
        zypper)
            echo "OSSEC not available in Zypper repos. Please install manually from source."
            return 1
            ;;
    esac
    
    return 0
}

# Configure Suricata
configure_suricata() {
    echo "Configuring Suricata..."
    
    local config_file="/etc/suricata/suricata.yaml"
    
    if [ ! -f "$config_file" ]; then
        echo "Suricata configuration file not found at $config_file"
        return 1
    fi
    
    # Backup original configuration
    sudo cp "$config_file" "${config_file}.backup"
    
    # Configure Suricata for IPS mode
    sudo bash -c 'cat > /etc/suricata/suricata.yaml << "EOF"
# Suricata Configuration for Spectre Suite

%YAML 1.1
---

# General settings
af-packet:
  - interface: eth0
    cluster-type: cluster_flow
    cluster-id: 99
    defrag: yes
    roll-over-hash: yes

# Run modes
runmode:
  - af-packet

# Logging
default-log-dir: /var/log/suricata/

# Stats
stats:
  enabled: yes
  interval: 30
  decoders:
    enabled: yes
  streams:
    enabled: yes

# Outputs
outputs:
  - fast:
      enabled: yes
      filename: fast.log
      include: id,timestamp,srcip,dstip,sport,dport,proto
  - alert-debug:
      enabled: no
      filename: alert-debug.log
  - stats:
      enabled: yes
      filename: stats.log
      totals: yes
  - file-store:
      enabled: no

# Rule files
rule-files:
  - suricata.rules

# Classification
classifications:
  - name: Not Suspicious Traffic
    priority: 3
  - name: Unknown Traffic
    priority: 3
  - name: Attack Response
    priority: 1
  - name: Attempted Information Leak
    priority: 2
  - name: Information Leak
    priority: 2
  - name: Suspicious Login
    priority: 2
  - name: System Software Problem
    priority: 2
  - name: Unusual Client Port Communication
    priority: 3
  - name: Attack Signatures
    priority: 1
  - name: Denial of Service
    priority: 1

# Thresholds
thresholds:
  type: both
  track: by_src
  count: 5
  seconds: 60

# Suppressions
suppress:
  - gen_id: 1
    sig_id: 2270010
EOF'
    
    # Replace the hardcoded eth0 with the detected primary interface
    sudo sed -i "s/interface: eth0/interface: $SURICATA_INTERFACE/" "$config_file"
    
    echo "Suricata configuration updated"
}

# Configure OSSEC
configure_ossec() {
    echo "Configuring OSSEC..."
    
    if [ ! -d /var/ossec ]; then
        echo "OSSEC not installed, skipping configuration"
        return 1
    fi
    
    # Basic OSSEC configuration
    sudo bash -c 'cat > /var/ossec/etc/ossec.conf << "EOF"
<ossec_config>
  <global>
    <email_notification>no</email_notification>
    <email_to>admin@example.com</email_to>
    <email_from>ossec@example.com</email_from>
    <smtp_server>smtp.example.com</smtp_server>
  </global>

  <rules>
    <rule id="5501" level="5">
      <if_sid>5500</if_sid>
      <match>su</match>
      <description>First time user su to root</description>
    </rule>
  </rules>

  <syscheck>
    <frequency>7200</frequency>
    <directories check_all="yes">/etc,/usr/bin,/usr/sbin</directories>
    <directories check_all="yes">/bin,/sbin</directories>
    <ignore>/etc/mtab</ignore>
    <ignore>/etc/hosts.deny</ignore>
  </syscheck>

  <rootcheck>
    <rootkit_files>/var/ossec/etc/rootkit_files.txt</rootkit_files>
    <rootkit_trojans>/var/ossec/etc/rootkit_trojans.txt</rootkit_trojans>
  </rootcheck>

  <alerts>
    <log_alerts>yes</log_alerts>
    <email_alerts>no</email_alerts>
  </alerts>

  <localfile>
    <log_format>syslog</log_format>
    <location>/var/log/messages</location>
  </localfile>

  <localfile>
    <log_format>syslog</log_format>
    <location>/var/log/secure</location>
  </localfile>

  <localfile>
    <log_format>syslog</log_format>
    <location>/var/log/auth.log</location>
  </localfile>
</ossec_config>
EOF'
    
    echo "OSSEC configuration updated"
}

# Create systemd service for Suricata
create_suricata_service() {
    echo "Creating Suricata systemd service..."
    
    cat > /tmp/suricata.service << 'SERVICEEOF'
[Unit]
Description=Suricata IDS/IPS
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/suricata -c /etc/suricata/suricata.yaml -i eth0
ExecReload=/bin/kill -HUP $MAINPID
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SERVICEEOF
    sudo mv /tmp/suricata.service /etc/systemd/system/suricata.service
    # Replace the hardcoded eth0 with the detected primary interface
    sudo sed -i "s/-i eth0/-i $SURICATA_INTERFACE/" /etc/systemd/system/suricata.service
    
    sudo systemctl daemon-reload
    sudo systemctl enable suricata
}

# Create monitoring integration
create_ids_monitoring() {
    echo "Creating IDS monitoring integration..."
    
    # Create log monitoring script
    sudo mkdir -p /usr/local/bin
    
    cat > /tmp/ids-log-monitor.sh << 'IDSSCRIPT'
#!/bin/bash
# IDS Log Monitor Script

LOG_FILE="/var/log/suricata/fast.log"
PROMETHEUS_TEXTFILE="/var/lib/node_exporter/textfile_collector/ids_alerts.prom"

# Monitor Suricata alerts
if [ -f "$LOG_FILE" ]; then
    ALERT_COUNT=$(tail -100 "$LOG_FILE" | grep " \[**\] " | wc -l || true)
    
    cat > "$PROMETHEUS_TEXTFILE.$$" << EOFPROM
# HELP ids_alerts_total Total number of IDS alerts
# TYPE ids_alerts_total counter
ids_alerts_total ${ALERT_COUNT}
EOFPROM
    
    mv "$PROMETHEUS_TEXTFILE.$$" "$PROMETHEUS_TEXTFILE"
fi
IDSSCRIPT
    
    sudo mv /tmp/ids-log-monitor.sh /usr/local/bin/ids-log-monitor.sh
    sudo chmod +x /usr/local/bin/ids-log-monitor.sh
}

# Install and configure
install_suricata
configure_suricata
create_suricata_service
create_ids_monitoring

# Optionally install OSSEC (host-based IDS)
read -p "Install OSSEC Host-based IDS? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    install_ossec
    configure_ossec
fi

echo "IDS/IPS installation completed for $DISTRO_NAME!"
echo ""
echo "📝 Next Steps:"
echo "  1. Start Suricata: sudo systemctl start suricata"
echo "  2. Check status: sudo systemctl status suricata"
echo "  3. View alerts: sudo tail -f /var/log/suricata/fast.log"
echo "  4. Update rules: sudo suricata-update"
echo "  5. Configure interface: Edit /etc/suricata/suricata.yaml"
echo ""
echo "⚠️  Important:"
echo "  - Review Suricata configuration for your network"
echo "  - Test in IDS mode before enabling IPS mode"
echo "  - Monitor performance impact on production systems"
