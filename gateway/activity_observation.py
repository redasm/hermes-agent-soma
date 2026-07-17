"""Privacy-minimal local application lifecycle observation.

The host only checks whether one explicitly configured process name is
running.  It never emits process ids, command lines, window titles, or the
names of unrelated processes.  Consumer plugins decide what the opaque
lifecycle means; no companion-domain enum belongs here.
"""

from __future__ import annotations

import asyncio
import os
import queue
import threading
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Iterable

import psutil

_STOP = object()


class LocalApplicationObservationPort:
    def __init__(
        self,
        *,
        process_name: str | None = None,
        label: str | None = None,
        poll_interval: float = 1.0,
        process_iter: Callable[[list[str]], Iterable[Any]] | None = None,
    ) -> None:
        self._process_name = str(process_name or "").strip()
        self._label = str(label or "Configured application").strip()
        self._poll_interval = max(0.01, float(poll_interval))
        self._process_iter = process_iter or psutil.process_iter
        self._events: queue.Queue[Any] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._envelope: dict[str, str] = {}

    @property
    def available(self) -> bool:
        return bool(self._process_name)

    async def start(self, _mode: str, grant: Any) -> None:
        if not self.available:
            raise RuntimeError("local application process is not configured")
        if not isinstance(grant, dict) or grant.get("confirmed") is not True:
            raise PermissionError("activity observation requires a confirmed grant")
        subject_id = str(grant.get("subject_id", "")).strip()
        session_id = str(grant.get("session_id", "")).strip()
        if not subject_id or not session_id:
            raise ValueError("activity observation grant requires subject_id and session_id")
        await self.stop()
        self._events = queue.Queue()
        self._stop = threading.Event()
        self._envelope = {"subject_id": subject_id, "session_id": session_id}
        self._thread = threading.Thread(
            target=self._poll,
            args=(self._stop, self._events, dict(self._envelope)),
            name="hermes-activity-observation",
            daemon=True,
        )
        self._thread.start()

    async def stop(self) -> None:
        thread = self._thread
        if thread is not None:
            self._stop.set()
            await asyncio.to_thread(thread.join, max(1.0, self._poll_interval * 2))
        self._thread = None
        self._events.put(_STOP)

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            item = await asyncio.to_thread(self._events.get)
            if item is _STOP:
                return
            if isinstance(item, dict):
                yield item

    def _poll(
        self,
        stop: threading.Event,
        events: queue.Queue[Any],
        envelope: dict[str, str],
    ) -> None:
        was_running = False
        while not stop.is_set():
            running = self._configured_process_is_running()
            if stop.is_set():
                return
            if running != was_running:
                events.put(
                    {
                        **envelope,
                        "origin": "local_process",
                        "occurred_at": datetime.now(timezone.utc).isoformat(),
                        "state": "started" if running else "stopped",
                        "application": self._label,
                    }
                )
                was_running = running
            stop.wait(self._poll_interval)

    def _configured_process_is_running(self) -> bool:
        target = os.path.basename(self._process_name).casefold()
        try:
            processes = self._process_iter(["name"])
            for process in processes:
                name = str(getattr(process, "info", {}).get("name") or "")
                if os.path.basename(name).casefold() == target:
                    return True
        except (OSError, psutil.Error):
            return False
        return False


__all__ = ["LocalApplicationObservationPort"]
