import time
from typing import Any

import psutil

from packages.core.agent import BaseAgent
from packages.memory.db import MaintenanceRecord, SystemMetric, save_maintenance_record, save_metric


class MonitoringAgent(BaseAgent):
    """Continuous system metrics collection and alerting."""

    def __init__(self, config: dict[str, Any] | None = None, context: Any = None):
        super().__init__(name="monitoring", config=config, context=context)

    def initialize(self) -> None:
        """Initialize monitoring state."""
        self.thresholds = {
            "cpu_percent": self.config.get("cpu_threshold", 90),
            "memory_percent": self.config.get("memory_threshold", 85),
            "swap_percent": self.config.get("swap_threshold", 80),
            "disk_percent": self.config.get("disk_threshold", 90),
        }
        if self.context and hasattr(self.context, "service_bus") and self.context.service_bus:
            self.context.service_bus.register_service(
                "monitoring", "agent", self, actions=["collect-metrics", "check-thresholds"]
            )

    def plan(self) -> list[str]:
        """Formulate a monitoring checklist."""
        return ["collect-metrics", "check-thresholds"]

    def execute(self, plan: list[str]) -> dict[str, Any]:
        """Run monitoring operations."""
        results: dict[str, Any] = {}
        for action in plan:
            start_time = time.monotonic()
            status = "success"
            log_output = ""

            try:
                if action == "collect-metrics":
                    log_output = self._collect_metrics()
                elif action == "check-thresholds":
                    log_output = self._check_thresholds()
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
        """Collect a full system metrics snapshot."""
        return self._gather_metrics()

    def report(self, results: dict[str, Any]) -> str:
        """Produce a formatted monitoring report."""
        lines = ["=== Monitoring Report ==="]
        for action, data in results.items():
            icon = "\u2713" if data["status"] == "success" else "\u2717"
            lines.append(f"{icon} {action}: {data['status'].upper()} ({data['duration_ms']}ms)")
            lines.append(f"  Details: {data['log_output']}")
        return "\n".join(lines)

    def recover(self, error: Exception) -> bool:
        """Recovery mechanism."""
        return True

    def verify(self) -> bool:
        """Verify metrics collection is working."""
        try:
            metrics = self._gather_metrics()
            return metrics.get("cpu_percent", 0) >= 0
        except Exception:
            return False

    def shutdown(self) -> None:
        """Clean up before shutdown."""
        pass

    def _gather_metrics(self) -> dict[str, Any]:
        """Gather all system metrics via psutil."""
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk = psutil.disk_usage("/")

        battery_pct = None
        temp_c = None
        net = psutil.net_io_counters()

        try:
            bat = psutil.sensors_battery()
            if bat:
                battery_pct = bat.percent
        except Exception:
            pass

        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for entries in temps.values():
                    if entries:
                        temp_c = entries[0].current
                        break
        except Exception:
            pass

        return {
            "cpu_percent": cpu,
            "memory_percent": mem.percent,
            "memory_used_gb": round(mem.used / (1024**3), 2),
            "memory_total_gb": round(mem.total / (1024**3), 2),
            "swap_percent": swap.percent,
            "disk_percent": disk.percent,
            "disk_used_gb": round(disk.used / (1024**3), 2),
            "disk_total_gb": round(disk.total / (1024**3), 2),
            "battery_percent": battery_pct,
            "temperature_c": temp_c,
            "net_sent_mb": round(net.bytes_sent / (1024**2), 2),
            "net_recv_mb": round(net.bytes_recv / (1024**2), 2),
        }

    def _collect_metrics(self) -> str:
        """Collect and persist system metrics."""
        metrics = self._gather_metrics()
        try:
            save_metric(
                SystemMetric(
                    cpu_percent=metrics["cpu_percent"],
                    memory_percent=metrics["memory_percent"],
                    swap_percent=metrics["swap_percent"],
                    disk_percent=metrics["disk_percent"],
                    battery_percent=metrics.get("battery_percent"),
                    temperature_c=metrics.get("temperature_c"),
                )
            )
        except Exception:
            pass
        return (
            f"CPU: {metrics['cpu_percent']}% | "
            f"RAM: {metrics['memory_percent']}% ({metrics['memory_used_gb']}/{metrics['memory_total_gb']} GB) | "
            f"Swap: {metrics['swap_percent']}% | "
            f"Disk: {metrics['disk_percent']}%"
        )

    def _check_thresholds(self) -> str:
        """Check if any metrics exceed configured thresholds."""
        metrics = self._gather_metrics()
        warnings: list[str] = []

        if metrics["cpu_percent"] > self.thresholds["cpu_percent"]:
            warnings.append(f"CPU at {metrics['cpu_percent']}% (threshold: {self.thresholds['cpu_percent']}%)")
        if metrics["memory_percent"] > self.thresholds["memory_percent"]:
            warnings.append(f"RAM at {metrics['memory_percent']}% (threshold: {self.thresholds['memory_percent']}%)")
        if metrics["swap_percent"] > self.thresholds["swap_percent"]:
            warnings.append(f"Swap at {metrics['swap_percent']}% (threshold: {self.thresholds['swap_percent']}%)")
        if metrics["disk_percent"] > self.thresholds["disk_percent"]:
            warnings.append(f"Disk at {metrics['disk_percent']}% (threshold: {self.thresholds['disk_percent']}%)")

        if warnings:
            return f"ALERTS: {'; '.join(warnings)}"
        return "All metrics within thresholds. System healthy."
