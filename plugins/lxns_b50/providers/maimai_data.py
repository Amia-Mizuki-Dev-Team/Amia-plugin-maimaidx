from __future__ import annotations

from datetime import datetime, timezone

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


def _field(value: object, *names: str):
    if value is None:
        return None
    for name in names:
        result = value.get(name) if isinstance(value, dict) else getattr(value, name, None)
        if result is not None:
            return result
    return None


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


def _optional_text(value: object) -> str | None:
    value = str(value or "").strip()
    return value or None


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _required_float(value: object, *, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid maimai record {field}: {value!r}") from exc


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _required_int(value: object, *, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid maimai record {field}: {value!r}") from exc


def _updated_at(value: object) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdecimal()):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.isoformat()
    return None


def _notes_total(song, difficulty_index: int) -> int | None:
    charts = getattr(song, "charts", ()) or ()
    if difficulty_index >= len(charts):
        return None
    notes = getattr(charts[difficulty_index], "notes", None)
    if notes is None:
        return None
    try:
        return sum(int(value) for value in notes)
    except (TypeError, ValueError):
        return None


def record_matches_query(record, query) -> bool:
    if query is None:
        return True
    if query.min_constant is not None and record.constant < query.min_constant:
        return False
    if query.max_constant is not None and record.constant > query.max_constant:
        return False
    if query.chart_types and record.chart.chart_type not in query.chart_types:
        return False
    if query.difficulty_indexes and record.chart.difficulty_index not in query.difficulty_indexes:
        return False
    return True


def _version(song):
    if song is None:
        return None
    basic_info = _field(song, "basic_info")
    return _optional_text(_field(basic_info, "from", "version") or _field(song, "version"))


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
    if not 0 <= difficulty_index <= 4:
        raise ValueError(f"invalid maimai difficulty_index for song {raw_song_id!r}: {difficulty_index}")
    chart = core.MaimaiChartKey(song_id, chart_type, difficulty_index)
    music = find_chart_music(chart)
    if music is None:
        log.warning("Skipping unverified maimai chart source=%s id=%r type=%s", source, raw_song_id, chart_type)
        return None
    constant = _float_or_none(_value(record, "ds"))
    if constant is None and difficulty_index < len(getattr(music, "ds", ()) or ()):
        constant = _float_or_none(music.ds[difficulty_index])
    if constant is None:
        log.warning("Skipping maimai record without a chart constant id=%r", raw_song_id)
        return None
    version = _version(music)
    if query and query.versions and version not in query.versions:
        return None
    converted = core.MaimaiChartRecord(
        chart=chart,
        title=str(_value(record, "title", "song_name", default=music.title) or music.title),
        level=str(_value(record, "level", default="")),
        constant=constant,
        achievement=_required_float(_value(record, "achievements"), field="achievements"),
        rating=_required_int(_value(record, "ra", "dx_rating"), field="rating"),
        rank=_optional_text(_value(record, "rate")),
        fc=_optional_text(_value(record, "fc")),
        fs=_optional_text(_value(record, "fs")),
        play_count=_int_or_none(_value(record, "play_count", "times")),
        updated_at=_updated_at(_value(record, "updated_at", "timestamp", "time")),
    )
    return converted if record_matches_query(converted, query) else None


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
        player_name=_optional_text(_field(player, "nickname")),
        rating=_required_int(_field(player, "rating"), field="player rating"),
        additional_rating=_int_or_none(_field(player, "additional_rating")),
        plate=_optional_text(_field(player, "plate")),
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
        for source, charts in (("lxns", player.charts.sd or []), ("lxns", player.charts.dx or [])):
            for record in charts:
                converted = _record_to_core(record, source=source, query=query)
                if converted is not None:
                    records.append(converted)
        return records

    async def get_player_records(self, identity, query=None):
        """Return complete WaterFish developer records, never a B50 fallback."""
        if (
            query is not None
            and query.min_constant is not None
            and query.max_constant is not None
            and query.min_constant > query.max_constant
        ):
            raise ValueError("min_constant must not be greater than max_constant")
        qq = resolve_qq_id(identity)
        if qq is None:
            return []
        raw_records = await maiApi.query_user_get_dev(qqid=qq)
        if raw_records is None:
            return []
        if isinstance(raw_records, dict):
            if "records" in raw_records:
                raw_records = raw_records["records"]
            elif "data" in raw_records:
                raw_records = raw_records["data"]
            else:
                raise TypeError("WaterFish records response does not contain 'records' or 'data'")
        if not isinstance(raw_records, list):
            raise TypeError("WaterFish records response must be a list")
        records = {}
        for record in raw_records:
            converted = _record_to_core(record, source="fish", query=query)
            if converted is not None:
                existing = records.get(converted.chart)
                if existing is None or (converted.achievement, converted.rating) > (
                    existing.achievement,
                    existing.rating,
                ):
                    records[converted.chart] = converted
        return sorted(records.values(), key=lambda record: (
            record.chart.song_id, record.chart.chart_type, record.chart.difficulty_index,
        ))

    async def get_music_catalog(self):
        catalog = {}
        for song in mai.total_list:
            chart_type = normalize_chart_type(getattr(song, "type", ""))
            song_id = catalog_song_id(getattr(song, "id", None), chart_type or "")
            if song_id is None:
                continue
            title = _optional_text(_field(song, "title"))
            if title is None:
                log.warning("Skipping maimai catalog entry without a title id=%r", song_id)
                continue
            # Native IDs win over waterfish DX-offset aliases deterministically.
            existing = catalog.get(song_id)
            if existing is not None and existing.title != title:
                log.warning("Conflicting maimai catalog titles for canonical id=%s", song_id)
            if existing is None or int(getattr(song, "id", 0)) == song_id:
                catalog[song_id] = core.MaimaiSong(
                    song_id=song_id,
                    title=title,
                    artist=_optional_text(_field(_field(song, "basic_info"), "artist")),
                    version=_version(song),
                    category=_optional_text(_field(_field(song, "basic_info"), "genre", "category")),
                    bpm=_float_or_none(_field(_field(song, "basic_info"), "bpm")),
                )
        return [catalog[song_id] for song_id in sorted(catalog)]

    async def get_chart_info(self, chart):
        song = find_chart_music(chart)
        levels = _field(song, "level") or ()
        constants = _field(song, "ds") or ()
        index = chart.difficulty_index
        if song is None or index < 0 or index >= len(levels) or index >= len(constants):
            return None
        constant = _float_or_none(constants[index])
        if constant is None:
            raise ValueError(f"invalid chart constant for {chart!r}")
        return core.MaimaiChart(
            key=chart,
            title=str(song.title),
            level=str(levels[index]),
            constant=constant,
            version=_version(song),
            notes=_notes_total(song, index),
        )


def register_provider() -> None:
    global _provider_registered
    if _provider_registered:
        return
    core.register_maimai_provider(core.MAIMAI_DATA_PROVIDER, MaimaidxDataProvider())
    _provider_registered = True


_provider_registered = False
