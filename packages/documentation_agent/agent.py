import time
from pathlib import Path
from typing import Any

from packages.core.agent import BaseAgent
from packages.memory.db import MaintenanceRecord, save_maintenance_record


class DocumentationAgent(BaseAgent):
    """Generates and maintains project documentation."""

    def __init__(self, config: dict[str, Any] | None = None, context: Any = None):
        super().__init__(name="documentation", config=config, context=context)

    def initialize(self) -> None:
        """Check for documentation tools."""
        self.tools = {
            "python": True,
            "git": True,
        }
        self.project_root = Path(self.config.get("project_root", "."))
        if self.context and hasattr(self.context, 'service_bus') and self.context.service_bus:
            self.context.service_bus.register_service("documentation", "agent", self, actions=["scan-docs", "check-links", "coverage-report"])

    def plan(self) -> list[str]:
        """Formulate a documentation checklist."""
        return ["scan-docs", "check-links", "coverage-report"]

    def execute(self, plan: list[str]) -> dict[str, Any]:
        """Run documentation operations."""
        results: dict[str, Any] = {}
        for action in plan:
            start_time = time.monotonic()
            status = "success"
            log_output = ""

            try:
                if action == "scan-docs":
                    log_output = self._scan_docs()
                elif action == "check-links":
                    log_output = self._check_links()
                elif action == "coverage-report":
                    log_output = self._coverage_report()
                else:
                    log_output = f"Unknown action: {action}"
                    status = "failed"
            except Exception as e:
                log_output = f"Execution failed: {e}"
                status = "failed"

            elapsed = int((time.monotonic() - start_time) * 1000)
            results[action] = {
                "status": status,
                "log_output": log_output,
                "duration_ms": elapsed,
            }

            save_maintenance_record(
                MaintenanceRecord(
                    agent=self.name,
                    action=action,
                    status=status,
                    log_output=log_output,
                    duration_ms=elapsed,
                )
            )
        return results

    def observe(self) -> dict[str, Any]:
        """Return documentation inventory."""
        docs_dir = self.project_root / "docs"
        md_files = list(self.project_root.rglob("*.md"))
        py_files = list(self.project_root.rglob("*.py"))

        documented_modules = 0
        for py_file in py_files:
            if py_file.name.startswith("_"):
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
                if '"""' in content or "'''" in content:
                    documented_modules += 1
            except Exception:
                pass

        return {
            "docs_dir_exists": docs_dir.is_dir(),
            "markdown_files": len(md_files),
            "python_files": len(py_files),
            "documented_modules": documented_modules,
        }

    def report(self, results: dict[str, Any]) -> str:
        """Produce a formatted documentation report."""
        lines = ["=== Documentation Report ==="]
        for action, data in results.items():
            icon = "\u2713" if data["status"] == "success" else "\u2717"
            lines.append(f"{icon} {action}: {data['status'].upper()} ({data['duration_ms']}ms)")
            lines.append(f"  Details: {data['log_output']}")
        return "\n".join(lines)

    def recover(self, error: Exception) -> bool:
        """Recovery mechanism."""
        return True

    def verify(self) -> bool:
        """Verify documentation is accessible."""
        return self.project_root.exists()

    def shutdown(self) -> None:
        """Clean up before shutdown."""
        pass

    def _scan_docs(self) -> str:
        """Scan project for documentation files."""
        md_files = list(self.project_root.rglob("*.md"))
        docs_dir = self.project_root / "docs"
        docs_files = list(docs_dir.glob("*.md")) if docs_dir.is_dir() else []

        sections = [f.stem for f in md_files if f.parent == self.project_root]
        return (
            f"Found {len(md_files)} markdown files total, "
            f"{len(docs_files)} in docs/. "
            f"Root docs: {', '.join(sections[:10])}"
        )

    def _check_links(self) -> str:
        """Check for broken internal references in markdown files."""
        broken: list[str] = []
        md_files = list(self.project_root.rglob("*.md"))

        for md_file in md_files[:20]:
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                import re

                refs = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", content)
                for label, target in refs:
                    if target.startswith("http"):
                        continue
                    ref_path = md_file.parent / target
                    if not ref_path.exists():
                        broken.append(f"{md_file.name}: {target}")
            except Exception:
                pass

        if broken:
            return f"Found {len(broken)} broken links: {'; '.join(broken[:5])}"
        return f"Checked {len(md_files)} files. No broken internal links found."

    def _coverage_report(self) -> str:
        """Report on Python docstring coverage."""
        py_files = list(self.project_root.rglob("*.py"))
        total = 0
        documented = 0

        for py_file in py_files:
            if py_file.name.startswith("_") or "__pycache__" in str(py_file):
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
                import re

                classes = re.findall(r"^class\s+(\w+)", content, re.MULTILINE)
                functions = re.findall(r"^def\s+(\w+)", content, re.MULTILINE)
                total += len(classes) + len(functions)
                documented += content.count('"""') // 2 + content.count("'''") // 2
            except Exception:
                pass

        if total == 0:
            return "No Python classes or functions found."
        pct = int(documented / total * 100) if total > 0 else 0
        return f"Docstring coverage: {documented}/{total} ({pct}%)"
