"""User-facing Diving-Fish OAuth status commands.

OAuth 绑定由 sync 插件的「绑定水鱼」命令完成，maimaidx 仅读取绑定状态并
通过自身的 DivingFishOAuth 换票验证授权有效性。
"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent

from ..dependencies import (
    build_markdown_segment,
    get_real_qq,
)
from ..libraries.maimaidx_api_data import is_official_bot, maiApi
from ..libraries.maimaidx_error import (
    OAuthConsentRequiredError,
)
from ..release010_import import send_error_with_diagnostic


waterfish_authorize_status = on_command(
    "水鱼授权状态", aliases={"水鱼OAuth状态", "df授权状态"}
)


def _external_id(event: MessageEvent) -> str | None:
    raw = str(event.user_id)
    real = get_real_qq(raw)
    if real:
        return str(real)
    # OAuth identity must use the qbind-resolved QQ, even when an adapter
    # happens to expose a numeric-looking virtual user id.
    return None


def _markdown_enabled(bot: Bot | None = None) -> bool:
    """Use Markdown only where the adapter is configured to understand it."""
    return is_official_bot(getattr(bot, "self_id", None))


def _status_message(content: str, *, bot: Bot | None = None):
    """Render short OAuth status text consistently with the auth prompt."""
    if not _markdown_enabled(bot):
        return content
    return Message(
        build_markdown_segment(
            f"### 水鱼 OAuth\n\n{content}",
            [
                [
                    {
                        "id": "waterfish_bind_hint",
                        "render_data.label": "如何绑定？",
                        "render_data.style": 1,
                        "action.type": 2,
                        "action.permission.type": 2,
                        "action.data": "绑定水鱼",
                        "action.enter": True,
                    }
                ]
            ],
        )
    )


@waterfish_authorize_status.handle()
async def _(bot: Bot, event: MessageEvent):
    external_id = _external_id(event)
    if not external_id:
        await waterfish_authorize_status.finish(
            "我还没把你的平台身份绑定到真实 QQ，先完成 qbind 绑定后再查询授权状态。",
            reply_message=True,
        )
    qqid = int(external_id) if external_id.isdigit() else None
    if qqid is None:
        await waterfish_authorize_status.finish("无法解析你的真实 QQ，请先完成 qbind 绑定。", reply_message=True)

    from ..libraries.maimaidx_api_data import _get_fish_binding, maiApi
    fish, is_oauth = await _get_fish_binding(qqid)

    if fish is None:
        await waterfish_authorize_status.finish(
            _status_message("你尚未绑定水鱼查分器，请发送「绑定水鱼」完成授权。", bot=bot),
            reply_message=True,
        )
    if not is_oauth:
        await waterfish_authorize_status.finish(
            _status_message(
                "你使用的是旧版绑定（Import-Token），不支持完整成绩查询。\n"
                "请发送「绑定水鱼」重新绑定以启用 OAuth 授权。",
                bot=bot,
            ),
            reply_message=True,
        )

    # OAuth 格式，尝试换票验证
    if not maiApi.oauth_configured:
        await waterfish_authorize_status.finish(
            _status_message("水鱼 OAuth 应用未配置，无法验证授权状态。", bot=bot),
            reply_message=True,
        )
    try:
        await maiApi.oauth.get_access_token(maiApi.oauth_subject(qqid=qqid))
        await waterfish_authorize_status.finish(
            _status_message("水鱼 OAuth 授权有效，可以查询完整成绩。", bot=bot),
            reply_message=True,
        )
    except OAuthConsentRequiredError:
        await waterfish_authorize_status.finish(
            _status_message("水鱼授权已失效，请发送「绑定水鱼」重新绑定。", bot=bot),
            reply_message=True,
        )
    except Exception as exc:
        await send_error_with_diagnostic(waterfish_authorize_status, exc, "MAI", context="水鱼授权状态")
