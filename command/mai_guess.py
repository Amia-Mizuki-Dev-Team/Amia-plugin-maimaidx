import asyncio

from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import GROUP_ADMIN, GROUP_OWNER, GroupMessageEvent, MessageSegment
from nonebot.matcher import Matcher
from nonebot.permission import SUPERUSER
from nonebot.log import logger as log

from ..libraries.maimaidx_music import guess
from ..libraries.maimaidx_music_info import *
from ..libraries.maimaidx_update_plate import *


def is_now_playing_guess_music(event: GroupMessageEvent) -> bool:
    return event.group_id in guess.Group

guess_music_start   = on_command('猜歌', aliases={'mai猜歌'})
guess_music_pic     = on_command('猜曲绘', aliases={'mai猜曲绘'})
guess_music_voice   = on_command('听歌猜歌', aliases={'听歌猜曲', 'mai听歌猜歌', 'mai听歌猜曲'})
guess_music_alias   = on_command('别名猜歌', aliases={'猜别名', 'mai别名猜歌', 'mai猜别名'})
guess_music_solve   = on_message(rule=is_now_playing_guess_music)
guess_music_reset   = on_command('重置猜歌', aliases={'mai重置猜歌'}, permission=SUPERUSER | GROUP_OWNER | GROUP_ADMIN)
guess_music_enable  = on_command('开启mai猜歌', permission=SUPERUSER | GROUP_OWNER | GROUP_ADMIN)
guess_music_disable = on_command('关闭mai猜歌', permission=SUPERUSER | GROUP_OWNER | GROUP_ADMIN)



@guess_music_start.handle()
async def _(event: GroupMessageEvent):
    gid = event.group_id
    if gid in guess.Group:
        await guess_music_start.finish('该群已有正在进行的猜歌或猜曲绘')
    guess.start(gid)
    await guess_music_start.send(
        dedent('''\
            我将从热门乐曲中选择一首歌，每隔8秒描述它的特征，
            请输入歌曲的 id 标题 或 别名（需bot支持，无需大小写）进行猜歌（DX乐谱和标准乐谱视为两首歌）。
            猜歌时查歌等其他命令依然可用。
        ''')
    )
    await asyncio.sleep(4)
    for cycle in range(7):
        if gid not in guess.Group or guess.Group[gid].end:
            break
        if cycle < 6:
            await guess_music_start.send(f'{cycle + 1}/7 这首歌{guess.Group[gid].options[cycle]}')
            await asyncio.sleep(8)
        else:
            await guess_music_start.send(
                MessageSegment.text('7/7 这首歌封面的一部分是：\n') + 
                MessageSegment.image(guess.Group[gid].img) + 
                MessageSegment.text('答案将在30秒后揭晓')
            )
            for _ in range(30):
                await asyncio.sleep(1)
                if gid in guess.Group:
                    if guess.Group[gid].end:
                        await guess_music_start.finish()
                else:
                    await guess_music_start.finish()
            guess.Group[gid].end = True
            answer = MessageSegment.text('答案是：\n') + await draw_music_info(guess.Group[gid].music)
            guess.end(gid)
            await guess_music_start.finish(answer)


@guess_music_pic.handle()
async def _(event: GroupMessageEvent):
    gid = event.group_id
    if gid in guess.Group:
        await guess_music_pic.finish('该群已有正在进行的猜歌或猜曲绘', reply_message=True)
    guess.startpic(gid)
    await guess_music_pic.send(
        MessageSegment.text('以下裁切图片是哪首谱面的曲绘：\n') +
        MessageSegment.image(guess.Group[gid].img) +
        MessageSegment.text('请在30s内输入答案')
    )
    for _ in range(30):
        await asyncio.sleep(1)
        if gid in guess.Group:
            if guess.Group[gid].end:
                await guess_music_pic.finish()
        else:
            await guess_music_pic.finish()
    guess.Group[gid].end = True
    answer = MessageSegment.text('答案是：\n') + await draw_music_info(guess.Group[gid].music)
    guess.end(gid)
    await guess_music_pic.finish(answer)


@guess_music_solve.handle()
async def _(event: GroupMessageEvent):
    gid = event.group_id
    if gid not in guess.Group:
        await guess_music_solve.finish()
    ans = event.get_plaintext().strip()
    if ans.lower() in guess.Group[gid].answer:
        guess.Group[gid].end = True
        answer = MessageSegment.text('猜对了，答案是：\n') + \
            await draw_music_info(guess.Group[gid].music)
        guess.end(gid)
        await guess_music_solve.finish(answer, reply_message=True)


@guess_music_reset.handle()
async def _(event: GroupMessageEvent):
    gid = event.group_id
    if gid in guess.Group:
        msg = '已重置该群猜歌'
        guess.end(gid)
    else:
        msg = '该群未处在猜歌状态'
    await guess_music_reset.finish(msg, reply_message=True)


@guess_music_enable.handle()
@guess_music_disable.handle()
async def _(matcher: Matcher, event: GroupMessageEvent):
    await guess_music_enable.finish("💡 猜歌小游戏在此群默认永久开启，无需手动开关，直接发送 猜歌 / 猜曲绘 等指令即可开启游玩！", reply_message=True)


@guess_music_voice.handle()
async def _(event: GroupMessageEvent):
    gid = event.group_id
    if gid in guess.Group:
        await guess_music_voice.finish('该群已有正在进行的猜歌或猜曲绘', reply_message=True)
    
    await guess_music_voice.send('正在从落雪下载并切片音频，请稍候...')
    try:
        sliced_audio = await guess.start_voice(gid)
    except Exception as e:
        log.error(f"听歌猜歌启动失败: {e}")
        await guess_music_voice.finish(f'听歌猜歌启动失败: {e}', reply_message=True)
        
    await guess_music_voice.send(
        MessageSegment.record(sliced_audio) +
        MessageSegment.text('\n请听上面这首歌曲的 10 秒片段，在 30 秒内猜出歌名或 ID！')
    )
    for _ in range(30):
        await asyncio.sleep(1)
        if gid in guess.Group:
            if guess.Group[gid].end:
                await guess_music_voice.finish()
        else:
            await guess_music_voice.finish()
    guess.Group[gid].end = True
    answer = MessageSegment.text('答案是：\n') + await draw_music_info(guess.Group[gid].music)
    guess.end(gid)
    await guess_music_voice.finish(answer)


@guess_music_alias.handle()
async def _(event: GroupMessageEvent):
    gid = event.group_id
    if gid in guess.Group:
        await guess_music_alias.finish('该群已有正在进行的猜歌或猜曲绘', reply_message=True)
        
    try:
        alias = guess.start_alias(gid)
    except Exception as e:
        log.error(f"别名猜歌启动失败: {e}")
        await guess_music_alias.finish(f'别名猜歌启动失败: {e}', reply_message=True)
        
    await guess_music_alias.send(
        f"【别名猜歌】这是哪首歌的别名：\n『 {alias} 』\n请在 30 秒内输入答案！"
    )
    for _ in range(30):
        await asyncio.sleep(1)
        if gid in guess.Group:
            if guess.Group[gid].end:
                await guess_music_alias.finish()
        else:
            await guess_music_alias.finish()
    guess.Group[gid].end = True
    answer = MessageSegment.text('答案是：\n') + await draw_music_info(guess.Group[gid].music)
    guess.end(gid)
    await guess_music_alias.finish(answer)