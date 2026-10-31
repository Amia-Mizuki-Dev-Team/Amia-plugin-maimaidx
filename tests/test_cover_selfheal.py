"""曲绘自愈回归测试（无 nonebot / 无网络环境可运行）。

钉四件事：

1. ``.cover_sync_done`` 只是附带信息：曲库更新后文件数量早已超过 marker，
   旧实现据此短路，新曲永远补不上（B50 掉占位图）。补缺必须以 musicDB 的
   曲目键为准逐键校验。
2. ``_corrupted_cover_ids`` 不能永久拉黑：重新下载/校验到有效文件后必须解除，
   否则有效曲绘会在下次读取时被无条件删除。
3. 水鱼封面 URL 的归一化是 ``>= 10000 一律 % 10000``（旧实现只减 10001~11000，
   DX id 11001..99999 全拼错；宴会场也走同一规则，落到父曲那张图）。
4. B50 绘制前按需补下**有界**（并发 ≤5 / 总超时 15s），读不到曲绘时用内存
   灰色占位兜底，整张图不能因为缺图失败。
5. 宴会场（id >= 100000）与普通 id 走**同一条**落雪 ``% 10000`` 路径：宴会曲目
   在上游没有专属封面，``% 10000`` 命中的就是父曲曲绘（实测 41/41 均 200，
   100851 → jacket/851.png）；水鱼只在落雪失败时作最后兜底。
6. 缺图判定不能经过 ``music_picture`` 的回退：110114 会因 10114.png 存在而被当成
   健康；普通 SD/DX 仍按 ``{id}``/``{id±10000}`` 回退集合判断。
7. 落盘必须是临时文件 + 魔数校验 + ``os.replace``：直接写在中断/并发时留下的
   半截 PNG 头 16 字节合法，会被后续校验永久当健康文件。
8. marker 只作附带信息（``v2:<文件数>``），**不再**按「%10000 写脏」删宴会场
   曲绘——那个前提是错的，会误删正确的父曲曲绘再重下 404；``force_redownload``
   必须绕过「已有有效文件」与负缓存两处早退。
9. 落雪 + 水鱼都 404 的 id 写持久化负缓存（TTL 7 天）：窗口内不再发请求，过期
   自动重试；写入必须原子（半截 JSON 等于负缓存失效）。

手法沿用 ``tests/test_b50_render.py``：``image.py`` / ``lib_music_db.py`` 的
``..config`` 依赖链在单测环境 import 不动，所以用别名包 + 配置替身加载生产
源码本体；``maimaidx_best_50.py`` 依赖 nonebot，只按名字 exec 相关定义。

运行：``python -m unittest discover -s tests -p "test_cover_selfheal.py" -v``
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import io
import json
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Union
from unittest import mock

from PIL import Image

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
BEST50_FILE = PLUGIN_ROOT / "libraries" / "maimaidx_best_50.py"
MUSIC_FILE = PLUGIN_ROOT / "libraries" / "maimaidx_music.py"
_PKG = "maidx_cover_selfheal_under_test"

_GRAY = (72, 72, 72, 255)


class _LogStub:
    def __init__(self) -> None:
        self.warnings: List[str] = []
        self.infos: List[str] = []

    def debug(self, msg: str, *a: Any, **k: Any) -> None:
        pass

    def info(self, msg: str, *a: Any, **k: Any) -> None:
        self.infos.append(str(msg))

    def success(self, msg: str, *a: Any, **k: Any) -> None:
        pass

    def warning(self, msg: str, *a: Any, **k: Any) -> None:
        self.warnings.append(str(msg))

    def error(self, msg: str, *a: Any, **k: Any) -> None:
        pass


def _png_bytes(color=(10, 20, 30), size=(4, 4)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


class _FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        pass


def _load_modules():
    """用别名包加载 ``libraries.image`` / ``libraries.lib_music_db``。"""
    for name in list(sys.modules):
        if name == _PKG or name.startswith(_PKG + "."):
            sys.modules.pop(name, None)
    try:  # 生产依赖；单测环境未安装时给个不会被调用到的替身
        import curl_cffi  # noqa: F401
    except ImportError:
        stub = types.ModuleType("curl_cffi")
        stub.requests = SimpleNamespace(get=None, AsyncSession=None)
        sys.modules["curl_cffi"] = stub

    pkg = types.ModuleType(_PKG)
    pkg.__path__ = [str(PLUGIN_ROOT)]
    sys.modules[_PKG] = pkg
    libraries = types.ModuleType(f"{_PKG}.libraries")
    libraries.__path__ = [str(PLUGIN_ROOT / "libraries")]
    sys.modules[f"{_PKG}.libraries"] = libraries
    config = types.ModuleType(f"{_PKG}.config")
    config.Path = Path
    config.log = _LogStub()
    config.coverdir = Path("__unset__")
    # lib_music_db 在模块导入期就取 `..config.static`（负缓存落盘根目录）
    config.static = Path("__unset_static__")
    config.SHANGGUMONO = ""
    sys.modules[f"{_PKG}.config"] = config
    image = importlib.import_module(f"{_PKG}.libraries.image")
    lib = importlib.import_module(f"{_PKG}.libraries.lib_music_db")
    return image, lib


class _CoverDirMixin:
    """每个用例一个临时 coverdir；``image.coverdir`` 指向它。"""

    image_mod = None

    def setUp(self) -> None:  # noqa: D401 - unittest 钩子
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.coverdir = Path(self.tmp.name)
        patcher = mock.patch.object(self.image_mod, "coverdir", self.coverdir)
        patcher.start()
        self.addCleanup(patcher.stop)
        # 负缓存是持久化文件：测试一律指向临时目录，绝不写进插件的 static/
        lib = getattr(self, "lib", None)
        if lib is not None:
            cache_patcher = mock.patch.object(
                lib, "_cover_negative_cache_path", self._negative_cache_path
            )
            cache_patcher.start()
            self.addCleanup(cache_patcher.stop)
        self.image_mod._corrupted_cover_ids.clear()

    def _negative_cache_path(self) -> Path:
        return self.coverdir / "cover_negative_cache.json"

    def write_cover(self, name: str, color=(10, 20, 30)) -> Path:
        path = self.coverdir / name
        path.write_bytes(_png_bytes(color))
        return path


class CoverSyncMarkerTest(_CoverDirMixin, unittest.TestCase):
    """缺陷 1：marker 只能当附带信息，不能阻止按曲目键补缺。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.image_mod, cls.lib = _load_modules()

    def _set_music_db(self, ids) -> None:
        cache = self.lib.music_db_cache
        cache._cache = {str(i): {"name": f"song-{i}", "version": 20000} for i in ids}
        cache._loaded = True

    def tearDown(self) -> None:
        self.lib.music_db_cache._cache = {}
        self.lib.music_db_cache._loaded = False

    def test_marker_does_not_block_missing_cover(self) -> None:
        # 现场：2301 张图、marker=1328 —— 「文件数 >= marker」正是旧短路的触发条件
        self._set_music_db([8, 1817, 11817])
        self.write_cover("8.png")
        self.write_cover("0.png")
        (self.coverdir / ".cover_sync_done").write_text("1328")

        calls = []

        def fake_download(download_id, save_id, cover_dir, headers, force=False, status=None):
            calls.append((download_id, save_id))
            (Path(cover_dir) / f"{save_id}.png").write_bytes(_png_bytes())
            return True

        with mock.patch.object(self.lib, "_download_one_cover", fake_download):
            added = asyncio.run(self.lib.download_all_covers(self.coverdir))

        self.assertEqual(added, 1)
        # 只补缺的两首（1817 / 11817 共用同一张图），已有 8.png 不再下载
        self.assertEqual(calls, [(1817, "__tmp_1817")])
        self.assertEqual(self.image_mod.music_picture(1817), self.coverdir / "1817.png")
        self.assertEqual(self.image_mod.music_picture(11817), self.coverdir / "11817.png")
        # marker 仍被写入（v2:<文件数>），但只是迁移/附带信息
        self.assertEqual((self.coverdir / ".cover_sync_done").read_text(), "v2:3")

    def test_all_covers_present_skips_download(self) -> None:
        self._set_music_db([8, 1817])
        self.write_cover("8.png")
        self.write_cover("1817.png")
        (self.coverdir / ".cover_sync_done").write_text("999")

        def boom(*args, **kwargs):  # pragma: no cover - 被调用即失败
            raise AssertionError("曲绘齐全时不应下载")

        with mock.patch.object(self.lib, "_download_one_cover", boom):
            added = asyncio.run(self.lib.download_all_covers(self.coverdir))

        self.assertEqual(added, 0)
        self.assertEqual((self.coverdir / ".cover_sync_done").read_text(), "v2:2")

    def test_invalid_download_content_is_not_copied(self) -> None:
        self._set_music_db([1817])
        self.write_cover("0.png")

        def fake_download(download_id, save_id, cover_dir, headers, force=False, status=None):
            # 200 但是反爬 HTML：不能当曲绘复制给曲目键
            (Path(cover_dir) / f"{save_id}.png").write_bytes(b"<html>blocked</html>")
            return True

        def fake_fish(*args, **kwargs):
            return False  # 落雪内容不可用 → 水鱼兜底也失败（不该落空文件）

        with mock.patch.object(self.lib, "_download_one_cover", fake_download), \
                mock.patch.object(self.lib, "_download_one_cover_fish", fake_fish):
            added = asyncio.run(self.lib.download_all_covers(self.coverdir))

        self.assertEqual(added, 0)
        self.assertFalse((self.coverdir / "1817.png").exists())


class CorruptedCoverBlacklistTest(_CoverDirMixin, unittest.TestCase):
    """缺陷 2：损坏记录不能永久拉黑有效文件。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.image_mod, cls.lib = _load_modules()

    def test_blacklisted_but_valid_file_is_kept(self) -> None:
        cover = self.write_cover("1817.png")
        self.image_mod._corrupted_cover_ids.add("1817")

        self.assertEqual(self.image_mod.music_picture(1817), cover)
        self.assertTrue(cover.exists())
        self.assertNotIn("1817", self.image_mod._corrupted_cover_ids)

    def test_corrupt_file_is_deleted_and_listed(self) -> None:
        self.write_cover("0.png")
        broken = self.coverdir / "1818.png"
        broken.write_bytes(b"<html>not an image at all</html>")

        self.assertEqual(self.image_mod.music_picture(1818).name, "0.png")
        self.assertFalse(broken.exists())
        self.assertIn("1818", self.image_mod._corrupted_cover_ids)

    def test_successful_download_clears_blacklist(self) -> None:
        self.image_mod._corrupted_cover_ids.add("1819")
        fake = SimpleNamespace(get=lambda *a, **k: _FakeResponse(_png_bytes()))

        with mock.patch.object(self.lib, "cffi_requests", fake):
            ok = self.lib._download_one_cover(1819, "1819", self.coverdir, {})

        self.assertTrue(ok)
        self.assertNotIn("1819", self.image_mod._corrupted_cover_ids)
        self.assertEqual(self.image_mod.music_picture(1819), self.coverdir / "1819.png")


class FishCoverUrlTest(unittest.TestCase):
    """缺陷 3：水鱼曲绘 URL 归一化必须是「>= 10000 一律 % 10000」。"""

    @classmethod
    def setUpClass(cls) -> None:
        _, cls.lib = _load_modules()

    def test_sd_id_is_zero_padded(self) -> None:
        self.assertEqual(self.lib.get_fish_cover_url(8).rsplit("/", 1)[-1], "00008.png")

    def test_fish_dx_id_subtracts_10000(self) -> None:
        self.assertEqual(self.lib.get_fish_cover_url(10008).rsplit("/", 1)[-1], "00008.png")

    def test_dx_id_above_old_cap_subtracts_10000(self) -> None:
        # 旧实现只处理 10001..11000，11817 会拼成不存在的 11817.png
        self.assertEqual(self.lib.get_fish_cover_url(11817).rsplit("/", 1)[-1], "01817.png")

    def test_banquet_id_falls_back_to_parent_cover(self) -> None:
        # 宴会 id 在上游没有专属封面：00121.png / 00851.png 就是父曲那张图，
        # 保持 6 位原 ID 只会拼出必然 404 的地址（修复前的水鱼兜底就是这样）。
        self.assertEqual(self.lib.get_fish_cover_url(110121).rsplit("/", 1)[-1], "00121.png")
        self.assertEqual(self.lib.get_fish_cover_url(100851).rsplit("/", 1)[-1], "00851.png")

    def test_banquet_and_parent_share_fish_cover(self) -> None:
        # 同一父曲的宴会 id 必须指向同一张图——这是修复点，不是缺陷
        self.assertEqual(self.lib.fish_cover_id(110121), self.lib.fish_cover_id(121))
        self.assertEqual(self.lib.fish_cover_id(100851), 851)


class CoverNegativeCacheTest(_CoverDirMixin, unittest.TestCase):
    """缺陷 8/9：宴会 id 统一走落雪 %10000；双源 404 记负缓存（TTL 7 天）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.image_mod, cls.lib = _load_modules()

    def tearDown(self) -> None:
        self.lib.music_db_cache._cache = {}
        self.lib.music_db_cache._loaded = False

    def _set_music_db(self, ids) -> None:
        cache = self.lib.music_db_cache
        cache._cache = {str(i): {"name": f"song-{i}", "version": 20000} for i in ids}
        cache._loaded = True

    def _cache_file(self) -> Path:
        return self.coverdir / "cover_negative_cache.json"

    # ---- ① 宴会 id 100851 解析出落雪 jacket/851.png ----
    def test_banquet_id_resolves_to_parent_lxns_url(self) -> None:
        self._set_music_db([100851])
        urls: List[str] = []

        def fake_get(url, *args, **kwargs):
            urls.append(url)
            return _FakeResponse(_png_bytes((3, 4, 5)))

        with mock.patch.object(self.lib, "cffi_requests", SimpleNamespace(get=fake_get)):
            added = asyncio.run(self.lib.download_all_covers(self.coverdir))

        self.assertEqual(added, 1)
        self.assertEqual(urls, ["https://assets2.lxns.net/maimai/jacket/851.png"])
        self.assertTrue((self.coverdir / "100851.png").is_file())
        self.assertFalse((self.coverdir / "851.png").exists())  # 只按原始键名落盘

    # ---- ② 负缓存命中时不再发起请求 ----
    def test_fresh_negative_cache_suppresses_requests(self) -> None:
        self._set_music_db([100851])
        self._cache_file().write_text(
            json.dumps({"100851": time.time()}), encoding="utf-8"
        )

        def boom(*args, **kwargs):  # pragma: no cover - 命中即不该被调用
            raise AssertionError("负缓存命中时不应发请求")

        with mock.patch.object(self.lib, "_download_one_cover", boom), \
                mock.patch.object(self.lib, "_download_one_cover_fish", boom):
            added = asyncio.run(self.lib.download_all_covers(self.coverdir))

        self.assertEqual(added, 0)
        self.assertFalse((self.coverdir / "100851.png").exists())

    def test_ensure_covers_skips_negative_cached_id(self) -> None:
        # B50 出图前的按需补下同样受负缓存约束（连 downloader 都不应被调用）
        self._cache_file().write_text(
            json.dumps({"100851": time.time()}), encoding="utf-8"
        )
        called: List[int] = []

        async def downloader(sid: int) -> bool:
            called.append(sid)
            return True

        count = asyncio.run(
            self.lib.ensure_covers([100851], self.coverdir, timeout=1, downloader=downloader)
        )
        self.assertEqual(count, 0)
        self.assertEqual(called, [])

    # ---- ③ 过期条目会重试 ----
    def test_expired_negative_entry_is_retried(self) -> None:
        self._set_music_db([100851])
        stale = time.time() - (8 * 24 * 60 * 60)  # 超过 7 天 TTL
        self._cache_file().write_text(
            json.dumps({"100851": stale}), encoding="utf-8"
        )
        calls: List[int] = []

        def fake_lxns(download_id, save_id, cover_dir, headers, force=False, status=None):
            calls.append(int(download_id))
            (Path(cover_dir) / f"{save_id}.png").write_bytes(_png_bytes())
            return True

        with mock.patch.object(self.lib, "_download_one_cover", fake_lxns):
            added = asyncio.run(self.lib.download_all_covers(self.coverdir))

        self.assertEqual(calls, [851], "过期条目必须重试")
        self.assertEqual(added, 1)

    # ---- 双源 404 → 写负缓存（顺带清掉过期条目） ----
    def test_both_sources_404_writes_negative_cache(self) -> None:
        self._set_music_db([100851])
        stale = time.time() - (8 * 24 * 60 * 60)
        self._cache_file().write_text(
            json.dumps({"123456": stale}), encoding="utf-8"
        )

        class _NotFound:
            status_code = 404
            content = b""

            @staticmethod
            def raise_for_status() -> None:
                raise RuntimeError("404 Client Error")

        fake = SimpleNamespace(get=lambda *a, **k: _NotFound())
        with mock.patch.object(self.lib, "cffi_requests", fake):
            added = asyncio.run(self.lib.download_all_covers(self.coverdir))

        self.assertEqual(added, 0)
        data = json.loads(self._cache_file().read_text(encoding="utf-8"))
        self.assertIn("100851", data)
        self.assertIsInstance(data["100851"], float)
        self.assertNotIn("123456", data, "过期条目在写回时应被清掉")

    # ---- 落盘原子性：半截 JSON 等于负缓存失效 ----
    def test_negative_cache_write_is_atomic(self) -> None:
        target = self._cache_file()
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            self.lib._save_negative_cache({"100851": time.time()}, target)

        self.assertFalse(target.exists())
        self.assertEqual(list(self.coverdir.iterdir()), [])


class _CoverPrefetchBoundTest(_CoverDirMixin, unittest.TestCase):
    """缺陷 4（补下侧）：有界并发 + 总超时保留已完成结果。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.image_mod, cls.lib = _load_modules()

    def test_timeout_keeps_finished_downloads(self) -> None:
        async def scenario():
            async def downloader(sid):
                if sid == 1:
                    return True
                await asyncio.sleep(5)
                return True

            started = time.monotonic()
            count = await self.lib.ensure_covers(
                [1, 2], self.coverdir, concurrency=2, timeout=0.1, downloader=downloader
            )
            return count, time.monotonic() - started

        count, elapsed = asyncio.run(scenario())
        self.assertEqual(count, 1)  # 已完成的 1 不能被超时的 2 一起丢掉
        self.assertLess(elapsed, 2.0)

    def test_concurrency_is_capped(self) -> None:
        async def scenario():
            active = 0
            peak = 0

            async def downloader(sid):
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.02)
                active -= 1
                return True

            count = await self.lib.ensure_covers(
                range(1, 9), self.coverdir, concurrency=2, timeout=5, downloader=downloader
            )
            return count, peak

        count, peak = asyncio.run(scenario())
        self.assertEqual(count, 8)
        self.assertLessEqual(peak, 2)

    def test_download_exception_is_ignored(self) -> None:
        async def downloader(sid):
            raise RuntimeError("network down")

        count = asyncio.run(
            self.lib.ensure_covers([1, 2], self.coverdir, timeout=1, downloader=downloader)
        )
        self.assertEqual(count, 0)

    def test_present_covers_are_not_downloaded(self) -> None:
        self.write_cover("1.png")
        self.write_cover("2.png")
        called = []

        async def downloader(sid):  # pragma: no cover - 不应被调用
            called.append(sid)
            return True

        count = asyncio.run(
            self.lib.ensure_covers([1, 2], self.coverdir, timeout=1, downloader=downloader)
        )
        self.assertEqual(count, 0)
        self.assertEqual(called, [])


def _pick_defs(path: Path, names: set, extra_globals: dict, module_name: str):
    """按名字从生产源码挑出定义，exec 进受控命名空间（同 test_b50_render.py）。"""
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


def _pick_method(path: Path, name: str, extra_globals: dict, module_name: str):
    """挑出**类方法**本体 exec 进受控命名空间（``_pick_defs`` 只看模块顶层）。

    ``__package__`` 必须指向别名包的 ``libraries``：方法体内有
    ``from ..libraries.image`` / ``from .lib_music_db`` 这样的相对导入。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
        ),
        None,
    )
    if node is None:
        raise AssertionError(f"{path.name} 缺少待测方法: {name}")

    module = types.ModuleType(module_name)
    module.__dict__.update(extra_globals)
    module.__dict__["__name__"] = module_name
    module.__dict__["__package__"] = module_name.rsplit(".", 1)[0]
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), module.__dict__)
    return module


class CoverRenderPlaceholderTest(unittest.TestCase):
    """缺陷 4（绘制侧）：读不到曲绘时用内存灰色占位，整张图不能失败。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.log = _LogStub()
        cls.mod = _pick_defs(
            BEST50_FILE,
            {"_load_cover_image", "_COVER_SIZE", "_COVER_PLACEHOLDER_RGBA"},
            {"Any": Any, "Image": Image, "Union": Union, "log": cls.log},
            "_cover_renderer_under_test",
        )

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.coverdir = Path(self.tmp.name)
        self.target = self.coverdir / "1817.png"
        self.mod.music_picture = lambda song_id: self.target  # type: ignore[attr-defined]

    def test_missing_cover_falls_back_to_memory_placeholder(self) -> None:
        image = self.mod._load_cover_image(1817)
        self.assertEqual(image.size, (75, 75))
        self.assertEqual(image.mode, "RGBA")
        self.assertEqual(image.getpixel((0, 0)), _GRAY)
        self.assertTrue(self.log.warnings)

    def test_broken_cover_file_falls_back_to_memory_placeholder(self) -> None:
        self.target.write_bytes(b"<html>not an image at all</html>")
        image = self.mod._load_cover_image(1817)
        self.assertEqual(image.size, (75, 75))
        self.assertEqual(image.getpixel((0, 0)), _GRAY)

    def test_valid_cover_is_scaled_to_card_size(self) -> None:
        self.target.write_bytes(_png_bytes((10, 20, 30)))
        image = self.mod._load_cover_image(1817)
        self.assertEqual(image.size, (75, 75))
        self.assertEqual(image.mode, "RGBA")
        self.assertEqual(image.getpixel((0, 0)), (10, 20, 30, 255))


class DegradedFishFallbackTest(_CoverDirMixin, unittest.TestCase):
    """缺陷 3（降级路径）：按**原始 id** 分键下载/落盘，各曲目互不覆盖。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.image_mod, cls.lib = _load_modules()
        cls.log = _LogStub()
        cls.mod = _pick_method(
            MUSIC_FILE,
            "download_missing_covers",
            {
                "Path": Path,
                "log": cls.log,
                "coverdir": Path("__unset__"),
                "music_db_path": Path("__no_such_music_db__.json"),
                "music_db_cache": SimpleNamespace(load=None),
                "download_all_covers": None,
                "maiconfig": SimpleNamespace(lxnstoken=""),
            },
            f"{_PKG}.libraries.maimaidx_music",
        )

    def setUp(self) -> None:
        super().setUp()
        self.mod.coverdir = self.coverdir

    def test_degraded_path_keys_by_raw_id_without_overwrite(self) -> None:
        calls: List[int] = []

        def fake_fish(download_id, save_id, cover_dir, force=False):
            calls.append(int(download_id))
            # 内容直接写 ID，方便断言两张宴会曲绘没有互相覆盖
            (Path(cover_dir) / f"{save_id}.png").write_bytes(str(download_id).encode())
            return True

        songs = [{"id": 8}, {"id": 10008}, {"id": 110114}, {"id": 100114}]
        with mock.patch.object(self.lib, "_download_one_cover_fish", fake_fish):
            asyncio.run(self.mod.download_missing_covers(SimpleNamespace(total_list=songs)))

        # 传给下载器的必须是原始 ID：旧实现会把 110114 / 100114 都压成 114
        self.assertEqual(calls, [8, 10008, 110114, 100114])
        self.assertEqual((self.coverdir / "10008.png").read_bytes(), b"10008")
        self.assertEqual((self.coverdir / "110114.png").read_bytes(), b"110114")
        self.assertEqual((self.coverdir / "100114.png").read_bytes(), b"100114")


class BanquetCoverPrecisionTest(_CoverDirMixin, unittest.TestCase):
    """缺陷 5/6：宴会场必须用精确 ID 补下与判缺；缺陷 7：落盘必须原子。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.image_mod, cls.lib = _load_modules()

    def tearDown(self) -> None:
        self.lib.music_db_cache._cache = {}
        self.lib.music_db_cache._loaded = False

    def _set_music_db(self, ids) -> None:
        cache = self.lib.music_db_cache
        cache._cache = {str(i): {"name": f"song-{i}", "version": 20000} for i in ids}
        cache._loaded = True

    # ---- 按需补下：宴会 id 同样走落雪 %10000（父曲曲绘），不再必然 404 ----
    def test_ensure_covers_banquet_uses_parent_cover(self) -> None:
        lxns_calls: List[Any] = []
        fish_calls: List[Any] = []

        def fake_lxns(*args, **kwargs):
            lxns_calls.append((int(args[0]), args[1]))
            (Path(args[2]) / f"{args[1]}.png").write_bytes(_png_bytes())
            return True

        def fake_fish(*args, **kwargs):  # pragma: no cover - 落雪成功就不该兜底
            fish_calls.append(args)
            return False

        async def scenario():
            with mock.patch.object(self.lib, "_download_one_cover", fake_lxns), \
                    mock.patch.object(self.lib, "_download_one_cover_fish", fake_fish):
                return await self.lib.ensure_covers([100851], self.coverdir, timeout=5)

        count = asyncio.run(scenario())
        self.assertEqual(count, 1)
        # 100851 % 10000 = 851 → 落雪 jacket/851.png（实测 200，父曲曲绘）
        self.assertEqual(lxns_calls, [(851, "100851")])
        self.assertEqual(fish_calls, [])
        self.assertTrue((self.coverdir / "100851.png").is_file())
        self.assertFalse((self.coverdir / "851.png").exists())

    # ---- 全量补缺：每个宴会 id 取自己的父曲图，按原始键名落盘 ----
    def test_download_all_covers_banquet_uses_parent_covers(self) -> None:
        self._set_music_db([110121, 100851])
        png_121 = _png_bytes((121, 0, 0))
        png_851 = _png_bytes((0, 123, 0))
        lxns_calls: List[Any] = []

        def fake_lxns(download_id, save_id, cover_dir, headers, force=False, status=None):
            lxns_calls.append((int(download_id), save_id))
            payload = png_121 if int(download_id) == 121 else png_851
            (Path(cover_dir) / f"{save_id}.png").write_bytes(payload)
            return True

        def fake_fish(*args, **kwargs):  # pragma: no cover
            raise AssertionError("落雪成功时不应再走水鱼")

        with mock.patch.object(self.lib, "_download_one_cover", fake_lxns), \
                mock.patch.object(self.lib, "_download_one_cover_fish", fake_fish):
            added = asyncio.run(self.lib.download_all_covers(self.coverdir))

        self.assertEqual(added, 2)
        self.assertEqual(lxns_calls, [(121, "__tmp_121"), (851, "__tmp_851")])
        self.assertEqual((self.coverdir / "110121.png").read_bytes(), png_121)
        self.assertEqual((self.coverdir / "100851.png").read_bytes(), png_851)
        self.assertFalse((self.coverdir / "121.png").exists())  # 只按原始键名落盘

    # ---- 缺图判定：不吃 music_picture 的回退结果 ----
    def test_needs_download_banquet_ignores_alias_file(self) -> None:
        self.write_cover("10114.png")  # music_picture 对 110114 的回退目标
        self.assertEqual(self.image_mod.music_picture(110114), self.coverdir / "10114.png")
        self.assertTrue(self.lib._cover_needs_download(110114))

        self.write_cover("110114.png")
        self.assertFalse(self.lib._cover_needs_download(110114))

    def test_needs_download_keeps_sd_dx_fallback_set(self) -> None:
        # 普通 SD/DX 仍按 {id}/{id±10000} 回退集合判断，不能误判缺图反复下载
        self.write_cover("8.png")
        self.assertFalse(self.lib._cover_needs_download(10008))
        self.assertFalse(self.lib._cover_needs_download(8))
        self.assertTrue(self.lib._cover_needs_download(1817))

    def test_download_all_covers_refills_banquet_despite_alias(self) -> None:
        # 10114.png 让 music_picture 有图可回退，但 110114.png 仍缺 → 补自己的键
        self._set_music_db([110114])
        self.write_cover("10114.png")
        lxns_calls: List[int] = []

        def fake_lxns(download_id, save_id, cover_dir, headers, force=False, status=None):
            lxns_calls.append(int(download_id))
            (Path(cover_dir) / f"{save_id}.png").write_bytes(_png_bytes((9, 9, 9)))
            return True

        with mock.patch.object(self.lib, "_download_one_cover", fake_lxns):
            added = asyncio.run(self.lib.download_all_covers(self.coverdir))

        self.assertEqual(added, 1)
        self.assertEqual(lxns_calls, [114])  # jacket/114.png = 110114 的父曲曲绘
        self.assertTrue((self.coverdir / "110114.png").is_file())

    # ---- 落盘原子性 ----
    def test_atomic_write_failure_leaves_no_final_or_temp_file(self) -> None:
        fake = SimpleNamespace(get=lambda *a, **k: _FakeResponse(_png_bytes()))
        with mock.patch.object(self.lib, "cffi_requests", fake), \
                mock.patch("os.replace", side_effect=OSError("disk full")):
            ok = self.lib._download_one_cover(1819, "1819", self.coverdir, {})

        self.assertFalse(ok)
        self.assertFalse((self.coverdir / "1819.png").exists())
        leftovers = sorted(p.name for p in self.coverdir.iterdir() if "1819" in p.name)
        self.assertEqual(leftovers, [])

    def test_atomic_write_replaces_truncated_file(self) -> None:
        target = self.coverdir / "1819.png"
        target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x01" * 8)  # 半截 PNG：头合法
        full = _png_bytes((1, 2, 3))
        fake = SimpleNamespace(get=lambda *a, **k: _FakeResponse(full))

        with mock.patch.object(self.lib, "cffi_requests", fake):
            ok = self.lib._download_one_cover(1819, "1819", self.coverdir, {})

        self.assertTrue(ok)
        self.assertEqual(target.read_bytes(), full)
        self.assertTrue(self.image_mod.is_valid_image(target.read_bytes()[:16]))

    def test_atomic_write_rejects_non_image_content(self) -> None:
        fake = SimpleNamespace(get=lambda *a, **k: _FakeResponse(b"<html>" + b"x" * 32))
        with mock.patch.object(self.lib, "cffi_requests", fake):
            ok = self.lib._download_one_cover(1820, "1820", self.coverdir, {})

        self.assertFalse(ok)
        self.assertFalse((self.coverdir / "1820.png").exists())
        leftovers = sorted(p.name for p in self.coverdir.iterdir() if "1820" in p.name)
        self.assertEqual(leftovers, [])


class CoverMarkerNoPurgeTest(_CoverDirMixin, unittest.TestCase):
    """复审回归：marker 不是迁移判据，旧的「%10000 写脏」清理必须彻底移除。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.image_mod, cls.lib = _load_modules()

    def tearDown(self) -> None:
        self.lib.music_db_cache._cache = {}
        self.lib.music_db_cache._loaded = False

    def _set_music_db(self, ids) -> None:
        cache = self.lib.music_db_cache
        cache._cache = {str(i): {"name": f"song-{i}", "version": 20000} for i in ids}
        cache._loaded = True

    def test_stale_marker_keeps_parent_cover(self) -> None:
        # 旧版把 110121.png 当「%10000 写脏」删掉，再按 6 位 id 重下 404。
        # 它就是 jacket/121.png 的合法副本 —— 必须原地保留，且一个请求都不发。
        self._set_music_db([8, 110121])
        self.write_cover("8.png")
        kept = self.write_cover("110121.png", (200, 0, 0))
        before = kept.read_bytes()
        (self.coverdir / ".cover_sync_done").write_text("1328")  # 旧格式 marker

        def boom(*args, **kwargs):  # pragma: no cover - 曲绘齐全就不该下载
            raise AssertionError("已有有效曲绘时不应重下（更不能先删）")

        with mock.patch.object(self.lib, "_download_one_cover", boom), \
                mock.patch.object(self.lib, "_download_one_cover_fish", boom):
            added = asyncio.run(self.lib.download_all_covers(self.coverdir))

        self.assertEqual(added, 0)
        self.assertTrue(kept.is_file())
        self.assertEqual(kept.read_bytes(), before)  # 没被删、也没被重写
        self.assertTrue((self.coverdir / "8.png").exists())
        # marker 照常升级成 v2（只是附带信息，不代表清过文件）
        self.assertEqual((self.coverdir / ".cover_sync_done").read_text(), "v2:2")

    def test_current_marker_keeps_banquet_cover(self) -> None:
        self._set_music_db([110114])
        self.write_cover("110114.png")
        (self.coverdir / ".cover_sync_done").write_text("v2:1")

        def boom(*args, **kwargs):  # pragma: no cover - 已迁移过就不该重下
            raise AssertionError("marker 已是 v2，不应重下宴会场曲绘")

        with mock.patch.object(self.lib, "_download_one_cover_fish", boom):
            added = asyncio.run(self.lib.download_all_covers(self.coverdir))

        self.assertEqual(added, 0)
        self.assertTrue((self.coverdir / "110114.png").exists())

    def test_temp_file_removed_when_download_fails(self) -> None:
        self._set_music_db([1817])

        def fake_dl(download_id, save_id, cover_dir, headers, force=False, status=None):
            (Path(cover_dir) / f"{save_id}.png").write_bytes(b"<html>blocked</html>")
            return False

        with mock.patch.object(self.lib, "_download_one_cover", fake_dl), \
                mock.patch.object(self.lib, "_download_one_cover_fish", lambda *a, **k: False):
            added = asyncio.run(self.lib.download_all_covers(self.coverdir))

        self.assertEqual(added, 0)
        self.assertEqual(list(self.coverdir.glob("__tmp_*.png")), [])

    def test_temp_file_removed_when_write_raises(self) -> None:
        self._set_music_db([1817])

        def fake_dl(download_id, save_id, cover_dir, headers, force=False, status=None):
            (Path(cover_dir) / f"{save_id}.png").write_bytes(_png_bytes())
            return True

        with mock.patch.object(self.lib, "_download_one_cover", fake_dl), \
                mock.patch.object(self.lib, "_atomic_write_cover",
                                  side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                asyncio.run(self.lib.download_all_covers(self.coverdir))

        self.assertEqual(list(self.coverdir.glob("__tmp_*.png")), [])


class ForceRedownloadTest(_CoverDirMixin, unittest.TestCase):
    """复审：``force_redownload`` 必须绕过 ``_download_one_cover*`` 的已有文件早退。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.image_mod, cls.lib = _load_modules()

    def tearDown(self) -> None:
        self.lib.music_db_cache._cache = {}
        self.lib.music_db_cache._loaded = False

    def _set_music_db(self, ids) -> None:
        cache = self.lib.music_db_cache
        cache._cache = {str(i): {"name": f"song-{i}", "version": 20000} for i in ids}
        cache._loaded = True

    def _fake_existing_cover(self, name: str = "1819.png") -> Path:
        # 体积 >5000 且魔数合法 —— 正是「已有有效文件」早退分支的判定条件
        path = self.coverdir / name
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8000)
        return path

    def test_lxns_early_return_without_force(self) -> None:
        path = self._fake_existing_cover()
        before = path.read_bytes()
        fake = SimpleNamespace(get=lambda *a, **k: _FakeResponse(_png_bytes((1, 2, 3))))

        with mock.patch.object(self.lib, "cffi_requests", fake):
            ok = self.lib._download_one_cover(1819, "1819", self.coverdir, {})

        self.assertTrue(ok)
        self.assertEqual(path.read_bytes(), before)  # 早退：没走网络、没覆盖

    def test_lxns_force_bypasses_early_return(self) -> None:
        path = self._fake_existing_cover()
        new = _png_bytes((1, 2, 3))
        fake = SimpleNamespace(get=lambda *a, **k: _FakeResponse(new))

        with mock.patch.object(self.lib, "cffi_requests", fake):
            ok = self.lib._download_one_cover(1819, "1819", self.coverdir, {}, force=True)

        self.assertTrue(ok)
        self.assertEqual(path.read_bytes(), new)

    def test_fish_force_bypasses_early_return(self) -> None:
        path = self._fake_existing_cover()
        new = _png_bytes((4, 5, 6))
        fake = SimpleNamespace(get=lambda *a, **k: _FakeResponse(new))

        with mock.patch.object(self.lib, "cffi_requests", fake):
            ok = self.lib._download_one_cover_fish(1819, "1819", self.coverdir, force=True)

        self.assertTrue(ok)
        self.assertEqual(path.read_bytes(), new)

    def test_download_all_covers_forwards_force(self) -> None:
        self._set_music_db([110121])
        self.write_cover("110121.png")
        (self.coverdir / ".cover_sync_done").write_text("v2:1")
        lxns_calls: List[Any] = []

        def fake_lxns(download_id, save_id, cover_dir, headers, force=False, status=None):
            lxns_calls.append((int(download_id), bool(force)))
            (Path(cover_dir) / f"{save_id}.png").write_bytes(_png_bytes())
            return True

        with mock.patch.object(self.lib, "_download_one_cover", fake_lxns):
            added = asyncio.run(
                self.lib.download_all_covers(self.coverdir, force_redownload=True)
            )

        self.assertEqual(added, 1)
        # 强制重下走同一条落雪路径（110121 % 10000 = 121），force 必须透传
        self.assertEqual(lxns_calls, [(121, True)])


if __name__ == "__main__":
    unittest.main(verbosity=2)