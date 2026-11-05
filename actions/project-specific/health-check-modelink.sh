#!/bin/bash
set -euo pipefail
PROJECTS_ROOT="${PROJECTS_ROOT:-$HOME/projects}"
# Modelink Project Health Check Script

PROJECT_DIR="$PROJECTS_ROOT/Modelink"
HEALTH_LOG="/var/log/modelink-health.log"
DATE=$(date +%Y%m%d_%H%M%S)

echo "==========================================" >> "$HEALTH_LOG"
echo "Modelink Health Check - $DATE" >> "$HEALTH_LOG"
echo "==========================================" >> "$HEALTH_LOG"

# Check if project directory exists
if [ ! -d "$PROJECT_DIR" ]; then
    echo "ERROR: Modelink project directory not found" >> "$HEALTH_LOG"
    exit 1
fi

# Check Docker containers
echo "Checking Modelink Docker containers..." >> "$HEALTH_LOG"
cd "$PROJECT_DIR"
docker-compose ps >> "$HEALTH_LOG" 2>&1

# Check for running services
echo "Running services:" >> "$HEALTH_LOG"
docker-compose ps --services --filter "status=running" >> "$HEALTH_LOG" 2>&1

# Check disk usage for project
echo "Project disk usage:" >> "$HEALTH_LOG"
du -sh "$PROJECT_DIR" >> "$HEALTH_LOG"

# Check recent errors in logs (if docker logs available)
echo "Recent container logs (last 20 lines):" >> "$HEALTH_LOG"
docker-compose logs --tail=20 >> "$HEALTH_LOG" 2>&1

# Check if environment file exists
if [ -f "$PROJECT_DIR/.env" ]; then
    echo "Environment file: OK" >> "$HEALTH_LOG"
else
    echo "WARNING: Environment file missing" >> "$HEALTH_LOG"
fi

echo "Modelink health check completed: $DATE" >> "$HEALTH_LOG"
echo "==========================================" >> "$HEALTH_LOG"

logger -p user.info "Modelink project health check completed"
