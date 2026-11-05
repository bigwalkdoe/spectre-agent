#!/bin/bash
# Analyze resource usage and recommend rightsizing
set -euo pipefail

echo "=== Resource Rightsizing Analysis ==="
echo ""

# Memory analysis
echo "Memory Usage by Process (top 10):"
ps aux --sort=-%mem | head -11 | awk '{printf "%-30s %-10s %-10s %-10s\n", $11, $6"KB", $4"%", $3"%"}'

echo ""
echo "Container Resource Usage:"
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}" 2>/dev/null || true

# CPU analysis
echo ""
echo "CPU Usage by Process (top 10):"
ps aux --sort=-%cpu | head -11 | awk '{printf "%-30s %-10s %-10s\n", $11, $3"%", $6"KB"}'

# Recommendations
echo ""
echo "Rightsizing Recommendations:"
echo "----------------------------------------"

# Check containers with low CPU usage
docker stats --no-stream --format "{{.Name}}\t{{.CPUPerc}}\t{{.MemPerc}}" 2>/dev/null | while read name cpu mem; do
    cpu_val=${cpu%\%}
    mem_val=${mem%\%}
    
    if [ -n "$cpu_val" ] && [ -n "$mem_val" ]; then
        if (( $(echo "$cpu_val < 5" | bc -l) )) && (( $(echo "$mem_val < 20" | bc -l) )); then
            echo "  $name: Consider reducing resources (CPU: ${cpu_val}%, Memory: ${mem_val}%)"
        elif (( $(echo "$cpu_val > 80" | bc -l) )); then
            echo "  $name: Consider increasing CPU (currently ${cpu_val}%)"
        elif (( $(echo "$mem_val > 80" | bc -l) )); then
            echo "  $name: Consider increasing memory (currently ${mem_val}%)"
        fi
    fi
done

# Disk analysis
echo ""
echo "Disk Usage Analysis:"
TOTAL_DISK=$(df / | tail -1 | awk '{print $2}')
USED_DISK=$(df / | tail -1 | awk '{print $3}')
AVAIL_DISK=$(df / | tail -1 | awk '{print $4}')
USED_PCT=$(df / | tail -1 | awk '{print $5}' | sed 's/%//')

echo "  Total: $(numfmt --to=iec $((TOTAL_DISK * 1024)))"
echo "  Used: $(numfmt --to=iec $((USED_DISK * 1024))) ($USED_PCT%)"
echo "  Available: $(numfmt --to=iec $((AVAIL_DISK * 1024)))"

if [ "$USED_PCT" -gt 80 ]; then
    echo "  WARNING: Disk usage above 80%, consider cleanup or expansion"
fi
