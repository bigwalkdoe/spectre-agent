# Decisions

- 2026-07-12 — Rebranded repository from the Modelink LLM Gateway to **Spectre Agent**, an infrastructure defender. All Modelink/AI-engineering content removed. Scope is five domains: Linux hardening, Kubernetes, firewall analysis, SSH monitoring, container security.
- Agent is **read-only by default**; remediation only on explicit request.
- Python 3.11+, ruff + mypy + pytest; findings are structured dataclasses with machine-readable JSON output.
