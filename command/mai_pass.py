import traceback
import httpx
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.params import CommandArg, Depends
from nonebot.exception import FinishedException
from loguru import logger as log

from ..libraries.maimaidx_api_data import maiApi, LXNS_BASE
from ..libraries.maimaidx_pass import DrawPass
from ..libraries.image import image_to_base64
from ..libraries.maimaidx_error import UserNotBindLXNSError, UserNotBindFishError
from ..config import maiconfig, is_official_bot

dxpass = on_command('dxpass', aliases={'dx名片', 'dx信息'})

def get_at_qq(message: MessageEvent) -> int | None:
    for item in message.message:
        if isinstance(item, MessageSegment) and item.type == 'at' and item.data['qq'] != 'all':
            return int(item.data['qq'])
    return None


@dxpass.handle()
async def _(bot: Bot, event: MessageEvent, message: Message = CommandArg(), user_id: int | None = Depends(get_at_qq)):
    qqid = user_id or event.user_id
    args = message.extract_plain_text().strip().split()
    is_official = is_official_bot(bot.self_id)

    # 检测并提取 gold / --gold 参数
    force_gold = False
    if "gold" in args:
        force_gold = True
        args.remove("gold")
    elif "--gold" in args:
        force_gold = True
        args.remove("--gold")

    # 用户可选覆盖参数：dxpass [角色ID] [卡框ID] [底板ID]
    override_chara = args[0] if len(args) >= 1 else None
    override_frame = args[1] if len(args) >= 2 else None
    override_plate = args[2] if len(args) >= 3 else None

    await dxpass.send("🎨 正在拉取玩家查分数据并合成 DXPass 名片，请稍候...")

    try:
        # 1. 从落雪 API 获取玩家完整信息（含装扮）
        nickname = str(qqid)
        rating = 0
        friend_code = None
        api_chara_id = None
        api_frame_id = None
        api_plate_id = None

        if maiconfig.lxnstoken:
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    res = await client.get(
                        f"{LXNS_BASE}/maimai/player/qq/{qqid}",
                        headers=maiApi.headers,
                    )
                    if res.status_code == 200:
                        pdata = res.json().get("data", {})
                        nickname = pdata.get("name", str(qqid))
                        rating = pdata.get("rating", 0)
                        friend_code = pdata.get("friend_code")

                        # 解析当前装扮
                        icon = pdata.get("icon")
                        if icon and icon.get("id"):
                            api_chara_id = str(icon["id"])

                        frame = pdata.get("frame")
                        if frame and frame.get("id"):
                            api_frame_id = str(frame["id"])

                        plate = pdata.get("name_plate")
                        if plate and plate.get("id"):
                            api_plate_id = str(plate["id"])
            except Exception as e:
                log.warning(f"获取落雪玩家信息失败: {e}")

        # 如果落雪没返回 rating，尝试从 B50 接口补充
        if rating == 0:
            try:
                userinfo = await maiApi.query_user_b50(qqid=qqid)
                nickname = userinfo.nickname or nickname
                rating = userinfo.rating or 0
            except Exception:
                pass

        # 2. 确定最终使用的装扮 ID（用户覆盖 > API 返回 > 默认）
        final_chara = override_chara or api_chara_id or "000101"
        final_frame = override_frame or api_frame_id or "6"
        final_plate = override_plate or api_plate_id or "000001"

        # 3. 合成名片
        drawer = DrawPass(
            nickname=nickname,
            rating=rating,
            qqid=qqid,
            friend_code=friend_code,
            chara_id=final_chara,
            frame_id=final_frame,
            base_id=final_plate,
            draw_stamps=True if force_gold else None,
        )

        img_res = MessageSegment.image(image_to_base64(drawer.draw()))
        await dxpass.finish(img_res, reply_message=True)

    except FinishedException:
        raise
    except (UserNotBindLXNSError, UserNotBindFishError) as e:
        error_msg = str(UserNotBindLXNSError(is_official)) if isinstance(e, UserNotBindLXNSError) else str(UserNotBindFishError(is_official))
        await dxpass.finish(error_msg, reply_message=True)
    except Exception as e:
        log.error(f"[dxpass] 名片生成失败:\n{traceback.format_exc()}")
        await dxpass.finish(f"⚠️ 生成 DXPass 名片失败，请联系管理员检修。\n错误信息: {type(e).__name__}", reply_message=True)
