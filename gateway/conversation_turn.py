"""Generic plugin handoff for authenticated ordinary conversation turns."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Iterable

logger = logging.getLogger(__name__)

_VISUAL_MEDIA_RE = re.compile(
    r"MEDIA:((?:[A-Za-z]:[/\\]|/|~/)[^\r\n]+?\.(?:png|jpe?g|gif|webp))(?=\s*$)",
    re.IGNORECASE | re.MULTILINE,
)


def interaction_mode(config: Any) -> str:
    """Return the host's normalized ordinary-turn mode."""

    agent = config.get("agent") if isinstance(config, dict) else None
    value = agent.get("interaction_mode") if isinstance(agent, dict) else None
    normalized = str(value or "agent").strip().lower()
    return normalized if normalized in {"agent", "companion"} else "agent"


def project_dialogue_history(history: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    """Return only persisted user/assistant text for a dialogue consumer."""

    projected: list[dict[str, str]] = []
    for message in history:
        role = message.get("role")
        content = message.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        projected.append({"role": role, "content": content})
    return projected


async def invoke_conversation_turn(**payload: Any) -> dict[str, Any] | None:
    """Return the first valid plugin-owned response or delegation request."""

    from hermes_cli.plugins import invoke_hook

    results = await asyncio.to_thread(invoke_hook, "conversation_turn", **payload)
    responses = [
        result
        for result in results
        if isinstance(result, dict)
        and (
            (
                result.get("action") == "respond"
                and isinstance(result.get("response"), str)
                and result["response"].strip()
            )
            or (
                result.get("action") == "delegate"
                and _valid_capability_request(result.get("capability_request"))
            )
        )
    ]
    if len(responses) > 1:
        logger.warning(
            "Multiple conversation_turn handlers responded; using the first of %d",
            len(responses),
        )
    return responses[0] if responses else None


async def invoke_conversation_capability_result(
    **payload: Any,
) -> dict[str, Any] | None:
    """Return the first valid plugin-authored final response to a task result."""

    from hermes_cli.plugins import invoke_hook

    results = await asyncio.to_thread(
        invoke_hook,
        "conversation_capability_result",
        **payload,
    )
    responses = [
        result
        for result in results
        if isinstance(result, dict)
        and result.get("action") == "respond"
        and isinstance(result.get("response"), str)
        and result["response"].strip()
    ]
    if len(responses) > 1:
        logger.warning(
            "Multiple conversation_capability_result handlers responded; "
            "using the first of %d",
            len(responses),
        )
    return responses[0] if responses else None


async def notify_conversation_turn_delivered(**payload: Any) -> None:
    """Notify plugins after a plugin-owned ordinary reply was actually delivered."""

    from hermes_cli.plugins import invoke_hook

    await asyncio.to_thread(invoke_hook, "conversation_turn_delivered", **payload)


def handler_agent_result(
    handler_result: dict[str, Any],
    *,
    history: list[dict[str, Any]],
    user_message: str,
    session_id: str,
    artifacts: Iterable[str] = (),
) -> dict[str, Any]:
    """Adapt a bounded handler response to the gateway persistence contract."""

    response = handler_result["response"].strip()
    media = [str(path).strip() for path in artifacts if str(path).strip()]
    if media:
        response += "\n" + "\n".join(f"MEDIA:{path}" for path in dict.fromkeys(media))
    return {
        "final_response": response,
        "messages": [
            *history,
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": response},
        ],
        "tools": [],
        "history_offset": len(history),
        "last_prompt_tokens": _non_negative_int(
            handler_result.get("last_prompt_tokens")
        ),
        "api_calls": _non_negative_int(handler_result.get("api_calls")),
        "model": _optional_string(handler_result.get("model")),
        "context_length": _optional_positive_int(handler_result.get("context_length")),
        "session_id": session_id,
        "agent_persisted": False,
        "conversation_delivery_metadata": (
            dict(handler_result["delivery_metadata"])
            if isinstance(handler_result.get("delivery_metadata"), dict)
            else None
        ),
        "failed": False,
        "completed": True,
    }


def capability_task_result(
    capability_request: dict[str, Any],
    agent_result: dict[str, Any],
) -> dict[str, Any]:
    """Project an internal executor result into the bounded host contract."""

    failed = bool(agent_result.get("failed"))
    cancelled = bool(agent_result.get("cancelled"))
    raw_summary = str(agent_result.get("final_response") or "").strip()
    status = "cancelled" if cancelled else "failed" if failed else "completed"
    successful_visual_capture = (
        capability_request.get("kind") == "visual_capture" and status == "completed"
    )
    artifacts = (
        list(dict.fromkeys(_VISUAL_MEDIA_RE.findall(raw_summary)))
        if successful_visual_capture
        else []
    )
    summary = (
        _VISUAL_MEDIA_RE.sub("", raw_summary).strip()
        if successful_visual_capture
        else raw_summary
    )[:20_000]
    return {
        "request_id": str(capability_request["request_id"]),
        "status": status,
        "summary": summary,
        "evidence": [],
        "artifacts": artifacts,
        "error_code": (
            str(agent_result.get("error_code") or "execution_failed")[:200]
            if failed
            else None
        ),
    }


def internal_execution_prompt(capability_request: dict[str, Any]) -> str:
    """Build a bounded non-user-facing executor instruction."""

    if capability_request.get("kind") == "visual_capture":
        grounding = str(capability_request.get("visual_grounding") or "").strip()
        return (
            "You are an internal visual execution worker. Do not address the user and do not "
            "adopt the companion's conversational voice. Execute exactly one visual_capture "
            "using the private grounding below. Read companion_visual_identity; if it is unset, "
            "derive one stable compact appearance from the grounding and save it before the first "
            "photo. Use image_generate to create the requested casual phone photo. Do not add "
            "disclaimers, labels, captions, watermarks, or text to the image. Return a concise "
            "factual result and the generated MEDIA artifact.\n\nObjective:\n"
            + str(capability_request["objective"]).strip()
            + "\n\nPrivate visual grounding:\n"
            + grounding
        )

    return (
        "You are an internal execution worker. Do not address the user and do not "
        "adopt a companion persona. Execute only the bounded objective below using "
        "authorized tools. Return concise factual results, evidence, artifacts, and "
        "errors for Soma to interpret.\n\nObjective:\n"
        + str(capability_request["objective"]).strip()
    )


def _valid_capability_request(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return all(
        isinstance(value.get(field), str) and value[field].strip()
        for field in ("request_id", "kind", "objective")
    )


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _optional_positive_int(value: Any) -> int | None:
    parsed = _non_negative_int(value)
    return parsed or None


def _optional_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
