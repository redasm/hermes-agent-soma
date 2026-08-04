"""Gateway contract for plugin-owned ordinary conversation turns."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

import gateway.run as gateway_run
import hermes_cli.plugins as plugin_runtime
from gateway.config import GatewayConfig, Platform
from gateway.platforms.base import MessageEvent
from gateway.session import SessionEntry, SessionSource
from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest

SESSION_KEY = "agent:main:telegram:group:-1001:12345"


def _source() -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="-1001",
        chat_type="group",
        user_id="12345",
    )


def _event() -> MessageEvent:
    return MessageEvent(
        text="I meant why you stayed home.",
        source=_source(),
        message_id="msg-42",
        reply_to_message_id="msg-41",
        reply_to_text="Use /sethome to choose a home channel.",
        reply_to_author_id="bot",
        reply_to_author_name="Companion",
        reply_to_is_own_message=True,
    )


def _runner(monkeypatch, tmp_path) -> gateway_run.GatewayRunner:
    runner = gateway_run.GatewayRunner(GatewayConfig())
    runner.adapters = {}
    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner._pending_messages = {}
    runner._pending_approvals = {}
    runner._is_user_authorized = lambda _source: True
    runner._set_session_env = lambda _context: None
    runner._handle_active_session_busy_message = AsyncMock(return_value=False)
    runner._session_db = MagicMock()
    runner._recover_telegram_topic_thread_id = lambda _source: None
    runner._cache_session_source = lambda _key, _source: None
    runner._is_session_run_current = lambda _key, _gen: True
    runner._begin_session_run_generation = lambda _key: 1
    runner._reply_anchor_for_event = lambda _event: None
    runner._get_guild_id = lambda _event: None
    runner._should_send_voice_reply = lambda *_a, **_kw: False
    runner.hooks = MagicMock()
    runner.hooks.emit = AsyncMock()

    runner.session_store = MagicMock()
    runner.session_store.get_or_create_session.return_value = SessionEntry(
        session_key=SESSION_KEY,
        session_id="sess-companion",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        platform=Platform.TELEGRAM,
        chat_type="group",
    )
    runner.session_store.load_transcript.return_value = [
        {"role": "session_meta", "tools": [{"name": "terminal"}]},
        {"role": "user", "content": "Why didn't you go out?"},
        {"role": "assistant", "content": "Use /sethome first."},
    ]
    runner.session_store.has_platform_message_id.return_value = False
    runner.session_store.append_to_transcript = MagicMock()
    runner.session_store.update_session = MagicMock()

    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    monkeypatch.setattr(
        gateway_run,
        "_resolve_runtime_agent_kwargs",
        lambda: {"api_key": "fake"},
    )
    monkeypatch.setattr(
        gateway_run,
        "_load_gateway_config",
        lambda: {"agent": {"interaction_mode": "companion"}},
    )
    monkeypatch.setattr(
        "agent.model_metadata.get_model_context_length",
        lambda *_args, **_kwargs: 100_000,
    )
    return runner


@pytest.mark.asyncio
async def test_plugin_conversation_response_bypasses_agent_and_persists_clean_turn(
    monkeypatch,
    tmp_path,
):
    runner = _runner(monkeypatch, tmp_path)
    runner._run_agent = AsyncMock(
        return_value={
            "final_response": "agent path",
            "messages": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
        }
    )

    seen = {}
    manager = PluginManager()
    context = PluginContext(PluginManifest(name="dialogue-test"), manager)

    def respond(**turn):
        seen.update(turn)
        return {
            "action": "respond",
            "response": "I was tired, so I stayed in.",
            "api_calls": 1,
            "model": "test-dialogue-model",
            "last_prompt_tokens": 17,
        }

    context.register_hook("conversation_turn", respond)
    monkeypatch.setattr(plugin_runtime, "_plugin_manager", manager)
    runner._set_pending_turn_sidecar_notes(
        SESSION_KEY,
        ["[System note: introduce the agent and mention /help.]"],
    )

    response = await runner._handle_message_with_agent(
        _event(), _source(), SESSION_KEY, 1
    )

    assert response == "I was tired, so I stayed in."
    runner._run_agent.assert_not_awaited()
    assert seen["user_message"] == "I meant why you stayed home."
    assert seen["interaction_mode"] == "companion"
    assert seen["history"] == [
        {"role": "user", "content": "Why didn't you go out?"},
        {"role": "assistant", "content": "Use /sethome first."},
    ]
    assert seen["quoted_message"] == {
        "message_id": "msg-41",
        "text": "Use /sethome to choose a home channel.",
        "author_id": "bot",
        "author_name": "Companion",
        "is_own_message": True,
    }

    appended = [
        call.args[1]
        for call in runner.session_store.append_to_transcript.call_args_list
    ]
    assert [message["role"] for message in appended] == ["user", "assistant"]
    assert appended[0]["content"] == "I meant why you stayed home."
    assert appended[0]["message_id"] == "msg-42"
    assert appended[1]["content"] == "I was tired, so I stayed in."
    assert all(
        call.kwargs.get("skip_db") is False
        for call in runner.session_store.append_to_transcript.call_args_list
    )
    assert runner._consume_pending_turn_sidecar_notes(SESSION_KEY) == []


@pytest.mark.asyncio
async def test_companion_mode_without_an_owner_never_falls_back_to_agent(
    monkeypatch,
    tmp_path,
):
    runner = _runner(monkeypatch, tmp_path)
    runner._run_agent = AsyncMock(
        return_value={
            "final_response": "Hermes agent response must stay private.",
            "messages": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
        }
    )
    monkeypatch.setattr(plugin_runtime, "_plugin_manager", PluginManager())

    response = await runner._handle_message_with_agent(
        _event(), _source(), SESSION_KEY, 1
    )

    assert response is None
    runner._run_agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_companion_delegation_keeps_executor_output_private_and_returns_soma_reply(
    monkeypatch,
    tmp_path,
):
    runner = _runner(monkeypatch, tmp_path)
    runner._run_agent = AsyncMock(
        return_value={
            "final_response": "RAW HERMES EXECUTOR OUTPUT",
            "messages": [
                {"role": "assistant", "content": "RAW HERMES EXECUTOR OUTPUT"}
            ],
            "tools": [{"name": "terminal"}],
            "history_offset": 0,
            "last_prompt_tokens": 23,
            "api_calls": 2,
            "model": "executor-model",
            "failed": False,
            "completed": True,
        }
    )

    seen_result = {}
    manager = PluginManager()
    context = PluginContext(PluginManifest(name="dialogue-test"), manager)
    request = {
        "request_id": "capability:req-42",
        "subject_id": "user:local",
        "turn_id": "msg-42",
        "kind": "hermes_task",
        "objective": "Run the repository tests.",
        "interest": None,
    }
    context.register_hook(
        "conversation_turn",
        lambda **_turn: {
            "action": "delegate",
            "capability_request": request,
        },
    )

    def finish(**payload):
        seen_result.update(payload)
        return {
            "action": "respond",
            "response": "测试跑完了，有一处路由测试失败。",
        }

    context.register_hook("conversation_capability_result", finish)
    monkeypatch.setattr(plugin_runtime, "_plugin_manager", manager)

    response = await runner._handle_message_with_agent(
        _event(), _source(), SESSION_KEY, 1
    )

    assert response == "测试跑完了，有一处路由测试失败。"
    execution = runner._run_agent.await_args.kwargs
    assert execution["internal_execution"] is True
    assert execution["history"] == []
    assert execution["session_id"].endswith(":capability:req-42")
    assert execution["session_key"].endswith(":capability:req-42")
    assert "Run the repository tests." in execution["message"]
    assert seen_result["capability_request"] == request
    assert seen_result["task_result"] == {
        "request_id": "capability:req-42",
        "status": "completed",
        "summary": "RAW HERMES EXECUTOR OUTPUT",
        "evidence": [],
        "artifacts": [],
        "error_code": None,
    }

    appended = [
        call.args[1]
        for call in runner.session_store.append_to_transcript.call_args_list
    ]
    assert [message["role"] for message in appended] == ["user", "assistant"]
    assert appended[-1]["content"] == "测试跑完了，有一处路由测试失败。"
    assert all("RAW HERMES" not in str(message) for message in appended)
    assert all("terminal" not in str(message) for message in appended)


@pytest.mark.asyncio
async def test_visual_capture_delegation_preserves_generated_media_for_delivery(
    monkeypatch,
    tmp_path,
):
    runner = _runner(monkeypatch, tmp_path)
    image = tmp_path / "generated-selfie.png"
    image.write_bytes(b"image")
    runner._run_agent = AsyncMock(
        return_value={
            "final_response": f"Created the requested image.\nMEDIA:{image}",
            "messages": [],
            "tools": [{"name": "image_generate"}],
            "failed": False,
            "completed": True,
        }
    )
    manager = PluginManager()
    context = PluginContext(PluginManifest(name="visual-dialogue-test"), manager)
    request = {
        "request_id": "capability:visual-42",
        "subject_id": "user:local",
        "turn_id": "msg-42",
        "kind": "visual_capture",
        "objective": "Take and send one casual photo at home.",
        "interest": None,
        "visual_grounding": '{"appearance":"stable","situation":"at home"}',
    }
    context.register_hook(
        "conversation_turn",
        lambda **_turn: {"action": "delegate", "capability_request": request},
    )

    seen_result = {}

    def finish(**payload):
        seen_result.update(payload)
        return {"action": "respond", "response": "等我一下。"}

    context.register_hook("conversation_capability_result", finish)
    monkeypatch.setattr(plugin_runtime, "_plugin_manager", manager)

    response = await runner._handle_message_with_agent(
        _event(), _source(), SESSION_KEY, 1
    )

    assert response == f"等我一下。\nMEDIA:{image}"
    assert seen_result["task_result"]["summary"] == "Created the requested image."
    assert seen_result["task_result"]["artifacts"] == [str(image)]
    execution_prompt = runner._run_agent.await_args.kwargs["message"]
    assert "visual_capture" in execution_prompt
    assert "stable" in execution_prompt
    assert "image_generate" in execution_prompt


def test_non_visual_capability_result_does_not_reinterpret_media_text():
    from gateway.conversation_turn import capability_task_result

    result = capability_task_result(
        {"request_id": "capability:task-42", "kind": "hermes_task"},
        {
            "final_response": "Task output includes MEDIA:/tmp/report.png",
            "failed": False,
            "cancelled": False,
        },
    )

    assert result["summary"] == "Task output includes MEDIA:/tmp/report.png"
    assert result["artifacts"] == []


@pytest.mark.asyncio
async def test_companion_delegation_without_soma_finalizer_never_exposes_executor_output(
    monkeypatch,
    tmp_path,
):
    runner = _runner(monkeypatch, tmp_path)
    runner._run_agent = AsyncMock(
        return_value={
            "final_response": "RAW PRIVATE RESULT",
            "messages": [],
            "failed": False,
            "completed": True,
        }
    )
    manager = PluginManager()
    context = PluginContext(PluginManifest(name="dialogue-test"), manager)
    context.register_hook(
        "conversation_turn",
        lambda **_turn: {
            "action": "delegate",
            "capability_request": {
                "request_id": "capability:no-finalizer",
                "subject_id": "user:local",
                "turn_id": "msg-42",
                "kind": "hermes_task",
                "objective": "Inspect the repository.",
                "interest": None,
            },
        },
    )
    monkeypatch.setattr(plugin_runtime, "_plugin_manager", manager)

    response = await runner._handle_message_with_agent(
        _event(), _source(), SESSION_KEY, 1
    )

    assert response is None
    assert all(
        "RAW PRIVATE RESULT" not in str(call)
        for call in runner.session_store.append_to_transcript.call_args_list
    )


@pytest.mark.asyncio
async def test_plugin_conversation_delivery_metadata_waits_for_success_receipt(
    monkeypatch,
    tmp_path,
):
    runner = _runner(monkeypatch, tmp_path)
    runner._run_agent = AsyncMock()

    class Adapter:
        def __init__(self):
            self.callbacks = []

        def register_delivery_receipt_callback(
            self,
            session_key,
            callback,
            *,
            generation=None,
        ):
            self.callbacks.append((session_key, callback, generation))

        async def stop_typing(self, _chat_id):
            return None

    adapter = Adapter()
    runner._adapter_for_source = lambda _source: adapter
    delivered = []
    manager = PluginManager()
    context = PluginContext(PluginManifest(name="dialogue-test"), manager)
    context.register_hook(
        "conversation_turn",
        lambda **_turn: {
            "action": "respond",
            "response": "I found one thing worth sharing.",
            "delivery_metadata": {"owner": "dialogue-test", "token": "discovery-7"},
        },
    )
    context.register_hook(
        "conversation_turn_delivered",
        lambda **receipt: delivered.append(receipt),
    )
    monkeypatch.setattr(plugin_runtime, "_plugin_manager", manager)

    response = await runner._handle_message_with_agent(
        _event(), _source(), SESSION_KEY, 1
    )

    assert response == "I found one thing worth sharing."
    assert delivered == []
    assert len(adapter.callbacks) == 1
    session_key, callback, generation = adapter.callbacks[0]
    assert session_key == SESSION_KEY
    assert generation == 1

    await callback()

    assert delivered == [
        {
            "delivery_metadata": {"owner": "dialogue-test", "token": "discovery-7"},
            "session_id": "sess-companion",
            "session_key": SESSION_KEY,
            "telemetry_schema_version": "hermes.observer.v1",
        }
    ]


@pytest.mark.asyncio
async def test_companion_first_turn_does_not_send_agent_home_channel_notice(
    monkeypatch,
    tmp_path,
):
    runner = _runner(monkeypatch, tmp_path)
    runner.session_store.load_transcript.return_value = []
    runner.session_store.has_any_sessions = AsyncMock(return_value=False)
    runner._deliver_platform_notice = AsyncMock()
    runner._run_agent = AsyncMock()

    manager = PluginManager()
    context = PluginContext(PluginManifest(name="dialogue-test"), manager)
    context.register_hook(
        "conversation_turn",
        lambda **_turn: {
            "action": "respond",
            "response": "I stayed close today.",
        },
    )
    monkeypatch.setattr(plugin_runtime, "_plugin_manager", manager)

    response = await runner._handle_message_with_agent(
        _event(), _source(), SESSION_KEY, 1
    )

    assert response == "I stayed close today."
    runner._deliver_platform_notice.assert_not_awaited()
    runner._run_agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_companion_first_turn_does_not_consume_agent_onboarding(
    monkeypatch,
    tmp_path,
):
    runner = _runner(monkeypatch, tmp_path)
    runner.session_store.load_transcript.return_value = []
    runner.async_session_store.has_any_sessions = AsyncMock(return_value=False)
    runner._deliver_platform_notice = AsyncMock()
    runner._run_agent = AsyncMock()

    manager = PluginManager()
    context = PluginContext(PluginManifest(name="dialogue-test"), manager)
    context.register_hook(
        "conversation_turn",
        lambda **_turn: {
            "action": "respond",
            "response": "I'm here.",
        },
    )
    monkeypatch.setattr(plugin_runtime, "_plugin_manager", manager)

    response = await runner._handle_message_with_agent(
        _event(), _source(), SESSION_KEY, 1
    )

    assert response == "I'm here."
    assert not (tmp_path / "config.yaml").exists()
    runner._run_agent.assert_not_awaited()
