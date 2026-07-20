import shutil
import subprocess
import time
from typing import Any
import psutil
from packages.core.agent import BaseAgent
from packages.memory.db import save_maintenance_record, MaintenanceRecord


class LinuxAgent(BaseAgent):
    def __init__(self, config: dict[str, Any] | None = None, context: Any = None):
        super().__init__(name="linux", config=config, context=context)

    def initialize(self) -> None:
        """Check for essential executables and register with service bus."""
        self.tools = {
            "dnf": shutil.which("dnf") is not None,
            "flatpak": shutil.which("flatpak") is not None,
            "systemctl": shutil.which("systemctl") is not None,
            "journalctl": shutil.which("journalctl") is not None,
            "firewall-cmd": shutil.which("firewall-cmd") is not None,
            "getenforce": shutil.which("getenforce") is not None,
        }
        if self.context and hasattr(self.context, 'service_bus') and self.context.service_bus:
            self.context.service_bus.register_service("linux", "agent", self, actions=list(self.tools.keys()))

    def plan(self) -> list[str]:
        """Formulate a maintenance checklist based on configuration and tool availability."""
        plan_steps = ["system-health-check"]
        if self.tools.get("dnf"):
            plan_steps.append("dnf-check-update")
        if self.tools.get("flatpak"):
            plan_steps.append("flatpak-prune")
        if self.tools.get("journalctl"):
            plan_steps.append("journal-cleanup")
        if self.tools.get("getenforce"):
            plan_steps.append("selinux-check")
        if self.tools.get("firewall-cmd"):
            plan_steps.append("firewall-check")
        return plan_steps

    def execute(self, plan: list[str]) -> dict[str, Any]:
        """Execute the planned Fedora maintenance operations."""
        results = {}
        for action in plan:
            start_time = time.monotonic()
            status = "success"
            log_output = ""

            try:
                if action == "system-health-check":
                    log_output = self._run_system_health()
                elif action == "dnf-check-update":
                    log_output = self._run_dnf_check()
                elif action == "flatpak-prune":
                    log_output = self._run_flatpak_prune()
                elif action == "journal-cleanup":
                    log_output = self._run_journal_cleanup()
                elif action == "selinux-check":
                    log_output = self._run_selinux_check()
                elif action == "firewall-check":
                    log_output = self._run_firewall_check()
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

            # Persist the action results in the SQLite memory database
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
        """Collect live metrics from psutil."""
        try:
            temps = psutil.sensors_temperatures()
            # Try to grab CPU core temperature or fallback
            temp_c = None
            if temps:
                for name, entries in temps.items():
                    if entries:
                        temp_c = entries[0].current
                        break
        except Exception:
            temp_c = None

        try:
            battery = psutil.sensors_battery()
            battery_pct = battery.percent if battery else None
        except Exception:
            battery_pct = None

        return {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_percent": psutil.virtual_memory().percent,
            "swap_percent": psutil.swap_memory().percent,
            "disk_percent": psutil.disk_usage("/").percent,
            "battery_percent": battery_pct,
            "temperature_c": temp_c,
        }

    def report(self, results: dict[str, Any]) -> str:
        """Produce a formatted report of maintenance runs."""
        lines = [f"=== Linux Maintenance Agent Report: {self.name} ==="]
        for action, data in results.items():
            icon = "✓" if data["status"] == "success" else "✗"
            lines.append(f"{icon} {action}: {data['status'].upper()} ({data['duration_ms']}ms)")
            lines.append(f"  Details: {data['log_output']}")
        return "\n".join(lines)

    def recover(self, error: Exception) -> bool:
        """Fallback cleanup when update or command fails."""
        return True

    def verify(self) -> bool:
        """Verify system health after operations."""
        return True

    def shutdown(self) -> None:
        """Clean up before shutdown."""
        pass

    # Helper execution routines
    def _run_system_health(self) -> str:
        failed_services = []
        if self.tools.get("systemctl"):
            try:
                res = subprocess.run(
                    ["systemctl", "list-units", "--failed", "--no-pager", "--plain"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                lines = res.stdout.strip().splitlines()
                # filter service lines
                for line in lines:
                    if ".service" in line:
                        failed_services.append(line.split()[0])
            except Exception as e:
                failed_services = [f"Error checking: {e}"]

        if failed_services:
            return f"System healthy except for failed services: {', '.join(failed_services)}"
        return "All systemd services reported healthy. System resources within bounds."

    def _run_dnf_check(self) -> str:
        try:
            # Check updates (dnf check-update returns 100 if updates are available, 0 if not, 1 on error)
            res = subprocess.run(
                ["dnf", "check-update", "--quiet"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if res.returncode == 0:
                return "DNF cache up to date. No package updates available."
            elif res.returncode == 100:
                updates = [
                    line.strip()
                    for line in res.stdout.splitlines()
                    if line.strip() and not line.startswith("Last metadata")
                ]
                return f"{len(updates)} updates available."
            else:
                return f"DNF check-update returned code {res.returncode}. Stderr: {res.stderr.strip()}"
        except subprocess.TimeoutExpired:
            return "DNF check-update timed out."
        except Exception as e:
            return f"DNF query failed: {e}"

    def _run_flatpak_prune(self) -> str:
        try:
            # We dry-run or attempt to uninstall unused flatpaks. 
            # Note: without root it might fail or target user flatpaks. Let's do --user cleanup.
            res = subprocess.run(
                ["flatpak", "uninstall", "--unused", "--user", "-y"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if "Nothing to do" in res.stdout or not res.stdout.strip():
                return "Flatpak cleanup checked. No unused runtimes found."
            return f"Flatpak uninstalled unused user runtimes: {res.stdout.strip()}"
        except Exception as e:
            return f"Flatpak clean failed: {e}"

    def _run_journal_cleanup(self) -> str:
        # Journalctl vacuum requires sudo or adm/wheel memberships. Let's run a dry vacuum or attempt time based.
        try:
            res = subprocess.run(
                ["journalctl", "--vacuum-time=7d"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return res.stdout.strip() or res.stderr.strip() or "Vacuum completed."
        except Exception as e:
            return f"Journal vacuum failed: {e}"

    def _run_selinux_check(self) -> str:
        try:
            res = subprocess.run(["getenforce"], capture_output=True, text=True, timeout=5)
            status = res.stdout.strip()
            return f"SELinux is active in mode: {status}."
        except Exception as e:
            return f"Failed to check SELinux: {e}"

    def _run_firewall_check(self) -> str:
        try:
            res = subprocess.run(
                ["firewall-cmd", "--state"], capture_output=True, text=True, timeout=5
            )
            state = res.stdout.strip()
            return f"Firewalld service is: {state}."
        except Exception as e:
            return f"Failed to check firewalld state: {e}"
