#!/bin/bash
# API Security Monitoring Script

SECURITY_LOG="$HOME/.local/share/api-security.log"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p $HOME/.local/share

echo "==========================================" >> "$SECURITY_LOG"
echo "API Security Monitor - $DATE" >> "$SECURITY_LOG"
echo "==========================================" >> "$SECURITY_LOG"

# Monitor API endpoints
echo "API Endpoint Status:" >> "$SECURITY_LOG"
curl -s http://localhost:8000/health >/dev/null 2>&1 && echo "API Health: OK" >> "$SECURITY_LOG" || echo "API Health: FAILED" >> "$SECURITY_LOG"

# Check for suspicious API calls
echo "Recent API calls:" >> "$SECURITY_LOG"
sudo journalctl -u docker -n 50 | grep -i "api" | tail -5 >> "$SECURITY_LOG"

# Check Fail2Ban status
echo "Fail2Ban Status:" >> "$SECURITY_LOG"
sudo fail2ban-client status nginx-limit 2>/dev/null || echo "nginx-limit jail not active" >> "$SECURITY_LOG"

echo "API security monitoring completed: $DATE" >> "$SECURITY_LOG"
