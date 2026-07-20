"""Tests for the plugin loader."""

from __future__ import annotations

from pathlib import Path

from packages.plugins.loader import PluginLoader, BasePlugin


def test_plugin_loader_default_dir() -> None:
    loader = PluginLoader()
    assert loader.plugins_dir == Path.home() / ".config" / "spectre" / "plugins"


def test_plugin_loader_custom_dir(tmp_path: Path) -> None:
    loader = PluginLoader(plugins_dir=tmp_path)
    assert loader.plugins_dir == tmp_path


def test_load_plugins_empty_dir(tmp_path: Path) -> None:
    loader = PluginLoader(plugins_dir=tmp_path)
    plugins = loader.load_plugins({})
    assert plugins == []


def test_load_plugins_nonexistent_dir() -> None:
    loader = PluginLoader(plugins_dir=Path("/nonexistent"))
    plugins = loader.load_plugins({})
    assert plugins == []


def test_load_plugins_with_valid_plugin(tmp_path: Path) -> None:
    plugin_code = '''
from packages.plugins.loader import BasePlugin

class MyPlugin(BasePlugin):
    def register_commands(self):
        return [{"name": "test"}]
'''
    (tmp_path / "my_plugin.py").write_text(plugin_code)
    loader = PluginLoader(plugins_dir=tmp_path)
    plugins = loader.load_plugins({"key": "value"})
    assert len(plugins) == 1
    assert isinstance(plugins[0], BasePlugin)


def test_load_plugins_skips_init(tmp_path: Path) -> None:
    (tmp_path / "__init__.py").write_text("# skip me")
    loader = PluginLoader(plugins_dir=tmp_path)
    plugins = loader.load_plugins({})
    assert plugins == []


def test_base_plugin_defaults() -> None:
    plugin = BasePlugin(context={})
    assert plugin.register_commands() == []
    assert plugin.register_workflows() == {}
    assert plugin.register_listeners() == {}
