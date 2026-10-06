import base64
import math
import inspect
import traceback
import httpx
import anyio
from curl_cffi import requests as cffi_requests
from datetime import date
from io import BytesIO
from typing import Any, Tuple, Union, overload, List, Optional

from nonebot.adapters.onebot.v11 import MessageSegment
from PIL import Image, ImageDraw
from loguru import logger as log

from ..config import *
from .image import DrawText, image_to_base64, music_picture
from .maimaidx_api_data import maiApi
from .maimaidx_error import *
from .maimaidx_model import ChartInfo, PlayInfoDefault, PlayInfoDev, UserInfo
from .maimaidx_music import mai
from ..release010_import import format_user_error
from .attribution import draw_attribution
from .maimaidx_merge import effective_source
from .maimaidx_types import SourceName, normalize_source

# 契约类型与 capability 表都在 amia_core（依赖方向 coach → amia_core ← maimaidx，
# 两侧互不 import）。三档加载路径与 dependencies.py:47-53 /
# providers/maimai_data.py:8-14 同构；最后一档也失败时 core = None —— 附录静默
# 缺席，绝不因为姊妹层没装好而让 b50 主功能挂掉。
try:
    from nonebot import require

    core = require("amia_core")
except Exception:  # noqa: BLE001 - 任何加载失败都只是「没有附录」
    try:
        from src.plugins import amia_core as core  # type: ignore[no-redef]
    except Exception:  # noqa: BLE001
        try:
            import amia_core as core  # type: ignore[no-redef]
        except Exception:  # noqa: BLE001
            core = None  # type: ignore[assignment]

B50_APPENDIX_PROVIDER = getattr(core, "B50_APPENDIX_PROVIDER", "maimai.b50.appendix")
"""capability 稳定名（``amia_core/b50_appendix.py``）；coach 注册、本仓库查表。"""


def _find_local_chart_music(song_id: int | str, chart_type: str):
    """Resolve a score to the local SD/DX catalog entry without mixing IDs.

    LXNS uses the native song id for both chart types, whereas historical
    Diving-Fish records use ``native_id + 10000`` for DX.  Looking up by id
    alone can therefore select the SD entry for an LXNS DX record (for
    example native 1235 versus Fish/local 11235).
    """
    raw_id = int(song_id)
    is_dx = str(chart_type or "").strip().lower() in {"dx", "deluxe"}
    exact = mai.total_list.by_id(str(raw_id))
    if exact is not None:
        exact_is_dx = str(getattr(exact, "type", "")).strip().lower() in {"dx", "deluxe"}
        if exact_is_dx == is_dx:
            return exact
    if is_dx and raw_id < 10000:
        offset = mai.total_list.by_id(str(raw_id + 10000))
        if offset is not None:
            return offset
    return exact

class ScoreBaseImage:
    
    text_color = (124, 129, 255, 255)
    t_color = [
        (255, 255, 255, 255), 
        (255, 255, 255, 255), 
        (255, 255, 255, 255), 
        (255, 255, 255, 255), 
        (138, 0, 226, 255)
    ]
    id_color = [
        (129, 217, 85, 255), 
        (245, 189, 21, 255),  
        (255, 129, 141, 255), 
        (159, 81, 220, 255),
        (138, 0, 226, 255)
    ]
    bg_color = [
        (111, 212, 61, 255), 
        (248, 183, 9, 255), 
        (255, 129, 141, 255), 
        (159, 81, 220, 255), 
        (219, 170, 255, 255)
    ]
    id_diff = [Image.new('RGBA', (55, 10), color) for color in bg_color]
    
    _class_loaded = False
    _diff = []
    _rise = []
    title_bg = None
    title_lengthen_bg = None
    design_bg = None
    aurora_bg = None
    shines_bg = None
    pattern_bg = None
    rainbow_bg = None
    rainbow_bottom_bg = None
    
    def __init__(self, image: Image.Image = None) -> None:
        # 确保类级别图片已加载（首次调用或预加载时）
        type(self).load_image()
        
        if image is not None:
            self._im = image
            dr = ImageDraw.Draw(self._im)
            self._sy = DrawText(dr, SIYUAN)
            self._tb = DrawText(dr, TBFONT)
        # 绘制顺序台账：(bucket, 桶内 1-based 序号, info)。只有传了 bucket 的
        # 调用（= DrawBest 的 B50/AP50）会写入，DrawScore 等其它图不记。
        self._draw_order: List[Tuple[str, int, Any]] = []
    
    @classmethod
    def load_image(cls):
        """加载 UI 图片资源到类属性。支持预加载（由 __init__.py 在启动时调用）"""
        if cls._class_loaded:
            return
        cls._diff = [
            Image.open(maidir / 'b50_score_basic.png'), 
            Image.open(maidir / 'b50_score_advanced.png'), 
            Image.open(maidir / 'b50_score_expert.png'), 
            Image.open(maidir / 'b50_score_master.png'), 
            Image.open(maidir / 'b50_score_remaster.png')
        ]
        cls._rise = [
            Image.open(maidir / 'rise_score_basic.png'),
            Image.open(maidir / 'rise_score_advanced.png'),
            Image.open(maidir / 'rise_score_expert.png'),
            Image.open(maidir / 'rise_score_master.png'),
            Image.open(maidir / 'rise_score_remaster.png')
        ]
        cls.title_bg = Image.open(maidir / 'title.png')
        cls.title_lengthen_bg = Image.open(maidir / 'title-lengthen.png')
        cls.design_bg = Image.open(maidir / 'design.png')
        cls.aurora_bg = Image.open(maidir / 'aurora.png').convert('RGBA').resize((1400, 220))
        cls.shines_bg = Image.open(maidir / 'bg_shines.png').convert('RGBA')
        cls.pattern_bg = Image.open(maidir / 'pattern.png')
        cls.rainbow_bg = Image.open(maidir / 'rainbow.png').convert('RGBA')
        cls.rainbow_bottom_bg = Image.open(maidir / 'rainbow_bottom.png').convert('RGBA').resize((1200, 200))
        cls._class_loaded = True
    
    def whiledraw(self, data: Union[List[ChartInfo], List[PlayInfoDefault], List[PlayInfoDev]], dx: bool, height: int = 0, bucket: Optional[str] = None) -> None:
        dy = 114
        if data and type(data[0]) == ChartInfo:
            y = 1085 if dx else 235
        else:
            y = height
            
        for num, info in enumerate(data):
            if num % 5 == 0:
                x = 16
                y += dy if num != 0 else 0
            else:
                x += 276

            if bucket is not None:
                # ★ 附录卡位的唯一真源：这一格**确实被画在这里**，所以顺序、桶、
                #   序号都在绘制循环里就地记账，不在事后按阈值重排（P0 实测：
                #   song_id=1736 版本码 25504，两源都归上半区，而 coach 的 25500
                #   阈值会判成 b15 —— 所以 coach 不重排，只吃这里记下来的顺序）。
                self._draw_order.append((bucket, num + 1, info))

            cover = Image.open(music_picture(info.song_id)).resize((75, 75))
            type_name = 'SD' if info.type.lower() == 'standard' else info.type.upper()
            version = Image.open(maidir / f'{type_name}.png').resize((37, 14))
            if info.rate.islower():
                rate = Image.open(maidir / f'UI_TTR_Rank_{score_Rank_l[info.rate]}.png').resize((63, 28))
            else:
                rate = Image.open(maidir / f'UI_TTR_Rank_{info.rate}.png').resize((63, 28))

            self._im.alpha_composite(self._diff[info.level_index], (x, y))
            self._im.alpha_composite(cover, (x + 12, y + 12))
            self._im.alpha_composite(version, (x + 51, y + 91))
            self._im.alpha_composite(rate, (x + 92, y + 78))
            if info.fc:
                fc = Image.open(maidir / f'UI_MSS_MBase_Icon_{fcl[info.fc]}.png').resize((34, 34))
                self._im.alpha_composite(fc, (x + 154, y + 77))
            if info.fs:
                fs = Image.open(maidir / f'UI_MSS_MBase_Icon_{fsl[info.fs]}.png').resize((34, 34))
                self._im.alpha_composite(fs, (x + 185, y + 77))
            
            _music = _find_local_chart_music(info.song_id, info.type)
            if _music and len(_music.charts) > info.level_index:
                # 【修改点】向下兼容原生字典的读取方式，绝育 AttributeError
                chart_data = _music.charts[info.level_index]
                notes = chart_data.get('notes', []) if isinstance(chart_data, dict) else getattr(chart_data, 'notes', [])
                dxscore = sum(notes) * 3
                
                dxnum = dxScore(info.dxScore / dxscore * 100) if dxscore > 0 else 0
                if dxnum:
                    self._im.alpha_composite(Image.open(maidir / f'UI_GAM_Gauge_DXScoreIcon_0{dxnum}.png').resize((47, 26)), (x + 217, y + 80))
                self._tb.draw(x + 219, y + 65, 15, f'{info.dxScore}/{dxscore}', self.t_color[info.level_index], anchor='mm')

            self._tb.draw(x + 26, y + 98, 13, info.song_id, self.id_color[info.level_index], anchor='mm')
            title = info.title
            if coloumWidth(title) > 18:
                title = changeColumnWidth(title, 17) + '...'
            self._sy.draw(x + 93, y + 14, 14, title, self.t_color[info.level_index], anchor='lm')
            self._tb.draw(x + 93, y + 38, 30, f'{info.achievements:.4f}%', self.t_color[info.level_index], anchor='lm')
            self._tb.draw(x + 93, y + 65, 15, f'{info.ds} -> {info.ra}', self.t_color[info.level_index], anchor='lm')

class DrawBest(ScoreBaseImage):

    def __init__(self, UserInfo: UserInfo, qqid: Optional[Union[int, str]] = None, is_ap: bool = False, source: SourceName | str = "merged") -> None:
        super().__init__(Image.open(maidir / 'b50_bg.png').convert('RGBA'))
        self.userName = UserInfo.nickname
        self.plate = UserInfo.plate
        self.lxns_icon = UserInfo.username
        self.addRating = UserInfo.additional_rating
        self.Rating = UserInfo.rating

        self.sdBest = [c for c in (UserInfo.charts.sd or []) if c.level_index <= 4]
        self.dxBest = [c for c in (UserInfo.charts.dx or []) if c.level_index <= 4]

        self.qqid = qqid
        self.is_ap = is_ap
        # "merged" 是双源汇总的署名标注，不能被 normalize_source 归一成单源
        self.source = source if source == "merged" else normalize_source(source)

    def _findRaPic(self) -> str:
        if self.Rating < 1000: return '01'
        elif self.Rating < 2000: return '02'
        elif self.Rating < 4000: return '03'
        elif self.Rating < 7000: return '04'
        elif self.Rating < 10000: return '05'
        elif self.Rating < 12000: return '06'
        elif self.Rating < 13000: return '07'
        elif self.Rating < 14000: return '08'
        elif self.Rating < 14500: return '09'
        elif self.Rating < 15000: return '10'
        else: return '11'

    def _findMatchLevel(self) -> str:
        if self.addRating <= 10:
            num = f'{self.addRating:02d}'
        else:
            num = f'{self.addRating + 1:02d}'
        return f'UI_DNM_DaniPlate_{num}.png'

    def b50_cards(self) -> tuple:
        """图上全部卡，**顺序 = ``whiledraw`` 实际画上去的顺序**（b35 五列行优先，
        再 b15）。契约类型来自 ``amia_core/b50_appendix.py``；拿不到契约（core 为
        None，或是没有这两个导出的旧版 amia_core）时返回空元组，附录自然不出。"""
        card_type = getattr(core, "B50CardPosition", None) if core is not None else None
        if card_type is None:
            # getattr 而不是硬访问：旧版 amia_core 缺导出时静默降级，
            # 绝不能让 AttributeError 冒到 generate() 把 b50 打成错误卡
            return ()
        cards = []
        for bucket, index_1based, info in self._draw_order:
            constant = getattr(info, "ds", 0)
            ra = getattr(info, "ra", None)
            cards.append(card_type(
                bucket=bucket,
                index_1based=int(index_1based),
                song_id=int(info.song_id),
                chart_type=str(info.type),
                level_index=int(info.level_index),
                title=str(info.title),
                achievement=float(info.achievements),
                # 回填**之后**的 ds（落雪 payload 没有 ds，generate() 里按本地曲库
                # 补）；补不上就是 0/None → 传 None，由消费侧跳过该卡并记日志。
                constant=float(constant) if constant else None,
                ra=int(ra) if ra is not None else None,
            ))
        return tuple(cards)

    async def draw(self) -> Image.Image:
        logo = Image.open(maidir / 'logo.png').resize((249, 120))
        dx_rating = Image.open(maidir / f'UI_CMN_DXRating_{self._findRaPic()}.png').resize((186, 35))
        Name = Image.open(maidir / 'Name.png')
        MatchLevel = Image.open(maidir / self._findMatchLevel()).resize((80, 32))
        ClassLevel = Image.open(maidir / 'UI_FBR_Class_00.png').resize((90, 54))
        rating = Image.open(maidir / 'UI_CMN_Shougou_Rainbow.png').resize((270, 27))

        self._im.alpha_composite(logo, (14, 60))
        
        plate = Image.open(maidir / 'UI_Plate_300501.png').resize((800, 130))
        if self.plate and self.plate.isdigit():
            plate_cache_path = platedir / f"{self.plate}_lxns.png"
            if plate_cache_path.exists():
                try:
                    plate = Image.open(plate_cache_path).convert('RGBA').resize((800, 130))
                except Exception as e:
                    log.warning(f"加载缓存的牌子图片失败: {e}")
            else:
                try:
                    async with cffi_requests.AsyncSession(impersonate="chrome110") as client:
                        res = await client.get(f"https://assets2.lxns.net/maimai/plate/{self.plate}.png", timeout=15)
                    if res.status_code == 200 and not res.content.startswith(b'<'):
                        downloaded_plate = Image.open(BytesIO(res.content)).convert('RGBA')
                        downloaded_plate.save(plate_cache_path, format='PNG')
                        plate = downloaded_plate.resize((800, 130))
                except Exception as e:
                    log.warning(f"下载落雪牌子({self.plate})失败: {e}")
        self._im.alpha_composite(plate, (300, 60))
        
        icon = Image.open(maidir / 'UI_Icon_309503.png').resize((120, 120))
        if getattr(self, 'lxns_icon', None) and self.lxns_icon.isdigit():
            icon_cache_path = icondir / f"{self.lxns_icon}.png"
            if icon_cache_path.exists():
                try:
                    icon = Image.open(icon_cache_path).convert('RGBA').resize((120, 120))
                except Exception as e:
                    log.warning(f"加载缓存的头像图片失败: {e}")
            else:
                try:
                    async with cffi_requests.AsyncSession(impersonate="chrome110") as client:
                        res = await client.get(f"https://assets2.lxns.net/maimai/icon/{self.lxns_icon}.png", timeout=15)
                    if res.status_code == 200 and not res.content.startswith(b'<'):
                        downloaded_icon = Image.open(BytesIO(res.content)).convert('RGBA')
                        downloaded_icon.save(icon_cache_path, format='PNG')
                        icon = downloaded_icon.resize((120, 120))
                except Exception as e:
                    log.warning(f"下载落雪头像({self.lxns_icon})失败: {e}")
        elif self.qqid:
            try:
                qqLogo = Image.open(BytesIO(await maiApi.qqlogo(qqid=self.qqid)))
                icon = qqLogo.convert('RGBA').resize((120, 120))
            except Exception as e:
                log.warning(f"获取QQ头像失败(qqid={self.qqid}): {e}")
        self._im.alpha_composite(icon, (305, 65))
                
        self._im.alpha_composite(dx_rating, (435, 72))
        Rating = f'{self.Rating:05d}'
        for n, i in enumerate(Rating):
            self._im.alpha_composite(
                Image.open(maidir / f'UI_NUM_Drating_{i}.png').resize((17, 20)), (520 + 15 * n, 80)
            )
        self._im.alpha_composite(Name, (435, 115))
        self._im.alpha_composite(MatchLevel, (625, 120))
        self._im.alpha_composite(ClassLevel, (620, 60))
        self._im.alpha_composite(rating, (435, 160))

        self._sy.draw(445, 135, 25, self.userName, (0, 0, 0, 255), 'lm', char_spacing=-2)
        sdrating, dxrating = sum([_.ra for _ in self.sdBest]), sum([_.ra for _ in self.dxBest])
        
        if self.is_ap:
            self._tb.draw(570, 172, 17, f'AP35: {sdrating} + AP15: {dxrating} = {sdrating + dxrating}', (0, 0, 0, 255), 'mm', 3, (255, 255, 255, 255))
        else:
            self._tb.draw(570, 172, 17, f'B35: {sdrating} + B15: {dxrating} = {self.Rating}', (0, 0, 0, 255), 'mm', 3, (255, 255, 255, 255))

        draw_attribution(self._sy, self._im.size[0], 1570, self.source, self.text_color)

        # 桶语义（唯一依据 libraries/maimaidx_merge.py:11-12）：sd/standard = 旧版本
        # 乐曲 B35，dx = 现版本乐曲 B15 —— 按版本划分，**不是** SD/DX 谱面类型。
        self.whiledraw(self.sdBest, False, bucket="b35")
        self.whiledraw(self.dxBest, True, bucket="b15")

        return self._im

def dxScore(dx: int) -> int:
    if dx <= 85: return 0
    elif dx <= 90: return 1
    elif dx <= 93: return 2
    elif dx <= 95: return 3
    elif dx <= 97: return 4
    else: return 5

def getCharWidth(o: int) -> int:
    widths = [
        (126, 1), (159, 0), (687, 1), (710, 0), (711, 1), (727, 0), (733, 1), (879, 0), (1154, 1), (1161, 0),
        (4347, 1), (4447, 2), (7467, 1), (7521, 0), (8369, 1), (8426, 0), (9000, 1), (9002, 2), (11021, 1),
        (12350, 2), (12351, 1), (12438, 2), (12442, 0), (19893, 2), (19967, 1), (55203, 2), (63743, 1),
        (64106, 2), (65039, 1), (65059, 0), (65131, 2), (65279, 1), (65376, 2), (65500, 1), (65510, 2),
        (120831, 1), (262141, 2), (1114109, 1),
    ]
    if o == 0xe or o == 0xf: return 0
    for num, wid in widths:
        if o <= num: return wid
    return 1

def coloumWidth(s: str) -> int:
    res = 0
    for ch in s: res += getCharWidth(ord(ch))
    return res

def changeColumnWidth(s: str, length: int) -> str:
    res = 0
    sList = []
    for ch in s:
        res += getCharWidth(ord(ch))
        if res <= length: sList.append(ch)
    return ''.join(sList)

@overload
def computeRa(ds: float, achievement: float) -> int: ...
@overload
def computeRa(ds: float, achievement: float, *, onlyrate: bool = False) -> str: ...
@overload
def computeRa(ds: float, achievement: float, *, israte: bool = False) -> Tuple[int, str]: ...

def computeRa(ds: float, achievement: float, *, onlyrate: bool = False, israte: bool = False) -> Union[int, str, Tuple[int, str]]:
    if achievement < 50: baseRa, rate = 7.0, 'D'
    elif achievement < 60: baseRa, rate = 8.0, 'C'
    elif achievement < 70: baseRa, rate = 9.6, 'B'
    elif achievement < 75: baseRa, rate = 11.2, 'BB'
    elif achievement < 80: baseRa, rate = 12.0, 'BBB'
    elif achievement < 90: baseRa, rate = 13.6, 'A'
    elif achievement < 94: baseRa, rate = 15.2, 'AA'
    elif achievement < 97: baseRa, rate = 16.8, 'AAA'
    elif achievement < 98: baseRa, rate = 20.0, 'S'
    elif achievement < 99: baseRa, rate = 20.3, 'Sp'
    elif achievement < 99.5: baseRa, rate = 20.8, 'SS'
    elif achievement < 100: baseRa, rate = 21.1, 'SSp'
    elif achievement < 100.5: baseRa, rate = 21.6, 'SSS'
    else: baseRa, rate = 22.4, 'SSSp'

    if israte: data = (math.floor(ds * (min(100.5, achievement) / 100) * baseRa), rate)
    elif onlyrate: data = rate
    else: data = math.floor(ds * (min(100.5, achievement) / 100) * baseRa)
    return data

# ============================================================
# B50 锐评附录（任务 b50-critique-merge · P1b）
# ============================================================
# 画布所有权与编码**留在本仓库**：coach 只交一条已缩放到 ctx.width 的 RGBA PNG，
# 我们把它拼在原图下方，再走原来的 image_to_base64。附录是附加区、b50 是主功能，
# 所以这条路径上任何失败都只降级成「原图 +（用户主动要锐评时）一句提示」：
#   查表抛异常 / coach 没注册 / 总闸关闭 / 返回 None / render_appendix 抛异常 /
#   8s 超时 / 返回类型不合 / 宽度不等于 ctx.width / 解码或拼接失败 /
#   旧版 amia_core 缺 B50CardPosition、B50AppendixContext 导出 / 组装 ctx 抛异常。
# 查表是 **call-time**（不是 load-time），这样两侧 import 顺序完全无关。
_APPENDIX_TIMEOUT_SEC = 8.0
"""附录总预算（设计稿 §2.5）：超时即降级，绝不把 b50 的回复拖长。"""
_APPENDIX_DEGRADE_NOTICE = "（锐评附录这次没能生成，图片按原样发出）"
_APPENDIX_DISABLED_NOTICE = "（锐评附录当前未启用，图片按原样发出）"
_APPENDIX_ABSENT_NOTICE = "（锐评功能当前不可用：coach 插件不在场，图片按原样发出）"
"""coach 缺席时**由调用方**补的话术（P5b · m1）。

``generate()`` 对「provider 缺席」保持静默（硬线：缺席路径逐字节相等、零话术），
所以「用户主动打了锐评标记但 coach 不在场」这句提示由 ``mai_score`` 在拿到空
notice 后用 ``appendix_provider_available()`` 判定后自行补上 —— notice 机制本来
就是给调用方决定说不说。"""


_APPENDIX_SEAM_BAND_PX = 24
"""采样**画布最下方那条带**的高度（px）：附录条就接在这条边下面，衔接口径以它为准。"""

_APPENDIX_SAMPLE_MAX_POINTS = 1024
"""单次区域采样的点数上限（≈32×32）。附录只要一个均色，不需要逐像素。"""


def _mean_rgb_over(
    source: Image.Image,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    *,
    max_points: int = _APPENDIX_SAMPLE_MAX_POINTS,
) -> Optional[Tuple[int, int, int, int]]:
    """对 ``source`` 的矩形区域按网格步长**只读**取样求均色 → RGBA；不合 → None。

    ★ 只调 ``getpixel`` / ``size``，不 crop、不 paste、不 draw，也不返回任何图像对象：
    原画布一个像素都不会被改动，编码路径因此逐字节不变（b50 是主功能，附录是附加区）。
    """
    width, height = source.size
    if x1 <= x0 or y1 <= y0 or x0 >= width or y0 >= height or x1 <= 0 or y1 <= 0:
        return None  # 空区域或完全越界：宁可没有颜色，也不拿区域外的像素凑一个
    xa, xb = max(0, min(int(x0), width - 1)), max(0, min(int(x1), width))
    ya, yb = max(0, min(int(y0), height - 1)), max(0, min(int(y1), height))
    if xb <= xa or yb <= ya:
        return None
    side = max(1, int(math.sqrt(max(1, int(max_points)))))
    step_x = max(1, (xb - xa) // side)
    step_y = max(1, (yb - ya) // side)
    red = green = blue = hits = 0
    for y in range(ya, yb, step_y):
        for x in range(xa, xb, step_x):
            pixel = source.getpixel((x, y))
            if len(pixel) >= 4 and pixel[3] < 8:
                continue  # 全透明处不参与均色（否则会把底色算成 0）
            red += pixel[0]
            green += pixel[1]
            blue += pixel[2]
            hits += 1
    if hits == 0:
        return None
    return (round(red / hits), round(green / hits), round(blue / hits), 255)


def _sample_background_palette(draw_best: "DrawBest"):
    """从**出图侧自己实际使用的背景图**采样调色板（只读，不改任何像素）。

    两路口径：
    - ``base_rgb``：``maidir/b50_bg.png`` 素材本体 —— ``DrawBest.__init__`` 正是拿它
      当画布（``:210``），所以它就是「实际使用的背景图」。素材不在 → None。
    - ``seam_rgb``：当前画布最下方 ``_APPENDIX_SEAM_BAND_PX`` 那条带的均色 —— 附录条
      要相接的那条边，画布到这一步已经是「背景 + 已绘卡」的最终像素。

    ★ 只在 provider 在场时才会被调到（``_render_appendix_png`` 先查表、后构造 ctx），
    coach 缺席路径连一次 ``getpixel`` 都不发生 → 输出与接入附录前逐字节相等。
    ★ 旧版 amia_core 没有 ``B50AppendixPalette`` 导出 → 返回 None，ctx 照常构造；
      采样本身任何异常也只是「没有采样色」，绝不把附录带崩。
    """
    palette_type = getattr(core, "B50AppendixPalette", None) if core is not None else None
    if palette_type is None:
        return None
    base_rgb = None
    try:
        bg_path = maidir / 'b50_bg.png'
        if bg_path.is_file():
            with Image.open(bg_path) as bg:
                bg.load()
                sample = bg if bg.mode in ("RGB", "RGBA") else bg.convert("RGBA")
                base_rgb = _mean_rgb_over(sample, 0, 0, sample.size[0], sample.size[1])
    except Exception as exc:  # noqa: BLE001 - 采样失败只是没有调色板，不影响出图
        log.debug(f"[b50] 锐评附录背景素材采样失败（按无调色板处理）: {exc!r}")
    seam_rgb = None
    try:
        canvas = draw_best._im
        width, height = canvas.size
        seam_rgb = _mean_rgb_over(canvas, 0, max(0, height - _APPENDIX_SEAM_BAND_PX), width, height)
    except Exception as exc:  # noqa: BLE001
        log.debug(f"[b50] 锐评附录画布接缝采样失败（按无调色板处理）: {exc!r}")
    if base_rgb is None and seam_rgb is None:
        return None
    return palette_type(base_rgb=base_rgb, seam_rgb=seam_rgb)


def _ctx_accepts(ctx_type, field: str) -> bool:
    """ctx 类型是否接受某个新字段（palette / identity）。

    旧版 amia_core 的 ``B50AppendixContext`` 没有这些字段，多传一个关键字就是
    TypeError → 整条附录白丢（tests 的 ``_LegacyCtx`` 钉的就是这条）。dataclass
    看字段表，普通类看构造签名；两者都问不出来 → 保守按「不接受」。
    """
    if field in getattr(ctx_type, "__dataclass_fields__", {}):
        return True
    try:
        return field in inspect.signature(ctx_type).parameters
    except (TypeError, ValueError):
        return False


def _appendix_identity(draw_best: "DrawBest") -> Optional[str]:
    """被查询对象的稳定标识（P5b）：按 QQ 查 → ``qqid`` 十进制串；按昵称查 → 归一后的昵称。

    ``generate()`` 里 ``username`` 一旦给出就把 ``qqid`` 置 None，所以两个分支互斥；
    ``userName`` 是上游返回的玩家昵称（按昵称查时它就是归一后的那个名字）。
    两者都拿不到 → None，消费侧回落「无身份」路径（全量回退不触发、节流不生效）。
    """
    qqid = getattr(draw_best, "qqid", None)
    if qqid is not None:
        text = str(qqid).strip()
        if text:
            return text
    name = str(getattr(draw_best, "userName", "") or "").strip()
    return name or None


def appendix_provider_available() -> bool:
    """coach 附录 capability 是否在场（供调用方决定要不要补一句「锐评不可用」）。

    ``generate()`` 对缺席保持静默（硬线：缺席路径逐字节相等、零话术），所以
    「用户主动要锐评但 coach 不在场」这句提示只能由调用方在拿到空 notice 后自己
    判定 —— 见 ``_APPENDIX_ABSENT_NOTICE``。查表异常按「不在场」处理（与
    ``_render_appendix_png`` 的静默降级同方向）。
    """
    if core is None:
        return False
    try:
        return core.registry.get_capability_provider(B50_APPENDIX_PROVIDER) is not None
    except Exception as exc:  # noqa: BLE001
        log.debug(f"[b50] 锐评附录在场判定失败，按不在场处理: {exc!r}")
        return False


def appendix_absent_notice() -> str:
    """「用户主动要锐评但 coach 不在场」该补的话术；coach 在场 → 空串（m1）。

    调用方（``mai_score``）只在用户打了锐评标记、且 ``generate()`` 没给任何
    notice 时才用它 —— 裸 ``b50`` 的文字必须与改动前逐字一致。
    """
    return "" if appendix_provider_available() else _APPENDIX_ABSENT_NOTICE


def _build_appendix_context(draw_best: "DrawBest"):
    """按契约组装 ``B50AppendixContext``；契约不可用（core 为 None 或旧版缺导出）、
    图上一张卡都没有 → None。"""
    ctx_type = getattr(core, "B50AppendixContext", None) if core is not None else None
    if ctx_type is None:
        return None
    cards = draw_best.b50_cards()
    if not cards:
        return None
    width, height = draw_best._im.size
    # 只有 ctx 类型真的接受这些新字段才传：旧版 amia_core 的 ctx 没有 palette /
    # identity，多传一个关键字会 TypeError → 整条附录白丢。
    extra = {}
    palette = _sample_background_palette(draw_best)
    if palette is not None and _ctx_accepts(ctx_type, "palette"):
        extra["palette"] = palette
    identity = _appendix_identity(draw_best)
    if identity is not None and _ctx_accepts(ctx_type, "identity"):
        extra["identity"] = identity
    return ctx_type(
        cards=cards,
        # 渲染侧宽度一律用它，禁止硬编码 1400
        width=int(width),
        canvas_height=int(height),
        nickname=str(draw_best.userName or ""),
        total_rating=int(draw_best.Rating or 0),
        title_font=SIYUAN,
        body_font=TBFONT,
        accent_rgb=tuple(ScoreBaseImage.text_color),
        generated_on=date.today().isoformat(),
        **extra,
    )


def _take_provider_notice(provider, ctx) -> str:
    """问渲染侧要一句**可转述**的话（可选扩展 ``take_notice``，P5b）。

    旧版 coach 没有这个方法 → 空串（调用方用默认降级话术）；本方法自身抛异常也
    只当没有话术 —— 它就在降级路径上，绝不许把降级再降级成崩溃。
    """
    take = getattr(provider, "take_notice", None)
    if not callable(take):
        return ""
    try:
        return str(take(ctx) or "").strip()
    except Exception as exc:  # noqa: BLE001
        log.debug(f"[b50] 锐评附录 take_notice 失败，按无话术处理: {exc!r}")
        return ""


async def _render_appendix_png(draw_best: "DrawBest") -> Tuple[Optional[bytes], str]:
    """查 capability 表 → 渲染附录条。返回 ``(PNG bytes | None, 降级提示)``。

    ★ 本函数**绝不向上抛异常**：出图路径的唯一事实是「拿到 bytes 就拼，否则原图」。
    """
    if core is None:
        log.debug("[b50] 锐评附录未接：amia_core 契约不可用，按原样出图")
        return None, ""
    try:
        provider = core.registry.get_capability_provider(B50_APPENDIX_PROVIDER)
    except Exception as exc:  # noqa: BLE001
        log.debug(f"[b50] 锐评附录查表失败，按原样出图: {exc!r}")
        return None, ""
    if provider is None:
        # coach 缺席：静默降级（提示留空串），输出必须与接入前逐字节相等
        return None, ""
    try:
        ctx = _build_appendix_context(draw_best)
    except Exception as exc:  # noqa: BLE001
        # 组装上下文本身出问题（旧版契约签名不合、画布属性缺失…）也只是没有附录
        log.debug(f"[b50] 锐评附录上下文构造失败，按原样出图: {exc!r}")
        return None, ""
    if ctx is None:
        return None, ""
    try:
        # maimaidx 只问这一个方法，不知道背后有配置这回事
        if not provider.is_enabled():
            return None, _APPENDIX_DISABLED_NOTICE
    except Exception as exc:  # noqa: BLE001
        log.warning(f"[b50] 锐评附录 is_enabled() 异常，按原样出图: {exc!r}")
        return None, _APPENDIX_DEGRADE_NOTICE
    try:
        with anyio.fail_after(_APPENDIX_TIMEOUT_SEC):
            png = await provider.render_appendix(ctx)
    except TimeoutError:
        log.warning(f"[b50] 锐评附录渲染超过 {_APPENDIX_TIMEOUT_SEC}s，按原样出图")
        return None, _APPENDIX_DEGRADE_NOTICE
    except Exception as exc:  # noqa: BLE001
        log.warning(f"[b50] 锐评附录渲染抛异常，按原样出图: {exc!r}")
        return None, _APPENDIX_DEGRADE_NOTICE
    if png is None:
        # 契约规定 None = 渲染侧自行降级，本来就不该出附录。
        # ★ P5b：渲染侧可以给一句可转述的话（节流 / 排队中），拿不到就用默认话术。
        return None, _take_provider_notice(provider, ctx) or _APPENDIX_DEGRADE_NOTICE
    if not isinstance(png, (bytes, bytearray)):
        log.warning(f"[b50] 锐评附录返回类型不合契约: {type(png).__name__}")
        return None, _APPENDIX_DEGRADE_NOTICE
    return bytes(png), ""


def _paste_appendix(base: Image.Image, png: bytes) -> Image.Image:
    """把附录条拼在原图**下方**，返回新画布。尺寸不合契约 → ``ValueError``。"""
    appendix = Image.open(BytesIO(png))
    appendix.load()
    if appendix.mode != "RGBA":
        appendix = appendix.convert("RGBA")
    width, height = base.size
    if appendix.size[0] != width:
        raise ValueError(f"附录宽度 {appendix.size[0]} != 画布宽度 {width}")
    if appendix.size[1] <= 0:
        raise ValueError(f"附录高度不合契约: {appendix.size[1]}")
    canvas = Image.new("RGBA", (width, height + appendix.size[1]), (255, 255, 255, 255))
    canvas.alpha_composite(base.convert("RGBA"), (0, 0))
    canvas.alpha_composite(appendix, (0, height))
    return canvas


async def generate(
    qqid: Optional[int] = None,
    username: Optional[str] = None,
    *,
    is_ap: bool = False,
    appendix: bool = True,
) -> Tuple[MessageSegment, str]:
    """出 B50/AP50 图，返回 ``(图片段, 降级提示)``；提示为空串表示一切正常。

    ``appendix=False``（ap50 路径、「b50 无锐评」）时**完全不查表**，输出与接入
    附录前逐字节相同。提示只在调用方决定要不要说给用户听（mai_score 仅在用户
    主动打了「锐评/点评」标记时才附上），所以裸 ``b50`` 的文字永远不变。
    """
    if username:
        qqid = None
    userinfo, meta = await maiApi.query_user_b50_merged(qqid=qqid, username=username, is_ap=is_ap)

    for chart in (userinfo.charts.sd or []) + (userinfo.charts.dx or []):
        music = _find_local_chart_music(chart.song_id, chart.type)
        if music:
            chart.song_id = int(music.id)
            if 0 <= chart.level_index < len(music.ds):
                chart.ds = music.ds[chart.level_index]
        # DX 谱面可能使用 song_id + 10000 作为独立 ID
        if not chart.ds and chart.type.lower() == 'dx':
            dx_music = mai.total_list.by_id(str(chart.song_id + 10000))
            if dx_music:
                chart.song_id = int(dx_music.id)
                if 0 <= chart.level_index < len(dx_music.ds):
                    chart.ds = dx_music.ds[chart.level_index]
        if not chart.ds:
            log.warning(f"[b50] 未找到定数: song_id={chart.song_id}, level_index={chart.level_index}, type={chart.type}")

    draw_best = DrawBest(userinfo, qqid, is_ap, effective_source(meta))
    image = await draw_best.draw()
    notice = ""
    if appendix:
        png, notice = await _render_appendix_png(draw_best)
        if png is not None:
            try:
                # ★ PIL 同步阻塞（整画布 RGBA 复制 + 更高画布重编码）→ 必须进线程，
                # 禁止在事件循环里跑（与 coach 侧 render_strip 同纪律）。
                image = await anyio.to_thread.run_sync(_paste_appendix, image, png)
            except Exception as exc:  # noqa: BLE001 - 尺寸不合/解码失败都回原图
                log.warning(f"[b50] 锐评附录拼接失败，按原样出图: {exc!r}")
                notice = _APPENDIX_DEGRADE_NOTICE
    # ★ 编码同样同步阻塞（PNG 编码 + base64）→ 一并进线程
    # 压缩到 90% 质量（用户定稿）：JPEG 编码，RGBA 铺白底在 image_to_base64 内处理
    def _encode() -> str:
        return image_to_base64(image, format="JPEG", quality=90)

    encoded = await anyio.to_thread.run_sync(_encode)
    return MessageSegment.image(encoded), notice
