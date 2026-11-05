#!/bin/bash

# Spectre Suite Monitoring Stack Deployment Script
# This script deploys Prometheus, Grafana, and related monitoring tools

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "🚀 Deploying Spectre Suite Monitoring Stack..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

# Check if Docker Compose is available
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose is not available. Please install it first."
    exit 1
fi

# Create necessary directories
echo "📁 Creating necessary directories..."
mkdir -p "$PROJECT_ROOT/prometheus"
mkdir -p "$PROJECT_ROOT/grafana-dashboards"
mkdir -p "$PROJECT_ROOT/grafana-provisioning/datasources"
mkdir -p "$PROJECT_ROOT/grafana-provisioning/dashboards"

# Check if configuration files exist
if [ ! -f "$PROJECT_ROOT/prometheus/prometheus.yml" ]; then
    echo "❌ Prometheus configuration not found at $PROJECT_ROOT/prometheus/prometheus.yml"
    exit 1
fi

if [ ! -f "$PROJECT_ROOT/prometheus/alert_rules.yml" ]; then
    echo "❌ Alert rules not found at $PROJECT_ROOT/prometheus/alert_rules.yml"
    exit 1
fi

# Deploy monitoring stack
echo "🐳 Starting monitoring stack..."
cd "$PROJECT_ROOT"

# Try docker compose first, then docker-compose
if docker compose version &> /dev/null; then
    docker compose -f docker-compose.monitoring.yml up -d
else
    docker-compose -f docker-compose.monitoring.yml up -d
fi

# Wait for services to be ready
echo "⏳ Waiting for services to start..."
sleep 10

# Check if services are running
echo "🔍 Checking service status..."
services=("prometheus" "grafana" "alertmanager" "node-exporter" "cadvisor")
for service in "${services[@]}"; do
    if docker ps --format '{{.Names}}' | grep -q "^${service}$"; then
        echo "✅ $service is running"
    else
        echo "❌ $service failed to start"
        docker logs "$service" | tail -20
    fi
done

echo ""
echo "🎉 Monitoring stack deployed successfully!"
echo ""
echo "📍 Access Points:"
echo "  - Web Dashboard: http://localhost:8081"
echo "  - Grafana Dashboard: http://localhost:3002 (admin/changeme)"
echo "  - Prometheus: http://localhost:9090"
echo "  - Alertmanager: http://localhost:9093"
echo "  - Node Exporter: http://localhost:9100/metrics"
echo "  - cAdvisor: http://localhost:8080"
echo ""
echo "📝 Next Steps:"
echo "  1. Change the default Grafana admin password"
echo "  2. Configure alert notifications in alertmanager.yml"
echo "  3. Import additional dashboards if needed"
echo "  4. Set up authentication for production use"
echo ""
echo "🛠️ Management Commands:"
echo "  - Stop: docker-compose -f docker-compose.monitoring.yml down"
echo "  - Restart: docker-compose -f docker-compose.monitoring.yml restart"
echo "  - Logs: docker-compose -f docker-compose.monitoring.yml logs -f [service]"
echo "  - Update: docker-compose -f docker-compose.monitoring.yml pull && docker-compose -f docker-compose.monitoring.yml up -d"
