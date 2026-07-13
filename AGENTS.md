# Spectre Agent

Spectre Agent is an infrastructure defender for Linux and Kubernetes hosts. It audits, hardens, and monitors the attack surface across five domains:

- **Linux Hardening** — CIS-aligned checks for SSH, boot, updates, and system configuration.
- **Kubernetes** — Pod security context, network policy, RBAC, and image posture analysis.
- **Firewall Analysis** — Inspects iptables/nftables/ufw policy and flags open exposure.
- **SSH Monitoring** — Detects brute-force and unauthorized access attempts from auth logs.
- **Container Security** — Scans images for root users, privileged mode, dangerous mounts, and stale tags.

## Operating Principles

1. **Read-only by default** — Audit and report. Never mutate system state unless explicitly told to remediate.
2. **Defense in depth** — Report every gap; prioritize by exploitability, not by count.
3. **Evidence over assertions** — Every finding cites the command, file, or source that produced it.
4. **Fail safe** — If a tool (kubectl, podman, ufw) is missing, report the gap; do not assume secure.
5. **No secrets in output** — Redact keys, tokens, and private material from logs and reports.
6. **Security first** — Never log or commit credentials.

## Task Lifecycle

```
Scope -> Inspect -> Analyze -> Report -> (Remediate on request) -> Record
```

## Structure

```
spectre-agent/
├── AGENTS.md              # This file: operating instructions
├── README.md              # Overview and usage
├── pyproject.toml         # Packaging, ruff, mypy
├── src/spectre/           # Capability modules
│   ├── cli.py             # Entrypoint / dispatcher
│   ├── linux_hardening.py
│   ├── kubernetes.py
│   ├── firewall.py
│   ├── ssh_monitor.py
│   └── container_security.py
├── config/                # Baselines and benchmarks
├── knowledge/             # Domain reference
├── playbooks/             # Defender runbooks
├── scripts/               # Helper automation
└── memory/                # Decisions and changelog
```

## Standards

- Python 3.11+, ruff (lint/format), mypy (types), pytest (tests)
- Structured findings via dataclasses; machine-readable JSON output support
- Run as an unprivileged user; escalate only the checks that require root
