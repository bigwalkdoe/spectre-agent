"""Tests for the event bus system."""

from __future__ import annotations

import asyncio

from packages.core.event_bus import EventBus


def _run(coro):
    """Run a coroutine in a new event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_subscribe_and_publish() -> None:
    bus = EventBus()
    received: list[str] = []

    def handler(data: str) -> None:
        received.append(data)

    bus.subscribe("test.event", handler)
    _run(bus.publish("test.event", "hello"))
    assert received == ["hello"]


def test_multiple_subscribers() -> None:
    bus = EventBus()
    results: list[int] = []

    bus.subscribe("evt", lambda d: results.append(1))
    bus.subscribe("evt", lambda d: results.append(2))
    _run(bus.publish("evt"))
    assert sorted(results) == [1, 2]


def test_unsubscribe() -> None:
    bus = EventBus()
    results: list[str] = []

    def handler(data: str) -> None:
        results.append(data)

    bus.subscribe("evt", handler)
    bus.unsubscribe("evt", handler)
    _run(bus.publish("evt", "x"))
    assert results == []


def test_unsubscribe_nonexistent() -> None:
    bus = EventBus()
    bus.unsubscribe("evt", lambda d: None)  # Should not raise


def test_no_subscribers() -> None:
    bus = EventBus()
    count = _run(bus.publish("nobody.listens"))
    assert count == 0


def test_get_subscribers() -> None:
    bus = EventBus()
    fn = lambda d: None
    bus.subscribe("evt", fn)
    subs = bus.get_subscribers("evt")
    assert fn in subs


def test_events_property() -> None:
    bus = EventBus()
    bus.subscribe("a", lambda d: None)
    bus.subscribe("b", lambda d: None)
    assert set(bus.events) == {"a", "b"}


def test_clear() -> None:
    bus = EventBus()
    bus.subscribe("a", lambda d: None)
    bus.subscribe("b", lambda d: None)
    bus.clear()
    assert bus.events == []


def test_exception_in_handler_does_not_propagate() -> None:
    bus = EventBus()

    def bad_handler(data: str) -> None:
        raise RuntimeError("boom")

    good_results: list[str] = []
    bus.subscribe("evt", bad_handler)
    bus.subscribe("evt", lambda d: good_results.append(d))

    count = _run(bus.publish("evt", "test"))
    assert count == 1
    assert good_results == ["test"]
