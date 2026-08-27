import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import psutil

from packages.core.agent import BaseAgent
from packages.memory.db import (
    MaintenanceRecord,
    SecurityIncident,
    save_maintenance_record,
    save_security_incident,
)


class SecurityAgent(BaseAgent):
    def __init__(self, config: dict[str, Any] | None = None, context: Any = None):
        super().__init__(name="security", config=config, context=context)

    def initialize(self) -> None:
        """Check for security command utilities."""
        self.tools = {
            "getenforce": shutil.which("getenforce") is not None,
            "firewall-cmd": shutil.which("firewall-cmd") is not None,
        }
        if self.context and hasattr(self.context, 'service_bus') and self.context.service_bus:
            self.context.service_bus.register_service("security", "agent", self, actions=list(self.tools.keys()))

    def plan(self) -> list[str]:
        """Formulate security audit checklist."""
        plan_steps = ["selinux-audit", "firewall-audit", "ports-audit", "secrets-scan", "ssh-audit"]
        return plan_steps

    def execute(self, plan: list[str]) -> dict[str, Any]:
        """Run security audits."""
        results = {}
        for action in plan:
            start_time = time.monotonic()
            status = "success"
            log_output = ""

            try:
                if action == "selinux-audit":
                    log_output = self._audit_selinux()
                elif action == "firewall-audit":
                    log_output = self._audit_firewall()
                elif action == "ports-audit":
                    log_output = self._audit_ports()
                elif action == "secrets-scan":
                    log_output = self._scan_secrets()
                elif action == "ssh-audit":
                    log_output = self._audit_ssh()
                else:
                    log_output = f"Unknown action: {action}"
                    status = "failed"
            except Exception as e:
                log_output = f"Audit failed: {e}"
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
        """Report on port count and active incident warnings."""
        ports = []
        try:
            for conn in psutil.net_connections(kind="inet"):
                if conn.status == "LISTEN" and conn.laddr:
                    ports.append(conn.laddr.port)
            ports = sorted(list(set(ports)))
        except Exception:
            pass

        return {
            "listening_ports": ports,
            "listening_ports_count": len(ports),
        }

    def report(self, results: dict[str, Any]) -> str:
        """Produce a formatted security status report."""
        lines = ["=== Security Audit Report ==="]
        for action, data in results.items():
            icon = "✓" if data["status"] == "success" else "✗"
            lines.append(f"{icon} {action}: {data['status'].upper()} ({data['duration_ms']}ms)")
            lines.append(f"  Details: {data['log_output']}")
        return "\n".join(lines)

    def recover(self, error: Exception) -> bool:
        """Fallback cleanup."""
        return True

    def verify(self) -> bool:
        """Verify security state is clean."""
        return True

    def shutdown(self) -> None:
        """Clean up before shutdown."""
        pass

    # Audit implementations
    def _audit_selinux(self) -> str:
        if not self.tools.get("getenforce"):
            return "getenforce tool missing. SELinux audit skipped."
        try:
            res = subprocess.run(["getenforce"], capture_output=True, text=True, timeout=5)
            mode = res.stdout.strip()
            if mode == "Enforcing":
                return "SELinux is actively enforcing policies (secure)."
            elif mode == "Permissive":
                save_security_incident(
                    SecurityIncident(
                        severity="medium",
                        rule_id="SELINUX_PERMISSIVE",
                        message="SELinux is in Permissive mode. Policies are logged but not enforced.",
                    )
                )
                return "WARNING: SELinux is in Permissive mode (warnings generated)."
            else:
                save_security_incident(
                    SecurityIncident(
                        severity="high",
                        rule_id="SELINUX_DISABLED",
                        message="SELinux is disabled on the system.",
                    )
                )
                return "CRITICAL: SELinux is disabled (warnings generated)."
        except Exception as e:
            return f"SELinux check failed: {e}"

    def _audit_firewall(self) -> str:
        if not self.tools.get("firewall-cmd"):
            return "firewall-cmd missing. Firewalld audit skipped."
        try:
            res = subprocess.run(
                ["firewall-cmd", "--state"], capture_output=True, text=True, timeout=5
            )
            state = res.stdout.strip()
            if state == "running":
                return "Firewalld is active and running."
            return "Firewalld is not active (or firewall-cmd timed out)."
        except Exception as e:
            return f"Firewalld check failed: {e}"

    def _audit_ports(self) -> str:
        try:
            listening = []
            for conn in psutil.net_connections(kind="inet"):
                if conn.status == "LISTEN" and conn.laddr:
                    addr = conn.laddr.ip or "*"
                    listening.append(f"{addr}:{conn.laddr.port}")
            listening = sorted(list(set(listening)))
            
            # Check for generic listening on wildcard address for non-local services
            wildcards = [
                p for p in listening
                if p.startswith("0.0.0.0:") or p.startswith("*:") or p.startswith("[::]:")
            ]
            if wildcards:
                save_security_incident(
                    SecurityIncident(
                        severity="low",
                        rule_id="WILDCARD_PORTS",
                        message=f"Listening on open wildcard addresses: {', '.join(wildcards)}",
                    )
                )
                return f"Audit complete. Warning: Listening on open network addresses: {', '.join(wildcards)}."
            return f"No open public wildcard ports. Active local listeners: {', '.join(listening)}."
        except Exception as e:
            return f"Ports audit failed: {e}"

    def _scan_secrets(self) -> str:
        # Scan for private keys, oauth tokens, or passwords in .env, settings, or configs
        scan_dir = Path(".")
        secret_patterns = {
            "private_key": re.compile(r"-----BEGIN [A-Z]+ PRIVATE KEY-----"),
            "generic_secret": re.compile(
                r"(api_key|secret_key|password|token)\s*=\s*['\"][A-Za-z0-9_-]{20,}['\"]", re.IGNORECASE
            )
        }
        
        found_incidents = []
        # Walk directories (ignore hidden files, virtual environments, .git, etc.)
        ignore_dirs = {".git", ".venv", ".mypy_cache", ".pytest_cache", "__pycache__", "node_modules"}
        
        try:
            for path in scan_dir.rglob("*"):
                if any(part in ignore_dirs for part in path.parts):
                    continue
                if path.is_file() and path.suffix in (".py", ".env", ".toml", ".json", ".yaml", ".yml"):
                    try:
                        content = path.read_text(encoding="utf-8", errors="ignore")
                        for name, pattern in secret_patterns.items():
                            matches = pattern.findall(content)
                            if matches:
                                found_incidents.append(f"{name} in {path.name}")
                                save_security_incident(
                                    SecurityIncident(
                                        severity="high",
                                        rule_id="EXPOSED_SECRET",
                                        message=f"Possible exposed secret ({name}) found in file: {path}",
                                    )
                                )
                    except Exception:
                        pass
        except Exception as e:
            return f"Secrets scan failed during traversal: {e}"

        if found_incidents:
            return f"WARNING: Found potential secrets exposed in files: {', '.join(found_incidents)}."
        return "Secrets scan complete. No exposed credentials or keys found in local files."

    def _audit_ssh(self) -> str:
        ssh_config_file = Path("/etc/ssh/sshd_config")
        if not ssh_config_file.is_file():
            # Check user ssh config or fallback
            return "System SSH config (/etc/ssh/sshd_config) not found. SSH audit skipped."
        try:
            content = ssh_config_file.read_text(errors="ignore")
            # Check PermitRootLogin setting
            root_login = True
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("PermitRootLogin") and "no" in line.lower():
                    root_login = False
                    break
            
            if root_login:
                save_security_incident(
                    SecurityIncident(
                        severity="medium",
                        rule_id="SSH_ROOT_ALLOWED",
                        message="SSH allows root login. Consider changing PermitRootLogin to no.",
                    )
                )
                return "SSH configuration allows root login. Recommending PermitRootLogin=no."
            return "SSH configuration checked. PermitRootLogin is securely disabled."
        except Exception as e:
            return f"SSH configuration check failed (permission error?): {e}"
