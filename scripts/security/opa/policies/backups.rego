package security.backups

import rego.v1

# Backup policy
deny contains msg if {
    not input.backup_encryption_enabled == true
    msg := "backups: encryption at rest is not enabled"
}

deny contains msg if {
    object.get(input, "backup_retention_days", 0) < 7
    msg := "backups: retention is under 7 days"
}

deny contains msg if {
    not input.backup_offsite_enabled == true
    msg := "backups: off-site replication is not enabled"
}

deny contains msg if {
    not input.backup_verification_enabled == true
    msg := "backups: restore verification is not enabled"
}

deny contains msg if {
    not input.database_backups_enabled == true
    msg := "backups: databases are not included"
}

deny contains msg if {
    not input.docker_volume_backups_enabled == true
    msg := "backups: docker volumes are not included"
}

# Total controls evaluated for security.backups: 6
