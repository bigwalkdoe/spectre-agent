# Incident Response Playbook

## Steps

1. **Assess severity** — Is production affected? How many users?
2. **Mitigate** — Rollback, feature flag, or hotfix to restore service
3. **Communicate** — Notify stakeholders with status
4. **Root cause analysis** — Inspect logs, metrics, recent changes
5. **Fix permanently** — Implement proper fix
6. **Verify** — Deploy fix, monitor for resolution
7. **Document** — Write postmortem: timeline, cause, fix, prevention

## Principles

- Restore service first, investigate second
- No blame — focus on system improvements
- Every incident should produce at least one preventive measure
