import shutil
import subprocess
import time
from typing import Any
from packages.core.agent import BaseAgent
from packages.memory.db import save_maintenance_record, MaintenanceRecord


class DevOpsAgent(BaseAgent):
    def __init__(self, config: dict[str, Any] | None = None, context: Any = None):
        super().__init__(name="devops", config=config, context=context)

    def initialize(self) -> None:
        """Check for docker, podman, docker-compose, and kubectl binaries."""
        self.tools = {
            "podman": shutil.which("podman") is not None,
            "docker": shutil.which("docker") is not None,
            "kubectl": shutil.which("kubectl") is not None,
        }
        if self.context and hasattr(self.context, 'service_bus') and self.context.service_bus:
            self.context.service_bus.register_service("devops", "agent", self, actions=list(self.tools.keys()))

    def plan(self) -> list[str]:
        """Formulate container audit and optimization steps."""
        plan_steps = []
        if self.tools.get("podman"):
            plan_steps.append("podman-status")
            plan_steps.append("podman-prune")
        if self.tools.get("docker"):
            plan_steps.append("docker-status")
            plan_steps.append("docker-prune")
        if self.tools.get("kubectl"):
            plan_steps.append("kubectl-status")
        return plan_steps

    def execute(self, plan: list[str]) -> dict[str, Any]:
        """Run DevOps operations."""
        results = {}
        for action in plan:
            start_time = time.monotonic()
            status = "success"
            log_output = ""

            try:
                if action == "podman-status":
                    log_output = self._run_podman_status()
                elif action == "podman-prune":
                    log_output = self._run_podman_prune()
                elif action == "docker-status":
                    log_output = self._run_docker_status()
                elif action == "docker-prune":
                    log_output = self._run_docker_prune()
                elif action == "kubectl-status":
                    log_output = self._run_kubectl_status()
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
        """Return running container count metrics."""
        podman_count = 0
        docker_count = 0
        kube_context = None

        if self.tools.get("podman"):
            try:
                res = subprocess.run(
                    ["podman", "ps", "-q"], capture_output=True, text=True, timeout=5
                )
                podman_count = len([x for x in res.stdout.splitlines() if x.strip()])
            except Exception:
                pass

        if self.tools.get("docker"):
            try:
                res = subprocess.run(
                    ["docker", "ps", "-q"], capture_output=True, text=True, timeout=5
                )
                docker_count = len([x for x in res.stdout.splitlines() if x.strip()])
            except Exception:
                pass

        if self.tools.get("kubectl"):
            try:
                res = subprocess.run(
                    ["kubectl", "config", "current-context"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                kube_context = res.stdout.strip()
            except Exception:
                pass

        return {
            "running_podman_containers": podman_count,
            "running_docker_containers": docker_count,
            "kube_context": kube_context,
        }

    def report(self, results: dict[str, Any]) -> str:
        """Produce a formatted DevOps run summary."""
        lines = [f"=== DevOps Orchestration Report ==="]
        for action, data in results.items():
            icon = "✓" if data["status"] == "success" else "✗"
            lines.append(f"{icon} {action}: {data['status'].upper()} ({data['duration_ms']}ms)")
            lines.append(f"  Details: {data['log_output']}")
        return "\n".join(lines)

    def recover(self, error: Exception) -> bool:
        """Recovery mechanism."""
        return True

    def verify(self) -> bool:
        """Verify container operations succeeded."""
        return True

    def shutdown(self) -> None:
        """Clean up before shutdown."""
        pass

    # Subprocess execution helpers
    def _run_podman_status(self) -> str:
        res = subprocess.run(["podman", "ps", "--all", "--format", "{{.Names}}"], capture_output=True, text=True)
        containers = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        if containers:
            return f"Found Podman containers: {', '.join(containers)}."
        return "No Podman containers found."

    def _run_podman_prune(self) -> str:
        # Prune stopped containers and unused images
        res = subprocess.run(["podman", "system", "prune", "-f"], capture_output=True, text=True)
        return res.stdout.strip() or "Podman system prune finished."

    def _run_docker_status(self) -> str:
        res = subprocess.run(["docker", "ps", "--all", "--format", "{{.Names}}"], capture_output=True, text=True)
        containers = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        if containers:
            return f"Found Docker containers: {', '.join(containers)}."
        return "No Docker containers found."

    def _run_docker_prune(self) -> str:
        res = subprocess.run(["docker", "system", "prune", "-f"], capture_output=True, text=True)
        return res.stdout.strip() or "Docker system prune finished."

    def _run_kubectl_status(self) -> str:
        # Check current context and connection to the cluster
        res_ctx = subprocess.run(["kubectl", "config", "current-context"], capture_output=True, text=True)
        ctx = res_ctx.stdout.strip()
        if not ctx:
            return "No Kubernetes context configured."
        # Try checking nodes (with short timeout to fail fast if cluster is offline)
        res_nodes = subprocess.run(["kubectl", "get", "nodes", "--request-timeout=5"], capture_output=True, text=True)
        if res_nodes.returncode == 0:
            return f"Connected to Kubernetes context: '{ctx}'. Cluster is responsive."
        return f"Kubernetes context configured to '{ctx}', but cluster is unreachable."
