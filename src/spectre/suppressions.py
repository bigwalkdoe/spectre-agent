from __future__ import annotations

import fnmatch
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from spectre.findings import Finding, ScanResult


@dataclass
class Suppression:
    domain: str
    title: str
    reason: str
    expires: str | None = None

    def matches(self, finding: Finding) -> bool:
        if self.domain not in ("*", finding.domain):
            return False
        return fnmatch.fnmatch(finding.title, self.title)

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def load_suppressions(path: str) -> list[Suppression]:
    p = Path(path)
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    out: list[Suppression] = []
    for entry in data:
        out.append(
            Suppression(
                domain=entry.get("domain", "*"),
                title=entry.get("title", "*"),
                reason=entry.get("reason", "acknowledged"),
                expires=entry.get("expires"),
            )
        )
    return out


def apply_suppressions(
    results: list[ScanResult], suppressions: list[Suppression]
) -> list[ScanResult]:
    if not suppressions:
        return results
    for result in results:
        for finding in result.findings:
            if any(s.matches(finding) for s in suppressions):
                finding.suppressed = True
    return results


def count_suppressed(results: list[ScanResult]) -> int:
    return sum(1 for r in results for f in r.findings if f.suppressed)
