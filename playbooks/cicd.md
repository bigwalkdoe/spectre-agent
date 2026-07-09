# CI/CD Pipeline Playbook

## Steps

1. **Lint** — run on every PR, fail on warnings in strict mode
2. **Typecheck** — mypy --strict or tsc --noEmit
3. **Test** — unit + integration, with service containers (PostgreSQL, Redis)
4. **Build** — container image with semantic tags, push to registry
5. **Deploy staging** — auto-deploy on merge to develop
6. **Smoke test** — health check, critical path test
7. **Deploy production** — manual approval or release tag trigger
8. **Monitor** — check error rates, latency, resource usage after deploy
