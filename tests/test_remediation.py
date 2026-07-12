from __future__ import annotations

from spectre import remediation
from spectre.findings import Finding, ScanResult, Severity


def _linux_result(title: str, path: str, key: str, value: str) -> ScanResult:
    remediation._LINUX_FIXES[title] = (path, key, value)
    return ScanResult(
        "linux",
        [Finding("linux", title, Severity.high, "evidence", "fix")],
    )


def test_dry_run_reports_change(tmp_path: object) -> None:
    cfg = tmp_path / "sshd_config"  # type: ignore[attr-defined]
    cfg.write_text("PermitRootLogin yes\n")  # type: ignore[attr-defined]
    result = _linux_result(
        "Root SSH login not explicitly disabled",
        str(cfg),
        "PermitRootLogin",
        "no",
    )
    out = remediation.remediate(result, apply=False)
    assert out[0].status == remediation.RemediationStatus.dry_run
    assert "PermitRootLogin no" in out[0].detail
    assert "PermitRootLogin yes" in cfg.read_text()  # type: ignore[attr-defined]


def test_apply_writes_and_backs_up(tmp_path: object) -> None:
    cfg = tmp_path / "sshd_config"  # type: ignore[attr-defined]
    cfg.write_text("PasswordAuthentication yes\n")  # type: ignore[attr-defined]
    result = _linux_result(
        "SSH password authentication enabled",
        str(cfg),
        "PasswordAuthentication",
        "no",
    )
    out = remediation.remediate(result, apply=True)
    assert out[0].status == remediation.RemediationStatus.applied
    assert "PasswordAuthentication no" in cfg.read_text()  # type: ignore[attr-defined]
    assert (tmp_path / "sshd_config.spectre.bak").exists()  # type: ignore[attr-defined]


def test_manual_domain_returns_manual() -> None:
    result = ScanResult(
        "firewall",
        [Finding("firewall", "iptables issue", Severity.critical, "ev", "fix it")],
    )
    out = remediation.remediate(result, apply=False)
    assert out[0].status == remediation.RemediationStatus.manual
