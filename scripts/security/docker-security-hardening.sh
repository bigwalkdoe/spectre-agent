#!/bin/bash
set -euo pipefail
# Docker Container Security Hardening (Distribution-agnostic)

# Source distribution detection
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
# shellcheck disable=SC1091  # resolved at runtime
source "$PROJECT_ROOT/detect-distribution.sh"

# Initialize distribution settings
detect_distribution
set_package_manager

echo "Hardening Docker container security for $DISTRO_NAME..."

# Install Trivy vulnerability scanner
install_trivy() {
    if command -v trivy >/dev/null 2>&1; then
        echo "Trivy is already installed"
        return 0
    fi

    echo "Installing Trivy vulnerability scanner..."
    
    case "$PKG_MANAGER" in
        dnf)
            # Try dnf first
            $PKG_INSTALL trivy 2>/dev/null || {
                # Fallback to direct download
                echo "Installing Trivy from release..."
                wget -qO - https://github.com/aquasecurity/trivy/releases/download/v0.50.0/trivy_0.50.0_Linux-64bit.tar.gz | tar -xz
                sudo mv trivy /usr/local/bin/
                sudo chmod +x /usr/local/bin/trivy
            }
            ;;
        apt)
            # Add Trivy repository for Debian/Ubuntu
            sudo apt-get install wget apt-transport-https gnupg lsb-release -y
            wget -qO - https://aquasecurity.github.io/trivy-repo/deb/public.key | sudo apt-key add -
            echo "deb https://aquasecurity.github.io/trivy-repo/deb $(lsb_release -sc) main" | sudo tee -a /etc/apt/sources.list.d/trivy.list
            $PKG_UPDATE
            $PKG_INSTALL trivy
            ;;
        pacman)
            # Install from AUR or download binary
            wget -qO - https://github.com/aquasecurity/trivy/releases/download/v0.50.0/trivy_0.50.0_Linux-64bit.tar.gz | tar -xz
            sudo mv trivy /usr/local/bin/
            sudo chmod +x /usr/local/bin/trivy
            ;;
        zypper)
            wget -qO - https://github.com/aquasecurity/trivy/releases/download/v0.50.0/trivy_0.50.0_Linux-64bit.tar.gz | tar -xz
            sudo mv trivy /usr/local/bin/
            sudo chmod +x /usr/local/bin/trivy
            ;;
        *)
            echo "Cannot install Trivy automatically for $PKG_MANAGER"
            echo "Please install Trivy manually from: https://github.com/aquasecurity/trivy"
            return 1
            ;;
    esac
}

# Create Docker security scan script
create_docker_scan_script() {
    local scan_dir="$SCRIPT_DIR/security"
    sudo mkdir -p "$scan_dir"
    
    cat > "$scan_dir/scan-docker-images.sh" << 'EOF'
#!/bin/bash
# Docker Image Vulnerability Scanner

echo "Scanning Docker images for vulnerabilities..."

# Check if Trivy is available
if ! command -v trivy >/dev/null 2>&1; then
    echo "Trivy is not installed. Please install it first."
    exit 1
fi

# Scan running containers
if command -v docker >/dev/null 2>&1; then
    echo "Scanning running containers..."
    docker ps --format "{{.Image}}" | sort -u | while read image; do
        echo "Scanning image: $image"
        trivy image --severity HIGH,CRITICAL "$image" || echo "Failed to scan $image"
    done
else
    echo "Docker is not installed or not running"
fi

echo "Docker image scanning completed!"
EOF
    
    chmod +x "$scan_dir/scan-docker-images.sh"
}

# Install Trivy
install_trivy

# Create and run Docker scan script
echo "Creating Docker scan script..."
create_docker_scan_script

echo "Running Docker image vulnerability scan..."
"$SCRIPT_DIR/scan-docker-images.sh"

# Set up Docker security policies
echo "Setting up Docker security policies..."

# Check if Docker is installed
if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is not installed. Skipping Docker security configuration."
    exit 0
fi

# Create Docker daemon security configuration
sudo bash -c 'cat > /etc/docker/daemon-security.json << "EOF"
{
  "live-restore": true,
  "userland-proxy": false,
  "no-new-privileges": true,
  "icc": false,
  "disable-legacy-registry": true,
  "default-runtime": "runc",
  "runtimes": {
    "runc": {
      "path": "runc",
      "runtimeArgs": []
    }
  }
}
EOF'

# Merge with existing daemon.json if it exists
if [ -f /etc/docker/daemon.json ]; then
    # Check if jq is available for JSON merging
    if command -v jq >/dev/null 2>&1; then
        echo "Merging with existing Docker daemon configuration..."
        sudo bash -c 'jq -s ".[0] * .[1]" /etc/docker/daemon.json /etc/docker/daemon-security.json > /tmp/daemon-merged.json'
        sudo mv /tmp/daemon-merged.json /etc/docker/daemon.json
    else
        echo "jq not found, keeping original daemon.json. Security config saved as daemon-security.json"
        echo "Please manually merge the configurations"
    fi
else
    echo "Setting Docker daemon security configuration as default..."
    sudo cp /etc/docker/daemon-security.json /etc/docker/daemon.json
fi

# Configure Docker user namespace remapping (optional, enhanced security)
echo "Configuring Docker user namespace remapping..."
sudo bash -c 'cat >> /etc/docker/daemon.json << "EOF"
  "userns-remap": "default"
EOF' 2>/dev/null || echo "Could not configure user namespace remapping"

# Set up Docker daemon reload based on distribution
echo "Docker security policies configured."
case "$DISTRO" in
    ubuntu|debian)
        echo "Restart Docker to apply changes with: sudo systemctl restart docker"
        ;;
    fedora|rhel|centos)
        echo "Restart Docker to apply changes with: sudo systemctl restart docker"
        ;;
    arch|manjaro)
        echo "Restart Docker to apply changes with: sudo systemctl restart docker"
        ;;
    *)
        echo "Restart Docker service to apply changes"
        ;;
esac

echo "Docker security hardening completed for $DISTRO_NAME!"
