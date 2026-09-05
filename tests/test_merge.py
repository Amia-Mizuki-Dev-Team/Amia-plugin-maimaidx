"""双源逐谱面汇总（libraries.maimaidx_merge）纯函数测试（无 nonebot 环境可运行）。"""

from __future__ import annotations

import math
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from libraries.maimaidx_merge import (  # noqa: E402
    better_fc,
    better_fs,
    chart_key,
    effective_source,
    fish_consent_missing,
    merge_b50,
    merge_chart_info,
    merge_chart_infos,
    normalized_song_id,
    sources_label,
)
from libraries.maimaidx_model import ChartInfo, Data, UserInfo  # noqa: E402


def _chart(
    song_id: int,
    *,
    type_: str = "standard",
    level_index: int = 3,
    achievements: float = 100.0,
    fc: str = "",
    fs: str = "",
    ra: int = 0,
    ds: float = 13.5,
    level: str = "13+",
    title: str = "测试曲",
    source: str = "lxns",
    rate: str = "sss+",
    dxScore: int = 0,
) -> ChartInfo:
    return ChartInfo(
        song_id=song_id,
        title=title,
        level_index=level_index,
        level=level,
        achievements=achievements,
        dxScore=dxScore,
        rate=rate,
        fc=fc,
        fs=fs,
        type=type_,
        level_label="",
        ds=ds,
        source=source,
        ra=ra,
    )


def _user(charts_sd=None, charts_dx=None, **kwargs) -> UserInfo:
    return UserInfo(
        nickname=kwargs.get("nickname", "落雪昵称"),
        rating=kwargs.get("rating", 0),
        additional_rating=kwargs.get("additional_rating", 0),
        plate=kwargs.get("plate", ""),
        username=kwargs.get("username", ""),
        charts=Data(sd=list(charts_sd or []), dx=list(charts_dx or [])),
    )


class BadgeRankTests(unittest.TestCase):
    def test_fc_rank_order(self):
        # app > ap > fcp > fc > 无
        self.assertEqual(better_fc("fc", "ap"), "ap")
        self.assertEqual(better_fc("ap", "app"), "app")
        self.assertEqual(better_fc("fcp", "fc"), "fcp")
        self.assertEqual(better_fc("", "fc"), "fc")
        self.assertEqual(better_fc("fc", ""), "fc")
        self.assertEqual(better_fc("app", "app"), "app")

    def test_fs_rank_order(self):
        # fsdp/fdxp > fsd/fdx > fsp > fs > 无
        self.assertEqual(better_fs("fs", "fsdp"), "fsdp")
        self.assertEqual(better_fs("fs", "fdxp"), "fdxp")
        self.assertEqual(better_fs("fsd", "fsp"), "fsd")
        self.assertEqual(better_fs("fs", "fsp"), "fsp")
        self.assertEqual(better_fs("", "fs"), "fs")
        self.assertEqual(better_fs("fsdp", "fdxp"), "fsdp")

    def test_legacy_badge_aliases_are_normalized(self):
        self.assertEqual(better_fc("fc+", "fcp"), "fcp")
        self.assertEqual(better_fs("fs+", "fsp"), "fsp")


class MergeChartInfoTests(unittest.TestCase):
    def test_user_example_cross_source_badge_combination(self):
        # 用户示例：落雪 100.9250%+FC，水鱼 100.0000%+AP → 汇总 = 100.9250% + AP
        lxns = _chart(799, achievements=100.9250, fc="fc", ra=520)
        fish = _chart(799, achievements=100.0000, fc="ap", ra=505, source="diving-fish")
        merged = merge_chart_info(lxns, fish)
        self.assertEqual(merged.achievements, 100.9250)
        self.assertEqual(merged.fc, "ap")
        self.assertEqual(merged.ra, 520)
        self.assertEqual(merged.source, "merged")
        # 达成率较高一方（落雪）提供 rate/dxScore
        self.assertEqual(merged.rate, lxns.rate)

    def test_achievements_take_max_and_ra_take_max(self):
        lxns = _chart(38, achievements=99.0000, ra=400)
        fish = _chart(38, achievements=99.5000, ra=410, source="diving-fish")
        merged = merge_chart_info(lxns, fish)
        self.assertEqual(merged.achievements, 99.5)
        self.assertEqual(merged.ra, 410)
        self.assertEqual(merged.rate, fish.rate)

    def test_dx_id_normalization_unifies_both_namespaces(self):
        # 水鱼 DX id = 原生 id + 10000；落雪用原生 id
        lxns = _chart(1235, type_="dx", achievements=100.0, fc="fc")
        fish = _chart(11235, type_="dx", achievements=98.0, fc="ap", source="diving-fish")
        self.assertEqual(chart_key(lxns), chart_key(fish))
        merged_list = merge_chart_infos([lxns], [fish])
        self.assertEqual(len(merged_list), 1)
        self.assertEqual(merged_list[0].song_id, 1235)
        self.assertEqual(merged_list[0].fc, "ap")

    def test_utage_ids_are_not_offset(self):
        info = _chart(100018, type_="dx", source="diving-fish")
        self.assertEqual(normalized_song_id(info), 100018)
        self.assertEqual(chart_key(info)[0], 100018)

    def test_single_source_records_are_kept_with_native_ids(self):
        lxns = [_chart(799, achievements=100.0)]
        fish = [_chart(11008, type_="dx", achievements=99.0, source="diving-fish")]
        self.assertEqual([c.song_id for c in merge_chart_infos(lxns, [])], [799])
        self.assertEqual([c.song_id for c in merge_chart_infos([], fish)], [1008])

    def test_ds_conflict_prefers_lxns(self):
        lxns = _chart(799, ds=13.5)
        fish = _chart(799, ds=13.6, source="diving-fish")
        self.assertEqual(merge_chart_info(lxns, fish).ds, 13.5)
        # 非零单方直接采用
        fish_only_ds = _chart(799, ds=0.0)
        self.assertEqual(merge_chart_info(fish_only_ds, fish).ds, 13.6)

    def test_ds_conflict_recomputes_ra_from_lxns_ds(self):
        # 定数冲突时 ra 按落雪 ds + 两源较大达成率重算（computeRa），
        # 而非沿用两源 max；独立测试环境导入 maimaidx_best_50 必然失败
        # （依赖 nonebot/PIL），注入同名 stub 模块使重算路径可确定性验证。
        lxns = _chart(799, ds=13.5, ra=520)
        fish = _chart(799, ds=13.6, ra=999, source="diving-fish")
        stub = types.ModuleType("libraries.maimaidx_best_50")
        # 与官方 computeRa 同式：合并达成率 100.0% 落 SSS 档，系数 21.6
        stub.computeRa = lambda ds, ach, **kw: math.floor(ds * min(100.5, ach) / 100 * 21.6)
        with patch.dict(sys.modules, {"libraries.maimaidx_best_50": stub}):
            merged = merge_chart_info(lxns, fish)
        self.assertEqual(merged.ds, 13.5)
        # floor(13.5 × 1.0 × 21.6) = 291，取代两源 max(520, 999)
        self.assertEqual(merged.ra, 291)
        self.assertNotEqual(merged.ra, max(lxns.ra, fish.ra))


class MergeB50Tests(unittest.TestCase):
    def test_both_sources_merge_into_buckets(self):
        lxns = _user(
            charts_sd=[_chart(799, achievements=100.0, ra=520)],
            charts_dx=[_chart(11235, type_="dx", achievements=99.0, ra=300, source="diving-fish")],
        )
        fish = _user(
            charts_sd=[_chart(799, achievements=99.5, ra=510)],
            charts_dx=[_chart(1235, type_="dx", achievements=100.5, ra=310, source="diving-fish")],
        )
        userinfo, meta = merge_b50(lxns, fish)
        self.assertTrue(meta["lxns"]["ok"])
        self.assertTrue(meta["diving-fish"]["ok"])
        sd_ids = [c.song_id for c in userinfo.charts.sd]
        dx_ids = [c.song_id for c in userinfo.charts.dx]
        # 同谱面跨桶：归入达成率较高一方所在桶（dx 侧 100.5 > 99.0）
        self.assertIn(799, sd_ids)
        self.assertEqual(dx_ids, [1235])
        # rating = 合并后 B35+B15 单曲 ra 之和
        self.assertEqual(userinfo.rating, 520 + 310)
        # 徽章跨源组合
        sd_record = userinfo.charts.sd[0]
        self.assertEqual(sd_record.achievements, 100.0)
        self.assertEqual(sd_record.ra, 520)

    def test_single_source_degradation_labels(self):
        lxns = _user(charts_sd=[_chart(799, ra=100)], rating=100)
        userinfo, meta = merge_b50(lxns, None)
        self.assertFalse(meta["diving-fish"]["ok"])
        self.assertEqual(userinfo.rating, 100)
        self.assertEqual(sources_label(meta), "仅落雪")
        self.assertEqual(effective_source(meta), "lxns")

        meta["diving-fish"].update(error="水鱼未授权", error_type="OAuthConsentRequiredError")
        self.assertEqual(sources_label(meta), "仅落雪（水鱼未授权）")
        self.assertTrue(fish_consent_missing(meta))

        meta["diving-fish"].update(error="上游超时", error_type="MaimaiTimeoutError")
        self.assertEqual(sources_label(meta), "仅落雪（水鱼失败：上游超时）")
        self.assertFalse(fish_consent_missing(meta))

    def test_fish_only_degradation_label(self):
        fish = _user(
            nickname="水鱼昵称",
            charts_dx=[_chart(11008, type_="dx", ra=200, source="diving-fish")],
            rating=200,
        )
        userinfo, meta = merge_b50(None, fish)
        self.assertFalse(meta["lxns"]["ok"])
        meta["lxns"].update(error="上游超时", error_type="MaimaiTimeoutError")
        self.assertEqual(sources_label(meta), "仅水鱼（落雪失败：上游超时）")
        self.assertEqual(effective_source(meta), "diving-fish")
        self.assertEqual(userinfo.nickname, "水鱼昵称")
        # fish-only DX 成绩应归一化为原生 id
        self.assertEqual([c.song_id for c in userinfo.charts.dx], [1008])

    def test_ap_mode_marks_fish_as_not_applicable(self):
        lxns = _user(charts_sd=[_chart(799, ra=100)], rating=100)
        _, meta = merge_b50(lxns, None)
        meta["diving-fish"].update(error=None, error_type="not_applicable")
        self.assertEqual(sources_label(meta), "仅落雪")
        self.assertEqual(effective_source(meta), "lxns")

    def test_rating_falls_back_to_source_max_when_merged_sum_is_zero(self):
        lxns = _user(charts_sd=[_chart(799, ra=0)], rating=14000)
        fish = _user(charts_sd=[_chart(799, ra=0, source="diving-fish")], rating=14500)
        userinfo, _meta = merge_b50(lxns, fish)
        self.assertEqual(userinfo.rating, 14500)

    def test_merged_b35_b15_cap_by_ra(self):
        sd_charts = [
            _chart(100 + i, achievements=100.0 - i, ra=500 - i) for i in range(40)
        ]
        userinfo, _meta = merge_b50(_user(charts_sd=sd_charts, rating=0), None)
        self.assertEqual(len(userinfo.charts.sd), 35)
        ras = [c.ra for c in userinfo.charts.sd]
        self.assertEqual(ras, sorted(ras, reverse=True))

    def test_both_none_raises(self):
        with self.assertRaises(ValueError):
            merge_b50(None, None)


if __name__ == "__main__":
    unittest.main()
