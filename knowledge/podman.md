# Podman Knowledge

- Rootless by default — no `sudo` needed
- Podman Compose: `podman-compose up -d`
- Build: `podman build -t name:tag .`
- Run: `podman run -d --name name image:tag`
- Logs: `podman logs -f container_name`
- Network: `podman network create mynet`
- Pods: `podman pod create --name mypod`
- Systemd integration: `podman generate systemd --name container`
