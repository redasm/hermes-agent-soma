"""Each flushed/discarded utterance permits a new speech-start signal."""
from types import SimpleNamespace
import pytest
from plugins.platforms.discord.adapter import VoiceReceiver
from plugins.platforms.discord.adapter_voice_lifecycle import notify_first_speech


@pytest.mark.parametrize("reset", ["flush_pending", "discard_pending", "stop"])
def test_voice_receiver_starts_a_new_utterance_after_reset(reset):
    observed = []
    receiver = VoiceReceiver(SimpleNamespace(_connection=SimpleNamespace(remove_socket_listener=lambda _: None)), on_speech_start=lambda *args: observed.append(args))
    receiver._ssrc_to_user[42] = 7
    receiver._last_packet_time[42] = 1.0
    receiver._buffers[42].extend(b"pcm")
    notify_first_speech(receiver, 42)
    getattr(receiver, reset)()
    receiver._ssrc_to_user[42] = 7
    receiver._last_packet_time[42] = 2.0
    notify_first_speech(receiver, 42)
    assert observed == [(7, 1.0), (7, 2.0)]
