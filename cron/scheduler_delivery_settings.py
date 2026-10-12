"""Topical helpers for the gateway and scheduled delivery."""
from __future__ import annotations
from typing import Any, Optional, Callable

def _resolve_cron_surface_mode(pconfig, logical_platform_name: str) -> str:
    """Return ``"in_channel"`` or ``"thread"`` (default) for a platform config.

    Native: flat ``platforms.<p>.extra.cron_continuable_surface``. Relay-fronted:
    ``platforms.relay.extra.<logical>.cron_continuable_surface`` (same sub-block as the relay's
    Slack knobs); the sub-block wins and is scoped to its logical platform. Unlike
    _relay_slack_extra, a sub-block that omits the knob falls back to the flat key (deliberate —
    the flat key must keep working), so a flat value applies to EVERY platform the relay fronts.
    """
    from cron.scheduler_delivery import (
        contextlib
    )
    with contextlib.suppress(Exception):
        extra = getattr(pconfig, "extra", None) or {}
        sub = extra.get(str(logical_platform_name or "").lower())
        raw = sub.get("cron_continuable_surface") if isinstance(sub, dict) else None
        if raw is None:
            raw = extra.get("cron_continuable_surface")
        if raw is not None and str(raw).strip().lower() == "in_channel":
            return "in_channel"
    return "thread"
