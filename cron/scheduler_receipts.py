"""Delivery evidence and plugin receipts for scheduled jobs."""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional
logger = logging.getLogger("cron.scheduler")

@dataclass(frozen=True)
class CronDeliveryReceipt:
    """Host-owned result of delivering one scheduled job output."""

    job_id: str
    status: str
    targets: tuple[dict, ...] = ()
    metadata: dict = field(default_factory=dict)
    error: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "targets": [dict(target) for target in self.targets],
            "metadata": dict(self.metadata),
            "error": self.error,
        }

def _make_delivery_receipt(
    job: dict,
    status: str,
    targets: Optional[list[dict]] = None,
    error: Optional[str] = None,
) -> CronDeliveryReceipt:
    target_rows = tuple(
        {
            "platform": target.get("platform"),
            "chat_id": str(target.get("chat_id")),
            "thread_id": target.get("thread_id"),
        }
        for target in (targets or [])
    )
    metadata = job.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    runtime_metadata = job.get("_cron_runtime_metadata")
    if isinstance(runtime_metadata, dict):
        metadata = {**metadata, **runtime_metadata}
    return CronDeliveryReceipt(
        job_id=str(job.get("id") or ""),
        status=status,
        targets=target_rows,
        metadata=dict(metadata),
        error=error,
    )

def _notify_cron_delivery(receipt: CronDeliveryReceipt) -> None:
    """Best-effort plugin notification after a host delivery attempt."""
    try:
        from hermes_cli.plugins import invoke_hook

        invoke_hook("cron_delivery", receipt=receipt.as_dict())
    except Exception as exc:
        logger.warning(
            "cron_delivery hook failed for job %r: %s", receipt.job_id, exc, exc_info=True
        )


def _deliver_result_with_receipt(job, content, adapters=None, loop=None, *, for_failure=False):
    from cron import scheduler as _sched
    from cron.scheduler_delivery import _deliver_result_upstream, _resolve_delivery_targets
    try:
        error = _deliver_result_upstream(job, content, adapters, loop, for_failure=for_failure)
    except Exception as exc:
        logger.exception("Cron delivery attempt failed")
        return _sched._make_delivery_receipt(job, "failed", error=str(exc))
    targets = _resolve_delivery_targets(job, for_failure=for_failure)
    error = job.pop("_cron_run_error", None) or error
    status = "failed" if error else "queued" if job.get("last_delivery_queued") else "unverified" if job.get("last_delivery_unverified") else "skipped" if not targets or job.get("_notification_all_targets_suppressed") else "delivered"
    return _sched._make_delivery_receipt(job, status, targets, error)
