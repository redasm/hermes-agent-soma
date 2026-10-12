"""Soma compatibility behaviour contracts."""
import asyncio, os, unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch



class TestAdapterModuleCompat(unittest.TestCase):
    def test_official_ws_runner_consumes_normal_close_task_exception(self):
        from websockets.exceptions import ConnectionClosedOK
        from websockets.frames import Close

        from plugins.platforms.feishu.adapter import _run_official_feishu_ws_client

        class _FakeWSClient:
            def start(self):
                loop = asyncio.get_event_loop()

                async def close_normally():
                    import logging

                    logging.getLogger("Lark").error(
                        "receive message loop exit, err: sent 1000 (OK); "
                        "then received 1000 (OK) bye"
                    )
                    raise ConnectionClosedOK(Close(1000, "bye"), Close(1000, ""), False)

                loop.create_task(close_normally())
                loop.run_until_complete(asyncio.sleep(0))

        adapter = SimpleNamespace(
            _running=False,
            _ws_thread_loop=None,
            _loop=None,
            _ws_reconnect_nonce=30,
            _ws_reconnect_interval=120,
            _ws_ping_interval=None,
            _ws_ping_timeout=None,
        )
        with self.assertNoLogs(level="ERROR"):
            _run_official_feishu_ws_client(_FakeWSClient(), adapter)


class TestAdapterBehaviorCompat(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_dm_reply_can_share_chat_session_without_losing_quote_metadata(self):
        from gateway.config import PlatformConfig
        from gateway.session import build_session_key
        from plugins.platforms.feishu.adapter import FeishuAdapter

        config = PlatformConfig(extra={"dm_top_level_threads_as_sessions": False})
        adapter = FeishuAdapter(config)
        adapter._dispatch_inbound_event = AsyncMock()
        adapter.get_chat_info = AsyncMock(
            return_value={"chat_id": "oc_chat", "name": "Feishu DM", "type": "dm"}
        )
        adapter._resolve_sender_profile = AsyncMock(
            return_value={"user_id": "ou_user", "user_name": "张三", "user_id_alt": None}
        )
        adapter._fetch_message_text = AsyncMock(return_value="被引用的回答")
        message = SimpleNamespace(
            chat_id="oc_chat",
            thread_id="omt_thread",
            root_id="om_root",
            parent_id="om_parent",
            upper_message_id=None,
            message_type="text",
            content='{"text":"纠正一下"}',
            message_id="om_reply",
        )

        asyncio.run(
            adapter._process_inbound_message(
                data=SimpleNamespace(event=SimpleNamespace(message=message)),
                message=message,
                sender_id=SimpleNamespace(open_id="ou_user", user_id=None, union_id=None),
                is_bot=False,
                chat_type="p2p",
                message_id="om_reply",
            )
        )

        event = adapter._dispatch_inbound_event.await_args.args[0]
        self.assertIsNone(event.source.thread_id)
        self.assertEqual(event.reply_to_message_id, "om_parent")
        self.assertEqual(event.reply_to_text, "被引用的回答")
        top_level = adapter.build_source(
            chat_id="oc_chat",
            chat_name="Feishu DM",
            chat_type="dm",
            user_id="ou_user",
            user_name="张三",
            thread_id=None,
        )
        self.assertEqual(build_session_key(event.source), build_session_key(top_level))
