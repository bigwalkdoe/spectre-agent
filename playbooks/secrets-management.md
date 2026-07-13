# Secrets Management

## Steps

1. Choose secrets storage:
   - Environment variables (development)
   - HashiCorp Vault (production)
   - AWS Secrets Manager / Azure Key Vault
   - Kubernetes Secrets (containerized)

2. Define secrets categories:
   - Database credentials
   - API keys (external services)
   - JWT signing keys
   - Encryption keys
   - OAuth client secrets
   - Certificate private keys

3. Implement secrets injection:
   - Load from environment at runtime
   - Use vault-agent for sidecar injection
   - Use CSI driver for Kubernetes
   - Never hardcode in code or config files

4. Rotate secrets regularly:
   - Database credentials: quarterly
   - API keys: when compromised or quarterly
   - JWT keys: annually
   - Encryption keys: annually

5. Implement secret access logging:
   - Log all secret access attempts
   - Monitor for unusual access patterns
   - Alert on failed access attempts
   - Regular audit of access logs

6. Use principle of least privilege:
   - Grant minimal required permissions
   - Use role-based access control
   - Regular permission audits
   - Revoke access for inactive users

7. Secrets in development:
   - Use .env files (gitignored)
   - Provide .env.example template
   - Use different secrets per environment
   - Never commit actual secrets

8. Secrets in CI/CD:
   - Use GitHub Secrets / GitLab CI variables
   - Use environment-specific secrets
   - Inject at runtime, not build time
   - Rotate leaked secrets immediately

9. Validate secrets at startup:
   - Check required secrets exist
   - Validate secret format
   - Fail fast if secrets missing
   - Log validation errors securely

10. Emergency procedures:
    - Compromised secret rotation process
    - Incident response for secret leaks
    - Backup and restore procedures
    - Contact escalation for security issues

## Best Practices

- Never log or print secrets
- Use strong random secrets (32+ characters)
- Encrypt secrets at rest
- Use separate secrets per environment
- Document secret dependencies
- Regular security audits
- Use secret scanning tools (gitleaks, trufflehog)

## Tools

- `gitleaks`: Scan for leaked secrets in git history
- `trufflehog`: Scan for secrets in code
- `vault`: HashiCorp Vault for secret management
- `kubectl secrets`: Kubernetes secret management
