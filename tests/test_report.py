from __future__ import annotations

from spectre import report
from spectre.findings import Finding, ScanResult, Severity


def _result() -> ScanResult:
    return ScanResult(
        "linux",
        [
            Finding("linux", "Root SSH login not disabled", Severity.critical, "ev", "fix"),
            Finding("linux", "Core dumps not disabled", Severity.low, "ev", "fix"),
        ],
    )


def test_render_json_contains_domain() -> None:
    out = report.render_json([_result()])
    assert "linux" in out
    assert "critical" in out


def test_render_markdown_counts() -> None:
    out = report.render_markdown([_result()])
    assert "critical: 1" in out
    assert "high: 0" in out


def test_record_run_appends(tmp_path: object) -> None:
    log = tmp_path / "changelog.md"  # type: ignore[attr-defined]
    log.write_text("# Changelog\n")  # type: ignore[attr-defined]
    report.record_run([_result()], str(log))
    text = log.read_text()  # type: ignore[attr-defined]
    assert "Scan" in text
    assert "Root SSH login not disabled" in text
