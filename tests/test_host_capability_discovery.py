"""Host capability discovery must include built-in tools before plugins inspect it."""

from unittest.mock import MagicMock

from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest
from tools import registry as tool_registry


def test_host_capabilities_discovers_builtin_tools_before_snapshot(monkeypatch):
    discover = MagicMock()
    monkeypatch.setattr(tool_registry.registry, "get_entry", lambda _name: None)
    monkeypatch.setattr(tool_registry, "discover_builtin_tools", discover)

    context = PluginContext(PluginManifest(name="capability-test"), PluginManager())
    context.get_host_capabilities()

    discover.assert_called_once_with()
