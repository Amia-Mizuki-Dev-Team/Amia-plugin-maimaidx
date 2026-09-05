"""落雪 / 水鱼双源逐谱面汇总的纯函数集合（无网络 I/O，便于单测）。

汇总规则（同谱面键在两源都有成绩时）：
- ``achievements`` / ``ra`` 取两源最大值；
- ``fc`` / ``fs`` 取两源最优徽章（空串视为无）；
- ``dxScore`` / ``rate`` 取达成率较高那条记录（平手取落雪）；
- ``ds`` / ``level`` 取非零方，冲突时以落雪为准并记录日志；
  ds 冲突时按落雪定数重算 ``ra``，保持 ds/ra 自洽；
- 单源成绩原样保留，仅把 song_id 归一化为原生 id。

B50 分组语义（两源一致）：``sd``/``standard`` 键 = 旧版本乐曲 B35；
``dx`` 键 = 现版本乐曲 B15（按版本划分，非 SD/DX 谱面类型）。
"""

from __future__ import annotations

from typing import Optional

from loguru import logger as log

from .maimaidx_error import (
    MaimaiError,
    MaimaiTimeoutError,
    MusicNotPlayError,
    OAuthConsentRequiredError,
    TokenNotFoundError,
)
from .maimaidx_model import ChartInfo, Data, UserInfo
from .maimaidx_types import SourceName

LABEL_LXNS = "lxns"
LABEL_FISH = "diving-fish"

# FC 等级序：app > ap > fcp > fc > 无（空串视为无）
_FC_RANK = {"": 0, "fc": 1, "fcp": 2, "ap": 3, "app": 4}
# FS 等级序：fsdp/fdxp > fsd/fdx > fsp > fs > 无（fsd 与 fdx 同级，图标同为 FSD）
_FS_RANK = {
    "": 0, "fs": 1, "sync": 1, "fsp": 2,
    "fsd": 3, "fdx": 3, "fsdp": 4, "fdxp": 4,
}
# 历史写法别名，归一化后再比较等级
_BADGE_ALIASES = {
    "fc+": "fcp", "ap+": "app",
    "fs+": "fsp", "fsd+": "fsdp", "fdx+": "fdxp",
}


def _badge(value: object) -> str:
    text = str(value or "").strip().lower()
    return _BADGE_ALIASES.get(text, text)


def fc_rank(value: object) -> int:
    return _FC_RANK.get(_badge(value), 0)


def fs_rank(value: object) -> int:
    return _FS_RANK.get(_badge(value), 0)


def better_fc(a: object, b: object) -> str:
    """返回两源中更优的 FC 徽章；等级相同时保留 a（调用方保证 a 为落雪侧）。"""
    badge_a, badge_b = _badge(a), _badge(b)
    return badge_b if fc_rank(badge_b) > fc_rank(badge_a) else badge_a


def better_fs(a: object, b: object) -> str:
    """返回两源中更优的 FS 徽章；等级相同时保留 a（调用方保证 a 为落雪侧）。"""
    badge_a, badge_b = _badge(a), _badge(b)
    return badge_b if fs_rank(badge_b) > fs_rank(badge_a) else badge_a


def chart_type(info: ChartInfo) -> str:
    """把两源的谱面类型写法归一为 standard/dx（utage 原样保留）。"""
    value = str(getattr(info, "type", "") or "").strip().lower()
    if value in {"sd", "standard"}:
        return "standard"
    if value in {"dx", "deluxe"}:
        return "dx"
    return value


def normalized_song_id(info: ChartInfo) -> int:
    """归一化谱面 song_id 为原生 id。

    水鱼与本地曲库把 DX 谱面放在 ``原生 id + 10000`` 命名空间（如 11235），
    落雪用原生 id（如 1235）；宴会场 id ≥ 100000 不做偏移。
    """
    song_id = int(getattr(info, "song_id", 0) or 0)
    if song_id >= 100000:
        return song_id
    if chart_type(info) == "dx" and song_id > 10000:
        return song_id - 10000
    return song_id


def chart_key(info: ChartInfo) -> tuple[int, str, int]:
    """同谱面键 = 归一化 id + 类型 + 难度序号。"""
    return (normalized_song_id(info), chart_type(info), int(info.level_index))


def _merge_scalar(a: object, b: object, field: str, label_a: str, label_b: str):
    """取非零/非空方；两方均有效且冲突时以 a（落雪）为准并记录日志。"""
    if a and b:
        if a != b:
            log.warning(
                f"[双源汇总] {field} 冲突（{label_a}={a}, {label_b}={b}），以 {label_a} 为准"
            )
        return a
    return a if a else b


def _ra_for_merged(a: ChartInfo, b: ChartInfo, merged_ds: float) -> Optional[int]:
    """按合并定数重算 ra；computeRa 不可用时返回 None（保持两源较大值）。

    运行期懒导入 ``maimaidx_best_50.computeRa``：该模块反向依赖本模块的
    ``effective_source``，模块级导入会成环；运行期两侧均已加载完毕，
    函数内导入无环。注意 computeRa 默认参数返回 int。
    """
    try:
        from .maimaidx_best_50 import computeRa
    except Exception as exc:
        # 独立单测环境（无 nonebot driver / 顶层包外）导入失败：退回原值
        log.debug(f"[双源汇总] computeRa 不可用，ra 保持两源较大值: {exc}")
        return None
    merged_achievements = max(float(a.achievements), float(b.achievements))
    return int(computeRa(merged_ds, merged_achievements))


def merge_chart_info(
    a: ChartInfo,
    b: ChartInfo,
    label_a: str = LABEL_LXNS,
    label_b: str = LABEL_FISH,
) -> ChartInfo:
    """合并同键的两条成绩；a/b 依次为优先侧（平手取 a，即落雪）。"""
    primary = a if float(a.achievements) >= float(b.achievements) else b
    merged_ds = _merge_scalar(a.ds, b.ds, "定数", label_a, label_b)
    ra = max(int(a.ra or 0), int(b.ra or 0))
    if a.ds and b.ds and float(a.ds) != float(b.ds):
        # 两源定数漂移时，水鱼 ra 按其自身定数算出，与合并后的落雪定数
        # 不自洽（合并 ra 会大于按合并字段的重算值）；以落雪定数 + 两源
        # 较大达成率重算 ra，保持 ds/ra 一致。两源 ds 一致时维持取 max
        # 的原行为不变。
        recomputed = _ra_for_merged(a, b, float(merged_ds or 0))
        if recomputed is not None:
            log.info(
                f"[双源汇总] 定数冲突（{label_a}={a.ds}, {label_b}={b.ds}），"
                f"以 {label_a} 定数重算 ra: {ra} -> {recomputed}"
            )
            ra = recomputed
    return ChartInfo(
        song_id=normalized_song_id(a),
        title=str(a.title or b.title or ""),
        level_index=int(a.level_index),
        level=str(_merge_scalar(a.level, b.level, "等级", label_a, label_b) or ""),
        achievements=max(float(a.achievements), float(b.achievements)),
        dxScore=int(primary.dxScore or 0),
        rate=str(primary.rate or ""),
        fc=better_fc(a.fc, b.fc),
        fs=better_fs(a.fs, b.fs),
        type=chart_type(a),
        level_label=str(a.level_label or b.level_label or ""),
        ds=float(merged_ds or 0),
        source="merged",
        ra=ra,
    )


def _single(info: ChartInfo) -> ChartInfo:
    """单源成绩原样保留，仅把 song_id 归一化为原生 id。"""
    native = normalized_song_id(info)
    if native == int(info.song_id):
        return info
    return info.model_copy(update={"song_id": native})


def merge_chart_infos(
    a: list[ChartInfo],
    b: list[ChartInfo],
    label_a: str = LABEL_LXNS,
    label_b: str = LABEL_FISH,
) -> list[ChartInfo]:
    """把两条成绩列表按同谱面键逐条汇总，保持 a 侧顺序优先、b 侧新增在后。"""
    a_map: dict[tuple[int, str, int], ChartInfo] = {}
    for info in a or []:
        a_map.setdefault(chart_key(info), info)
    b_map: dict[tuple[int, str, int], ChartInfo] = {}
    for info in b or []:
        b_map.setdefault(chart_key(info), info)

    merged: list[ChartInfo] = []
    for key, info in a_map.items():
        other = b_map.pop(key, None)
        merged.append(
            merge_chart_info(info, other, label_a, label_b) if other else _single(info)
        )
    for info in b_map.values():
        merged.append(_single(info))
    return merged


def merge_b50(
    lxns_user: Optional[UserInfo],
    fish_user: Optional[UserInfo],
) -> "tuple[UserInfo, dict]":
    """合并落雪/水鱼两侧 B50，返回 ``(UserInfo, 数据源元信息)``。

    同谱面出现在两源不同桶（sd=B35 / dx=B15）时，归入达成率较高一方所在桶；
    汇总后按 ra 降序截取 B35/B15。rating = 合并后 B35+B15 单曲 ra 之和，
    合计为 0 时回退 max(两源 rating)。nickname/plate/additional_rating
    优先落雪、回退水鱼。
    """
    if lxns_user is None and fish_user is None:
        raise ValueError("merge_b50 至少需要一个成功的数据源结果")

    def _entry(user: Optional[UserInfo]) -> dict:
        if user is not None:
            return {"ok": True, "error": None, "error_type": None}
        # 上游未提供数据：默认视为“未参与”；失败原因由 API 层补充装饰
        return {"ok": False, "error": None, "error_type": "not_applicable"}

    meta = {
        LABEL_LXNS: _entry(lxns_user),
        LABEL_FISH: _entry(fish_user),
    }

    index: dict[tuple[int, str, int], dict[str, tuple[ChartInfo, str]]] = {}
    for user, label in ((lxns_user, LABEL_LXNS), (fish_user, LABEL_FISH)):
        if user is None:
            continue
        charts = user.charts or Data()
        for bucket, items in (("sd", charts.sd or []), ("dx", charts.dx or [])):
            for info in items:
                index.setdefault(chart_key(info), {})[label] = (info, bucket)

    sd_out: list[ChartInfo] = []
    dx_out: list[ChartInfo] = []
    for sides in index.values():
        lxns_side = sides.get(LABEL_LXNS)
        fish_side = sides.get(LABEL_FISH)
        if lxns_side is not None and fish_side is not None:
            lxns_rec, lxns_bucket = lxns_side
            fish_rec, fish_bucket = fish_side
            merged_record = merge_chart_info(lxns_rec, fish_rec)
            # 平手取落雪所在桶
            bucket = (
                lxns_bucket
                if float(lxns_rec.achievements) >= float(fish_rec.achievements)
                else fish_bucket
            )
        elif lxns_side is not None:
            merged_record, bucket = _single(lxns_side[0]), lxns_side[1]
        else:
            merged_record, bucket = _single(fish_side[0]), fish_side[1]
        (sd_out if bucket == "sd" else dx_out).append(merged_record)

    sd_out.sort(key=lambda c: c.ra, reverse=True)
    dx_out.sort(key=lambda c: c.ra, reverse=True)
    data = Data(sd=sd_out[:35], dx=dx_out[:15])

    rating = sum(c.ra for c in (data.sd or [])) + sum(c.ra for c in (data.dx or []))
    if rating <= 0:
        ratings = [
            int(u.rating)
            for u in (lxns_user, fish_user)
            if u is not None and u.rating is not None
        ]
        rating = max(ratings, default=0)

    def _first_text(*values: Optional[str]) -> str:
        for value in values:
            if value:
                return str(value)
        return ""

    def _first_not_none(*values):
        for value in values:
            if value is not None:
                return value
        return None

    lxns_nickname = lxns_user.nickname if lxns_user is not None else None
    fish_nickname = fish_user.nickname if fish_user is not None else None
    userinfo = UserInfo(
        nickname=_first_text(lxns_nickname, fish_nickname),
        rating=rating,
        additional_rating=_first_not_none(
            lxns_user.additional_rating if lxns_user is not None else None,
            fish_user.additional_rating if fish_user is not None else None,
        ),
        plate=_first_text(
            lxns_user.plate if lxns_user is not None else None,
            fish_user.plate if fish_user is not None else None,
        ),
        username=_first_text(
            lxns_user.username if lxns_user is not None else None,
            fish_user.username if fish_user is not None else None,
        ),
        charts=data,
    )
    return userinfo, meta


def summarize_error(exc: BaseException) -> str:
    """生成用于展示/诊断的数据源失败原因摘要（短句，不含堆栈与敏感信息）。"""
    if isinstance(exc, OAuthConsentRequiredError):
        return "水鱼未授权"
    if isinstance(exc, MaimaiTimeoutError):
        return "上游超时"
    if isinstance(exc, TokenNotFoundError):
        return "凭证未配置"
    if isinstance(exc, MusicNotPlayError):
        return "该源无游玩记录"
    if isinstance(exc, MaimaiError):
        return str(exc)
    return type(exc).__name__


def _meta_entry(meta: dict, label: str) -> dict:
    entry = (meta or {}).get(label)
    return entry if isinstance(entry, dict) else {}


def sources_label(meta: dict) -> str:
    """把数据源元信息渲染为用户可读的汇总标签。"""
    lxns = _meta_entry(meta, LABEL_LXNS)
    fish = _meta_entry(meta, LABEL_FISH)
    lxns_ok, fish_ok = bool(lxns.get("ok")), bool(fish.get("ok"))
    if lxns_ok and fish_ok:
        return "落雪+水鱼汇总"
    if lxns_ok:
        if fish.get("error_type") == "not_applicable":
            return "仅落雪"
        if fish.get("error_type") == "OAuthConsentRequiredError":
            return "仅落雪（水鱼未授权）"
        if fish.get("error_type") == "NoData":
            return "仅落雪（水鱼无成绩数据）"
        error = str(fish.get("error") or "").strip()
        return f"仅落雪（水鱼失败：{error}）" if error else "仅落雪"
    if fish_ok:
        # 源成功但返回空（meta NoData）是「无数据」而非「失败」，文案区分两者
        if lxns.get("error_type") == "NoData":
            return "仅水鱼（落雪无成绩数据）"
        error = str(lxns.get("error") or "").strip()
        return f"仅水鱼（落雪失败：{error}）" if error else "仅水鱼"
    return "双源均不可用"


def effective_source(meta: dict) -> SourceName | str:
    """返回图片署名行使用的数据源标注（merged/单源名）。"""
    lxns_ok = bool(_meta_entry(meta, LABEL_LXNS).get("ok"))
    fish_ok = bool(_meta_entry(meta, LABEL_FISH).get("ok"))
    if lxns_ok and fish_ok:
        return "merged"
    if fish_ok and not lxns_ok:
        return LABEL_FISH
    return LABEL_LXNS


def fish_consent_missing(meta: dict) -> bool:
    """水鱼侧是否因 OAuth 未授权而未参与汇总。"""
    fish = _meta_entry(meta, LABEL_FISH)
    return not fish.get("ok") and fish.get("error_type") == "OAuthConsentRequiredError"
