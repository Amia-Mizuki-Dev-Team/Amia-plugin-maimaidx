import traceback
from typing import Optional, Union
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.params import CommandArg, Depends
from nonebot.exception import FinishedException
from loguru import logger as log

from ..libraries.maimaidx_duel import DrawDuel
from ..libraries.maimaidx_api_data import maiApi
from ..libraries.image import image_to_base64
from ..libraries.maimaidx_error import UserNotFoundError, UserDisabledQueryError

# Command registration
mai_duel = on_command('mai对决', aliases={'战力PK', '战力pk', 'maiPK', 'maipk'})

def get_at_qq(message: MessageEvent) -> Optional[int]:
    """Parse the QQ number of the user who is @mentioned"""
    for item in message.message:
        if isinstance(item, MessageSegment) and item.type == 'at' and item.data['qq'] != 'all':
            return int(item.data['qq'])
    return None

@mai_duel.handle()
async def _(bot: Bot, event: MessageEvent, message: Message = CommandArg(), user_id: Optional[int] = Depends(get_at_qq)):
    qqid1 = event.user_id
    arg = message.extract_plain_text().strip()

    qqid2 = None
    username2 = None

    if user_id:
        qqid2 = user_id
    elif arg:
        if arg.isdigit():
            qqid2 = int(arg)
        else:
            username2 = arg
    else:
        await mai_duel.finish(
            "❌ 请指定对决的对手！可以使用 @群友、输入对手QQ 或 输对手查分器用户名。\n"
            "例如：\n"
            "· mai对决 @群友\n"
            "· mai对决 123456789\n"
            "· mai对决 玩家昵称",
            reply_message=True
        )

    if qqid1 == qqid2:
        await mai_duel.finish("❌ 无法与自己进行战力对决！请指定其他对手。", reply_message=True)

    # 1. Fetch player 1 (sender) info
    try:
        user1 = await maiApi.query_user_b50(qqid=qqid1)
    except (UserNotFoundError, UserDisabledQueryError) as e:
        await mai_duel.finish(f"❌ 获取您的数据失败: {e}\n请确保您已绑定并开启了成绩公开查询。", reply_message=True)
    except Exception as e:
        log.error(f"[mai对决] 获取发送者数据失败: {e}\n{traceback.format_exc()}")
        await mai_duel.finish("❌ 获取您的 B50 数据失败，请稍后再试。", reply_message=True)

    # 2. Fetch player 2 (opponent) info
    try:
        user2 = await maiApi.query_user_b50(qqid=qqid2, username=username2)
    except (UserNotFoundError, UserDisabledQueryError) as e:
        opponent_name = username2 if username2 else (qqid2 or "对方")
        await mai_duel.finish(f"❌ 获取对手「{opponent_name}」数据失败: {e}\n请确保对方已绑定并开启了成绩公开查询。", reply_message=True)
    except Exception as e:
        log.error(f"[mai对决] 获取对手数据失败: {e}\n{traceback.format_exc()}")
        await mai_duel.finish("❌ 获取对手 B50 数据失败，请确认对手的账户正确或稍后再试。", reply_message=True)

    # 3. Draw duel poster
    try:
        await mai_duel.send("⚔️ 正在对比双方 B50 数据并绘制对决海报，请稍候...")
        draw_duel = DrawDuel(user1, user2, qqid1, qqid2 or username2)
        poster_img = await draw_duel.draw()
        await mai_duel.finish(MessageSegment.image(image_to_base64(poster_img)), reply_message=True)
    except FinishedException:
        raise
    except Exception as e:
        log.error(f"[mai对决] 渲染对决大图失败: {e}\n{traceback.format_exc()}")
        await mai_duel.finish("⚠️ 战力对决海报渲染失败，请联系管理员检修服务器配置环境。", reply_message=True)
