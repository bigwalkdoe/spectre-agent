#!/usr/bin/env python3
"""Fail when the documented API surface does not match the code.

Both AGENTS.md and README.md publish a table of endpoints. Nothing checked those
tables against the FastAPI app, so they had drifted: ``GET /`` was missing
entirely, and two rows named the wrong path parameter (``/api/agents/{name}``
against a route declared as ``/api/agents/{agent_name}``), which sends a reader
building a URL to the wrong name.

The same script also checks the CLI count and the built-in workflow names,
because both are stated as exact numbers in the docs and both had drifted.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ("AGENTS.md", "README.md")

ROUTE_RE = re.compile(r'@app\.(get|post|put|delete|patch)\("([^"]+)"')
DOC_ROUTE_RE = re.compile(
    r"^\|\s*`(/[^`]*)`\s*\|\s*`?([A-Za-z/]+)`?\s*\|", re.M
)
DOC_CLI_RE = re.compile(r"^- `spectre ([a-z-]+)`", re.M)
CLI_CMD_RE = re.compile(
    r'@app\.command\("([a-z-]+)"\)\s*\ndef\s+\w+'
    r"|@app\.command\(name=\"([a-z-]+)\"\)\s*\ndef\s+\w+"
    r"|@app\.command\(\)\s*\ndef\s+([a-z_]+)"
)
WORKFLOW_RE = re.compile(r'^    "([a-z-]+)": WorkflowDefinition\(', re.M)

failures: list[str] = []


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# --- API routes -------------------------------------------------------------
api_src = read("apps/api/main.py")
routes = [(m.group(1).upper(), m.group(2)) for m in ROUTE_RE.finditer(api_src)]


def normalise(path: str) -> str:
    """Collapse path parameters so `/a/{x}` and `/a/{y}` compare equal."""
    return re.sub(r"\{[^}]+\}", "{}", path)


for doc in DOCS:
    if not (ROOT / doc).exists():
        continue
    text = read(doc)
    documented = [path for path, _method in DOC_ROUTE_RE.findall(text)]
    doc_by_template: dict[str, list[str]] = {}
    for dpath in documented:
        doc_by_template.setdefault(normalise(dpath), []).append(dpath)

    for _method, path in routes:
        candidates = doc_by_template.get(normalise(path), [])
        if not candidates:
            failures.append(f"{doc}: {path} is implemented but not documented")
            continue
        # A row whose parameter name differs from the route is worse than a
        # missing row: it looks correct and yields the wrong URL.
        expected = set(re.findall(r"\{([^}]+)\}", path))
        for dpath in candidates:
            if set(re.findall(r"\{([^}]+)\}", dpath)) != expected:
                failures.append(
                    f"{doc}: documented path {dpath} does not match route {path}"
                )

# --- CLI command count ------------------------------------------------------
cli_src = read("apps/cli/main.py")
cli_names = set()
for m in CLI_CMD_RE.finditer(cli_src):
    explicit, named, func = m.groups()
    cli_names.add(explicit or named or func.replace("_", "-"))

docs_text = "\n".join(read(d) for d in DOCS if (ROOT / d).exists())
for m in re.finditer(r"(\d+)\s+CLI [Cc]ommands", docs_text):
    claimed = int(m.group(1))
    if claimed != len(cli_names):
        failures.append(
            f"docs claim {claimed} CLI commands, {len(cli_names)} are registered"
        )

# --- Built-in workflows -----------------------------------------------------
engine_src = read("packages/workflow_engine/engine.py")
workflows = set(WORKFLOW_RE.findall(engine_src))
documented_workflows = set(
    re.findall(r"^- `([a-z-]+)` — ", docs_text, re.M)
)
missing_wf = workflows - documented_workflows
if missing_wf:
    failures.append(
        f"built-in workflows not documented: {', '.join(sorted(missing_wf))}"
    )

# --- Report -----------------------------------------------------------------
if failures:
    for f in failures:
        print(f"ERROR: {f}", file=sys.stderr)
    print(
        "\nThe documented API surface has drifted from the code. Fix the docs, "
        "or the code if the docs describe the intended behaviour.",
        file=sys.stderr,
    )
    sys.exit(1)

print(
    f"API docs OK: {len(routes)} routes, {len(cli_names)} CLI commands, "
    f"{len(workflows)} built-in workflows all match the documentation"
)
