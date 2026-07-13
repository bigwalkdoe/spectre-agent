# Spectre Agent

Deployment orchestrator for containerized services. Pre-checks, builds, deploys, health-checks, and tracks deployments across environments.

## Quickstart

```bash
pip install -e ".[dev]"

# Deploy a service
spectre deploy my-api staging v1.2.3

# Deploy with build/deploy options
spectre deploy my-api staging v1.2.3 \
  --build-type docker \
  --deploy-type docker-compose \
  --health-url http://localhost:8000/health

# Record in changelog
spectre deploy my-api staging $(git rev-parse --short HEAD) --record

# View status
spectre status

# List deployments
spectre list

# Rollback
spectre rollback my-api staging
```

## Architecture

```
spectre deploy <service> <env> <version>
  │
  ├── 1. pre_check     git clean? tools available?
  ├── 2. build         docker build / pip install
  ├── 3. deploy        docker compose up / kubectl set image
  ├── 4. health_check  HTTP GET /health with retry
  └── 5. record        append to .spectre/deployments.json
```

Each stage runs sequentially. If any stage fails, the deployment is marked `failed` and stops immediately.

## State

Deployment history is stored in `.spectre/deployments.json`. This file tracks every deployment with per-step results and timing.

## Configuration

Service and environment definitions go in `config/services.yaml` and `config/environments.yaml`. See `config/` for examples.
