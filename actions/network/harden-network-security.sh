#!/bin/bash
set -euo pipefail
# Network Security Hardening Script

echo "Hardening network security..."

# Enable SYN cookies protection
echo "Enabling SYN cookies protection..."
sudo sysctl -w net.ipv4.tcp_syncookies=1
echo "net.ipv4.tcp_syncookies=1" | sudo tee -a /etc/sysctl.conf

# Enable IP spoofing protection
echo "Enabling IP spoofing protection..."
sudo sysctl -w net.ipv4.conf.all.rp_filter=1
sudo sysctl -w net.ipv4.conf.default.rp_filter=1
echo "net.ipv4.conf.all.rp_filter=1" | sudo tee -a /etc/sysctl.conf
echo "net.ipv4.conf.default.rp_filter=1" | sudo tee -a /etc/sysctl.conf

# Enable ICMP ignore broadcasts
echo "Enabling ICMP ignore broadcasts..."
sudo sysctl -w net.ipv4.icmp_echo_ignore_broadcasts=1
echo "net.ipv4.icmp_echo_ignore_broadcasts=1" | sudo tee -a /etc/sysctl.conf

# Disable ICMP redirects
echo "Disabling ICMP redirects..."
sudo sysctl -w net.ipv4.conf.all.accept_redirects=0
sudo sysctl -w net.ipv4.conf.default.accept_redirects=0
echo "net.ipv4.conf.all.accept_redirects=0" | sudo tee -a /etc/sysctl.conf
echo "net.ipv4.conf.default.accept_redirects=0" | sudo tee -a /etc/sysctl.conf

# Enable source routing protection
echo "Enabling source routing protection..."
sudo sysctl -w net.ipv4.conf.all.accept_source_route=0
sudo sysctl -w net.ipv4.conf.default.accept_source_route=0
echo "net.ipv4.conf.all.accept_source_route=0" | sudo tee -a /etc/sysctl.conf
echo "net.ipv4.conf.default.accept_source_route=0" | sudo tee -a /etc/sysctl.conf

# Enable TCP SYN cookies
echo "Enabling TCP SYN cookies..."
sudo sysctl -w net.ipv4.tcp_syncookies=1
echo "net.ipv4.tcp_syncookies=1" | sudo tee -a /etc/sysctl.conf

# Enable TCP timestamps protection
echo "Enabling TCP timestamps protection..."
sudo sysctl -w net.ipv4.tcp_timestamps=0
echo "net.ipv4.tcp_timestamps=0" | sudo tee -a /etc/sysctl.conf

# Optimize TCP settings
echo "Optimizing TCP settings..."
sudo sysctl -w net.ipv4.tcp_fin_timeout=30
sudo sysctl -w net.ipv4.tcp_keepalive_time=600
sudo sysctl -w net.ipv4.tcp_keepalive_intvl=10
sudo sysctl -w net.ipv4.tcp_keepalive_probes=5
echo "net.ipv4.tcp_fin_timeout=30" | sudo tee -a /etc/sysctl.conf
echo "net.ipv4.tcp_keepalive_time=600" | sudo tee -a /etc/sysctl.conf
echo "net.ipv4.tcp_keepalive_intvl=10" | sudo tee -a /etc/sysctl.conf
echo "net.ipv4.tcp_keepalive_probes=5" | sudo tee -a /etc/sysctl.conf

echo "Network security hardening completed!"
logger -p user.info "Network security hardening completed"
