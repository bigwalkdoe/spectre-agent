#!/bin/bash
# Performance monitoring script

THRESHOLD_CPU=80
THRESHOLD_MEM=85
THRESHOLD_DISK=90

# Check CPU usage
CPU_USAGE=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)
if (( $(echo "$CPU_USAGE > $THRESHOLD_CPU" | bc -l) )); then
    logger -p user.warning "High CPU usage: ${CPU_USAGE}%"
fi

# Check memory usage
MEM_USAGE=$(free | grep Mem | awk '{printf "%.0f", $3/$2 * 100.0}')
if [ "$MEM_USAGE" -gt "$THRESHOLD_MEM" ]; then
    logger -p user.warning "High memory usage: ${MEM_USAGE}%"
fi

# Check disk usage
DISK_USAGE=$(df / | tail -1 | awk '{print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -gt "$THRESHOLD_DISK" ]; then
    logger -p user.warning "High disk usage: ${DISK_USAGE}%"
fi

echo "Performance check completed - CPU: ${CPU_USAGE}%, MEM: ${MEM_USAGE}%, DISK: ${DISK_USAGE}%"
