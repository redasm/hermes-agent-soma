"""Soma compatibility behaviour contracts."""
from unittest.mock import MagicMock, AsyncMock, patch
from cron.scheduler import _deliver_result



class TestDeliverResultWrappingCompat:
    def test_job_text_only_response_mode_overrides_global_wrapping(self):
        """A clean companion delivery can opt out without changing other jobs."""
        from gateway.config import Platform

        pconfig = MagicMock()
        pconfig.enabled = True
        mock_cfg = MagicMock()
        mock_cfg.platforms = {Platform.TELEGRAM: pconfig}

        with patch("gateway.config.load_gateway_config", return_value=mock_cfg), \
             patch("tools.send_message_tool._send_to_platform", new=AsyncMock(return_value={"success": True})) as send_mock, \
             patch("cron.scheduler.load_config", return_value={"cron": {"wrap_response": True}}):
            job = {
                "id": "companion-job",
                "name": "companion-checkin",
                "deliver": "origin",
                "origin": {"platform": "telegram", "chat_id": "123"},
                "response_mode": "text_only",
            }
            _deliver_result(job, "今天路过一家很香的面包店，突然想起你。")

        send_mock.assert_called_once()
        sent_content = send_mock.call_args.kwargs.get("content") or send_mock.call_args[0][-1]
        assert sent_content == "今天路过一家很香的面包店，突然想起你。"
    def test_job_framed_response_mode_overrides_global_clean_output(self):
        """An operational job can retain provenance when clean output is global."""
        from gateway.config import Platform

        pconfig = MagicMock()
        pconfig.enabled = True
        mock_cfg = MagicMock()
        mock_cfg.platforms = {Platform.TELEGRAM: pconfig}

        with patch("gateway.config.load_gateway_config", return_value=mock_cfg), \
             patch("tools.send_message_tool._send_to_platform", new=AsyncMock(return_value={"success": True})) as send_mock, \
             patch("cron.scheduler.load_config", return_value={"cron": {"wrap_response": False}}):
            job = {
                "id": "audit-job",
                "name": "audit-report",
                "deliver": "origin",
                "origin": {"platform": "telegram", "chat_id": "123"},
                "response_mode": "framed",
            }
            _deliver_result(job, "Audit complete.")

        sent_content = send_mock.call_args.kwargs.get("content") or send_mock.call_args[0][-1]
        assert "Cronjob Response: audit-report" in sent_content
        assert "(job_id: audit-job)" in sent_content
