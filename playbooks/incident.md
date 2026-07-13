# Incident Response

1. **Triage** — Run `spectre scan --all --json` and sort by severity (critical → high).
2. **Contain** — Isolate the affected host/namespace: block offending source IPs, cordon nodes, revoke credentials.
3. **Eradicate** — Apply the `recommendation` from each finding; prefer least-privilege fixes.
4. **Verify** — Re-run the relevant `spectre scan --<domain>` until clean.
5. **Record** — Append the incident to `memory/changelog.md` with the trigger and remediation.

Spectre Agent is read-only. Remediation is performed by the operator unless explicitly requested.
