# Spectre Agent

An infrastructure defender for Linux and Kubernetes hosts. Spectre Agent audits, hardens, and monitors the attack surface across five domains:

| Domain | What it does |
| --- | --- |
| Linux Hardening | CIS-aligned checks for SSH, boot, updates, and system config |
| Kubernetes | Pod security context, network policy, RBAC, image posture |
| Firewall Analysis | Inspects iptables/nftables/ufw and flags open exposure |
| SSH Monitoring | Detects brute-force and unauthorized access from auth logs |
| Container Security | Scans images for root users, privileged mode, mounts, stale tags |

Spectre Agent is **read-only by default**. It inspects and reports; it never changes system state unless you explicitly ask it to remediate.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

```bash
# Run every audit
spectre --all

# Target a single domain
spectre --linux
spectre --kubernetes
spectre --firewall
spectre --ssh
spectre --containers

# Machine-readable output
spectre --all --json
```

Each domain is implemented as a module under `src/spectre/` and can be imported and run programmatically:

```python
from spectre import linux_hardening

findings = linux_hardening.check()
for f in findings:
    print(f.severity, f.title, f.evidence)
```

## Principles

- Audit first, remediate only on request.
- Every finding cites its evidence (command, file, or source).
- Missing tooling is reported as a gap — never assumed secure.
- No secrets, keys, or tokens in output.

See `AGENTS.md` for operating instructions and `playbooks/` for response runbooks.
