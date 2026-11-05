package security.network

import rego.v1

# Network policy
deny contains msg if {
    not input.network_segmentation_enabled == true
    msg := "network: segmentation is not enabled"
}

deny contains msg if {
    not input.dmz_isolated == true
    msg := "network: the DMZ is not isolated"
}

deny contains msg if {
    not input.internal_no_internet == true
    msg := "network: the internal network has direct internet access"
}

deny contains msg if {
    not input.vpn_enabled == true
    msg := "network: no VPN is configured for remote access"
}

deny contains msg if {
    not input.ddos_protection_enabled == true
    msg := "network: DDoS protection is not enabled"
}

# Total controls evaluated for security.network: 5
