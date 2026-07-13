from __future__ import annotations

from spectre import suppressions
from spectre.findings import Finding, ScanResult, Severity


def _finding(domain: str, title: str, severity: Severity) -> Finding:
    return Finding(domain, title, severity, "ev", "fix")


def test_exact_match_suppresses() -> None:
    supp = suppressions.Suppression("kubernetes", "Privileged system container in ns/p", "ok")
    f = _finding("kubernetes", "Privileged system container in ns/p", Severity.critical)
    assert supp.matches(f)


def test_glob_title_match() -> None:
    supp = suppressions.Suppression("kubernetes", "Privileged system container in *", "ok")
    f = _finding("kubernetes", "Privileged system container in kube-system/x", Severity.low)
    assert supp.matches(f)


def test_domain_mismatch_no_match() -> None:
    supp = suppressions.Suppression("linux", "*", "ok")
    assert not supp.matches(_finding("kubernetes", "anything", Severity.high))


def test_apply_marks_suppressed_and_excludes_counts() -> None:
    results = [
        ScanResult(
            "kubernetes",
            [_finding("kubernetes", "Privileged system container in kube-system/x", Severity.low)],
        )
    ]
    supps = [suppressions.Suppression("kubernetes", "Privileged system container in *", "ok")]
    out = suppressions.apply_suppressions(results, supps)
    assert out[0].findings[0].suppressed is True
    assert suppressions.count_suppressed(out) == 1


def test_load_missing_file_returns_empty(tmp_path: object) -> None:
    assert suppressions.load_suppressions(str(tmp_path / "nope.json")) == []  # type: ignore[attr-defined]
