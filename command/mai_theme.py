from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.params import CommandArg

from ..dependencies import get_real_qq
from ..libraries.maimaidx_api_data import is_official_bot
from ..libraries.theme import ThemeService


theme_service = ThemeService()
theme = on_command("mai主题", aliases={"mai主题列表", "切换mai主题"})


@theme.handle()
async def _(event: MessageEvent, message=CommandArg()):
    raw = message.extract_plain_text().strip()
    resolved = get_real_qq(str(event.user_id))
    if not (resolved and str(resolved).isdigit()):
        if is_official_bot(event.self_id):
            await theme.finish("当前身份尚未绑定，无法保存主题。请先完成 qbind 绑定。", reply_message=True)
        resolved = str(event.user_id)
    user_id = int(resolved)
    if not raw or raw in {"列表", "list"}:
        current = theme_service.get(user_id)
        options = "、".join(f"{item.theme_id}（{item.display_name}）" for item in theme_service.list_themes())
        await theme.finish(f"当前主题：{current.theme_id}\n可用主题：{options}\n发送「切换mai主题 <主题ID>」进行切换。", reply_message=True)
    theme_id = raw.split()[0].lower()
    try:
        selected = theme_service.set(user_id, theme_id)
    except ValueError:
        await theme.finish("主题不存在。可用主题：default、mizuki。", reply_message=True)
    await theme.finish(f"已切换主题：{selected.display_name}（{selected.theme_id}）。", reply_message=True)
