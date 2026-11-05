#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROJECTS_ROOT="${PROJECTS_ROOT:-$HOME/projects}"
# Multi-Server Management Script
# Foundation for managing multiple servers from a central location

SERVERS_FILE="$REPO_ROOT/config/servers.conf"
LOG_DIR="/var/log/multi-server"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$LOG_DIR"

# Create servers configuration file if it doesn't exist
if [ ! -f "$SERVERS_FILE" ]; then
    echo "# Server Configuration File" > "$SERVERS_FILE"
    echo "# Format: SERVER_NAME,SSH_USER,SSH_HOST,SSH_PORT" >> "$SERVERS_FILE"
    echo "# Example: production-server-1,admin,192.168.1.100,22" >> "$SERVERS_FILE"
    echo "" >> "$SERVERS_FILE"
    echo "# Add your servers below:" >> "$SERVERS_FILE"
    echo "local,deon,localhost,22" >> "$SERVERS_FILE"
fi

# Function to execute command on remote server
execute_on_server() {
    local server_name=${1:-}
    local ssh_user=${2:-}
    local ssh_host=${3:-}
    local ssh_port=$4
    local command=$5
    
    echo "Executing on $server_name ($ssh_user@$ssh_host:$ssh_port)..."
    ssh -p "$ssh_port" "$ssh_user@$ssh_host" "$command" 2>&1
}

# Function to check server health
check_server_health() {
    local server_name=${1:-}
    local ssh_user=${2:-}
    local ssh_host=${3:-}
    local ssh_port=$4
    
    echo "Checking health of $server_name..."
    HEALTH_LOG="$LOG_DIR/${server_name}_health_${DATE}.log"
    
    execute_on_server "$server_name" "$ssh_user" "$ssh_host" "$ssh_port" "
        echo '=== System Information ==='
        uname -a
        echo ''
        echo '=== Disk Usage ==='
        df -h
        echo ''
        echo '=== Memory Usage ==='
        free -h
        echo ''
        echo '=== CPU Usage ==='
        top -bn1 | head -20
        echo ''
        echo '=== Running Services ==='
        systemctl list-units --type=service --state=running | head -20
        echo ''
        echo '=== Docker Containers ==='
        docker ps --format 'table {{.Names}}\t{{.Status}}'
    " > "$HEALTH_LOG"
    
    echo "Health check saved to $HEALTH_LOG"
}

# Function to deploy maintenance scripts to remote server
deploy_maintenance_scripts() {
    local server_name=${1:-}
    local ssh_user=${2:-}
    local ssh_host=${3:-}
    local ssh_port=$4
    
    echo "Deploying maintenance scripts to $server_name..."
    
    # Copy maintenance scripts directory
    scp -P "$ssh_port" -r "$REPO_ROOT/scripts/" \
        "$ssh_user@$ssh_host:/tmp/maintenance-scripts/"
    
    # Install scripts on remote server
    execute_on_server "$server_name" "$ssh_user" "$ssh_host" "$ssh_port" "
        sudo mkdir -p /usr/local/bin/
        sudo cp /tmp/maintenance-scripts/backups/*.sh /usr/local/bin/
        sudo cp /tmp/maintenance-scripts/maintenance/*.sh /usr/local/bin/
        sudo cp /tmp/maintenance-scripts/performance/*.sh /usr/local/bin/
        sudo cp /tmp/maintenance-scripts/network/*.sh /usr/local/bin/
        sudo cp /tmp/maintenance-scripts/security/*.sh /usr/local/bin/
        sudo chmod +x /usr/local/bin/*.sh
        sudo rm -rf /tmp/maintenance-scripts
        echo 'Maintenance scripts deployed successfully'
    "
}

# Function to check status of all servers
check_all_servers() {
    echo "Checking all servers..."
    ALL_HEALTH_LOG="$LOG_DIR/all_servers_health_${DATE}.log"
    
    while IFS=',' read -r server_name ssh_user ssh_host ssh_port; do
        # Skip comments and empty lines
        [[ "$server_name" =~ ^#.*$ ]] && continue
        [[ -z "$server_name" ]] && continue
        
        echo "=== $server_name ===" >> "$ALL_HEALTH_LOG"
        check_server_health "$server_name" "$ssh_user" "$ssh_host" "$ssh_port"
        echo "" >> "$ALL_HEALTH_LOG"
    done < "$SERVERS_FILE"
    
    echo "All servers health check completed. Log saved to $ALL_HEALTH_LOG"
}

# Function to sync backups from remote servers
sync_remote_backups() {
    local server_name=${1:-}
    local ssh_user=${2:-}
    local ssh_host=${3:-}
    local ssh_port=$4
    
    echo "Syncing backups from $server_name..."
    mkdir -p "/backups/remote/$server_name"
    
    scp -P "$ssh_port" -r "$ssh_user@$ssh_host:/backups/" \
        "/backups/remote/$server_name/"
    
    echo "Backups synced from $server_name"
}

# Main menu
case "${1:-}" in
    check-health)
        if [ -n "${2:-}" ]; then
            # Check specific server
            while IFS=',' read -r name user host port; do
                [[ "$name" =~ ^#.*$ ]] && continue
                [[ -z "$name" ]] && continue
                if [ "$name" = "${2:-}" ]; then
                    check_server_health "$name" "$user" "$host" "$port"
                    break
                fi
            done < "$SERVERS_FILE"
        else
            # Check all servers
            check_all_servers
        fi
        ;;
    deploy-scripts)
        if [ -n "${2:-}" ]; then
            while IFS=',' read -r name user host port; do
                [[ "$name" =~ ^#.*$ ]] && continue
                [[ -z "$name" ]] && continue
                if [ "$name" = "${2:-}" ]; then
                    deploy_maintenance_scripts "$name" "$user" "$host" "$port"
                    break
                fi
            done < "$SERVERS_FILE"
        else
            echo "Usage: $0 deploy-scripts <server_name>"
            exit 1
        fi
        ;;
    sync-backups)
        if [ -n "${2:-}" ]; then
            while IFS=',' read -r name user host port; do
                [[ "$name" =~ ^#.*$ ]] && continue
                [[ -z "$name" ]] && continue
                if [ "$name" = "${2:-}" ]; then
                    sync_remote_backups "$name" "$user" "$host" "$port"
                    break
                fi
            done < "$SERVERS_FILE"
        else
            echo "Syncing backups from all servers..."
            while IFS=',' read -r name user host port; do
                [[ "$name" =~ ^#.*$ ]] && continue
                [[ -z "$name" ]] && continue
                sync_remote_backups "$name" "$user" "$host" "$port"
            done < "$SERVERS_FILE"
        fi
        ;;
    list-servers)
        echo "Configured servers:"
        while IFS=',' read -r name user host port; do
            [[ "$name" =~ ^#.*$ ]] && continue
            [[ -z "$name" ]] && continue
            echo "  - $name: $user@$host:$port"
        done < "$SERVERS_FILE"
        ;;
    add-server)
        if [ -z "${4:-}" ]; then
            echo "Usage: $0 add-server <name> <user> <host> <port>"
            exit 1
        fi
        echo "${1:-},${2:-},${3:-},${4:-}" >> "$SERVERS_FILE"
        echo "Server ${1:-} added to configuration"
        ;;
    *)
        echo "Multi-Server Management Script"
        echo ""
        echo "Usage: $0 <command> [arguments]"
        echo ""
        echo "Commands:"
        echo "  check-health [server_name]   - Check health of all servers or specific server"
        echo "  deploy-scripts <server_name> - Deploy maintenance scripts to server"
        echo "  sync-backups [server_name]   - Sync backups from remote servers"
        echo "  list-servers                 - List all configured servers"
        echo "  add-server <name> <user> <host> <port> - Add new server"
        echo ""
        exit 1
        ;;
esac
