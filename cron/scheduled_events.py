"""Durable, host-neutral one-shot events for plugin wakeups."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from cron.jobs import _jobs_lock
from hermes_constants import get_hermes_home
from utils import atomic_replace


def _default_path() -> Path:
    return get_hermes_home() / "cron" / "scheduled_events.json"


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("due_at must include a timezone")
    return parsed.astimezone(timezone.utc)


class ScheduledEventStore:
    """Atomic snapshot store for typed deadlines without prompts or domain policy."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else _default_path()

    def upsert(
        self,
        *,
        event_id: str,
        subject_id: str,
        due_at: str,
        event_type: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        identity = {
            "event_id": self._required(event_id, "event_id"),
            "subject_id": self._required(subject_id, "subject_id"),
            "due_at": _parse_timestamp(due_at).isoformat(),
            "event_type": self._required(event_type, "event_type"),
            "correlation_id": str(correlation_id or ""),
        }
        with _jobs_lock():
            events = self._load()
            current = next(
                (event for event in events if event.get("event_id") == identity["event_id"]),
                None,
            )
            comparable = {
                key: current.get(key) for key in identity
            } if current is not None else None
            if current is not None and comparable == identity and current.get("status") == "pending":
                return dict(current)
            generation = int(current.get("generation", 0)) + 1 if current else 1
            saved = {**identity, "generation": generation, "status": "pending"}
            events = [
                saved if event.get("event_id") == identity["event_id"] else event
                for event in events
            ]
            if current is None:
                events.append(saved)
            self._save(events)
            return dict(saved)

    def cancel(self, event_id: str) -> bool:
        with _jobs_lock():
            events = self._load()
            for event in events:
                if event.get("event_id") != event_id or event.get("status") != "pending":
                    continue
                event["status"] = "cancelled"
                self._save(events)
                return True
            return False

    def snapshot(self, subject_id: str | None = None) -> list[dict[str, Any]]:
        with _jobs_lock():
            events = self._load()
        if subject_id is not None:
            events = [event for event in events if event.get("subject_id") == subject_id]
        return sorted(events, key=lambda event: (event.get("due_at", ""), event["event_id"]))

    def claim_due(
        self,
        *,
        now: datetime | None = None,
        limit: int | None = None,
        lease_seconds: int = 300,
        max_attempts: int = 5,
    ) -> list[dict[str, Any]]:
        current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        with _jobs_lock():
            events = self._load()
            due = [
                event
                for event in events
                if self._claimable(event, current_time, max_attempts)
                and _parse_timestamp(event["due_at"]) <= current_time
            ]
            due.sort(key=lambda event: (event["due_at"], event["event_id"]))
            if limit is not None:
                due = due[: max(0, limit)]
            claimed_at = current_time.isoformat()
            for event in due:
                event["status"] = "claimed"
                event["claimed_at"] = claimed_at
                event["lease_expires_at"] = (
                    current_time + timedelta(seconds=max(1, lease_seconds))
                ).isoformat()
                event["claim_id"] = uuid.uuid4().hex
                event["attempt_count"] = int(event.get("attempt_count", 0)) + 1
            if due:
                self._save(events)
        return [dict(event) for event in due]

    def ack(self, event_id: str, generation: int, claim_id: str) -> bool:
        return self._finish_claim(
            event_id,
            generation,
            claim_id,
            status="completed",
        )

    def nack(
        self,
        event_id: str,
        generation: int,
        claim_id: str,
        *,
        error_category: str,
        retryable: bool,
        max_attempts: int = 5,
    ) -> bool:
        with _jobs_lock():
            events = self._load()
            event = self._matching_claim(events, event_id, generation, claim_id)
            if event is None:
                return False
            attempts = int(event.get("attempt_count", 0))
            event["status"] = (
                "failed_retryable" if retryable and attempts < max_attempts else "failed_terminal"
            )
            event["last_error_category"] = str(error_category or "unknown")[:80]
            event["failed_at"] = datetime.now(timezone.utc).isoformat()
            self._save(events)
            return True

    def _finish_claim(
        self,
        event_id: str,
        generation: int,
        claim_id: str,
        *,
        status: str,
    ) -> bool:
        with _jobs_lock():
            events = self._load()
            event = self._matching_claim(events, event_id, generation, claim_id)
            if event is None:
                return False
            event["status"] = status
            event["completed_at"] = datetime.now(timezone.utc).isoformat()
            self._save(events)
            return True

    @staticmethod
    def _matching_claim(
        events: list[dict[str, Any]], event_id: str, generation: int, claim_id: str
    ) -> dict[str, Any] | None:
        return next(
            (
                event
                for event in events
                if event.get("event_id") == event_id
                and int(event.get("generation", 0)) == int(generation)
                and event.get("claim_id") == claim_id
                and event.get("status") == "claimed"
            ),
            None,
        )

    @staticmethod
    def _claimable(
        event: dict[str, Any], current_time: datetime, max_attempts: int
    ) -> bool:
        status = event.get("status")
        if status == "pending":
            return True
        if status == "failed_retryable":
            return int(event.get("attempt_count", 0)) < max_attempts
        if status != "claimed":
            return False
        lease_expires_at = event.get("lease_expires_at")
        if not lease_expires_at:
            return True
        return _parse_timestamp(lease_expires_at) <= current_time

    @staticmethod
    def _required(value: str, name: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{name} must not be blank")
        return normalized

    def _load(self) -> list[dict[str, Any]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
            raise RuntimeError("scheduled event store is corrupt")
        return [dict(event) for event in payload["events"] if isinstance(event, dict)]

    def _save(self, events: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            dir=self.path.parent, prefix=".scheduled-events-", suffix=".json"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"schema_version": 1, "events": events}, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            atomic_replace(temporary, self.path)
        finally:
            try:
                os.remove(temporary)
            except FileNotFoundError:
                pass


def dispatch_due_scheduled_events(
    *,
    store: ScheduledEventStore | None = None,
    deliver: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
    adapters: Any = None,
    loop: Any = None,
) -> int:
    """Claim and notify due events only when a plugin consumer is ready."""
    from hermes_cli.plugins import get_plugin_manager, has_hook, invoke_hook

    if not has_hook("scheduled_event_due"):
        return 0
    event_store = store or ScheduledEventStore()
    claimed = event_store.claim_due()
    for event in claimed:
        _emit_lifecycle(invoke_hook, event, "claimed")
        due_events = [
            {
                "event_id": candidate["event_id"],
                "subject_id": candidate["subject_id"],
                "due_at": candidate["due_at"],
                "event_type": candidate["event_type"],
                "correlation_id": candidate["correlation_id"],
                "generation": candidate["generation"],
                "claim_id": candidate["claim_id"],
            }
            for candidate in claimed
            if candidate["subject_id"] == event["subject_id"]
        ]
        results, error_count = get_plugin_manager().invoke_hook_report(
            "scheduled_event_due",
            event_id=event["event_id"],
            subject_id=event["subject_id"],
            due_at=event["due_at"],
            event_type=event["event_type"],
            correlation_id=event["correlation_id"],
            generation=event["generation"],
            claim_id=event["claim_id"],
            due_events=due_events,
        )
        if error_count:
            event_store.nack(
                event["event_id"],
                event["generation"],
                event["claim_id"],
                error_category="consumer_error",
                retryable=True,
            )
            _emit_lifecycle(
                invoke_hook,
                event,
                "failed_retryable",
                error_category="consumer_error",
            )
            continue
        request = next(
            (
                result
                for result in results
                if _valid_outreach_request(result, event["subject_id"])
            ),
            None,
        )
        if request is None:
            event_store.ack(event["event_id"], event["generation"], event["claim_id"])
            _emit_lifecycle(invoke_hook, event, "completed")
            continue
        try:
            receipt = (
                _deliver_outreach(event, request, adapters=adapters, loop=loop)
                if deliver is None
                else deliver(event, request)
            )
        except Exception:
            event_store.nack(
                event["event_id"],
                event["generation"],
                event["claim_id"],
                error_category="delivery_error",
                retryable=True,
            )
            _emit_lifecycle(
                invoke_hook,
                event,
                "failed_retryable",
                error_category="delivery_error",
            )
            continue
        invoke_hook(
            "scheduled_outreach_delivery",
            event_id=event["event_id"],
            subject_id=event["subject_id"],
            generation=event["generation"],
            claim_id=event["claim_id"],
            action_id=request["action_id"],
            delivery_attempt_id=request["delivery_attempt_id"],
            status=str(receipt.get("status") or "failed"),
            targets=list(receipt.get("targets") or []),
            error=receipt.get("error"),
        )
        event_store.ack(event["event_id"], event["generation"], event["claim_id"])
        _emit_lifecycle(invoke_hook, event, "completed")
    return len(claimed)


def _emit_lifecycle(
    invoke_hook: Callable[..., Any],
    event: dict[str, Any],
    transition: str,
    *,
    error_category: str = "",
) -> None:
    try:
        due_at = _parse_timestamp(event["due_at"])
        invoke_hook(
            "scheduled_event_lifecycle",
            event_id=event["event_id"],
            subject_id=event["subject_id"],
            event_type=event["event_type"],
            generation=event["generation"],
            claim_id=event.get("claim_id", ""),
            transition=transition,
            error_category=error_category,
            attempt_count=int(event.get("attempt_count", 0)),
            lateness_seconds=max(
                0.0,
                (datetime.now(timezone.utc) - due_at).total_seconds(),
            ),
        )
    except Exception:
        return


def _valid_outreach_request(value: object, subject_id: str) -> bool:
    if not isinstance(value, dict) or value.get("subject_id") != subject_id:
        return False
    required = ("action_id", "delivery_attempt_id", "content")
    if not all(isinstance(value.get(key), str) and value[key].strip() for key in required):
        return False
    return len(value["content"]) <= 4000


def _deliver_outreach(
    event: dict[str, Any],
    request: dict[str, Any],
    *,
    adapters: Any = None,
    loop: Any = None,
) -> dict[str, Any]:
    from cron.scheduler import _deliver_result_with_receipt

    origin = _recent_verified_origin(request["subject_id"], adapters)
    job = {
        "id": event["event_id"],
        "name": event["event_type"],
        "deliver": "origin",
        "origin": origin,
        "response_mode": "text_only",
        "metadata": {
            "action_id": request["action_id"],
            "delivery_attempt_id": request["delivery_attempt_id"],
            "subject_id": request["subject_id"],
            "route_source": (
                "recent_verified_session" if origin is not None else "host_configured_home"
            ),
        },
    }
    receipt = _deliver_result_with_receipt(
        job, request["content"], adapters=adapters, loop=loop
    ).as_dict()
    if receipt.get("status") == "skipped" and not receipt.get("targets"):
        return {"status": "failed", "targets": [], "error": "no_verified_route"}
    return receipt


def _recent_verified_origin(subject_id: str, adapters: Any) -> dict[str, Any] | None:
    if subject_id != "user:local":
        return None
    connected = _connected_platforms(adapters)
    if not connected:
        return None
    try:
        from hermes_state import SessionDB

        database = SessionDB()
        try:
            rows = database.list_gateway_sessions(active_only=False)
        finally:
            database.close()
    except Exception:
        return None
    for row in rows:
        origin = _session_origin(row)
        if origin is None or origin["platform"] not in connected:
            continue
        return origin
    return None


def _connected_platforms(adapters: Any) -> set[str]:
    if not isinstance(adapters, dict):
        return set()
    return {
        str(getattr(platform, "value", platform)).strip().lower()
        for platform in adapters
        if str(getattr(platform, "value", platform)).strip()
    }


def _session_origin(row: dict[str, Any]) -> dict[str, Any] | None:
    origin: dict[str, Any] = {}
    raw = row.get("origin_json")
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                origin = parsed
        except (TypeError, ValueError):
            pass
    platform = str(origin.get("platform") or row.get("source") or "").strip().lower()
    chat_id = str(origin.get("chat_id") or row.get("chat_id") or "").strip()
    chat_type = str(origin.get("chat_type") or row.get("chat_type") or "").strip().lower()
    if not platform or not chat_id or chat_type not in {"dm", "direct", "private"}:
        return None
    selected = {
        "platform": platform,
        "chat_id": chat_id,
        "user_id": str(origin.get("user_id") or row.get("user_id") or "").strip(),
        "chat_type": chat_type,
    }
    thread_id = origin.get("thread_id", row.get("thread_id"))
    if thread_id not in (None, ""):
        selected["thread_id"] = str(thread_id)
    return selected


__all__ = ["ScheduledEventStore", "dispatch_due_scheduled_events"]
