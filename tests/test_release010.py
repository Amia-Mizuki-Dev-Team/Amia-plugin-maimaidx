from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from libraries.maimaidx_error import (  # noqa: E402
    TokenNotFoundError,
    UserNotBindLXNSError,
    UserNotFoundError,
)
from release010_import import (  # noqa: E402
    _classify_fallback,
    send_error_with_diagnostic,
    format_user_error,
)


class NetworkError(Exception):
    """Small adapter-shaped exception used to reproduce the reported log."""


class _DeadWebSocketMatcher:
    async def send(self, *_args, **_kwargs):
        raise NetworkError("WebSocket call api send_msg timeout")

    async def finish(self, *_args, **_kwargs):
        raise NetworkError("WebSocket call api send_msg timeout")


class Release010MaimaiErrorTests(unittest.TestCase):
    def test_errors_have_stable_codes_and_no_raw_exception_text(self):
        self.assertIn("HX-MAI-001", format_user_error(UserNotBindLXNSError(), "MAI"))
        self.assertIn("HX-MAI-002", format_user_error(TokenNotFoundError(), "MAI"))
        self.assertIn("HX-MAI-005", format_user_error(UserNotFoundError(), "MAI"))
        self.assertNotIn("<class", format_user_error(UserNotFoundError(), "MAI"))

    def test_source_aware_player_miss_explains_how_to_switch(self):
        lxns_message = format_user_error(
            UserNotFoundError(source="lxns"), "MAI", include_code=False
        )
        self.assertIn("落雪（LXNS）", lxns_message)
        self.assertIn("切换数据源 水鱼", lxns_message)
        self.assertNotIn("HX-MAI", lxns_message)

        fish_message = format_user_error(
            UserNotFoundError(source="diving-fish"), "MAI", include_code=False
        )
        self.assertIn("水鱼（Diving-Fish）", fish_message)
        self.assertIn("切换数据源 落雪", fish_message)

    def test_onebot_send_timeout_is_transport_error(self):
        failure = _classify_fallback(
            NetworkError("WebSocket call api send_msg timeout"), "MAI"
        )
        self.assertEqual(failure.code, "HX-MAI-008")
        self.assertIn("消息通道", failure.reason)

    def test_dead_websocket_does_not_trigger_a_second_error(self):
        async def run_case():
            with tempfile.TemporaryDirectory() as directory:
                path = await send_error_with_diagnostic(
                    _DeadWebSocketMatcher(),
                    NetworkError("WebSocket call api send_msg timeout"),
                    "MAI",
                    context="b50",
                    directory=directory,
                )
                return path.name, path.is_file(), path.read_text(encoding="utf-8")

        path_name, path_exists, content = asyncio.run(run_case())
        self.assertTrue(path_exists)
        self.assertTrue(path_name.startswith("hx-mai-008-"))
        self.assertIn("error_code=HX-MAI-008", content)

    def test_expected_user_error_does_not_create_diagnostic_or_escape_send_timeout(self):
        async def run_case():
            with tempfile.TemporaryDirectory() as directory:
                path = await send_error_with_diagnostic(
                    _DeadWebSocketMatcher(),
                    UserNotFoundError(),
                    "MAI",
                    context="b50",
                    directory=directory,
                )
                return path, list(Path(directory).iterdir())

        path, files = asyncio.run(run_case())
        self.assertEqual(path, Path())
        self.assertEqual(files, [])


if __name__ == "__main__":
    unittest.main()
