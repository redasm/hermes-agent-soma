"""Topical helpers for the Soma host integration."""
from __future__ import annotations
from typing import Any, Optional, Callable
import logging
logger = logging.getLogger(__name__)

def _is_known_busy_slash_command(config: Any, command_name: str) -> bool:
    """Return whether a non-built-in slash command is valid between turns."""
    from hermes_cli.commands import (
        is_gateway_known_command
    )

    if is_gateway_known_command(command_name):
        return True

    if isinstance(config, dict):
        quick_commands = config.get("quick_commands", {}) or {}
    else:
        quick_commands = getattr(config, "quick_commands", {}) or {}
    if isinstance(quick_commands, dict) and command_name in quick_commands:
        return True

    try:
        from agent.skill_bundles import resolve_bundle_command_key

        if resolve_bundle_command_key(command_name) is not None:
            return True
    except Exception:
        logger.exception("Failed to resolve busy skill bundle command")

    try:
        from agent.skill_commands import resolve_skill_command_key

        return resolve_skill_command_key(command_name) is not None
    except Exception:
        logger.exception("Failed to resolve busy skill command")
        return False


def _unknown_slash_command_notice(command_name: str) -> str:
    return (
        f"Unknown command `/{command_name}`. "
        f"Type /commands to see what's available, "
        f"or resend without the leading slash to send "
        f"as a regular message."
    )



def strip_discord_triggering_note(event: Any, message_text: Any) -> Any:
    """Authored text for the durable user row: peel off exactly the note
    ``_prepend_inbound_reply_context`` added for THIS event, if present. The note is a
    model instruction, not something the user wrote — persisted as ``content`` it renders
    verbatim in every transcript surface and pollutes FTS/memory (#71304, #114719). It
    keeps riding ``message_text`` (and the replay-only ``api_content`` sidecar)."""
    from gateway.run_inbound import (
        discord_triggering_note
    )
    message_id = getattr(event, "message_id", None)
    if not message_id or not isinstance(message_text, str):
        return message_text
    prefix = f"{discord_triggering_note(message_id)}\n\n"
    return message_text.removeprefix(prefix)
