"""Soma compatibility behaviour contracts."""
import logging
from hermes_cli.plugins import PluginManager, PluginContext, PluginManifest



class TestPluginHooksCompat:
    def test_activity_observation_is_a_supported_host_hook(self, caplog):
        manager = PluginManager()
        context = PluginContext(
            PluginManifest(name="activity-consumer", key="activity-consumer"),
            manager,
        )
        received = []

        with caplog.at_level(logging.WARNING):
            context.register_hook(
                "activity_observation",
                lambda **event: received.append(event),
            )

        manager.invoke_hook("activity_observation", session_id="presence:1")

        assert received == [
            {
                "session_id": "presence:1",
                "telemetry_schema_version": "hermes.observer.v1",
            }
        ]
        assert "unknown hook 'activity_observation'" not in caplog.text
