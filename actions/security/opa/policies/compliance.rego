package security.compliance

import rego.v1

# Compliance baseline
deny contains msg if {
    not input.security_baseline_compliant == true
    msg := "compliance: system is not compliant with the security baseline"
}

deny contains msg if {
    not input.cis_benchmarks_followed == true
    msg := "compliance: CIS benchmarks are not being followed"
}

deny contains msg if {
    not input.pci_dss_compliant == true
    msg := "compliance: PCI-DSS requirements are not met"
}

deny contains msg if {
    not input.security_assessments_scheduled == true
    msg := "compliance: security assessments are not scheduled"
}

deny contains msg if {
    not input.patch_management_active == true
    msg := "compliance: patch management is not active"
}

# Total controls evaluated for security.compliance: 5
