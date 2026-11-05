#!/bin/bash
set -euo pipefail
PROJECTS_ROOT="${PROJECTS_ROOT:-$HOME/projects}"
# Network Monitoring Script

NETWORK_LOG="$HOME/.local/share/network-monitor.log"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p "$HOME/.local/share"

echo "==========================================" >> "$NETWORK_LOG"
echo "Network Monitor - $DATE" >> "$NETWORK_LOG"
echo "==========================================" >> "$NETWORK_LOG"

# Check network interfaces
echo "Network Interfaces:" >> "$NETWORK_LOG"
ip addr show >> "$NETWORK_LOG"
echo "" >> "$NETWORK_LOG"

# Check network connectivity
echo "Network Connectivity:" >> "$NETWORK_LOG"
ping -c 3 8.8.8.8 >/dev/null 2>&1 && echo "Google DNS: OK" >> "$NETWORK_LOG" || echo "Google DNS: FAILED" >> "$NETWORK_LOG"
ping -c 3 1.1.1.1 >/dev/null 2>&1 && echo "Cloudflare DNS: OK" >> "$NETWORK_LOG" || echo "Cloudflare DNS: FAILED" >> "$NETWORK_LOG"
echo "" >> "$NETWORK_LOG"

# Check DNS resolution
echo "DNS Resolution:" >> "$NETWORK_LOG"
if nslookup google.com >/dev/null 2>&1; then
    echo "DNS resolution: OK" >> "$NETWORK_LOG"
else
    echo "DNS resolution: FAILED" >> "$NETWORK_LOG"
fi
echo "" >> "$NETWORK_LOG"

# Check network statistics
echo "Network Statistics:" >> "$NETWORK_LOG"
netstat -i >> "$NETWORK_LOG"
echo "" >> "$NETWORK_LOG"

# Check firewall status
echo "Firewall Status:" >> "$NETWORK_LOG"
firewall-cmd --state >> "$NETWORK_LOG" 2>&1 || echo "Firewall status check failed" >> "$NETWORK_LOG"
echo "" >> "$NETWORK_LOG"

# Check active connections
echo "Active Network Connections:" >> "$NETWORK_LOG"
ss -s >> "$NETWORK_LOG"
echo "" >> "$NETWORK_LOG"

# Check for suspicious connections
echo "External Connections:" >> "$NETWORK_LOG"
ss -tun | grep ESTABLISHED | awk '{print $5}' | cut -d':' -f1 | sort -u >> "$NETWORK_LOG" || true
echo "" >> "$NETWORK_LOG"

echo "Network monitoring completed: $DATE" >> "$NETWORK_LOG"
logger -p user.info "Network monitoring completed"
