"""Plugin System — Manifest, permissions, hooks, lifecycle, and ServiceBus integration."""

from __future__ import annotations

import importlib.util
import inspect
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packages.memory.db import PluginRecord, save_plugin_record

logger = logging.getLogger(__name__)


@dataclass
class PluginManifest:
    """Plugin manifest describing capabilities and requirements."""

    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    permissions: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "permissions": self.permissions,
            "hooks": self.hooks,
            "requires": self.requires,
        }


# ── Permission Constants ──────────────────────────────────────────────────

PERM_READ_SYSTEM = "system:read"
PERM_WRITE_SYSTEM = "system:write"
PERM_READ_CONFIG = "config:read"
PERM_WRITE_CONFIG = "config:write"
PERM_NETWORK = "network"
PERM_EXEC = "exec"
PERM_CONTAINER = "container"
PERM_DATABASE = "database"


class BasePlugin:
    """Interface that Spectre plugins should subclass."""

    def __init__(self, context: dict[str, Any] | None = None):
        self.context = context or {}
        self._manifest: PluginManifest | None = None

    @property
    def manifest(self) -> PluginManifest:
        """Plugin manifest. Override to provide metadata."""
        if self._manifest is None:
            self._manifest = PluginManifest(
                name=self.__class__.__name__,
                version="0.1.0",
            )
        return self._manifest

    def register_commands(self) -> list[dict[str, Any]]:
        """Return list of dicts specifying Typer CLI commands to inject."""
        return []

    def register_workflows(self) -> dict[str, list[str]]:
        """Return dict of custom workflows: {name: [actions]}."""
        return {}

    def register_listeners(self) -> dict[str, Any]:
        """Return mappings of event name to event listener callback."""
        return {}

    def register_hooks(self) -> dict[str, Callable]:
        """Register lifecycle hooks (pre_execute, post_execute, etc.)."""
        return {}

    def on_load(self) -> None:
        """Called when the plugin is loaded."""
        pass

    def on_unload(self) -> None:
        """Called when the plugin is unloaded."""
        pass

    def has_permission(self, perm: str) -> bool:
        """Check if the plugin has a given permission."""
        return perm in self.manifest.permissions


class PluginLoader:
    """Loads, validates, and manages plugins with ServiceBus integration."""

    def __init__(self, plugins_dir: Path | None = None, service_bus: Any | None = None):
        self.plugins_dir = plugins_dir or (Path.home() / ".config" / "spectre" / "plugins")
        self.plugins: list[BasePlugin] = []
        self._hooks: dict[str, list[Callable]] = {}
        self.service_bus = service_bus

    def _load_manifest(self, filepath: Path) -> PluginManifest | None:
        """Load a plugin manifest from a JSON file alongside the plugin."""
        manifest_path = filepath.with_suffix(".json")
        if manifest_path.is_file():
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    data = json.load(f)
                return PluginManifest(**data)
            except Exception:
                logger.warning("Failed to load manifest for %s", filepath.name)
        return None

    def load_plugins(self, context: dict[str, Any] | None = None) -> list[BasePlugin]:
        """Scan and load all valid plugins from the plugins directory."""
        if not self.plugins_dir.is_dir():
            return []

        loaded_plugins = []
        for filepath in self.plugins_dir.glob("*.py"):
            if filepath.name.startswith("__"):
                continue
            try:
                module_name = f"spectre.plugins.{filepath.stem}"
                spec = importlib.util.spec_from_file_location(module_name, filepath)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    for name, obj in inspect.getmembers(module, inspect.isclass):
                        if issubclass(obj, BasePlugin) and obj is not BasePlugin:
                            instance = obj(context)
                            # Apply manifest if available
                            manifest = self._load_manifest(filepath)
                            if manifest:
                                instance._manifest = manifest
                            loaded_plugins.append(instance)
                            instance.on_load()
                            self._register_plugin_hooks(instance)
                            # Register with ServiceBus
                            self._register_with_service_bus(instance)
                            # Persist to database
                            self._persist_plugin(instance)
                            logger.info(
                                "Loaded plugin: %s v%s",
                                manifest.name if manifest else name,
                                manifest.version if manifest else "0.1.0",
                            )
            except Exception:
                logger.exception("Failed to load plugin %s", filepath.name)

        self.plugins = loaded_plugins
        return loaded_plugins

    def _register_with_service_bus(self, plugin: BasePlugin) -> None:
        """Register a plugin as a service on the ServiceBus."""
        if not self.service_bus:
            return
        name = plugin.manifest.name
        self.service_bus.register_service(
            name,
            "plugin",
            plugin,
            version=plugin.manifest.version,
            permissions=plugin.manifest.permissions,
        )

    def _persist_plugin(self, plugin: BasePlugin) -> None:
        """Persist plugin record to database."""
        try:
            save_plugin_record(
                PluginRecord(
                    name=plugin.manifest.name,
                    version=plugin.manifest.version,
                    enabled=True,
                    permissions=json.dumps(plugin.manifest.permissions),
                    status="active",
                )
            )
        except Exception:
            pass

    def _register_plugin_hooks(self, plugin: BasePlugin) -> None:
        """Register a plugin's lifecycle hooks."""
        for hook_name, callback in plugin.register_hooks().items():
            self._hooks.setdefault(hook_name, []).append(callback)

    def trigger_hooks(self, hook_name: str, *args: Any, **kwargs: Any) -> list[Any]:
        """Trigger all registered hooks for a given lifecycle event."""
        results = []
        for callback in self._hooks.get(hook_name, []):
            try:
                results.append(callback(*args, **kwargs))
            except Exception:
                logger.exception("Hook '%s' failed in %s", hook_name, callback.__name__)
        return results

    def unload_plugins(self) -> None:
        """Unload all plugins, calling on_unload on each."""
        for plugin in self.plugins:
            try:
                plugin.on_unload()
                # Unregister from ServiceBus
                if self.service_bus:
                    self.service_bus.unregister_service(plugin.manifest.name)
            except Exception:
                logger.exception("Failed to unload plugin %s", plugin.manifest.name)
        self.plugins.clear()
        self._hooks.clear()

    def get_plugin(self, name: str) -> BasePlugin | None:
        """Get a plugin by name."""
        for plugin in self.plugins:
            if plugin.manifest.name == name:
                return plugin
        return None

    def check_permissions(self, required: list[str]) -> dict[str, bool]:
        """Check which required permissions are granted across all plugins."""
        granted = set()
        for plugin in self.plugins:
            granted.update(plugin.manifest.permissions)
        return {perm: perm in granted for perm in required}
