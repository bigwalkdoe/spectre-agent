from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


@dataclass
class Finding:
    domain: str
    title: str
    severity: Severity
    evidence: str
    recommendation: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class ScanResult:
    domain: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def critical(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.critical)

    @property
    def high(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.high)

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "summary": {"critical": self.critical, "high": self.high, "total": len(self.findings)},
            "findings": [f.to_dict() for f in self.findings],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)
