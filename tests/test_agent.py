from __future__ import annotations

from spectre import (
    container_security,
    firewall,
    kubernetes,
    linux_hardening,
    ssh_monitor,
)
from spectre.findings import ScanResult, Severity


def test_all_domains_return_scan_result() -> None:
    for check in (
        linux_hardening.check,
        kubernetes.check,
        firewall.check,
        ssh_monitor.check,
        container_security.check,
    ):
        result = check()
        assert isinstance(result, ScanResult)
        assert result.domain
        for f in result.findings:
            assert isinstance(f.severity, Severity)
            assert f.title and f.evidence and f.recommendation


def test_finding_to_json() -> None:
    result = linux_hardening.check()
    payload = result.to_dict()
    assert "findings" in payload
    assert "summary" in payload
