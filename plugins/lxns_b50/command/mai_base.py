# -*- coding: utf-8 -*-
import json
import time
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.params import CommandArg
from ..libraries.maimaidx_api_data import maiApi, user_source_route, maiconfig, is_official_bot, build_markdown_keyboard
from ..libraries.tool import run_chrome_to_base64
from ..dependencies import build_markdown_segment as _build_markdown_segment, get_real_qq

# 指令注册总览
maimaidxhelp = on_command('mai帮助', aliases={'帮助maimaiDX', '帮助maimaidx'}, priority=5, block=True)
switch_source = on_command('切换数据源')
user_profile = on_command('mai状态', aliases={'详细信息', 'mai个人中心'})
render_curve = on_command('mai曲线')
render_recent = on_command('mai最近', aliases={'mai最近成绩', 'mai recent'})
render_heatmap = on_command('mai热度', aliases={'mai热力图', 'mai heatmap'})
lxbind = on_command('lxbind', aliases={'绑定落雪', '绑定lx'})


@lxbind.handle()
async def _(bot: Bot, event: MessageEvent, message: Message = CommandArg()):
    raw_qq = event.user_id
    real_qq_str = get_real_qq(str(raw_qq))
    qqid = int(real_qq_str) if (real_qq_str and real_qq_str.isdigit()) else raw_qq
    
    auth_url = (
        "https://maimai.lxns.net/oauth/authorize"
        "?response_type=code"
        "&client_id=c9dc866a-1d49-4159-beb0-b711f19055ac"
        "&redirect_uri=https%3A%2F%2Fapi.mizuki.top%2Fauth%2Fcallback"
        "&scope=read_user_profile+read_player+write_player+read_user_token"
    )
    
    md_content = (
        "### ❄️ 落雪查分器 OAuth 授权绑定\n\n"
        f"针对您的 QQ 账号：`{qqid}`\n"
        "请点击下方按钮前往落雪查分器进行安全授权，绑定您的成绩数据以同步至 Bot。\n\n"
        "**💡 授权后操作**：\n"
        "授权成功后，落雪官网会生成该格式的「授权码」：`XXXX-XXXX-XXXX`。\n"
        "请复制该授权码直接在此处发送给 Bot 完成最后的接入校验。"
    )
    
    plain_content = (
        "【落雪查分器 OAuth 绑定引导】\n\n"
        f"请复制以下链接前往浏览器打开并授权：\n"
        f"{auth_url}\n\n"
        "授权成功后将您获得的授权码直接发送给 Bot 即可完成绑定！"
    )
    
    if is_official_bot(bot.self_id):
        msg_segment = _build_markdown_segment(md_content, [
            [
                {"id": "go_auth", "render_data.label": "🌐 前往落雪授权", "render_data.style": 1, "action.type": 0, "action.permission.type": 2, "action.data": auth_url}
            ]
        ])
        await lxbind.finish(Message(msg_segment))
    else:
        await lxbind.finish(plain_content, reply_message=True)


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
        await switch_source.finish("已成功为您指定查分默认输出为：❄️ 落雪 (LXNS)", reply_message=True)
    elif arg in ['水鱼', 'diving-fish', 'df']:
        user_source_route[qqid] = 'diving-fish'
        await switch_source.finish("已成功为您指定查分默认输出为：🔮 水鱼 (Diving-Fish)", reply_message=True)
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
        "• `lxbind` : 引导授权并绑定您的落雪账号\n"
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
        "· lxbind : 绑定落雪账号\n"
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
                {"id": "bind", "render_data.label": "绑定落雪账号", "render_data.style": 1, "action.type": 2, "action.permission.type": 2, "action.data": "lxbind", "action.enter": True},
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
    lx_ind = "🟢 已同步绑定" if bind["lxns"] else "🔴 未绑定"
    fi_ind = "🟢 已同步绑定" if bind["diving_fish"] else "🔴 未绑定"
    
    current_source = user_source_route.get(qqid, maiconfig.prober_source.lower())
    source_title = "❄️ 落雪 (LXNS)" if current_source == 'lxns' else "🔮 水鱼 (Diving-Fish)"

    # 档案卡 Markdown 规范格式
    md_profile = (
        f"### 👤 MaimaiDX 玩家档案大盘\n"
        f"针对您的 QQ 账号：`{qqid}` 诊断报告：\n\n"
        f"**⚙️ 当前默认输出端**\n"
        f"• 正在使用：**{source_title}**\n\n"
        f"**🔗 全端数据同步状态检测**\n"
        f"• ❄️ 落雪查分器：{lx_ind}\n"
        f"• 🔮 水鱼查分器：{fi_ind}\n\n"
        f"💡 *管理建议：如若两端有未完成绑定的账户，请点击最下方对应官方传送链快速授权绑定；点击切置按钮直接变更输出。*"
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
                {"id": "set_lxns", "render_data.label": "❄️ 默认设为落雪", "render_data.style": 2, "action.type": 2, "action.permission.type": 2, "action.data": "切换数据源 落雪", "action.enter": True},
                {"id": "set_fish", "render_data.label": "🔮 默认设为水鱼", "render_data.style": 2, "action.type": 2, "action.permission.type": 2, "action.data": "切换数据源 水鱼", "action.enter": True}
            ],
            [
                {"id": "v_curve", "render_data.label": "📈 趋势折线走势图", "render_data.style": 1, "action.type": 2, "action.permission.type": 2, "action.data": "mai曲线", "action.enter": True}
            ],
            [
                {"id": "lnk_lx", "render_data.label": "🌐 落雪主页传送", "render_data.style": 0, "action.type": 0, "action.permission.type": 2, "action.data": "https://maimai.lxns.net/user/profile?tab=profile"},
                {"id": "lnk_fi", "render_data.label": "🌐 水鱼主页传送", "render_data.style": 0, "action.type": 0, "action.permission.type": 2, "action.data": "https://www.diving-fish.com/maimaidx/prober/"}
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
        await render_curve.finish("⚠️ 趋势历史曲线功能目前由落雪API独占特供，请先切换默认输出端为落雪查分器！", reply_message=True)
        
    curves = await maiApi.get_lxns_rating_curves(qqid)
    if not curves:
        await render_curve.finish("❌ 未在落雪官网检测到您的 Rating 变动轨迹，请确保您在落雪同步并积累了大于一次的有效成绩！", reply_message=True)

    try:
        import pyecharts.options as opts
        from pyecharts.charts import Line
        from ..config import pie_html_file
        
        raw_timestamps = [time.strftime("%m-%d", time.localtime(c["time"])) for c in curves]
        raw_ratings = [c["rating"] for c in curves]
        
        # 阈值 = 全距 × 20%，超过阈值时才标注数据点
        rng = max(raw_ratings) - min(raw_ratings)
        threshold = rng * 0.2 if rng > 0 else 0
        timestamps, ratings = [raw_timestamps[0]], [raw_ratings[0]]
        for i in range(1, len(raw_ratings)):
            if abs(raw_ratings[i] - ratings[-1]) > threshold:
                timestamps.append(raw_timestamps[i])
                ratings.append(raw_ratings[i])
        
        import math
        y_min = math.floor(min(ratings))
        y_max = math.ceil(max(ratings))
        
        line = Line(init_opts=opts.InitOpts(width="1000px", height="600px", bg_color="#fff"))
        line.add_xaxis(xaxis_data=timestamps)
        line.add_yaxis(
            series_name="Rating变动走势",
            y_axis=ratings,
            is_smooth=True,
            label_opts=opts.LabelOpts(is_show=True),
        )
        line.set_global_opts(
            title_opts=opts.TitleOpts(title="📈 MaimaiDX 个人历史 Rating 演变折线图", pos_left="center"),
            yaxis_opts=opts.AxisOpts(min_=y_min, max_=y_max),
        )
        line.render(str(pie_html_file))
        
        base64_img = await run_chrome_to_base64()
        await render_curve.finish(MessageSegment.image(base64_img), reply_message=True)
    except Exception as e:
        from nonebot.exception import FinishedException
        if isinstance(e, FinishedException):
            raise
        import traceback
        from loguru import logger as log
        log.error(f"mai曲线 渲染失败: {e}\n{traceback.format_exc()}")
        await render_curve.finish("⚠️ 历史战绩画布高级组件渲染失败，请联系Bot管理员检修服务器配置环境。", reply_message=True)


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
        await render_recent.finish("⚠️ 最近游玩记录功能目前由落雪 API 独占特供，请先切换默认输出端为落雪查分器！", reply_message=True)
    
    try:
        import httpx
        headers = {"Authorization": maiconfig.lxnstoken}
        async with httpx.AsyncClient(timeout=15) as client:
            # 先获取 friend_code
            res = await client.get(f"https://maimai.lxns.net/api/v0/maimai/player/qq/{qqid}", headers=headers)
            if res.status_code != 200:
                await render_recent.finish("❌ 未在落雪找到您的绑定信息，请先前往 https://maimai.lxns.net 绑定 QQ", reply_message=True)
            player_data = res.json().get("data", {})
            friend_code = player_data.get("friend_code")
            if not friend_code:
                await render_recent.finish("❌ 无法获取您的落雪好友码", reply_message=True)
            
            # 获取最近 50 条记录
            recents_res = await client.get(
                f"https://maimai.lxns.net/api/v0/maimai/player/{friend_code}/recents",
                headers=headers
            )
            if recents_res.status_code != 200:
                await render_recent.finish("❌ 获取最近记录失败，可能暂无游玩数据", reply_message=True)
            
            recents = recents_res.json().get("data", [])
            if not recents:
                await render_recent.finish("📭 暂无最近游玩记录", reply_message=True)
        
        # 格式化输出最近记录
        msg = f"🎵 {player_data.get('name', '未知')} 的最近游玩记录\n"
        msg += f"{'='*30}\n"
        for i, r in enumerate(recents[:20]):  # 最多显示20条
            song_name = r.get("song_name", "未知曲目")
            level = r.get("level", "")
            achievements = r.get("achievements", 0)
            rate = r.get("rate", "")
            fc = r.get("fc", "")
            fs = r.get("fs", "")
            dx_score = r.get("dx_score", 0)
            
            badges = ""
            if fc: badges += f" [{fc.upper()}]"
            if fs: badges += f" [{fs.upper()}]"
            
            msg += f"{i+1:2d}. {song_name} [{level}] {achievements:.4f}% {rate}{badges} DX:{dx_score}\n"
        
        if len(recents) > 20:
            msg += f"\n... 及另外 {len(recents) - 20} 条记录"
        
        from ..libraries.image import text_to_bytes_io
        await render_recent.finish(MessageSegment.image(text_to_bytes_io(msg.strip())), reply_message=True)
        
    except Exception as e:
        import traceback
        log.error(f"[mai最近] 查询失败:\n{traceback.format_exc()}")
        await render_recent.finish(f"⚠️ 查询最近记录失败: {type(e).__name__}", reply_message=True)
 
 
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
        await render_heatmap.finish("⚠️ 热力图功能目前由落雪 API 独占特供，请先切换默认输出端为落雪查分器！", reply_message=True)
    
    try:
        import httpx
        headers = {"Authorization": maiconfig.lxnstoken}
        async with httpx.AsyncClient(timeout=15) as client:
            # 先获取 friend_code
            res = await client.get(f"https://maimai.lxns.net/api/v0/maimai/player/qq/{qqid}", headers=headers)
            if res.status_code != 200:
                await render_heatmap.finish("❌ 未在落雪找到您的绑定信息", reply_message=True)
            player_data = res.json().get("data", {})
            friend_code = player_data.get("friend_code")
            if not friend_code:
                await render_heatmap.finish("❌ 无法获取您的落雪好友码", reply_message=True)
            
            heatmap_res = await client.get(
                f"https://maimai.lxns.net/api/v0/maimai/player/{friend_code}/heatmap",
                headers=headers
            )
            if heatmap_res.status_code != 200:
                await render_heatmap.finish("❌ 获取热力图数据失败", reply_message=True)
            
            heat_data = heatmap_res.json().get("data", {})
            if not heat_data:
                await render_heatmap.finish("📭 暂无热力图数据", reply_message=True)
        
        from ..libraries.image import text_to_bytes_io
        sorted_dates = sorted(heat_data.items(), key=lambda x: x[0], reverse=True)[:30]
        msg = f"🔥 {player_data.get('name', '未知')} 的成绩上传热力图 (近30天)\n"
        msg += f"{'='*30}\n"
        for date, count in sorted_dates:
            bar = "█" * min(count, 20)
            msg += f"{date} │ {bar} {count}\n"
        
        await render_heatmap.finish(MessageSegment.image(text_to_bytes_io(msg.strip())), reply_message=True)
        
    except Exception as e:
        import traceback
        log.error(f"[mai热度] 查询失败:\n{traceback.format_exc()}")
        await render_heatmap.finish(f"⚠️ 查询热力图失败: {type(e).__name__}", reply_message=True)
