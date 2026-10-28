"""B50 出图两个显示缺陷的回归单测。

钉两件事：

1. **定数回填不得用 0 覆盖上游有效值**（``libraries/maimaidx_best_50.py``）：
   上游接口本来就带 ``ds``；本地曲库对新曲/新难度缺数据（0）时，图上曾出现
   ``0.0 -> xxx``。只有本地值 > 0 才覆盖，本地有效值仍然优先。
2. **曲绘回落不得被旧上限截断**（``libraries/image.py`` 的 ``music_picture``）：
   水鱼 DX ID = 落雪 ID + 10000，曲库扩容后已突破 11000（如 11817 → 1817）。
   策略 4 的安全区间是 ``10000 < id < 100000``（宴会场 > 100000 由策略 2 处理）。

手法沿用 ``tests/test_b50_appendix.py`` 的 AST 路线：这两个模块都 import 了
``..config`` 依赖链（.env、曲库），单测环境 import 不动；所以从生产源码里按
**名字**（不按行号）挑出相关定义 exec 进受控命名空间，被测的是生产源码本体。

运行：``python -m unittest tests.test_b50_render -v``（在插件根目录）
"""

from __future__ import annotations

import ast
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Union
from unittest import mock

from PIL import Image

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
BEST50_FILE = PLUGIN_ROOT / "libraries" / "maimaidx_best_50.py"
IMAGE_FILE = PLUGIN_ROOT / "libraries" / "image.py"


class _LogStub:
    """loguru 替身：只记录 warning，供「两处都拿不到才告警」断言。"""

    def __init__(self) -> None:
        self.warnings: List[str] = []

    def debug(self, msg: str, *a: Any, **k: Any) -> None:
        pass

    def info(self, msg: str, *a: Any, **k: Any) -> None:
        pass

    def warning(self, msg: str, *a: Any, **k: Any) -> None:
        self.warnings.append(str(msg))

    def error(self, msg: str, *a: Any, **k: Any) -> None:
        pass


def _pick_module(
    path: Path,
    names: set,
    extra_globals: dict,
    module_name: str,
) -> types.ModuleType:
    """按名字从生产源码挑出定义，exec 进受控命名空间。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    body: List[ast.stmt] = []
    found: set = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in names:
                body.append(node)
                found.add(node.name)
        elif isinstance(node, ast.Assign):
            targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
            hits = targets & names
            if hits:
                body.append(node)
                found.update(hits)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in names:
                body.append(node)
                found.add(node.target.id)
    missing = names - found
    if missing:
        raise AssertionError(f"{path.name} 缺少待测定义: {sorted(missing)}")

    module = types.ModuleType(module_name)
    module.__dict__.update(extra_globals)
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), "exec"), module.__dict__)
    return module


def _load_levels_module(local_lookup, dx_by_id) -> types.ModuleType:
    return _pick_module(
        BEST50_FILE,
        {"_coerce_ds", "_fill_missing_chart_levels"},
        {
            "Any": Any,
            "List": List,
            # 生产注解求值用；真实类型不影响被测逻辑
            "ChartInfo": object,
            "_find_local_chart_music": local_lookup,
            "mai": SimpleNamespace(total_list=SimpleNamespace(by_id=dx_by_id)),
            "log": _LogStub(),
        },
        "_best50_levels_under_test",
    )


def _load_image_module() -> types.ModuleType:
    return _pick_module(
        IMAGE_FILE,
        {
            "_corrupted_cover_ids",
            "is_valid_image",
            "_check_and_clean_corrupted",
            "forget_corrupted_cover",
            "music_picture",
        },
        {"Path": Path, "Union": Union, "log": _LogStub(), "coverdir": Path("__unset__")},
        "_image_under_test",
    )


class ChartLevelBackfillTest(unittest.TestCase):
    """缺陷 1：本地曲库定数为 0 时，不得覆盖上游有效定数。"""

    def setUp(self) -> None:
        self.local_music = None
        self.dx_music = None
        self.mod = _load_levels_module(self._local_lookup, self._dx_by_id)

    def _local_lookup(self, song_id, chart_type):
        return self.local_music

    def _dx_by_id(self, sid):
        return self.dx_music

    def _chart(self, *, ds, level_index: int = 3, song_id: int = 11817, chart_type: str = "dx"):
        return SimpleNamespace(song_id=song_id, type=chart_type, level_index=level_index, ds=ds)

    def test_local_zero_keeps_upstream_ds(self) -> None:
        # 本地曲库有该难度但定数缺失（0）——上游 13.5 必须原样保留
        self.local_music = SimpleNamespace(id=11817, ds=[0.0, 0.0, 0.0, 0.0, 0.0])
        chart = self._chart(ds=13.5)
        self.mod._fill_missing_chart_levels([chart])
        self.assertEqual(chart.ds, 13.5)
        self.assertIsInstance(chart.ds, float)
        self.assertEqual(self.mod.log.warnings, [])

    def test_local_valid_ds_still_wins(self) -> None:
        # 本地有有效定数时保持既有行为：以本地为准
        self.local_music = SimpleNamespace(id=11817, ds=[0.0, 0.0, 0.0, 13.2, 0.0])
        chart = self._chart(ds=13.5)
        self.mod._fill_missing_chart_levels([chart])
        self.assertEqual(chart.ds, 13.2)
        self.assertIsInstance(chart.ds, float)

    def test_local_string_ds_is_coerced(self) -> None:
        # 本地曲库偶尔给字符串：不能把 str 直接塞进 ChartInfo.ds
        self.local_music = SimpleNamespace(id=11817, ds=[0, 0, 0, "13.2", 0])
        chart = self._chart(ds=13.5)
        self.mod._fill_missing_chart_levels([chart])
        self.assertEqual(chart.ds, 13.2)
        self.assertNotIsInstance(chart.ds, str)

    def test_dx_offset_fallback_still_applies(self) -> None:
        # 本地按原 ID 查不到时，DX 仍走 song_id + 10000 兜底
        self.dx_music = SimpleNamespace(id=12000, ds=[0.0, 0.0, 0.0, 14.0, 0.0])
        chart = self._chart(ds=0, song_id=2000, chart_type="dx")
        self.mod._fill_missing_chart_levels([chart])
        self.assertEqual(chart.song_id, 12000)
        self.assertEqual(chart.ds, 14.0)
        self.assertEqual(self.mod.log.warnings, [])

    def test_warning_only_when_both_sources_miss(self) -> None:
        chart = self._chart(ds=0, song_id=2000, chart_type="dx")
        self.mod._fill_missing_chart_levels([chart])
        self.assertEqual(chart.ds, 0.0)
        self.assertEqual(len(self.mod.log.warnings), 1)
        self.assertIn("未找到定数", self.mod.log.warnings[0])
        self.assertIn("song_id=2000", self.mod.log.warnings[0])


class MusicPictureFallbackTest(unittest.TestCase):
    """缺陷 2：水鱼 DX ID 超过旧上限 11000 后仍要回落到落雪原生曲绘。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_image_module()

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.coverdir = Path(self.tmp.name)
        patcher = mock.patch.object(self.mod, "coverdir", self.coverdir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.mod._corrupted_cover_ids.clear()

    def _cover(self, name: str) -> Path:
        """在临时 coverdir 写一张真实 PNG（不依赖仓库里的 static/cover）。"""
        path = self.coverdir / name
        Image.new("RGB", (4, 4), (10, 20, 30)).save(path, format="PNG")
        return path

    def test_dx_id_above_old_cap_resolves_lxns_cover(self) -> None:
        target = self._cover("1817.png")
        self.assertEqual(self.mod.music_picture(11817), target)
        self.assertNotEqual(self.mod.music_picture(11817), self.coverdir / "0.png")

    def test_sd_id_tries_fish_dx_cover(self) -> None:
        target = self._cover("10008.png")
        self.assertEqual(self.mod.music_picture(8), target)

    def test_fish_dx_id_tries_lxns_cover(self) -> None:
        target = self._cover("8.png")
        self.assertEqual(self.mod.music_picture(10008), target)

    def test_banquet_id_still_resolves_lxns_cover(self) -> None:
        target = self._cover("8.png")
        self.assertEqual(self.mod.music_picture(100008), target)

    def test_placeholder_fallback_unchanged(self) -> None:
        target = self._cover("0.png")
        self.assertEqual(self.mod.music_picture(11817), target)

    def test_no_cover_returns_placeholder_path(self) -> None:
        self.assertEqual(self.mod.music_picture(11817), self.coverdir / "0.png")


if __name__ == "__main__":
    unittest.main(verbosity=2)
