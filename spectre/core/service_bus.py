"""Spectre Core — Service Bus for inter-agent communication.

Agents communicate only through the Service Bus.
No direct coupling between agents.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ServiceInfo:
    """Metadata about a registered service."""

    name: str
    service_type: str  # "agent", "engine", "utility", "plugin"
    instance: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ServiceBus:
    """Central communication bus for inter-agent messaging.

    Agents register services and communicate through request/response
    or publish/subscribe patterns. No direct agent-to-agent references.
    """

    def __init__(self) -> None:
        self._services: dict[str, ServiceInfo] = {}
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._request_handlers: dict[str, Callable] = {}
        self._registry: dict[str, dict[str, Any]] = {}  # Persistent registry

    # ── Service Registration ──────────────────────────────────────────────

    def register_service(self, name: str, service_type: str, instance: Any, **metadata: Any) -> None:
        """Register a service with the bus."""
        self._services[name] = ServiceInfo(
            name=name,
            service_type=service_type,
            instance=instance,
            metadata=metadata,
        )
        # Persist registration metadata (without instance)
        self._registry[name] = {"type": service_type, "metadata": metadata}
        logger.info("Service registered: %s (%s)", name, service_type)

    def unregister_service(self, name: str) -> None:
        """Unregister a service."""
        self._services.pop(name, None)
        self._registry.pop(name, None)
        logger.info("Service unregistered: %s", name)

    def get_service(self, name: str) -> Any | None:
        """Get a service instance by name."""
        info = self._services.get(name)
        return info.instance if info else None

    def list_services(self) -> list[ServiceInfo]:
        """List all registered services."""
        return list(self._services.values())

    def find_services(self, service_type: str) -> list[ServiceInfo]:
        """Find services by type."""
        return [s for s in self._services.values() if s.service_type == service_type]

    def get_registry(self) -> dict[str, dict[str, Any]]:
        """Get the persistent service registry."""
        return dict(self._registry)

    def save_registry(self) -> str:
        """Serialize the registry to JSON for persistence."""
        return json.dumps(self._registry)

    def load_registry(self, data: str) -> None:
        """Load registry metadata from JSON (for re-registration after restart)."""
        try:
            self._registry = json.loads(data)
        except Exception:
            logger.warning("Failed to load service bus registry")

    def get_registered_names(self) -> list[str]:
        """Get names of all registered services (from registry)."""
        return list(self._registry.keys())

    # ── Request/Response ──────────────────────────────────────────────────

    def register_request_handler(self, action: str, handler: Callable) -> None:
        """Register a handler for a specific request action."""
        self._request_handlers[action] = handler
        logger.debug("Request handler registered for: %s", action)

    def request(self, action: str, data: Any = None) -> Any:
        """Send a request and get a response."""
        handler = self._request_handlers.get(action)
        if not handler:
            logger.warning("No handler for request action: %s", action)
            return None
        try:
            return handler(data)
        except Exception:
            logger.exception("Request handler failed for: %s", action)
            return None

    # ── Publish/Subscribe ─────────────────────────────────────────────────

    def subscribe(self, topic: str, callback: Callable) -> None:
        """Subscribe to a topic."""
        if callback not in self._handlers[topic]:
            self._handlers[topic].append(callback)

    def unsubscribe(self, topic: str, callback: Callable) -> None:
        """Unsubscribe from a topic."""
        try:
            self._handlers[topic].remove(callback)
        except ValueError:
            pass

    def publish(self, topic: str, data: Any = None) -> int:
        """Publish a message to all subscribers. Returns count of notified."""
        handlers = self._handlers.get(topic, [])
        count = 0
        for handler in handlers:
            try:
                handler(data)
                count += 1
            except Exception:
                logger.exception("Handler failed for topic '%s'", topic)
        return count

    def get_subscribers(self, topic: str) -> list[Callable]:
        """Get all subscribers for a topic."""
        return list(self._handlers.get(topic, []))

    def get_topics(self) -> list[str]:
        """Get all topics that have at least one subscriber."""
        return list(self._handlers.keys())

    def get_request_actions(self) -> list[str]:
        """Get all registered request handler actions."""
        return list(self._request_handlers.keys())
