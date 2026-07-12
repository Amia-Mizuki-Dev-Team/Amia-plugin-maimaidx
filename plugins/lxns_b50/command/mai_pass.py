import re
import httpx
import traceback
from typing import Optional
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.params import CommandArg, Depends
from nonebot.exception import FinishedException
from loguru import logger as log

from ..config import maiconfig
from ..libraries.maimaidx_api_data import maiApi, LXNS_BASE, is_official_bot
from ..libraries.image import image_to_base64
from ..libraries.maimaidx_pass import DrawPass, get_chara_id_by_name
from ..dependencies import build_markdown_segment as _build_markdown_segment, get_real_qq

import io
import base64

dxpass = on_command('dxpass', aliases={'dxpass', 'pass', '名片', '金卡'})

def get_at_qq(message: MessageEvent) -> Optional[int]:
    for item in message.message:
        if item.type == 'at' and item.data['qq'] != 'all':
            return int(item.data['qq'])
    return None

@dxpass.handle()
async def _(bot: Bot, event: MessageEvent, message: Message = CommandArg(), user_id: Optional[int] = Depends(get_at_qq)):
    raw_qq = user_id or event.user_id
    real_qq_str = get_real_qq(str(raw_qq))
    qqid = int(real_qq_str) if (real_qq_str and real_qq_str.isdigit()) else raw_qq
    args = message.extract_plain_text().strip()

    nickname = "Maimai Player"
    rating = 0
    friend_code = ""
    chara_id = "000101"
    frame_id = "6"
    base_id = "000001"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(
                f"{LXNS_BASE}/maimai/player/qq/{qqid}",
                headers=maiApi.headers
            )
            if res.status_code == 200:
                pdata = res.json().get("data", {})
                if pdata:
                    nickname = pdata.get("name", nickname)
                    rating = pdata.get("rating", rating)
                    friend_code = pdata.get("friend_code", "")
                    icon = pdata.get("icon", {})
                    frame = pdata.get("frame", {})
                    plate = pdata.get("name_plate", {})
                    if icon.get("id"):
                        chara_id = str(icon["id"])
                    if frame.get("id"):
                        frame_id = str(frame["id"])
                    if plate.get("id"):
                        base_id = str(plate["id"])
    except Exception as e:
        log.error(f"查询落雪异常: {e}")

    watermark = False
    if "-p" in args or "--preview" in args:
        watermark = True
        args = args.replace("--preview", "").replace("-p", "").strip()

    chara_type = "chara"
    type_match = re.search(r'(?:--type|-t)\s+(\w+)', args, re.IGNORECASE)
    if type_match:
        t_val = type_match.group(1).lower()
        if t_val in ["partner", "chara"]:
            chara_type = t_val
        args = re.sub(r'(?:--type|-t)\s+\w+', '', args, flags=re.IGNORECASE).strip()

    parts = [p.strip() for p in args.split() if p.strip()]

    if len(parts) == 0:
        md_text = (
            "### dxpass 名片合成助手\n\n"
            "请选择卡框模板："
        )
        plain_text = (
            "[dxpass 名片合成助手]\n\n"
            "请选择卡框 ID：\n"
            "2 - 蓝色\n"
            "3 - 黄色\n"
            "4 - 红色\n"
            "5 - 紫色\n"
            "6 - 默认"
        )
        if is_official_bot(bot.self_id):
            msg_segment = _build_markdown_segment(md_text, [
                [
                    {"render_data.label": "卡框：默认", "action.data": f"dxpass {chara_id} 6", "action.enter": True},
                    {"render_data.label": "卡框：蓝色", "action.data": f"dxpass {chara_id} 2", "action.enter": True},
                    {"render_data.label": "卡框：黄色", "action.data": f"dxpass {chara_id} 3", "action.enter": True}
                ],
                [
                    {"render_data.label": "卡框：红色", "action.data": f"dxpass {chara_id} 4", "action.enter": True},
                    {"render_data.label": "卡框：紫色", "action.data": f"dxpass {chara_id} 5", "action.enter": True}
                ]
            ])
            await dxpass.finish(Message(msg_segment))
        else:
            await dxpass.finish(plain_text, reply_message=True)

    elif len(parts) == 1:
        val = parts[0]
        mapped_id = get_chara_id_by_name(val)
        selected_chara = mapped_id if mapped_id else (val if val.isdigit() else chara_id)
        md_text = (
            "### dxpass 名片合成助手\n\n"
            "请选择卡框模板："
        )
        plain_text = (
            "[dxpass 名片合成助手]\n\n"
            "请选择卡框 ID：\n"
            "2 - 蓝色\n"
            "3 - 黄色\n"
            "4 - 红色\n"
            "5 - 紫色\n"
            "6 - 默认"
        )
        if is_official_bot(bot.self_id):
            msg_segment = _build_markdown_segment(md_text, [
                [
                    {"render_data.label": "卡框：默认", "action.data": f"dxpass {selected_chara} 6", "action.enter": True},
                    {"render_data.label": "卡框：蓝色", "action.data": f"dxpass {selected_chara} 2", "action.enter": True},
                    {"render_data.label": "卡框：黄色", "action.data": f"dxpass {selected_chara} 3", "action.enter": True}
                ],
                [
                    {"render_data.label": "卡框：红色", "action.data": f"dxpass {selected_chara} 4", "action.enter": True},
                    {"render_data.label": "卡框：紫色", "action.data": f"dxpass {selected_chara} 5", "action.enter": True}
                ]
            ])
            await dxpass.finish(Message(msg_segment))
        else:
            await dxpass.finish(plain_text, reply_message=True)

    elif len(parts) == 2:
        selected_chara = parts[0]
        selected_frame = parts[1]
        md_text = (
            "### dxpass 名片合成助手\n\n"
            "请选择名片背景底图："
        )
        plain_text = (
            "[dxpass 名片合成助手]\n\n"
            "请选择背景 ID：\n"
            "000001 - 白色\n"
            "000002 - 蓝色\n"
            "000003 - 黄色\n"
            "000004 - 红色\n"
            "000005 - 紫色\n"
            "000006 - 黑色\n"
            "100007 - 金色\n"
            "650004 - 炫彩"
        )
        if is_official_bot(bot.self_id):
            msg_segment = _build_markdown_segment(md_text, [
                [
                    {"render_data.label": "背景：白色", "action.data": f"dxpass {selected_chara} {selected_frame} 000001", "action.enter": True},
                    {"render_data.label": "背景：蓝色", "action.data": f"dxpass {selected_chara} {selected_frame} 000002", "action.enter": True},
                    {"render_data.label": "背景：黄色", "action.data": f"dxpass {selected_chara} {selected_frame} 000003", "action.enter": True}
                ],
                [
                    {"render_data.label": "背景：红色", "action.data": f"dxpass {selected_chara} {selected_frame} 000004", "action.enter": True},
                    {"render_data.label": "背景：紫色", "action.data": f"dxpass {selected_chara} {selected_frame} 000005", "action.enter": True},
                    {"render_data.label": "背景：黑色", "action.data": f"dxpass {selected_chara} {selected_frame} 000006", "action.enter": True}
                ],
                [
                    {"render_data.label": "背景：金色", "action.data": f"dxpass {selected_chara} {selected_frame} 100007", "action.enter": True},
                    {"render_data.label": "背景：炫彩", "action.data": f"dxpass {selected_chara} {selected_frame} 650004", "action.enter": True}
                ]
            ])
            await dxpass.finish(Message(msg_segment))
        else:
            await dxpass.finish(plain_text, reply_message=True)

    override_chara = parts[0]
    override_frame = parts[1]
    override_base = parts[2]

    mapped_id = get_chara_id_by_name(override_chara)
    if mapped_id:
        chara_id = mapped_id
    elif override_chara.isdigit():
        chara_id = override_chara
    else:
        await dxpass.finish(f"未找到角色或立绘: 「{override_chara}」", reply_message=True)

    if override_frame.isdigit():
        frame_id = override_frame
    if override_base.isdigit():
        base_id = override_base

    try:
        drawer = DrawPass(
            nickname=nickname,
            rating=rating,
            qqid=qqid,
            friend_code=friend_code,
            chara_id=chara_id,
            frame_id=frame_id,
            base_id=base_id,
            chara_type=chara_type,
            watermark=watermark
        )
        if watermark:
            img = drawer.preview_chara()
        else:
            img = drawer.draw()
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=90)
        b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")
        img_res = MessageSegment.image(f"base64://{b64_str}")
        await dxpass.finish(img_res, reply_message=True)
    except FinishedException:
        raise
    except Exception as e:
        log.error(f"[dxpass] 合成名片遭遇未捕获异常:\n{traceback.format_exc()}")
        await dxpass.finish(f"名片合成失败，原因: {e}", reply_message=True)
