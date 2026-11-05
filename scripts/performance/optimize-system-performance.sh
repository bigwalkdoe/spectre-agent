#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECTS_ROOT="${PROJECTS_ROOT:-$HOME/projects}"
# System Performance Optimization Script

echo "Optimizing system performance..."

# Enable tuned performance profile
if command -v tuned-adm >/dev/null 2>&1; then
    echo "Configuring tuned for virtual-machine profile..."
    sudo tuned-adm profile virtual-host
else
    echo "tuned not installed, skipping..."
fi

# Optimize swappiness
echo "Optimizing swappiness..."
CURRENT_SWAPPINESS=$(cat /proc/sys/vm/swappiness)
if [ "$CURRENT_SWAPPINESS" -gt 20 ]; then
    echo "Current swappiness: $CURRENT_SWAPPINESS, setting to 10..."
    sudo sysctl vm.swappiness=10
    echo "vm.swappiness=10" | sudo tee -a /etc/sysctl.conf
else
    echo "Swappiness already optimized: $CURRENT_SWAPPINESS"
fi

# Optimize I/O scheduler
# Detect the root disk (override with IO_DEVICE if needed). NVMe/SSD benefit
# from the 'deadline'/'none' scheduler. Set at runtime only — persisting across
# reboots requires a udev rule, not sysctl.conf (which rejects this path).
echo "Optimizing I/O scheduler..."
IO_DEVICE="${IO_DEVICE:-}"
if [ -z "$IO_DEVICE" ]; then
    IO_DEVICE=$(lsblk -ndo PKNAME "$(findmnt -n -o SOURCE / 2>/dev/null)" 2>/dev/null | xargs -r basename) || true
fi
if [ -n "$IO_DEVICE" ] && [ -f "/sys/block/$IO_DEVICE/queue/scheduler" ]; then
    CURRENT_SCHEDULER=$(cat "/sys/block/$IO_DEVICE/queue/scheduler")
    echo "Current I/O scheduler ($IO_DEVICE): $CURRENT_SCHEDULER"
    echo deadline | sudo tee "/sys/block/$IO_DEVICE/queue/scheduler" || true
else
    echo "Could not determine a block device with a tunable scheduler; skipping I/O scheduler tuning"
fi

# Optimize network settings
echo "Optimizing network settings..."
sudo sysctl net.core.rmem_max=16777216
sudo sysctl net.core.wmem_max=16777216
sudo sysctl net.ipv4.tcp_rmem='4096 87380 16777216'
sudo sysctl net.ipv4.tcp_wmem='4096 65536 16777216'

echo "Network optimizations applied (via sysctl):
- rmem_max: 16MB
- wmem_max: 16MB
- tcp_rmem: 4KB 85KB 16MB
- tcp_wmem: 4KB 64KB 16MB"

# Increase file descriptor limits
echo "Optimizing file descriptor limits..."
sudo bash -c 'cat > /etc/security/limits.d/99-performance.conf << "EOF"
* soft nofile 65536
* hard nofile 65536
* soft nproc 65536
* hard nproc 65536
EOF'

# Create performance monitoring dashboard alerts
echo "Setting up performance alerts..."
mkdir -p "$SCRIPT_DIR/performance"

cat > "$SCRIPT_DIR/check-performance.sh" << 'EOF'
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
EOF

chmod +x "$SCRIPT_DIR/check-performance.sh"

# Create systemd timer for performance monitoring
sudo bash -c 'cat > /etc/systemd/system/performance-check.service << "EOF"
[Unit]
Description=Performance Monitoring Service

[Service]
Type=oneshot
ExecStart=$SCRIPT_DIR/check-performance.sh
User=deon
EOF'

sudo bash -c 'cat > /etc/systemd/system/performance-check.timer << "EOF"
[Unit]
Description=Performance Monitoring Timer

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
EOF'

sudo systemctl enable --now performance-check.timer

echo "Performance optimization completed!"
echo "Performance monitoring is now running hourly"
logger -p user.info "System performance optimization completed"
