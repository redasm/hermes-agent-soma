"""Internal cron metadata and structured delivery-receipt contracts."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def cron_env(tmp_path, monkeypatch):
    hermes_home = tmp_path / ".hermes"
    cron_dir = hermes_home / "cron"
    cron_dir.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    import cron.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "HERMES_DIR", hermes_home)
    monkeypatch.setattr(jobs_mod, "CRON_DIR", cron_dir)
    monkeypatch.setattr(jobs_mod, "JOBS_FILE", cron_dir / "jobs.json")
    monkeypatch.setattr(jobs_mod, "OUTPUT_DIR", cron_dir / "output")
    return hermes_home


def test_internal_metadata_persists_but_never_enters_prompt_or_tool_view(cron_env):
    from cron.jobs import create_job, get_job
    from cron.scheduler import _build_job_prompt
    from tools.cronjob_tools import _format_job

    marker = "attempt-secret-123"
    metadata = {"attempt_id": marker, "outcome_id": "outcome-7"}
    job = create_job(
        prompt="Write a natural check-in.",
        schedule="every 1h",
        metadata=metadata,
    )
    metadata["attempt_id"] = "mutated-after-create"

    stored = get_job(job["id"])
    assert stored["metadata"]["attempt_id"] == marker
    assert marker not in _build_job_prompt(stored)
    assert "metadata" not in _format_job(stored)
    assert marker not in json.dumps(_format_job(stored))


@pytest.mark.parametrize("metadata", [[], "opaque", {1: "bad-key"}, {"x": object()}])
def test_create_rejects_invalid_internal_metadata(cron_env, metadata):
    from cron.jobs import create_job

    with pytest.raises(ValueError, match="metadata"):
        create_job(
            prompt="Companion tick",
            schedule="every 1h",
            metadata=metadata,
        )


def test_create_rejects_oversized_internal_metadata(cron_env):
    from cron.jobs import create_job

    with pytest.raises(ValueError, match="8192"):
        create_job(
            prompt="Companion tick",
            schedule="every 1h",
            metadata={"value": "x" * 9000},
        )


def test_tool_accepts_metadata_without_echoing_it(cron_env):
    from cron.jobs import get_job
    from tools.cronjob_tools import cronjob

    result = json.loads(
        cronjob(
            action="create",
            prompt="Companion tick",
            schedule="every 1h",
            deliver="local",
            metadata={"attempt_id": "attempt-42"},
        )
    )

    assert result["success"] is True
    assert "metadata" not in result["job"]
    assert "attempt-42" not in json.dumps(result)
    assert get_job(result["job_id"])["metadata"] == {"attempt_id": "attempt-42"}


def test_text_only_delivery_returns_structured_receipt_without_metadata_leak():
    from cron.scheduler import _deliver_result, _deliver_result_with_receipt
    from gateway.config import Platform

    pconfig = MagicMock()
    pconfig.enabled = True
    mock_cfg = MagicMock()
    mock_cfg.platforms = {Platform.TELEGRAM: pconfig}
    job = {
        "id": "companion-job",
        "name": "companion-checkin",
        "deliver": "origin",
        "origin": {"platform": "telegram", "chat_id": "123", "user_id": "u1"},
        "response_mode": "text_only",
        "metadata": {"attempt_id": "attempt-42", "outcome_id": "outcome-7"},
    }

    with (
        patch("gateway.config.load_gateway_config", return_value=mock_cfg),
        patch(
            "tools.send_message_tool._send_to_platform",
            new=AsyncMock(return_value={"success": True}),
        ) as send_mock,
    ):
        receipt = _deliver_result_with_receipt(job, "今天看到一只很神气的橘猫。")

    sent = send_mock.call_args.args[3]
    assert sent == "今天看到一只很神气的橘猫。"
    assert "attempt-42" not in sent
    assert receipt.status == "delivered"
    assert receipt.error is None
    assert receipt.metadata == {"attempt_id": "attempt-42", "outcome_id": "outcome-7"}
    assert receipt.targets == (
        {"platform": "telegram", "chat_id": "123", "thread_id": None},
    )

    with (
        patch("gateway.config.load_gateway_config", return_value=mock_cfg),
        patch(
            "tools.send_message_tool._send_to_platform",
            new=AsyncMock(return_value={"success": True}),
        ),
    ):
        assert _deliver_result(job, "legacy caller") is None


def test_delivery_receipt_hook_receives_structured_data(monkeypatch):
    from cron.scheduler import CronDeliveryReceipt, _notify_cron_delivery

    observed = []
    monkeypatch.setattr(
        "hermes_cli.plugins.invoke_hook",
        lambda name, **kwargs: observed.append((name, kwargs)) or [],
    )
    receipt = CronDeliveryReceipt(
        job_id="job-1",
        status="delivered",
        targets=({"platform": "telegram", "chat_id": "123", "thread_id": None},),
        metadata={"attempt_id": "attempt-42"},
    )

    _notify_cron_delivery(receipt)

    assert observed == [
        ("cron_delivery", {"receipt": receipt.as_dict()}),
    ]


def test_legacy_delivery_entrypoint_emits_receipt(monkeypatch):
    import cron.scheduler as scheduler

    receipt = scheduler.CronDeliveryReceipt(job_id="job-1", status="skipped")
    observed = []
    monkeypatch.setattr(
        scheduler,
        "_deliver_result_with_receipt",
        lambda *args, **kwargs: receipt,
    )
    monkeypatch.setattr(
        scheduler,
        "_notify_cron_delivery",
        lambda value: observed.append(value),
    )

    result = scheduler._deliver_result({"id": "job-1"}, "hello")

    assert result is None
    assert observed == [receipt]


def test_schema_exposes_metadata_as_non_prompt_correlation_data():
    from hermes_cli.plugins import VALID_HOOKS
    from tools.cronjob_tools import CRONJOB_SCHEMA

    field = CRONJOB_SCHEMA["parameters"]["properties"]["metadata"]
    assert field["type"] == "object"
    assert "cron_delivery" in VALID_HOOKS


def test_public_web_job_views_hide_internal_metadata():
    from gateway.platforms.api_server import _public_cron_job
    from hermes_cli.web_server import _annotate_cron_job

    job = {
        "id": "job-1",
        "name": "companion",
        "metadata": {"attempt_id": "attempt-42"},
        "origin": {
            "platform": "telegram",
            "chat_id": "123",
            "session_id": "session-secret-3",
        },
    }

    dashboard = _annotate_cron_job(job, "default", __import__("pathlib").Path("/tmp"))
    gateway_api = _public_cron_job(job)

    assert "metadata" not in dashboard
    assert "metadata" not in gateway_api
    assert "session_id" not in dashboard["origin"]
    assert "session_id" not in gateway_api["origin"]
    assert "attempt-42" not in json.dumps([dashboard, gateway_api])
    assert "session-secret-3" not in json.dumps([dashboard, gateway_api])


def test_registry_handler_forwards_companion_cron_fields(monkeypatch):
    import tools.cronjob_tools as cron_tools
    from tools.registry import registry

    captured = {}

    def fake_cronjob(**kwargs):
        captured.update(kwargs)
        return json.dumps({"success": True})

    monkeypatch.setattr(cron_tools, "cronjob", fake_cronjob)

    result = registry.dispatch(
        "cronjob",
        {
            "action": "create",
            "schedule": "every 1h",
            "prompt": "Companion tick",
            "attach_to_session": True,
            "response_mode": "text_only",
            "context_provider": "soma",
            "metadata": {"attempt_id": "attempt-42"},
        },
    )

    assert json.loads(result)["success"] is True
    assert captured["attach_to_session"] is True
    assert captured["response_mode"] == "text_only"
    assert captured["context_provider"] == "soma"
    assert captured["metadata"] == {"attempt_id": "attempt-42"}


def test_silent_cron_run_emits_skipped_receipt_without_delivery(monkeypatch):
    import cron.scheduler as scheduler

    receipts = []
    monkeypatch.setattr(
        scheduler,
        "run_job",
        lambda job, defer_agent_teardown=None: (True, "output", "[SILENT]", None),
    )
    monkeypatch.setattr(scheduler, "save_job_output", lambda *args: "/tmp/out")
    monkeypatch.setattr(
        scheduler,
        "_deliver_result",
        lambda *args, **kwargs: pytest.fail("silent run must not deliver"),
    )
    monkeypatch.setattr(
        scheduler,
        "_notify_cron_delivery",
        lambda receipt: receipts.append(receipt),
    )
    monkeypatch.setattr(scheduler, "mark_job_run", lambda *args, **kwargs: None)
    job = {
        "id": "companion-job",
        "name": "companion-checkin",
        "metadata": {"attempt_id": "attempt-42"},
    }

    assert scheduler.run_one_job(job) is True
    assert len(receipts) == 1
    assert receipts[0].status == "skipped"
    assert receipts[0].metadata == {"attempt_id": "attempt-42"}


def test_dashboard_create_forwards_companion_host_contract(tmp_path, monkeypatch):
    import hermes_cli.web_server as web_server

    captured = {}
    monkeypatch.setattr(
        web_server,
        "_cron_profile_home",
        lambda profile: ("default", tmp_path),
    )

    def fake_call(profile, function, **kwargs):
        captured.update(kwargs)
        return {"id": "job-1", **kwargs}

    monkeypatch.setattr(web_server, "_call_cron_for_profile", fake_call)
    body = web_server.CronJobCreate(
        prompt="Companion tick",
        schedule="every 1h",
        deliver="local",
        attach_to_session=True,
        response_mode="text_only",
        context_provider="soma",
        metadata={"attempt_id": "attempt-42"},
    )

    web_server._create_cron_job_sync(body)

    assert captured["attach_to_session"] is True
    assert captured["response_mode"] == "text_only"
    assert captured["context_provider"] == "soma"
    assert captured["metadata"] == {"attempt_id": "attempt-42"}


def test_run_exception_emits_failed_receipt(monkeypatch):
    import cron.scheduler as scheduler

    receipts = []

    def fail_run(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(scheduler, "run_job", fail_run)
    monkeypatch.setattr(scheduler, "mark_job_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        scheduler,
        "_notify_cron_delivery",
        lambda receipt: receipts.append(receipt),
    )

    result = scheduler.run_one_job(
        {
            "id": "companion-job",
            "metadata": {"attempt_id": "attempt-42"},
        }
    )

    assert result is False
    assert len(receipts) == 1
    assert receipts[0].status == "failed"
    assert receipts[0].metadata == {"attempt_id": "attempt-42"}
    assert receipts[0].error == "provider unavailable"
