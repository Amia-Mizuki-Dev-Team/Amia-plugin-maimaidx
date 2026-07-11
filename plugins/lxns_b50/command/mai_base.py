# -*- coding: utf-8 -*-
import json
import re
import time
from io import BytesIO

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.exception import FinishedException
from nonebot.params import CommandArg
from loguru import logger as log
from ..libraries.maimaidx_api_data import maiApi, user_source_route, maiconfig, is_official_bot, build_markdown_keyboard
from ..dependencies import build_markdown_segment as _build_markdown_segment, get_real_qq
from PIL import Image, ImageDraw, ImageFont
from ..config import SIYUAN

# 指令注册总览
maimaidxhelp = on_command('mai帮助', aliases={'帮助maimaiDX', '帮助maimaidx'}, priority=5, block=True)
switch_source = on_command('切换数据源')
user_profile = on_command('mai状态', aliases={'详细信息', 'mai个人中心'})
render_curve = on_command('mai曲线')
render_recent = on_command('mai最近', aliases={'mai最近成绩', '最近记录', '最近成绩', 'mai recent'})
render_heatmap = on_command('mai热度', aliases={'mai热力图', '热力图', 'mai heatmap'})


def _card_font(size: int):
    return ImageFont.truetype(str(SIYUAN), size)


def _card_image(image: Image.Image) -> BytesIO:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def _short_text(text: object, limit: int) -> str:
    value = str(text or "未知曲目")
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _draw_rating_curve(curves: list[dict]) -> BytesIO:
    width, height = 1080, 620
    image = Image.new("RGB", (width, height), "#F4F7F8")
    draw = ImageDraw.Draw(image)
    title_font, label_font, value_font = _card_font(40), _card_font(22), _card_font(28)
    draw.rounded_rectangle((36, 28, width - 36, height - 30), radius=18, fill="#FFFFFF")
    draw.rectangle((36, 28, width - 36, 116), fill="#1C3546")
    draw.text((70, 51), "Rating 变化曲线", font=title_font, fill="#FFFFFF")

    ratings = [float(item.get("rating", 0)) for item in curves]
    dates = [time.strftime("%m-%d", time.localtime(item.get("time", 0))) for item in curves]
    low, high = min(ratings), max(ratings)
    if low == high:
        low -= 1
        high += 1
    padding = max((high - low) * 0.12, 1)
    low -= padding
    high += padding
    left, top, right, bottom = 105, 170, width - 70, height - 105
    for step in range(5):
        y = top + (bottom - top) * step / 4
        value = high - (high - low) * step / 4
        draw.line((left, y, right, y), fill="#DCE5E8", width=2)
        draw.text((45, y - 13), f"{value:.0f}", font=label_font, fill="#63727A")

    count = len(ratings)
    points = []
    for index, value in enumerate(ratings):
        x = left + (right - left) * (index / max(count - 1, 1))
        y = bottom - (value - low) / (high - low) * (bottom - top)
        points.append((x, y))
    if len(points) > 1:
        draw.line(points, fill="#159A9C", width=6, joint="curve")
    for x, y in points:
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill="#F06D5F")
    label_indices = sorted({0, count - 1, count // 2})
    for index in label_indices:
        x, _ = points[index]
        draw.text((x, bottom + 22), dates[index], font=label_font, fill="#63727A", anchor="ma")
    draw.text((70, 126), f"最新 Rating  {ratings[-1]:.0f}", font=value_font, fill="#1C3546")
    draw.text((right, 126), f"记录数  {count}", font=value_font, fill="#1C3546", anchor="ra")
    return _card_image(image)


def _draw_recent_card(player_name: str, recents: list[dict]) -> BytesIO:
    records = recents[:15]
    width, row_height = 1080, 74
    height = 196 + len(records) * row_height + 48
    image = Image.new("RGB", (width, height), "#F4F7F8")
    draw = ImageDraw.Draw(image)
    title_font, head_font, row_font, small_font = _card_font(38), _card_font(23), _card_font(24), _card_font(19)
    draw.rounded_rectangle((28, 24, width - 28, height - 24), radius=18, fill="#FFFFFF")
    draw.rectangle((28, 24, width - 28, 120), fill="#1C3546")
    draw.text((62, 49), "最近游玩记录", font=title_font, fill="#FFFFFF")
    draw.text((62, 132), _short_text(player_name, 24), font=head_font, fill="#1C3546")
    draw.text((width - 62, 132), f"显示最近 {len(records)} 条", font=small_font, fill="#63727A", anchor="ra")
    columns = ((58, "#"), (112, "曲目"), (605, "难度"), (704, "达成率"), (861, "评价"), (968, "DX"))
    for x, label in columns:
        draw.text((x, 166), label, font=small_font, fill="#63727A")
    for index, record in enumerate(records):
        top = 190 + index * row_height
        if index % 2 == 0:
            draw.rounded_rectangle((46, top, width - 46, top + row_height - 8), radius=8, fill="#EEF4F5")
        try:
            achievement = float(record.get("achievements", 0) or 0)
        except (TypeError, ValueError):
            achievement = 0.0
        grade = str(record.get("rate", "-") or "-").upper()
        badges = " ".join(str(record.get(key, "") or "").upper() for key in ("fc", "fs")).strip()
        draw.text((58, top + 17), f"{index + 1:02d}", font=row_font, fill="#159A9C")
        draw.text((112, top + 17), _short_text(record.get("song_name"), 24), font=row_font, fill="#1C3546")
        draw.text((605, top + 17), str(record.get("level", "-")), font=row_font, fill="#1C3546")
        draw.text((704, top + 17), f"{achievement:.4f}%", font=row_font, fill="#1C3546")
        draw.text((861, top + 9), grade, font=row_font, fill="#F06D5F")
        if badges:
            draw.text((861, top + 40), badges, font=small_font, fill="#63727A")
        draw.text((968, top + 17), str(record.get("dx_score", 0) or 0), font=small_font, fill="#1C3546")
    return _card_image(image)


def _draw_heatmap_card(player_name: str, heat_data: dict) -> BytesIO:
    entries = sorted(heat_data.items(), key=lambda item: item[0], reverse=True)[:30]
    values = []
    for _, raw_count in entries:
        try:
            values.append(max(0, int(raw_count)))
        except (TypeError, ValueError):
            values.append(0)
    maximum = max(values, default=1) or 1
    width, height = 1080, 780
    image = Image.new("RGB", (width, height), "#F4F7F8")
    draw = ImageDraw.Draw(image)
    title_font, head_font, cell_font, small_font = _card_font(38), _card_font(23), _card_font(22), _card_font(18)
    draw.rounded_rectangle((28, 24, width - 28, height - 24), radius=18, fill="#FFFFFF")
    draw.rectangle((28, 24, width - 28, 120), fill="#1C3546")
    draw.text((62, 49), "近 30 天成绩上传热度", font=title_font, fill="#FFFFFF")
    draw.text((62, 140), _short_text(player_name, 24), font=head_font, fill="#1C3546")
    draw.text((width - 62, 140), f"累计上传 {sum(values)} 次", font=head_font, fill="#1C3546", anchor="ra")
    left, top, cell_w, cell_h, gap = 60, 200, 128, 84, 12
    for index, ((date, _), count) in enumerate(zip(entries, values)):
        row, col = divmod(index, 7)
        x, y = left + col * (cell_w + gap), top + row * (cell_h + gap)
        ratio = count / maximum
        color = (int(229 - ratio * 115), int(244 - ratio * 75), int(245 - ratio * 72))
        draw.rounded_rectangle((x, y, x + cell_w, y + cell_h), radius=10, fill=color)
        draw.text((x + 12, y + 10), _short_text(date, 10), font=small_font, fill="#1C3546")
        draw.text((x + cell_w / 2, y + 42), str(count), font=cell_font, fill="#1C3546", anchor="ma")
    draw.text((60, 710), "颜色越深表示当天上传记录越多", font=small_font, fill="#63727A")
    return _card_image(image)
@switch_source.handle()
async def _(event: MessageEvent, message: Message = CommandArg()):
    """
    动态修改玩家在内存字典中指定的默认输出查分数据源
    """
    arg = message.extract_plain_text().strip().lower()
    raw_qq = event.user_id
    real_qq_str = get_real_qq(str(raw_qq))
    qqid = int(real_qq_str) if (real_qq_str and real_qq_str.isdigit()) else raw_qq
    if arg in ['落雪', 'lxns']:
        user_source_route[qqid] = 'lxns'
        await switch_source.finish("已成功为您指定查分默认输出为：落雪 (LXNS)", reply_message=True)
    elif arg in ['水鱼', 'diving-fish', 'df']:
        user_source_route[qqid] = 'diving-fish'
        await switch_source.finish("已成功为您指定查分默认输出为：水鱼 (Diving-Fish)", reply_message=True)
    else:
        await switch_source.finish("参数有误，支持：「切换数据源 水鱼」或「切换数据源 落雪」", reply_message=True)


@maimaidxhelp.handle()
async def _(bot: Bot, event: MessageEvent):
    raw_qq = event.user_id
    real_qq_str = get_real_qq(str(raw_qq))
    qqid = int(real_qq_str) if (real_qq_str and real_qq_str.isdigit()) else raw_qq
    current_source = user_source_route.get(qqid, maiconfig.prober_source.lower())
    source_title = "落雪 (LXNS)" if current_source == 'lxns' else "水鱼 (Diving-Fish)"

    md_help = (
        "### MaimaiDX 查分助手\n"
        f"> 当前为您生效的默认输出端：{source_title}\n\n"
        "**成绩核心查分**\n"
        "• `b50` : 生成 Best 50 个人成绩图\n"
        "• `ap50` : 生成 AP 50 成绩图 (落雪源)\n"
        "• `minfo <ID>` : 查询单谱面游玩详情与分数线\n"
        "• `ginfo <ID>` : 查询单谱面全服统计图\n"
        "• `分数线 <ID> <达成率>` : 查询单谱面达成分数线\n"
        "• `dxpass [立绘ID/名] [卡框ID] [底板ID]` : 生成金卡名片合成图\n\n"
        "**曲目与检索**\n"
        "• `查歌 <关键词>` : 全局模糊检索歌曲名\n"
        "• `id <曲目ID>` : 调取目标谱面核心底标参数\n"
        "• `完成表` / `定数表` : 完成进度与定数信息\n\n"
        "**游戏与互动**\n"
        "• `猜歌` / `猜曲绘` / `听歌猜歌` / `别名猜歌` : 开启群内猜曲游戏\n\n"
        "**账户与路由中心**\n"
        "• `mai状态` : 诊断您的双端绑定状态与档案大盘\n"
        "• `切换数据源 水鱼/落雪` : 实时修改输出端\n"
        "• `mai曲线` / `mai最近` / `mai热度` : 绘制落雪数据趋势走势及记录"
    )

    plain_help = (
        "[MaimaiDX 查分器指令字典]\n"
        f"当前为您生效的数据源：{source_title}\n\n"
        "· b50 : 生成 Best 50 成绩图\n"
        "· ap50 : 生成 AP 50 成绩图\n"
        "· minfo <曲目ID> : 查询单曲游玩详情\n"
        "· ginfo <曲目ID> : 查询单曲全服统计图\n"
        "· 分数线 <曲目ID> <达成率> : 查询单曲分数线\n"
        "· dxpass [立绘ID/名] [卡框ID] [底板ID] : 生成名片大图\n"
        "· 查歌 <关键词> : 检索歌曲\n"
        "· id <曲目ID> : 查看谱面详细底标\n"
        "· 完成表 / 定数表 : 查看完成表与定数表\n"
        "· 猜歌 / 猜曲绘 / 听歌猜歌 / 别名猜歌 : 开启小游戏\n"
        "· mai状态 : 诊断查分器双端绑定状态\n"
        "· 切换数据源 <水鱼/落雪> : 修改输出端\n"
        "· mai曲线 / mai最近 / mai热度 : 查询落雪趋势/最近记录/热力图"
    )

    if is_official_bot(bot.self_id):
        msg_segment = _build_markdown_segment(md_help, [
            [
                {"id": "b50", "render_data.label": "生成我的 B50", "render_data.style": 1, "action.type": 2, "action.permission.type": 2, "action.data": "b50", "action.enter": True},
                {"id": "profile", "render_data.label": "个人状态大盘", "render_data.style": 1, "action.type": 2, "action.permission.type": 2, "action.data": "mai状态", "action.enter": True}
            ],
            [
                {"id": "dxpass", "render_data.label": "生成名片", "render_data.style": 1, "action.type": 2, "action.permission.type": 2, "action.data": "dxpass", "action.enter": True}
            ],
            [
                {"id": "to_lx", "render_data.label": "默认切至落雪", "render_data.style": 2, "action.type": 2, "action.permission.type": 2, "action.data": "切换数据源 落雪", "action.enter": True},
                {"id": "to_fi", "render_data.label": "默认切至水鱼", "render_data.style": 2, "action.type": 2, "action.permission.type": 2, "action.data": "切换数据源 水鱼", "action.enter": True}
            ]
        ])
        await maimaidxhelp.finish(Message(msg_segment))
    else:
        await maimaidxhelp.finish(plain_help, reply_message=True)


@user_profile.handle()
async def _(bot: Bot, event: MessageEvent):
    """
    【详细信息：个人中心大盘】
    同步探测玩家落雪和水鱼的绑定和注册细节，并送出官方跳转和一键切换机制
    """
    raw_qq = event.user_id
    real_qq_str = get_real_qq(str(raw_qq))
    qqid = int(real_qq_str) if (real_qq_str and real_qq_str.isdigit()) else raw_qq
    bind = await maiApi.check_bind_status(qqid)
    lx_ind = "已绑定" if bind["lxns"] else "未绑定"
    fi_ind = "已绑定" if bind["diving_fish"] else "未绑定"
    
    current_source = user_source_route.get(qqid, maiconfig.prober_source.lower())
    source_title = "落雪 (LXNS)" if current_source == 'lxns' else "水鱼 (Diving-Fish)"

    # 档案卡 Markdown 规范格式
    md_profile = (
        f"### MaimaiDX 玩家档案\n"
        f"针对您的 QQ 账号：`{qqid}` 诊断报告：\n\n"
        f"**当前默认输出端**\n"
        f"• 正在使用：**{source_title}**\n\n"
        f"**数据源绑定状态**\n"
        f"• 落雪查分器：{lx_ind}\n"
        f"• 水鱼查分器：{fi_ind}\n\n"
        f"*可使用下方按钮切换默认输出端。*"
    )

    # 档案卡 纯文本/picmenu 兼容版
    plain_profile = (
        f"【MaimaiDX 个人中心详细档案】\n"
        f"用户 QQ：{qqid}\n\n"
        f"当前默认输出端：{source_title}\n"
        f"落雪查分器绑定状态：{'[已绑定]' if bind['lxns'] else '[未绑定]'}\n"
        f"水鱼查分器绑定状态：{'[已绑定]' if bind['diving_fish'] else '[未绑定]'}\n\n"
        f"• 提示：落雪源用户可发送「mai曲线」调取Rating历史走势。"
    )

    if is_official_bot(bot.self_id):
        msg_segment = _build_markdown_segment(md_profile, [
            [
                {"id": "set_lxns", "render_data.label": "默认设为落雪", "render_data.style": 2, "action.type": 2, "action.permission.type": 2, "action.data": "切换数据源 落雪", "action.enter": True},
                {"id": "set_fish", "render_data.label": "默认设为水鱼", "render_data.style": 2, "action.type": 2, "action.permission.type": 2, "action.data": "切换数据源 水鱼", "action.enter": True}
            ],
            [
                {"id": "v_curve", "render_data.label": "趋势折线图", "render_data.style": 1, "action.type": 2, "action.permission.type": 2, "action.data": "mai曲线", "action.enter": True}
            ],
            [
                {"id": "lnk_lx", "render_data.label": "打开落雪主页", "render_data.style": 0, "action.type": 0, "action.permission.type": 2, "action.data": "https://maimai.lxns.net/user/profile?tab=profile"},
                {"id": "lnk_fi", "render_data.label": "打开水鱼主页", "render_data.style": 0, "action.type": 0, "action.permission.type": 2, "action.data": "https://www.diving-fish.com/maimaidx/prober/"}
            ]
        ])
        await user_profile.finish(Message(msg_segment))
    else:
        await user_profile.finish(plain_profile, reply_message=True)


@render_curve.handle()
async def _(bot: Bot, event: MessageEvent):
    """
    【向外拓展：Rating 历史变动趋势折线图】
    仅在用户将当前输出源切换为落雪时提供支持
    """
    raw_qq = event.user_id
    real_qq_str = get_real_qq(str(raw_qq))
    qqid = int(real_qq_str) if (real_qq_str and real_qq_str.isdigit()) else raw_qq
    current_source = user_source_route.get(qqid, maiconfig.prober_source.lower())
    if current_source != 'lxns':
        await render_curve.finish("趋势历史曲线目前仅支持落雪数据源，请先切换数据源为落雪。", reply_message=True)
        
    curves = await maiApi.get_lxns_rating_curves(qqid)
    if not curves:
        await render_curve.finish("未检测到 Rating 变动轨迹，请确认已在落雪同步过至少两次有效成绩。", reply_message=True)

    try:
        await render_curve.finish(MessageSegment.image(_draw_rating_curve(curves)), reply_message=True)
    except FinishedException:
        raise
    except Exception:
        log.exception("mai曲线 渲染失败")
        await render_curve.finish("Rating 曲线渲染失败，请稍后重试。", reply_message=True)


@render_recent.handle()
async def _(bot: Bot, event: MessageEvent):
    """
    【落雪特供】最近 50 条游玩记录
    使用落雪 API: GET /maimai/player/qq/{qq}/recents
    """
    raw_qq = event.user_id
    real_qq_str = get_real_qq(str(raw_qq))
    qqid = int(real_qq_str) if (real_qq_str and real_qq_str.isdigit()) else raw_qq
    current_source = user_source_route.get(qqid, maiconfig.prober_source.lower())
    if current_source != 'lxns':
        await render_recent.finish("最近游玩记录目前仅支持落雪数据源，请先切换数据源为落雪。", reply_message=True)
    
    try:
        import httpx
        headers = {"Authorization": maiconfig.lxnstoken}
        async with httpx.AsyncClient(timeout=15) as client:
            # 先获取 friend_code
            res = await client.get(f"https://maimai.lxns.net/api/v0/maimai/player/qq/{qqid}", headers=headers)
            if res.status_code != 200:
                await render_recent.finish("未在落雪找到您的绑定信息，请先前往落雪绑定 QQ。", reply_message=True)
            player_data = res.json().get("data", {})
            friend_code = player_data.get("friend_code")
            if not friend_code:
                await render_recent.finish("无法获取您的落雪好友码。", reply_message=True)
            
            # 获取最近 50 条记录
            recents_res = await client.get(
                f"https://maimai.lxns.net/api/v0/maimai/player/{friend_code}/recents",
                headers=headers
            )
            if recents_res.status_code != 200:
                await render_recent.finish("获取最近记录失败，可能暂无游玩数据。", reply_message=True)
            
            recents = recents_res.json().get("data", [])
            if not recents:
                await render_recent.finish("暂无最近游玩记录。", reply_message=True)
        
        await render_recent.finish(
            MessageSegment.image(_draw_recent_card(player_data.get("name", "未知玩家"), recents)),
            reply_message=True,
        )
    except FinishedException:
        raise
    except Exception as e:
        log.exception("[mai最近] 查询失败")
        await render_recent.finish(f"查询最近记录失败: {type(e).__name__}", reply_message=True)
 
 
@render_heatmap.handle()
async def _(bot: Bot, event: MessageEvent):
    """
    【落雪特供】成绩上传热力图
    使用落雪 API: GET /maimai/player/{friend_code}/heatmap
    """
    raw_qq = event.user_id
    real_qq_str = get_real_qq(str(raw_qq))
    qqid = int(real_qq_str) if (real_qq_str and real_qq_str.isdigit()) else raw_qq
    current_source = user_source_route.get(qqid, maiconfig.prober_source.lower())
    if current_source != 'lxns':
        await render_heatmap.finish("热力图目前仅支持落雪数据源，请先切换数据源为落雪。", reply_message=True)
    
    try:
        import httpx
        headers = {"Authorization": maiconfig.lxnstoken}
        async with httpx.AsyncClient(timeout=15) as client:
            # 先获取 friend_code
            res = await client.get(f"https://maimai.lxns.net/api/v0/maimai/player/qq/{qqid}", headers=headers)
            if res.status_code != 200:
                await render_heatmap.finish("未在落雪找到您的绑定信息。", reply_message=True)
            player_data = res.json().get("data", {})
            friend_code = player_data.get("friend_code")
            if not friend_code:
                await render_heatmap.finish("无法获取您的落雪好友码。", reply_message=True)
            
            heatmap_res = await client.get(
                f"https://maimai.lxns.net/api/v0/maimai/player/{friend_code}/heatmap",
                headers=headers
            )
            if heatmap_res.status_code != 200:
                await render_heatmap.finish("获取热力图数据失败。", reply_message=True)
            
            heat_data = heatmap_res.json().get("data", {})
            if not heat_data:
                await render_heatmap.finish("暂无热力图数据。", reply_message=True)
        
        await render_heatmap.finish(
            MessageSegment.image(_draw_heatmap_card(player_data.get("name", "未知玩家"), heat_data)),
            reply_message=True,
        )
    except FinishedException:
        raise
    except Exception as e:
        log.exception("[mai热度] 查询失败")
        await render_heatmap.finish(f"查询热力图失败: {type(e).__name__}", reply_message=True)
