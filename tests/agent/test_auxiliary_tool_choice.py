"""Soma compatibility behaviour contracts."""
from agent.auxiliary_client import _build_call_kwargs



class TestBuildCallKwargsToolDedupCompat:
    def test_required_tool_choice_is_projected_with_tools(self):
        tools = [
            make_tool("respond_to_user"),
            make_tool("request_host_task"),
        ]
        try:
            kwargs = _build_call_kwargs(
                provider="openai",
                model="gpt-4o",
                messages=[],
                tools=tools,
                tool_choice="required",
            )
        except TypeError as exc:
            kwargs = exc

        assert not isinstance(kwargs, TypeError), str(kwargs)
        assert kwargs["tool_choice"] == "required"


def make_tool(name):
    return {"type": "function", "function": {"name": name, "description": f"Tool {name}", "parameters": {"type": "object", "properties": {}}}}


def test_responses_adapter_preserves_required_and_named_tool_choices():
    from types import SimpleNamespace
    from agent.auxiliary_client import _CodexCompletionsAdapter
    adapter = _CodexCompletionsAdapter(SimpleNamespace(base_url="https://api.openai.com/v1"), "gpt-5")
    for choice, expected in [("required", "required"), ({"type": "function", "function": {"name": "respond_to_user"}}, {"type": "function", "name": "respond_to_user"})]:
        payload, _, _ = adapter._build_responses_kwargs({"tools": [make_tool("respond_to_user")], "messages": [{"role": "user", "content": "hello"}], "tool_choice": choice})
        assert payload["tool_choice"] == expected
