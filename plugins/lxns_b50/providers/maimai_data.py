from __future__ import annotations

from nonebot import require

core = require("amia_core")

from ..libraries.maimaidx_api_data import maiApi
from ..libraries.maimaidx_music import mai


def normalize_lxns_song_id(raw: object) -> int:
    """Keep LXNS-native IDs intact; chart type distinguishes SD and DX."""
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid LXNS song id: {raw!r}") from exc
    if value < 0:
        raise ValueError(f"invalid LXNS song id: {raw!r}")
    return value


def _qq(identity) -> int | None:
    raw = identity.canonical_user_id or identity.external_key.user_id
    return int(raw) if isinstance(raw, str) and raw.isdecimal() else None


class MaimaidxDataProvider:
    async def get_player_summary(self, identity):
        qq = _qq(identity)
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

    async def get_player_records(self, identity, query=None):
        qq = _qq(identity)
        if qq is None:
            return []
        player = await maiApi.query_user_b50(qqid=qq)
        if player is None or player.charts is None:
            return []
        records = []
        for chart_type, charts in (("standard", player.charts.sd or []), ("dx", player.charts.dx or [])):
            if query and query.chart_types and chart_type not in query.chart_types:
                continue
            for record in charts:
                song_id = normalize_lxns_song_id(record.song_id)
                if query and query.difficulty_indexes and int(record.level_index) not in query.difficulty_indexes:
                    continue
                constant = float(record.ds or 0)
                if query and query.min_constant is not None and constant < query.min_constant:
                    continue
                if query and query.max_constant is not None and constant > query.max_constant:
                    continue
                records.append(core.MaimaiChartRecord(
                    chart=core.MaimaiChartKey(song_id, chart_type, int(record.level_index)),
                    title=record.title,
                    level=record.level,
                    constant=constant,
                    achievement=float(record.achievements),
                    rating=int(record.ra or 0),
                    rank=record.rate or None,
                    fc=record.fc or None,
                    fs=record.fs or None,
                ))
        return records

    async def get_music_catalog(self):
        return [core.MaimaiSong(
            song_id=normalize_lxns_song_id(song.id),
            title=str(song.title),
            artist=getattr(getattr(song, "basic_info", {}), "artist", None),
            version=getattr(getattr(song, "basic_info", {}), "version", None),
            category=getattr(getattr(song, "basic_info", {}), "genre", None),
        ) for song in mai.total_list]

    async def get_chart_info(self, chart):
        song = mai.total_list.by_id(str(chart.song_id))
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
    core.register_maimai_provider(core.MAIMAI_DATA_PROVIDER, MaimaidxDataProvider())
