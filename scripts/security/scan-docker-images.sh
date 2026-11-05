#!/bin/bash
set -euo pipefail
# Docker Image Vulnerability Scanner

echo "Scanning Docker images for vulnerabilities..."

# Install Trivy if not available
if ! command -v trivy >/dev/null 2>&1; then
    echo "Installing Trivy vulnerability scanner..."
    sudo dnf install -y trivy || {
        # Install from release if not in repo
        wget -qO - https://github.com/aquasecurity/trivy/releases/download/v0.50.0/trivy_0.50.0_Linux-64bit.tar.gz | tar -xz
        sudo mv trivy /usr/local/bin/
        sudo chmod +x /usr/local/bin/trivy
    }
fi

# Scan running containers
echo "Scanning running containers..."
docker ps --format "{{.Image}}" | sort -u | while read -r image; do
    echo "Scanning image: $image"
    trivy image --severity HIGH,CRITICAL "$image" || echo "Failed to scan $image"
done

echo "Docker image scanning completed!"
