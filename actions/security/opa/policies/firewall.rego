package security.firewall

import rego.v1

# Firewall and SSH
deny contains msg if {
    not input.firewall_enabled == true
    msg := "firewall: firewalld is not active"
}

deny contains msg if {
    not input.ssh_password_auth == false
    msg := "firewall: SSH password authentication is enabled"
}

deny contains msg if {
    not input.ssh_root_login == false
    msg := "firewall: SSH root login is enabled"
}

deny contains msg if {
    not input.fail2ban_active == true
    msg := "firewall: fail2ban is not active"
}

# Total controls evaluated for security.firewall: 4
