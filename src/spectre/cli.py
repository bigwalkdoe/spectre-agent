from __future__ import annotations

import argparse
import json
import sys

from spectre import (
    container_security,
    firewall,
    kubernetes,
    linux_hardening,
    remediation,
    report,
    ssh_monitor,
)
from spectre.findings import ScanResult

SCANS = {
    "linux": linux_hardening.check,
    "kubernetes": kubernetes.check,
    "firewall": firewall.check,
    "ssh": ssh_monitor.check,
    "containers": container_security.check,
}

_ORDER = ["linux", "kubernetes", "firewall", "ssh", "containers"]


def _print_human(results: list[ScanResult]) -> None:
    for result in results:
        print(f"\n=== {result.domain} ===")
        if not result.findings:
            print("  clean")
            continue
        for f in result.findings:
            print(f"  [{f.severity}] {f.title}")
            print(f"     evidence: {f.evidence}")
            print(f"     fix:      {f.recommendation}")


def _print_remediation(results: list[ScanResult], apply: bool) -> None:
    print("\n=== remediation (read-only audit by default) ===")
    if not apply:
        print("  dry-run: no system state changed. Use --apply to write changes.")
    for result in results:
        for r in remediation.remediate(result, apply):
            print(f"  [{r.status}] {r.domain}: {r.title}")
            print(f"     {r.detail}")


def _run_selected(domains: list[str]) -> list[ScanResult]:
    return [SCANS[d]() for d in domains]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spectre", description="Spectre Agent infrastructure defender"
    )
    parser.add_argument("--all", action="store_true", help="Run every domain scan")
    for name in _ORDER:
        parser.add_argument(f"--{name}", action="store_true", help=f"Scan the {name} domain")
    parser.add_argument(
        "--remediate", action="store_true", help="Show/safe-apply fixes for findings"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Write changes (requires --remediate)"
    )
    parser.add_argument("--report", metavar="PATH", help="Write a report to PATH")
    parser.add_argument(
        "--format", choices=["json", "md"], default="json", help="Report format"
    )
    parser.add_argument(
        "--record", action="store_true", help="Append a run summary to memory/changelog.md"
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    args = parser.parse_args(argv)

    domains = [d for d in _ORDER if getattr(args, d)]
    if args.all or not domains:
        domains = _ORDER

    results = _run_selected(domains)

    if args.json:
        print("[" + ",".join(r.to_json() for r in results) + "]")
    else:
        _print_human(results)

    if args.remediate:
        apply = args.apply
        if args.json:
            rem = [remediation.remediate(r, apply) for r in results]
            flat = [item.to_dict() for res in rem for item in res]
            print("\n" + json.dumps({"remediation": flat}, indent=2))
        else:
            _print_remediation(results, apply)

    if args.report:
        written = report.write_report(results, args.report, args.format)
        print(f"report written: {written}")

    if args.record:
        recorded = report.record_run(results)
        print(f"run recorded: {recorded}")

    critical = sum(r.critical for r in results)
    high = sum(r.high for r in results)
    return 1 if (critical or high) else 0


if __name__ == "__main__":
    sys.exit(main())
