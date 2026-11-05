package security.docker

import rego.v1

# Docker hardening
deny contains msg if {
    not input.docker_not_root == true
    msg := "docker: dockerd must not run as root"
}

deny contains msg if {
    not input.docker_no_new_privileges == true
    msg := "docker: no-new-privileges is not set"
}

deny contains msg if {
    not input.docker_userland_proxy_disabled == true
    msg := "docker: userland-proxy is not disabled"
}

deny contains msg if {
    not input.docker_resource_limits == true
    msg := "docker: containers have no resource limits"
}

deny contains msg if {
    not input.docker_privileged_disabled == true
    msg := "docker: privileged containers are enabled"
}

# Total controls evaluated for security.docker: 5
