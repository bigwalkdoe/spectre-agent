#!/bin/bash
set -euo pipefail
# System Health Check Script
# Performs comprehensive system health analysis

HEALTH_LOG="/var/log/system-health.log"
DATE=$(date +%Y%m%d_%H%M%S)

echo "==========================================" >> "$HEALTH_LOG"
echo "System Health Check - $DATE" >> "$HEALTH_LOG"
echo "==========================================" >> "$HEALTH_LOG"

# Check disk space
echo "Disk Space:" >> "$HEALTH_LOG"
df -h >> "$HEALTH_LOG"
echo "" >> "$HEALTH_LOG"

# Check memory usage
echo "Memory Usage:" >> "$HEALTH_LOG"
free -h >> "$HEALTH_LOG"
echo "" >> "$HEALTH_LOG"

# Check CPU load
echo "CPU Load:" >> "$HEALTH_LOG"
uptime >> "$HEALTH_LOG"
echo "" >> "$HEALTH_LOG"

# Check Docker containers
echo "Docker Container Status:" >> "$HEALTH_LOG"
docker ps --format "table {{.Names}}\t{{.Status}}" >> "$HEALTH_LOG"
echo "" >> "$HEALTH_LOG"

# Check failed services
echo "Failed Services:" >> "$HEALTH_LOG"
systemctl list-units --state=failed >> "$HEALTH_LOG"
echo "" >> "$HEALTH_LOG"

# Check for kernel errors
echo "Recent Kernel Errors:" >> "$HEALTH_LOG"
dmesg | tail -20 >> "$HEALTH_LOG" 2>/dev/null || echo "Unable to read dmesg" >> "$HEALTH_LOG"
echo "" >> "$HEALTH_LOG"

# Check network connectivity
echo "Network Connectivity:" >> "$HEALTH_LOG"
ping -c 1 8.8.8.8 >/dev/null 2>&1 && echo "Internet: OK" >> "$HEALTH_LOG" || echo "Internet: FAILED" >> "$HEALTH_LOG"
echo "" >> "$HEALTH_LOG"

# Generate summary
echo "==========================================" >> "$HEALTH_LOG"
echo "Health check completed: $DATE" >> "$HEALTH_LOG"
echo "==========================================" >> "$HEALTH_LOG"

# Alert if critical issues found
if systemctl list-units --state=failed | grep -q "loaded"; then
    logger -p user.warning "System health check found failed services"
    if [ -n "$DISPLAY" ]; then
        notify-send "System Health Alert" "Some services have failed - check logs" -u critical
    fi
fi

echo "System health check completed!"
logger -p user.info "System health check completed"
