from unittest.mock import MagicMock


def test_discord_voice_interrupt_stops_mixer_speech_and_resumes_receiver():
    from plugins.platforms.discord.adapter import DiscordAdapter

    adapter = DiscordAdapter.__new__(DiscordAdapter)
    mixer = MagicMock()
    mixer.speech_active = True
    voice_client = MagicMock()
    voice_client.is_playing.return_value = True
    receiver = MagicMock()
    adapter._voice_mixers = {7: mixer}
    adapter._voice_clients = {7: voice_client}
    adapter._voice_receivers = {7: receiver}

    assert adapter.interrupt_voice_playback(7) is True
    mixer.stop_speech.assert_called_once()
    voice_client.stop.assert_not_called()
    receiver.resume.assert_called_once()


def test_discord_voice_interrupt_stops_legacy_playback():
    from plugins.platforms.discord.adapter import DiscordAdapter

    adapter = DiscordAdapter.__new__(DiscordAdapter)
    voice_client = MagicMock()
    voice_client.is_playing.return_value = True
    adapter._voice_mixers = {}
    adapter._voice_clients = {7: voice_client}
    adapter._voice_receivers = {}
    assert adapter.interrupt_voice_playback(7) is True
    voice_client.stop.assert_called_once()
