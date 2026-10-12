"""Topical helpers for the Soma host integration."""
from __future__ import annotations
from typing import Any, Optional, Callable
import logging
logger = logging.getLogger(__name__)

async def _process_inbound_message(
    self,
    *,
    data: Any,
    message: Any,
    sender_id: Any,
    chat_type: str,
    message_id: str,
    is_bot: bool = False,
) -> None:
    from plugins.platforms.feishu.adapter import (
        MessageEvent, MessageType, _build_mention_hint, _strip_edge_self_mentions, datetime
    )
    text, inbound_type, media_urls, media_types, media_text_inlined, mentions = await self._extract_message_content(message)
    if inbound_type == MessageType.TEXT:
        text = _strip_edge_self_mentions(text, mentions)
        if text.startswith("/"):
            inbound_type = MessageType.COMMAND
    # Post-strip guard so a pure "@Bot" message (stripped to "") is dropped.
    if inbound_type == MessageType.TEXT and not text and not media_urls:
        logger.debug("[Feishu] Ignoring empty text message id=%s", message_id)
        return
    if inbound_type != MessageType.COMMAND:
        hint = _build_mention_hint(mentions)
        if hint:
            text = f"{hint}\n\n{text}" if text else hint

    # Only a native ``thread_id`` marks a topic. ``root_id`` is present on every quoted reply
    # too, so using it as a fallback (#19711) turned ordinary quote replies into topic
    # sessions and pushed the bot's answer into a fresh thread (#20548).
    thread_id = getattr(message, "thread_id", None) or None
    reply_to_message_id = (
        getattr(message, "parent_id", None) or getattr(message, "upper_message_id", None)
        or getattr(message, "root_id", None) or None
    )
    reply_to_text = await self._fetch_message_text(reply_to_message_id) if reply_to_message_id else None
    sender_primary = (
        getattr(sender_id, "open_id", None) or getattr(sender_id, "user_id", None)
        or getattr(sender_id, "union_id", None) or "<unknown>"
    )
    chat_id = getattr(message, "chat_id", "") or ""
    logger.info(
        "[Feishu] Inbound %s message received: id=%s type=%s chat_id=%s sender=%s:%s text=%r media=%d",
        "dm" if chat_type == "p2p" else "group", message_id, inbound_type.value, chat_id,
        "bot" if is_bot else "user", sender_primary, text[:120], len(media_urls),
    )

    chat_info = await self.get_chat_info(chat_id)
    sender_profile = await self._resolve_sender_profile(sender_id, is_bot=is_bot)
    session_thread_id = thread_id
    if chat_type == "p2p":
        raw = self.config.extra.get("dm_top_level_threads_as_sessions")
        threads_as_sessions = (
            True if raw is None else str(raw).strip().lower() in {"1", "true", "yes", "on"}
        )
        if not threads_as_sessions:
            session_thread_id = None
    source = self.build_source(
        chat_id=chat_id,
        chat_name=chat_info.get("name") or chat_id or "Feishu Chat",
        chat_type=self._resolve_source_chat_type(
            chat_info=chat_info, event_chat_type=chat_type
        ),
        user_id=sender_profile["user_id"],
        user_name=sender_profile["user_name"],
        thread_id=session_thread_id,
        user_id_alt=sender_profile["user_id_alt"],
        is_bot=is_bot,
        message_id=message_id,
    )
    normalized = MessageEvent(
        text=text, message_type=inbound_type, source=source, raw_message=data,
        message_id=message_id, media_urls=media_urls, media_types=media_types,
        media_text_inlined=media_text_inlined,
        reply_to_message_id=reply_to_message_id, reply_to_text=reply_to_text,
        channel_prompt=self._resolve_channel_prompt(chat_id, thread_id or None),
        timestamp=datetime.now(),
    )
    await self._dispatch_inbound_event(normalized)
