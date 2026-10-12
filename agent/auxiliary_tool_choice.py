"""Native function-choice projection for Responses requests."""
from __future__ import annotations
from typing import Any


def responses_tool_choice(choice: Any, renamed: dict[str, str]) -> Any:
    if isinstance(choice, str):
        return choice if choice in {"auto", "required", "none"} else None
    if not isinstance(choice, dict) or choice.get("type") != "function":
        return None
    function = choice.get("function")
    name = function.get("name") if isinstance(function, dict) else choice.get("name")
    return {"type": "function", "name": renamed.get(name, name)} if name else None


def apply_responses_tool_choice(payload: dict, choice: Any, renamed: dict[str, str]) -> None:
    projected = responses_tool_choice(choice, renamed)
    if projected is not None:
        payload["tool_choice"] = projected
