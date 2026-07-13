# CI/CD Pipeline Playbook

## Pipeline Stages

1. **Lint** — run on every PR, fail on warnings in strict mode
   - Python: `ruff check && ruff format --check`
   - TypeScript: `eslint && prettier --check`

2. **Typecheck** — mypy --strict or tsc --noEmit
   - Python: `mypy src/ --strict`
   - TypeScript: `tsc --noEmit`

3. **Security Scan** — dependency and code vulnerability checks
   - Run `safety check` or `npm audit`
   - Scan container images with Trivy
   - Check for hardcoded secrets with gitleaks

4. **Test** — unit + integration, with service containers (PostgreSQL, Redis)
   - Unit tests: `pytest` or `vitest`
   - Integration tests with docker-compose
   - Coverage threshold: 80%

5. **Build** — container image with semantic tags, push to registry
   - Use semantic versioning: `v1.2.3`
   - Build multi-stage Dockerfile
   - Push to ACR or GHCR

6. **Deploy staging** — auto-deploy on merge to develop
   - Apply Kubernetes manifests or docker-compose
   - Run database migrations
   - Verify deployment health

7. **Smoke test** — health check, critical path test
   - Check `/health` endpoint
   - Test critical user flows
   - Verify external integrations

8. **Deploy production** — manual approval or release tag trigger
   - Require approval from code owner
   - Blue-green deployment or canary release
   - Monitor rollback capability

9. **Monitor** — check error rates, latency, resource usage after deploy
   - Verify SLO compliance
   - Check error budget consumption
   - Monitor resource utilization

## Branch Strategy

- `main` — production, auto-deploy
- `develop` — staging, auto-deploy
- `feature/*` — PR-based, no deployment
- `hotfix/*` — direct to main, accelerated pipeline
