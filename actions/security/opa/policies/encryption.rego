package security.encryption

import rego.v1

# Encryption policy
deny contains msg if {
    not input.encryption_at_rest_enabled == true
    msg := "encryption: encryption at rest is not enabled"
}

deny contains msg if {
    not input.encryption_in_transit_enabled == true
    msg := "encryption: encryption in transit is not enabled"
}

deny contains msg if {
    not input.tls_configured == true
    msg := "encryption: TLS is not configured for all services"
}

deny contains msg if {
    not input.certificate_monitoring_enabled == true
    msg := "encryption: certificate expiry is not monitored"
}

deny contains msg if {
    not input.key_rotation_enabled == true
    msg := "encryption: key rotation is not performed"
}

# Total controls evaluated for security.encryption: 5
