"""Topical helpers for the gateway and scheduled delivery."""
from __future__ import annotations
from gateway.platforms.event import MessageEvent

def _requeue_backoff_delay(self, session_key: str, pending_event: MessageEvent,
                           dispatched_event: MessageEvent) -> float:
    """Delay before re-dispatching the queued follow-up.

    Only the event this task just dispatched coming straight back backs off: the same
    ``message_id``, or for an id-less event the same ``timestamp`` (rewrite-hook
    ``dataclasses.replace`` copies keep both; a genuine new message gets a fresh timestamp).
    The handler put it back because the session is busy elsewhere, and re-dispatching it at
    once hot-loops for the whole busy window (#123229). Any other follow-up resets the counter
    and runs immediately. The first bounce stays immediate (restart auto-resume relies on one
    self-bounce), then back off exponentially to a cap. Defers, never drops."""
    from gateway.platforms.base import (
        jittered_backoff, logger
    )
    # The identical object always matches too: its id equals itself, and when empty the
    # timestamp comparison does.
    same = (pending_event.message_id == dispatched_event.message_id
            and (bool(pending_event.message_id)
                 or pending_event.timestamp == dispatched_event.timestamp))
    if not same:
        self._requeue_counts.pop(session_key, None)
        return 0.0
    attempts = self._requeue_counts.get(session_key, 0)
    self._requeue_counts[session_key] = attempts + 1
    if attempts == 0:
        return 0.0
    delay = jittered_backoff(attempts, base_delay=self._REQUEUE_BACKOFF_INITIAL_SECONDS,
                             max_delay=self._REQUEUE_BACKOFF_MAX_SECONDS, jitter_ratio=0.0)
    (logger.info if attempts == 1 else logger.debug)(
        "[%s] Handler re-queued a pending event for %s again (session busy elsewhere); "
        "backing off %.2fs", self.name, session_key, delay)
    return delay
