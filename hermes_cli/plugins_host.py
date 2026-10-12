"""Topical helpers for the Soma host integration."""
from __future__ import annotations
from typing import Any, Optional, Callable
import logging
logger = logging.getLogger(__name__)

def register_inspector(
    self, callback: Callable[[dict[str, Any]], dict[str, Any]]
) -> None:
    """Register one read-only diagnostic snapshot provider for this plugin.

    Inspectors are host-facing observability endpoints. They are not model
    tools and must not mutate plugin state.
    """
    key = self.manifest.key or self.manifest.name
    if key in self._manager._inspectors:
        raise ValueError(f"inspector already registered for plugin {key!r}")
    self._manager._inspectors[key] = callback
    self._manager._track_registration(self.manifest, "inspector", key,
        lambda: self._manager._restore_mapping(self._manager._inspectors, key, callback, None))
    logger.debug("Plugin %s registered inspector", self.manifest.name)


@property
def activity_observation_port(self) -> Any:
    """Return the profile's optional privacy-minimal activity port."""
    if self._activity_observation_port is None:
        from gateway.activity_observation import LocalApplicationObservationPort
        from hermes_cli.config import load_config_readonly

        config = load_config_readonly()
        gateway = config.get("gateway") if isinstance(config, dict) else {}
        settings = (
            gateway.get("activity_observation") if isinstance(gateway, dict) else {}
        )
        if not isinstance(settings, dict):
            settings = {}
        self._activity_observation_port = LocalApplicationObservationPort(
            process_name=settings.get("process_name"),
            label=settings.get("label"),
        )
    return self._activity_observation_port


def get_location_observation(self) -> dict[str, Any]:
    """Return one OS-mediated location observation for this plugin."""
    from hermes_cli.host_observations import (
        observe_location
    )

    return observe_location()


def get_host_observations(self) -> dict[str, Any]:
    """Return minimum, non-secret device context available to plugins."""
    from hermes_time import (
        get_timezone_context
    )

    capabilities = self.get_host_capabilities()
    return {
        "profile": self.profile_name,
        "timezone": get_timezone_context(),
        "location": {
            "status": "unavailable",
            "permission": "unavailable",
            "source": "none",
        },
        "browser": {
            "available": capabilities["tools"]["browser"],
            "authorization": "unknown",
            "source": "host_browser",
        },
        "activity": {
            "available": capabilities["activity"]["observation"],
            "source": "local_process",
        },
    }


def scheduled_event_snapshot(
    self, subject_id: str | None = None
) -> list[dict[str, Any]]:
    """Return the durable scheduled-event snapshot for recovery."""
    return self._scheduled_events().snapshot(subject_id)


def cancel_scheduled_event(self, event_id: str) -> bool:
    """Cancel a pending deadline by stable identity."""
    return self._scheduled_events().cancel(event_id)


def upsert_scheduled_event(
    self,
    *,
    event_id: str,
    subject_id: str,
    due_at: str,
    event_type: str,
    correlation_id: str = "",
) -> dict[str, Any]:
    """Create or replace one durable host-neutral deadline."""
    return self._scheduled_events().upsert(
        event_id=event_id,
        subject_id=subject_id,
        due_at=due_at,
        event_type=event_type,
        correlation_id=correlation_id,
    )


def _scheduled_events(self) -> Any:
    from cron.scheduled_events import (
        ScheduledEventStore
    )

    return ScheduledEventStore(getattr(self, "_scheduled_event_store_path", None))


def get_host_capabilities(self) -> dict[str, Any]:
    """Return the versioned runtime surface currently available to a plugin.

    This is an introspection API, not a model tool. Plugins can select a
    supported adapter path without probing tools and parsing error text.
    """
    from hermes_cli.plugins import (
        HOST_CONTRACT_VERSION, VALID_HOOKS
    )
    from tools.registry import (
        discover_builtin_tools, registry
    )

    # Plugin registration can inspect the host before the agent tool
    # pipeline imports model_tools. Ensure built-in capabilities such as
    # image_generate are visible in that early capability snapshot.
    if registry.get_entry("image_generate") is None:
        discover_builtin_tools()

    names = registry.get_all_tool_names()

    def available(*candidates: str) -> bool:
        return any(registry.get_definitions({name}) for name in candidates)

    return {
        "contract_version": HOST_CONTRACT_VERSION,
        "observations": {
            "timezone": True,
            "location": True,
            "browser_authorization": True,
        },
        "scheduler": {
            "scheduled_context": "cron_context" in VALID_HOOKS,
            "delivery_receipts": "cron_delivery" in VALID_HOOKS,
            "text_only": True,
            "attach_to_session": True,
        },
        "scheduled_events": {
            "available": True,
            "durable": True,
            "cancel": True,
            "dedupe": True,
            "lease": True,
            "ack_nack": True,
        },
        "activity": {
            "observation": self.activity_observation_port.available,
        },
        "tools": {
            "names": sorted(names),
            "web_search": available("web_search"),
            "browser": available("browser_navigate"),
            "image_generation": available("image_generate"),
            "location": available("get_location", "location"),
        },
    }
