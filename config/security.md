# Deployment Configuration

Service and environment definitions live in TOML files under `config/`.

## Services (`config/services.toml`)

```toml
[api]
build_type = "docker"
deploy_type = "docker-compose"
build_context = "."
dockerfile = "Dockerfile"
health_endpoint = "/health"
port = 8000

[worker]
build_type = "docker"
deploy_type = "kubernetes"
build_context = "./worker"
```

## Environments (`config/environments.toml`)

```toml
[staging]
compose_file = "docker-compose.yml"

[production]
compose_file = "docker-compose.prod.yml"
kube_namespace = "production"
kube_context = "prod-cluster"

[development]
compose_file = "docker-compose.override.yml"
```

## CLI overrides

CLI flags override config values when both are provided:

```bash
spectre deploy api staging v2 --build-type pip --health-url http://localhost:9000/health
```
