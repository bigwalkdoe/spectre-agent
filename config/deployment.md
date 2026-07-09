# Deployment Standards

## Containers

- **Base images**: python:3.12-slim for Python services, node:22-alpine for Node/Next.js
- **Multi-stage builds**: build stage + production stage
- **Health checks**: Define `HEALTHCHECK` in Dockerfile
- **Non-root user**: Create and use a non-root user in the final stage
- **Labels**: Maintain `org.opencontainers.image.*` labels

## CI/CD (GitHub Actions)

- Lint and format check on every PR.
- Run tests on every push to `feat/*` and `fix/*` branches.
- Build and push container images on merge to `develop`.
- Deploy to staging on merge to `develop`.
- Deploy to production on merge to `main` (or release tag).

## Container Image Tags

- Never use `:latest` in production manifests — pin to specific SHA or semver.
- Use `${{ github.sha }}` as primary tag with `${{ github.ref_name }}` as alias.

## Environments

- **Local**: Podman Compose with env_file for secrets
- **Staging**: Fedora server or GitHub Codespaces
- **Production**: Fedora server or cloud VPS

## Database Migrations

- Run `alembic upgrade head` as a separate step before app starts (init container or CI pipeline).
- Never auto-migrate on app startup in production.
