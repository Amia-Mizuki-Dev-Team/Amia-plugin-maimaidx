"""Diving-Fish server-side record filtering command."""

from __future__ import annotations

import math

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent
from nonebot.params import CommandArg

from ..dependencies import get_real_qq
from ..libraries.diving_fish_filters import (
    FilterParseError,
    ParsedFilters,
    extract_response_records,
    echoed_keys,
    parse_filters,
    record_matches,
)
from ..libraries.maimaidx_api_data import maiApi
from ..libraries.maimaidx_error import OAuthConsentRequiredError, MaimaiRequestError
from ..libraries.maimaidx_player_score import DrawScore
from ..libraries.image import image_to_base64, tricolor_gradient
from ..release010_import import send_error_with_diagnostic


waterfish_filter = on_command("水鱼筛选", aliases={"mai筛选", "df筛选"})


FILTER_HELP = (
    "水鱼筛选用法：水鱼筛选 key=value [key=value ...] [page=页码]\n"
    "示例：水鱼筛选 level_index=3 ds=13.5.. fc=fc,fcp,ap,app\n"
    "支持：song_id/id/music_id、level_index/difficulty、ds、bpm、"
    "achievements、dxScore/dx_score、ra、title、artist、genre、charter、"
    "version、release_date、type、level、level_label、rate、fc、fs、is_new、plate。\n"
    "数值支持 13.5..、..14、13.5..14；多个值用逗号分隔；带空格的文字请加引号。"
)


def _external_id(event: MessageEvent) -> str | None:
    raw = str(event.user_id)
    real = get_real_qq(raw)
    if real:
        return str(real)
    return None


def _subject(external_id: str) -> str:
    if external_id.isdecimal():
        return maiApi.oauth_subject(qqid=int(external_id))
    return maiApi.oauth.subject_ref(external_id)


def _sort_key(record: dict) -> tuple[float, float, int, int]:
    def number(*names: str, default: float = 0.0) -> float:
        for name in names:
            value = record.get(name)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass
        return default

    return (
        -number("ds"),
        -number("achievements"),
        int(number("song_id", "id", "music_id")),
        int(number("level_index", "difficulty")),
    )


def _render(records: list[dict], parsed: ParsedFilters):
    models = []
    for item in records:
        try:
            models.append(maiApi._play_info_default(item))
        except Exception:
            continue
    if not models:
        return None
    page_total = max(1, math.ceil(len(models) / 80))
    if parsed.page > page_total:
        raise FilterParseError(f"页码超出了范围，目前只有 {page_total} 页。")
    shown = models[(parsed.page - 1) * 80 : parsed.page * 80]
    rows = max(1, math.ceil(len(shown) / 20))
    height = 150 + rows * (109 * 4 + 140)
    image = tricolor_gradient(1400, height)
    drawer = DrawScore(image, source="diving-fish")
    rendered = drawer.draw_scorelist(
        parsed.display(), models, parsed.page, page_total
    )
    return rendered, len(models)


@waterfish_filter.handle()
async def _(bot: Bot, event: MessageEvent, message: Message = CommandArg()):
    text = message.extract_plain_text().strip()
    if text in {"", "帮助", "help", "h"}:
        await waterfish_filter.finish(FILTER_HELP, reply_message=True)
    external_id = _external_id(event)
    if not external_id:
        await waterfish_filter.finish(
            "我还没把你的平台身份绑定到真实 QQ，先完成 qbind 绑定后再查询水鱼成绩。",
            reply_message=True,
        )
    try:
        parsed = parse_filters(text)
        raw_payload = await maiApi.query_player_records(
            _subject(external_id), filters=parsed.query_params()
        )
        raw_records, echoed = extract_response_records(raw_payload)
        if echoed_keys(echoed) < parsed.keys:
            from ..libraries.maimaidx_error import MaimaiDataFormatError

            raise MaimaiDataFormatError()
        filtered = [record for record in raw_records if record_matches(record, parsed.values)]
        filtered.sort(key=_sort_key)
        rendered = _render(filtered, parsed)
        if rendered is None:
            await waterfish_filter.finish(
                f"没有找到符合条件的成绩（{parsed.display()}）。", reply_message=True
            )
        image, total = rendered
        # DrawScore already includes the source-aware full attribution and the
        # page/total footer.  The message contains exactly one image segment.
        from nonebot.adapters.onebot.v11 import MessageSegment

        await waterfish_filter.finish(
            MessageSegment.image(image_to_base64(image)), reply_message=True
        )
    except OAuthConsentRequiredError:
        await waterfish_filter.finish(
            "水鱼完整成绩需要 OAuth 授权，请发送「绑定水鱼」。",
            reply_message=True,
        )
    except FilterParseError as exc:
        await waterfish_filter.finish(str(exc), reply_message=True)
    except MaimaiRequestError as exc:
        await waterfish_filter.finish(
            f"{exc.hx_reason}\n{exc.hx_suggestion}", reply_message=True
        )
    except Exception as exc:
        await send_error_with_diagnostic(
            waterfish_filter, exc, "MAI", context="水鱼筛选"
        )
