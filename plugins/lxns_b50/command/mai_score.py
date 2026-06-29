import re
import traceback
from typing import Any, Optional
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.params import CommandArg, Depends
from nonebot.exception import FinishedException
from loguru import logger as log

try:
    from zhconv import convert as zh_convert
except ImportError:
    zh_convert = None

from ..libraries.maimaidx_best_50 import generate
from ..libraries.maimaidx_error import UserNotBindLXNSError, UserNotBindFishError
from ..libraries.maimaidx_music import mai
from ..libraries.maimaidx_api_data import is_official_bot
from maimai_sync.lib_msg import _build_markdown_segment

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

best50 = on_command('b50', aliases={'B50'})
ap50 = on_command('ap50', aliases={'AP50'})
minfo = on_command('minfo', aliases={'minfo', 'Minfo', 'MINFO', 'info', 'Info', 'INFO'})
ginfo = on_command('ginfo', aliases={'ginfo', 'Ginfo', 'GINFO'})
score = on_command('分数线')

def get_at_qq(message: MessageEvent) -> Optional[int]:
    for item in message.message:
        if isinstance(item, MessageSegment) and item.type == 'at' and item.data['qq'] != 'all':
            return int(item.data['qq'])
    return None

def _search_music(name: str) -> Optional[Any]:
    music = mai.total_list.by_id(name)
    if music:
        return music
    music = mai.total_list.by_title(name)
    if music:
        return music
    name_lower = name.lower()
    for sid, aliases in mai.total_alias_list.items():
        alias_lower = [a.lower() for a in aliases]
        if name_lower in alias_lower:
            music = mai.total_list.by_id(sid)
            if music:
                return music
        if len(name_lower) >= 2 and any(name_lower in a for a in alias_lower):
            music = mai.total_list.by_id(sid)
            if music:
                return music
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
    for m in mai.total_list:
        if m.title.lower() == name_lower:
            return m
    return None

from src.plugins.qbind import get_real_qq

@best50.handle()
async def _(bot: Bot, event: MessageEvent, message: Message = CommandArg(), user_id: Optional[int] = Depends(get_at_qq)):
    raw_qq = user_id or event.user_id
    real_qq_str = get_real_qq(str(raw_qq))
    qqid = int(real_qq_str) if (real_qq_str and real_qq_str.isdigit()) else raw_qq
    username = message.extract_plain_text().strip()
    is_official = is_official_bot(bot.self_id)
    
    try:
        img_res = await generate(qqid, username)
        await best50.finish(img_res, reply_message=True)
    except FinishedException:
        raise
    except (UserNotBindLXNSError, UserNotBindFishError) as e:
        error_msg = str(UserNotBindLXNSError(is_official)) if isinstance(e, UserNotBindLXNSError) else str(UserNotBindFishError(is_official))
        if is_official:
            await best50.finish(Message(_build_markdown_segment(error_msg)))
        else:
            await best50.finish(error_msg, reply_message=True)
    except Exception:
        log.error(f"[b50] 查询遭遇未捕获异常:\n{traceback.format_exc()}")
        await best50.finish("查询遭遇技术阻塞，请确认输入的账户正确或稍后再试。", reply_message=True)

@ap50.handle()
async def _(bot: Bot, event: MessageEvent, message: Message = CommandArg(), user_id: Optional[int] = Depends(get_at_qq)):
    raw_qq = user_id or event.user_id
    real_qq_str = get_real_qq(str(raw_qq))
    qqid = int(real_qq_str) if (real_qq_str and real_qq_str.isdigit()) else raw_qq
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
            await ap50.finish(Message(_build_markdown_segment(error_msg)))
        else:
            await ap50.finish(error_msg, reply_message=True)
    except Exception:
        log.error(f"[ap50] 查询遭遇未捕获异常:\n{traceback.format_exc()}")
        await ap50.finish("查询遭遇技术阻塞，请确认输入的账户正确或稍后再试。", reply_message=True)

@minfo.handle()
async def _(event: MessageEvent, message: Message = CommandArg(), user_id: Optional[int] = Depends(get_at_qq)):
    if not player_score_data:
        await minfo.finish('本地缺少单曲成绩查询组件 (player_score_data)，无法调用此功能。', reply_message=True)
        
    raw_qq = user_id or event.user_id
    real_qq_str = get_real_qq(str(raw_qq))
    qqid = int(real_qq_str) if (real_qq_str and real_qq_str.isdigit()) else raw_qq
    name = message.extract_plain_text().strip()
    if not name:
        await minfo.finish('请输入曲名或ID', reply_message=True)
        
    music = _search_music(name)
    if not music:
        await minfo.finish('未找到该曲目，请检查输入', reply_message=True)
        
    try:
        data = await player_score_data(qqid, music)
        if isinstance(data, str) and draw_music_info:
            data = await draw_music_info(music, qqid)
        await minfo.finish(data, reply_message=True)
    except FinishedException:
        raise
    except Exception as e:
        await minfo.finish(str(e), reply_message=True)

@ginfo.handle()
async def _(message: Message = CommandArg()):
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
    except ValueError as ve:
        await ginfo.finish(str(ve), reply_message=True)
    except Exception:
        log.error(f"[ginfo] 全服统计资产渲染失败:\n{traceback.format_exc()}")
        await ginfo.finish("全服统计资产渲染失败。", reply_message=True)

@score.handle()
async def _(message: Message = CommandArg()):
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
