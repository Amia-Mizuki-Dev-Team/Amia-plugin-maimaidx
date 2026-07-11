import io
import re
import traceback
from pathlib import Path
from typing import Optional

import httpx
import qrcode
from loguru import logger as log
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.exception import FinishedException
from nonebot.params import CommandArg, Depends

from ..dependencies import build_markdown_segment as _build_markdown_segment, get_real_qq

from ..libraries.maimaidx_api_data import LXNS_BASE, is_official_bot, maiApi
from ..libraries.maimaidx_pass import DrawPass, get_chara_id_by_name
from ..libraries.tool import render_html_card_to_base64
from ..config import static

dxpass = on_command("dxpass", aliases={"dxpass", "pass", "名片", "金卡"})

_BACKGROUND_PAGE_SIZE = 6
_FRAME_LABELS = {
    "00_Bronze": "青铜外框",
    "00_Gold": "黄金外框",
    "00_Platinum": "白金外框",
    "00_Sliver": "白银外框",
    "01_Gold": "金色外框",
    "02_Freedom": "自由外框",
}
_BACKGROUND_LABELS = {
    "1.00_back": "初代 回忆",
    "1.00_dragon": "初代 龙纹",
    "1.00": "初代 默认",
    "1.00_metropolis": "初代 都市",
    "1.00_start": "初代 启程",
    "1.00_youth": "初代 青春",
    "1.00-1.09_blackrose": "黑蔷薇",
    "1.00-1.09_heaven": "天空",
    "1.09": "1.09 默认",
    "1.09_metropolis2": "1.09 都市",
    "1.09_mikan": "1.09 蜜柑",
    "1.09_start2": "1.09 启程",
    "1.10": "1.10 默认",
    "1.10_heaven3": "1.10 天空",
    "1.10_metropolis3": "1.10 都市",
    "1.10_shuwa": "1.10 汽水",
    "1.10_skystreet": "1.10 天街",
    "1.15": "1.15 默认",
    "1.20-1.25": "1.20 花纹",
    "1.30-1.35": "1.30 花纹",
    "1.40-1.45": "1.40 花纹",
    "1.50-1.55": "1.50 花纹",
    "BG_00": "图案 01",
    "BG_01": "图案 02",
    "BG_02": "图案 03",
    "BG_03": "图案 04",
    "BG_04": "涂鸦暗纹",
    "BG_05": "叶片圆点",
    "BG_06": "图案 07",
    "BG_07": "图案 08",
    "Naqua": "青蓝几何",
    "Nfire": "珊瑚几何",
    "Nleaf": "嫩绿几何",
    "Raqua": "浅蓝几何",
    "Rfire": "粉红几何",
    "Rleaf": "浅绿几何",
}
_FRAME_ORDER = (
    "00_Bronze",
    "00_Sliver",
    "00_Gold",
    "00_Platinum",
    "01_Gold",
    "02_Freedom",
)
_BACKGROUND_ORDER = (
    "Raqua", "Rleaf", "Nleaf", "Rfire", "Naqua", "Nfire",
    "BG_00", "BG_01", "BG_02", "BG_03", "BG_04", "BG_05", "BG_06", "BG_07",
    "1.00", "1.00_back", "1.00_start", "1.00_youth", "1.00_dragon", "1.00_metropolis",
    "1.00-1.09_blackrose", "1.00-1.09_heaven",
    "1.09", "1.09_start2", "1.09_mikan", "1.09_metropolis2",
    "1.10", "1.10_shuwa", "1.10_skystreet", "1.10_heaven3", "1.10_metropolis3",
    "1.15", "1.20-1.25", "1.30-1.35", "1.40-1.45", "1.50-1.55",
)


def get_at_qq(message: MessageEvent) -> Optional[int]:
    for item in message.message:
        if item.type == "at" and item.data["qq"] != "all":
            return int(item.data["qq"])
    return None


def _asset_label(path: Path, prefix: str) -> str:
    name = path.stem
    if name.startswith(prefix):
        name = name[len(prefix):]
    parts = name.split("_")
    if len(parts) > 1 and re.fullmatch(r"[0-9a-fA-F-]{36}", parts[-1]):
        name = "_".join(parts[:-1])
    return name


def _frame_label(path: Path) -> str:
    return _FRAME_LABELS.get(_asset_label(path, "UC_Frame_"), "自定义外框")


def _background_label(path: Path) -> str:
    return _BACKGROUND_LABELS.get(_asset_label(path, "UC_BG_"), "自定义背景")


def _dxpass_frames() -> list[Path]:
    frames = list((static / "dxpass" / "CardFrame").glob("UC_Frame_*.png"))
    priority = {name: index for index, name in enumerate(_FRAME_ORDER)}
    return sorted(frames, key=lambda path: (priority.get(_asset_label(path, "UC_Frame_"), len(priority)), path.name))


def _dxpass_backgrounds() -> list[Path]:
    backgrounds = list((static / "dxpass" / "CardBase").glob("UC_BG_*.png"))
    priority = {name: index for index, name in enumerate(_BACKGROUND_ORDER)}
    return sorted(backgrounds, key=lambda path: (priority.get(_asset_label(path, "UC_BG_"), len(priority)), path.name))


def _button_rows(buttons: list[dict], per_row: int = 3) -> list[list[dict]]:
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def _frame_guide_text() -> tuple[str, str]:
    frames = _dxpass_frames()
    md_text = "### dxpass 名片合成助手\n\n请选择外框："
    if frames:
        plain_items = [f"f{i:02d} - {_frame_label(path)}" for i, path in enumerate(frames, start=1)]
        plain_text = "[dxpass 名片合成助手]\n\n请选择外框：\n" + "\n".join(plain_items)
    else:
        plain_text = "[dxpass 名片合成助手]\n\n未找到 UC_Frame 外框素材，将随机使用默认外框。"
    return md_text, plain_text


def _base_guide_text(page: int = 1) -> tuple[str, str]:
    backgrounds = _dxpass_backgrounds()
    total_pages = max(1, (len(backgrounds) + _BACKGROUND_PAGE_SIZE - 1) // _BACKGROUND_PAGE_SIZE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * _BACKGROUND_PAGE_SIZE
    current = backgrounds[start:start + _BACKGROUND_PAGE_SIZE]
    md_text = f"### dxpass 名片合成助手\n\n请选择正面背景（{page}/{total_pages}）："
    if backgrounds:
        plain_items = [
            f"b{i:02d} - {_background_label(path)}"
            for i, path in enumerate(current, start=start + 1)
        ]
        plain_text = f"[dxpass 名片合成助手]\n\n请选择正面背景（{page}/{total_pages}）：\n" + "\n".join(plain_items)
    else:
        plain_text = "[dxpass 名片合成助手]\n\n未找到 UC_BG 背景素材，将随机使用默认背景。"
    return md_text, plain_text


def _build_frame_picker(bot: Bot, selected_target: str):
    md_text, plain_text = _frame_guide_text()
    if is_official_bot(bot.self_id):
        buttons = [
            {
                "render_data.label": _frame_label(path),
                "action.data": f"dxpass {selected_target} f{i:02d}",
                "action.enter": True,
            }
            for i, path in enumerate(_dxpass_frames(), start=1)
        ]
        return Message(
            _build_markdown_segment(
                md_text,
                _button_rows(buttons) or [[
                    {"render_data.label": "随机外框", "action.data": f"dxpass {selected_target} random", "action.enter": True}
                ]],
            )
        )
    return plain_text


def _build_base_picker(bot: Bot, selected_target: str, selected_frame: str, page: int = 1):
    backgrounds = _dxpass_backgrounds()
    total_pages = max(1, (len(backgrounds) + _BACKGROUND_PAGE_SIZE - 1) // _BACKGROUND_PAGE_SIZE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * _BACKGROUND_PAGE_SIZE
    current = backgrounds[start:start + _BACKGROUND_PAGE_SIZE]
    md_text, plain_text = _base_guide_text(page)
    if is_official_bot(bot.self_id):
        buttons = [
            {
                "render_data.label": _background_label(path),
                "action.data": f"dxpass {selected_target} {selected_frame} b{i:02d}",
                "action.enter": True,
            }
            for i, path in enumerate(current, start=start + 1)
        ]
        navigation = []
        if page > 1:
            navigation.append({"render_data.label": "上一页", "action.data": f"dxpass {selected_target} {selected_frame} p{page - 1}", "action.enter": True})
        navigation.append({"render_data.label": "随机背景", "action.data": f"dxpass {selected_target} {selected_frame} random", "action.enter": True})
        if page < total_pages:
            navigation.append({"render_data.label": "下一页", "action.data": f"dxpass {selected_target} {selected_frame} p{page + 1}", "action.enter": True})
        return Message(
            _build_markdown_segment(
                md_text,
                (_button_rows(buttons) + [navigation]) if buttons else [navigation],
            )
        )
    return plain_text


def _make_qr_data_uri(data: str) -> str:
    qr = qrcode.QRCode(version=1, border=1, box_size=8)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    import base64

    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _looks_like_friend_code(text: str) -> bool:
    return text.isdigit() and len(text) >= 12


@dxpass.handle()
async def _(
    bot: Bot,
    event: MessageEvent,
    message: Message = CommandArg(),
    user_id: Optional[int] = Depends(get_at_qq),
):
    raw_qq = user_id or event.user_id
    real_qq_str = get_real_qq(str(raw_qq))
    qqid = int(real_qq_str) if (real_qq_str and real_qq_str.isdigit()) else raw_qq
    args = message.extract_plain_text().strip()
    raw_parts = [p.strip() for p in args.split() if p.strip()]
    friend_code_arg = raw_parts[0] if raw_parts and _looks_like_friend_code(raw_parts[0]) else ""
    selection_parts = raw_parts[1:] if friend_code_arg else raw_parts

    nickname = "Maimai Player"
    rating = 0
    friend_code = ""
    chara_id = "000101"
    chara_name = ""
    icon_id = ""
    frame_id = "6"
    base_id = "000001"
    plate_id = ""

    try:
        if not maiApi.headers:
            maiApi.load_token_proxy()
        async with httpx.AsyncClient(timeout=15) as client:
            if friend_code_arg:
                res = await client.get(f"{LXNS_BASE}/maimai/player/{friend_code_arg}", headers=maiApi.headers)
            else:
                res = await client.get(f"{LXNS_BASE}/maimai/player/qq/{qqid}", headers=maiApi.headers)
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
                        icon_id = str(icon["id"])
                    if icon.get("name"):
                        chara_name = str(icon["name"])
                    if frame.get("id"):
                        frame_id = str(frame["id"])
                    if plate.get("id"):
                        base_id = str(plate["id"])
                        plate_id = str(plate["id"])
    except Exception as e:
        log.error(f"查询落雪玩家信息异常: {e}")

    watermark = False
    if "-p" in args or "--preview" in args:
        watermark = True
        args = args.replace("--preview", "").replace("-p", "").strip()

    chara_type = "chara"
    type_match = re.search(r"(?:--type|-t)\s+(\w+)", args, re.IGNORECASE)
    if type_match:
        t_val = type_match.group(1).lower()
        if t_val in ["partner", "chara"]:
            chara_type = t_val
        args = re.sub(r"(?:--type|-t)\s+\w+", "", args, flags=re.IGNORECASE).strip()

    parts = [p.strip() for p in args.split() if p.strip()]
    if friend_code_arg:
        parts = selection_parts
        if parts and parts[0].lower() in {"pick", "select", "选择"}:
            parts = parts[1:]
    if friend_code_arg and not parts:
        parts = [chara_id, frame_id, base_id]

    try:
        if len(parts) == 0:
            await dxpass.finish(_build_frame_picker(bot, chara_id), reply_message=True)

        if len(parts) == 1:
            val = parts[0]
            if friend_code_arg and val.lower().startswith("f"):
                await dxpass.finish(_build_base_picker(bot, friend_code_arg, val), reply_message=True)
            mapped_id = get_chara_id_by_name(val)
            selected_chara = mapped_id if mapped_id else (val if val.isdigit() else chara_id)
            await dxpass.finish(_build_frame_picker(bot, selected_chara), reply_message=True)

        if len(parts) == 2:
            if friend_code_arg:
                parts = [chara_id, parts[0], parts[1]]
            else:
                selected_chara = parts[0]
                selected_frame = parts[1]
                await dxpass.finish(_build_base_picker(bot, selected_chara, selected_frame), reply_message=True)

        if len(parts) == 3 and re.fullmatch(r"p\d+", parts[2], re.IGNORECASE):
            target = friend_code_arg or parts[0]
            await dxpass.finish(
                _build_base_picker(bot, target, parts[1], int(parts[2][1:])),
                reply_message=True,
            )

        override_chara = parts[0]
        override_frame = parts[1]
        override_base = parts[2]

        mapped_id = get_chara_id_by_name(override_chara)
        if mapped_id:
            chara_id = mapped_id
        elif override_chara.isdigit():
            chara_id = override_chara
        else:
            await dxpass.finish(f"未找到角色或立绘: {override_chara}", reply_message=True)

        if override_frame.isdigit() or override_frame.lower().startswith("f"):
            frame_id = override_frame
        if override_base.isdigit() or override_base.lower().startswith("b"):
            base_id = override_base

        drawer = DrawPass(
            nickname=nickname,
            rating=rating,
            qqid=qqid,
            friend_code=friend_code,
            chara_id=chara_id,
            frame_id=frame_id,
            base_id=base_id,
            chara_type=chara_type,
            watermark=watermark,
            chara_name=chara_name,
            icon_id=icon_id,
            plate_id=plate_id,
        )

        if watermark:
            img = drawer.preview_chara()
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=90)
            import base64

            img_res = MessageSegment.image(f"base64://{base64.b64encode(buf.getvalue()).decode('utf-8')}")
            await dxpass.finish(img_res, reply_message=True)

        try:
            qr_data_uri = _make_qr_data_uri("https://help.mizuki.top")
            html_doc = drawer.build_usagi_card_html(qr_data_uri)
            img_res = MessageSegment.image(await render_html_card_to_base64(html_doc))
            await dxpass.finish(img_res, reply_message=True)
        except FinishedException:
            # finish() uses this exception to stop the matcher after sending.
            # It is not an HTML rendering failure and must not trigger PIL fallback.
            raise
        except Exception:
            log.exception("[dxpass] HTML 名片渲染失败，回退到 PIL 渲染")
            img = drawer.draw()
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=90)
            import base64

            img_res = MessageSegment.image(f"base64://{base64.b64encode(buf.getvalue()).decode('utf-8')}")
            await dxpass.finish(img_res, reply_message=True)
    except FinishedException:
        raise
    except Exception as e:
        log.error(f"[dxpass] 合成名片遭遇未捕获异常\n{traceback.format_exc()}")
        await dxpass.finish(f"名片合成失败，原因: {e}", reply_message=True)
