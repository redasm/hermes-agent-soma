"""Soma compatibility behaviour contracts."""
import importlib, sys, types
from types import SimpleNamespace
import pytest
from gateway.config import Platform
from gateway.session import SessionSource
from tests.gateway.test_run_progress_topics import ProgressCaptureAdapter, _make_runner



@pytest.mark.asyncio
async def test_internal_execution_disables_every_user_visible_agent_surface(
    monkeypatch,
    tmp_path,
):
    import yaml

    (tmp_path / "config.yaml").write_text(
        yaml.dump(
            {
                "display": {
                    "tool_progress": "all",
                    "thinking_progress": True,
                    "interim_assistant_messages": True,
                    "live_status": "full",
                }
            }
        ),
        encoding="utf-8",
    )
    fake_dotenv = types.ModuleType("dotenv")
    fake_dotenv.load_dotenv = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "dotenv", fake_dotenv)
    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = PrivateExecutionAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)

    adapter = ProgressCaptureAdapter(platform=Platform.TELEGRAM)
    runner = _make_runner(adapter)
    runner.hooks = SimpleNamespace(loaded_hooks=True, emit=lambda *_a, **_kw: None)
    gateway_run = importlib.import_module("gateway.run")
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    monkeypatch.setattr(
        gateway_run,
        "_resolve_runtime_agent_kwargs",
        lambda: {"api_key": "fake"},
    )
    source = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="private-executor",
        chat_type="dm",
    )

    result = await runner._run_agent(
        message="private objective",
        context_prompt="",
        history=[],
        source=source,
        session_id="sess:capability:req",
        session_key="key:capability:req",
        internal_execution=True,
    )

    assert result["final_response"] == "private result"
    assert PrivateExecutionAgent.observed == {
        "message": "private objective",
        "history": [],
        "tool_progress": None,
        "tool_start": None,
        "step": None,
        "stream": None,
        "interim": None,
        "status": None,
        "execution_owner": "hermes",
        "execution_purpose": "tool_execution",
    }
    assert adapter.sent == []
    assert adapter.edits == []



class PrivateExecutionAgent:
    observed = None

    def __init__(self, **_kwargs):
        self.tools = []

    def run_conversation(self, message, conversation_history=None, task_id=None):
        type(self).observed = {
            "message": message,
            "history": conversation_history,
            "tool_progress": getattr(self, "tool_progress_callback", None),
            "tool_start": getattr(self, "tool_start_callback", None),
            "step": getattr(self, "step_callback", None),
            "stream": getattr(self, "stream_delta_callback", None),
            "interim": getattr(self, "interim_assistant_callback", None),
            "status": getattr(self, "status_callback", None),
            "execution_owner": getattr(self, "_execution_owner", None),
            "execution_purpose": getattr(self, "_execution_purpose", None),
        }
        return {
            "final_response": "private result",
            "messages": [{"role": "assistant", "content": "private result"}],
            "api_calls": 1,
        }
