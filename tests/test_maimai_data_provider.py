from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROVIDER = ROOT / "plugins" / "lxns_b50" / "providers"


class DTO:
    def __init__(self, **values):
        self.__dict__.update(values)


@dataclass(frozen=True)
class ChartKey:
    song_id: int
    chart_type: str
    difficulty_index: int


def music(song_id, chart_type, title="Song", version="version A", ds=(13.7, 14.0, 14.2, 14.5, 14.8)):
    notes = [types.SimpleNamespace(notes=(100, 20, 30, 4)) for _ in ds]
    return types.SimpleNamespace(
        id=str(song_id), type=chart_type, title=title, level=["13+"] * len(ds), ds=list(ds),
        charts=notes, basic_info=types.SimpleNamespace(**{"from": version, "artist": "Artist", "genre": "Genre", "bpm": 180}),
    )


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.saved = {name: sys.modules.get(name) for name in list(sys.modules) if name.startswith("provider_test") or name.startswith("nonebot")}
        core = types.SimpleNamespace(
            MaimaiChartKey=ChartKey, MaimaiChartRecord=DTO, MaimaiPlayerSummary=DTO,
            MaimaiSong=DTO, MaimaiChart=DTO, MAIMAI_DATA_PROVIDER="maimai.data",
        )
        nonebot = types.ModuleType("nonebot")
        nonebot.require = lambda name: core
        log = types.ModuleType("nonebot.log")
        log.logger = types.SimpleNamespace(warning=lambda *args, **kwargs: None)
        sys.modules["nonebot"] = nonebot
        sys.modules["nonebot.log"] = log
        for name in ("provider_test", "provider_test.providers", "provider_test.libraries"):
            package = types.ModuleType(name); package.__path__ = []; sys.modules[name] = package
        config = types.ModuleType("provider_test.config"); config.maiconfig = types.SimpleNamespace(official_bot_ids=[]); sys.modules[config.__name__] = config
        api = types.SimpleNamespace()
        api_data = types.ModuleType("provider_test.libraries.maimaidx_api_data"); api_data.maiApi = api; sys.modules[api_data.__name__] = api_data
        mai = types.SimpleNamespace(total_list=[])
        music_data = types.ModuleType("provider_test.libraries.maimaidx_music"); music_data.mai = mai; sys.modules[music_data.__name__] = music_data
        for module_name, path in (("provider_test.providers.normalization", PROVIDER / "normalization.py"), ("provider_test.providers.maimai_data", PROVIDER / "maimai_data.py")):
            spec = importlib.util.spec_from_file_location(module_name, path); module = importlib.util.module_from_spec(spec); sys.modules[module_name] = module; spec.loader.exec_module(module)
        self.core, self.api, self.mai = core, api, mai
        self.module = sys.modules["provider_test.providers.maimai_data"]
        self.provider = self.module.MaimaidxDataProvider()

    def tearDown(self):
        for name in list(sys.modules):
            if name.startswith("provider_test") or name.startswith("nonebot"):
                sys.modules.pop(name, None)
        for name, value in self.saved.items():
            if value is not None:
                sys.modules[name] = value

    def identity(self, canonical="123"):
        return types.SimpleNamespace(canonical_user_id=canonical, external_key=types.SimpleNamespace(self_id="1", user_id="456"))

    def record(self, song_id=8, chart_type="SD", achievement=100.0, **extra):
        value = {"song_id": song_id, "type": chart_type, "level_index": 3, "title": "Song", "level": "14", "ds": 14.5, "achievements": achievement, "ra": 300, "rate": "sssp", "fc": "ap", "fs": "fsdp", "play_count": 2, "timestamp": 0}
        value.update(extra); return value

    def test_identity_prefers_canonical(self): self.assertEqual(self.module.resolve_qq_id(self.identity("123")), 123)
    def test_identity_falls_back_to_external(self): self.assertEqual(self.module.resolve_qq_id(self.identity(None)), 456)
    def test_identity_rejects_non_numeric(self): self.assertIsNone(self.module.resolve_qq_id(self.identity("not-qq")))
    def test_version_prioritizes_from(self): self.assertEqual(self.module._version(music(8, "SD", version="from-value")), "from-value")
    def test_version_fallbacks(self):
        self.assertEqual(self.module._version(types.SimpleNamespace(basic_info={"version": "fallback"})), "fallback")
        self.assertEqual(self.module._version(types.SimpleNamespace(version="root")), "root")
    def test_summary_optional_fields(self):
        self.api.query_user_b50 = lambda **kwargs: asyncio.sleep(0, result=types.SimpleNamespace(nickname=None, rating=1, additional_rating=None, plate=None))
        identity = self.identity()
        result = asyncio.run(self.provider.get_player_summary(identity))
        self.assertIsNone(result.player_name); self.assertIsNone(result.additional_rating); self.assertIs(result.identity, identity)
    def test_records_convert_deduplicate_and_sort(self):
        self.mai.total_list[:] = [music(8, "SD"), music(10008, "DX")]
        self.api.query_user_get_dev = lambda **kwargs: asyncio.sleep(0, result=[self.record(10008, "DX", 99), self.record(8, "SD", 100), self.record(10008, "DX", 100.5)])
        result = asyncio.run(self.provider.get_player_records(self.identity()))
        self.assertEqual([(item.chart.song_id, item.chart.chart_type) for item in result], [(8, "dx"), (8, "standard")]); self.assertEqual(result[0].achievement, 100.5); self.assertEqual(result[0].updated_at, "1970-01-01T00:00:00+00:00")
    def test_records_filter_version_and_fields(self):
        self.mai.total_list[:] = [music(8, "SD", version="version A")]
        self.api.query_user_get_dev = lambda **kwargs: asyncio.sleep(0, result=[self.record()])
        query = types.SimpleNamespace(min_constant=14, max_constant=15, versions=("version A",), chart_types=("standard",), difficulty_indexes=(3,))
        result = asyncio.run(self.provider.get_player_records(self.identity(), query)); self.assertEqual(len(result), 1)
    def test_records_reject_bad_range_and_response(self):
        query = types.SimpleNamespace(min_constant=2, max_constant=1)
        with self.assertRaises(ValueError): asyncio.run(self.provider.get_player_records(self.identity(), query))
        self.api.query_user_get_dev = lambda **kwargs: asyncio.sleep(0, result={"bad": []})
        with self.assertRaises(TypeError): asyncio.run(self.provider.get_player_records(self.identity()))
    def test_records_propagate_network_error(self):
        async def fail(**kwargs): raise TimeoutError()
        self.api.query_user_get_dev = fail
        with self.assertRaises(TimeoutError): asyncio.run(self.provider.get_player_records(self.identity()))
    def test_catalog_deduplicates_and_metadata(self):
        self.mai.total_list[:] = [music(10008, "DX"), music(8, "SD"), music(9, "SD", title=" ")]
        result = asyncio.run(self.provider.get_music_catalog())
        self.assertEqual(len(result), 1); self.assertEqual((result[0].song_id, result[0].version, result[0].bpm), (8, "version A", 180.0))
    def test_chart_info_standard_dx_and_bounds(self):
        self.mai.total_list[:] = [music(8, "SD"), music(10008, "DX")]
        standard = asyncio.run(self.provider.get_chart_info(ChartKey(8, "standard", 3)))
        deluxe = asyncio.run(self.provider.get_chart_info(ChartKey(8, "dx", 3)))
        self.assertEqual((standard.notes, deluxe.constant), (154, 14.5))
        self.assertIsNone(asyncio.run(self.provider.get_chart_info(ChartKey(8, "dx", 4 + 1))))
