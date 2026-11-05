#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECTS_ROOT="${PROJECTS_ROOT:-$HOME/projects}"
# Grafana Dashboard Setup Script

GRAFANA_URL="${GRAFANA_URL:-http://localhost:3002}"
GRAFANA_USER="${GRAFANA_USER:-admin}"

# Password comes from the environment, matching GF_SECURITY_ADMIN_PASSWORD in
# docker-compose.monitoring.yml. This script previously reset the admin password
# to a hardcoded "admin123" and printed it, which is both a weak credential and
# a divergence from the password compose actually configures.
if [ -z "${GRAFANA_ADMIN_PASSWORD:-}" ]; then
    echo "Error: GRAFANA_ADMIN_PASSWORD is not set." >&2
    echo "Export the same password you set for docker-compose before running this." >&2
    exit 1
fi
GRAFANA_PASSWORD="$GRAFANA_ADMIN_PASSWORD"

# curl without --fail exits 0 on a 4xx/5xx, so an auth failure would be
# silently ignored and every later call would use the wrong password.
grafana_api() {
    curl -sS --fail-with-body -X "${1}" \
        -H "Content-Type: application/json" \
        -u "${GRAFANA_USER}:${GRAFANA_PASSWORD}" \
        "${@:2}"
}

echo "Setting up Grafana dashboards and data sources..."

# Wait for Grafana to be ready
echo "Waiting for Grafana to be ready..."
for _ in $(seq 1 30); do
    if curl -sS -o /dev/null "${GRAFANA_URL}/api/health"; then
        break
    fi
    sleep 2
done

# Rotate the initial admin password. Only needed when Grafana is still using its
# factory default; skipped if the configured password already works.
if ! grafana_api GET "${GRAFANA_URL}/api/user" >/dev/null 2>&1; then
    echo "Changing initial Grafana password..."
    grafana_api POST "${GRAFANA_URL}/api/user/password" \
        -d "$(printf '{"oldPassword":"%s","newPassword":"%s","confirmNewPassword":"%s"}' \
            "admin" "$GRAFANA_PASSWORD" "$GRAFANA_PASSWORD")"
else
    echo "Grafana admin credentials already valid."
fi

# Add Prometheus data source
echo "Adding Prometheus data source..."
grafana_api POST "${GRAFANA_URL}/api/datasources" \
    -d '{
      "name": "Prometheus",
      "type": "prometheus",
      "url": "http://prometheus:9090",
      "access": "proxy",
      "isDefault": true
    }' >/dev/null

# Import dashboards
import_dashboard() {
    local label="$1" file="$2"
    echo "Importing ${label} dashboard..."
    grafana_api POST "${GRAFANA_URL}/api/dashboards/db" \
        -d "$(printf '{"dashboard":%s,"overwrite":true,"message":"Imported via script"}' "$(cat "$file")")" >/dev/null
}

import_dashboard "System Monitoring" "$REPO_ROOT/grafana-dashboards/system-monitoring.json"
import_dashboard "PostgreSQL Monitoring" "$REPO_ROOT/grafana-dashboards/postgresql-monitoring.json"
import_dashboard "Redis Monitoring" "$REPO_ROOT/grafana-dashboards/redis-monitoring.json"

echo "Grafana setup complete!"
echo "Access Grafana at: ${GRAFANA_URL}"
echo "Username: ${GRAFANA_USER}"
echo "Password: (the GRAFANA_ADMIN_PASSWORD you supplied; not echoed)"