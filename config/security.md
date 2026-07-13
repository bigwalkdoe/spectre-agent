# Deployment Configurations

Service and environment definitions for the orchestrator.

## Services

```yaml
services:
  my-api:
    build_type: docker
    deploy_type: docker-compose
    build_context: .
    dockerfile: Dockerfile
    health_endpoint: /health
    port: 8000
```

## Environments

```yaml
environments:
  staging:
    compose_file: docker-compose.yml
    hosts:
      - localhost
  production:
    compose_file: docker-compose.prod.yml
    hosts:
      - app1.example.com
      - app2.example.com
```
