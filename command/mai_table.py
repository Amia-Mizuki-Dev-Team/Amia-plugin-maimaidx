import re
from typing import Optional

from nonebot import on_fullmatch, on_regex
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment, PrivateMessageEvent
from nonebot.params import Depends, RegexMatched
from nonebot.permission import SUPERUSER

from ..dependencies import get_at_user_id, get_real_qq
from ..libraries.maimaidx_error import OAuthConsentRequiredError
from ..release010_import import send_error_with_diagnostic

from ..libraries.maimaidx_music_info import *
from ..libraries.maimaidx_player_score import *
from ..libraries.maimaidx_update_plate import *

update_table            = on_fullmatch('更新定数表', permission=SUPERUSER)
update_plate            = on_fullmatch('更新完成表', permission=SUPERUSER)
rating_table            = on_regex(r'([0-9]+\+?)定数表')
rating_table_pfm        = on_regex(r'^([0-9]+\+?)(([apfcp]+|\+)+)?完成表$', re.IGNORECASE)
plate_table_pfm         = on_regex(r'^([真超檄橙暁晓桃櫻樱紫菫堇白雪輝辉舞霸熊華华爽煌星宙祭祝双宴镜彩])([極极将舞神者]舞?)完成表$')
rise_score              = on_regex(r'^我要在?([0-9]+\+?)?[上加\+]([0-9]+)?分\s?(.+)?')
plate_process           = on_regex(r'^([真超檄橙暁晓桃櫻樱紫菫堇白雪輝辉舞霸熊華华爽煌星宙祭祝双宴镜彩])([極极将舞神者]舞?)进度\s?(.+)?')
level_process           = on_regex(r'^([0-9]+\+?)\s?([abcdsfxp\+]+)\s?([\u4e00-\u9fa5]+)?\s?进度\s?([0-9]+)?(.+)?', re.IGNORECASE)
level_achievement_list  = on_regex(r'^([0-9]+\.?[0-9]?\+?)\s?分数列表\s?([0-9]+)?\s?(.+)?')


def get_at_qq(message: MessageEvent) -> Optional[int]:
    for item in message.message:
        if isinstance(item, MessageSegment):
            target = get_at_user_id(item)
            if target is not None:
                return target
    return None


def _bound_user_id(value: object) -> int | str | None:
    """Use the real qbind identity before deriving an OAuth subject."""
    raw = str(value)
    real = get_real_qq(raw)
    if real:
        return int(real) if str(real).isdigit() else str(real)
    return None


async def _finish_unbound(matcher) -> None:
    await matcher.finish(
        "我还没把你的平台身份绑定到真实 QQ，先完成 qbind 绑定后再查询水鱼成绩。",
        reply_message=True,
    )


@update_table.handle()
async def _(event: PrivateMessageEvent):
    await update_table.finish(await update_rating_table())
    

@update_plate.handle()
async def _(event: PrivateMessageEvent):
    await update_plate.finish(await update_plate_table())


@rating_table.handle()
async def _(match = RegexMatched()):
    args = match.group(1).strip()
    if args in levelList[:6]:
        await rating_table.finish('只支持查询lv7-15的定数表', reply_message=True)
    elif args in levelList[6:]:
        path = ratingdir / f'{args}.png'
        pic = draw_rating(args, path)
        await rating_table.finish(pic, reply_message=True)
    else:
        await rating_table.finish('无法识别的定数', reply_message=True)


@rating_table_pfm.handle()
async def _(bot: Bot, event: MessageEvent, match = RegexMatched()):
    ra = match.group(1)
    plan = match.group(2)
    if ra in levelList[:6]:
        await rating_table_pfm.finish('只支持查询lv7-15的完成表', reply_message=True)
    elif ra in levelList[6:]:
        qqid = _bound_user_id(event.user_id)
        if qqid is None:
            await _finish_unbound(rating_table_pfm)
            return
        try:
            pic = await draw_rating_table(qqid, ra, True if plan and plan.lower() in comboRank else False)
        except OAuthConsentRequiredError:
            await rating_table_pfm.finish(
                "水鱼完整成绩需要 OAuth 授权，请发送「绑定水鱼」。",
                reply_message=True,
            )
        except Exception as exc:
            await send_error_with_diagnostic(rating_table_pfm, exc, "MAI", context="完成表")
            return
        await rating_table_pfm.finish(pic, reply_message=True)
    else:
        await rating_table_pfm.finish('无法识别的定数', reply_message=True)


@plate_table_pfm.handle()
async def _(bot: Bot, event: MessageEvent, match = RegexMatched()):
    ver = match.group(1)
    plan = match.group(2)
    if ver in platecn:
        ver = platecn[ver]
    if ver in ['舞', '霸']:
        await plate_table_pfm.finish('暂不支持查询「舞」系和「霸者」的牌子', reply_message=True)
    if f'{ver}{plan}' == '真将':
        await plate_table_pfm.finish('真系没有真将哦', reply_message=True)
    qqid = _bound_user_id(event.user_id)
    if qqid is None:
        await _finish_unbound(plate_table_pfm)
        return
    try:
        pic = await draw_plate_table(qqid, ver, plan)
    except OAuthConsentRequiredError:
        await plate_table_pfm.finish(
            "水鱼完整成绩需要 OAuth 授权，请发送「绑定水鱼」。",
            reply_message=True,
        )
    except Exception as exc:
        await send_error_with_diagnostic(plate_table_pfm, exc, "MAI", context="牌子进度")
        return
    await plate_table_pfm.finish(pic, reply_message=True)


@rise_score.handle()
async def _(bot: Bot, event: MessageEvent, match = RegexMatched(), user_id: Optional[int] = Depends(get_at_qq)):
    username = None
    
    rating = match.group(1)
    score = match.group(2)
    
    if rating and rating not in levelList:
        await rise_score.finish('无此等级', reply_message=True)
    elif match.group(3):
        username = match.group(3).strip()
    qqid = None if username else _bound_user_id(user_id or event.user_id)
    if qqid is None and not username:
        await _finish_unbound(rise_score)
        return

    try:
        data = await rise_score_data(qqid, username, rating, score)
    except OAuthConsentRequiredError:
        if username:
            await rise_score.finish("指定用户名还没有授权水鱼，请让该用户本人发送「绑定水鱼」。", reply_message=True)
            return
        await rise_score.finish(
            "水鱼完整成绩需要 OAuth 授权，请发送「绑定水鱼」。",
            reply_message=True,
        )
    except Exception as exc:
        await send_error_with_diagnostic(rise_score, exc, "MAI", context="上分推荐")
        return
    await rise_score.finish(data, reply_message=True)


@plate_process.handle()
async def _(bot: Bot, event: MessageEvent, match = RegexMatched(), user_id: Optional[int] = Depends(get_at_qq)):
    ver = match.group(1)
    plan = match.group(2)
    
    if f'{ver}{plan}' == '真将':
        await plate_process.finish('真系没有真将哦', reply_message=True)

    qqid = _bound_user_id(user_id or event.user_id)
    if qqid is None:
        await _finish_unbound(plate_process)
        return

    try:
        data = await player_plate_data(qqid, '', ver, plan)
    except OAuthConsentRequiredError:
        await plate_process.finish(
            "水鱼完整成绩需要 OAuth 授权，请发送「绑定水鱼」。",
            reply_message=True,
        )
    except Exception as exc:
        await send_error_with_diagnostic(plate_process, exc, "MAI", context="牌子进度")
        return
    await plate_process.finish(data, reply_message=True)


@level_process.handle()
async def _(bot: Bot, event: MessageEvent, match = RegexMatched(), user_id: Optional[int] = Depends(get_at_qq)):
    level = match.group(1)
    plan = match.group(2)
    category = match.group(3)
    page = match.group(4)
    username = match.group(5)
    qqid = None if username else _bound_user_id(user_id or event.user_id)
    if qqid is None and not username:
        await _finish_unbound(level_process)
        return
    
    if level not in levelList:
        await level_process.finish('无此等级', reply_message=True)
    if plan.lower() not in scoreRank + comboRank + syncRank:
        await level_process.finish('无此评价等级', reply_message=True)
    if levelList.index(level) < 11 or (plan.lower() in scoreRank and scoreRank.index(plan.lower()) < 8):
        await level_process.finish('兄啊，有点志向好不好', reply_message=True)
    if category:
        if category in ['已完成', '未完成', '未开始']:
            _c = {
                '已完成': 'completed',
                '未完成': 'unfinished',
                '未开始': 'notstarted',
                '未游玩': 'notstarted'
            }
            category = _c[category]
        else:
            await level_process.finish(f'无法指定查询「{category}」', reply_message=True)
    else:
        category = 'default'

    try:
        data = await level_process_data(qqid, username, level, plan, category, int(page) if page else 1)
    except OAuthConsentRequiredError:
        if username:
            await level_process.finish("指定用户名还没有授权水鱼，请让该用户本人发送「绑定水鱼」。", reply_message=True)
            return
        await level_process.finish(
            "水鱼完整成绩需要 OAuth 授权，请发送「绑定水鱼」。",
            reply_message=True,
        )
    except Exception as exc:
        await send_error_with_diagnostic(level_process, exc, "MAI", context="等级进度")
        return
    await level_process.finish(data, reply_message=True)


@level_achievement_list.handle()
async def _(bot: Bot, event: MessageEvent, match = RegexMatched(), user_id: Optional[int] = Depends(get_at_qq)):
    rating = match.group(1)
    page = match.group(2)
    username = match.group(3)
    qqid = None if username else _bound_user_id(user_id or event.user_id)
    if qqid is None and not username:
        await _finish_unbound(level_achievement_list)
        return
    
    try:
        if '.' in rating:
            rating = round(float(rating), 1)
        elif rating not in levelList:
            await level_achievement_list.finish('无此等级', reply_message=True)
    except ValueError:
        if rating not in levelList:
            await level_achievement_list.finish('无此等级', reply_message=True)

    try:
        data = await level_achievement_list_data(qqid, username, rating, int(page) if page else 1)
    except OAuthConsentRequiredError:
        if username:
            await level_achievement_list.finish("指定用户名还没有授权水鱼，请让该用户本人发送「绑定水鱼」。", reply_message=True)
            return
        await level_achievement_list.finish(
            "水鱼完整成绩需要 OAuth 授权，请发送「绑定水鱼」。",
            reply_message=True,
        )
    except Exception as exc:
        await send_error_with_diagnostic(level_achievement_list, exc, "MAI", context="分数列表")
        return
    await level_achievement_list.finish(data, reply_message=True)
