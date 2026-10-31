"""落雪曲库归一化的 SD/DX/utage 行为回归测试（无 nonebot / 无网络环境可运行）。

钉五件事：
1. 只有 DX 谱面的歌归一化后 id 必须 +10000（水鱼/成绩体系的 DX 命名空间）。
2. 混合歌（同一 id 同时有 SD 与 DX）必须产出两条：原生 id 的 SD 条目与
   id+10000 的 DX 条目，且结果不依赖 ``difficulties`` 的键序或歌曲 ``type``。
3. 宴会场（utage）不进曲库：notes 是 dict、level 形如 ``"12?"``、ds 恒 0，
   混进 ``total_list`` 会让 ``sum(notes)`` 直接 TypeError。
4. ``0 < id < 10000`` 守卫：宴会场（>= 100000）与已偏移 id 不能被再 +10000。
5. 合流只按**归一化后**的键判重：水鱼只有 SD 1001 时，落雪混合歌的 DX 11001
   仍要写入（旧实现按落雪原始 id 跳过，60 首混合歌的 DX B50 行显示 SD 定数）。

手法沿用 ``tests/test_cover_selfheal.py``：``maimaidx_music.py`` 的 ``..config``
与 ``image`` / ``lib_music_db`` / ``maimaidx_api_data`` 依赖链在单测环境 import
不动，所以用别名包 + 替身模块加载生产源码本体。
运行：``python -m unittest discover -s tests -p "test_lxns_mixed_charts.py" -v``
"""

from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
_PKG = "maidx_mixed_charts_under_test"


def _module(name: str, **attrs: Any) -> types.ModuleType:
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


def _load_music_module():
    pkg = types.ModuleType(_PKG)
    pkg.__path__ = [str(PLUGIN_ROOT)]
    sys.modules[_PKG] = pkg
    libraries = types.ModuleType(f"{_PKG}.libraries")
    libraries.__path__ = [str(PLUGIN_ROOT / "libraries")]
    sys.modules[f"{_PKG}.libraries"] = libraries
    _module(
        f"{_PKG}.config",
        maiconfig=SimpleNamespace(lxnstoken="", maimaidx_alias_proxy=False),
        static=Path("__unset_static__"),
        music_file=Path("__unset_music__.json"),
        coverdir=Path("__unset_cover__"),
        # 不存在即不读不写：Guess.__init__ 只在文件存在时读。
        guess_file=Path("__unset_guess__") / "guess.jsonl",
        music_db_path=Path("__unset_musicdb__.json"),
    )
    _module(
        f"{_PKG}.libraries.image",
        music_picture=lambda song_id: Path("__unset_cover__") / f"{song_id}.png",
    )
    _module(
        f"{_PKG}.libraries.lib_music_db",
        music_db_cache=SimpleNamespace(load=None),
        download_all_covers=None,
        _download_one_cover=None,
        _LXNS_HEADERS={},
    )
    _module(f"{_PKG}.libraries.maimaidx_api_data", maiApi=SimpleNamespace())
    _module(
        f"{_PKG}.libraries.maimaidx_alias_sync",
        alias_values=lambda values: list(values or []),
        fetch_yuzu_aliases=None,
    )
    return importlib.import_module(f"{_PKG}.libraries.maimaidx_music")


music_module = _load_music_module()
_normalize_lxns_song = music_module._normalize_lxns_song
_merge_song_sources = music_module._merge_song_sources
MaiMusic = music_module.MaiMusic
MusicList = music_module.MusicList


# --------------------------------------------------------------------------
# 上游形状替身
# --------------------------------------------------------------------------


def _chart(
    level: str,
    level_value: float,
    difficulty: int,
    *,
    notes: Any = None,
    designer: str = "chart",
) -> Dict[str, Any]:
    return {
        "difficulty": difficulty,
        "level": level,
        "level_value": level_value,
        "notes": [100, 10, 20, 5, 4] if notes is None else notes,
        "note_designer": designer,
    }


def _mixed_song(song_id: int = 70, *, standard_first: bool = False) -> Dict[str, Any]:
    """SD 5 张、DX 4 张；歌曲级 ``type`` 故意写 standard，键序可切换。"""
    standard = [
        _chart("5", 5.0, 0),
        _chart("8", 8.0, 1),
        _chart("9+", 9.8, 2),
        _chart("11", 11.2, 3),
        _chart("12+", 12.7, 4),
    ]
    dx = [
        _chart("6", 6.0, 0),
        _chart("9", 9.0, 1),
        _chart("11+", 11.5, 2),
        _chart("13", 13.0, 3),
    ]
    difficulties = (
        {"standard": standard, "dx": dx}
        if standard_first
        else {"dx": dx, "standard": standard}
    )
    return {
        "id": song_id,
        "title": "Grievous Lady",
        "artist": "Team Grimoire vs Laur",
        "genre": "maimai",
        "version": "CiRCLE",
        "bpm": 210,
        "type": "standard",
        "difficulties": difficulties,
    }


def _dx_only_song(song_id: int = 1235) -> Dict[str, Any]:
    return {
        "id": song_id,
        "title": "DX Only",
        "type": "dx",
        "difficulties": {
            "dx": [
                _chart("7", 7.0, 0),
                _chart("10", 10.0, 1),
                _chart("12", 12.0, 2),
                _chart("14", 14.0, 3),
            ]
        },
    }


def _utage_song(song_id: int = 100851) -> Dict[str, Any]:
    return {
        "id": song_id,
        "title": "宴会场测试曲",
        "type": "utage",
        "difficulties": {
            "utage": [
                {
                    "difficulty": 0,
                    "level": "12?",
                    "level_value": 0,
                    "notes": {"tap": 100, "hold": 10, "slide": 20, "touch": 5, "break": 4},
                    "note_designer": "utage",
                }
            ]
        },
    }


def _fish_song(song_id: int, title: str, type_: str = "standard") -> Dict[str, Any]:
    return {
        "id": song_id,
        "title": title,
        "type": type_,
        "level": ["13"],
        "ds": [13.0],
        "charts": [{"notes": [1, 2, 3, 4, 5], "charter": "fish"}],
        "basic_info": {"artist": "fish", "genre": "maimai", "bpm": 200, "from": "PRiSM"},
    }


# --------------------------------------------------------------------------
# 单首归一化
# --------------------------------------------------------------------------


class NormalizeTest(unittest.TestCase):
    def test_dx_only_song_gets_offset_id(self):
        music = _normalize_lxns_song(_dx_only_song(1235))
        self.assertIsNotNone(music)
        self.assertEqual(str(music.id), "11235")
        self.assertEqual(music.type, "DX")
        self.assertEqual(music.level, ["7", "10", "12", "14"])

    def test_mixed_song_produces_sd_and_dx_entries(self):
        song = _mixed_song(70)
        standard = _normalize_lxns_song(song)
        dx = _normalize_lxns_song(song, chart_type="DX")

        self.assertIsNotNone(standard)
        self.assertIsNotNone(dx)
        # SD 走原生 id、5 级；不能混进 DX 的下标（否则 Master 位显示 DX 定数）
        self.assertEqual((str(standard.id), standard.type), ("70", "standard"))
        self.assertEqual(standard.level, ["5", "8", "9+", "11", "12+"])
        self.assertEqual(standard.ds, [5.0, 8.0, 9.8, 11.2, 12.7])
        # DX 走 +10000、4 级（10070）
        self.assertEqual((str(dx.id), dx.type), ("10070", "DX"))
        self.assertEqual(dx.level, ["6", "9", "11+", "13"])
        self.assertEqual(dx.ds, [6.0, 9.0, 11.5, 13.0])

    def test_mixed_song_is_key_order_independent(self):
        dx_first = _normalize_lxns_song(_mixed_song(70))
        sd_first = _normalize_lxns_song(_mixed_song(70, standard_first=True))
        self.assertEqual((str(dx_first.id), dx_first.type), ("70", "standard"))
        self.assertEqual((str(sd_first.id), sd_first.type), ("70", "standard"))
        self.assertEqual(dx_first.level, sd_first.level)
        self.assertEqual(dx_first.ds, sd_first.ds)

    def test_utage_song_is_dropped(self):
        self.assertIsNone(_normalize_lxns_song(_utage_song(100851)))

    def test_utage_entry_is_dropped_when_sd_coexists(self):
        song = _dx_only_song(1235)
        song["difficulties"]["utage"] = [
            {"difficulty": 0, "level": "12?", "level_value": 0, "notes": {"tap": 1}}
        ]
        music = _normalize_lxns_song(song)
        self.assertIsNotNone(music)
        self.assertEqual(music.id, "11235")
        self.assertNotIn("12?", music.level)

    def test_id_offset_guard_keeps_large_dx_id(self):
        # >= 10000 的 id 已经是偏移命名/宴会场，再加 10000 会撞到别的歌
        music = _normalize_lxns_song(_dx_only_song(161852))
        self.assertIsNotNone(music)
        self.assertEqual(str(music.id), "161852")
        self.assertEqual(music.type, "DX")

    def test_explicit_chart_type_without_matching_charts_returns_none(self):
        self.assertIsNone(_normalize_lxns_song(_dx_only_song(1235), chart_type="standard"))


# --------------------------------------------------------------------------
# 双源合流
# --------------------------------------------------------------------------


class MergeTest(unittest.TestCase):
    def test_mixed_song_yields_reachable_sd_and_dx_ids(self):
        combined = _merge_song_sources([_mixed_song(70)], [])
        self.assertEqual(set(combined), {"70", "10070"})
        total = MusicList(combined.values())
        self.assertEqual(total.by_id("70").type, "standard")
        self.assertEqual(total.by_id("10070").type, "DX")
        self.assertEqual(total.by_id("70").level[4], "12+")
        self.assertEqual(total.by_id("10070").level[3], "13")

    def test_mixed_song_keeps_dx_when_fish_only_has_sd(self):
        # 复审 Major：水鱼只给 SD 1001，落雪的 mixed 歌 DX 11001 仍必须写入
        combined = _merge_song_sources(
            [_mixed_song(1001)], [_fish_song(1001, "Fish SD")]
        )
        self.assertEqual(set(combined), {"1001", "11001"})
        self.assertEqual(combined["1001"].title, "Fish SD")
        self.assertEqual(combined["11001"].type, "DX")

    def test_fish_entries_win_when_both_sides_present(self):
        combined = _merge_song_sources(
            [_mixed_song(1001)],
            [_fish_song(1001, "Fish SD"), _fish_song(11001, "Fish DX", "dx")],
        )
        self.assertEqual(set(combined), {"1001", "11001"})
        self.assertEqual(combined["1001"].title, "Fish SD")
        self.assertEqual(combined["11001"].title, "Fish DX")

    def test_utage_never_enters_total_list(self):
        combined = _merge_song_sources(
            [_mixed_song(70), _utage_song(100851), _utage_song(100852)],
            [],
        )
        self.assertEqual(set(combined), {"70", "10070"})

        catalog = MaiMusic()
        catalog.total_list = MusicList(combined.values())
        level_data = catalog.total_level_data
        ids = {
            str(entry.id)
            for bucket in level_data.values()
            for entries in bucket.values()
            for entry in entries
        }
        self.assertNotIn("100851", ids)
        self.assertIn("10070", ids)
        self.assertFalse([level for level in level_data if str(level).endswith("?")])


if __name__ == "__main__":
    unittest.main()
