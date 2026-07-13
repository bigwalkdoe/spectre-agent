# Spectre

Deployment orchestrator for containerized services. Pre-checks, builds, deploys, health-checks, and tracks deployments across environments.

## Quickstart

```bash
pip install -e ".[dev]"

# Deploy a service (uses config/services.toml and config/environments.toml)
spectre deploy api staging v1.2.3

# Override config values with CLI flags
spectre deploy api staging v1.2.3 --build-type pip --health-url http://localhost:9000/health

# Record the deploy in the changelog
spectre deploy api staging $(git rev-parse --short HEAD) --record

# View status
spectre status

# List deployments
spectre list

# Rollback
spectre rollback api staging
```

## Pipeline

```
spectre deploy <service> <env> <version>
  │
  ├── 1. pre_check     git clean? docker available?
  ├── 2. build         docker build / pip install
  ├── 3. deploy        docker compose up / kubectl set image
  ├── 4. health_check  HTTP GET health endpoint with retry
  └── 5. record        append to .spectre/deployments.json
```

Each stage runs sequentially. A failure stops the deployment immediately.

## Configuration

Service definitions go in `config/services.toml`, environments in `config/environments.toml`:

```toml
# config/services.toml
[api]
build_type = "docker"
deploy_type = "docker-compose"
port = 8000
```

```toml
# config/environments.toml
[staging]
compose_file = "docker-compose.yml"

[production]
compose_file = "docker-compose.prod.yml"
kube_namespace = "production"
```

Custom config paths can be specified with `--services` and `--environments`.

## State

Deployment history is persisted in `.spectre/deployments.json`.
