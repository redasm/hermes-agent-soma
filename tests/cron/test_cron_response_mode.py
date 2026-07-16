"""Behavior contracts for per-job cron response formatting."""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def cron_env(tmp_path, monkeypatch):
    """Isolate cron persistence from the user's Hermes home."""
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


def test_create_persists_explicit_response_mode(cron_env):
    from cron.jobs import create_job, get_job

    job = create_job(
        prompt="Share something naturally.",
        schedule="every 1h",
        response_mode="text_only",
    )

    assert job["response_mode"] == "text_only"
    assert get_job(job["id"])["response_mode"] == "text_only"


def test_create_omits_response_mode_when_unspecified(cron_env):
    from cron.jobs import create_job

    job = create_job(prompt="Operational report", schedule="every 1h")

    assert "response_mode" not in job


@pytest.mark.parametrize("response_mode", ["plain", "raw", "", 7])
def test_create_rejects_invalid_response_mode(cron_env, response_mode):
    from cron.jobs import create_job

    with pytest.raises(ValueError, match="response_mode"):
        create_job(
            prompt="Invalid mode",
            schedule="every 1h",
            response_mode=response_mode,
        )


def test_tool_create_and_update_response_mode(cron_env):
    from cron.jobs import get_job
    from tools.cronjob_tools import cronjob

    created = json.loads(
        cronjob(
            action="create",
            prompt="Companion check-in",
            schedule="every 1h",
            deliver="local",
            response_mode="text_only",
        )
    )
    assert created["success"] is True
    job_id = created["job_id"]
    assert get_job(job_id)["response_mode"] == "text_only"
    assert created["job"]["response_mode"] == "text_only"

    updated = json.loads(
        cronjob(action="update", job_id=job_id, response_mode="framed")
    )
    assert updated["success"] is True
    assert updated["job"]["response_mode"] == "framed"
    assert get_job(job_id)["response_mode"] == "framed"


def test_tool_schema_exposes_only_supported_response_modes():
    from tools.cronjob_tools import CRONJOB_SCHEMA

    field = CRONJOB_SCHEMA["parameters"]["properties"]["response_mode"]
    assert field["type"] == "string"
    assert field["enum"] == ["framed", "text_only"]
