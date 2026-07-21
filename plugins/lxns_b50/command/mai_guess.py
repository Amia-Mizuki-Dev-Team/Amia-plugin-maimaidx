import asyncio
import io
import random
from pathlib import Path
from textwrap import dedent

from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import GROUP_ADMIN, GROUP_OWNER, GroupMessageEvent, MessageSegment
from nonebot.matcher import Matcher
from nonebot.permission import SUPERUSER
from PIL import Image

from ..libraries.maimaidx_music import guess
from ..libraries.maimaidx_music_info import draw_music_info


def _guess_image_segment(image_path) -> MessageSegment:
    """Pass generated local images as bytes so Gensokyo can publish them."""

    path = Path(str(image_path))
    try:
        return MessageSegment.image(path.read_bytes())
    except (OSError, ValueError):
        # Keep the existing adapter fallback for remote URLs or already
        # normalized image references.
        return MessageSegment.image(str(image_path))


def _guess_partial_image_segment(image_path) -> MessageSegment:
    """Send a random square crop instead of revealing the whole cover."""

    path = Path(str(image_path))
    try:
        with Image.open(path) as source:
            image = source.convert("RGB")
            width, height = image.size
            edge = min(width, height)
            crop_edge = min(edge, max(64, int(edge * 0.6)))
            left = random.randint(0, max(0, width - crop_edge))
            top = random.randint(0, max(0, height - crop_edge))
            cropped = image.crop((left, top, left + crop_edge, top + crop_edge))
            cropped = cropped.resize((320, 320), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            cropped.save(buffer, format="PNG")
            return MessageSegment.image(buffer.getvalue())
    except (OSError, ValueError):
        return _guess_image_segment(image_path)


def is_now_playing_guess_music(event: GroupMessageEvent) -> bool:
    group_id = getattr(event, "group_id", None)
    return group_id is not None and str(group_id) in guess.Group


guess_control_permission = SUPERUSER | GROUP_OWNER | GROUP_ADMIN
guess_music_start = on_command("猜歌", permission=guess_control_permission)
guess_music_pic = on_command("猜曲绘", permission=guess_control_permission)
guess_music_solve = on_message(rule=is_now_playing_guess_music)
guess_music_reset = on_command("重置猜歌", permission=guess_control_permission)
guess_music_enable = on_command("开启mai猜歌", permission=guess_control_permission)
guess_music_disable = on_command("关闭mai猜歌", permission=guess_control_permission)


@guess_music_start.handle()
async def _(event: GroupMessageEvent):
    gid = str(event.group_id)
    if not guess.is_enabled(gid):
        await guess_music_start.finish("本群已关闭猜歌功能，群主或管理员可发送 开启mai猜歌")
    if gid in guess.Group:
        await guess_music_start.finish("本群已有正在进行的猜歌或猜曲绘")
    if not guess.start(gid):
        await guess_music_start.finish("歌曲数据尚未加载完成，请稍后再试")

    game = guess.Group[gid]
    await guess_music_start.send(
        dedent(
            """\
            猜歌开始。输入歌曲 ID、标题或别名即可作答。
            每隔 8 秒给出一个提示，30 秒后公布答案。
            """
        )
    )
    await asyncio.sleep(4)
    for cycle in range(7):
        if not guess.is_enabled(gid) or gid not in guess.Group or game.end:
            break
        if cycle < 6:
            await guess_music_start.send(f"{cycle + 1}/7 {game.options[cycle]}")
            await asyncio.sleep(8)
        else:
            await guess_music_start.send(
                MessageSegment.text("7/7 这首歌的曲绘局部是：\n")
                + _guess_partial_image_segment(game.img)
                + MessageSegment.text("\n30 秒后公布答案")
            )
            for _ in range(30):
                await asyncio.sleep(1)
                if gid not in guess.Group or not guess.is_enabled(gid) or game.end:
                    return
            guess.end(gid)
            await guess_music_start.finish(
                MessageSegment.text("答案是：\n") + await draw_music_info(game.music)
            )


@guess_music_pic.handle()
async def _(event: GroupMessageEvent):
    gid = str(event.group_id)
    if not guess.is_enabled(gid):
        await guess_music_pic.finish("本群已关闭猜歌功能，群主或管理员可发送 开启mai猜歌", reply_message=True)
    if gid in guess.Group:
        await guess_music_pic.finish("本群已有正在进行的猜歌或猜曲绘", reply_message=True)
    if not guess.startpic(gid):
        await guess_music_pic.finish("歌曲数据尚未加载完成，请稍后再试", reply_message=True)

    game = guess.Group[gid]
    await guess_music_pic.send(
        MessageSegment.text("以下裁切图片是哪首歌的曲绘？\n")
        + _guess_partial_image_segment(game.img)
        + MessageSegment.text("\n请在 30 秒内输入答案")
    )
    for _ in range(30):
        await asyncio.sleep(1)
        if gid not in guess.Group or not guess.is_enabled(gid) or game.end:
            return
    guess.end(gid)
    await guess_music_pic.finish(
        MessageSegment.text("答案是：\n") + _guess_image_segment(game.img)
    )


@guess_music_solve.handle()
async def _(event: GroupMessageEvent):
    gid = str(event.group_id)
    game = guess.Group.get(gid)
    if game is None:
        return
    answer = event.get_plaintext().strip().lower()
    if answer in game.answer:
        game.end = True
        guess.end(gid)
        if game.pic:
            result = MessageSegment.text("猜对了，答案是：\n") + _guess_image_segment(game.img)
        else:
            result = MessageSegment.text("猜对了，答案是：\n") + await draw_music_info(game.music)
        await guess_music_solve.finish(result, reply_message=True)


@guess_music_reset.handle()
async def _(event: GroupMessageEvent):
    gid = str(event.group_id)
    if gid in guess.Group:
        guess.end(gid)
        msg = "已重置本群猜歌"
    else:
        msg = "本群当前没有进行中的猜歌"
    await guess_music_reset.finish(msg, reply_message=True)


@guess_music_enable.handle()
@guess_music_disable.handle()
async def _(matcher: Matcher, event: GroupMessageEvent):
    gid = str(event.group_id)
    if type(matcher) is guess_music_enable:
        msg = await guess.on(gid)
    else:
        msg = await guess.off(gid)
    await matcher.finish(msg, reply_message=True)
