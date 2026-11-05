#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROJECTS_ROOT="${PROJECTS_ROOT:-$HOME/projects}"
PROMETHEUS_CONTAINER="${PROMETHEUS_CONTAINER:-$PROMETHEUS_CONTAINER}"
ALERTMANAGER_CONTAINER="${ALERTMANAGER_CONTAINER:-$ALERTMANAGER_CONTAINER}"
# Prometheus Alert Rules Setup Script

echo "Setting up Prometheus alert rules..."

# Copy alert rules to Prometheus container
docker cp "$REPO_ROOT/prometheus/alert_rules.yml" "$PROMETHEUS_CONTAINER":/etc/prometheus/alert_rules.yml

# Restart Prometheus to load new rules
docker restart "$PROMETHEUS_CONTAINER"

# Wait for Prometheus to start
echo "Waiting for Prometheus to restart..."
sleep 10

# Verify rules are loaded
echo "Verifying alert rules are loaded..."
docker exec "$PROMETHEUS_CONTAINER" promtool check config /etc/prometheus/prometheus.yml

echo "Prometheus alert rules configured successfully!"
echo "Access Prometheus at http://localhost:9091 to view alerts"
