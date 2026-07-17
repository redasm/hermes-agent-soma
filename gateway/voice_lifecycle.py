"""Generic voice lifecycle notifications for host plugins.

The events carry transport metadata only.  Companion/domain semantics remain
in a consumer plugin such as Soma.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def _invoke_hook(name: str, **payload: Any) -> None:
    from hermes_cli.plugins import invoke_hook

    invoke_hook(name, **payload)


def _emit(name: str, session_id: str, *, subject_id: str, origin: str, **payload: Any) -> None:
    _invoke_hook(
        name,
        session_id=session_id,
        subject_id=subject_id,
        origin=origin,
        occurred_at=datetime.now(timezone.utc).isoformat(),
        **payload,
    )


def emit_voice_session_start(session_id: str, *, subject_id: str, origin: str) -> None:
    _emit("voice_session_start", session_id, subject_id=subject_id, origin=origin)


def emit_voice_transcript(
    session_id: str,
    *,
    subject_id: str,
    text: str,
    final: bool,
    origin: str,
    turn_id: str,
    action_id: str = "",
) -> None:
    turn_id = str(turn_id).strip()
    action_id = str(action_id).strip()
    if not turn_id:
        raise ValueError("voice transcript requires turn_id")
    if final and not action_id:
        raise ValueError("final voice transcript requires action_id")
    _emit(
        "voice_transcript",
        session_id,
        subject_id=subject_id,
        origin=origin,
        text=text,
        final=bool(final),
        turn_id=turn_id,
        action_id=action_id,
    )


def emit_voice_barge_in(
    session_id: str,
    *,
    subject_id: str,
    turn_id: str,
    action_id: str,
    origin: str,
    latency_ms: float | None = None,
) -> None:
    turn_id = str(turn_id).strip()
    if not turn_id:
        raise ValueError("voice barge-in requires turn_id")
    payload: dict[str, Any] = {"action_id": action_id}
    payload["turn_id"] = turn_id
    if latency_ms is not None:
        latency_ms = float(latency_ms)
        if not math.isfinite(latency_ms) or latency_ms < 0:
            raise ValueError("voice barge-in latency must be finite and non-negative")
        payload["latency_ms"] = latency_ms
    _emit(
        "voice_barge_in",
        session_id,
        subject_id=subject_id,
        origin=origin,
        **payload,
    )


def emit_voice_response_start(
    session_id: str,
    *,
    subject_id: str,
    turn_id: str,
    action_id: str,
    origin: str,
    latency_ms: float,
) -> None:
    turn_id = str(turn_id).strip()
    if not turn_id:
        raise ValueError("voice response start requires turn_id")
    action_id = str(action_id).strip()
    if not action_id:
        raise ValueError("voice response start requires action_id")
    latency_ms = float(latency_ms)
    if not math.isfinite(latency_ms) or latency_ms < 0:
        raise ValueError("voice first-response latency must be finite and non-negative")
    _emit(
        "voice_response_start",
        session_id,
        subject_id=subject_id,
        origin=origin,
        turn_id=turn_id,
        action_id=action_id,
        latency_ms=latency_ms,
    )


def emit_voice_delivery(
    session_id: str,
    *,
    subject_id: str,
    turn_id: str,
    action_id: str,
    origin: str,
    delivered: bool,
) -> None:
    turn_id = str(turn_id).strip()
    if not turn_id:
        raise ValueError("voice delivery requires turn_id")
    action_id = str(action_id).strip()
    if not action_id:
        raise ValueError("voice delivery requires action_id")
    if not isinstance(delivered, bool):
        raise ValueError("voice delivery delivered must be boolean")
    _emit(
        "voice_delivery",
        session_id,
        subject_id=subject_id,
        origin=origin,
        turn_id=turn_id,
        action_id=action_id,
        delivered=delivered,
    )


def emit_voice_session_end(session_id: str, *, subject_id: str, origin: str) -> None:
    _emit("voice_session_end", session_id, subject_id=subject_id, origin=origin)


__all__ = [
    "emit_voice_barge_in",
    "emit_voice_delivery",
    "emit_voice_response_start",
    "emit_voice_session_end",
    "emit_voice_session_start",
    "emit_voice_transcript",
]
