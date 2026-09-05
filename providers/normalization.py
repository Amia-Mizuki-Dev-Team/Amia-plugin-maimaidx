from __future__ import annotations


def normalize_chart_type(raw: object) -> str | None:
    """Translate upstream chart labels to a canonical chart type.

    The shared ``amia-core`` contract currently accepts only ``standard`` and
    ``dx`` records.  We still retain ``utage`` here so API adapters can make
    the correct LXNS id/type request before the provider deliberately skips
    that special chart when converting to the Core model.
    """
    value = str(raw).strip().lower()
    if value in {"sd", "standard"}:
        return "standard"
    if value in {"dx", "deluxe"}:
        return "dx"
    if value in {"utage", "宴会场", "宴会場"}:
        return "utage"
    raise ValueError(f"unsupported chart type: {raw!r}")


def normalize_song_id(
    raw_song_id: object,
    *,
    source: str,
    chart_type: str,
) -> int | None:
    """Return the canonical LXNS song id for an upstream record.

    WaterFish represents ordinary DX charts as the corresponding native song
    id plus 10000.  Core uses the native id for both chart types and keeps the
    distinction in ``chart_type``.  Utage ids are already native LXNS ids and
    remain in the ``100000+`` namespace.  The provider may still reject them
    later because the shared Core model has no Utage chart type.
    """
    if chart_type not in {"standard", "dx", "utage"}:
        return None
    try:
        value = int(raw_song_id)
    except (TypeError, ValueError):
        return None
    if value <= 0 or (chart_type != "utage" and value >= 100000):
        return None

    if chart_type == "utage":
        return value if value >= 100000 else None

    # "merged" records come from the dual-source summary, which already
    # normalizes every song id to the native (LXNS) namespace.
    if source in {"lxns", "merged"}:
        return value
    if source in {"fish", "diving-fish"}:
        if chart_type == "dx" and 10000 < value < 20000:
            return value - 10000
        return value
    return None


def catalog_song_id(raw_song_id: object, chart_type: str) -> int | None:
    """Canonicalize a local catalog item whose source was not persisted."""
    if chart_type not in {"standard", "dx"}:
        return None
    try:
        value = int(raw_song_id)
    except (TypeError, ValueError):
        return None
    source = "fish" if chart_type == "dx" and 10000 < value < 20000 else "lxns"
    return normalize_song_id(value, source=source, chart_type=chart_type)



def resolve_qq_id(identity) -> int | None:
    """Resolve a Core identity into the numeric QQ used by score upstreams.

    优先级：canonical_user_id（amia_core 解析结果）> qbind 绑定映射 >
    external user_id 直接使用。官方机器人平台的 user_id 是虚拟 id，只能
    经 qbind 换取真实 QQ；Gensokyo/OneBot 的 user_id 本身就是真实 QQ。

    注意：official_bot_ids 在本插件中用于 markdown 能力判定，默认值包含
    Gensokyo self_id，绝不能作为身份拒绝依据 —— 否则 Provider 会对所有
    未注册 identity resolver 的 OneBot 用户静默返回空记录（表现为
    「没有找到你的游玩记录」而控制台无任何报错）。
    """
    from loguru import logger as log

    canonical = identity.canonical_user_id
    if canonical is not None and str(canonical).isdecimal():
        return int(canonical)
    raw_user_id = str(identity.external_key.user_id)
    try:
        # 延迟导入：dependencies 会强制加载 maimai_sync/qbind，隔离测试环境下不可用。
        from ..dependencies import get_real_qq
        real_qq = get_real_qq(raw_user_id)
    except Exception:
        real_qq = None
    if real_qq and str(real_qq).isdecimal():
        return int(real_qq)
    if raw_user_id.isdecimal():
        return int(raw_user_id)
    log.warning(
        "[provider] 身份断点: 无法解析真实 QQ，成绩查询将被拒绝 "
        f"(canonical={canonical!r} external_user={raw_user_id!r} "
        f"self_id={identity.external_key.self_id!r})"
    )
    return None
