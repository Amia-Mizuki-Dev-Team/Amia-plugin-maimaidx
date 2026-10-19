"""双源 B50 容错回归测试（无 nonebot 环境可运行）。

锁定的不变量：
- 双源全失败时，用户可见错误同时包含落雪与水鱼两侧的原因摘要；
- 落雪已绑定但未同步成绩时抛 ``ScoreNotSyncedError``，而不是“没有找到玩家”；
- 单源解析失败或单条脏成绩记录不会中断另一源 / 整条 B50；
- ``merge_b50`` 自身抛异常时回退单源结果，不中断整条流程。
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

_PKG = "maidx_b50_sources_under_test"


def _load_modules():
    """用别名包加载插件库，绕开 ``..config`` 的相对导入与 nonebot 初始化。"""
    for name in list(sys.modules):
        if name == _PKG or name.startswith(_PKG + "."):
            sys.modules.pop(name, None)
    pkg = ModuleType(_PKG)
    pkg.__path__ = [str(PLUGIN_ROOT)]
    sys.modules[_PKG] = pkg
    libraries = ModuleType(f"{_PKG}.libraries")
    libraries.__path__ = [str(PLUGIN_ROOT / "libraries")]
    sys.modules[f"{_PKG}.libraries"] = libraries
    config = ModuleType(f"{_PKG}.config")
    config.maiconfig = SimpleNamespace(lxnstoken="test-token")
    sys.modules[f"{_PKG}.config"] = config
    return (
        importlib.import_module(f"{_PKG}.libraries.maimaidx_api_data"),
        importlib.import_module(f"{_PKG}.libraries.maimaidx_error"),
        importlib.import_module(f"{_PKG}.libraries.maimaidx_merge"),
        importlib.import_module(f"{_PKG}.libraries.maimaidx_model"),
    )


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, *, bad_json: bool = False):
        self.status_code = status_code
        self._payload = payload
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("invalid JSON")
        return self._payload


class _FakeLxnsClient:
    """GET-only LXNS client; profile and bests payloads are class attributes."""

    profile_status = 200
    profile_payload = {"data": {"friend_code": "FRIEND-1", "name": "落雪玩家"}}
    bests_status = 200
    bests_payload = {"data": {"standard": [], "dx": [], "total": 0}}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, headers=None):
        if "/bests" not in url:
            return _FakeResponse(self.profile_status, self.profile_payload)
        return _FakeResponse(self.bests_status, self.bests_payload)


class _SplitClient:
    """GET → LXNS (all-dirty records), POST → Fish (healthy records)."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, headers=None):
        if "/player/qq/" in url:
            return _FakeResponse(200, {"data": {"friend_code": "FRIEND-1", "name": "落雪玩家"}})
        return _FakeResponse(
            200,
            {"data": {"standard": [{"song_id": "not-a-number"}], "dx": [None]}},
        )

    async def post(self, url, json=None):
        return _FakeResponse(
            200,
            {
                "nickname": "水鱼玩家",
                "rating": 100,
                "additional_rating": 0,
                "plate": "",
                "username": "fish_user",
                "charts": {
                    "sd": [
                        {
                            "song_id": 799,
                            "level_index": 3,
                            "achievements": 100.0,
                            "ra": 500,
                            "type": "standard",
                        }
                    ],
                    "dx": [],
                },
            },
        )


class B50SourceFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api, cls.errors, cls.merge, cls.model = _load_modules()

    @classmethod
    def tearDownClass(cls):
        for name in list(sys.modules):
            if name == _PKG or name.startswith(_PKG + "."):
                sys.modules.pop(name, None)

    def _user(self, nickname: str, song_id: int, *, source: str):
        return self.model.UserInfo(
            nickname=nickname,
            rating=100,
            additional_rating=0,
            plate="",
            username="",
            charts=self.model.Data(
                sd=[
                    self.model.ChartInfo(
                        song_id=song_id,
                        title="测试曲",
                        level_index=3,
                        level="13+",
                        achievements=100.0,
                        dxScore=0,
                        rate="sss+",
                        fc="",
                        fs="",
                        type="standard",
                        level_label="",
                        ds=13.5,
                        source=source,
                        ra=500,
                    )
                ],
                dx=[],
            ),
        )

    def _run_with_sources(self, effects):
        async def fake_query(_self, qqid=None, username=None, *, source, is_ap=False):
            value = effects[source]
            if isinstance(value, BaseException):
                raise value
            return value

        with patch.object(self.api.MaiApi, "query_user_b50", fake_query):
            return asyncio.run(self.api.MaiApi().query_user_b50_merged(qqid=12345))

    def test_both_sources_failed_keeps_both_reasons(self):
        lxns_exc = self.errors.UserNotFoundError(source="lxns")
        fish_exc = self.errors.OAuthConsentRequiredError()
        with self.assertRaises(self.errors.AllSourcesFailedError) as caught:
            self._run_with_sources({"lxns": lxns_exc, "diving-fish": fish_exc})
        message = str(caught.exception)
        self.assertIn("落雪", message)
        self.assertIn("水鱼", message)
        self.assertIn("没有找到对应的舞萌玩家数据", message)
        self.assertIn("水鱼未授权", message)
        self.assertEqual(caught.exception.hx_code, "HX-MAI-004")

    def test_legacy_lxns_token_missing_raises_fish_error(self):
        fish_exc = self.errors.MaimaiTimeoutError()
        with self.assertRaises(self.errors.MaimaiTimeoutError) as caught:
            self._run_with_sources(
                {"lxns": self.errors.TokenNotFoundError(), "diving-fish": fish_exc}
            )
        self.assertIs(caught.exception, fish_exc)
        self.assertNotIsInstance(caught.exception, self.errors.AllSourcesFailedError)

    def test_ap_mode_does_not_blame_absent_fish(self):
        lxns_exc = self.errors.MaimaiDataFormatError()
        with patch.object(self.api.MaiApi, "query_user_b50", self._ap_fake(lxns_exc)):
            with self.assertRaises(self.errors.MaimaiDataFormatError):
                asyncio.run(self.api.MaiApi().query_user_b50_merged(qqid=1, is_ap=True))

    def _ap_fake(self, lxns_exc):
        async def fake_query(_self, qqid=None, username=None, *, source, is_ap=False):
            raise lxns_exc

        return fake_query

    def test_one_source_parse_failure_still_renders_other_source(self):
        with patch.object(self.api.httpx, "AsyncClient", _SplitClient):
            userinfo, meta = asyncio.run(
                self.api.MaiApi().query_user_b50_merged(qqid=12345)
            )
        self.assertEqual(userinfo.nickname, "水鱼玩家")
        self.assertEqual([c.song_id for c in userinfo.charts.sd], [799])
        self.assertFalse(meta["lxns"]["ok"])
        self.assertEqual(meta["lxns"]["error_type"], "MaimaiDataFormatError")
        self.assertTrue(meta["diving-fish"]["ok"])
        self.assertEqual(self.merge.sources_label(meta), "仅水鱼（落雪失败：查分器返回的数据和当前插件版本对不上。）")
        self.assertEqual(self.merge.effective_source(meta), "diving-fish")

    def test_dirty_record_is_skipped_not_fatal(self):
        class MixedClient(_FakeLxnsClient):
            bests_payload = {
                "data": {
                    "standard": [
                        {"song_id": "dirty"},
                        {"song_id": 799, "level_index": 3, "achievements": 100.0, "ra": 500},
                    ],
                    "dx": [{"song_id": 1235, "level_index": 3, "achievements": 99.0, "ra": 300}],
                    "total": 800,
                }
            }

        with patch.object(self.api.httpx, "AsyncClient", MixedClient):
            userinfo = asyncio.run(
                self.api.MaiApi().query_user_b50(qqid=12345, source="lxns")
            )
        self.assertEqual([c.song_id for c in userinfo.charts.sd], [799])
        self.assertEqual([c.song_id for c in userinfo.charts.dx], [1235])

    def test_fish_dirty_record_is_skipped_not_fatal(self):
        class DirtyFishClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc_info):
                return False

            async def post(self, url, json=None):
                return _FakeResponse(
                    200,
                    {
                        "nickname": "水鱼玩家",
                        "rating": 100,
                        "charts": {
                            "sd": [
                                {"song_id": None, "achievements": "oops"},
                                {"song_id": 1008, "level_index": 3, "achievements": 99.0, "ra": 400},
                            ],
                            "dx": [],
                        },
                    },
                )

        with patch.object(self.api.httpx, "AsyncClient", DirtyFishClient):
            userinfo = asyncio.run(
                self.api.MaiApi().query_user_b50(qqid=12345, source="diving-fish")
            )
        self.assertEqual([c.song_id for c in userinfo.charts.sd], [1008])

    def test_bound_but_not_synced_raises_score_not_synced(self):
        class NotSyncedClient(_FakeLxnsClient):
            bests_status = 404

        with patch.object(self.api.httpx, "AsyncClient", NotSyncedClient):
            with self.assertRaises(self.errors.ScoreNotSyncedError) as caught:
                asyncio.run(self.api.MaiApi().query_user_b50(qqid=12345, source="lxns"))
        message = str(caught.exception)
        self.assertIn("还没有同步过成绩", message)
        self.assertNotIn("没有找到对应的舞萌玩家数据", message)
        self.assertIn("同步", caught.exception.hx_suggestion)
        self.assertEqual(caught.exception.hx_code, "HX-MAI-005")

    def test_unknown_profile_keeps_user_not_found_wording(self):
        class UnknownProfileClient(_FakeLxnsClient):
            profile_status = 404

        with patch.object(self.api.httpx, "AsyncClient", UnknownProfileClient):
            with self.assertRaises(self.errors.UserNotFoundError) as caught:
                asyncio.run(self.api.MaiApi().query_user_b50(qqid=12345, source="lxns"))
        self.assertEqual(
            str(caught.exception), "落雪（LXNS）没有找到对应的舞萌玩家数据。"
        )

    def test_profile_without_friend_code_raises_score_not_synced(self):
        class NoFriendCodeClient(_FakeLxnsClient):
            pass

        for payload in (
            {"data": {"name": "落雪玩家"}},
            {"data": {}},
            {"data": {"friend_code": ""}},
        ):
            for bests_status in (400, 404):
                with self.subTest(payload=payload, bests_status=bests_status):
                    NoFriendCodeClient.profile_payload = payload
                    NoFriendCodeClient.bests_status = bests_status
                    with patch.object(self.api.httpx, "AsyncClient", NoFriendCodeClient):
                        with self.assertRaises(self.errors.ScoreNotSyncedError) as caught:
                            asyncio.run(
                                self.api.MaiApi().query_user_b50(qqid=12345, source="lxns")
                            )
                    self.assertIn("还没有同步过成绩", str(caught.exception))
                    self.assertNotIn("没有找到对应的舞萌玩家数据", str(caught.exception))

    def test_merge_failure_falls_back_to_lxns(self):
        lxns_user = self._user("落雪玩家", 799, source="lxns")
        fish_user = self._user("水鱼玩家", 1008, source="diving-fish")

        async def fake_query(_self, qqid=None, username=None, *, source, is_ap=False):
            return lxns_user if source == "lxns" else fish_user

        def broken_merge(_lxns, _fish):
            raise RuntimeError("merge boom")

        with patch.object(self.api.MaiApi, "query_user_b50", fake_query), patch.object(
            self.merge, "merge_b50", broken_merge
        ):
            userinfo, meta = asyncio.run(
                self.api.MaiApi().query_user_b50_merged(qqid=12345)
            )
        self.assertIs(userinfo, lxns_user)
        self.assertTrue(meta["lxns"]["ok"])
        self.assertFalse(meta["diving-fish"]["ok"])
        self.assertEqual(meta["diving-fish"]["error_type"], "merge_failed")
        self.assertEqual(self.merge.sources_label(meta), "仅落雪（合并异常，已回退单源）")

    def test_wholly_broken_bucket_fails_source(self):
        class BrokenBucketClient(_FakeLxnsClient):
            bests_payload = {
                "data": {
                    "standard": [{"song_id": "dirty"}, None],
                    "dx": [
                        {"song_id": 1235, "level_index": 3, "achievements": 99.0, "ra": 300}
                    ],
                }
            }

        with patch.object(self.api.httpx, "AsyncClient", BrokenBucketClient):
            with self.assertRaises(self.errors.MaimaiDataFormatError):
                asyncio.run(self.api.MaiApi().query_user_b50(qqid=12345, source="lxns"))

    def test_wholly_broken_fish_bucket_fails_source(self):
        class BrokenFishClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc_info):
                return False

            async def post(self, url, json=None):
                return _FakeResponse(
                    200,
                    {
                        "nickname": "水鱼玩家",
                        "charts": {
                            "sd": [{"song_id": "dirty"}],
                            "dx": [
                                {
                                    "song_id": 1235,
                                    "level_index": 3,
                                    "achievements": 99.0,
                                    "ra": 300,
                                }
                            ],
                        },
                    },
                )

        with patch.object(self.api.httpx, "AsyncClient", BrokenFishClient):
            with self.assertRaises(self.errors.MaimaiDataFormatError):
                asyncio.run(
                    self.api.MaiApi().query_user_b50(qqid=12345, source="diving-fish")
                )

    def test_empty_bucket_beside_healthy_bucket_is_fine(self):
        class DxOnlyClient(_FakeLxnsClient):
            bests_payload = {
                "data": {
                    "standard": [],
                    "dx": [
                        {"song_id": 1235, "level_index": 3, "achievements": 99.0, "ra": 300}
                    ],
                }
            }

        with patch.object(self.api.httpx, "AsyncClient", DxOnlyClient):
            userinfo = asyncio.run(
                self.api.MaiApi().query_user_b50(qqid=12345, source="lxns")
            )
        self.assertEqual(userinfo.charts.sd, [])
        self.assertEqual([c.song_id for c in userinfo.charts.dx], [1235])

    def test_source_200_with_empty_buckets_raises_no_scores(self):
        with patch.object(self.api.httpx, "AsyncClient", _FakeLxnsClient):
            with self.assertRaises(self.errors.NoScoresDataError) as caught:
                asyncio.run(self.api.MaiApi().query_user_b50(qqid=12345, source="lxns"))
        self.assertTrue(caught.exception.user_expected)

    def test_fish_200_with_empty_charts_raises_no_scores(self):
        class EmptyFishClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc_info):
                return False

            async def post(self, url, json=None):
                return _FakeResponse(
                    200,
                    {"nickname": "水鱼玩家", "charts": {"sd": [], "dx": []}},
                )

        with patch.object(self.api.httpx, "AsyncClient", EmptyFishClient):
            with self.assertRaises(self.errors.NoScoresDataError) as caught:
                asyncio.run(
                    self.api.MaiApi().query_user_b50(qqid=12345, source="diving-fish")
                )
        self.assertTrue(caught.exception.user_expected)

    def test_source_nodata_is_marked_in_meta(self):
        fish_user = self._user("水鱼玩家", 1008, source="diving-fish")
        userinfo, meta = self._run_with_sources(
            {"lxns": self.errors.NoScoresDataError(), "diving-fish": fish_user}
        )
        self.assertEqual([c.song_id for c in userinfo.charts.sd], [1008])
        self.assertFalse(meta["lxns"]["ok"])
        self.assertEqual(meta["lxns"]["error_type"], "NoData")
        self.assertEqual(meta["lxns"]["error"], "未返回成绩数据")
        self.assertTrue(meta["diving-fish"]["ok"])
        self.assertEqual(self.merge.sources_label(meta), "仅水鱼（落雪无成绩数据）")

    def test_both_sources_nodata_raises_user_expected_error(self):
        with self.assertRaises(self.errors.NoScoresDataError) as caught:
            self._run_with_sources(
                {
                    "lxns": self.errors.NoScoresDataError(),
                    "diving-fish": self.errors.NoScoresDataError(),
                }
            )
        self.assertTrue(caught.exception.user_expected)
        self.assertIn("没有可用的成绩数据", str(caught.exception))

    def test_both_real_sources_empty_do_not_render_empty_charts(self):
        class EmptyBothClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc_info):
                return False

            async def get(self, url, headers=None):
                if "/bests" in url:
                    return _FakeResponse(200, {"data": {"standard": [], "dx": []}})
                return _FakeResponse(200, {"data": {"friend_code": "FRIEND-1"}})

            async def post(self, url, json=None):
                return _FakeResponse(
                    200,
                    {"nickname": "水鱼玩家", "charts": {"sd": [], "dx": []}},
                )

        with patch.object(self.api.httpx, "AsyncClient", EmptyBothClient):
            with self.assertRaises(self.errors.NoScoresDataError):
                asyncio.run(self.api.MaiApi().query_user_b50_merged(qqid=12345))

    def test_all_sources_failed_is_user_expected_without_diagnostic(self):
        from release010_import import send_error_with_diagnostic

        class RecordingMatcher:
            def __init__(self):
                self.messages = []

            async def send(self, message, **kwargs):
                self.messages.append(message)

            async def finish(self, message=None, *args, **kwargs):
                if message is not None:
                    self.messages.append(message)
                return None

        exc = self.errors.AllSourcesFailedError("没有找到玩家", "上游超时")

        async def run_case(directory):
            matcher = RecordingMatcher()
            path = await send_error_with_diagnostic(
                matcher, exc, "MAI", context="b50", directory=directory
            )
            return path, list(Path(directory).iterdir()), matcher.messages

        with tempfile.TemporaryDirectory() as directory:
            path, files, messages = asyncio.run(run_case(directory))

        self.assertTrue(exc.user_expected)
        self.assertEqual(path, Path())
        self.assertEqual(files, [])
        self.assertEqual(len(messages), 1)
        self.assertIn("没有找到玩家", messages[0])


if __name__ == "__main__":
    unittest.main()
