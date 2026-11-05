#!/bin/bash
set -euo pipefail
# Distribution Detection Script
# Detects the Linux distribution and sets appropriate package manager and paths

# Detect Linux distribution
detect_distribution() {
    if [ -f /etc/os-release ]; then
        # shellcheck disable=SC1091  # resolved at runtime
        . /etc/os-release
        DISTRO=$ID
        DISTRO_VERSION=$VERSION_ID
        DISTRO_NAME=$PRETTY_NAME
    elif [ -f /etc/redhat-release ]; then
        DISTRO="rhel"
        DISTRO_VERSION=$(cat /etc/redhat-release | sed -n 's/.*release \([0-9.]*\).*/\1/p')
        DISTRO_NAME="Red Hat Enterprise Linux"
    elif [ -f /etc/debian_version ]; then
        DISTRO="debian"
        DISTRO_VERSION=$(cat /etc/debian_version)
        DISTRO_NAME="Debian"
    else
        DISTRO="unknown"
        DISTRO_VERSION="unknown"
        DISTRO_NAME="Unknown Linux Distribution"
    fi
    
    export DISTRO
    export DISTRO_VERSION
    export DISTRO_NAME
}

# Set package manager and commands based on distribution
set_package_manager() {
    case "$DISTRO" in
        fedora|rhel|centos|rocky|almalinux)
            PKG_MANAGER="dnf"
            PKG_INSTALL="sudo dnf install -y"
            PKG_REMOVE="sudo dnf remove -y"
            PKG_UPDATE="sudo dnf update -y"
            PKG_UPGRADE="sudo dnf upgrade -y"
            PKG_CLEAN="sudo dnf clean all"
            PKG_AUTOREMOVE="sudo dnf autoremove -y"
            PKG_SEARCH="dnf search"
            SERVICE_CMD="systemctl"
            FIREWALL_CMD="firewall-cmd"
            ;;
        ubuntu|debian|linuxmint|pop)
            PKG_MANAGER="apt"
            PKG_INSTALL="sudo apt install -y"
            PKG_REMOVE="sudo apt remove -y"
            PKG_UPDATE="sudo apt update"
            PKG_UPGRADE="sudo apt upgrade -y"
            PKG_CLEAN="sudo apt autoremove -y && sudo apt autoclean"
            PKG_AUTOREMOVE="sudo apt autoremove -y"
            PKG_SEARCH="apt search"
            SERVICE_CMD="systemctl"
            FIREWALL_CMD="ufw"
            ;;
        arch|manjaro)
            PKG_MANAGER="pacman"
            PKG_INSTALL="sudo pacman -S --noconfirm"
            PKG_REMOVE="sudo pacman -Rns --noconfirm"
            PKG_UPDATE="sudo pacman -Sy"
            PKG_UPGRADE="sudo pacman -Syu --noconfirm"
            PKG_CLEAN="sudo pacman -Sc --noconfirm"
            PKG_AUTOREMOVE="sudo pacman -Qtdq | sudo pacman -Rns --noconfirm -"
            PKG_SEARCH="pacman -Ss"
            SERVICE_CMD="systemctl"
            FIREWALL_CMD="ufw"
            ;;
        opensuse-leap|opensuse-tumbleweed)
            PKG_MANAGER="zypper"
            PKG_INSTALL="sudo zypper install -y"
            PKG_REMOVE="sudo zypper remove -y"
            PKG_UPDATE="sudo zypper refresh"
            PKG_UPGRADE="sudo zypper dup -y"
            PKG_CLEAN="sudo zypper clean"
            PKG_AUTOREMOVE="sudo zypper removerep -y"
            PKG_SEARCH="zypper search"
            SERVICE_CMD="systemctl"
            FIREWALL_CMD="firewall-cmd"
            ;;
        *)
            PKG_MANAGER="unknown"
            PKG_INSTALL="echo Unsupported-distribution:"
            PKG_REMOVE="echo Unsupported-distribution:"
            PKG_UPDATE="echo Unsupported-distribution:"
            PKG_UPGRADE="echo Unsupported-distribution:"
            PKG_CLEAN="echo Unsupported-distribution:"
            PKG_AUTOREMOVE="echo Unsupported-distribution:"
            PKG_SEARCH="echo Unsupported-distribution:"
            SERVICE_CMD="systemctl"
            FIREWALL_CMD="echo Unknown-firewall"
            ;;
    esac
    
    export PKG_MANAGER
    export PKG_INSTALL
    export PKG_REMOVE
    export PKG_UPDATE
    export PKG_UPGRADE
    export PKG_CLEAN
    export PKG_AUTOREMOVE
    export PKG_SEARCH
    export SERVICE_CMD
    export FIREWALL_CMD
}

# Set distribution-specific paths
set_distribution_paths() {
    case "$DISTRO" in
        fedora|rhel|centos|rocky|almalinux)
            LOG_DIR="/var/log"
            CACHE_DIR="/var/cache"
            TEMP_DIR="/tmp"
            CONFIG_DIR="/etc"
            BACKUP_DIR="/backups"
            ;;
        ubuntu|debian|linuxmint|pop)
            LOG_DIR="/var/log"
            CACHE_DIR="/var/cache"
            TEMP_DIR="/tmp"
            CONFIG_DIR="/etc"
            BACKUP_DIR="/backups"
            ;;
        arch|manjaro)
            LOG_DIR="/var/log"
            CACHE_DIR="/var/cache"
            TEMP_DIR="/tmp"
            CONFIG_DIR="/etc"
            BACKUP_DIR="/backups"
            ;;
        *)
            LOG_DIR="/var/log"
            CACHE_DIR="/var/cache"
            TEMP_DIR="/tmp"
            CONFIG_DIR="/etc"
            BACKUP_DIR="/backups"
            ;;
    esac
    
    export LOG_DIR
    export CACHE_DIR
    export TEMP_DIR
    export CONFIG_DIR
    export BACKUP_DIR
}

# Check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Install package with fallback
install_package() {
    local package=$1
    echo "Installing $package..."
    
    case "$PKG_MANAGER" in
        dnf)
            $PKG_INSTALL "$package"
            ;;
        apt)
            $PKG_UPDATE
            $PKG_INSTALL "$package"
            ;;
        pacman)
            $PKG_UPDATE
            $PKG_INSTALL "$package"
            ;;
        zypper)
            $PKG_UPDATE
            $PKG_INSTALL "$package"
            ;;
        *)
            echo "Cannot install $package: Unknown package manager"
            return 1
            ;;
    esac
}

# Main execution
main() {
    detect_distribution
    set_package_manager
    set_distribution_paths
    
    echo "Detected Distribution: $DISTRO_NAME ($DISTRO $DISTRO_VERSION)"
    echo "Package Manager: $PKG_MANAGER"
    echo "Service Manager: $SERVICE_CMD"
    echo "Firewall Command: $FIREWALL_CMD"
}

# Run main function if script is executed directly
if [ "${BASH_SOURCE[0]}" == "${0}" ]; then
    main
fi

# Export functions for use in other scripts
export -f detect_distribution
export -f set_package_manager
export -f set_distribution_paths
export -f command_exists
export -f install_package
