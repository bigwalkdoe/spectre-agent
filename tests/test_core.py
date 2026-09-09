"""Tests for Spectre Core — Kernel, ServiceBus, Config."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from packages.core.agent import AgentContext, BaseAgent
from packages.core.config import SpectreConfig, load_config, save_config
from packages.core.kernel import Container, Kernel
from packages.core.service_bus import ServiceBus

# ── Container ─────────────────────────────────────────────────────────────


def test_container_register_and_resolve() -> None:
    container = Container()
    container.register("test", "hello")
    assert container.resolve("test") == "hello"


def test_container_factory() -> None:
    container = Container()
    container.register_factory("lazy", lambda: 42)
    assert container.resolve("lazy") == 42


def test_container_has() -> None:
    container = Container()
    assert not container.has("missing")
    container.register("exists", 1)
    assert container.has("exists")
    container.register_factory("factory", lambda: 2)
    assert container.has("factory")


def test_container_list_services() -> None:
    container = Container()
    container.register("a", 1)
    container.register_factory("b", lambda: 2)
    names = container.list_services()
    assert "a" in names
    assert "b" in names


def test_container_resolve_missing() -> None:
    container = Container()
    with pytest.raises(KeyError):
        container.resolve("nonexistent")


# ── Kernel ────────────────────────────────────────────────────────────────


def test_kernel_init() -> None:
    kernel = Kernel()
    assert kernel.running is False
    assert kernel.container.has("kernel")
    assert kernel.container.has("event_bus")
    assert kernel.container.has("scheduler")
    assert kernel.container.has("service_bus")


def test_kernel_register_service() -> None:
    kernel = Kernel()
    kernel.register_service("custom", "value")
    assert kernel.container.resolve("custom") == "value"


def test_kernel_shutdown_hook() -> None:
    kernel = Kernel()
    called = []
    kernel.register_shutdown_hook(lambda: called.append(True))
    kernel._shutdown_hooks[-1]()
    assert called == [True]


# ── ServiceBus ────────────────────────────────────────────────────────────


def test_service_bus_register_and_get() -> None:
    bus = ServiceBus()
    bus.register_service("test", "agent", "instance", key="value")
    assert bus.get_service("test") == "instance"


def test_service_bus_unregister() -> None:
    bus = ServiceBus()
    bus.register_service("test", "agent", "instance")
    bus.unregister_service("test")
    assert bus.get_service("test") is None


def test_service_bus_list_services() -> None:
    bus = ServiceBus()
    bus.register_service("a", "agent", 1)
    bus.register_service("b", "engine", 2)
    services = bus.list_services()
    assert len(services) == 2
    assert any(s.name == "a" for s in services)
    assert any(s.name == "b" for s in services)


def test_service_bus_find_services() -> None:
    bus = ServiceBus()
    bus.register_service("agent1", "agent", 1)
    bus.register_service("engine1", "engine", 2)
    agents = bus.find_services("agent")
    assert len(agents) == 1
    assert agents[0].name == "agent1"


def test_service_bus_registry_persistence() -> None:
    bus = ServiceBus()
    bus.register_service("test", "agent", "instance", version="1.0")
    registry = bus.get_registry()
    assert "test" in registry
    assert registry["test"]["type"] == "agent"
    assert registry["test"]["metadata"]["version"] == "1.0"

    # Save and load
    json_str = bus.save_registry()
    bus2 = ServiceBus()
    bus2.load_registry(json_str)
    assert "test" in bus2.get_registry()


def test_service_bus_request_handler() -> None:
    bus = ServiceBus()
    bus.register_request_handler("ping", lambda data: "pong")
    assert bus.request("ping") == "pong"
    assert bus.request("nonexistent") is None


def test_service_bus_pubsub() -> None:
    bus = ServiceBus()
    received = []
    bus.subscribe("test.event", lambda data: received.append(data))
    count = bus.publish("test.event", {"key": "value"})
    assert count == 1
    assert received == [{"key": "value"}]


def test_service_bus_unsubscribe() -> None:
    bus = ServiceBus()

    def handler(data):
        pass

    bus.subscribe("test", handler)
    bus.unsubscribe("test", handler)
    assert bus.get_subscribers("test") == []


# ── Config ────────────────────────────────────────────────────────────────


def test_spectre_config_defaults() -> None:
    config = SpectreConfig()
    assert config.profile == "laptop"
    assert config.log_level == "INFO"
    assert config.ollama_url == "http://localhost:11434"
    assert config.monitoring_interval == 30


def test_load_config_defaults() -> None:
    config = load_config()
    assert isinstance(config, SpectreConfig)
    assert config.profile == "laptop"


def test_save_and_load_config() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "settings.yaml"
        config = SpectreConfig(profile="workstation", log_level="DEBUG")
        save_config(config, path)
        loaded = load_config(path)
        assert loaded.profile == "workstation"
        assert loaded.log_level == "DEBUG"


# ── Agent Context ─────────────────────────────────────────────────────────


def test_agent_context() -> None:
    bus = ServiceBus()
    ctx = AgentContext(service_bus=bus)
    assert ctx.service_bus is bus
    assert ctx.kernel is None


def test_agent_accepts_context() -> None:
    bus = ServiceBus()
    ctx = AgentContext(service_bus=bus)

    class TestAgent(BaseAgent):
        def initialize(self):
            pass

        def plan(self):
            return []

        def execute(self, plan):
            return {}

        def observe(self):
            return {}

        def verify(self):
            return True

        def report(self, results):
            return ""

        def recover(self, error):
            return True

        def shutdown(self):
            pass

    agent = TestAgent("test", context=ctx)
    assert agent.context is ctx
