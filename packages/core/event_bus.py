from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)


class EventBus:
    """Lightweight publish/subscribe event bus for inter-agent communication."""

    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event: str, callback: Callable) -> None:
        """Subscribe a callback to an event type."""
        if callback not in self._listeners[event]:
            self._listeners[event].append(callback)
            logger.debug("Subscribed %s to '%s'", callback.__name__, event)

    def unsubscribe(self, event: str, callback: Callable) -> None:
        """Remove a callback subscription from an event type."""
        try:
            self._listeners[event].remove(callback)
            logger.debug("Unsubscribed %s from '%s'", callback.__name__, event)
        except ValueError:
            pass

    async def publish(self, event: str, data: Any = None) -> int:
        """Publish an event to all subscribers. Returns the number of callbacks invoked."""
        listeners = self._listeners.get(event, [])
        if not listeners:
            logger.debug("No listeners for event '%s'", event)
            return 0

        count = 0
        for callback in listeners:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(data)
                else:
                    callback(data)
                count += 1
            except Exception:
                logger.exception("Listener %s failed for event '%s'", callback.__name__, event)
        return count

    def get_subscribers(self, event: str) -> list[Callable]:
        """Return the list of subscribers for an event type."""
        return list(self._listeners.get(event, []))

    def clear(self) -> None:
        """Remove all subscriptions."""
        self._listeners.clear()

    @property
    def events(self) -> list[str]:
        """Return all event types that have at least one subscriber."""
        return [e for e, subs in self._listeners.items() if subs]
