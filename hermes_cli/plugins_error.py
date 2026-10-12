"""Plugin-provided error classifications."""
from __future__ import annotations
from typing import Any, Optional

def get_plugin_error_classification(
    *, provider: str = "", model: str = "", status_code: Optional[int] = None, error_type: str = "",
    error_code: str = "", error_message: str = "", error_body: Optional[dict[str, Any]] = None,
    error: Optional[BaseException] = None, approx_tokens: int = 0, context_length: int = 0,
    num_messages: int = 0,
) -> Optional[dict[str, Any]]:
    """Consult ``transform_api_error_classification`` hooks BEFORE the built-in classifier.
    Run-all-then-pick-first: the first valid result in registration order wins, losing valid results
    warn (conflicts visible, not shadowed). Returns a sanitized dict (``reason`` -> ``FailoverReason``,
    hint flags -> bool, ``message`` capped at 500) or ``None``. Privacy: inputs may be unredacted.

    A callback returns ``None`` to decline, or a dict with a required ``"reason"`` (a
    :class:`agent.error_classifier.FailoverReason` member or its string name) plus optional recovery-hint
    overrides. Dispatch is run-all-then-pick-first: ``invoke_hook`` runs every registered callback with
    failures isolated, then the first result carrying a valid reason wins in registration order — mirroring
    :func:`get_pre_tool_call_block_message`, invalid or irrelevant returns are silently ignored so a
    misbehaving plugin degrades to a no-op. When more than one callback returns a valid classification, the
    losing results are skipped with a runtime warning (the #64714 skipped-transform rule) so conflicting
    provider plugins are visible in logs instead of silently shadowed.
    """
    from hermes_cli.plugins import Any, invoke_hook, logger, suppress
    from agent.error_classifier import FailoverReason
    hook_results = invoke_hook(
        "transform_api_error_classification", provider=provider, model=model,
        status_code=status_code, error_type=error_type, error_code=error_code,
        error_message=error_message, error_body=error_body if isinstance(error_body, dict) else {},
        error=error, approx_tokens=approx_tokens, context_length=context_length,
        num_messages=num_messages,
    )

    def _reason(result: Any) -> Any:
        reason = result.get("reason") if isinstance(result, dict) else None
        if isinstance(reason, str):
            with suppress(ValueError):
                return FailoverReason(reason.strip().lower())
            return None
        return reason if isinstance(reason, FailoverReason) else None

    valid = [(result, reason) for result in hook_results if (reason := _reason(result)) is not None]
    if not valid:
        return None
    result, reason = valid[0]
    winner: dict[str, Any] = {"reason": reason}
    for key in ("retryable", "should_compress", "should_rotate_credential", "should_fallback"):
        if key in result:
            winner[key] = bool(result[key])
    message = result.get("message")
    if isinstance(message, str) and message.strip():
        winner["message"] = message.strip()[:500]
    if isinstance(result.get("error_context"), dict):
        winner["error_context"] = result["error_context"]
    if len(valid) > 1:
        logger.warning("transform_api_error_classification: skipped %d valid classification(s) after the "
                       "first result in registration order won (run-all-then-pick-first)", len(valid) - 1)
    return winner
