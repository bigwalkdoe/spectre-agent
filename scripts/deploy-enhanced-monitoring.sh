#!/bin/bash
# Deploy enhanced monitoring components
set -euo pipefail

echo "=== Deploying Enhanced Monitoring ==="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# 1. Add Blackbox exporter to docker-compose
echo "Adding Blackbox exporter to monitoring stack..."
if ! grep -q "blackbox-exporter" "$PROJECT_ROOT/docker-compose.monitoring.yml" 2>/dev/null; then
    cat >> "$PROJECT_ROOT/docker-compose.monitoring.yml" << 'EOF'

  # Blackbox Exporter - External endpoint monitoring
  blackbox-exporter:
    image: prom/blackbox-exporter:latest
    container_name: blackbox-exporter
    ports:
      - "9115:9115"
    volumes:
      - ./prometheus/blackbox-exporter.yml:/config/blackbox-exporter.yml
    command:
      - '--config.file=/config/blackbox-exporter.yml'
      - '--web.external-url=http://localhost:9115'
    restart: unless-stopped
    networks:
      - monitoring
EOF
    echo "Blackbox exporter added to monitoring stack"
fi

# 2. Create alertmanager templates directory
mkdir -p "$PROJECT_ROOT/prometheus/templates"
cp "$PROJECT_ROOT/prometheus/alertmanager-templates.tmpl" "$PROJECT_ROOT/prometheus/templates/"

# 3. Merge uptime monitoring into prometheus.yml
echo "Adding uptime monitoring targets to prometheus.yml..."
if ! grep -q "blackbox-http" "$PROJECT_ROOT/prometheus/prometheus.yml" 2>/dev/null; then
    cat >> "$PROJECT_ROOT/prometheus/prometheus.yml" << 'EOF'

  # Blackbox Exporter - HTTP checks
  - job_name: 'blackbox-http'
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
        - https://api.github.com
        - https://hub.docker.com
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: blackbox-exporter:9115

  # Blackbox Exporter - TCP checks
  - job_name: 'blackbox-tcp'
    metrics_path: /probe
    params:
      module: [tcp_connect]
    static_configs:
      - targets:
        - 'localhost:22'
        - 'localhost:443'
        - 'localhost:5432'
        - 'localhost:6379'
        - 'localhost:9090'
        - 'localhost:3002'
        - 'localhost:8081'
        - 'localhost:3100'
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: blackbox-exporter:9115

  # Business metrics via textfile collector
  - job_name: 'business-metrics'
    scrape_interval: 60s
    static_configs:
      - targets: ['node-exporter:9100']
    metrics_path: /metrics
EOF
    echo "Uptime monitoring targets added to prometheus.yml"
fi

# 4. Set up business metrics exporter cron
echo "Setting up business metrics exporter..."
if ! crontab -l 2>/dev/null | grep -q "business-metrics-exporter"; then
    (crontab -l 2>/dev/null; echo "*/5 * * * * $PROJECT_ROOT/prometheus/business-metrics-exporter.sh") | crontab -
    echo "Business metrics exporter scheduled (every 5 minutes)"
fi

# 5. Add uptime alerts
echo "Adding uptime monitoring alerts..."
if ! grep -q "UptimeCheck" "$PROJECT_ROOT/prometheus/alert_rules.yml" 2>/dev/null; then
    cat >> "$PROJECT_ROOT/prometheus/alert_rules.yml" << 'EOF'

  - name: uptime_alerts
    interval: 30s
    rules:
      - alert: UptimeCheckFailed
        expr: probe_success == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Uptime check failed"
          description: "Endpoint {{ $labels.instance }} is unreachable (module: {{ $labels.module }})"

      - alert: HighLatency
        expr: probe_duration_seconds > 2
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High endpoint latency"
          description: "Endpoint {{ $labels.instance }} has latency of {{ $value }}s"

      - alert: DNSCheckFailed
        expr: probe_dns_lookup_time_seconds > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Slow DNS resolution"
          description: "DNS lookup for {{ $labels.instance }} took {{ $value }}s"

      - alert: BusinessMetricStale
        expr: time() - backup_last_success_timestamp > 86400
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Backup metric is stale"
          description: "Last successful backup was over 24 hours ago"
EOF
    echo "Uptime alerts added to alert_rules.yml"
fi

echo ""
echo "=== Enhanced Monitoring Deployment Complete ==="
echo ""
echo "Components deployed:"
echo "  - Blackbox exporter (port 9115)"
echo "  - Business metrics exporter"
echo "  - Uptime monitoring for critical services"
echo "  - Enhanced alertmanager with Slack/Email/PagerDuty"
echo ""
echo "Restart monitoring stack to apply:"
echo "  docker-compose -f docker-compose.monitoring.yml down"
echo "  docker-compose -f docker-compose.monitoring.yml up -d"
