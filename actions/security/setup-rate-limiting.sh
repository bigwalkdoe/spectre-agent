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
