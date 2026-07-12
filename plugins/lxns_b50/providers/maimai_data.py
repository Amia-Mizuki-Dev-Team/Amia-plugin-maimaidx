from __future__ import annotations

from nonebot import require
from nonebot.log import logger as log

core = require("amia_core")

from ..config import maiconfig
from ..libraries.maimaidx_api_data import maiApi
from ..libraries.maimaidx_music import mai
from .normalization import catalog_song_id, normalize_chart_type, normalize_song_id


def resolve_qq_id(identity) -> int | None:
    canonical = identity.canonical_user_id
    if canonical is not None:
        value = str(canonical)
        return int(value) if value.isdecimal() else None
    if str(identity.external_key.self_id) in {str(item) for item in maiconfig.official_bot_ids}:
        return None
    raw_user_id = str(identity.external_key.user_id)
    return int(raw_user_id) if raw_user_id.isdecimal() else None


def _value(record: object, *names: str, default=None):
    for name in names:
        if isinstance(record, dict):
            value = record.get(name)
        else:
            value = getattr(record, name, None)
        if value is not None:
            return value
    return default


def find_chart_music(chart):
    """Find and validate a local catalog entry for a canonical Core chart key."""
    if chart.chart_type not in {"standard", "dx"}:
        return None
    for song in mai.total_list:
        song_type = normalize_chart_type(getattr(song, "type", ""))
        if song_type != chart.chart_type:
            continue
        if catalog_song_id(getattr(song, "id", None), song_type) == chart.song_id:
            return song
    return None


def _version(song):
    return getattr(getattr(song, "basic_info", {}), "version", None) if song else None


def _record_to_core(record, *, source: str, query=None):
    chart_type = normalize_chart_type(_value(record, "type", default=""))
    raw_song_id = _value(record, "song_id", "id")
    song_id = normalize_song_id(raw_song_id, source=source, chart_type=chart_type or "")
    if chart_type is None or song_id is None:
        log.warning("Skipping unsupported maimai record source=%s id=%r type=%r", source, raw_song_id, chart_type)
        return None
    try:
        difficulty_index = int(_value(record, "level_index", default=-1))
    except (TypeError, ValueError):
        return None
    chart = core.MaimaiChartKey(song_id, chart_type, difficulty_index)
    music = find_chart_music(chart)
    if music is None:
        log.warning("Skipping unverified maimai chart source=%s id=%r type=%s", source, raw_song_id, chart_type)
        return None
    constant = float(_value(record, "ds", default=0) or 0)
    version = _version(music)
    if query and query.versions and version not in query.versions:
        return None
    if query and query.chart_types and chart_type not in query.chart_types:
        return None
    if query and query.difficulty_indexes and difficulty_index not in query.difficulty_indexes:
        return None
    if query and query.min_constant is not None and constant < query.min_constant:
        return None
    if query and query.max_constant is not None and constant > query.max_constant:
        return None
    return core.MaimaiChartRecord(
        chart=chart,
        title=str(_value(record, "title", "song_name", default=music.title)),
        level=str(_value(record, "level", default="")),
        constant=constant,
        achievement=float(_value(record, "achievements", default=0) or 0),
        rating=int(_value(record, "ra", "dx_rating", default=0) or 0),
        rank=_value(record, "rate"),
        fc=_value(record, "fc"),
        fs=_value(record, "fs"),
    )


class MaimaidxDataProvider:
    async def get_player_summary(self, identity):
        qq = resolve_qq_id(identity)
        if qq is None:
            return None
        player = await maiApi.query_user_b50(qqid=qq)
        if player is None:
            return None
        return core.MaimaiPlayerSummary(
            identity=identity,
            player_name=player.nickname or str(qq),
            rating=int(player.rating or 0),
            additional_rating=int(player.additional_rating or 0),
            plate=player.plate or None,
        )

    async def get_player_best_records(self, identity, query=None):
        """Return B50 only; this is intentionally distinct from full records."""
        qq = resolve_qq_id(identity)
        if qq is None:
            return []
        player = await maiApi.query_user_b50(qqid=qq)
        if player is None or player.charts is None:
            return []
        records = []
        for _chart_type, charts in (("standard", player.charts.sd or []), ("dx", player.charts.dx or [])):
            for record in charts:
                converted = _record_to_core(record, source=_value(record, "source", default="unknown"), query=query)
                if converted is not None:
                    records.append(converted)
        return records

    async def get_player_records(self, identity, query=None):
        """Return complete WaterFish developer records, never a B50 fallback."""
        qq = resolve_qq_id(identity)
        if qq is None:
            return []
        try:
            raw_records = await maiApi.query_user_get_dev(qqid=qq)
        except Exception as exc:
            log.warning("Complete maimai records are unavailable: %r", exc)
            return []
        if isinstance(raw_records, dict):
            raw_records = raw_records.get("records", raw_records.get("data", []))
        if not isinstance(raw_records, list):
            return []
        records = []
        for record in raw_records:
            converted = _record_to_core(record, source="fish", query=query)
            if converted is not None:
                records.append(converted)
        return records

    async def get_music_catalog(self):
        catalog = {}
        for song in mai.total_list:
            chart_type = normalize_chart_type(getattr(song, "type", ""))
            song_id = catalog_song_id(getattr(song, "id", None), chart_type or "")
            if song_id is None:
                continue
            # Native IDs win over waterfish DX-offset aliases deterministically.
            existing = catalog.get(song_id)
            if existing is None or int(getattr(song, "id", 0)) == song_id:
                catalog[song_id] = core.MaimaiSong(
                    song_id=song_id,
                    title=str(song.title),
                    artist=getattr(getattr(song, "basic_info", {}), "artist", None),
                    version=_version(song),
                    category=getattr(getattr(song, "basic_info", {}), "genre", None),
                )
        return [catalog[song_id] for song_id in sorted(catalog)]

    async def get_chart_info(self, chart):
        song = find_chart_music(chart)
        if song is None or chart.difficulty_index < 0 or chart.difficulty_index >= len(song.level):
            return None
        return core.MaimaiChart(
            key=chart,
            title=str(song.title),
            level=str(song.level[chart.difficulty_index]),
            constant=float(song.ds[chart.difficulty_index]),
            version=getattr(getattr(song, "basic_info", {}), "version", None),
        )


def register_provider() -> None:
    global _provider_registered
    if _provider_registered:
        return
    core.register_maimai_provider(core.MAIMAI_DATA_PROVIDER, MaimaidxDataProvider())
    _provider_registered = True


_provider_registered = False
