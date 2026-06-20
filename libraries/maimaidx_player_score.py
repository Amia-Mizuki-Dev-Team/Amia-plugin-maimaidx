import random
import time
import traceback
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, DefaultDict, Tuple, List, Dict, Union, Optional

import pyecharts.options as opts
from nonebot.adapters.onebot.v11 import MessageSegment
from pyecharts.charts import Pie

from ..config import *
from .image import *
from .maimaidx_api_data import *
from .maimaidx_best_50 import ScoreBaseImage, changeColumnWidth, coloumWidth, computeRa
from .maimaidx_error import UserNotFoundError, UserDisabledQueryError, UserNotExistsError
from .maimaidx_model import ChartInfo, PlanInfo, PlayInfoDefault, PlayInfoDev, RaMusic
from .maimaidx_music import Music, mai
from .maimaidx_music_info import draw_music_info
from .tool import run_chrome_to_base64

@dataclass
class RiseScore:
    """完美平替老版本的上分数据模型，供底部代码进行实例化"""
    song_id: int
    title: str
    type: str
    level_index: int
    ds: float
    ra: int
    rate: str
    achievements: float
    oldra: int = 0
    oldrate: str = ""
    oldachievements: float = 0.0

Filter = Tuple[
    List[PlayInfoDefault],
    List[PlayInfoDefault],
    List[PlayInfoDefault],
    List[PlayInfoDefault],
    List[PlayInfoDefault]
]
Condition = Callable[[PlayInfoDefault], bool]


async def music_global_data(music: Music, level_index: int) -> MessageSegment:
    """
    绘制曲目游玩详情
    
    Params:
        `music`: :class:Music
        `level_index`: 难度
    Returns:
        `MessageSegment`
    """
    stats = music.stats[level_index]
    fc_data_pair = [list(z) for z in zip([c.upper() if c else 'Not FC' for c in [''] + comboRank], stats.fc_dist)]
    acc_data_pair = [list(z) for z in zip([s.upper() for s in scoreRank], stats.dist)]

    initopts = opts.InitOpts(width='1000px', height='800px', bg_color='#fff', js_host='./')
    labelopts = opts.LabelOpts(
        position='outside',
        formatter='{a|{a}}{abg|}\n{hr|}\n {b|{b}: }{c}  {per|{d}%}  ',
        background_color='#eee',
        border_color='#aaa',
        border_width=1,
        border_radius=4,
        rich={
            'a': {'color': '#999', 'lineHeight': 22, 'align': 'center'},
            'abg': {
                'backgroundColor': '#e3e3e3',
                'width': '100%',
                'align': 'right',
                'height': 22,
                'borderRadius': [4, 4, 0, 0],
            },
            'hr': {
                'borderColor': '#aaa',
                'width': '100%',
                'borderWidth': 0.5,
                'height': 0,
            },
            'b': {'fontSize': 16, 'lineHeight': 33},
            'per': {
                'color': '#eee',
                'backgroundColor': '#334455',
                'padding': [2, 4],
                'borderRadius': 2,
            },
        },
    )
    titleopts = opts.TitleOpts(
        title=f'{music.id} {music.title} 「{diffs[level_index]}」',
        pos_left='center',
        pos_top='20',
        title_textstyle_opts=opts.TextStyleOpts(color='#2c343c'),
    )
    legendopts = opts.LegendOpts(pos_left=15, pos_top=10, orient='vertical')

    pie = Pie(initopts)
    pie.add('全连等级', fc_data_pair, radius=[0, '30%'], label_opts=labelopts)
    pie.add('达成率等级', acc_data_pair, radius=['50%', '70%'], is_clockwise=True, label_opts=labelopts)
    pie.set_global_opts(title_opts=titleopts, legend_opts=legendopts)
    pie.set_series_opts(tooltip_opts=opts.TooltipOpts(trigger='item', formatter='{a} <br/>{b}: {c} ({d}%)'))
    pie.render(str(pie_html_file))
    base64 = await run_chrome_to_base64()

    return MessageSegment.image(base64)


class DrawScore(ScoreBaseImage):
    
    def __init__(self, image: Image.Image = None) -> None:
        super().__init__(image)
        self._im.alpha_composite(self.aurora_bg)
        self._im.alpha_composite(self.shines_bg, (34, 0))
        self._im.alpha_composite(self.rainbow_bg, (319, self._im.size[1] - 643))
        self._im.alpha_composite(self.rainbow_bottom_bg, (100, self._im.size[1] - 343))
        for h in range((self._im.size[1] // 358) + 1):
            self._im.alpha_composite(self.pattern_bg, (0, (358 + 7) * h))

    def whilepic(self, data: List[RaMusic], y: int = 200):
        """
        循环绘制谱面
        
        Params:
            `data`: `谱面数据`
            `y`: `Y轴偏移`
        """
        dy = 65
        x = 0
        for n, v in enumerate(data):
            if n % 20 == 0:
                x = 55
                y += dy if n != 0 else 0
            else:
                x += 65
            cover = get_cover_image(v.id, (55, 55))
            self._im.alpha_composite(cover, (x, y))
            self._im.alpha_composite(self.id_diff[int(v.lv)], (x, y + 45))
            self._tb.draw(x + 27, y + 50, 10, v.id, self.t_color[int(v.lv)], 'mm')
    
    def whilerisepic(self, data: List[RiseScore], low_score: int, isdx: bool):
        """
        循环绘制上分推荐数据
        
        Params:
            `data`: `上分数据`
            `low_score`: `最低分`
            `isdx`: `是否DX版本`
        """
        y = 120
        for index, _d in enumerate(data):
            x = 200 if isdx else 700
            y += 140 if index != 0 else 0
            
            rate = get_asset_image(f'UI_TTR_Rank_{_d.rate}.png', (63, 28))
            
            self._im.alpha_composite(self._rise[_d.level_index], (x + 30, y))
            self._im.alpha_composite(get_cover_image(_d.song_id, (80, 80)), (x + 55, y + 40))
            type_name = 'SD' if _d.type.lower() == 'standard' else _d.type.upper()
            self._im.alpha_composite(get_asset_image(f'{type_name}.png', (60, 22)), (x + 240, y + 114))
            if _d.oldrate:
                oldrate = get_asset_image(f'UI_TTR_Rank_{_d.oldrate}.png', (63, 28))
                self._im.alpha_composite(oldrate, (x + 145, y + 82))
            self._im.alpha_composite(rate, (x + 305, y + 82))
            
            title = _d.title
            if coloumWidth(title) > 26:
                title = changeColumnWidth(title, 25) + '...'
            self._sy.draw(x + 142, y + 44, 17, title, self.t_color[_d.level_index], 'lm')
            self._tb.draw(x + 145, y + 124, 18, f'ID: {_d.song_id}', self.id_color[_d.level_index], 'lm')
            self._tb.draw(x + 210, y + 71, 25, f'{_d.oldachievements:.4f}%', self.t_color[_d.level_index], anchor='mm')
            self._tb.draw(x + 245, y + 96, 17, f'Ra: {_d.oldra}', self.t_color[_d.level_index], anchor='mm')
            self._tb.draw(x + 370, y + 71, 25, f'{_d.achievements:.4f}%', self.t_color[_d.level_index], anchor='mm')
            self._tb.draw(x + 415, y + 96, 17, f'Ra: {_d.ra}', self.t_color[_d.level_index], anchor='mm')
            self._tb.draw(x + 315, y + 124, 18, f'ds:{_d.ds}', self.id_color[_d.level_index], anchor='lm')
            if _d.oldra > low_score:
                new_ra = _d.ra - _d.oldra
            else:
                new_ra = _d.ra - low_score
            self._tb.draw(x + 390, y + 124, 18, f'Ra +{new_ra}', self.id_color[_d.level_index], 'lm')
         
    def draw_rise(self, sd: List[RiseScore], sd_score: int, dx: List[RiseScore], dx_score: int) -> Image.Image:
        """
        绘制上分数据表
        
        Params:
            `sd`: `旧版本谱面`
            `sd_score`: `旧版本最低分`
            `dx`: `新版本谱面`
            `dx_score`: `新版本最低分`
        Returns:
            `Image.Image`
        """
        title_bg = self.title_bg.copy().resize((273, 80))
        self._im.alpha_composite(title_bg, (314, 30))
        self._sy.draw(450, 68, 18, '旧版本谱面推荐', self.text_color, 'mm')
        self.whilerisepic(sd, sd_score, True)
        self._im.alpha_composite(title_bg, (814, 30))
        self._sy.draw(950, 68, 18, '新版本谱面推荐', self.text_color, 'mm')
        self.whilerisepic(dx, dx_score, False)
        
        height = self._im.size[1]
        self._im.alpha_composite(self.design_bg.resize((800, 72)), (300, height - 110))
        self._sy.draw(700, height - 76, 18, 'Powered By MizukiBot LXNS', self.text_color, 'mm')
        return self._im

    def draw_plan(
        self,
        completed: Union[List[PlayInfoDefault], List[PlayInfoDev]],
        completed_y: int,
        unfinished: Union[List[PlayInfoDefault], List[PlayInfoDev]],
        unfinished_y: int,
        notstarted: List[RaMusic],
        plan: str,
        completed_len: int,
    ) -> Image.Image:
        """
        绘制进度表
        
        Params:
            `completed`: `已完成谱面`
            `completed_y`: `已完成谱面高度`
            `unfinished`: `未完成谱面`
            `unfinished_y`: `未完成谱面高度`
            `notstarted`: `未游玩谱面`
            `plan`: `目标`
            `completed_len`: `已完成谱面数量`
        Returns:
            `Image.Image`
        """
        max = len(completed + unfinished + notstarted)

        self._im.alpha_composite(self.title_lengthen_bg, (475, 30))
        self._im.alpha_composite(self.title_lengthen_bg, (475, 30 + completed_y))
        self._im.alpha_composite(self.title_lengthen_bg, (475, 30 + completed_y + unfinished_y))
        
        self._sy.draw(700, 77, 22, f'已完成谱面「{len(completed)}」个', self.text_color, 'mm')
        self._sy.draw(700, 77 + completed_y, 22, f'未完成谱面「{len(unfinished)}」个', self.text_color, 'mm')
        self._sy.draw(700, 77 + completed_y + unfinished_y, 22, f'未游玩谱面「{len(notstarted)}」个', self.text_color, 'mm')
        
        self.whiledraw(completed[:completed_len], True, 140)
        self.whiledraw(unfinished[:30], True, 140 + completed_y)
        self.whilepic(notstarted[:100], 140 + completed_y + unfinished_y)

        self._im.alpha_composite(self.design_bg, (200, self._im.size[1] - 113))
        pagemsg = f'共计「{max}」个谱面，剩余「{len(unfinished + notstarted)}」个谱面未完成「{plan.upper()}」'
        self._sy.draw(700, self._im.size[1] - 70, 25, pagemsg, self.text_color, 'mm')
        return self._im

    def draw_category(
        self, 
        category: str, 
        data: Union[List[PlayInfoDefault], List[PlayInfoDev], List[RaMusic]],
        page: int = 1, 
        end_page: int = 1
    ) -> Image.Image:
        """
        绘制指定进度表
        
        Params:
            `category`: `类别`
            `data`: `数据`
            `page`: `页数`
            `end_page`: `总页数`
        Returns:
            `Image.Image`
        """
        lendata = len(data)
        newdata = data[(page - 1) * 80: page * 80]
        self._im.alpha_composite(self.title_lengthen_bg, (475, 30))
        if category == 'completed' or category == 'unfinished':
            txt = '已完成' if category == 'completed' else '未完成'
            self._sy.draw(700, 77, 28, f'{txt}谱面', self.text_color, 'mm')
            self.whiledraw(newdata, True, 140)
            self._im.alpha_composite(self.design_bg, (200, self._im.size[1] - 113))
            
            pagemsg = f'{txt}谱面共计「{lendata}」个，'
            pagemsg += f'展示第「{(page - 1) * 80 + 1}-{80 * (page - 1) + len(newdata)}」个，'
            pagemsg += f'当前第「{page} / {end_page}」页'
            self._sy.draw(700, self._im.size[1] - 70, 25, pagemsg, self.text_color, 'mm')
        else:
            self._sy.draw(700, 105, 28, '未游玩谱面', self.text_color, 'mm')
            self.whilepic(data)
            self._im.alpha_composite(self.design_bg, (200, self._im.size[1] - 113))
            self._sy.draw(700, self._im.size[1] - 70, 25, f'未游玩谱面共计「{len(data)}」个', self.text_color, 'mm')
        return self._im
    
    def draw_scorelist(
        self, 
        rating: Union[str, float], 
        data: Union[List[PlayInfoDefault], List[PlayInfoDev]], 
        page: int = 1, 
        end_page: int = 1
    ) -> Image.Image:
        """
        绘制分数列表
        
        Params:
            `rating`: `定数`
            `data`: `数据`
            `page`: `页数`
            `end_page`: `总页数`
        Returns:
            `Image.Image`
        """
        lendata = len(data)
        newdata = data[(page - 1) * 80: page * 80]
        r = len(newdata) // 20 + (0 if len(newdata) % 20 == 0 else 1)
        for n in range(r):
            y = (109 * 4 + 140) * n
            self._im.alpha_composite(self.title_lengthen_bg, (475, 30 + y))
            start = (20 * n + 1) + 80 * (page - 1)
            self._sy.draw(700, 77 + y, 28, f'No.{start}- No.{start + len(newdata[n * 20: (n + 1) * 20]) - 1}', self.text_color, 'mm')
            self.whiledraw(newdata[n * 20: (n + 1) * 20], True, 140 + y)
        self._im.alpha_composite(self.design_bg, (200, self._im.size[1] - 113))
        
        pagemsg = f'「{rating}」共计「{lendata}」个成绩，'
        pagemsg += f'展示第「{(page - 1) * 80 + 1}-{80 * (page - 1) + len(newdata)}」个，'
        pagemsg += f'当前第「{page} / {end_page}」页'
        self._sy.draw(700, self._im.size[1] - 70, 25, pagemsg, self.text_color, 'mm')
        return self._im


def get_rise_score_list(
    old_records: DefaultDict[int, Dict[int, float]],
    type: str, 
    info: List[ChartInfo], 
    level: Optional[str] = None, 
    score: Optional[int] = None
) -> Tuple[List[RiseScore], int]:
    """
    随机获取并智能筛选推荐上分曲目 (避雷并推荐虚高神曲)
    """
    ignore = [m.song_id for m in info if m.achievements >= 100.5]
    if not info:
        return [], 0
    ra = info[-1].ra
    candidates: List[Tuple[RiseScore, float]] = []
    if score is None:
        ss_ds = round(ra / 20.8, 1)
    else:
        ss_ds = round((ra + int(score)) / 20.8, 1)
    sssp_ds = round(ra / 22.4, 1)
    ds = (sssp_ds + 0.1, ss_ds + 0.1)
    version = list(plate_to_dx_version.values())[-2:] if type == 'DX' else list(plate_to_dx_version.values())[:-2]
    musiclist = mai.total_list.filter(level=level, ds=ds, version=version)
    for _m in musiclist:
        if (song_id := int(_m.id)) in ignore:
            continue
        if song_id >= 100000:
            continue
        for index in _m.diff:
            # 获取拟合难度
            fit_diff = None
            if _m.stats and len(_m.stats) > index and _m.stats[index]:
                fit_diff = _m.stats[index].get("fit_diff") if isinstance(_m.stats[index], dict) else getattr(_m.stats[index], "fit_diff", None)
            
            # 过滤严重诈骗地雷曲
            if fit_diff and fit_diff > _m.ds[index] + 0.25:
                continue

            for r in achievementList[-4:]:
                basera, rate = computeRa(_m.ds[index], r, israte=True)
                if basera <= ra:
                    continue
                if score and basera - int(score) < ra:
                    continue
                
                # 计算虚高红利空间 (advantage)
                advantage = 0.0
                if fit_diff:
                    advantage = _m.ds[index] - fit_diff

                if song_id in old_records and index in old_records[song_id]:
                    oldra, oldrate = computeRa(_m.ds[index], old_records[song_id][index], israte=True)
                    if oldra >= basera:
                        continue
                    ss = RiseScore(
                        song_id=song_id,
                        title=_m.title,
                        type=_m.type,
                        level_index=index,
                        ds=_m.ds[index],
                        ra=basera,
                        rate=rate,
                        achievements=r,
                        oldra=oldra,
                        oldrate=oldrate,
                        oldachievements=old_records[song_id][index]
                    )
                else:
                    ss = RiseScore(
                        song_id=song_id,
                        title=_m.title,
                        type=_m.type,
                        level_index=index,
                        ds=_m.ds[index],
                        ra=basera,
                        rate=rate,
                        achievements=r
                    )
                candidates.append((ss, advantage))
                break
    if not candidates:
        return [], 0
    # 按照上分优势降序排序，优先选取易上分神曲
    candidates.sort(key=lambda x: x[1], reverse=True)
    top_candidates = [x[0] for x in candidates[:15]]
    new = random.sample(top_candidates, min(len(top_candidates), 5))
    new.sort(key=lambda x: x.song_id, reverse=True)
    return new, ra


async def rise_score_data(
    qqid: int, 
    username: Optional[str] = None, 
    level: Optional[str] = None, 
    score: Optional[int] = None
) -> Union[MessageSegment, str]:
    """
    上分数据
    
    Params:
        `qqid`: 用户QQ
        `username`: 查分器用户名
        `level`: 定数
        `score`: 分数
    Returns:
        `Union[Image.Image, str]`
    """
    try:
        user = await maiApi.query_user_b50(qqid=qqid, username=username)
        records = await maiApi.query_user_plate(qqid=qqid, username=username, version=list(plate_to_dx_version.values()))
        old_records: DefaultDict[int, Dict[int, float]] = defaultdict(dict)
        for m in records:
            old_records[m.song_id][m.level_index] = m.achievements
        
        sd, sd_low_score = get_rise_score_list(old_records, 'SD', user.charts.sd, level, score)
        dx, dx_low_score = get_rise_score_list(old_records, 'DX', user.charts.dx, level, score)
        
        if not sd and not dx:
            return '没有推荐的铺面'
        
        lensd, lendx = len(sd), len(dx)
        
        h = max(lensd, lendx)
        height = h * 140 + 110 + 150
        image = tricolor_gradient(1400, height)
        
        ds = DrawScore(image)
        im = ds.draw_rise(sd, sd_low_score, dx, dx_low_score)
        
        msg = MessageSegment.image(image_to_base64(im.crop((200, 0, 1200, height))))
    except (UserNotFoundError, UserNotExistsError, UserDisabledQueryError) as e:
        msg = str(e)
    except Exception as e:
        log.error(traceback.format_exc())
        msg = f'未知错误：{type(e)}\n请联系Bot管理员'
        
    return msg


def plate_message(
    result: str, 
    plan: str, 
    music_list: List[PlayInfoDefault], 
    played: List[Tuple[int, int]]
) -> Union[MessageSegment, str]:
    """
    Params:
        `result`: 结果
        `plan`: 目标
        `music_list`: 谱面列表
        `played`: 已游玩谱面
    Returns:
        `Union[MessageSegment, str]`
    """
    for n, m in enumerate(music_list):
        self_record = ''
        if (m.song_id, m.level_index) in played:
            if plan in ['将', '者']:
                self_record = f'{m.achievements}%'
            if plan in ['極', '极', '神']:
                self_record = m.fc
            if plan in '舞舞':
                self_record = m.fs
        result += f'No.{n + 1:02d} {f"「{m.song_id}」":>7} {f"「{diffs[m.level_index]}」":>11} 「{m.ds}」 {m.title}  {self_record}\n'
    if len(music_list) > 10:
        result = MessageSegment.image(text_to_bytes_io((result.strip())))
    return result


def draw_plate_grid_image(appellation: str, version: str, plan: str, total_songs: list, completed_songs: set, unfinished_songs_diff: dict) -> MessageSegment:
    num_songs = len(total_songs)
    cols = 10
    rows = math.ceil(num_songs / cols)
    
    cell_size = 90
    spacing = 15
    padding = 40
    
    width = padding * 2 + cols * cell_size + (cols - 1) * spacing
    height = 160 + rows * cell_size + (rows - 1) * spacing + 100
    
    im = Image.new('RGBA', (width, height), (20, 22, 32, 255))
    dr = ImageDraw.Draw(im)
    sy = DrawText(dr, SIYUAN)
    tb = DrawText(dr, TBFONT)
    
    for y in range(height):
        ratio = y / height
        r = int(20 * (1 - ratio) + 30 * ratio)
        g = int(22 * (1 - ratio) + 36 * ratio)
        b = int(32 * (1 - ratio) + 55 * ratio)
        dr.line([(0, y), (width, y)], fill=(r, g, b, 255))
        
    pattern_path = maidir / 'pattern.png'
    if pattern_path.exists():
        try:
            pat = Image.open(pattern_path).convert('RGBA')
            for h in range((height // pat.height) + 1):
                im.alpha_composite(pat, (0, h * pat.height))
        except Exception:
            pass
            
    sy.draw(width // 2, 50, 32, f"🏆 {appellation} 的「{version}{plan}」曲绘进度墙 🏆", (255, 255, 255, 255), 'mm')
    sy.draw(width // 2, 100, 18, f"已完成: {len(completed_songs)}  |  未完成: {num_songs - len(completed_songs)}  |  总曲目: {num_songs}", (170, 190, 220, 255), 'mm')
    
    diff_colors = [
        (111, 212, 61, 255),
        (248, 183, 9, 255),
        (255, 129, 141, 255),
        (159, 81, 220, 255),
        (219, 170, 255, 255)
    ]
    
    check_icon = None
    clear_path = maidir / 'complete_bg_2.png'
    if clear_path.exists():
        try:
            check_icon = Image.open(clear_path).convert('RGBA').resize((cell_size, cell_size))
        except Exception:
            pass
            
    for idx, music in enumerate(total_songs):
        row = idx // cols
        col = idx % cols
        
        x = padding + col * (cell_size + spacing)
        y = 150 + row * (cell_size + spacing)
        
        cover = get_cover_image(music.id, (cell_size, cell_size))
        
        song_id = int(music.id)
        if song_id in completed_songs:
            cover_f = cover.copy()
            r, g, b, a = cover_f.split()
            a = a.point(lambda p: int(p * 0.4))
            cover_f = Image.merge('RGBA', (r, g, b, a))
            im.alpha_composite(cover_f, (x, y))
            
            if check_icon:
                im.alpha_composite(check_icon.resize((24, 24)), (x + cell_size - 28, y + 4))
            else:
                dr.ellipse((x + cell_size - 24, y + 4, x + cell_size - 4, y + 24), fill=(46, 204, 113, 255))
                dr.line([(x + cell_size - 18, y + 14), (x + cell_size - 14, y + 18), (x + cell_size - 8, y + 10)], fill=(255, 255, 255, 255), width=2)
        else:
            im.alpha_composite(cover, (x, y))
            incompletes = unfinished_songs_diff.get(song_id, [3])
            highest_inc = max(incompletes) if incompletes else 3
            border_color = diff_colors[highest_inc]
            dr.rectangle((x, y, x + cell_size, y + cell_size), outline=border_color, width=3)
            tb.draw(x + 6, y + cell_size - 6, 12, str(music.id), (255, 255, 255, 255), 'lb', stroke_width=1, stroke_fill=(0, 0, 0, 255))
            
    sy.draw(width // 2, height - 40, 16, "Powered By MizukiBot lxns_b50", (130, 140, 160, 255), 'mm')
    return MessageSegment.image(image_to_base64(im))


async def player_plate_data(
    qqid: int, 
    username: str, 
    version: str, 
    plan: str
) -> Union[MessageSegment, str]:
    """
    查看牌子进度 (升级后返回视觉化曲绘网格墙)
    """
    if version in platecn:
        version = platecn[version]
    ver, _ver = version_map.get(version, ([plate_to_dx_version.get(version)], version))
    
    try:
        verlist = await maiApi.query_user_plate(qqid=qqid, username=username, version=ver)
    except (UserNotFoundError, UserNotExistsError, UserDisabledQueryError) as e:
        return str(e)
    
    if plan in ['将', '者']:
        achievement = 100 if plan == '将' else 80
        callable_: Condition = lambda x: x.achievements < achievement
    elif plan in ['極', '极']:
        callable_: Condition = lambda x: not x.fc
    elif plan == '舞舞':
        callable_: Condition = lambda x: x.fs not in ['fsd', 'fsdp']
    elif plan  == '神':
        callable_: Condition = lambda x: x.fc not in ['ap', 'app']
    else:
        raise ValueError
    
    unfinished_model_list: Filter = ([], [], [], [], [])
    unfinished: List[Tuple[int, int]] = []
    played: List[Tuple[int, int]] = []
    remaster: List[int] = []
    
    plate_id_list = mai.total_plate_id_list[_ver]
    if _ver in ['舞', '霸']:
        remaster = mai.total_plate_id_list['舞ReMASTER']
        for music in verlist:
            if music.song_id not in plate_id_list:
                continue
            if music.level_index == 4 and music.song_id not in remaster:
                continue
            if callable_(music):
                unfinished.append((music.song_id, music.level_index))
            played.append((music.song_id, music.level_index))
    else:
        for music in verlist:
            if music.song_id not in plate_id_list:
                continue
            if callable_(music):
                unfinished.append((music.song_id, music.level_index))
            played.append((music.song_id, music.level_index))
            
    # 未游玩未完成曲目
    for music in mai.total_list:
        if int(music.id) not in plate_id_list:
            continue
        info = PlayInfoDefault(
            achievements=0,
            level='',
            level_index=0,
            title=music.title,
            type=music.type,
            id=int(music.id)
        )
        range_ = range(5 if version in ['舞', '霸'] and int(music.id) in remaster else 4)
        for level_index in range_:
            if (m := (info.song_id, level_index)) not in played or m in unfinished:
                _info = info.model_copy()
                _info.level = music.level[level_index]
                _info.ds = music.ds[level_index]
                _info.level_index = level_index
                unfinished_model_list[level_index].append(_info)

    basic, advanced, expert, master, re_master = unfinished_model_list
    appellation = username if username else '您'
    
    # 获取所有的曲目对象
    music_objects = mai.total_list.by_id_list(plate_id_list)
    
    # 计算未完成和已完成歌曲
    unfinished_songs_diff = defaultdict(list)
    completed_songs = set()
    for m in music_objects:
        song_id = int(m.id)
        range_ = range(5 if version in ['舞', '霸'] and song_id in remaster else 4)
        for level_index in range_:
            if (song_id, level_index) in unfinished or (song_id, level_index) not in played:
                unfinished_songs_diff[song_id].append(level_index)
        if song_id not in unfinished_songs_diff:
            completed_songs.add(song_id)

    # 排序曲目列表：未完成排前（根据最高未完成难度从高到低排序，其次定数从高到低），已完成在后
    incomplete_list = [m for m in music_objects if int(m.id) not in completed_songs]
    incomplete_list.sort(key=lambda x: (max(unfinished_songs_diff[int(x.id)]), -x.ds[max(unfinished_songs_diff[int(x.id)])]))
    completed_list = [m for m in music_objects if int(m.id) in completed_songs]
    music_sorted = incomplete_list + completed_list

    return draw_plate_grid_image(appellation, version, plan, music_sorted, completed_songs, unfinished_songs_diff)


async def level_process_data(
    qqid: int, 
    username: Optional[str], 
    level: str, 
    plan: str, 
    category: str = 'default', 
    page: int = 1
) -> Union[MessageSegment, str]:
    """
    查看谱面等级进度

    Params:
        `qqid`: 用户QQ
        `username`: 查分器用户名
        `level`: 定数
        `plan`: 评价等级
    Returns:
        `Union[MessageSegment, str]`
    """
    try:
        if maiApi.token:
            devobj = await maiApi.query_user_get_dev(qqid=qqid, username=username)
            obj = devobj.records
        else:
            version = list(set(_v for _v in list(plate_to_dx_version.values())))
            obj = await maiApi.query_user_plate(qqid=qqid, username=username, version=version)
        music = mai.total_list.by_plan(level)

        planlist = [0, 0, 0]
        plannum = 0
        if plan.lower() in scoreRank:
            plannum = 0
            planlist[0] = achievementList[scoreRank.index(plan.lower()) - 1]
        elif plan.lower() in comboRank:
            plannum = 1
            planlist[1] = comboRank.index(plan.lower())
        elif plan.lower() in syncRank:
            plannum = 2
            planlist[2] = syncRank.index(plan.lower())
        else:
            raise
        
        plan_value = planlist[plannum]
        
        def is_completed(plannum: int, _d: Union[PlayInfoDefault, PlayInfoDev]) -> bool:
            if plannum == 0:
                return _d.achievements >= plan_value
            elif plannum == 1:
                return bool(_d.fc and combo_rank.index(_d.fc) >= plan_value)
            elif plannum == 2:
                return bool(_d.fs and (
                    sync_rank.index(_d.fs) >= plan_value 
                    if _d.fs in sync_rank else sync_rank_p.index(_d.fs) >= plan_value
                ))
            return False
        
        for _d in obj:
            if isinstance(_d, PlayInfoDefault):
                _m = mai.total_list.by_id(_d.song_id)
                ds: float = _m.ds[_d.level_index]
                a: float = _d.achievements
                ra, rate = computeRa(ds, a, israte=True)
                _d.ra = ra
                _d.rate = rate
            if (song_id := str(_d.song_id)) in music and _d.level == level:
                if isinstance(music[song_id], Dict):
                    music[song_id][_d.level_index] = PlanInfo()
                    _p = music[song_id][_d.level_index]
                else:
                    music[song_id] = PlanInfo()
                    _p = music[song_id]
                
                if is_completed(plannum, _d):
                    _p.completed = _d
                else:
                    _p.unfinished = _d

        notplayed: List[RaMusic] = []
        completed: Union[List[PlayInfoDefault], List[PlayInfoDev]] = []
        unfinished: Union[List[PlayInfoDefault], List[PlayInfoDev]] = []
        for m in music:
            play = music[m]
            if isinstance(play, Dict):
                for index, p in play.items():
                    if isinstance(p, RaMusic):
                        notplayed.append(p)
                    elif p.completed:
                        completed.append(p.completed)
                    elif p.unfinished:
                        unfinished.append(p.unfinished)
            elif isinstance(play, PlanInfo):
                if play.completed:
                    completed.append(play.completed)
                if play.unfinished:
                    unfinished.append(play.unfinished)
            else:
                notplayed.append(play)
        completed.sort(key=lambda x: x.achievements if plannum == 0 else x.fc if plannum == 1 else x.fs, reverse=True)
        unfinished.sort(key=lambda x: x.achievements if plannum == 0 else x.fc if plannum == 1 else x.fs, reverse=True)
        notplayed.sort(key=lambda x: x.ds, reverse=True)

        if category == 'default':
            completed_len = 60 if len(unfinished) == 0 and len(notplayed) == 0 else 30
            clen = len(completed[:completed_len])
            completed_y = (clen // 5 + (0 if clen % 5 == 0 else 1)) * 109 + 140
            ulen = len(unfinished[:30])
            unfinished_y = (ulen // 5 + (0 if ulen % 5 == 0 else 1)) * 109 + 140
            nlen = len(notplayed[:100])
            notstarted_y = (nlen // 20 + (0 if nlen % 20 == 0 else 1)) * 65 + 140
            image = tricolor_gradient(1400, 150 + completed_y + unfinished_y + notstarted_y)
            dp = DrawScore(image)
            im = dp.draw_plan(completed, completed_y, unfinished, unfinished_y, notplayed, plan, completed_len)
        elif category == 'completed' or category == 'unfinished':
            data = completed if category == 'completed' else unfinished
            lendata = len(data)
            end_page_num = lendata // 80 + 1
            if page > end_page_num:
                return f'超出页数，您的成绩共计「{end_page_num}」页，请重新输入'
            topage = len(data[(page - 1) * 80: page * 80])
            plc = (topage // 5 + (0 if topage % 5 == 0 else 1)) * 109
            image = tricolor_gradient(1400, 240 + plc + 120)
            dp = DrawScore(image)
            im = dp.draw_category(category, data, page, end_page_num)
        else:
            lennotstarted = len(notplayed)
            pln = (lennotstarted // 20 + (0 if lennotstarted % 20 == 0 else 1)) * 65
            image = tricolor_gradient(1400, 240 + pln + 120)
            dp = DrawScore(image)
            im = dp.draw_category(category, notplayed)
        
        msg = MessageSegment.image(image_to_base64(im))
    except (UserNotFoundError, UserNotExistsError, UserDisabledQueryError) as e:
        msg = str(e)
    except Exception as e:
        log.error(traceback.format_exc())
        msg = f'未知错误：{type(e)}\n请联系Bot管理员'
    return msg


async def level_achievement_list_data(
    qqid: int, 
    username: Optional[str], 
    rating: Union[str, float], 
    page: int = 1
) -> Union[MessageSegment, str]:
    """
    查看分数列表

    Params:
        `qqid` : 用户QQ
        `username` : 查分器用户名
        `rating` : 定数
        `page` : 页数
        `nickname` : 用户昵称
    Returns:
        `Union[MessageSegment, str]
    """
    try:
        data: Union[List[PlayInfoDefault], List[PlayInfoDev]] = []
        if maiconfig.maimaidxtoken:
            obj = await maiApi.query_user_get_dev(qqid=qqid, username=username)
            data = obj.records
        else:
            version = list(set(_v for _v in list(plate_to_dx_version.values())))
            obj = await maiApi.query_user_plate(qqid=qqid, username=username, version=version)
            for _d in obj:
                music = mai.total_list.by_id(_d.song_id)
                _d.ds = music.ds[_d.level_index]
                _d.ra, _d.rate = computeRa(_d.ds, _d.achievements, israte=True)
            data = obj

        if isinstance(rating, str):
            newdata = sorted(list(filter(lambda x: x.level == rating, data)), key=lambda z: z.achievements, reverse=True)
        else:
            newdata = sorted(list(filter(lambda x: x.ds == rating, data)), key=lambda z: z.achievements, reverse=True)
        
        lendata = len(newdata)
        end_page_num = lendata // 80 + 1
        if page > end_page_num:
            return f'超出页数，您的成绩共计「{end_page_num}」页，请重新输入'
        
        topage = len(newdata[(page - 1) * 80: page * 80])
        line = topage // 5 + (0 if topage % 5 == 0 else 1)
        if page < end_page_num:
            plc = line * 109 + 140 * 4
        elif topage <= 20:
            plc = 4 * 109 + 140
        elif topage <= 40:
            plc = line * 109 + 140 * 2
        elif topage <= 60:
            plc = line * 109 + 140 * 3
        else:
            plc = line * 109 + 140 * 4
        
        image = tricolor_gradient(1400, 150 + plc)

        sc = DrawScore(image)
        im = sc.draw_scorelist(rating, newdata, page, end_page_num)
        msg = MessageSegment.image(image_to_base64(im))
    except (UserNotFoundError, UserNotExistsError, UserDisabledQueryError) as e:
        msg = str(e)
    except Exception as e:
        log.error(traceback.format_exc())
        msg = f'未知错误：{type(e)}\n请联系Bot管理员'
    return msg


def score_line_data(music: Music, level_index: int, target_ra: float) -> str:
    """
    计算分数线（达成率 -> 目标 Rating）

    Params:
        `music`: 曲目对象
        `level_index`: 难度索引
        `target_ra`: 目标 Rating
    Returns:
        `str`
    """
    ds = music.ds[level_index] if level_index < len(music.ds) else 0
    if ds == 0:
        return '该谱面定数数据异常。'

    diff_label = diffs[level_index] if level_index < len(diffs) else f'Lv.{level_index}'
    level_lbl = music.level[level_index] if level_index < len(music.level) else '?'

    # 遍历各个评级阈值，计算所需达成率
    thresholds = [
        (100.5, 22.4, 'SSSp'),
        (100.0, 21.6, 'SSS'),
        (99.5, 21.1, 'SSp'),
        (99.0, 20.8, 'SS'),
        (98.0, 20.3, 'Sp'),
        (97.0, 20.0, 'S'),
        (94.0, 16.8, 'AAA'),
        (90.0, 15.2, 'AA'),
        (80.0, 13.6, 'A'),
        (75.0, 12.0, 'BBB'),
        (70.0, 11.2, 'BB'),
        (60.0, 9.6, 'B'),
        (50.0, 8.0, 'C'),
    ]

    lines = [f'📊 {music.title} (ID: {music.id}) 「{diff_label}」Lv.{level_lbl}({ds})\n']
    lines.append(f'目标 Ra: {int(target_ra)}\n')

    for ach_ceil, base_ra, rate_name in thresholds:
        # 反推：ra = floor(ds * (achievement / 100) * baseRa)
        # achievement = (target_ra / (ds * base_ra)) * 100
        needed = (target_ra / (ds * base_ra)) * 100
        if needed <= ach_ceil:
            actual_needed = max(needed, 0.0)
            lines.append(f'  {rate_name}: 达成率需 ≥ {actual_needed:.4f}%')
        else:
            lines.append(f'  {rate_name}: 无法达到（需超过 {ach_ceil:.1f}%）')

    lines.append(f'\n当前定数 {ds}，每 0.1 定数变化约影响 {(0.1 / ds) * 100:.2f}% 达成率')
    return '\n'.join(lines)


async def player_score_data(qqid: int, music: Music) -> Union[MessageSegment, str]:
    """
    查询玩家单曲成绩

    Params:
        `qqid`: 用户QQ
        `music`: 曲目对象
    Returns:
        `Union[MessageSegment, str]`
    """
    try:
        records: List[Union[PlayInfoDefault, PlayInfoDev]] = []
        # 按用户数据源偏好顺序尝试
        source = user_source_route.get(qqid, maiconfig.prober_source.lower())

        async def _try_lxns() -> bool:
            """尝试落雪 API，成功返回 True"""
            try:
                lxns_records = await maiApi.query_user_song_score(qqid, music.id)
                if lxns_records:
                    records.extend(lxns_records)
                    for r in records:
                        m = mai.total_list.by_id(str(r.song_id))
                        if m and r.level_index < len(m.ds):
                            r.ds = m.ds[r.level_index]
                        elif not r.ds and r.level_index < len(music.ds):
                            r.ds = music.ds[r.level_index]
                    return True
                return False
            except Exception:
                return False

        async def _try_fish() -> bool:
            """尝试水鱼 API，成功返回 True"""
            try:
                if maiApi.token:
                    dev_records = await maiApi.query_user_post_dev(qqid, music.id)
                    if dev_records:
                        records.extend(dev_records)
                        return True
                # /query/plate 已要求 Developer-Token，无 token 跳过
                return False
            except Exception:
                return False

        if source == 'lxns':
            if not await _try_lxns():
                await _try_fish()
        else:
            if not await _try_fish():
                await _try_lxns()

        # 统一使用 draw_music_info 渲染精美曲目详情图（含/不含成绩）
        data = await draw_music_info(music, qqid)
    except Exception as e:
        log.error(traceback.format_exc())
        data = f'未知错误：{type(e)}\n请联系Bot管理员'
    return data


async def rating_ranking_data(name: Optional[str] = '', page: Optional[int] = 1) -> Union[MessageSegment, str]:
    """
    查看查分器排行榜 (升级后默认第一页展示全服 TOP 20 豪华排版图)
    """
    try:
        rank_data = await maiApi.rating_ranking()
        if not rank_data:
            return "❌ 无法从数据源拉取排行榜数据，请稍后再试。"
            
        if not name and (page == 1 or page is None):
            # 绘制全服 TOP 20 豪华大图
            im = Image.new('RGBA', (1000, 1380), (25, 28, 41, 255))
            dr = ImageDraw.Draw(im)
            sy = DrawText(dr, SIYUAN)
            tb = DrawText(dr, TBFONT)
            
            # Gradient background
            for y in range(1380):
                ratio = y / 1380.0
                r = int(20 * (1 - ratio) + 35 * ratio)
                g = int(24 * (1 - ratio) + 40 * ratio)
                b = int(35 * (1 - ratio) + 65 * ratio)
                dr.line([(0, y), (1000, y)], fill=(r, g, b, 255))
                
            # Pattern overlay
            pattern_path = maidir / 'pattern.png'
            if pattern_path.exists():
                try:
                    pat = Image.open(pattern_path).convert('RGBA')
                    for h in range((1380 // pat.height) + 1):
                        im.alpha_composite(pat, (0, h * pat.height))
                except Exception:
                    pass
            
            # Title
            sy.draw(500, 60, 42, "🏆 Maimai DX 全服战力排行榜 🏆", (255, 255, 255, 255), 'mm')
            sy.draw(500, 110, 18, "TOP 20 RATING LEADERBOARD", (150, 180, 220, 255), 'mm')
            
            # Table headers
            dr.rounded_rectangle((60, 160, 940, 215), radius=8, fill=(35, 45, 75, 255))
            sy.draw(120, 188, 20, "排名", (255, 255, 255, 255), 'mm')
            sy.draw(450, 188, 20, "玩家昵称", (255, 255, 255, 255), 'mm')
            sy.draw(820, 188, 20, "Rating 战力", (255, 255, 255, 255), 'mm')
            
            top_20 = rank_data[:20]
            for idx, r in enumerate(top_20):
                rank = idx + 1
                
                # Support both dict and object
                if isinstance(r, dict):
                    username = r.get("username", "")
                    ra = r.get("ra", 0)
                else:
                    username = getattr(r, "username", "")
                    ra = getattr(r, "ra", 0)
                    
                y_pos = 230 + idx * 52
                bg_color = (35, 45, 75, 150) if rank % 2 == 1 else (25, 30, 55, 150)
                dr.rounded_rectangle((60, y_pos, 940, y_pos + 46), radius=5, fill=bg_color)
                
                # Rank representation
                if rank == 1:
                    rank_color = (255, 215, 0, 255)
                    rank_text = "🥇 1"
                elif rank == 2:
                    rank_color = (192, 192, 192, 255)
                    rank_text = "🥈 2"
                elif rank == 3:
                    rank_color = (205, 127, 50, 255)
                    rank_text = "🥉 3"
                else:
                    rank_color = (200, 220, 255, 255)
                    rank_text = str(rank)
                    
                sy.draw(120, y_pos + 23, 20, rank_text, rank_color, 'mm')
                
                # Name limits
                if coloumWidth(username) > 30:
                    username = changeColumnWidth(username, 29) + "..."
                sy.draw(450, y_pos + 23, 20, username, (255, 255, 255, 255), 'mm')
                
                # Rating
                tb.draw(820, y_pos + 23, 22, str(ra), (100, 220, 255, 255), 'mm')
                
            sy.draw(500, 1330, 16, "数据源：水鱼查分器  |  Powered By MizukiBot lxns_b50", (130, 140, 160, 255), 'mm')
            return MessageSegment.image(image_to_base64(im))
            
        # Fallback to text format for other pages or name search
        _time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        if name != '':
            name_lower = name.lower()
            matched_idx = -1
            matched_name = ""
            for i, r in enumerate(rank_data):
                uname = r.get("username", "") if isinstance(r, dict) else getattr(r, "username", "")
                if uname.lower() == name_lower:
                    matched_idx = i + 1
                    matched_name = uname
                    break
            if matched_idx != -1:
                ranker = rank_data[matched_idx - 1]
                ra = ranker.get("ra", 0) if isinstance(ranker, dict) else getattr(ranker, "ra", 0)
                data = f'截止至 {_time}\n玩家 {matched_name} 在查分器已注册用户ra排行第{matched_idx}，当前Rating: {ra}'
            else:
                data = '未找到该玩家'
        else:
            user_num = len(rank_data)
            msg = f'截止至 {_time}，查分器已注册用户ra排行：\n'
            if page * 50 > user_num:
                page = user_num // 50 + 1
            end = page * 50 if page * 50 < user_num else user_num
            for i, ranker in enumerate(rank_data[(page - 1) * 50:end]):
                uname = ranker.get("username", "") if isinstance(ranker, dict) else getattr(ranker, "username", "")
                ra = ranker.get("ra", 0) if isinstance(ranker, dict) else getattr(ranker, "ra", 0)
                msg += f'No.{i + 1 + (page - 1) * 50:02d}.「{ra}」 {uname} \n'
            msg += f'第「{page}」页，共「{user_num // 50 + 1}」页'
            data = MessageSegment.image(text_to_bytes_io((msg.strip())))
    except Exception as e:
        log.error(traceback.format_exc())
        data = f'未知错误：{type(e)}\n请联系Bot管理员'
    return data


async def draw_player_card(qqid: int) -> Union[MessageSegment, str]:
    """
    绘制豪华玩家名片大图，包含详细头像、段位、绑定诊断、B50游玩统计等
    """
    try:
        user_info = await maiApi.query_user_b50(qqid=qqid)
        bind = await maiApi.check_bind_status(qqid)
    except Exception as e:
        log.error(f"Failed to fetch user info for player card: {e}")
        return f"❌ 未查找到您的成绩数据，请先绑定落雪/水鱼查分器。\n绑定说明：\n落雪: https://maimai.lxns.net\n水鱼: https://www.diving-fish.com"

    # 基础大小：1080 x 640
    bg_path = maidir / 'UI_TTR_BG_Base.png'
    if bg_path.exists():
        try:
            im = Image.open(bg_path).convert('RGBA').resize((1080, 640))
        except Exception:
            im = Image.new('RGBA', (1080, 640), (25, 28, 41, 255))
    else:
        im = Image.new('RGBA', (1080, 640), (25, 28, 41, 255))
        
    dr = ImageDraw.Draw(im)
    sy = DrawText(dr, SIYUAN)
    tb = DrawText(dr, TBFONT)
    
    # 磨砂暗色蒙版层
    overlay = Image.new('RGBA', (1080, 640), (20, 30, 50, 180))
    im.alpha_composite(overlay)
    
    # 绘制玩家 QQ 头像
    avatar_img = None
    if qqid:
        try:
            avatar_bytes = await maiApi.qqlogo(qqid)
            avatar_img = Image.open(BytesIO(avatar_bytes)).convert('RGBA').resize((150, 150))
        except Exception as e:
            log.warning(f"获取QQ头像失败: {e}")
    if not avatar_img:
        fallback_icon = maidir / 'UI_Icon_309503.png'
        if fallback_icon.exists():
            avatar_img = Image.open(fallback_icon).convert('RGBA').resize((150, 150))
        else:
            avatar_img = Image.new('RGBA', (150, 150), (100, 100, 100, 255))
            
    avatar_img = rounded_corners(avatar_img, 75, (True, True, True, True))
    im.alpha_composite(avatar_img, (60, 60))
    
    # 绘制底版（Nameplate）
    plate_img = None
    if user_info.plate and user_info.plate.isdigit():
        plate_cache_path = platedir / f"{user_info.plate}_lxns.png"
        if plate_cache_path.exists():
            try:
                plate_img = Image.open(plate_cache_path).convert('RGBA').resize((750, 150))
            except Exception:
                pass
    if not plate_img:
        default_plate_path = maidir / 'UI_Plate_300501.png'
        if default_plate_path.exists():
            plate_img = Image.open(default_plate_path).convert('RGBA').resize((750, 150))
        else:
            plate_img = Image.new('RGBA', (750, 150), (40, 50, 70, 255))
            
    im.alpha_composite(plate_img, (250, 60))
    
    # 写入昵称
    sy.draw(280, 135, 36, user_info.nickname, (255, 255, 255, 255), 'lm')
    
    # 写入段位
    if user_info.additional_rating is not None:
        try:
            add_rating = int(user_info.additional_rating)
            if add_rating <= 10:
                num = f'{add_rating:02d}'
            else:
                num = f'{add_rating + 1:02d}'
            dani_path = maidir / f'UI_DNM_DaniPlate_{num}.png'
            if dani_path.exists():
                dani_img = Image.open(dani_path).convert('RGBA').resize((100, 40))
                im.alpha_composite(dani_img, (880, 75))
        except Exception:
            pass
                
    # 写入 Class 等级
    class_path = maidir / 'UI_FBR_Class_00.png'
    if class_path.exists():
        try:
            class_img = Image.open(class_path).convert('RGBA').resize((100, 60))
            im.alpha_composite(class_img, (880, 130))
        except Exception:
            pass

    # 写入 DX Rating 底座
    ra = user_info.rating or 0
    if ra < 1000: r_pic = '01'
    elif ra < 2000: r_pic = '02'
    elif ra < 4000: r_pic = '03'
    elif ra < 7000: r_pic = '04'
    elif ra < 10000: r_pic = '05'
    elif ra < 12000: r_pic = '06'
    elif ra < 13000: r_pic = '07'
    elif ra < 14000: r_pic = '08'
    elif ra < 14500: r_pic = '09'
    elif ra < 15000: r_pic = '10'
    else: r_pic = '11'
    
    ra_plate_path = maidir / f'UI_CMN_DXRating_{r_pic}.png'
    if ra_plate_path.exists():
        try:
            ra_plate = Image.open(ra_plate_path).convert('RGBA').resize((200, 40))
            im.alpha_composite(ra_plate, (60, 240))
        except Exception:
            pass
            
    # 写入 DX Rating 数字
    ra_str = f'{ra:05d}'
    for n, char in enumerate(ra_str):
        digit_path = maidir / f'UI_NUM_Drating_{char}.png'
        if digit_path.exists():
            try:
                digit_img = Image.open(digit_path).convert('RGBA').resize((18, 22))
                im.alpha_composite(digit_img, (150 + 16 * n, 249))
            except Exception:
                pass
                
    # 查分器绑定状态诊断面板 (左下)
    dr.rounded_rectangle((60, 310, 520, 570), radius=10, fill=(30, 40, 60, 200), outline=(50, 70, 100, 255), width=2)
    sy.draw(80, 340, 22, "🔗 查分器绑定状态诊断", (255, 255, 255, 255), 'lm')
    
    lx_txt = "🟢 已同步绑定" if bind.get("lxns") else "🔴 未绑定"
    fi_txt = "🟢 已同步绑定" if bind.get("diving_fish") else "🔴 未绑定"
    active_source = user_source_route.get(qqid, maiconfig.prober_source.lower())
    active_source_txt = "❄️ 落雪 (LXNS)" if active_source == 'lxns' else "🔮 水鱼 (Diving-Fish)"
    
    sy.draw(90, 395, 20, f"落雪数据源 (LXNS):  {lx_txt}", (200, 220, 255, 255), 'lm')
    sy.draw(90, 445, 20, f"水鱼数据源 (DF):     {fi_txt}", (200, 220, 255, 255), 'lm')
    sy.draw(90, 495, 20, f"当前默认输出源:     {active_source_txt}", (100, 255, 180, 255), 'lm')
    sy.draw(90, 540, 16, "使用「切换数据源 水鱼/落雪」更改偏好", (160, 170, 190, 255), 'lm')

    # B50 游玩战果概要面板 (右下)
    dr.rounded_rectangle((560, 310, 1020, 570), radius=10, fill=(30, 40, 60, 200), outline=(50, 70, 100, 255), width=2)
    sy.draw(580, 340, 22, "📊 B50 游玩战果概要", (255, 255, 255, 255), 'lm')
    
    sd_best = user_info.charts.sd or []
    dx_best = user_info.charts.dx or []
    sd_ra_sum = sum(c.ra for c in sd_best)
    dx_ra_sum = sum(c.ra for c in dx_best)
    
    all_charts = sd_best + dx_best
    ap_count = sum(1 for c in all_charts if c.fc in ('ap', 'app'))
    fc_count = sum(1 for c in all_charts if c.fc in ('fc', 'fcp'))
    sss_plus_count = sum(1 for c in all_charts if c.achievements >= 100.5)
    sss_count = sum(1 for c in all_charts if 100.0 <= c.achievements < 100.5)
    
    tb.draw(580, 395, 20, f"SD B35: {sd_ra_sum} | DX B15: {dx_ra_sum}", (255, 255, 255, 255), 'lm')
    sy.draw(580, 435, 18, f"🥇 B50 SSS+ 达成数:  {sss_plus_count} 首", (255, 215, 0, 255), 'lm')
    sy.draw(580, 470, 18, f"🥈 B50 SSS  达成数:  {sss_count} 首", (220, 220, 220, 255), 'lm')
    sy.draw(580, 505, 18, f"⚡ B50 AP/AP+ 极太:  {ap_count} 首", (100, 220, 255, 255), 'lm')
    sy.draw(580, 540, 18, f"🔥 B50 FC/FC+ 全连:  {fc_count} 首", (255, 150, 100, 255), 'lm')
    
    logo_path = maidir / 'logo.png'
    if logo_path.exists():
        try:
            logo_img = Image.open(logo_path).convert('RGBA').resize((120, 58))
            im.alpha_composite(logo_img, (920, 235))
        except Exception:
            pass
        
    sy.draw(1000, 595, 16, "Powered By MizukiBot lxns_b50", (130, 140, 160, 255), 'rm')
    
    return MessageSegment.image(image_to_base64(im))


async def draw_rating_analysis(qqid: int) -> Union[MessageSegment, str]:
    """
    绘制豪华多维战力分析大图，包含Rating比例、评级占比、定数分布、流派雷达饼图等
    """
    try:
        user_info = await maiApi.query_user_b50(qqid=qqid)
    except Exception as e:
        log.error(f"Failed to fetch user info for rating analysis: {e}")
        return "❌ 未查找到您的成绩数据，请先绑定落雪或水鱼查分器。"

    sd_best = user_info.charts.sd or []
    dx_best = user_info.charts.dx or []
    all_charts = sd_best + dx_best
    if not all_charts:
        return "❌ 您的 Best 50 记录为空，无法进行多维战力分析。"

    # 画布大小：1200 x 960
    im = Image.new('RGBA', (1200, 960), (20, 22, 32, 255))
    dr = ImageDraw.Draw(im)
    sy = DrawText(dr, SIYUAN)
    tb = DrawText(dr, TBFONT)

    # 渐变背景
    for y in range(960):
        ratio = y / 960.0
        r = int(20 * (1 - ratio) + 30 * ratio)
        g = int(22 * (1 - ratio) + 36 * ratio)
        b = int(32 * (1 - ratio) + 55 * ratio)
        dr.line([(0, y), (1200, y)], fill=(r, g, b, 255))

    # 网格图案
    pattern_path = maidir / 'pattern.png'
    if pattern_path.exists():
        try:
            pat = Image.open(pattern_path).convert('RGBA')
            for h in range((960 // pat.height) + 1):
                im.alpha_composite(pat, (0, h * pat.height))
        except Exception:
            pass

    # 标题
    sy.draw(600, 50, 42, "📊 Maimai DX 个人战力多维深度分析 📊", (255, 255, 255, 255), 'mm')
    sy.draw(600, 95, 18, f"玩家：{user_info.nickname}  |  总战力 Rating：{user_info.rating}", (150, 180, 220, 255), 'mm')

    # 计算全局数值
    sd_ra = sum(c.ra for c in sd_best)
    dx_ra = sum(c.ra for c in dx_best)
    avg_ach = sum(c.achievements for c in all_charts) / len(all_charts)
    avg_ds = sum(c.ds for c in all_charts) / len(all_charts)
    
    # 1. 战力构成 (左上)
    dr.rounded_rectangle((50, 130, 580, 330), radius=10, fill=(35, 42, 65, 180), outline=(70, 85, 120, 255))
    sy.draw(70, 160, 22, "⚡ Rating 战力构成比例", (255, 255, 255, 255), 'lm')
    
    sd_ratio = sd_ra / max(1, user_info.rating)
    dx_ratio = dx_ra / max(1, user_info.rating)
    dr.rounded_rectangle((70, 200, 560, 225), radius=5, fill=(45, 55, 80, 255))
    dr.rounded_rectangle((70, 200, 70 + int(490 * sd_ratio), 225), radius=5, fill=(110, 140, 255, 255))
    dr.rounded_rectangle((70 + int(490 * sd_ratio), 200, 560, 225), radius=5, fill=(100, 230, 200, 255))
    sy.draw(70, 250, 18, f"旧版本 B35 贡献: {sd_ra} ({sd_ratio*100:.1f}%)", (110, 140, 255, 255), 'lm')
    sy.draw(70, 280, 18, f"新版本 B15 贡献: {dx_ra} ({dx_ratio*100:.1f}%)", (100, 230, 200, 255), 'lm')
    sy.draw(70, 310, 16, f"B50平均定数: {avg_ds:.2f}  |  平均达成率: {avg_ach:.4f}%", (200, 210, 230, 255), 'lm')

    # 2. 达成率评级占比 (左下)
    dr.rounded_rectangle((50, 360, 580, 910), radius=10, fill=(35, 42, 65, 180), outline=(70, 85, 120, 255))
    sy.draw(70, 390, 22, "🏅 B50 达成率评级分布", (255, 255, 255, 255), 'lm')
    
    ranks_list = ['SSSp', 'SSS', 'SSp', 'SS', 'Sp', 'S', 'AAA']
    rank_labels = {'SSSp': 'SSS+', 'SSS': 'SSS', 'SSp': 'SS+', 'SS': 'SS', 'Sp': 'S+', 'S': 'S', 'AAA': 'AAA'}
    rank_colors = {
        'SSSp': (255, 100, 120, 255), 'SSS': (255, 150, 80, 255), 'SSp': (255, 200, 80, 255),
        'SS': (240, 240, 100, 255), 'Sp': (100, 240, 150, 255), 'S': (100, 220, 255, 255),
        'AAA': (180, 180, 220, 255)
    }
    
    rank_counts = {r: 0 for r in ranks_list}
    for c in all_charts:
        crate = c.rate.upper()
        if crate == 'SSSP': crate = 'SSSp'
        elif crate == 'SSP': crate = 'SSp'
        elif crate == 'SP': crate = 'Sp'
        if crate in rank_counts:
            rank_counts[crate] += 1
            
    max_count = max(1, max(rank_counts.values()))
    for idx, r_name in enumerate(ranks_list):
        count = rank_counts[r_name]
        y_pos = 430 + idx * 64
        sy.draw(70, y_pos + 15, 20, rank_labels[r_name], rank_colors[r_name], 'lm')
        tb.draw(140, y_pos + 15, 20, f"{count:2d} 首", (255, 255, 255, 255), 'lm')
        dr.rounded_rectangle((220, y_pos, 540, y_pos + 26), radius=5, fill=(45, 55, 80, 255))
        if count > 0:
            bar_w = int(300 * (count / max_count))
            dr.rounded_rectangle((220, y_pos, 220 + bar_w, y_pos + 26), radius=5, fill=rank_colors[r_name])

    # 3. 谱面定数分布 (右上)
    dr.rounded_rectangle((620, 130, 1150, 480), radius=10, fill=(35, 42, 65, 180), outline=(70, 85, 120, 255))
    sy.draw(640, 160, 22, "📈 B50 谱面定数分布", (255, 255, 255, 255), 'lm')
    
    brackets = [
        ("14.5-15.0", lambda d: 14.5 <= d <= 15.0),
        ("14.0-14.4", lambda d: 14.0 <= d < 14.5),
        ("13.5-13.9", lambda d: 13.5 <= d < 14.0),
        ("13.0-13.4", lambda d: 13.0 <= d < 13.5),
        ("12.0-12.9", lambda d: 12.0 <= d < 13.0),
    ]
    bracket_counts = []
    for label, cond in brackets:
        bracket_counts.append((label, sum(1 for c in all_charts if cond(c.ds))))
        
    max_br_count = max(1, max(c for l, c in bracket_counts))
    for idx, (label, count) in enumerate(bracket_counts):
        y_pos = 200 + idx * 52
        tb.draw(640, y_pos + 15, 20, label, (200, 220, 255, 255), 'lm')
        tb.draw(760, y_pos + 15, 20, f"{count:2d} 首", (255, 255, 255, 255), 'lm')
        dr.rounded_rectangle((840, y_pos, 1110, y_pos + 22), radius=5, fill=(45, 55, 80, 255))
        if count > 0:
            bar_w = int(250 * (count / max_br_count))
            dr.rounded_rectangle((840, y_pos, 840 + bar_w, y_pos + 22), radius=5, fill=(100, 200, 255, 255))

    # 4. 音乐流派分类贡献度 (右下)
    dr.rounded_rectangle((620, 510, 1150, 910), radius=10, fill=(35, 42, 65, 180), outline=(70, 85, 120, 255))
    sy.draw(640, 540, 22, "🎵 B50 音乐类别占比", (255, 255, 255, 255), 'lm')
    
    genre_counts = defaultdict(int)
    for c in all_charts:
        m = mai.total_list.by_id(str(c.song_id))
        if m and m.basic_info:
            genre = m.basic_info.genre
        else:
            genre = "其他"
        genre_counts[genre] += 1
        
    sorted_genres = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)
    max_genre_count = max(1, max(c for g, c in sorted_genres)) if sorted_genres else 1
    
    for idx, (genre, count) in enumerate(sorted_genres[:6]):
        y_pos = 580 + idx * 52
        if coloumWidth(genre) > 16:
            genre_disp = changeColumnWidth(genre, 15) + "..."
        else:
            genre_disp = genre
        sy.draw(640, y_pos + 15, 20, genre_disp, (220, 230, 255, 255), 'lm')
        tb.draw(790, y_pos + 15, 20, f"{count:2d} 首", (255, 255, 255, 255), 'lm')
        dr.rounded_rectangle((860, y_pos, 1110, y_pos + 22), radius=5, fill=(45, 55, 80, 255))
        if count > 0:
            bar_w = int(230 * (count / max_genre_count))
            dr.rounded_rectangle((860, y_pos, 860 + bar_w, y_pos + 22), radius=5, fill=(150, 150, 255, 255))

    sy.draw(600, 935, 16, "Powered By MizukiBot lxns_b50", (130, 140, 160, 255), 'mm')
    return MessageSegment.image(image_to_base64(im))


def draw_speedy_report(nickname: str, r: dict) -> MessageSegment:
    """
    绘制豪华成绩速报街机打卡分享图
    """
    # 基础大小：800 x 450
    im = Image.new('RGBA', (800, 450), (20, 22, 32, 255))
    dr = ImageDraw.Draw(im)
    sy = DrawText(dr, SIYUAN)
    tb = DrawText(dr, TBFONT)
    
    # 渐变背景
    for y in range(450):
        ratio = y / 450.0
        r_val = int(24 * (1 - ratio) + 40 * ratio)
        g_val = int(28 * (1 - ratio) + 52 * ratio)
        b_val = int(45 * (1 - ratio) + 85 * ratio)
        dr.line([(0, y), (800, y)], fill=(r_val, g_val, b_val, 255))
        
    # 网格图案
    pattern_path = maidir / 'pattern.png'
    if pattern_path.exists():
        try:
            pat = Image.open(pattern_path).convert('RGBA')
            for h in range((450 // pat.height) + 1):
                im.alpha_composite(pat, (0, h * pat.height))
        except Exception:
            pass
            
    # 磨砂暗色玻璃面板
    dr.rounded_rectangle((40, 40, 760, 410), radius=15, fill=(30, 38, 60, 200), outline=(70, 90, 130, 255), width=2)
    
    # 主标题
    sy.draw(400, 70, 26, f"✨ {nickname} 的 Maimai DX 成绩速报 ✨", (255, 255, 255, 255), 'mm')
    
    song_name = r.get("song_name", "未知曲目")
    music = mai.total_list.by_title(song_name)
    music_id = str(music.id) if music else "0"
    
    # 绘制曲绘
    cover = get_cover_image(music_id, (200, 200))
    cover = rounded_corners(cover, 15, (True, True, True, True))
    im.alpha_composite(cover, (80, 140))
    
    # 难度底色框
    level = r.get("level", "")
    level_idx = 3
    if music and level in music.level:
        level_idx = music.level.index(level)
    diff_name = diffs[level_idx] if level_idx < len(diffs) else "Master"
    diff_colors = [
        (111, 212, 61, 255),
        (248, 183, 9, 255),
        (255, 129, 141, 255),
        (159, 81, 220, 255),
        (219, 170, 255, 255)
    ]
    dr.rounded_rectangle((80, 350, 280, 380), radius=5, fill=diff_colors[level_idx])
    sy.draw(180, 365, 18, f"{diff_name} Lv.{level}", (255, 255, 255, 255), 'mm')
    
    # 写入歌名
    title_disp = song_name
    if coloumWidth(title_disp) > 34:
        title_disp = changeColumnWidth(title_disp, 33) + "..."
    sy.draw(310, 150, 26, title_disp, (255, 255, 255, 255), 'lm')
    
    # 写入达成率
    ach = r.get("achievements", 0.0)
    tb.draw(310, 220, 48, f"{ach:.4f}%", (100, 255, 180, 255), 'lm')
    
    # 写入评级
    rate_str = r.get("rate", "D").upper()
    rate_filename = f'UI_TTR_Rank_{rate_str}.png'
    rate_path = maidir / rate_filename
    if rate_path.exists():
        try:
            rate_img = Image.open(rate_path).convert('RGBA').resize((100, 45))
            im.alpha_composite(rate_img, (310, 255))
        except Exception:
            pass
            
    # 写入 FC / FS
    fc = r.get("fc", "")
    fs = r.get("fs", "")
    badge_x = 430
    if fc:
        fc_filename = f'UI_CHR_PlayBonus_{fcl[fc]}.png' if fc in fcl else f'UI_CHR_PlayBonus_{fc.upper()}.png'
        fc_path = maidir / fc_filename
        if fc_path.exists():
            try:
                fc_img = Image.open(fc_path).convert('RGBA').resize((45, 45))
                im.alpha_composite(fc_img, (badge_x, 255))
                badge_x += 55
            except Exception:
                pass
    if fs:
        fs_filename = f'UI_CHR_PlayBonus_{fsl[fs]}.png' if fs in fsl else f'UI_CHR_PlayBonus_{fs.upper()}.png'
        fs_path = maidir / fs_filename
        if fs_path.exists():
            try:
                fs_img = Image.open(fs_path).convert('RGBA').resize((45, 45))
                im.alpha_composite(fs_img, (badge_x, 255))
            except Exception:
                pass
                
    dx_score = r.get("dx_score", 0)
    tb.draw(310, 330, 20, f"DX Score: {dx_score}", (200, 210, 230, 255), 'lm')
    
    import datetime
    tb.draw(310, 365, 16, f"打卡时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}", (150, 160, 180, 255), 'lm')
    
    logo_path = maidir / 'logo.png'
    if logo_path.exists():
        try:
            logo_img = Image.open(logo_path).convert('RGBA').resize((100, 48))
            im.alpha_composite(logo_img, (640, 340))
        except Exception:
            pass
            
    return MessageSegment.image(image_to_base64(im))


def draw_github_heatmap(heat_data: dict, nickname: str) -> MessageSegment:
    """
    绘制 GitHub 风格绿色格子热力图，代替原本简陋的 ASCII / 纯文本输出
    """
    # 画布大小：960 x 300
    im = Image.new('RGBA', (960, 300), (13, 17, 23, 255))
    dr = ImageDraw.Draw(im)
    sy = DrawText(dr, SIYUAN)
    tb = DrawText(dr, TBFONT)
    
    sy.draw(480, 40, 24, f"🔥 {nickname} 的 Maimai DX 成绩上传热力图", (255, 255, 255, 255), 'mm')
    
    import datetime
    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=364 + (today.weekday() + 1) % 7)
    
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    
    x_offset = 80
    y_offset = 110
    
    day_labels = {1: "Mon", 3: "Wed", 5: "Fri"}
    for day_idx, label in day_labels.items():
        sy.draw(x_offset - 15, y_offset + day_idx * 15 + 7, 12, label, (139, 148, 158, 255), 'rm')
        
    current_date = start_date
    col = 0
    month_drawn = set()
    
    while current_date <= today:
        day_of_week = (current_date.weekday() + 1) % 7
        x = x_offset + col * 15
        y = y_offset + day_of_week * 15
        
        date_str = current_date.strftime("%Y-%m-%d")
        count = int(heat_data.get(date_str, 0))
        
        if count == 0:
            fill_color = (22, 27, 34, 255)
        elif count <= 2:
            fill_color = (14, 68, 41, 255)
        elif count <= 5:
            fill_color = (0, 109, 50, 255)
        elif count <= 9:
            fill_color = (38, 166, 65, 255)
        else:
            fill_color = (57, 211, 83, 255)
            
        dr.rounded_rectangle((x, y, x + 12, y + 12), radius=2, fill=fill_color)
        
        month_name = months[current_date.month - 1]
        if current_date.day <= 7 and month_name not in month_drawn:
            sy.draw(x, y_offset - 15, 12, month_name, (139, 148, 158, 255), 'lm')
            month_drawn.add(month_name)
            
        current_date += datetime.timedelta(days=1)
        if day_of_week == 6:
            col += 1
            
    legend_x = 960 - 180
    legend_y = y_offset + 7 * 15 + 20
    sy.draw(legend_x - 10, legend_y + 6, 12, "Less", (139, 148, 158, 255), 'rm')
    
    colors_legend = [
        (22, 27, 34, 255),
        (14, 68, 41, 255),
        (0, 109, 50, 255),
        (38, 166, 65, 255),
        (57, 211, 83, 255)
    ]
    for idx, c in enumerate(colors_legend):
        lx = legend_x + idx * 15
        dr.rounded_rectangle((lx, legend_y, lx + 12, legend_y + 12), radius=2, fill=c)
        
    sy.draw(legend_x + 5 * 15 + 5, legend_y + 6, 12, "More", (139, 148, 158, 255), 'lm')
    
    total_plays = sum(int(c) for c in heat_data.values())
    active_days = sum(1 for c in heat_data.values() if int(c) > 0)
    sy.draw(80, legend_y + 6, 14, f"过去一年累计上传: {total_plays} 次游玩成绩  |  活跃天数: {active_days} 天", (139, 148, 158, 255), 'lm')
    
    return MessageSegment.image(image_to_base64(im))


async def draw_skill_analysis(qqid: int) -> Union[MessageSegment, str]:
    """
    底力深度分析：统计玩家在 Level >= 13.0 的游玩成绩，生成底力积分，评定段位，并绘制 1000x800 精美海报卡片。
    """
    try:
        user_info = await maiApi.query_user_b50(qqid=qqid)
        nickname = user_info.nickname
        user_rating = user_info.rating
    except Exception:
        nickname = str(qqid)
        user_rating = 0

    try:
        records = await maiApi.query_user_all_records(qqid=qqid)
    except Exception as e:
        log.error(f"Failed to fetch user records for skill analysis: {e}")
        return "❌ 未查找到您的成绩数据，请先绑定落雪或水鱼查分器。"

    if not records:
        return "❌ 未查找到您的游玩成绩记录，无法进行底力分析。"

    # 处理高难成绩
    high_diff_plays = []
    total_hd_count = 0
    
    # 5个难度等级档的评级计数
    matrix_counts = {
        '13': {'SSS+': 0, 'SSS': 0, 'SS+': 0, 'SS': 0, 'S': 0},
        '13+': {'SSS+': 0, 'SSS': 0, 'SS+': 0, 'SS': 0, 'S': 0},
        '14': {'SSS+': 0, 'SSS': 0, 'SS+': 0, 'SS': 0, 'S': 0},
        '14+': {'SSS+': 0, 'SSS': 0, 'SS+': 0, 'SS': 0, 'S': 0},
        '15': {'SSS+': 0, 'SSS': 0, 'SS+': 0, 'SS': 0, 'S': 0}
    }

    for play in records:
        music = mai.total_list.by_id(str(play.song_id))
        if not music:
            if play.type.lower() == 'dx':
                music = mai.total_list.by_id(str(int(play.song_id) + 10000))
        if not music:
            continue
            
        try:
            ds = music.ds[play.level_index]
        except (IndexError, TypeError):
            continue
            
        if ds < 13.0:
            continue
            
        total_hd_count += 1
        ach = play.achievements
        
        # 计算难度评级段
        if ds <= 13.6:
            band = '13'
        elif ds <= 13.9:
            band = '13+'
        elif ds <= 14.3:
            band = '14'
        elif ds <= 14.6:
            band = '14+'
        else:
            band = '15'
            
        if ach >= 100.5000:
            matrix_counts[band]['SSS+'] += 1
        elif ach >= 100.0000:
            matrix_counts[band]['SSS'] += 1
        elif ach >= 99.5000:
            matrix_counts[band]['SS+'] += 1
        elif ach >= 99.0000:
            matrix_counts[band]['SS'] += 1
        elif ach >= 97.0000:
            matrix_counts[band]['S'] += 1

        # 计算单曲底力积分
        if ach >= 100.5000:
            factor = 1.0
        elif ach >= 100.0000:
            factor = 0.8
        elif ach >= 99.5000:
            factor = 0.6
        elif ach >= 99.0000:
            factor = 0.4
        elif ach >= 98.0000:
            factor = 0.2
        elif ach >= 97.0000:
            factor = 0.1
        else:
            factor = 0.0
            
        if ds <= 13.6:
            base_pts = 100
        elif ds <= 13.9:
            base_pts = 250
        elif ds <= 14.3:
            base_pts = 600
        elif ds <= 14.6:
            base_pts = 1500
        else:
            base_pts = 4000
            
        pts = int(factor * base_pts)
        if pts > 0:
            high_diff_plays.append({
                'play': play,
                'music': music,
                'ds': ds,
                'ach': ach,
                'pts': pts
            })

    # 按底力积分降序，达成率降序排序
    high_diff_plays.sort(key=lambda x: (x['pts'], x['ach']), reverse=True)
    
    # 截取 Top 30 成绩
    top_30 = high_diff_plays[:30]
    total_skill_pts = sum(x['pts'] for x in top_30)
    
    avg_ds = sum(x['ds'] for x in top_30) / len(top_30) if top_30 else 0.0
    avg_ach = sum(x['ach'] for x in top_30) / len(top_30) if top_30 else 0.0

    # 评定底力段位
    if total_skill_pts < 100:
        dan_rank = "底力·新手"
    elif total_skill_pts < 500:
        dan_rank = "底力·初段"
    elif total_skill_pts < 1500:
        dan_rank = "底力·中段"
    elif total_skill_pts < 4000:
        dan_rank = "底力·高段"
    elif total_skill_pts < 10000:
        dan_rank = "底力·超段"
    elif total_skill_pts < 25000:
        dan_rank = "底力·真传"
    else:
        dan_rank = "底力·极真传"

    # 绘制底力海报大图
    height = 800
    width = 1000
    im = tricolor_gradient(width, height, (236, 130, 156), (195, 146, 232), (45, 30, 50))
    dr = ImageDraw.Draw(im)
    sy = DrawText(dr, SIYUAN)
    tb = DrawText(dr, TBFONT)

    # 绘制蜂窝背景网格
    pattern_path = maidir / 'pattern.png'
    if pattern_path.exists():
        try:
            pat = Image.open(pattern_path).convert('RGBA')
            for h in range((height // pat.height) + 1):
                for w in range((width // pat.width) + 1):
                    im.alpha_composite(pat, (w * pat.width, h * pat.height))
        except Exception:
            pass

    # 1. 顶部标题
    sy.draw(500, 45, 36, "👤 Maimai DX 底力深度分析 👤", (255, 255, 255, 255), 'mm')
    sy.draw(500, 90, 18, f"玩家: {nickname}  |  总战力 Rating: {user_rating}", (255, 240, 245, 255), 'mm')

    # 2. 左侧大区块（底力段位与数值统计）
    dr.rounded_rectangle((60, 130, 450, 490), radius=10, fill=(70, 42, 80, 200), outline=(236, 130, 156, 255), width=2)
    sy.draw(255, 165, 16, "底力积分", (255, 218, 226, 255), 'mm')
    tb.draw(255, 215, 52, f"{total_skill_pts:,}", (255, 255, 255, 255), 'mm')
    sy.draw(255, 270, 16, "底力段位", (255, 218, 226, 255), 'mm')
    
    # 绘制段位底板
    dr.rounded_rectangle((140, 295, 370, 335), radius=20, fill=(236, 130, 156, 255))
    sy.draw(255, 316, 20, dan_rank, (255, 255, 255, 255), 'mm')

    # 装饰线
    dr.line([(100, 360), (410, 360)], fill=(195, 146, 232, 100), width=1)

    # 数值指标
    sy.draw(100, 385, 16, f"Top30 平均定数: {avg_ds:.2f}", (255, 255, 255, 255), 'lm')
    sy.draw(100, 420, 16, f"Top30 平均达成: {avg_ach:.4f}%", (255, 255, 255, 255), 'lm')
    sy.draw(100, 455, 16, f"高难游玩数 (>=13.0): {total_hd_count}", (255, 255, 255, 255), 'lm')

    # 3. 右侧大区块（极值评级统计表）
    dr.rounded_rectangle((470, 130, 940, 490), radius=10, fill=(70, 42, 80, 200), outline=(195, 146, 232, 255), width=2)
    
    # 表头
    cols = ["等级", "SSS+", "SSS", "SS+", "SS", "S"]
    x_coords = [515, 590, 670, 750, 830, 905]
    for c_idx, col_name in enumerate(cols):
        sy.draw(x_coords[c_idx], 160, 16, col_name, (255, 218, 226, 255), 'mm')

    dr.line([(490, 185), (920, 185)], fill=(195, 146, 232, 100), width=1)
    
    # 表行
    row_bands = ["13", "13+", "14", "14+", "15"]
    row_labels = ["Lv 13", "Lv 13+", "Lv 14", "Lv 14+", "Lv 15"]
    y_coords = [220, 275, 330, 385, 440]
    
    for r_idx, band in enumerate(row_bands):
        sy.draw(x_coords[0], y_coords[r_idx], 16, row_labels[r_idx], (255, 255, 255, 255), 'mm')
        
        grades = ["SSS+", "SSS", "SS+", "SS", "S"]
        for g_idx, grade in enumerate(grades):
            cnt = matrix_counts[band][grade]
            x_pos = x_coords[g_idx + 1]
            if cnt == 0:
                tb.draw(x_pos, y_coords[r_idx], 16, "-", (195, 146, 232, 80), 'mm')
            else:
                tb.draw(x_pos, y_coords[r_idx], 16, str(cnt), (255, 160, 185, 255), 'mm')
                
        if r_idx < 4:
            dr.line([(490, y_coords[r_idx] + 28), (920, y_coords[r_idx] + 28)], fill=(195, 146, 232, 50), width=1)
            
    # 竖向网格分割线
    dr.line([(552, 145), (552, 475)], fill=(195, 146, 232, 100), width=1)

    # 4. 底部大区块（Top 5 巅峰表现曲目）
    dr.rounded_rectangle((60, 510, 940, 750), radius=10, fill=(55, 32, 65, 200), outline=(236, 130, 156, 120), width=1)
    sy.draw(80, 532, 15, "🔥 个人高难底力 Top 5 巅峰极值表现", (255, 218, 226, 255), 'lm')
    
    top_5 = top_30[:5]
    diff_colors = [
        (111, 212, 61, 255),
        (248, 183, 9, 255),
        (255, 129, 141, 255),
        (159, 81, 220, 255),
        (219, 170, 255, 255)
    ]
    diff_names = ['Basic', 'Advanced', 'Expert', 'Master', 'Re:Master']
    
    for idx, item in enumerate(top_5):
        y_item = 560 + idx * 36
        
        # 曲绘
        try:
            cover = get_cover_image(item['play'].song_id, (30, 30))
            cover = rounded_corners(cover, 5, (True, True, True, True))
            im.alpha_composite(cover, (80, y_item))
        except Exception:
            pass
            
        # 歌名
        title = item['play'].title
        if coloumWidth(title) > 28:
            title = changeColumnWidth(title, 27) + "..."
        sy.draw(120, y_item + 15, 14, title, (255, 255, 255, 255), 'lm')
        
        # 难度标签
        lvl_idx = item['play'].level_index
        dr.rounded_rectangle((480, y_item + 2, 560, y_item + 26), radius=3, fill=diff_colors[lvl_idx])
        sy.draw(520, y_item + 14, 12, diff_names[lvl_idx], (255, 255, 255, 255), 'mm')
        
        # 定数 -> 达成率
        tb.draw(670, y_item + 15, 14, f"{item['ds']:.1f} -> {item['ach']:.4f}%", (255, 255, 255, 255), 'mm')
        
        # 底力加成点数
        tb.draw(910, y_item + 15, 14, f"+{item['pts']} pts", (255, 215, 0, 255), 'rm')

    # 页脚
    sy.draw(500, 775, 13, "统计规则: 依据定数>=13.0的Top30高难成绩加权底力分进行综合评定", (130, 140, 160, 255), 'mm')

    return MessageSegment.image(image_to_base64(im))
