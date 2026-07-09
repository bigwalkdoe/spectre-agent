# Security Audit Playbook

## Steps

1. **Review dependencies** — run `pip-audit` or `npm audit`, check for known CVEs
2. **Scan for secrets** — run `~/.spectre/scripts/security.sh .`
3. **Check authentication** — verify JWT validation, token expiry, password hashing (bcrypt/argon2)
4. **Check authorization** — ensure role/permission checks on every protected endpoint
5. **Review input validation** — Pydantic models on all public endpoints, no raw user input in HTML/SQL
6. **Check CORS** — explicit origins, no wildcard in production
7. **Review rate limiting** — verify limits on auth, public endpoints
8. **Check HTTPS configuration** — TLS version, HSTS headers
9. **Review logging** — no PII, tokens, or secrets in logs
10. **Check file permissions** — no world-readable secrets, configs
11. **Review container security** — non-root user, read-only root FS where possible, no privileged mode
12. **Document findings** — severity, impact, remediation steps
