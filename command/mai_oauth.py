"""User-facing Diving-Fish OAuth device binding commands."""

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
    OAuthConfigurationError,
)
from ..release010_import import send_error_with_diagnostic


waterfish_authorize = on_command("水鱼授权", aliases={"水鱼OAuth", "df授权"})
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


def _status_subject(external_id: str) -> str:
    if external_id.isdecimal():
        return maiApi.oauth_subject(qqid=int(external_id))
    return maiApi.oauth.subject_ref(external_id)


async def _persist_oauth_binding(external_id: str, *, authorized: bool) -> bool:
    """Persist only the shared consent marker, never an OAuth credential.

    ``maimai_sync`` owns the existing shared ``user_binds`` table.  Keeping
    this write here means every bot command uses the same qbind-resolved
    external identity, while the short-lived access token remains in the
    process-local OAuth cache.  A read-back is required for the success path;
    older sync installations that do not know the new field must not be
    reported as shared-ready.
    """

    return await maiApi.remember_oauth_authorization(
        external_id, authorized=authorized
    )


def _markdown_enabled(bot: Bot | None = None) -> bool:
    """Use Markdown only where the adapter is configured to understand it."""

    return is_official_bot(getattr(bot, "self_id", None))


def _authorization_message(device, *, reason: str, bot: Bot | None = None):
    """Build one authorization response with a URL button when supported."""

    expires_minutes = max(1, device.expires_in // 60)
    url = str(device.verification_uri_complete or device.verification_uri)
    plain = (
        f"🔐 水鱼查分器授权绑定\n\n"
        f"📋 请点击下方按钮打开授权链接\n\n"
        f"⏰ 链接有效期 {expires_minutes} 分钟\n"
        f"⚠️ 此链接仅当前用户可用\n\n"
        f"用户码：{device.user_code}"
    )
    if not _markdown_enabled(bot):
        return plain

    content = (
        f"### 🔐 水鱼查分器授权绑定\n\n"
        f"> 📋 请点击下方按钮打开授权链接\n\n"
        f"> ⏰ 链接有效期 {expires_minutes} 分钟\n"
        f"> ⚠️ 此链接仅当前用户可用\n\n"
        f"用户码：`{device.user_code}`"
    )
    buttons = [
        [
            {
                "id": "waterfish_oauth_open",
                "render_data.label": "打开授权链接",
                "render_data.style": 1,
                "action.type": 0,
                "action.permission.type": 2,
                "action.data": url,
            },
            {
                "id": "waterfish_oauth_status",
                "render_data.label": "检查授权状态",
                "render_data.style": 2,
                "action.type": 2,
                "action.permission.type": 2,
                "action.data": "水鱼授权状态",
                "action.enter": True,
            },
        ]
    ]
    return Message(build_markdown_segment(content, buttons))


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
                        "id": "waterfish_oauth_again",
                        "render_data.label": "重新获取授权链接",
                        "render_data.style": 1,
                        "action.type": 2,
                        "action.permission.type": 2,
                        "action.data": "水鱼授权",
                        "action.enter": True,
                    }
                ]
            ],
        )
    )


async def send_authorization_prompt(
    matcher,
    external_id: str,
    *,
    reason: str = "这项查询",
    bot: Bot | None = None,
):
    """Send one self-authorization link for a protected command."""
    try:
        device = await maiApi.request_device_authorization(external_id)
    except Exception as exc:
        await send_error_with_diagnostic(matcher, exc, "MAI", context="水鱼授权提示")
        return
    await matcher.finish(
        _authorization_message(device, reason=reason, bot=bot),
        reply_message=True,
    )


@waterfish_authorize.handle()
async def _(bot: Bot, event: MessageEvent):
    external_id = _external_id(event)
    if not external_id:
        await waterfish_authorize.finish(
            "我还没把你的平台身份绑定到真实 QQ，先完成 qbind 绑定后再发送「水鱼授权」。",
            reply_message=True,
        )
    try:
        device = await maiApi.request_device_authorization(external_id)
    except OAuthConfigurationError as exc:
        await send_error_with_diagnostic(
            waterfish_authorize, exc, "MAI", context="水鱼授权"
        )
        return
    except Exception as exc:
        await send_error_with_diagnostic(
            waterfish_authorize, exc, "MAI", context="水鱼授权"
        )
        return

    await waterfish_authorize.finish(
        _authorization_message(device, reason="水鱼完整成绩查询", bot=bot),
        reply_message=True,
    )


@waterfish_authorize_status.handle()
async def _(bot: Bot, event: MessageEvent):
    external_id = _external_id(event)
    if not external_id:
        await waterfish_authorize_status.finish(
            "我还没把你的平台身份绑定到真实 QQ，先完成 qbind 绑定后再查询授权状态。",
            reply_message=True,
        )
    try:
        await maiApi.oauth.get_access_token(_status_subject(external_id))
    except OAuthConsentRequiredError:
        await _persist_oauth_binding(external_id, authorized=False)
        await waterfish_authorize_status.finish(
            _status_message(
                "你还没有完成水鱼授权，或授权已经失效。请先点击下方按钮重新获取链接。",
                bot=bot,
            ),
            reply_message=True,
        )
    except Exception as exc:
        await send_error_with_diagnostic(
            waterfish_authorize_status, exc, "MAI", context="水鱼授权状态"
        )
        return
    shared = await _persist_oauth_binding(external_id, authorized=True)
    if not shared:
        await waterfish_authorize_status.finish(
            _status_message(
                "水鱼 OAuth 授权有效，可以查询完整成绩。\n"
                "但共享绑定数据库暂时没有写入成功，其他需要共享授权的插件可能看不到这次授权；"
                "请检查数据库连接后重新发送「水鱼授权状态」。",
                bot=bot,
            ),
            reply_message=True,
        )
        return
    await waterfish_authorize_status.finish(
        _status_message("水鱼 OAuth 授权有效，可以查询完整成绩。", bot=bot),
        reply_message=True,
    )
