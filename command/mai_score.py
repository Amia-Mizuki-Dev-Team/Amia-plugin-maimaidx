import re
import traceback
from typing import Any, Optional
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.params import CommandArg, Depends
from nonebot.exception import FinishedException  # 引入框架正常退出异常
from loguru import logger as log

try:
    from zhconv import convert as zh_convert
except ImportError:
    zh_convert = None

from ..libraries.maimaidx_best_50 import generate
from ..libraries.maimaidx_error import UserNotBindLXNSError, UserNotBindFishError
from ..libraries.maimaidx_music import mai
from ..libraries.maimaidx_api_data import is_official_bot

# ==========================================
# 宽泛导入存量老版本函数，阻断 ImportError
# ==========================================
try:
    from ..libraries.maimaidx_player_score import music_global_data, player_score_data, score_line_data
except ImportError:
    music_global_data = None
    player_score_data = None
    score_line_data = None

try:
    from ..libraries.maimaidx_music_info import draw_music_info
except ImportError:
    draw_music_info = None


# ==========================================
# 指令注册总览
# ==========================================
best50      = on_command('b50', aliases={'B50'})
ap50        = on_command('ap50', aliases={'AP50'})
minfo       = on_command('minfo', aliases={'minfo', 'Minfo', 'MINFO', 'info', 'Info', 'INFO'})
ginfo       = on_command('ginfo', aliases={'ginfo', 'Ginfo', 'GINFO'})
score       = on_command('分数线')
mai_card    = on_command('mai名片', aliases={'mai信息'})
mai_rank    = on_command('mai排行', aliases={'战力排行'})
mai_analyse = on_command('mai分析', aliases={'战力分析'})
mai_report  = on_command('mai速报', aliases={'mai打卡'})
mai_skill   = on_command('mai底力', aliases={'底力分析', '底力'})


def get_at_qq(message: MessageEvent) -> Optional[int]:
    """解析消息中被 @ 用户的 QQ 号"""
    for item in message.message:
        if isinstance(item, MessageSegment) and item.type == 'at' and item.data['qq'] != 'all':
            return int(item.data['qq'])
    return None


def _search_music(name: str) -> Optional[Any]:
    """
    综合搜索曲目：按 ID → 精确标题 → 别名(含子串) → 大小写不敏感标题
    
    Params:
        `name`: 搜索关键字
    Returns:
        `Optional[Music]`
    """
    music = mai.total_list.by_id(name)
    if music:
        return music
    music = mai.total_list.by_title(name)
    if music:
        return music
    # 别名检索（精确匹配 + 子串匹配）
    name_lower = name.lower()
    for sid, aliases in mai.total_alias_list.items():
        alias_lower = [a.lower() for a in aliases]
        # 精确匹配
        if name_lower in alias_lower:
            music = mai.total_list.by_id(sid)
            if music:
                return music
        # 子串匹配：搜索词是某个别名的子串（长度 >= 2 避免单字误匹配）
        if len(name_lower) >= 2 and any(name_lower in a for a in alias_lower):
            music = mai.total_list.by_id(sid)
            if music:
                return music
    # 简繁转换后再尝试别名检索
    if zh_convert:
        for src in (zh_convert(name_lower, 'zh-cn'), zh_convert(name_lower, 'zh-tw')):
            if src == name_lower:
                continue
            for sid, aliases in mai.total_alias_list.items():
                alias_lower = [a.lower() for a in aliases]
                if src in alias_lower or (len(src) >= 2 and any(src in a for a in alias_lower)):
                    music = mai.total_list.by_id(sid)
                    if music:
                        return music
    # 大小写不敏感标题匹配
    for m in mai.total_list:
        if m.title.lower() == name_lower:
            return m
    return None


@best50.handle()
async def _(bot: Bot, event: MessageEvent, message: Message = CommandArg(), user_id: Optional[int] = Depends(get_at_qq)):
    """生成 Best 50"""
    qqid = user_id or event.user_id
    username = message.extract_plain_text().strip()
    is_official = is_official_bot(bot.self_id)
    
    try:
        img_res = await generate(qqid, username)
        await best50.finish(img_res, reply_message=True)
    except FinishedException:
        raise  # 显式放行正常退出信号，屏蔽错误日志
    except (UserNotBindLXNSError, UserNotBindFishError) as e:
        error_msg = str(UserNotBindLXNSError(is_official)) if isinstance(e, UserNotBindLXNSError) else str(UserNotBindFishError(is_official))
        if is_official:
            md_data = {"markdown": {"content": error_msg}}
            await bot.send(event=event, message=MessageSegment(type="markdown", data={"data": md_data}))
        else:
            await best50.finish(error_msg, reply_message=True)
    except Exception:
        log.error(f"[b50] 查询遭遇未捕获异常:\n{traceback.format_exc()}")
        await best50.finish("⚠️ 查询遭遇技术阻塞，请确认输入的账户正确或稍后再试。", reply_message=True)


@ap50.handle()
async def _(bot: Bot, event: MessageEvent, message: Message = CommandArg(), user_id: Optional[int] = Depends(get_at_qq)):
    """生成 AP 50"""
    qqid = user_id or event.user_id
    username = message.extract_plain_text().strip()
    is_official = is_official_bot(bot.self_id)
    
    try:
        img_res = await generate(qqid, username, is_ap=True)
        await ap50.finish(img_res, reply_message=True)
    except FinishedException:
        raise
    except (UserNotBindLXNSError, UserNotBindFishError) as e:
        error_msg = str(UserNotBindLXNSError(is_official)) if isinstance(e, UserNotBindLXNSError) else str(UserNotBindFishError(is_official))
        if is_official:
            md_data = {"markdown": {"content": error_msg}}
            await bot.send(event=event, message=MessageSegment(type="markdown", data={"data": md_data}))
        else:
            await ap50.finish(error_msg, reply_message=True)
    except Exception:
        log.error(f"[ap50] 查询遭遇未捕获异常:\n{traceback.format_exc()}")
        await ap50.finish("⚠️ 查询遭遇技术阻塞，请确认输入的账户正确或稍后再试。", reply_message=True)


@minfo.handle()
async def _(event: MessageEvent, message: Message = CommandArg(), user_id: Optional[int] = Depends(get_at_qq)):
    """查询单曲游玩数据"""
    if not player_score_data:
        await minfo.finish('本地缺少单曲成绩查询组件 (player_score_data)，无法调用此功能。', reply_message=True)
        
    qqid = user_id or event.user_id
    name = message.extract_plain_text().strip()
    if not name:
        await minfo.finish('请输入曲名或ID', reply_message=True)
        
    music = _search_music(name)
    if not music:
        await minfo.finish('未找到该曲目，请检查输入', reply_message=True)
        
    try:
        data = await player_score_data(qqid, music)
        # 如果返回的是纯文本（用户无数据/未游玩），改用 draw_music_info 显示曲目详情
        if isinstance(data, str) and draw_music_info:
            data = await draw_music_info(music, qqid)
        await minfo.finish(data, reply_message=True)
    except FinishedException:
        raise
    except Exception as e:
        await minfo.finish(str(e), reply_message=True)


@ginfo.handle()
async def _(message: Message = CommandArg()):
    """查询单曲全服统计图"""
    if not music_global_data:
        await ginfo.finish('本地缺少全服统计组件 (music_global_data)。', reply_message=True)
        
    args = message.extract_plain_text().strip()
    match = re.match(r'^([绿黄红紫白]?)\s*(.+)$', args, re.IGNORECASE)
    if not match:
        await ginfo.finish('命令格式错误。例: ginfo紫799', reply_message=True)
        
    diff_char = match.group(1)
    name = match.group(2)
    level_index = '绿黄红紫白'.index(diff_char) if diff_char else 3
        
    music = mai.total_list.by_id(name) or mai.total_list.by_title(name)
    if not music:
        await ginfo.finish('未找到该曲目', reply_message=True)
        
    try:
        pic = await music_global_data(music, level_index)
        await ginfo.finish(pic, reply_message=True)
    except FinishedException:
        raise
    except Exception:
        log.error(f"[ginfo] 全服统计资产渲染失败:\n{traceback.format_exc()}")
        await ginfo.finish("⚠️ 全服统计资产渲染失败。", reply_message=True)


@score.handle()
async def _(message: Message = CommandArg()):
    """查询分数线"""
    if not score_line_data:
        await score.finish('本地缺少分数线查询组件 (score_line_data)。', reply_message=True)
        
    args = message.extract_plain_text().strip().split()
    if len(args) < 2:
        await score.finish('命令格式错误。例: 分数线 紫799 100', reply_message=True)
        
    target_score = args[-1]
    name = " ".join(args[:-1])
    
    match = re.match(r'^([绿黄红紫白]?)\s*(.+)$', name, re.IGNORECASE)
    if not match:
        await score.finish('无法解析难度，例: 分数线 紫799 100', reply_message=True)
        
    diff_char = match.group(1)
    song_name = match.group(2)
    level_index = '绿黄红紫白'.index(diff_char) if diff_char else 3
        
    music = mai.total_list.by_id(song_name) or mai.total_list.by_title(song_name)
    if not music:
        await score.finish('未找到该曲目', reply_message=True)
        
    try:
        result_text = score_line_data(music, level_index, float(target_score))
        await score.finish(result_text, reply_message=True)
    except FinishedException:
        raise
    except ValueError:
        await score.finish('目标达成率输入错误，请输入数字', reply_message=True)


@mai_card.handle()
async def _(bot: Bot, event: MessageEvent, message: Message = CommandArg(), user_id: Optional[int] = Depends(get_at_qq)):
    """生成个人名片大图"""
    qqid = user_id or event.user_id
    try:
        from ..libraries.maimaidx_player_score import draw_player_card
        img_res = await draw_player_card(qqid)
        await mai_card.finish(img_res, reply_message=True)
    except FinishedException:
        raise
    except Exception as e:
        log.error(f"[mai名片] 错误: {traceback.format_exc()}")
        await mai_card.finish(f"⚠️ 生成名片失败: {e}", reply_message=True)


@mai_rank.handle()
async def _(bot: Bot, event: MessageEvent):
    """群内 Rating 排行榜"""
    from nonebot.adapters.onebot.v11 import GroupMessageEvent
    if not isinstance(event, GroupMessageEvent):
        await mai_rank.finish("⚠️ 战力排行（群排行）仅支持在群聊中使用！", reply_message=True)

    group_id = event.group_id
    try:
        # 1. 获取群信息与群成员列表
        try:
            group_info = await bot.get_group_info(group_id=group_id)
            group_name = group_info.get("group_name", "本群")
        except Exception:
            group_name = "本群"

        await mai_rank.send("🔍 正在拉取群友绑定数据与 Rating 战力排行，请稍候...")

        member_list = await bot.get_group_member_list(group_id=group_id)
        # QQ号 -> 显示昵称（群名片优先，其次是QQ昵称）
        qq_to_card = {m["user_id"]: (m["card"] or m["nickname"]) for m in member_list}
        qq_list = list(qq_to_card.keys())

        # 2. 批量从本地和云端数据库查询已绑定的QQ号
        import json
        import time
        import asyncio
        from pathlib import Path
        from PIL import Image, ImageDraw
        from sqlalchemy import select
        from maimai_sync.lib_db import local_db, cloud_db, UserBind
        from ..config import static, maidir, SIYUAN, TBFONT, maiconfig
        from ..libraries.image import DrawText, image_to_base64
        from ..libraries.maimaidx_best_50 import coloumWidth, changeColumnWidth
        from ..libraries.maimaidx_api_data import maiApi

        bound_qqs = set()
        qq_strs = [str(qq) for qq in qq_list]

        if local_db and local_db.session_maker:
            try:
                async with local_db.session() as session:
                    stmt = select(UserBind.qq).where(UserBind.qq.in_(qq_strs))
                    result = await session.execute(stmt)
                    for row in result.all():
                        bound_qqs.add(row[0])
            except Exception as e:
                log.error(f"本地DB批量查询绑定状态失败: {e}")

        if cloud_db and cloud_db.session_maker:
            try:
                async with cloud_db.session() as session:
                    stmt = select(UserBind.qq).where(UserBind.qq.in_(qq_strs))
                    result = await session.execute(stmt)
                    for row in result.all():
                        bound_qqs.add(row[0])
            except Exception as e:
                log.error(f"云端DB批量查询绑定状态失败: {e}")

        # 如果通过数据库什么都没查到，回退单条查询（不超过20个，防止卡死）
        if not bound_qqs and len(qq_strs) <= 20:
            from maimai_sync.lib_db import get_user_bind_async
            for qq in qq_strs:
                bind = await get_user_bind_async(qq)
                if bind.get("fish") or bind.get("lxns"):
                    bound_qqs.add(qq)

        if not bound_qqs:
            await mai_rank.finish("❌ 本群暂无已绑定查分器的群友，快发送“mai绑定”进行绑定吧！", reply_message=True)

        # 3. 读取和更新 Rating 缓存
        CACHE_DIR = Path("data/lxns_b50")
        CACHE_FILE = CACHE_DIR / "rating_cache.json"

        cache = {}
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    cache = json.load(f)
            except Exception as e:
                log.error(f"加载 Rating 缓存失败: {e}")

        now = time.time()
        semaphore = asyncio.Semaphore(3)  # 控制并发

        async def update_player_rating(qq: str):
            cached_item = cache.get(str(qq))
            # 缓存有效期 4 小时 (14400秒)
            if cached_item and (now - cached_item.get("updated_at", 0) < 14400):
                return

            async with semaphore:
                try:
                    user_info = await maiApi.query_user_b50(qqid=int(qq))
                    if user_info and user_info.rating > 0:
                        cache[str(qq)] = {
                            "nickname": user_info.nickname,
                            "rating": user_info.rating,
                            "updated_at": now
                        }
                    else:
                        if str(qq) not in cache:
                            cache[str(qq)] = {
                                "nickname": qq_to_card.get(int(qq), f"未知玩家({qq})"),
                                "rating": 0,
                                "updated_at": now - 12000
                            }
                except Exception as e:
                    log.warning(f"获取 QQ {qq} 的 Rating 失败: {e}")
                    if cached_item:
                        cached_item["updated_at"] = now - 14400 + 1800  # 30分钟后重试
                        cache[str(qq)] = cached_item
                    else:
                        cache[str(qq)] = {
                            "nickname": qq_to_card.get(int(qq), f"未知玩家({qq})"),
                            "rating": 0,
                            "updated_at": now - 14400 + 1800
                        }

        # 运行并发拉取
        tasks = [update_player_rating(qq) for qq in bound_qqs]
        await asyncio.gather(*tasks)

        # 保存最新的缓存
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=4)
        except Exception as e:
            log.error(f"保存 Rating 缓存失败: {e}")

        # 4. 构建排行榜数据并排序
        rank_list = []
        for qq_str in bound_qqs:
            cached_item = cache.get(qq_str)
            if cached_item and cached_item.get("rating", 0) > 0:
                qq_int = int(qq_str)
                # 优先显示群名片，如果没有才显示查分器昵称
                show_name = qq_to_card.get(qq_int) or cached_item.get("nickname") or qq_str
                rank_list.append({
                    "qq": qq_str,
                    "show_name": show_name,
                    "rating": cached_item["rating"]
                })

        if not rank_list:
            await mai_rank.finish("❌ 未能在已绑定的群友中获取到有效的 Rating 数据（可能尚未开始同步或查分器未初始化）。", reply_message=True)

        rank_list.sort(key=lambda x: x["rating"], reverse=True)
        # 限制最多前100人
        rank_list = rank_list[:100]

        # 5. 动态计算高度并绘图
        row_height = 52
        height = 240 + len(rank_list) * row_height + 100
        
        im = Image.new('RGBA', (1000, height), (25, 28, 41, 255))
        dr = ImageDraw.Draw(im)
        sy = DrawText(dr, SIYUAN)
        tb = DrawText(dr, TBFONT)
        
        # 渐变背景
        for y in range(height):
            ratio = y / float(height)
            r = int(20 * (1 - ratio) + 35 * ratio)
            g = int(24 * (1 - ratio) + 40 * ratio)
            b = int(35 * (1 - ratio) + 65 * ratio)
            dr.line([(0, y), (1000, y)], fill=(r, g, b, 255))
            
        # 背景纹理
        pattern_path = maidir / 'pattern.png'
        if pattern_path.exists():
            try:
                pat = Image.open(pattern_path).convert('RGBA')
                for h in range((height // pat.height) + 1):
                    im.alpha_composite(pat, (0, h * pat.height))
            except Exception:
                pass

        # 绘制标题
        sy.draw(500, 60, 42, "🏆 群内 Rating 战力排行榜 🏆", (255, 255, 255, 255), 'mm')
        sy.draw(500, 110, 18, f"{group_name} • LEADERBOARD", (150, 180, 220, 255), 'mm')
        
        # 表头
        dr.rounded_rectangle((60, 160, 940, 215), radius=8, fill=(35, 45, 75, 255))
        sy.draw(120, 188, 20, "排名", (255, 255, 255, 255), 'mm')
        sy.draw(450, 188, 20, "玩家昵称", (255, 255, 255, 255), 'mm')
        sy.draw(820, 188, 20, "Rating 战力", (255, 255, 255, 255), 'mm')

        # 绘制行
        for idx, item in enumerate(rank_list):
            rank = idx + 1
            show_name = item["show_name"]
            ra = item["rating"]
            
            y_pos = 230 + idx * row_height
            bg_color = (35, 45, 75, 150) if rank % 2 == 1 else (25, 30, 55, 150)
            dr.rounded_rectangle((60, y_pos, 940, y_pos + 46), radius=5, fill=bg_color)
            
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
            
            if coloumWidth(show_name) > 30:
                show_name = changeColumnWidth(show_name, 29) + "..."
            sy.draw(450, y_pos + 23, 20, show_name, (255, 255, 255, 255), 'mm')
            
            tb.draw(820, y_pos + 23, 22, str(ra), (100, 220, 255, 255), 'mm')

        footer_y = height - 50
        sy.draw(500, footer_y, 16, "数据源：落雪/水鱼查分器  |  Powered By MizukiBot lxns_b50", (130, 140, 160, 255), 'mm')

        await mai_rank.finish(MessageSegment.image(image_to_base64(im)), reply_message=True)
    except FinishedException:
        raise
    except Exception as e:
        log.error(f"[mai排行] 错误: {traceback.format_exc()}")
        await mai_rank.finish(f"⚠️ 生成排行榜失败: {e}", reply_message=True)


@mai_analyse.handle()
async def _(event: MessageEvent, user_id: Optional[int] = Depends(get_at_qq)):
    """多维战力构成深度分析"""
    qqid = user_id or event.user_id
    try:
        from ..libraries.maimaidx_player_score import draw_rating_analysis
        img_res = await draw_rating_analysis(qqid)
        await mai_analyse.finish(img_res, reply_message=True)
    except FinishedException:
        raise
    except Exception as e:
        log.error(f"[mai分析] 错误: {traceback.format_exc()}")
        await mai_analyse.finish(f"⚠️ 战力分析失败: {e}", reply_message=True)


@mai_report.handle()
async def _(bot: Bot, event: MessageEvent, message: Message = CommandArg(), user_id: Optional[int] = Depends(get_at_qq)):
    """生成精致的最近游玩成绩打卡速报分享图"""
    qqid = user_id or event.user_id
    current_source = user_source_route.get(qqid, maiconfig.prober_source.lower())
    if current_source != 'lxns':
        await mai_report.finish("⚠️ 速报/打卡卡片功能目前由落雪 API 独占特供，请先切换默认输出端为落雪查分器！", reply_message=True)
        
    try:
        import httpx
        headers = {"Authorization": maiconfig.lxnstoken}
        async with httpx.AsyncClient(timeout=15) as client:
            # 获取 friend_code
            res = await client.get(f"https://maimai.lxns.net/api/v0/maimai/player/qq/{qqid}", headers=headers)
            if res.status_code != 200:
                await mai_report.finish("❌ 未在落雪找到您的绑定信息，请先绑定落雪查分器。", reply_message=True)
            player_data = res.json().get("data", {})
            friend_code = player_data.get("friend_code")
            if not friend_code:
                await mai_report.finish("❌ 无法获取您的落雪好友码", reply_message=True)
                
            # 获取最近游玩成绩
            recents_res = await client.get(
                f"https://maimai.lxns.net/api/v0/maimai/player/{friend_code}/recents",
                headers=headers
            )
            if recents_res.status_code != 200:
                await mai_report.finish("❌ 获取最近成绩记录失败，可能暂无最近游玩数据", reply_message=True)
            recents = recents_res.json().get("data", [])
            if not recents:
                await mai_report.finish("📭 暂无最近游玩记录", reply_message=True)
                
        # 获取最新的游玩数据
        latest_play = recents[0]
        from ..libraries.maimaidx_player_score import draw_speedy_report
        img_segment = draw_speedy_report(player_data.get('name', '未知'), latest_play)
        await mai_report.finish(img_segment, reply_message=True)
        
    except FinishedException:
        raise
    except Exception as e:
        log.error(f"[mai速报] 错误: {traceback.format_exc()}")
        await mai_report.finish(f"⚠️ 生成速报卡片失败: {e}", reply_message=True)


@mai_skill.handle()
async def _(event: MessageEvent, user_id: Optional[int] = Depends(get_at_qq)):
    """高难底力深度分析与段位评定"""
    qqid = user_id or event.user_id
    try:
        from ..libraries.maimaidx_player_score import draw_skill_analysis
        img_res = await draw_skill_analysis(qqid)
        await mai_skill.finish(img_res, reply_message=True)
    except FinishedException:
        raise
    except Exception as e:
        log.error(f"[mai底力] 错误: {traceback.format_exc()}")
        await mai_skill.finish(f"⚠️ 底力分析失败: {e}", reply_message=True)
