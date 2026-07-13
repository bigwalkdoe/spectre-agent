from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from spectre.findings import ScanResult, Severity


def render_json(results: list[ScanResult]) -> str:
    return "[" + ",".join(r.to_json() for r in results) + "]"


def render_markdown(results: list[ScanResult]) -> str:
    lines = ["# Spectre Agent Scan Report", ""]
    total_crit = total_high = 0
    for result in results:
        total_crit += result.critical
        total_high += result.high
        lines.append(f"## {result.domain}")
        lines.append("")
        lines.append(f"- critical: {result.critical}")
        lines.append(f"- high: {result.high}")
        lines.append(f"- total: {len(result.findings)}")
        lines.append("")
        if not result.findings:
            lines.append("_clean_")
            lines.append("")
            continue
        for f in result.findings:
            lines.append(f"- **[{f.severity}]** {f.title}")
            lines.append(f"  - evidence: {f.evidence}")
            lines.append(f"  - fix: {f.recommendation}")
        lines.append("")
    lines.append("--- ")
    lines.append(f"Totals: {total_crit} critical, {total_high} high across {len(results)} domains.")
    return "\n".join(lines)


def write_report(results: list[ScanResult], path: str, fmt: str = "json") -> Path:
    target = Path(path)
    rendered = render_json(results) if fmt == "json" else render_markdown(results)
    target.write_text(rendered + "\n", encoding="utf-8")
    return target


def _summary_line(results: list[ScanResult]) -> str:
    crit = sum(r.critical for r in results)
    high = sum(r.high for r in results)
    return f"- scan: {crit} critical, {high} high across {len(results)} domains"


def record_run(results: list[ScanResult], path: str = "memory/changelog.md") -> Path:
    target = Path(path)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    block = [f"\n## Scan {stamp}", ""]
    block.append(_summary_line(results))
    for result in results:
        if not result.findings:
            continue
        block.append(f"  - {result.domain}: {len(result.findings)} finding(s)")
        for f in result.findings:
            if f.severity in (Severity.critical, Severity.high):
                block.append(f"    - [{f.severity}] {f.title}")
    block.append("")
    existing = target.read_text(encoding="utf-8") if target.is_file() else ""
    target.write_text(existing + "\n".join(block), encoding="utf-8")
    return target
