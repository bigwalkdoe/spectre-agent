# Deployment Incident Response

1. **Assess** — Run `spectre status` to see the current deployment state.
2. **Rollback** — `spectre rollback <service> <environment>` to revert to the previous version.
3. **Verify** — Run `spectre status` and confirm the rollback completed.
4. **Record** — Append the incident to `memory/changelog.md` with the trigger and resolution.

If the rollback fails, check the service logs and docker state manually.
