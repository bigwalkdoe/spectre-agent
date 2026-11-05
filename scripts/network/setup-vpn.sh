#!/bin/bash
set -euo pipefail

# WireGuard VPN Setup Script
# Sets up WireGuard server and client configurations

WG_DIR="/etc/wireguard"
WG_INTERFACE="wg0"
WG_PORT="${WG_PORT:-51820}"
WG_SUBNET="${WG_SUBNET:-10.8.0.0/24}"
SERVER_PRIVATE_KEY_FILE="${WG_DIR}/server_private.key"
SERVER_PUBLIC_KEY_FILE="${WG_DIR}/server_public.key"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log "ERROR: This script must be run as root"
        exit 1
    fi
}

install_wireguard() {
    log "Installing WireGuard..."
    if command -v apt-get &>/dev/null; then
        apt-get update && apt-get install -y wireguard wireguard-tools qrencode
    elif command -v dnf &>/dev/null; then
        dnf install -y wireguard-tools qrencode
    elif command -v yum &>/dev/null; then
        yum install -y epel-release && yum install -y wireguard-tools qrencode
    elif command -v pacman &>/dev/null; then
        pacman -S --noconfirm wireguard-tools qrencode
    else
        log "ERROR: Unsupported package manager"
        exit 1
    fi
}

generate_server_keys() {
    log "Generating server keys..."
    mkdir -p "$WG_DIR"
    chmod 700 "$WG_DIR"
    
    wg genkey | tee "$SERVER_PRIVATE_KEY_FILE" | wg pubkey > "$SERVER_PUBLIC_KEY_FILE"
    chmod 600 "$SERVER_PRIVATE_KEY_FILE"
    chmod 644 "$SERVER_PUBLIC_KEY_FILE"
    
    SERVER_PRIVATE_KEY=$(cat "$SERVER_PRIVATE_KEY_FILE")
}

create_server_config() {
    log "Creating server config..."
    local server_ip
    server_ip=$(echo "$WG_SUBNET" | cut -d'/' -f1 | sed 's/\.[0-9]*$/.1/')
    local cidr
    cidr=$(echo "$WG_SUBNET" | cut -d'/' -f2)
    
    cat > "${WG_DIR}/${WG_INTERFACE}.conf" <<EOF
[Interface]
Address = ${server_ip}/${cidr}
ListenPort = ${WG_PORT}
PrivateKey = ${SERVER_PRIVATE_KEY}
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -o $(ip route | grep default | awk '{print $5}') -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -o $(ip route | grep default | awk '{print $5}') -j MASQUERADE
SaveConfig = false
EOF
    chmod 600 "${WG_DIR}/${WG_INTERFACE}.conf"
}

enable_ip_forwarding() {
    log "Enabling IP forwarding..."
    echo 'net.ipv4.ip_forward=1' > /etc/sysctl.d/99-wireguard.conf
    echo 'net.ipv6.conf.all.forwarding=1' >> /etc/sysctl.d/99-wireguard.conf
    sysctl --system
}

configure_firewall() {
    log "Configuring firewall..."
    if command -v ufw &>/dev/null; then
        ufw allow "${WG_PORT}/udp"
        ufw reload
    elif command -v firewall-cmd &>/dev/null; then
        firewall-cmd --permanent --add-port="${WG_PORT}/udp"
        firewall-cmd --permanent --add-masquerade
        firewall-cmd --reload
    else
        iptables -A INPUT -p udp --dport "${WG_PORT}" -j ACCEPT
        iptables-save > /etc/iptables/rules.v4 2>/dev/null || true
    fi
}

enable_and_start() {
    log "Enabling and starting WireGuard..."
    systemctl enable "wg-quick@${WG_INTERFACE}"
    systemctl start "wg-quick@${WG_INTERFACE}"
}

add_client() {
    local client_name="$1"
    local client_ip="$2"
    
    if [[ -z "$client_name" || -z "$client_ip" ]]; then
        log "Usage: $0 add-client <name> <ip>"
        exit 1
    fi
    
    log "Adding client: $client_name with IP: $client_ip"
    
    local client_private_key
    client_private_key=$(wg genkey)
    local client_public_key
    client_public_key=$(echo "$client_private_key" | wg pubkey)
    local client_preshared_key
    client_preshared_key=$(wg genpsk)
    
    cat >> "${WG_DIR}/${WG_INTERFACE}.conf" <<EOF

[Peer]
# $client_name
PublicKey = ${client_public_key}
PresharedKey = ${client_preshared_key}
AllowedIPs = ${client_ip}/32
EOF
    
    local server_public_key
    server_public_key=$(cat "$SERVER_PUBLIC_KEY_FILE")
    local server_endpoint
    server_endpoint=$(curl -s ifconfig.me || curl -s icanhazip.com):${WG_PORT}
    
    cat > "${WG_DIR}/${client_name}.conf" <<EOF
[Interface]
PrivateKey = ${client_private_key}
Address = ${client_ip}/32
DNS = 1.1.1.1, 8.8.8.8

[Peer]
PublicKey = ${server_public_key}
PresharedKey = ${client_preshared_key}
Endpoint = ${server_endpoint}
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
EOF
    
    chmod 600 "${WG_DIR}/${client_name}.conf"
    
    log "Client config saved to ${WG_DIR}/${client_name}.conf"
    qrencode -t ansiutf8 < "${WG_DIR}/${client_name}.conf"
    
    systemctl reload "wg-quick@${WG_INTERFACE}"
}

show_status() {
    wg show
}

main() {
    check_root
    
    case "${1:-setup}" in
        setup)
            install_wireguard
            generate_server_keys
            create_server_config
            enable_ip_forwarding
            configure_firewall
            enable_and_start
            show_status
            log "WireGuard server setup complete!"
            log "Add clients with: $0 add-client <name> <ip>"
            ;;
        add-client)
            add_client "$2" "$3"
            ;;
        status)
            show_status
            ;;
        *)
            echo "Usage: $0 {setup|add-client|status}"
            exit 1
            ;;
    esac
}

main "$@"