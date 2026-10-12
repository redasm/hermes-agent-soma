"""Topical helpers for the Soma host integration."""
from __future__ import annotations
from typing import Any, Optional, Callable
import logging
logger = logging.getLogger(__name__)

def _normalize_multimodal_content(content: Any) -> Any:
    """Validate multimodal content: a plain string when text-only, else canonical ``text`` /
    ``image_url`` parts (native OpenAI vision shape; Anthropic conversion happens downstream).

    Raises ``ValueError("<code>:<message>")`` with codes ``unsupported_content_type`` (file
    parts, non-image data URLs, unknown types), ``invalid_image_url``, ``invalid_content_part``.
    """
    from gateway.platforms.api_server import (
        _FILE_PART_TYPES, _IMAGE_PART_TYPES, _TEXT_PART_TYPES, _cap_list, _cap_text, _normalize_chat_content, _normalize_image_part
    )
    if content is None:
        return ""
    if isinstance(content, str):
        return _cap_text(content)
    if not isinstance(content, list):
        return _normalize_chat_content(content)
    normalized_parts: list[dict[str, Any]] = []
    for part in _cap_list(content):
        if isinstance(part, str):
            if part:
                normalized_parts.append({"type": "text", "text": _cap_text(part)})
            continue
        if not isinstance(part, dict):
            continue  # unknown scalars are ignored for forward compatibility (e.g. ``refusal``)
        raw_type = part.get("type")
        part_type = str(raw_type or "").strip().lower()
        if part_type in _TEXT_PART_TYPES:
            text = part.get("text")
            if text is not None and str(text):
                normalized_parts.append({"type": "text", "text": _cap_text(str(text))})
        elif part_type in _IMAGE_PART_TYPES:
            normalized_parts.append(_normalize_image_part(part))
        elif part_type in _FILE_PART_TYPES:
            raise ValueError(
                "unsupported_content_type:Inline image inputs are supported, "
                "but uploaded files and document inputs are not supported on this endpoint.")
        else:
            raise ValueError(
                f"unsupported_content_type:Unsupported content part type {raw_type!r}. "
                "Only text and image_url/input_image parts are supported.")
    if not normalized_parts:
        return ""
    # Text-only collapses to a plain string so trajectory logging and prompt caching see
    # the native shape.
    if all(p.get("type") == "text" for p in normalized_parts):
        return "\n".join(p["text"] for p in normalized_parts if p.get("text"))
    return normalized_parts


def _public_cron_job(job: dict[str, Any]) -> dict[str, Any]:
    """Return a public cron record without host-only correlation metadata."""
    public = dict(job)
    public.pop("metadata", None)
    if isinstance(public.get("origin"), dict):
        public["origin"] = dict(public["origin"])
        public["origin"].pop("session_id", None)
    return public
