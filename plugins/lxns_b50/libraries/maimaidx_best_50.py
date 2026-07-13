import math
import traceback
import httpx
from curl_cffi import requests as cffi_requests
from io import BytesIO
from typing import Tuple, Union, overload, List, Optional

from nonebot.adapters.onebot.v11 import MessageSegment
from PIL import Image, ImageDraw
from loguru import logger as log

from ..config import *
from .image import DrawText, image_to_base64, music_picture
from .maimaidx_api_data import maiApi
from .maimaidx_error import *
from .maimaidx_model import ChartInfo, PlayInfoDefault, PlayInfoDev, UserInfo
from .maimaidx_music import mai

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
    
    def whiledraw(self, data: Union[List[ChartInfo], List[PlayInfoDefault], List[PlayInfoDev]], dx: bool, height: int = 0) -> None:
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
            
            _music = mai.total_list.by_id(str(info.song_id))
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

    def __init__(self, UserInfo: UserInfo, qqid: Optional[Union[int, str]] = None, is_ap: bool = False) -> None:
        super().__init__(Image.open(maidir / 'b50_bg.png').convert('RGBA'))
        self.userName = UserInfo.nickname
        self.plate = UserInfo.plate
        self.lxns_icon = UserInfo.username
        self.addRating = UserInfo.additional_rating
        self.Rating = UserInfo.rating
        
        self.sdBest = [c for c in UserInfo.charts.sd if c.level_index <= 4]
        self.dxBest = [c for c in UserInfo.charts.dx if c.level_index <= 4]
        
        self.qqid = qqid
        self.is_ap = is_ap

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

        self._sy.draw(700, 1570, 27, 'Amia_晓山瑞希', self.text_color, 'mm', 5, (255, 255, 255, 255))

        self.whiledraw(self.sdBest, False)
        self.whiledraw(self.dxBest, True)

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

async def generate(qqid: Optional[int] = None, username: Optional[str] = None, is_ap: bool = False) -> Union[MessageSegment, str]:
    try:
        if username: qqid = None
        userinfo = await maiApi.query_user_b50(qqid=qqid, username=username, is_ap=is_ap)
        
        for chart in userinfo.charts.sd + userinfo.charts.dx:
            music = mai.total_list.by_id(str(chart.song_id))
            if music:
                chart.song_id = int(music.id)
                try:
                    chart.ds = music.ds[chart.level_index]
                except (IndexError, TypeError):
                    if isinstance(music.get('difficulties'), dict):
                        for diff_list in music.difficulties.values():
                            for d in diff_list:
                                if d.get('difficulty') == chart.level_index:
                                    chart.ds = d.get('level_value', 0)
                                    break
                            if chart.ds:
                                break
            # DX 谱面可能使用 song_id + 10000 作为独立 ID
            if not chart.ds and chart.type.lower() == 'dx':
                dx_music = mai.total_list.by_id(str(chart.song_id + 10000))
                if dx_music:
                    chart.song_id = int(dx_music.id)
                    try:
                        chart.ds = dx_music.ds[chart.level_index]
                    except (IndexError, TypeError):
                        pass
            if not chart.ds:
                log.warning(f"[b50] 未找到定数: song_id={chart.song_id}, level_index={chart.level_index}, type={chart.type}")

        draw_best = DrawBest(userinfo, qqid, is_ap)
        msg = MessageSegment.image(image_to_base64(await draw_best.draw()))
    except (UserNotFoundError, UserDisabledQueryError) as e:
        msg = str(e)
    except Exception as e:
        log.error(traceback.format_exc())
        msg = f'未知错误：{type(e)}\n请联系Bot管理员'
    return msg
