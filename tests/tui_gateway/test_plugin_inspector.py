from __future__ import annotations

import pytest

from hermes_cli import plugins
from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest
from tui_gateway import server


def test_plugin_context_registers_one_read_only_inspector():
    manager = PluginManager()
    context = PluginContext(PluginManifest(name="example", key="example"), manager)

    context.register_inspector(lambda params: {"echo": params.get("value")})

    assert manager.inspect_plugin("example", {"value": 7}) == {"echo": 7}


def test_plugin_inspector_rejects_duplicate_registration_and_non_objects():
    manager = PluginManager()
    context = PluginContext(PluginManifest(name="example", key="example"), manager)
    context.register_inspector(lambda _params: [])

    with pytest.raises(ValueError, match="already registered"):
        context.register_inspector(lambda _params: {})
    with pytest.raises(TypeError, match="must return an object"):
        manager.inspect_plugin("example")


def test_plugin_inspect_rpc_reports_missing_and_isolates_failures(monkeypatch):
    manager = PluginManager()
    monkeypatch.setattr(plugins, "_plugin_manager", manager)
    manager._discovered = True

    missing = server._methods["plugin.inspect"]("r1", {"plugin": "missing"})
    assert missing["error"]["code"] == 4040

    context = PluginContext(PluginManifest(name="broken", key="broken"), manager)

    def broken(_params):
        raise RuntimeError("snapshot failed")

    context.register_inspector(broken)
    failed = server._methods["plugin.inspect"]("r2", {"plugin": "broken"})
    assert failed["error"] == {"code": 5033, "message": "snapshot failed"}


def test_plugin_inspect_rpc_returns_registered_snapshot(monkeypatch):
    manager = PluginManager()
    monkeypatch.setattr(plugins, "_plugin_manager", manager)
    manager._discovered = True
    context = PluginContext(
        PluginManifest(name="soma-companion", key="soma-companion"), manager
    )
    context.register_inspector(lambda _params: {"schema_version": 1, "status": "ready"})

    response = server._methods["plugin.inspect"](
        "r3", {"plugin": "soma-companion", "limit": 20}
    )

    assert response["result"] == {"schema_version": 1, "status": "ready"}
