"""Spectre Daemon — Background monitoring and maintenance service using Kernel lifecycle."""

from __future__ import annotations

import logging
import sys
from typing import Any

from packages.config.settings import load_settings
from packages.core.kernel import Kernel
from packages.core.service_bus import ServiceBus
from packages.memory.db import init_db
from packages.monitoring_agent.agent import MonitoringAgent
from packages.workflow_engine.engine import WorkflowEngine

logger = logging.getLogger("spectre.daemon")


class SpectreDaemon:
    """Background daemon that runs periodic health checks and workflows.

    Uses the Kernel for lifecycle management and the ServiceBus for communication.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.settings = load_settings()

        # Initialize Kernel (replaces manual event_bus + scheduler)
        self.kernel = Kernel()
        self.service_bus = (
            self.kernel.container.resolve("service_bus")
            if self.kernel.container.has("service_bus")
            else ServiceBus()
        )

        # Initialize engine and monitoring with context
        self.engine = WorkflowEngine(
            config=self.config,
            service_bus=self.service_bus,
            event_bus=self.kernel.event_bus,
        )
        self.monitoring = MonitoringAgent(config=self.config)
        self.monitoring.initialize()

    def start(self) -> None:
        """Start the daemon using Kernel lifecycle."""
        logger.info("Spectre daemon starting...")
        init_db()

        # Register services with the kernel
        self.kernel.register_service("workflow_engine", self.engine)
        self.kernel.register_service("monitoring_agent", self.monitoring)

        # Schedule periodic tasks via kernel scheduler
        interval = self.settings.monitoring.interval_seconds
        self.kernel.scheduler.add_task("health-check", f"every {interval}s", self._run_health_check)

        for sched in self.settings.schedules:
            if sched.enabled:
                self.kernel.scheduler.add_task(
                    f"workflow:{sched.name}",
                    sched.schedule,
                    lambda name=sched.name: self._run_workflow(name),
                )

        # Start kernel (handles signal registration, event publishing)
        self.kernel.start()
        logger.info("Spectre daemon running (monitoring every %ds)", interval)

        # Block until shutdown
        import time
        while self.kernel.running:
            time.sleep(1)

    def stop(self) -> None:
        """Stop the daemon gracefully via Kernel."""
        self.kernel.stop()
        logger.info("Spectre daemon stopped.")

    def _run_health_check(self) -> None:
        """Collect metrics and check thresholds."""
        try:
            results = self.monitoring.execute(["collect-metrics", "check-thresholds"])
            for action, data in results.items():
                if data["status"] == "failed":
                    logger.warning("Health check '%s' failed: %s", action, data["log_output"])
        except Exception:
            logger.exception("Health check failed")

    def _run_workflow(self, name: str) -> None:
        """Execute a named workflow."""
        try:
            result = self.engine.run_workflow(name)
            logger.info("Workflow '%s' completed: %s", name, result["status"])
        except Exception:
            logger.exception("Workflow '%s' failed", name)


def main() -> None:
    """Entry point for the daemon."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    daemon = SpectreDaemon()
    daemon.start()


if __name__ == "__main__":
    main()
