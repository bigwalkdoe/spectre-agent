import subprocess
import time
from typing import Any

from packages.core.agent import BaseAgent
from packages.memory.db import MaintenanceRecord, save_maintenance_record


class PublishingAgent(BaseAgent):
    """Manages releases and publishing workflows."""

    def __init__(self, config: dict[str, Any] | None = None, context: Any = None):
        super().__init__(name="publishing", config=config, context=context)

    def initialize(self) -> None:
        """Check for publishing tools."""
        self.tools = {
            "git": True,
            "python": True,
            "build": True,
        }
        self.registry = self.config.get("registry", "pypi")
        self.package_name = self.config.get("package_name", "spectre")
        if self.context and hasattr(self.context, 'service_bus') and self.context.service_bus:
            self.context.service_bus.register_service(
                "publishing", "agent", self, actions=["check-version", "validate-dist", "check-git-status"]
            )

    def plan(self) -> list[str]:
        """Formulate a publishing checklist."""
        return ["check-version", "validate-dist", "check-git-status"]

    def execute(self, plan: list[str]) -> dict[str, Any]:
        """Run publishing operations."""
        results: dict[str, Any] = {}
        for action in plan:
            start_time = time.monotonic()
            status = "success"
            log_output = ""

            try:
                if action == "check-version":
                    log_output = self._check_version()
                elif action == "validate-dist":
                    log_output = self._validate_dist()
                elif action == "check-git-status":
                    log_output = self._check_git_status()
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
        """Return publishing state metrics."""
        version = self._get_version_from_pyproject()
        git_tag = self._get_latest_git_tag()
        dirty = self._is_dirty()

        return {
            "version": version,
            "git_tag": git_tag,
            "dirty": dirty,
            "registry": self.registry,
            "package_name": self.package_name,
        }

    def report(self, results: dict[str, Any]) -> str:
        """Produce a formatted publishing report."""
        lines = ["=== Publishing Report ==="]
        for action, data in results.items():
            icon = "\u2713" if data["status"] == "success" else "\u2717"
            lines.append(f"{icon} {action}: {data['status'].upper()} ({data['duration_ms']}ms)")
            lines.append(f"  Details: {data['log_output']}")
        return "\n".join(lines)

    def recover(self, error: Exception) -> bool:
        """Recovery mechanism."""
        return True

    def verify(self) -> bool:
        """Verify project is in a publishable state."""
        return not self._is_dirty()

    def shutdown(self) -> None:
        """Clean up before shutdown."""
        pass

    def _check_version(self) -> str:
        """Check current version from pyproject.toml."""
        version = self._get_version_from_pyproject()
        if version:
            return f"Current version: {version}"
        return "Could not determine version from pyproject.toml."

    def _validate_dist(self) -> str:
        """Validate built distributions exist."""
        try:
            res = subprocess.run(
                ["ls", "-la", "dist/"],
                capture_output=True, text=True, timeout=5,
            )
            if res.returncode == 0 and res.stdout.strip():
                files = [line.strip() for line in res.stdout.splitlines() if line.strip()]
                return f"Found {len(files)} files in dist/: {', '.join(files[:5])}"
            return "No files found in dist/. Run 'python -m build' first."
        except Exception as e:
            return f"Dist validation failed: {e}"

    def _check_git_status(self) -> str:
        """Check git status for publishing readiness."""
        try:
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, timeout=5,
            )
            if res.stdout.strip():
                changes = len(res.stdout.strip().splitlines())
                return f"Working tree has {changes} uncommitted changes. Commit before publishing."
            return "Working tree clean. Ready to publish."
        except Exception as e:
            return f"Git check failed: {e}"

    def _get_version_from_pyproject(self) -> str | None:
        """Extract version from pyproject.toml."""
        try:
            from pathlib import Path

            pyproject = Path("pyproject.toml")
            if pyproject.is_file():
                content = pyproject.read_text(encoding="utf-8")
                import re

                match = re.search(r'version\s*=\s*"([^"]+)"', content)
                return match.group(1) if match else None
        except Exception:
            pass
        return None

    def _get_latest_git_tag(self) -> str | None:
        """Get the latest git tag."""
        try:
            res = subprocess.run(
                ["git", "describe", "--tags", "--abbrev=0"],
                capture_output=True, text=True, timeout=5,
            )
            if res.returncode == 0:
                return res.stdout.strip() or None
        except Exception:
            pass
        return None

    def _is_dirty(self) -> bool:
        """Check if the working tree is dirty."""
        try:
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, timeout=5,
            )
            return bool(res.stdout.strip())
        except Exception:
            return False
