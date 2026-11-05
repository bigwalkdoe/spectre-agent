#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECTS_ROOT="${PROJECTS_ROOT:-$HOME/projects}"
# API Security Hardening Script

echo "Hardening API security configurations..."

# Check Guardrail-AI API configuration
GUARDRAIL_DIR="$PROJECTS_ROOT/Guardrail-AI"

if [ -d "$GUARDRAIL_DIR" ]; then
    echo "Configuring API security for Guardrail-AI..."
    
    # Create Nginx reverse proxy configuration with security headers
    mkdir -p "$GUARDRAIL_DIR/docker/nginx-security"
    
    cat > "$GUARDRAIL_DIR/docker/nginx-security/security.conf" << 'EOF'
# Security Headers
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-XSS-Protection "1; mode=block" always;
add_header Referrer-Policy "no-referrer-when-downgrade" always;
add_header Content-Security-Policy "default-src 'self' http: https: data: blob: 'unsafe-inline'" always;

# Rate Limiting
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
limit_conn_zone $binary_remote_addr zone=conn_limit:10m;

# Security Settings
client_max_body_size 10M;
client_body_timeout 12s;
client_header_timeout 12s;
EOF
    
    echo "Security headers and rate limiting configuration created"
    echo "Add this configuration to your Nginx reverse proxy to enable security hardening"
fi

# Create API rate limiting configuration for Docker services
cat > "$SCRIPT_DIR/setup-rate-limiting.sh" << 'EOF'
#!/bin/bash
# Setup API Rate Limiting with Docker

echo "Setting up API rate limiting..."

# Install and configure fail2ban for API protection
if ! grep -q "\[nginx-limit\]" /etc/fail2ban/jail.local 2>/dev/null; then
    echo "Adding API rate limiting to Fail2Ban..."
    sudo bash -c 'cat >> /etc/fail2ban/jail.local << "EOT"

[nginx-limit]
enabled = true
port = http,https
logpath = /var/log/nginx/error.log
maxretry = 5
findtime = 60
bantime = 1h
EOT'
    
    sudo systemctl restart fail2ban
    echo "API rate limiting configured in Fail2Ban"
fi

echo "API rate limiting setup completed!"
EOF

chmod +x "$SCRIPT_DIR/setup-rate-limiting.sh"

# Run rate limiting setup
"$SCRIPT_DIR/setup-rate-limiting.sh"

# Create API monitoring script
cat > "$SCRIPT_DIR/monitor-api-security.sh" << 'EOF'
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
EOF

chmod +x "$SCRIPT_DIR/monitor-api-security.sh"

echo "API security hardening completed!"
logger -p user.info "API security hardening completed"
