"""Topical helpers for the Soma host integration."""
from __future__ import annotations
from typing import Any, Optional, Callable
import logging
logger = logging.getLogger(__name__)

def _emit_voice_delivery(
    self,
    guild_id: int,
    identity: Optional[tuple[str, str, str]],
    *,
    delivered: bool,
) -> None:
    text_channel_id = self._voice_text_channels.get(guild_id)
    if identity is None or text_channel_id is None:
        return
    subject_id, turn_id, action_id = identity
    active_turn = getattr(self, "_voice_active_turn_ids", {}).get(guild_id)
    active_action = getattr(self, "_voice_active_action_ids", {}).get(guild_id)
    delivered = delivered and active_turn == turn_id and active_action == action_id
    if delivered:
        delivered_actions = getattr(self, "_voice_delivered_action_ids", None)
        if delivered_actions is None:
            delivered_actions = {}
            self._voice_delivered_action_ids = delivered_actions
        delivered_actions.setdefault(guild_id, set()).add(action_id)
    try:
        from gateway.voice_lifecycle import emit_voice_delivery

        emit_voice_delivery(
            f"discord:{guild_id}:{text_channel_id}",
            subject_id=subject_id,
            turn_id=turn_id,
            action_id=action_id,
            origin="discord_voice_channel",
            delivered=delivered,
        )
    except Exception:
        logger.debug("voice delivery hook failed", exc_info=True)


def _emit_pending_voice_response_start(self, guild_id: int) -> Optional[tuple[str, str, str]]:
    from plugins.platforms.discord.adapter import (
        time
    )
    pending = getattr(self, "_voice_response_pending", {}).pop(guild_id, None)
    text_channel_id = self._voice_text_channels.get(guild_id)
    if pending is None or text_channel_id is None:
        return None
    subject_id, final_at, turn_id, action_id = pending
    latency_ms = max(0.0, (time.monotonic() - final_at) * 1000)
    try:
        from gateway.voice_lifecycle import emit_voice_response_start

        emit_voice_response_start(
            f"discord:{guild_id}:{text_channel_id}",
            subject_id=subject_id,
            turn_id=turn_id,
            action_id=action_id,
            origin="discord_voice_channel",
            latency_ms=latency_ms,
        )
    except Exception:
        logger.debug("voice response start hook failed", exc_info=True)
    return subject_id, turn_id, action_id


def interrupt_voice_playback(self, guild_id: int) -> bool:
    """Stop current spoken output immediately for user barge-in."""
    interrupted = False
    mixer = getattr(self, "_voice_mixers", {}).get(guild_id)
    if mixer is not None and getattr(mixer, "speech_active", False):
        mixer.stop_speech()
        interrupted = True
    else:
        voice_client = getattr(self, "_voice_clients", {}).get(guild_id)
        if voice_client is not None and voice_client.is_playing():
            voice_client.stop()
            interrupted = True
    receiver = getattr(self, "_voice_receivers", {}).get(guild_id)
    if receiver is not None:
        receiver.resume()
    return interrupted


def notify_first_speech(self, ssrc):
    if ssrc not in self._speech_started_ssrc:
        self._speech_started_ssrc.add(ssrc)
        user_id = self._ssrc_to_user.get(ssrc, 0)
        if user_id and self._on_speech_start:
            try:
                self._on_speech_start(
                    user_id,
                    self._last_packet_time[ssrc],
                )
            except Exception:
                logger.debug("voice speech-start callback failed", exc_info=True)


async def play_in_voice_channel(self, guild_id: int, audio_path: str) -> bool:
    """Play audio in the VC: via the mixer (layered over the ambient bed, ducking it)
    when installed, else the legacy one-shot FFmpegPCMAudio path."""
    from plugins.platforms.discord.adapter import (
        _voice_mixer_module, asyncio, discord, logger, resolve_ffmpeg_executable, time
    )
    vc = self._voice_clients.get(guild_id)
    if not vc or not vc.is_connected():
        return False
    pending = getattr(self, "_voice_response_pending", {}).get(guild_id)
    if pending and len(pending) == 4 and pending[3] in getattr(self, "_voice_delivered_action_ids", {}).get(guild_id, set()):
        self._voice_response_pending.pop(guild_id, None)
        return True
    # Playback counts as activity: suspend the inactivity timer, re-arm in finally.
    self._cancel_voice_timeout(guild_id)
    try:
        playback_timeout = await self._playback_timeout_for_audio(audio_path)
        # ── Mixer path (overlap + ducking) ──────────────────────────────
        mixer = getattr(self, "_voice_mixers", {}).get(guild_id) if getattr(self, "_voice_mixers", None) else None
        if mixer is not None:
            decode_to_pcm = _voice_mixer_module().decode_to_pcm
            pcm = await asyncio.to_thread(decode_to_pcm, audio_path)
            if pcm:
                speech_gain = float(self._voice_fx_cfg.get("speech_gain", 1.0))
                mixer.play_speech(self._lead_silence_bytes() + pcm, gain=speech_gain)
                identity = self._emit_pending_voice_response_start(guild_id)
                playback_succeeded = True
                # Block until speech drains so callers serialise replies; ambient keeps playing.
                wait_start = time.monotonic()
                while mixer.speech_active:
                    if time.monotonic() - wait_start > playback_timeout:
                        logger.warning("Mixer speech playback timed out after %.1fs", playback_timeout)
                        playback_succeeded = False
                        mixer.stop_speech()
                        break
                    await asyncio.sleep(0.05)
                self._emit_voice_delivery(guild_id, identity, delivered=playback_succeeded)
                return True
            logger.warning("Mixer decode failed for %s; falling back to legacy playback", audio_path)
        # Legacy one-shot path: pause receiver while playing (echo prevention).
        receiver = self._voice_receivers.get(guild_id)
        if receiver:
            receiver.pause()
        try:
            wait_start = time.monotonic()
            while vc.is_playing():
                if time.monotonic() - wait_start > playback_timeout:
                    logger.warning("Timed out waiting for previous playback to finish")
                    vc.stop()
                    break
                await asyncio.sleep(0.1)
            done = asyncio.Event()
            loop = asyncio.get_running_loop()
            playback_succeeded = True

            def _after(error):
                nonlocal playback_succeeded
                if error:
                    playback_succeeded = False
                    logger.error("Voice playback error: %s", error)
                loop.call_soon_threadsafe(done.set)

            # Lead silence so socket warm-up doesn't clip the first word (mirrors mixer path).
            ffmpeg_opts: dict[str, Any] = {}
            _fx_cfg = getattr(self, "_voice_fx_cfg", None) or {}
            try:
                lead_ms = int(_fx_cfg.get("lead_silence_ms", 0) or 0)
            except (TypeError, ValueError):
                lead_ms = 0
            if lead_ms > 0:
                ffmpeg_opts["options"] = f"-af adelay={lead_ms}:all=1"
            source = discord.FFmpegPCMAudio(
                audio_path, executable=resolve_ffmpeg_executable(), **ffmpeg_opts,
            )
            source = discord.PCMVolumeTransformer(source, volume=1.0)
            vc.play(source, after=_after)
            identity = self._emit_pending_voice_response_start(guild_id)
            try:
                await asyncio.wait_for(done.wait(), timeout=playback_timeout)
            except TimeoutError:
                playback_succeeded = False
                logger.warning("Voice playback timed out after %.1fs", playback_timeout)
                vc.stop()
            self._emit_voice_delivery(guild_id, identity, delivered=playback_succeeded)
            return True
        finally:
            if receiver:
                receiver.resume()
    finally:
        self._reset_voice_timeout(guild_id)
