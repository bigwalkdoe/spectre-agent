package security.audit

import rego.v1

# Audit logging
deny contains msg if {
    not input.audit_logging_enabled == true
    msg := "audit: auditd/audit logging is not enabled"
}

deny contains msg if {
    object.get(input, "audit_retention_days", 0) < 90
    msg := "audit: audit log retention is under 90 days"
}

deny contains msg if {
    not input.sudo_logging_enabled == true
    msg := "audit: sudo logging is not enabled"
}

# Total controls evaluated for security.audit: 3
