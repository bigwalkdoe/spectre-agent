"""Spectre Core — Kernel, dependency injection, lifecycle management."""

from __future__ import annotations

import logging
import signal
import sys
from collections.abc import Callable
from typing import Any

from packages.core.event_bus import EventBus
from packages.core.scheduler import TaskScheduler

logger = logging.getLogger("spectre.kernel")


class Container:
    """Simple dependency injection container."""

    def __init__(self) -> None:
        self._services: dict[str, Any] = {}
        self._factories: dict[str, Any] = {}

    def register(self, name: str, instance: Any) -> None:
        """Register a service instance."""
        self._services[name] = instance
        logger.debug("Registered service: %s", name)

    def register_factory(self, name: str, factory: Any) -> None:
        """Register a factory function for lazy instantiation."""
        self._factories[name] = factory

    def resolve(self, name: str) -> Any:
        """Resolve a service by name."""
        if name in self._services:
            return self._services[name]
        if name in self._factories:
            instance = self._factories[name]()
            self._services[name] = instance
            return instance
        raise KeyError(f"Service '{name}' not registered")

    def has(self, name: str) -> bool:
        """Check if a service is registered."""
        return name in self._services or name in self._factories

    def list_services(self) -> list[str]:
        """List all registered service names."""
        return list(set(list(self._services.keys()) + list(self._factories.keys())))


class Kernel:
    """Spectre Core Kernel — bootstraps and manages the application lifecycle."""

    def __init__(self) -> None:
        self.container = Container()
        self.event_bus = EventBus()
        self.scheduler = TaskScheduler()
        self._running = False
        self._shutdown_hooks: list[Callable[[], Any]] = []

        # Register core services
        self.container.register("kernel", self)
        self.container.register("event_bus", self.event_bus)
        self.container.register("scheduler", self.scheduler)
        self.container.register("container", self.container)

        # Register service bus factory (lazy singleton)
        self.container.register_factory("service_bus", self._create_service_bus)

    def _create_service_bus(self) -> Any:
        """Create the ServiceBus singleton."""
        from packages.core.service_bus import ServiceBus
        bus = ServiceBus()
        self.container.register("service_bus", bus)
        return bus

    def register_service(self, name: str, instance: Any) -> None:
        """Register a service in the DI container."""
        self.container.register(name, instance)

    def register_shutdown_hook(self, hook: Callable[[], Any]) -> None:
        """Register a function to run on shutdown."""
        self._shutdown_hooks.append(hook)

    def start(self) -> None:
        """Start the kernel and all services."""
        logger.info("Spectre Kernel starting...")
        self._running = True

        # Set up signal handlers
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        # Start scheduler
        self.scheduler.start(interval=10.0)

        # Publish startup event
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.event_bus.publish("SystemStarted"))
            else:
                loop.run_until_complete(self.event_bus.publish("SystemStarted"))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self.event_bus.publish("SystemStarted"))
            loop.close()

        logger.info("Spectre Kernel started. Services: %s", self.container.list_services())

    def stop(self) -> None:
        """Stop the kernel and run shutdown hooks."""
        if not self._running:
            return

        logger.info("Spectre Kernel stopping...")
        self._running = False

        # Run shutdown hooks
        for hook in self._shutdown_hooks:
            try:
                hook()
            except Exception:
                logger.exception("Shutdown hook failed")

        # Unload plugins
        if self.container.has("plugin_loader"):
            try:
                loader = self.container.resolve("plugin_loader")
                loader.unload_plugins()
            except Exception:
                logger.exception("Failed to unload plugins during shutdown")

        # Stop scheduler
        self.scheduler.stop()

        # Publish shutdown event
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.event_bus.publish("SystemStopped"))
            else:
                loop.run_until_complete(self.event_bus.publish("SystemStopped"))
        except RuntimeError:
            pass

        logger.info("Spectre Kernel stopped.")

    def _handle_signal(self, signum: int, frame: Any) -> None:
        """Handle OS signals for graceful shutdown."""
        logger.info("Received signal %s, initiating shutdown...", signum)
        self.stop()
        sys.exit(0)

    @property
    def running(self) -> bool:
        return self._running
