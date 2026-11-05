#!/bin/bash
set -euo pipefail
PROJECTS_ROOT="${PROJECTS_ROOT:-$HOME/projects}"
# Docker Resource Optimization Script

echo "Optimizing Docker container resource limits..."

# Update docker-compose with resource limits for better performance
cd "$PROJECTS_ROOT/Guardrail-AI"

# Check if current docker-compose has resource limits
if ! grep -q "deploy:" docker-compose.yml; then
    echo "Adding resource limits to docker-compose.yml"

    # Add resource limits to key services
    # This will be added as a separate optimization file
    cat > docker-compose.override.yml << 'EOF'
version: '3.8'

services:
  postgres:
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 512M

  neo4j:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 4G
        reservations:
          cpus: '1.0'
          memory: 2G

  redis:
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 1G
        reservations:
          cpus: '0.25'
          memory: 256M

  api:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '1.0'
          memory: 512M

  celery-worker:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '1.0'
          memory: 512M

  prometheus:
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 512M

  grafana:
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 1G
        reservations:
          cpus: '0.25'
          memory: 256M

  cadvisor:
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
        reservations:
          cpus: '0.25'
          memory: 128M
EOF
    
    echo "Resource limits added to docker-compose.override.yml"
    echo "Restart containers to apply: docker-compose up -d"
else
    echo "Resource limits already configured"
fi
