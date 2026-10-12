"""Plugin-owned conversation routing and private capability delegation."""
from __future__ import annotations
import logging
logger = logging.getLogger("gateway.run")

async def execute_conversation_turn(self, event, source, prepared, history, message_text, plain_user_message, interaction_mode_value, run_start_session_id, session_key, run_generation, turn_source, turn_channel_prompt):
    from gateway.run_turn import reply_expected_metadata, diagnostic_metadata
    conversation_result = None
    if not getattr(event, "internal", False) and not event.is_command():
        from gateway.conversation_turn import invoke_conversation_turn, project_dialogue_history

        _conversation_payload = dict(
            user_message=plain_user_message,
            input_text=message_text,
            interaction_mode=interaction_mode_value,
            history=project_dialogue_history(history),
            quoted_message={
                "message_id": getattr(event, "reply_to_message_id", None),
                "text": getattr(event, "reply_to_text", None),
                "author_id": getattr(event, "reply_to_author_id", None),
                "author_name": getattr(event, "reply_to_author_name", None),
                "is_own_message": bool(
                    getattr(event, "reply_to_is_own_message", False)
                ),
            },
            platform=source.platform.value if source.platform else "",
            user_id=source.user_id,
            user_name=source.user_name,
            chat_id=source.chat_id or "",
            chat_type=getattr(source, "chat_type", "") or "",
            thread_id=str(getattr(source, "thread_id", None) or ""),
            session_id=run_start_session_id,
            session_key=session_key,
            message_id=str(getattr(event, "message_id", None) or ""),
            received_at=getattr(event, "timestamp", None),
        )
        with self._profile_scope_for_source(source):
            conversation_result = await invoke_conversation_turn(
                **_conversation_payload
            )

    if conversation_result is not None:
        self._pending_turn_sidecar_notes.pop(session_key, None)
        from gateway.conversation_turn import handler_agent_result

        if conversation_result.get("action") == "delegate":
            from gateway.conversation_turn import (
                capability_task_result,
                execute_visual_capture,
                internal_execution_prompt,
                invoke_conversation_capability_result,
            )

            _capability_request = conversation_result["capability_request"]
            _capability_id = str(_capability_request["request_id"])
            if _capability_request.get("kind") == "visual_capture":
                with self._profile_scope_for_source(source):
                    _task_result = await execute_visual_capture(_capability_request)
            else:
                _executor_result = await self._run_agent(
                    message=internal_execution_prompt(_capability_request),
                    context_prompt="",
                    history=[],
                    source=source,
                    session_id=f"{run_start_session_id}:{_capability_id}",
                    session_key=f"{session_key}:{_capability_id}",
                    run_generation=run_generation,
                    event_message_id=None,
                    channel_prompt=None,
                    moa_config=None,
                    persist_user_message=None,
                    persist_user_timestamp=None,
                    internal_execution=True,
                )
                _task_result = capability_task_result(
                    _capability_request,
                    _executor_result,
                )
            with self._profile_scope_for_source(source):
                _final_result = await invoke_conversation_capability_result(
                    **_conversation_payload,
                    capability_request=_capability_request,
                    task_result=_task_result,
                )
            if _final_result is None:
                logger.error(
                    "Companion delegation had no plugin finalizer; "
                    "refusing executor output"
                )
                return None
            agent_result = handler_agent_result(
                _final_result,
                history=history,
                user_message=plain_user_message,
                session_id=run_start_session_id,
                artifacts=(
                    _task_result["artifacts"]
                    if _capability_request.get("kind") == "visual_capture"
                    else ()
                ),
            )
        else:
            agent_result = handler_agent_result(
                conversation_result,
                history=history,
                user_message=plain_user_message,
                session_id=run_start_session_id,
            )
    elif interaction_mode_value == "companion":
        self._pending_turn_sidecar_notes.pop(session_key, None)
        logger.error(
            "Companion turn had no plugin owner; refusing implicit agent fallback"
        )
        try:
            _owner_adapter = self._delivery_adapter_for(source)
            if _owner_adapter:
                await _owner_adapter.stop_typing(source.chat_id)
        except Exception:
            logger.exception("Failed to stop typing for unowned companion turn")
        return None
    else:
        agent_result = await self._run_agent(
            message=message_text,
            context_prompt=prepared.context_prompt,
            history=history,
            source=turn_source,
            session_id=run_start_session_id,
            session_key=session_key,
            run_generation=run_generation,
            event_message_id=self._reply_anchor_for_event(event),
            inbound_message_id=str(event.message_id) if event.message_id else None,
            channel_prompt=turn_channel_prompt,
            moa_config=getattr(event, "_moa_config", None),
            title_user_message=prepared.title_user_message,
            persist_user_message=prepared.persist_user_message,
            persist_user_timestamp=prepared.persist_user_timestamp,
            persist_user_display_kind=prepared.persist_user_display_kind,
            reply_expected=event.reply_expected,
            persist_user_display_metadata={
                "gateway_input_owner": prepared.persistence_owner,
                **reply_expected_metadata(event.reply_expected),
                **diagnostic_metadata(event),
            },
            message_type=event.message_type,
            scheduled_heartbeat=bool(getattr(event, "_heartbeat_session_id", None)),
        )
    return agent_result

def register_conversation_receipt(self, agent_result, response, source, session_entry, session_key, run_generation):
    metadata = agent_result.get("conversation_delivery_metadata")
    if response and isinstance(metadata, dict):
        adapter = self._delivery_adapter_for(source)
        register = getattr(adapter, "register_delivery_receipt_callback", None)
        if callable(register):
            from gateway.conversation_turn import notify_conversation_turn_delivered
            async def notify(_sid=session_entry.session_id, _key=session_key):
                _metadata = dict(metadata)
                await notify_conversation_turn_delivered(delivery_metadata=_metadata, session_id=_sid, session_key=_key)
            register(session_key, notify, generation=run_generation)
