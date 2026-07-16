"""Contracts for bounded, target-aware cron context supplied by plugins."""

from __future__ import annotations

import json

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


def _job(**overrides):
    job = {
        "id": "abcdef123456",
        "name": "companion-checkin",
        "prompt": "Decide whether to share something naturally.",
        "context_provider": "soma",
        "origin": {
            "platform": "telegram",
            "chat_id": "chat-42",
            "thread_id": "topic-7",
            "user_id": "user-9",
            "session_id": "session-3",
        },
    }
    job.update(overrides)
    return job


def test_build_prompt_injects_matching_provider_context_ephemerally(monkeypatch):
    from cron.scheduler import _build_job_prompt

    calls = []

    def invoke_hook(name, **kwargs):
        calls.append((name, kwargs))
        return [{"provider": "soma", "context": "用户长期偏好使用中文。"}]

    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", invoke_hook)

    prompt = _build_job_prompt(_job())

    assert "## Scoped Context" in prompt
    assert "用户长期偏好使用中文。" in prompt
    assert "Decide whether to share something naturally." in prompt
    assert calls[0][0] == "cron_context"
    assert calls[0][1]["provider"] == "soma"
    assert calls[0][1]["target"] == {
        "profile": "default",
        "platform": "telegram",
        "chat_id": "chat-42",
        "thread_id": "topic-7",
        "user_id": "user-9",
        "session_id": "session-3",
    }


def test_build_prompt_ignores_context_from_other_provider(monkeypatch):
    from cron.scheduler import _build_job_prompt

    monkeypatch.setattr(
        "hermes_cli.plugins.invoke_hook",
        lambda *args, **kwargs: [
            {"provider": "other", "context": "must not leak"},
        ],
    )

    prompt = _build_job_prompt(_job())

    assert "must not leak" not in prompt
    assert "## Scoped Context" not in prompt


def test_build_prompt_does_not_call_hook_without_provider(monkeypatch):
    from cron.scheduler import _build_job_prompt

    def unexpected(*args, **kwargs):
        raise AssertionError("cron_context hook should be opt-in")

    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", unexpected)

    prompt = _build_job_prompt(_job(context_provider=None))

    assert "Decide whether to share something naturally." in prompt


def test_provider_context_is_bounded(monkeypatch):
    from cron.scheduler import _build_job_prompt

    monkeypatch.setattr(
        "hermes_cli.plugins.invoke_hook",
        lambda *args, **kwargs: [
            {"provider": "soma", "context": "x" * 9000},
        ],
    )

    prompt = _build_job_prompt(_job())

    assert "x" * 8000 in prompt
    assert "x" * 8001 not in prompt
    assert "[... context truncated ...]" in prompt


def test_provider_runtime_metadata_reaches_receipt_but_not_prompt(monkeypatch):
    from cron.scheduler import _build_job_prompt, _make_delivery_receipt

    job = _job(metadata={"outcome_id": "outcome-7"})
    monkeypatch.setattr(
        "hermes_cli.plugins.invoke_hook",
        lambda *args, **kwargs: [
            {
                "provider": "soma",
                "context": "请使用用户偏好的语言自然表达。",
                "metadata": {"attempt_id": "attempt-42"},
            },
        ],
    )

    prompt = _build_job_prompt(job)
    receipt = _make_delivery_receipt(job, "delivered")

    assert "attempt-42" not in prompt
    assert receipt.metadata == {
        "outcome_id": "outcome-7",
        "attempt_id": "attempt-42",
    }
    assert "_cron_runtime_metadata" not in receipt.as_dict()


def test_provider_runtime_metadata_does_not_leak_into_reused_job(monkeypatch):
    from cron.scheduler import _build_job_prompt, _make_delivery_receipt

    job = _job()
    results = [
        [{"provider": "soma", "metadata": {"attempt_id": "attempt-1"}}],
        [{"provider": "soma", "context": "No new attempt metadata."}],
    ]
    monkeypatch.setattr(
        "hermes_cli.plugins.invoke_hook",
        lambda *args, **kwargs: results.pop(0),
    )

    _build_job_prompt(job)
    assert _make_delivery_receipt(job, "delivered").metadata == {
        "attempt_id": "attempt-1"
    }

    _build_job_prompt(job)
    assert _make_delivery_receipt(job, "delivered").metadata == {}


def test_create_and_tool_persist_context_provider(cron_env):
    from cron.jobs import create_job, get_job
    from tools.cronjob_tools import cronjob

    direct = create_job(
        prompt="Companion tick",
        schedule="every 1h",
        context_provider="soma",
    )
    assert get_job(direct["id"])["context_provider"] == "soma"

    created = json.loads(
        cronjob(
            action="create",
            prompt="Companion tick",
            schedule="every 2h",
            deliver="local",
            context_provider="soma",
        )
    )
    assert created["success"] is True
    assert created["job"]["context_provider"] == "soma"
    assert get_job(created["job_id"])["context_provider"] == "soma"


@pytest.mark.parametrize("provider", ["", "has spaces", "../escape", "x" * 65])
def test_create_rejects_invalid_context_provider(cron_env, provider):
    from cron.jobs import create_job

    with pytest.raises(ValueError, match="context_provider"):
        create_job(
            prompt="Companion tick",
            schedule="every 1h",
            context_provider=provider,
        )


def test_tool_schema_exposes_context_provider():
    from hermes_cli.plugins import VALID_HOOKS
    from tools.cronjob_tools import CRONJOB_SCHEMA

    field = CRONJOB_SCHEMA["parameters"]["properties"]["context_provider"]
    assert field["type"] == "string"
    assert "cron_context" in VALID_HOOKS
