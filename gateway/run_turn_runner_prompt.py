"""Topical helpers for the Soma host integration."""
from __future__ import annotations
from typing import Any, Optional, Callable
import logging
logger = logging.getLogger(__name__)

def _combined_ephemeral_prompt(self) -> str:
    """Platform context + YAML channel_prompts hint + channel_overrides system_prompt (or global
    ephemeral) + the gateway ephemeral prompt."""
    ctx = self._ctx
    if ctx.internal_execution:
        return ""
    combined = ctx.context_prompt or ""
    for extra in (
        (ctx.channel_prompt or "").strip(),
        self._runner._get_system_prompt_for_channel(
            ctx.source.platform, ctx.source.chat_id or "", thread_id=getattr(ctx.source, "thread_id", None),
            parent_id=getattr(ctx.source, "parent_chat_id", None),
        ),
    ):
        if extra:
            combined = (combined + "\n\n" + extra).strip()
    return combined
