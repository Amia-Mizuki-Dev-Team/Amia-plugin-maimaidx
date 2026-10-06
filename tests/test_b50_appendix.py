"""出图侧的 B50 附录契约与降级单测（libraries/maimaidx_best_50.py · P1b）。

钉三件事：

1. **绘制顺序 = 唯一真源**：``B50CardPosition`` 的顺序、桶、序号必须来自
   ``ScoreBaseImage.whiledraw`` 的实际绘制循环（5 列行优先，``x=16``、列距 276、
   ``num % 5`` 换行；``sd→"b35"`` / ``dx→"b15"``，语义依据
   ``libraries/maimaidx_merge.py:11-12``）。P0 实测依据：``song_id=1736
   《プリズム△▽リズム》`` 版本码 25504，两源都归上半区，而 coach 按 25500 阈值会
   判成 b15 —— 所以 coach 不重排，本文件把顺序钉在**生产 whiledraw 本体**上。
2. **constant 取回填之后的值**：落雪 payload 没有 ds，``generate()`` 里按本地曲库
   回填（原 ``best_50.py:367-381``）；ctx 必须在回填之后构造。
3. **降级纪律**：coach 缺席 / ``is_enabled()`` 关 / ``render_appendix`` 抛异常 /
   返回 None / 8s 超时 / 宽度不等于 ``ctx.width`` / 字节解不开 → **返回原图，
   一个像素都不差**，编码仍走本仓库的 ``image_to_base64``。

手法沿用 tests/test_b50_critique_guard.py 的 AST 路线：``maimaidx_best_50.py`` 里
``from ..config import *`` 会拉起 .env 与曲库依赖链，单测环境 import 不动，所以
**从生产源码里挑出相关定义** exec 进受控命名空间 —— 被测的是生产源码本体。
契约类型直接加载 ``../amia_core/b50_appendix.py`` 源码（运行时也是同一个模块）。

运行：python -m unittest discover -v   （在 tests/ 目录里）
"""

from __future__ import annotations

import ast
import asyncio
import base64
import importlib.util
import inspect
import io
import math
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Optional, Tuple, Union

import anyio
from PIL import Image, ImageChops

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from libraries.maimaidx_model import ChartInfo, Data, UserInfo  # noqa: E402

BEST50_FILE = PLUGIN_ROOT / "libraries" / "maimaidx_best_50.py"
CONTRACT_FILE = PLUGIN_ROOT.parent / "amia_core" / "b50_appendix.py"

CANVAS_SIZE = (1400, 1700)


def _load_contract():
    """按文件加载 amia_core 的契约模块（运行时被 import 的就是这一份）。"""
    spec = importlib.util.spec_from_file_location("_b50_contract_under_test", CONTRACT_FILE)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    # 契约里有 ``@dataclass(slots=True)``：dataclasses 要按 ``cls.__module__``
    # 回查 sys.modules，所以必须先登记再 exec。
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


contract = _load_contract()

# 要挑出来的生产定义（按名字，不按行号 —— 行号一改就废）
TOP_DEFS = frozenset({
    "B50_APPENDIX_PROVIDER",
    "_APPENDIX_TIMEOUT_SEC",
    "_APPENDIX_DEGRADE_NOTICE",
    "_APPENDIX_DISABLED_NOTICE",
    "_APPENDIX_ABSENT_NOTICE",
    "_APPENDIX_SEAM_BAND_PX",
    "_APPENDIX_SAMPLE_MAX_POINTS",
    "_mean_rgb_over",
    "_sample_background_palette",
    "_ctx_accepts",
    "_appendix_identity",
    "appendix_provider_available",
    "appendix_absent_notice",
    "_take_provider_notice",
    "_build_appendix_context",
    "_render_appendix_png",
    "_paste_appendix",
    "generate",
    "coloumWidth",
    "changeColumnWidth",
    "getCharWidth",
    "dxScore",
})
PICKED_METHODS = frozenset({
    ("ScoreBaseImage", "whiledraw"),
    ("DrawBest", "b50_cards"),
})


# ------------------------------------------------------------------
# 替身
# ------------------------------------------------------------------
class _LogStub:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def _record(self, level: str, msg: str) -> None:
        self.lines.append(f"{level}: {msg}")

    def debug(self, msg: str, *a, **k) -> None:
        self._record("debug", msg)

    def info(self, msg: str, *a, **k) -> None:
        self._record("info", msg)

    def warning(self, msg: str, *a, **k) -> None:
        self._record("warning", msg)

    def error(self, msg: str, *a, **k) -> None:
        self._record("error", msg)


class _SegmentFactory:
    """onebot v11 MessageSegment 替身：生产只用到 ``.image()``。"""

    def __init__(self, data: str) -> None:
        self.data = data

    @classmethod
    def image(cls, data: str) -> "_SegmentFactory":
        return cls(data)


def _encode(img: Image.Image) -> str:
    """与 generate 末尾 _encode 同口径（JPEG 90%，RGBA 铺白底）。"""
    target = img
    if target.mode == "RGBA":
        flat = Image.new("RGB", target.size, (255, 255, 255))
        flat.paste(target, mask=target.split()[3])
        target = flat
    buffer = io.BytesIO()
    target.save(buffer, format="JPEG", quality=90)
    return "base64://" + base64.b64encode(buffer.getvalue()).decode()


class _Encoder:
    """``image_to_base64`` 替身：顺带记录被编码的图像对象（证明没重建画布）。"""

    def __init__(self) -> None:
        self.images: list[Image.Image] = []

    def __call__(self, img: Image.Image, format: str = "PNG", **save_kwargs) -> str:
        self.images.append(img)
        return _encode(img)


class _ProxyImage:
    """``Image`` 替身：路径（UI 素材）→ 纯色小图；BytesIO → 真解码。"""

    def __init__(self, real) -> None:
        self._real = real

    def open(self, fp, *args, **kwargs):
        if isinstance(fp, (str, Path)):
            return self._real.new("RGBA", (75, 75), (9, 9, 9, 255))
        return self._real.open(fp, *args, **kwargs)

    def new(self, *args, **kwargs):
        return self._real.new(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _Recorder:
    """假画布：记录每次合成的坐标，供「绘制顺序」比对。"""

    def __init__(self) -> None:
        self.size = CANVAS_SIZE
        self.composites: list[tuple[tuple[int, int], Any]] = []

    def alpha_composite(self, img, dest=(0, 0)) -> None:
        self.composites.append((tuple(dest), img))


class _FakeCanvas:
    """假 self：只需 whiledraw / b50_cards 用到的属性。"""

    def __init__(self) -> None:
        self._im = _Recorder()
        self._diff = [f"diff{i}" for i in range(5)]
        self._tb = SimpleNamespace(draw=lambda *a, **k: None)
        self._sy = SimpleNamespace(draw=lambda *a, **k: None)
        self.t_color = ["t"] * 5
        self.id_color = ["i"] * 5
        self._draw_order: list[tuple[str, int, Any]] = []


# ------------------------------------------------------------------
# 源码装载
# ------------------------------------------------------------------
def _target_names(node: ast.stmt) -> list[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return [node.name]
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    return []


def _load_namespace(**extra: Any) -> dict:
    """把生产源码里的附录相关定义 exec 进受控命名空间（extra 是替身全局）。"""
    tree = ast.parse(BEST50_FILE.read_text(encoding="utf-8"))
    picked: list[ast.stmt] = [n for n in tree.body if set(_target_names(n)) & TOP_DEFS]
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for method in node.body:
            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                node.name, method.name
            ) in PICKED_METHODS:
                picked.append(method)
    found = {name for n in picked for name in _target_names(n)}
    missing = (TOP_DEFS | {name for _, name in PICKED_METHODS}) - found
    if missing:
        raise AssertionError(f"maimaidx_best_50.py 里找不到定义：{sorted(missing)}")

    ns: dict = {
        "Any": Any, "List": List, "Optional": Optional, "Tuple": Tuple,
        "Union": Union, "Image": Image, "BytesIO": io.BytesIO, "date": date,
        "math": math, "inspect": inspect,
        "anyio": anyio, "ChartInfo": ChartInfo,
        "PlayInfoDefault": ChartInfo, "PlayInfoDev": ChartInfo,
        "music_picture": lambda sid: f"cover/{sid}.png",
        "maidir": Path("maidir"),
        "score_Rank_l": {}, "fcl": {}, "fsl": {},
        "_find_local_chart_music": lambda song_id, chart_type: None,
        "mai": SimpleNamespace(total_list=SimpleNamespace(by_id=lambda sid: None)),
        "effective_source": lambda meta: "merged",
        "SIYUAN": Path("static/common/ResourceHanRoundedCN-Bold.ttf"),
        "TBFONT": Path("static/common/Torus SemiBold.otf"),
        "ScoreBaseImage": SimpleNamespace(text_color=(124, 129, 255, 255)),
        "log": _LogStub(),
        "MessageSegment": _SegmentFactory,
        "image_to_base64": _Encoder(),
        "core": None,
    }
    ns.update(extra)
    module = ast.Module(body=picked, type_ignores=[])
    exec(compile(module, str(BEST50_FILE), "exec"), ns)
    return ns


# ------------------------------------------------------------------
# 测试数据与假 provider
# ------------------------------------------------------------------
def _chart(song_id: int, *, type_: str = "standard", level_index: int = 3,
           achievements: float = 100.0, ds: float = 13.5, ra: int = 50,
           title: str = "测试曲") -> ChartInfo:
    return ChartInfo(
        song_id=song_id, title=title, level_index=level_index, level="13+",
        achievements=achievements, dxScore=0, rate="SSS+", fc="", fs="",
        type=type_, level_label="", ds=ds, source="lxns", ra=ra,
    )


def _user(sd, dx, *, nickname="落雪昵称", rating=12345) -> UserInfo:
    return UserInfo(
        nickname=nickname, rating=rating, additional_rating=0, plate="",
        username="", charts=Data(sd=list(sd), dx=list(dx)),
    )


def _png(width: int, height: int, color=(0, 200, 0, 255)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (width, height), color).save(buffer, "PNG")
    return buffer.getvalue()


class FakeCore:
    """amia_core 替身：真契约类型 + 可控的 capability 表。"""

    def __init__(self, provider: Any = None) -> None:
        self.registry = self._Registry(provider)
        self.B50CardPosition = contract.B50CardPosition
        self.B50AppendixContext = contract.B50AppendixContext
        self.B50AppendixPalette = contract.B50AppendixPalette

    class _Registry:
        def __init__(self, provider: Any) -> None:
            self._provider = provider
            self.lookups = 0
            self.asked_name = None

        def get_capability_provider(self, name: str) -> Any:
            self.lookups += 1
            self.asked_name = name
            return self._provider


class FakeProvider:
    def __init__(self, *, png: bytes | None = None, exc: Exception | None = None,
                 delay: float | None = None, enabled: bool | None = True,
                 enabled_exc: Exception | None = None, bad_type: Any = None):
        self.png = png
        self.exc = exc
        self.delay = delay
        self.enabled = enabled
        self.enabled_exc = enabled_exc
        self.bad_type = bad_type
        self.ctx = None
        self.calls = 0

    def is_enabled(self) -> bool:
        if self.enabled_exc is not None:
            raise self.enabled_exc
        return bool(self.enabled)

    async def render_appendix(self, ctx):
        self.ctx = ctx
        self.calls += 1
        if self.delay is not None:
            await anyio.sleep(self.delay)
        if self.exc is not None:
            raise self.exc
        if self.bad_type is not None:
            return self.bad_type
        return self.png


# ------------------------------------------------------------------
# 1) 绘制顺序：在生产 whiledraw 本体上钉
# ------------------------------------------------------------------
class DrawOrderFidelityTests(unittest.TestCase):
    """``_draw_order`` / ``b50_cards`` 必须逐项等于实际画上去的顺序。"""

    @classmethod
    def setUpClass(cls) -> None:
        if contract is None:
            raise unittest.SkipTest(f"读不到契约模块：{CONTRACT_FILE}")
        cls.ns = _load_namespace(Image=_ProxyImage(Image), core=FakeCore())
        # staticmethod 包一层：否则它们会变成 TestCase 的方法，self 被当第一个
        # 位置参数塞进生产函数（data 就成了 canvas 自己）。
        cls.whiledraw = staticmethod(cls.ns["whiledraw"])
        cls.b50_cards = staticmethod(cls.ns["b50_cards"])

    @staticmethod
    def _sd() -> list[ChartInfo]:
        # 12 张 = 3 行（最后一行只有 2 张），跨过 num % 5 换行边界
        ids = [1001, 1002, 1003, 1004, 1005,
               1006, 1007, 1736, 1009, 1010,
               1011, 1012]
        return [_chart(i, title=f"sd{i}") for i in ids]

    @staticmethod
    def _dx() -> list[ChartInfo]:
        return [_chart(i, type_="dx", title=f"dx{i}") for i in (2001, 2002, 2003)]

    def test_positions_follow_the_draw_loop(self) -> None:
        canvas = _FakeCanvas()
        sd, dx = self._sd(), self._dx()
        self.whiledraw(canvas, sd, False, bucket="b35")
        self.whiledraw(canvas, dx, True, bucket="b15")

        self.assertEqual(len(canvas._draw_order), len(sd) + len(dx))
        drawn_ids = [c.song_id for c in sd + dx]
        self.assertEqual([info.song_id for _, _, info in canvas._draw_order], drawn_ids)

        cards = self.b50_cards(canvas)
        self.assertEqual([c.song_id for c in cards], drawn_ids,
                         "卡序必须逐项等于绘制序")
        self.assertEqual([c.index_1based for c in cards],
                         list(range(1, len(sd) + 1)) + list(range(1, len(dx) + 1)))
        self.assertEqual([c.bucket for c in cards],
                         ["b35"] * len(sd) + ["b15"] * len(dx))

    def test_grid_geometry_is_five_columns_row_major(self) -> None:
        """每张卡的第一笔（难度底色块）坐标 = 5 列行优先：x=16+276·col，y=235+114·row。"""
        canvas = _FakeCanvas()
        sd = self._sd()
        self.whiledraw(canvas, sd, False, bucket="b35")
        expected = [(16 + 276 * (n % 5), 235 + 114 * (n // 5)) for n in range(len(sd))]
        # 替身里只有难度底色块是 str，其余合成对象都是 PIL.Image → 用它挑出每张卡的第一笔
        origins = [pos for pos, img in canvas._im.composites if isinstance(img, str)]
        self.assertEqual(origins, expected)

    def test_dx_block_starts_at_its_own_origin(self) -> None:
        canvas = _FakeCanvas()
        dx = self._dx()
        self.whiledraw(canvas, dx, True, bucket="b15")
        origins = [pos for pos, img in canvas._im.composites if isinstance(img, str)]
        self.assertEqual(origins, [(16, 1085), (292, 1085), (568, 1085)])

    def test_1736_is_b35_at_its_drawn_slot(self) -> None:
        """★ P0 实测：1736 版本码 25504，两源都归上半区（coach 阈值会判 b15）。"""
        canvas = _FakeCanvas()
        self.whiledraw(canvas, self._sd(), False, bucket="b35")
        self.whiledraw(canvas, self._dx(), True, bucket="b15")
        cards = self.b50_cards(canvas)
        target = [c for c in cards if c.song_id == 1736]
        self.assertEqual(len(target), 1)
        self.assertEqual(target[0].bucket, "b35")
        self.assertEqual(target[0].index_1based, 8, "第 2 行第 3 列 = b35 的第 8 格")

    def test_bucket_is_version_not_chart_type(self) -> None:
        """桶来自 sd/dx 两组列表（版本划分），不是谱面 type。"""
        canvas = _FakeCanvas()
        odd = [_chart(3001, type_="dx"), _chart(3002, type_="standard")]
        self.whiledraw(canvas, odd, False, bucket="b35")
        cards = self.b50_cards(canvas)
        self.assertEqual([c.bucket for c in cards], ["b35", "b35"])
        self.assertEqual([c.chart_type for c in cards], ["dx", "standard"],
                         "谱面类型原样透传，由消费侧归一")

    def test_no_bucket_means_no_recording(self) -> None:
        """DrawScore 等其它图（不传 bucket）不得写台账，也不受影响。"""
        canvas = _FakeCanvas()
        self.whiledraw(canvas, self._dx(), True, 140)
        self.assertEqual(canvas._draw_order, [])
        self.assertEqual(self.b50_cards(canvas), ())

    def test_card_fields_map_chart_fields(self) -> None:
        canvas = _FakeCanvas()
        sd = [_chart(4001, achievements=100.4567, ds=14.2, ra=77, title="标题")]
        self.whiledraw(canvas, sd, False, bucket="b35")
        card = self.b50_cards(canvas)[0]
        self.assertEqual(card.title, "标题")
        self.assertAlmostEqual(card.achievement, 100.4567)
        self.assertEqual(card.constant, 14.2)
        self.assertEqual(card.ra, 77)
        self.assertEqual(card.level_index, 3)

    def test_constant_none_when_backfill_failed(self) -> None:
        """回填失败（ds=0）→ constant=None，由消费侧跳过该卡（契约规定）。"""
        canvas = _FakeCanvas()
        self.whiledraw(canvas, [_chart(4002, ds=0.0)], False, bucket="b35")
        self.assertIsNone(self.b50_cards(canvas)[0].constant)

    def test_provider_name_matches_contract(self) -> None:
        self.assertEqual(
            self.ns["B50_APPENDIX_PROVIDER"], contract.B50_APPENDIX_PROVIDER,
            "capability 稳定名漂移 = 查不到对方，附录永远不出",
        )

    def test_timeout_budget_is_eight_seconds(self) -> None:
        self.assertEqual(self.ns["_APPENDIX_TIMEOUT_SEC"], 8.0)


# ------------------------------------------------------------------
# 2) generate()：call-time 查表 + 拼接 + 降级
# ------------------------------------------------------------------
class _FakeDrawBest:
    """DrawBest 替身：生产 ``b50_cards`` + 生产 ctx 构造，只跳过像素绘制。

    「顺序」本身由 DrawOrderFidelityTests 在生产 whiledraw 上钉死；这里按同一条
    规则（sd 先、dx 后，桶内 1-based）喂数据，避免把素材/字体依赖拖进来。
    """

    instances: list["_FakeDrawBest"] = []

    def __init__(self, userinfo: UserInfo, qqid=None, is_ap=False, source="merged"):
        canvas = Image.new("RGBA", CANVAS_SIZE, (250, 250, 250, 255))
        for i in range(10):  # 非纯色，像素比对才有意义
            canvas.paste((i * 20, 40, 200, 255), (0, i * 170, 1400, i * 170 + 85))
        self._im = canvas
        self.qqid = qqid
        self.userName = userinfo.nickname
        self.Rating = userinfo.rating
        self.sdBest = [c for c in (userinfo.charts.sd or []) if c.level_index <= 4]
        self.dxBest = [c for c in (userinfo.charts.dx or []) if c.level_index <= 4]
        self._draw_order: list[tuple[str, int, Any]] = []
        _FakeDrawBest.instances.append(self)

    async def draw(self) -> Image.Image:
        self._draw_order = (
            [("b35", i + 1, c) for i, c in enumerate(self.sdBest)]
            + [("b15", i + 1, c) for i, c in enumerate(self.dxBest)]
        )
        return self._im


class GenerateAppendixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if contract is None:
            raise unittest.SkipTest(f"读不到契约模块：{CONTRACT_FILE}")

    class _Api:
        def __init__(self, userinfo: UserInfo) -> None:
            self.userinfo = userinfo
            self.calls: list[tuple] = []

        async def query_user_b50_merged(self, *, qqid=None, username=None, is_ap=False):
            self.calls.append((qqid, username, is_ap))
            return self.userinfo, {"sources": ["lxns"]}

    def setUp(self) -> None:
        _FakeDrawBest.instances.clear()
        self.userinfo = _user(
            [_chart(i, title=f"sd{i}") for i in (1001, 1002, 1736)],
            [_chart(2001, type_="dx", title="dx2001")],
        )
        self.core = FakeCore()
        self.ns = _load_namespace(core=self.core, DrawBest=_FakeDrawBest)
        # 生产 b50_cards 绑到替身上（顺序规则仍由生产实现算）
        _FakeDrawBest.b50_cards = self.ns["b50_cards"]
        self.encoder = self.ns["image_to_base64"]
        self.log = self.ns["log"]
        self.api = self._Api(self.userinfo)
        self.ns["maiApi"] = self.api
        self.generate = self.ns["generate"]

    def _run(self, **kwargs) -> tuple[str, str]:
        seg, notice = asyncio.run(self.generate(qqid=1, username=None, **kwargs))
        return seg.data, notice

    def _canvas(self) -> Image.Image:
        return _FakeDrawBest.instances[-1]._im

    def _control(self) -> str:
        """与改动前 ``generate`` 的最后一行等价：原画布直接编码。"""
        return _encode(self._canvas())

    # --- 硬线 1：coach 缺席 → 逐字节相等 -------------------------------
    def test_no_provider_is_byte_identical(self) -> None:
        base64_out, notice = self._run()
        control = self._control()
        self.assertEqual(notice, "", "coach 缺席必须静默，不新增任何话术")
        self.assertEqual(base64_out, control, "PNG 字节必须与不接附录时逐字节相等")
        self.assertEqual(len(self.encoder.images), 1, "只许编码一次")
        self.assertIs(self.encoder.images[0], self._canvas(),
                      "编码的必须就是原画布对象（没有重建、没有重绘）")
        self.assertEqual(self.core.registry.lookups, 1, "call-time 查一次表")
        self.assertEqual(self.core.registry.asked_name, contract.B50_APPENDIX_PROVIDER)

    def test_appendix_off_never_touches_the_registry(self) -> None:
        base64_out, notice = self._run(appendix=False)
        self.assertEqual(base64_out, self._control())
        self.assertEqual(notice, "")
        self.assertEqual(self.core.registry.lookups, 0,
                         "「b50 无锐评」/ ap50 连查表都不该发生")

    # --- 正常路径：拼在下方 --------------------------------------------
    def test_appendix_pasted_below_without_touching_original_rows(self) -> None:
        provider = FakeProvider(png=_png(1400, 60))
        self.core.registry._provider = provider
        base64_out, notice = self._run()
        self.assertEqual(notice, "")
        control = self._control()
        self.assertNotEqual(base64_out, control, "接上附录后输出必须变")
        canvas = self._canvas()
        out = Image.open(io.BytesIO(base64.b64decode(base64_out.split("//", 1)[1])))
        self.assertEqual(out.size, (canvas.size[0], canvas.size[1] + 60), "附录拼在下方")
        top = out.crop((0, 0, canvas.size[0], canvas.size[1])).convert("RGBA")
        self.assertIsNone(
            ImageChops.difference(top, canvas.convert("RGBA")).getbbox(),
            "原图区域一个像素都不差",
        )

    def test_ctx_fields_follow_the_contract(self) -> None:
        provider = FakeProvider(png=_png(1400, 20))
        self.core.registry._provider = provider
        self._run()
        ctx = provider.ctx
        canvas = self._canvas()
        self.assertIsInstance(ctx, contract.B50AppendixContext)
        self.assertEqual(ctx.width, canvas.size[0], "宽度必须取画布，不许硬编码 1400")
        self.assertEqual(ctx.canvas_height, canvas.size[1])
        self.assertEqual(ctx.nickname, "落雪昵称")
        self.assertEqual(ctx.total_rating, 12345)
        self.assertEqual(ctx.title_font, self.ns["SIYUAN"])
        self.assertEqual(ctx.body_font, self.ns["TBFONT"])
        self.assertEqual(ctx.accent_rgb, (124, 129, 255, 255))
        self.assertEqual(ctx.generated_on, date.today().isoformat())
        self.assertEqual([c.song_id for c in ctx.cards], [1001, 1002, 1736, 2001])
        self.assertEqual([c.bucket for c in ctx.cards], ["b35", "b35", "b35", "b15"])
        self.assertEqual([c.index_1based for c in ctx.cards], [1, 2, 3, 1])
        for card in ctx.cards:
            self.assertIsInstance(card, contract.B50CardPosition)

    def test_constant_is_the_backfilled_value(self) -> None:
        """★ 落雪 payload 无 ds（0.0），ctx 必须带**回填之后**的定数。"""
        self.userinfo = _user([_chart(9001, ds=0.0)], [_chart(9002, type_="dx", ds=0.0)])
        self.api = self._Api(self.userinfo)
        self.ns["maiApi"] = self.api
        # 本地曲库回填（生产 _find_local_chart_music 的替身）
        self.ns["_find_local_chart_music"] = lambda sid, ctype: SimpleNamespace(
            id=str(sid), ds=[12.0, 12.5, 13.0, 13.7, 14.4]
        )
        provider = FakeProvider(png=_png(1400, 20))
        self.core.registry._provider = provider
        self._run()
        self.assertEqual([c.constant for c in provider.ctx.cards], [13.7, 13.7],
                         "constant 必须是回填后的 ds（generate 里那段 best_50 回填）")

    def test_backfill_failure_passes_none_constant(self) -> None:
        self.userinfo = _user([_chart(9003, ds=0.0)], [])
        self.ns["maiApi"] = self._Api(self.userinfo)
        provider = FakeProvider(png=_png(1400, 20))
        self.core.registry._provider = provider
        self._run()
        self.assertIsNone(provider.ctx.cards[0].constant)
        self.assertTrue(
            any("未找到定数" in line for line in self.log.lines),
            "回填失败要留日志线索（生产既有行为，不得被附录改动吞掉）",
        )

    # --- 降级矩阵：一律原图 -------------------------------------------
    def _assert_degrade(self, provider: Any, *, expect_notice: bool) -> None:
        self.core.registry._provider = provider
        base64_out, notice = self._run()
        self.assertEqual(base64_out, self._control(), "降级必须回到原图字节")
        self.assertIs(self.encoder.images[-1], self._canvas())
        if expect_notice:
            self.assertIn(
                notice,
                (self.ns["_APPENDIX_DEGRADE_NOTICE"], self.ns["_APPENDIX_DISABLED_NOTICE"]),
                "用户主动要锐评时要有话术",
            )
        else:
            self.assertEqual(notice, "")

    def test_render_appendix_raises_keeps_original(self) -> None:
        self._assert_degrade(FakeProvider(exc=RuntimeError("渲染炸了")),
                             expect_notice=True)

    def test_render_appendix_returns_none_keeps_original(self) -> None:
        self._assert_degrade(FakeProvider(png=None), expect_notice=True)

    def test_timeout_keeps_original(self) -> None:
        self.ns["_APPENDIX_TIMEOUT_SEC"] = 0.05
        self._assert_degrade(FakeProvider(png=_png(1400, 20), delay=0.3),
                             expect_notice=True)

    def test_width_mismatch_keeps_original(self) -> None:
        self._assert_degrade(FakeProvider(png=_png(1399, 20)), expect_notice=True)

    def test_undecodable_bytes_keeps_original(self) -> None:
        self._assert_degrade(FakeProvider(png=b"not a png"), expect_notice=True)

    def test_wrong_return_type_keeps_original(self) -> None:
        self._assert_degrade(FakeProvider(bad_type="我要返回字符串"), expect_notice=True)

    def test_disabled_by_config_switch(self) -> None:
        self._assert_degrade(FakeProvider(png=_png(1400, 20), enabled=False),
                             expect_notice=True)

    def test_is_enabled_raises_keeps_original(self) -> None:
        self._assert_degrade(
            FakeProvider(enabled_exc=RuntimeError("配置读不到")), expect_notice=True
        )

    def test_registry_lookup_raises_keeps_original(self) -> None:
        class _BoomRegistry:
            lookups = 0

            def get_capability_provider(self, name):
                raise RuntimeError("注册表炸了")

        core = FakeCore()
        core.registry = _BoomRegistry()
        self.core = core
        self.ns["core"] = core
        base64_out, notice = self._run()
        self.assertEqual(base64_out, self._control())
        self.assertEqual(notice, "", "查表异常属静默降级，不加话术")

    def test_contract_unavailable_keeps_original(self) -> None:
        """amia_core 整个没装好（core=None）：静默原图，b50 主功能不受影响。"""
        self.ns["core"] = None
        base64_out, notice = self._run()
        self.assertEqual(base64_out, self._control())
        self.assertEqual(notice, "")

    def test_legacy_core_missing_contract_exports_keeps_original(self) -> None:
        """★ 旧版 amia_core 装了、但没导出 ``B50CardPosition`` / ``B50AppendixContext``。

        硬访问会 AttributeError 冒到 ``generate()`` → b50 退化成错误卡；必须静默降级。
        """

        class _LegacyCore:
            """只有 capability 表、没有契约类型的老 amia_core。"""

            def __init__(self, provider: Any) -> None:
                self.registry = FakeCore._Registry(provider)

        provider = FakeProvider(png=_png(1400, 20))
        self.ns["core"] = _LegacyCore(provider)
        base64_out, notice = self._run()
        self.assertEqual(base64_out, self._control(), "缺导出必须原样出图，不许抛")
        self.assertEqual(notice, "", "契约缺失属静默降级，不加话术")
        self.assertEqual(provider.calls, 0, "契约不可用就别调用渲染")
        self.assertEqual(_FakeDrawBest.instances[-1].b50_cards(), (),
                         "旧版 core 下 b50_cards 必须返回空元组")

    def test_context_construction_raises_keeps_original(self) -> None:
        """★ 契约类型在、但构造抛异常（旧版签名不合 / 内部炸）→ 原图 + debug 线索。"""
        boom = FakeCore(FakeProvider(png=_png(1400, 20)))

        def _raise(*args, **kwargs):
            raise RuntimeError("B50AppendixContext 构造炸了")

        boom.B50AppendixContext = _raise
        self.ns["core"] = boom
        base64_out, notice = self._run()
        self.assertEqual(base64_out, self._control(), "上下文构造炸了也要原样出图")
        self.assertEqual(notice, "")
        self.assertTrue(
            any("附录上下文" in line for line in self.log.lines),
            "降级要留 debug 线索",
        )

    def test_empty_cards_skips_appendix(self) -> None:
        """宴会场（level_index>4）全被滤掉、一张卡都没画 → 不查渲染。"""
        self.userinfo = _user([_chart(9004, level_index=5)], [])
        self.ns["maiApi"] = self._Api(self.userinfo)
        provider = FakeProvider(png=_png(1400, 20))
        self.core.registry._provider = provider
        base64_out, notice = self._run()
        self.assertEqual(base64_out, self._control())
        self.assertEqual(notice, "")
        self.assertEqual(provider.calls, 0, "没有卡就别调用对方")

    def test_provider_absent_and_present_same_bytes(self) -> None:
        """验收硬线 1 的直接证据：同一份数据、两条路径的 base64 对比。

        打印出来便于人工核对（``-v`` 运行时可见）：缺席路径必须与控制值全等。
        """
        absent, notice_absent = self._run()
        control = self._control()
        self.core.registry._provider = FakeProvider(png=_png(1400, 40))
        present, notice_present = self._run()
        digest = lambda s: base64.b64decode(s.split("//", 1)[1])[:8].hex()  # noqa: E731
        print(
            "\n[b50 附录比对]\n"
            f"  控制值（等价于改动前）: len={len(control)} head={digest(control)}\n"
            f"  provider 缺席        : len={len(absent)} head={digest(absent)} notice={notice_absent!r}\n"
            f"  provider 在场        : len={len(present)} head={digest(present)} notice={notice_present!r}\n"
            f"  缺席 == 控制值       : {absent == absent and absent == control}"
        )
        self.assertEqual(absent, control)
        self.assertNotEqual(present, control)

    # --- 调色板采样（P3 视觉重做：附录条要接得住 B50 图的实际底色）--------
    def test_palette_seam_sampled_from_the_canvas_edge(self) -> None:
        """``seam_rgb`` = 画布最下方那条带的均色（附录就接在这条边下面）。

        替身画布的最后一条色带停在 y=1615，底部 24px（1676..1700）全是底图的
        ``(250,250,250)``，所以期望值可以**独立算出来**，不是拿被测函数自证。
        """
        provider = FakeProvider(png=_png(1400, 20))
        self.core.registry._provider = provider
        self._run()
        palette = provider.ctx.palette
        self.assertIsInstance(palette, contract.B50AppendixPalette)
        self.assertEqual(palette.seam_rgb, (250, 250, 250, 255))

    def test_palette_base_follows_the_asset_pixels_not_a_hardcoded_value(self) -> None:
        """★ 禁止硬编码色值：换一张背景素材，采样值必须跟着变（值来自像素）。"""
        for color in ((10, 200, 216, 255), (220, 30, 90, 255)):
            with self.subTest(color=color):
                with tempfile.TemporaryDirectory() as tmp:
                    asset = Path(tmp) / "b50_bg.png"
                    Image.new("RGBA", (60, 40), color).save(asset)
                    self.ns["maidir"] = Path(tmp)
                    provider = FakeProvider(png=_png(1400, 20))
                    self.core.registry._provider = provider
                    self._run()
                    self.assertEqual(provider.ctx.palette.base_rgb, color)

    def test_palette_missing_when_asset_absent_is_none_not_an_error(self) -> None:
        """素材不在（测试替身把 ``maidir`` 指到不存在的目录）→ base_rgb 为 None，
        ctx 照常构造、附录照常出，不许因为采样把主功能带崩。"""
        provider = FakeProvider(png=_png(1400, 20))
        self.core.registry._provider = provider
        base64_out, notice = self._run()
        self.assertIsNone(provider.ctx.palette.base_rgb)
        self.assertIsNotNone(provider.ctx.palette.seam_rgb)
        self.assertEqual(notice, "")
        self.assertNotEqual(base64_out, self._control(), "附录仍然被拼上")

    def test_sampling_does_not_touch_a_single_canvas_pixel(self) -> None:
        """★ 硬线：采样只读。构造 ctx 前后画布必须逐像素相等（同一对象、同一字节）。"""
        provider = FakeProvider(png=_png(1400, 20))
        self.core.registry._provider = provider
        draw_best = _FakeDrawBest(self.userinfo)
        draw_best._draw_order = [("b35", 1, _chart(1001))]
        before = draw_best._im.copy()
        ctx = self.ns["_build_appendix_context"](draw_best)
        self.assertIsNotNone(ctx)
        self.assertIs(ImageChops.difference(before, draw_best._im).getbbox(), None,
                      "采样不得改动原画布任何像素")

    def test_sampling_skipped_entirely_when_provider_absent(self) -> None:
        """coach 缺席 → 连一次采样都不许发生（字节级不变的更强口径）。"""
        calls: list = []
        self.ns["_sample_background_palette"] = lambda db: calls.append(db) or None
        self._run()
        self.assertEqual(calls, [], "provider 缺席时不得触发采样")

    def test_legacy_core_without_palette_export_still_builds_ctx(self) -> None:
        """旧版 amia_core 没导出 ``B50AppendixPalette`` → **不传** palette 关键字。

        ctx 类型也是旧签名（多一个关键字就 TypeError），所以真把 palette 传过去
        等于把整条附录丢掉；这里断言旧契约下附录照常出、ctx 不带新字段。
        """

        class _LegacyCtx:
            """旧版 ``B50AppendixContext`` 的签名：没有 palette 这个字段。"""

            def __init__(self, *, cards, width, canvas_height, nickname, total_rating,
                         title_font, body_font, accent_rgb, generated_on) -> None:
                self.cards = cards
                self.width = width
                self.canvas_height = canvas_height
                self.nickname = nickname
                self.total_rating = total_rating
                self.title_font = title_font
                self.body_font = body_font
                self.accent_rgb = accent_rgb
                self.generated_on = generated_on

        class _LegacyNoPalette(FakeCore):
            def __init__(self, provider: Any = None) -> None:
                super().__init__(provider)
                del self.B50AppendixPalette
                self.B50AppendixContext = _LegacyCtx

        provider = FakeProvider(png=_png(1400, 20))
        self.ns["core"] = _LegacyNoPalette(provider)
        base64_out, notice = self._run()
        self.assertEqual(provider.calls, 1, "旧版契约下附录仍然要出")
        self.assertFalse(hasattr(provider.ctx, "palette"), "ctx 不该被塞进旧契约没有的字段")
        self.assertEqual(notice, "")
        self.assertNotEqual(base64_out, self._control())

    def test_sampler_returns_none_when_nothing_can_be_read(self) -> None:
        """素材缺失 + 画布全透明（采不到任何不透明点）→ None，不抛异常。"""
        with tempfile.TemporaryDirectory() as tmp:
            self.ns["maidir"] = Path(tmp)  # 目录在，b50_bg.png 不在
            blank = SimpleNamespace(_im=Image.new("RGBA", (8, 8), (0, 0, 0, 0)))
            self.assertIsNone(self.ns["_sample_background_palette"](blank))

    def test_mean_rgb_over_rejects_degenerate_boxes(self) -> None:
        """区域不合（越界 / 零面积 / 全透明）一律 None，不返回半成品颜色。"""
        canvas = Image.new("RGBA", (20, 20), (7, 8, 9, 255))
        mean = self.ns["_mean_rgb_over"]
        self.assertEqual(mean(canvas, 0, 0, 20, 20), (7, 8, 9, 255))
        self.assertIsNone(mean(canvas, 30, 30, 40, 40), "完全越界")
        self.assertIsNone(mean(canvas, 5, 5, 5, 9), "零面积")
        self.assertIsNone(mean(Image.new("RGBA", (4, 4), (0, 0, 0, 0)), 0, 0, 4, 4), "全透明")


class P5bIdentityNoticeAndThreadTests(unittest.TestCase):
    """P5b：ctx.identity（全量回退 + 节流键）、take_notice、m1 缺席话术、m5 线程化。"""

    @classmethod
    def setUpClass(cls) -> None:
        if contract is None:
            raise unittest.SkipTest(f"读不到契约模块：{CONTRACT_FILE}")

    def setUp(self) -> None:
        _FakeDrawBest.instances.clear()
        self.userinfo = _user([_chart(1001, title="sd1001")], [_chart(2001, type_="dx")])
        self.core = FakeCore()
        self.ns = _load_namespace(core=self.core, DrawBest=_FakeDrawBest)
        _FakeDrawBest.b50_cards = self.ns["b50_cards"]
        self.ns["maiApi"] = GenerateAppendixTests._Api(self.userinfo)
        self.generate = self.ns["generate"]

    def _run(self, **kwargs) -> tuple[str, str]:
        seg, notice = asyncio.run(self.generate(qqid=1, username=None, **kwargs))
        return seg.data, notice

    def _control(self) -> str:
        return _encode(_FakeDrawBest.instances[-1]._im)

    # --- 身份键（P5b §2）------------------------------------------------
    def test_ctx_identity_is_the_queried_qqid(self) -> None:
        provider = FakeProvider(png=_png(1400, 20))
        self.core.registry._provider = provider
        self._run()
        self.assertEqual(provider.ctx.identity, "1", "按 QQ 查 → identity = qqid 十进制串")

    def test_ctx_identity_falls_back_to_the_normalized_nickname(self) -> None:
        provider = FakeProvider(png=_png(1400, 20))
        self.core.registry._provider = provider
        asyncio.run(self.generate(qqid=None, username="  小明  "))
        self.assertEqual(provider.ctx.identity, "落雪昵称",
                         "按昵称查 → identity = 上游返回的昵称（归一后的那个名字）")

    def test_legacy_ctx_without_identity_field_is_not_passed_it(self) -> None:
        """旧版契约（ctx 没有 identity 字段）→ 不传该关键字，附录照常出。"""

        class _LegacyCtx:
            def __init__(self, *, cards, width, canvas_height, nickname, total_rating,
                         title_font, body_font, accent_rgb, generated_on) -> None:
                self.cards = cards
                self.width = width
                self.canvas_height = canvas_height
                self.nickname = nickname
                self.total_rating = total_rating
                self.title_font = title_font
                self.body_font = body_font
                self.accent_rgb = accent_rgb
                self.generated_on = generated_on

        class _LegacyCore(FakeCore):
            def __init__(self, provider: Any = None) -> None:
                super().__init__(provider)
                del self.B50AppendixPalette
                self.B50AppendixContext = _LegacyCtx

        provider = FakeProvider(png=_png(1400, 20))
        self.ns["core"] = _LegacyCore(provider)
        base64_out, notice = self._run()
        self.assertEqual(provider.calls, 1, "旧版契约下附录仍然要出")
        self.assertFalse(hasattr(provider.ctx, "identity"), "不许塞旧契约没有的字段")
        self.assertEqual(notice, "")
        self.assertNotEqual(base64_out, self._control())

    # --- take_notice（P5b §3：节流 / 排队话术由渲染侧给）------------------
    def test_take_notice_is_surfaced_when_render_returns_none(self) -> None:
        class _NoticeProvider(FakeProvider):
            def take_notice(self, ctx):
                return "刚锐评过，20 秒后再给你带上"

        self.core.registry._provider = _NoticeProvider(png=None)
        base64_out, notice = self._run()
        self.assertEqual(base64_out, self._control(), "只跳附录，图照发")
        self.assertEqual(notice, "刚锐评过，20 秒后再给你带上")

    def test_take_notice_raising_falls_back_to_the_default_notice(self) -> None:
        class _BoomNotice(FakeProvider):
            def take_notice(self, ctx):
                raise RuntimeError("话术炸了")

        self.core.registry._provider = _BoomNotice(png=None)
        base64_out, notice = self._run()
        self.assertEqual(base64_out, self._control())
        self.assertEqual(notice, self.ns["_APPENDIX_DEGRADE_NOTICE"])

    # --- m1：coach 缺席时由调用方补一句 ----------------------------------
    def test_appendix_absent_notice_only_when_provider_is_missing(self) -> None:
        self.assertEqual(self.ns["appendix_absent_notice"](),
                         self.ns["_APPENDIX_ABSENT_NOTICE"])
        self.core.registry._provider = FakeProvider(png=_png(1400, 20))
        self.assertEqual(self.ns["appendix_absent_notice"](), "",
                         "coach 在场 → 不补话术（裸 b50 的文字必须不变）")

    def test_generate_stays_silent_when_provider_is_missing(self) -> None:
        """硬线不变：缺席路径零话术（m1 的话术由调用方决定说不说）。"""
        base64_out, notice = self._run()
        self.assertEqual(notice, "")
        self.assertEqual(base64_out, self._control())

    # --- m5：PIL 拼接与编码必须进线程 ------------------------------------
    def test_paste_and_encode_run_in_a_worker_thread(self) -> None:
        calls: list = []
        real_anyio = self.ns["anyio"]

        class _RecordingAnyio:
            def __init__(self) -> None:
                self.to_thread = SimpleNamespace(run_sync=self._run_sync)

            def _run_sync(self, fn, *a, **k):
                calls.append(fn)
                return real_anyio.to_thread.run_sync(fn, *a, **k)

            def __getattr__(self, name):
                return getattr(real_anyio, name)

        self.ns["anyio"] = _RecordingAnyio()
        provider = FakeProvider(png=_png(1400, 20))
        self.core.registry._provider = provider
        self._run()
        self.assertIn(self.ns["_paste_appendix"], calls, "整画布拼接必须进线程")
        # 编码经 generate._encode 闭包整层进线程（内部调 image_to_base64）
        encode_fns = [fn for fn in calls if getattr(fn, "__name__", "") == "_encode"]
        self.assertTrue(encode_fns, "JPEG 编码 + base64 必须进线程")


if __name__ == "__main__":
    unittest.main()
