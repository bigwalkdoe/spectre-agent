# Git Workflow

## Branch Strategy

- `main` — production-ready, protected
- `develop` — integration branch
- `feat/*` — feature branches from develop
- `fix/*` — bugfix branches
- `chore/*` — maintenance tasks

## Commits

Format: `type(scope): description`

Examples:
- `feat(api): add endpoint for listing deployments`
- `fix(db): resolve connection pool exhaustion`
- `chore(deps): upgrade FastAPI to 0.110.0`

Rules:
- Never amend pushed commits.
- Never force-push to shared branches.
- Never create empty commits.
- Write meaningful commit messages — not "fix stuff".

## PRs

- PR title matches conventional commit format.
- Description explains what and why, not how.
- Link related issues.
- Request review from relevant team members.
