import shutil
import subprocess
import time
from typing import Any

from packages.core.agent import BaseAgent
from packages.memory.db import MaintenanceRecord, save_maintenance_record


class DeveloperAgent(BaseAgent):
    """Assists with software engineering tasks: git, tests, linting, dependency audits."""

    def __init__(self, config: dict[str, Any] | None = None, context: Any = None):
        super().__init__(name="developer", config=config, context=context)

    def initialize(self) -> None:
        """Check for developer tools."""
        self.tools = {
            "git": shutil.which("git") is not None,
            "python": shutil.which("python3") is not None,
            "ruff": shutil.which("ruff") is not None,
            "mypy": shutil.which("mypy") is not None,
            "pytest": shutil.which("pytest") is not None,
            "npm": shutil.which("npm") is not None,
            "node": shutil.which("node") is not None,
        }
        if self.context and hasattr(self.context, 'service_bus') and self.context.service_bus:
            self.context.service_bus.register_service("developer", "agent", self, actions=list(self.tools.keys()))

    def plan(self) -> list[str]:
        """Formulate a developer operations checklist."""
        plan_steps = []
        if self.tools.get("git"):
            plan_steps.append("git-status")
            plan_steps.append("dependency-audit")
        if self.tools.get("pytest"):
            plan_steps.append("test-runner")
        if self.tools.get("ruff"):
            plan_steps.append("lint-check")
        if self.tools.get("mypy"):
            plan_steps.append("type-check")
        return plan_steps

    def execute(self, plan: list[str]) -> dict[str, Any]:
        """Run developer operations."""
        results: dict[str, Any] = {}
        for action in plan:
            start_time = time.monotonic()
            status = "success"
            log_output = ""

            try:
                if action == "git-status":
                    log_output = self._run_git_status()
                elif action == "dependency-audit":
                    log_output = self._run_dependency_audit()
                elif action == "test-runner":
                    log_output = self._run_tests()
                elif action == "lint-check":
                    log_output = self._run_lint()
                elif action == "type-check":
                    log_output = self._run_typecheck()
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
        """Return repository status metrics."""
        branch = None
        dirty = False
        ahead = 0

        try:
            res = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True, text=True, timeout=5,
            )
            branch = res.stdout.strip() or None
        except Exception:
            pass

        try:
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, timeout=5,
            )
            dirty = bool(res.stdout.strip())
        except Exception:
            pass

        try:
            res = subprocess.run(
                ["git", "rev-list", "--count", "@{u}..HEAD"],
                capture_output=True, text=True, timeout=5,
            )
            if res.returncode == 0:
                ahead = int(res.stdout.strip() or 0)
        except Exception:
            pass

        return {
            "branch": branch,
            "dirty": dirty,
            "ahead": ahead,
            "has_git": self.tools.get("git", False),
        }

    def report(self, results: dict[str, Any]) -> str:
        """Produce a formatted developer operations report."""
        lines = ["=== Developer Operations Report ==="]
        for action, data in results.items():
            icon = "\u2713" if data["status"] == "success" else "\u2717"
            lines.append(f"{icon} {action}: {data['status'].upper()} ({data['duration_ms']}ms)")
            lines.append(f"  Details: {data['log_output']}")
        return "\n".join(lines)

    def recover(self, error: Exception) -> bool:
        """Recovery mechanism."""
        return True

    def verify(self) -> bool:
        """Verify developer tools are available."""
        return self.tools.get("git", False)

    def shutdown(self) -> None:
        """Clean up before shutdown."""
        pass

    def _run_git_status(self) -> str:
        try:
            res = subprocess.run(
                ["git", "status", "--short"],
                capture_output=True, text=True, timeout=10,
            )
            lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
            if lines:
                return f"{len(lines)} uncommitted changes: {', '.join(lines[:5])}"
            return "Working tree clean. No uncommitted changes."
        except Exception as e:
            return f"Git status failed: {e}"

    def _run_dependency_audit(self) -> str:
        try:
            res = subprocess.run(
                ["pip", "list", "--outdated", "--format=json"],
                capture_output=True, text=True, timeout=30,
            )
            if res.returncode == 0 and res.stdout.strip():
                import json

                outdated = json.loads(res.stdout)
                if outdated:
                    names = [p["name"] for p in outdated[:10]]
                    return f"{len(outdated)} outdated packages: {', '.join(names)}"
                return "All Python packages up to date."
            return "Dependency check completed."
        except Exception as e:
            return f"Dependency audit failed: {e}"

    def _run_tests(self) -> str:
        try:
            res = subprocess.run(
                ["pytest", "--tb=short", "-q"],
                capture_output=True, text=True, timeout=120,
            )
            output = res.stdout.strip()
            if res.returncode == 0:
                return f"Tests passed. {output}"
            return f"Tests failed (exit {res.returncode}). {output}"
        except Exception as e:
            return f"Test runner failed: {e}"

    def _run_lint(self) -> str:
        try:
            res = subprocess.run(
                ["ruff", "check", "."],
                capture_output=True, text=True, timeout=30,
            )
            output = res.stdout.strip()
            if res.returncode == 0:
                return "Lint clean. No issues found."
            issues = len(output.splitlines())
            return f"{issues} lint issues found. {output[:200]}"
        except Exception as e:
            return f"Lint check failed: {e}"

    def _run_typecheck(self) -> str:
        try:
            res = subprocess.run(
                ["mypy", ".", "--ignore-missing-imports"],
                capture_output=True, text=True, timeout=60,
            )
            output = res.stdout.strip()
            if res.returncode == 0:
                return "Type check clean. No issues found."
            issues = len(output.splitlines())
            return f"{issues} type issues found. {output[:200]}"
        except Exception as e:
            return f"Type check failed: {e}"
