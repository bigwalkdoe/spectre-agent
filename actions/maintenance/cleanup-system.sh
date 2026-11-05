#!/bin/bash
set -euo pipefail
# System Cleanup Script
# Performs regular system maintenance tasks (Distribution-agnostic)

# Source distribution detection
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
# shellcheck disable=SC1091  # resolved at runtime
source "$PROJECT_ROOT/detect-distribution.sh"

# Initialize distribution settings
detect_distribution
set_package_manager
set_distribution_paths

echo "Starting system maintenance cleanup for $DISTRO_NAME..."

# Clean package cache
echo "Cleaning $PKG_MANAGER package cache..."
$PKG_CLEAN

# Clean old journal logs (keep last 7 days)
echo "Cleaning old journal logs..."
if command -v journalctl >/dev/null 2>&1; then
    sudo journalctl --vacuum-time=7d
else
    echo "journalctl not available, skipping log cleanup"
fi

# Clean temporary files
echo "Cleaning temporary files..."
sudo rm -rf /tmp/* /var/tmp/* 2>/dev/null || true

# Clean user cache
echo "Cleaning user cache..."
# Clean generic cache directories
rm -rf ~/.cache/* 2>/dev/null || true

# Clean browser caches (if they exist)
rm -rf ~/.cache/mozilla/firefox/*/cache2 2>/dev/null || true
rm -rf ~/.config/google-chrome/Default/Cache 2>/dev/null || true
rm -rf ~/.config/chromium/Default/Cache 2>/dev/null || true
rm -rf ~/.cache/evolution 2>/dev/null || true
rm -rf ~/.cache/thumbnails 2>/dev/null || true

# Clean old downloads (older than 30 days)
echo "Cleaning old downloads..."
find ~/Downloads -type f -mtime +30 -delete 2>/dev/null || true

# Clean trash
echo "Emptying trash..."
rm -rf ~/.local/share/Trash/* 2>/dev/null || true
rm -rf ~/.trash/* 2>/dev/null || true

# Distribution-specific cleanup
case "$DISTRO" in
    ubuntu|debian)
        echo "Running Debian/Ubuntu specific cleanup..."
        # Clean old kernels (keep last 2)
        if [ "$PKG_MANAGER" = "apt" ]; then
            sudo apt autoremove -y
            sudo apt autoclean
        fi
        ;;
    fedora|rhel|centos)
        echo "Running Fedora/RHEL specific cleanup..."
        # Remove old package versions
        if [ "$PKG_MANAGER" = "dnf" ]; then
            sudo dnf autoremove -y
            sudo dnf clean all
        fi
        ;;
    arch|manjaro)
        echo "Running Arch specific cleanup..."
        if [ "$PKG_MANAGER" = "pacman" ]; then
            sudo pacman -Sc --noconfirm
            # Remove orphan packages
            if pacman -Qtdq >/dev/null 2>&1; then
                mapfile -t ORPHANS < <(pacman -Qtdq 2>/dev/null || true)
                if [ "${#ORPHANS[@]}" -gt 0 ]; then
                    sudo pacman -Rns --noconfirm -- "${ORPHANS[@]}"
                fi
            fi
        fi
        ;;
esac

# Docker system cleanup
if command -v docker >/dev/null 2>&1; then
    echo "Cleaning Docker system..."
    docker system prune -f --volumes
    
    echo "Cleaning Docker build cache..."
    if docker builder prune >/dev/null 2>&1; then
        docker builder prune -f
    fi
else
    echo "Docker not found, skipping Docker cleanup"
fi

# Additional cleanup for specific distributions
if [ "$DISTRO" = "ubuntu" ] || [ "$DISTRO" = "debian" ]; then
    # Clean apt lists
    sudo rm -rf /var/lib/apt/lists/* 2>/dev/null || true
fi

echo "System cleanup completed for $DISTRO_NAME!"
logger -p user.info "System maintenance cleanup completed for $DISTRO_NAME"
