#!/bin/bash
set -euo pipefail
# Network Configuration Optimization Script (Distribution-agnostic)

# Source distribution detection
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
# shellcheck disable=SC1091  # resolved at runtime
source "$PROJECT_ROOT/detect-distribution.sh"

# Initialize distribution settings
detect_distribution
set_package_manager

# Primary network interface (override with NET_IFACE if needed)
NET_IFACE="${NET_IFACE:-$(ip route show default 2>/dev/null | awk 'NR==1 {print $5}')}"
NET_IFACE="${NET_IFACE:-eth0}"

echo "Optimizing network configuration for $DISTRO_NAME..."

# Set up optimized DNS settings
echo "Configuring optimized DNS settings..."

# Distribution-specific DNS configuration
case "$DISTRO" in
    ubuntu|debian|linuxmint|pop)
        # Debian/Ubuntu uses NetworkManager or resolvconf
        if [ -d /etc/NetworkManager ]; then
            echo "Configuring NetworkManager for Debian/Ubuntu..."
            sudo mkdir -p /etc/NetworkManager/conf.d
            sudo bash -c 'cat > /etc/NetworkManager/conf.d/dns.conf << "EOF"
[main]
dns=dnsmasq
rc-manager=symlink
EOF'
            
            # Restart NetworkManager
            sudo systemctl restart NetworkManager
        fi
        
        # Configure systemd-resolved
        if command -v systemctl >/dev/null 2>&1 && systemctl is-active systemd-resolved >/dev/null 2>&1; then
            echo "Configuring systemd-resolved..."
            sudo mkdir -p /etc/systemd/resolved.conf.d
            sudo bash -c 'cat > /etc/systemd/resolved.conf.d/dns.conf << "EOF"
[Resolve]
DNS=8.8.8.8 8.8.4.4 1.1.1.1 1.0.0.1
FallbackDNS=9.9.9.9 149.112.112.112
Cache=yes
DNSStubListener=yes
EOF'
            sudo systemctl restart systemd-resolved
        fi
        ;;
    
    fedora|rhel|centos|rocky|almalinux)
        # Fedora/RHEL uses NetworkManager
        echo "Configuring NetworkManager for Fedora/RHEL..."
        
        # Backup current configuration
        if [ -f /etc/NetworkManager/NetworkManager.conf ]; then
            sudo cp /etc/NetworkManager/NetworkManager.conf /etc/NetworkManager/NetworkManager.conf.backup
        fi
        
        # Enable DNS caching and set fast DNS servers
        sudo mkdir -p /etc/NetworkManager/conf.d
        sudo bash -c 'cat > /etc/NetworkManager/conf.d/dns.conf << "EOF"
[main]
dns=dnsmasq
rc-manager=symlink
EOF'
        
        # Set up systemd-resolved for better DNS resolution
        sudo systemctl enable systemd-resolved
        sudo systemctl start systemd-resolved
        
        # Create stub resolver configuration
        sudo mkdir -p /etc/systemd/resolved.conf.d
        sudo bash -c 'cat > /etc/systemd/resolved.conf.d/dns.conf << "EOF"
[Resolve]
DNS=8.8.8.8 8.8.4.4 1.1.1.1 1.0.0.1
FallbackDNS=9.9.9.9 149.112.112.112
Cache=yes
DNSStubListener=yes
EOF'
        
        # Restart NetworkManager to apply DNS changes
        sudo systemctl restart NetworkManager
        ;;
    
    arch|manjaro)
        # Arch Linux uses NetworkManager
        echo "Configuring NetworkManager for Arch..."
        
        sudo mkdir -p /etc/NetworkManager/conf.d
        sudo bash -c 'cat > /etc/NetworkManager/conf.d/dns.conf << "EOF"
[main]
dns=dnsmasq
rc-manager=symlink
EOF'
        
        # Set up systemd-resolved
        sudo systemctl enable systemd-resolved
        sudo systemctl start systemd-resolved
        
        sudo mkdir -p /etc/systemd/resolved.conf.d
        sudo bash -c 'cat > /etc/systemd/resolved.conf.d/dns.conf << "EOF"
[Resolve]
DNS=8.8.8.8 8.8.4.4 1.1.1.1 1.0.0.1
FallbackDNS=9.9.9.9 149.112.112.112
Cache=yes
DNSStubListener=yes
EOF'
        
        sudo systemctl restart NetworkManager
        ;;
    
    opensuse-leap|opensuse-tumbleweed)
        # openSUSE uses wicked or NetworkManager
        echo "Configuring network for openSUSE..."
        
        if command -v systemctl >/dev/null 2>&1 && systemctl is-active NetworkManager >/dev/null 2>&1; then
            sudo mkdir -p /etc/NetworkManager/conf.d
            sudo bash -c 'cat > /etc/NetworkManager/conf.d/dns.conf << "EOF"
[main]
dns=dnsmasq
rc-manager=symlink
EOF'
            sudo systemctl restart NetworkManager
        fi
        ;;
    
    *)
        echo "Generic DNS configuration for unknown distribution..."
        # Try to use resolvconf if available
        if command -v resolvconf >/dev/null 2>&1; then
            echo "nameserver 8.8.8.8" | sudo resolvconf -a "$NET_IFACE"
            echo "nameserver 8.8.4.4" | sudo resolvconf -a "$NET_IFACE"
        fi
        ;;
esac

# Network security hardening (common across distributions)
echo "Applying network security hardening..."

# Create network security configuration
sudo bash -c 'cat > /etc/sysctl.d/99-network-security.conf << "EOF"
# TCP/IP hardening
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_max_syn_backlog = 2048
net.ipv4.tcp_synack_retries = 2
net.ipv4.tcp_syn_retries = 5

# IP spoofing protection
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
net.ipv4.conf.lo.rp_filter = 1

# Ignore ICMP broadcast requests
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv4.icmp_ignore_bogus_error_responses = 1

# Ignore directed pings
net.ipv4.icmp_echo_ignore_all = 0

# Disable source packet routing
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0

# Disable send redirects
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0

# Enable SYN cookies protection
net.ipv4.tcp_syncookies = 1

# Enable protection against TIME_WAIT attacks
net.ipv4.tcp_rfc1337 = 1

# Reduce TCP timeout
net.ipv4.tcp_fin_timeout = 30
net.ipv4.tcp_keepalive_time = 1800
net.ipv4.tcp_keepalive_intvl = 15
net.ipv4.tcp_keepalive_probes = 5

# Increase system port range
net.ipv4.ip_local_port_range = 1024 65535

# Enable TCP Fast Open
net.ipv4.tcp_fastopen = 3

# TCP window scaling
net.ipv4.tcp_window_scaling = 1
EOF'

# Apply sysctl settings
sudo sysctl -p /etc/sysctl.d/99-network-security.conf

echo "Network configuration optimized for $DISTRO_NAME!"
echo "DNS caching enabled"
echo "Fast DNS servers configured (8.8.8.8, 8.8.4.4, 1.1.1.1, 1.0.0.1)"
echo "Network security hardening applied"
