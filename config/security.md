# Security Standards

## Prohibited

- Committing `.env` files, secrets, API keys, tokens, certificates, or passwords.
- Hardcoded credentials in source code — use environment variables or secret managers.
- Logging sensitive data (PII, tokens, passwords).
- Running containers as root without justification.

## Required

- Input validation on all API endpoints (Pydantic models).
- Parameterized SQL queries — never string concatenation.
- HTTPS in production.
- CORS configured with explicit allowed origins.
- Rate limiting on public endpoints.
- Authentication via JWT or API keys — no session-based auth for APIs.

## Dependency Security

- Pin major dependency versions in requirements.txt and package.json.
- Run `pip-audit` or `npm audit` periodically.
- Use Dependabot or Renovate for automated updates.
