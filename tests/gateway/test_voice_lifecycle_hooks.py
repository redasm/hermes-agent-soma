def test_voice_lifecycle_helpers_emit_typed_host_events(monkeypatch):
    from gateway import voice_lifecycle

    calls = []
    monkeypatch.setattr(voice_lifecycle, "_invoke_hook", lambda name, **kwargs: calls.append((name, kwargs)))

    voice_lifecycle.emit_voice_session_start("session-1", subject_id="user-1", origin="discord")
    voice_lifecycle.emit_voice_transcript(
        "session-1",
        subject_id="user-1",
        text="hello",
        final=True,
        origin="discord",
        turn_id="turn-1",
        action_id="action-1",
    )
    voice_lifecycle.emit_voice_barge_in(
        "session-1",
        subject_id="user-1",
        turn_id="turn-1",
        action_id="action-1",
        origin="discord",
        latency_ms=125.0,
    )
    voice_lifecycle.emit_voice_response_start(
        "session-1",
        subject_id="user-1",
        turn_id="turn-1",
        action_id="action-1",
        origin="discord",
        latency_ms=850.0,
    )
    voice_lifecycle.emit_voice_delivery(
        "session-1",
        subject_id="user-1",
        turn_id="turn-1",
        action_id="action-1",
        origin="discord",
        delivered=True,
    )
    voice_lifecycle.emit_voice_session_end("session-1", subject_id="user-1", origin="discord")

    assert [name for name, _ in calls] == [
        "voice_session_start",
        "voice_transcript",
        "voice_barge_in",
        "voice_response_start",
        "voice_delivery",
        "voice_session_end",
    ]
    assert calls[1][1]["session_id"] == "session-1"
    assert calls[1][1]["origin"] == "discord"
    assert calls[1][1]["final"] is True
    assert calls[1][1]["turn_id"] == "turn-1"
    assert calls[1][1]["action_id"] == "action-1"
    assert calls[2][1]["latency_ms"] == 125.0
    assert calls[2][1]["turn_id"] == "turn-1"
    assert calls[3][1]["latency_ms"] == 850.0
    assert calls[3][1]["turn_id"] == "turn-1"
    assert calls[3][1]["action_id"] == "action-1"
    assert calls[4][1]["turn_id"] == "turn-1"
    assert calls[4][1]["delivered"] is True


def test_voice_hooks_are_declared_as_generic_plugin_contracts():
    from hermes_cli.plugins import VALID_HOOKS

    assert {
        "voice_session_start",
        "voice_transcript",
        "voice_barge_in",
        "voice_response_start",
        "voice_delivery",
        "voice_session_end",
    } <= VALID_HOOKS


def test_voice_barge_in_rejects_invalid_latency_samples():
    import pytest

    from gateway.voice_lifecycle import emit_voice_barge_in

    for value in (-1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="latency"):
            emit_voice_barge_in(
                "session-1",
                subject_id="user-1",
                turn_id="turn-1",
                action_id="action-1",
                origin="discord",
                latency_ms=value,
            )


def test_voice_response_start_emits_validated_content_free_latency(monkeypatch):
    import pytest

    from gateway import voice_lifecycle

    calls = []
    monkeypatch.setattr(voice_lifecycle, "_invoke_hook", lambda name, **kwargs: calls.append((name, kwargs)))

    voice_lifecycle.emit_voice_response_start(
        "session-1",
        subject_id="user-1",
        turn_id="turn-1",
        action_id="action-1",
        origin="discord",
        latency_ms=850.0,
    )

    assert calls[0][0] == "voice_response_start"
    assert calls[0][1]["latency_ms"] == 850.0
    assert "text" not in calls[0][1]
    for value in (-1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="latency"):
            voice_lifecycle.emit_voice_response_start(
                "session-1",
                subject_id="user-1",
                turn_id="turn-1",
                action_id="action-1",
                origin="discord",
                latency_ms=value,
            )
