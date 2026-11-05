package security.intrusion_detection

import rego.v1

# Intrusion detection
deny contains msg if {
    not input.intrusion_detection_active == true
    msg := "ids: intrusion detection is not enabled"
}

deny contains msg if {
    not input.file_integrity_monitoring == true
    msg := "ids: file integrity monitoring is not enabled"
}

deny contains msg if {
    not input.fail2ban_configured == true
    msg := "ids: fail2ban is not configured"
}

deny contains msg if {
    not input.log_monitoring_enabled == true
    msg := "ids: log monitoring is not enabled"
}

deny contains msg if {
    not input.alert_thresholds_configured == true
    msg := "ids: alert thresholds are not configured"
}

# Total controls evaluated for security.intrusion_detection: 5
