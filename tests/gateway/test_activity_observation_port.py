import asyncio
import threading

import pytest
import psutil


class _Process:
    def __init__(self, name):
        self.info = {"name": name}


@pytest.mark.asyncio
async def test_local_application_port_emits_only_configured_process_lifecycle():
    from gateway.activity_observation import LocalApplicationObservationPort

    snapshots = iter(
        [
            [_Process("other.exe")],
            [_Process("game.exe"), _Process("private-chat.exe")],
            [_Process("other.exe")],
        ]
    )
    last = []

    def process_iter(_attrs):
        nonlocal last
        try:
            last = next(snapshots)
        except StopIteration:
            pass
        return last

    port = LocalApplicationObservationPort(
        process_name="game.exe",
        label="Configured Game",
        poll_interval=0.01,
        process_iter=process_iter,
    )
    await port.start(
        "opaque-mode",
        {
            "confirmed": True,
            "subject_id": "user:1",
            "session_id": "presence:1",
        },
    )
    events = port.events()
    started = await asyncio.wait_for(anext(events), timeout=1)
    stopped = await asyncio.wait_for(anext(events), timeout=1)
    await port.stop()

    assert started["state"] == "started"
    assert stopped["state"] == "stopped"
    assert started["application"] == "Configured Game"
    assert started["subject_id"] == "user:1"
    assert started["session_id"] == "presence:1"
    assert "pid" not in started
    assert "private-chat.exe" not in str(started)


@pytest.mark.asyncio
async def test_local_application_port_requires_configuration_and_explicit_confirmation():
    from gateway.activity_observation import LocalApplicationObservationPort

    missing = LocalApplicationObservationPort(process_name="")
    assert not missing.available
    with pytest.raises(RuntimeError, match="configured"):
        await missing.start("opaque", {"confirmed": True})

    port = LocalApplicationObservationPort(process_name="game.exe")
    with pytest.raises(PermissionError, match="confirmed"):
        await port.start(
            "opaque",
            {"confirmed": False, "subject_id": "u", "session_id": "s"},
        )


@pytest.mark.asyncio
async def test_local_application_port_does_not_use_process_name_as_default_label():
    from gateway.activity_observation import LocalApplicationObservationPort

    port = LocalApplicationObservationPort(
        process_name="private-game.exe",
        poll_interval=0.01,
        process_iter=lambda _attrs: [_Process("private-game.exe")],
    )
    await port.start(
        "opaque",
        {"confirmed": True, "subject_id": "user", "session_id": "session"},
    )
    event = await asyncio.wait_for(anext(port.events()), timeout=1)
    await port.stop()

    assert event["application"] == "Configured application"
    assert "private-game.exe" not in str(event)


@pytest.mark.asyncio
async def test_local_application_port_real_process_smoke():
    from gateway.activity_observation import LocalApplicationObservationPort

    port = LocalApplicationObservationPort(
        process_name=psutil.Process().name(),
        label="Configured smoke process",
        poll_interval=0.02,
    )
    await port.start(
        "opaque",
        {"confirmed": True, "subject_id": "smoke", "session_id": "smoke-session"},
    )
    event = await asyncio.wait_for(anext(port.events()), timeout=2)
    await port.stop()

    assert event["state"] == "started"
    assert event["application"] == "Configured smoke process"
    assert set(event) == {
        "subject_id",
        "session_id",
        "origin",
        "occurred_at",
        "state",
        "application",
    }


@pytest.mark.asyncio
async def test_stopped_generation_cannot_emit_into_restarted_session():
    from gateway.activity_observation import LocalApplicationObservationPort

    first_scan_started = threading.Event()
    release_first_scan = threading.Event()
    scan_count = 0

    def process_iter(_attrs):
        nonlocal scan_count
        scan_count += 1
        if scan_count == 1:
            first_scan_started.set()
            release_first_scan.wait(timeout=3)
            return [_Process("game.exe")]
        return []

    port = LocalApplicationObservationPort(
        process_name="game.exe",
        label="Configured Game",
        poll_interval=0.01,
        process_iter=process_iter,
    )
    await port.start(
        "opaque",
        {"confirmed": True, "subject_id": "old-user", "session_id": "old-session"},
    )
    assert await asyncio.to_thread(first_scan_started.wait, 1)

    await port.stop()
    await port.start(
        "opaque",
        {"confirmed": True, "subject_id": "new-user", "session_id": "new-session"},
    )
    events = port.events()
    release_first_scan.set()

    try:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(anext(events), timeout=0.1)
    finally:
        release_first_scan.set()
        await port.stop()
