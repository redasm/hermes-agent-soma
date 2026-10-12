"""Topical helpers for the Soma host integration."""
from __future__ import annotations
from typing import Any, Optional, Callable
import logging
logger = logging.getLogger(__name__)

def pop_delivery_receipt_callback(
    self,
    session_key: str,
    *,
    generation: int | None = None,
) -> Callable | None:
    """Pop a success-only receipt callback with optional generation ownership."""
    if not session_key:
        return None
    entry = self._delivery_receipt_callbacks.get(session_key)
    if entry is None:
        return None
    if isinstance(entry, tuple) and len(entry) == 2:
        entry_generation, callback = entry
        if generation is not None and int(entry_generation) != int(generation):
            return None
        self._delivery_receipt_callbacks.pop(session_key, None)
        return callback if callable(callback) else None
    if generation is not None:
        return None
    self._delivery_receipt_callbacks.pop(session_key, None)
    return entry if callable(entry) else None


def register_delivery_receipt_callback(
    self,
    session_key: str,
    callback: Callable,
    *,
    generation: int | None = None,
) -> None:
    """Register one callback that fires only after successful main delivery."""
    if not session_key or not callable(callback):
        return
    entry = (int(generation), callback) if generation is not None else callback
    self._delivery_receipt_callbacks[session_key] = entry
