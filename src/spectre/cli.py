from __future__ import annotations

import argparse
import sys

from spectre import (
    container_security,
    firewall,
    kubernetes,
    linux_hardening,
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


def _run_selected(domains: list[str]) -> list[ScanResult]:
    return [SCANS[d]() for d in domains]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spectre", description="Spectre Agent infrastructure defender"
    )
    parser.add_argument("--all", action="store_true", help="Run every domain scan")
    for name in _ORDER:
        parser.add_argument(f"--{name}", action="store_true", help=f"Scan the {name} domain")
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

    critical = sum(r.critical for r in results)
    high = sum(r.high for r in results)
    return 1 if (critical or high) else 0


if __name__ == "__main__":
    sys.exit(main())
