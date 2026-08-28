"""Validated client-side representation of Diving-Fish record filters."""

from __future__ import annotations

from dataclasses import dataclass
import re
import shlex
from typing import Any, Iterable, Mapping


DivingFishFilterValue = str | list[str]
DivingFishFilters = Mapping[str, DivingFishFilterValue]


class FilterParseError(ValueError):
    """An expected user input error in the ``水鱼筛选`` command."""


ALIASES = {
    "id": "song_id",
    "music_id": "song_id",
    "difficulty": "level_index",
    "dx_score": "dxScore",
    "dxscore": "dxScore",
}

INTEGER_FIELDS = {"song_id", "level_index", "bpm", "dxScore", "ra"}
FLOAT_FIELDS = {"ds", "achievements"}
NUMERIC_FIELDS = INTEGER_FIELDS | FLOAT_FIELDS
BOOLEAN_FIELDS = {"is_new"}
STRING_FIELDS = {
    "title",
    "artist",
    "genre",
    "charter",
    "version",
    "release_date",
    "type",
    "level",
    "level_label",
    "rate",
    "fc",
    "fs",
    "plate",
}
ALLOWED_FIELDS = NUMERIC_FIELDS | BOOLEAN_FIELDS | STRING_FIELDS
_RANGE_RE = re.compile(r"^(?P<left>.*)\.\.(?P<right>.*)$")


def canonical_key(key: str) -> str:
    key = str(key or "").strip()
    lowered = key.lower()
    return ALIASES.get(lowered, key if key in ALLOWED_FIELDS else lowered)


def _number(value: str, *, integer: bool = False) -> float | int:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise FilterParseError(f"筛选条件「{value}」不是有效数字。") from exc
    if integer and not parsed.is_integer():
        raise FilterParseError(f"筛选条件「{value}」需要填写整数。")
    return int(parsed) if integer else parsed


def validate_numeric(value: str, *, integer: bool = False) -> str:
    match = _RANGE_RE.fullmatch(value)
    if match:
        if not match.group("left") and not match.group("right"):
            raise FilterParseError("范围筛选至少要填写一个边界。")
        if match.group("left"):
            _number(match.group("left"), integer=integer)
        if match.group("right"):
            _number(match.group("right"), integer=integer)
        if match.group("left") and match.group("right"):
            left = float(match.group("left"))
            right = float(match.group("right"))
            if left > right:
                raise FilterParseError("范围筛选的左边界不能大于右边界。")
        return value
    _number(value, integer=integer)
    return value


def _values(raw: str, key: str) -> list[str]:
    if raw == "" and key == "fc":
        return [""]
    values = [part.strip() for part in raw.split(",")]
    if any(not value for value in values):
        raise FilterParseError(f"筛选条件「{key}」包含空值，请检查逗号。")
    return values


@dataclass(frozen=True)
class ParsedFilters:
    values: dict[str, list[str] | bool]
    page: int = 1

    @property
    def keys(self) -> set[str]:
        return set(self.values)

    def query_params(self) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        for key, value in self.values.items():
            if isinstance(value, bool):
                result.append((key, "true" if value else "false"))
            else:
                for item in value:
                    result.append((key, item))
        return result

    def display(self, limit: int = 180) -> str:
        parts = []
        for key, value in self.values.items():
            if isinstance(value, bool):
                rendered = "true" if value else "false"
            else:
                rendered = ",".join(value)
            parts.append(f"{key}={rendered}")
        text = " ".join(parts) or "全部成绩"
        return text if len(text) <= limit else text[: limit - 1] + "…"


def parse_filters(text: str, *, max_terms: int = 12, max_length: int = 512) -> ParsedFilters:
    text = str(text or "").strip()
    if len(text) > max_length:
        raise FilterParseError(f"筛选条件太长了，最多支持 {max_length} 个字符。")
    if not text:
        raise FilterParseError("请至少填写一个筛选条件，例如 ds=13.5..。")
    try:
        tokens = shlex.split(text, posix=True)
    except ValueError as exc:
        raise FilterParseError("筛选条件的引号没有闭合。") from exc
    values: dict[str, list[str] | bool] = {}
    page = 1
    terms = 0
    for token in tokens:
        if "=" not in token:
            raise FilterParseError(f"筛选条件「{token}」需要写成 key=value。")
        key_raw, raw = token.split("=", 1)
        key = canonical_key(key_raw)
        if key == "page":
            if not raw.isdecimal() or int(raw) < 1:
                raise FilterParseError("page 必须是大于等于 1 的整数。")
            page = int(raw)
            continue
        if key not in ALLOWED_FIELDS:
            raise FilterParseError(f"不支持筛选字段「{key_raw}」，请输入「水鱼筛选 帮助」。")
        terms += 1
        if terms > max_terms:
            raise FilterParseError(f"一次最多填写 {max_terms} 个筛选条件。")
        if key in BOOLEAN_FIELDS:
            lowered = raw.casefold()
            if lowered not in {"true", "false", "1", "0", "是", "否"}:
                raise FilterParseError(f"筛选条件「{key}」只能填写 true 或 false。")
            value: list[str] | bool = lowered in {"true", "1", "是"}
        else:
            parts = _values(raw, key)
            if key in NUMERIC_FIELDS:
                for part in parts:
                    validate_numeric(part, integer=key in INTEGER_FIELDS)
            value = parts
        if key in BOOLEAN_FIELDS:
            if key in values and values[key] != value:
                raise FilterParseError(f"筛选条件「{key}」重复且取值不同。")
            values[key] = value
        else:
            existing = values.setdefault(key, [])
            if not isinstance(existing, list):
                raise FilterParseError(f"筛选条件「{key}」重复且格式不一致。")
            existing.extend(value)
    if not values:
        raise FilterParseError("请至少填写一个筛选条件，例如 ds=13.5..。")
    return ParsedFilters(values, page)


def _record_value(record: Any, key: str) -> Any:
    aliases = {
        "song_id": ("song_id", "id", "music_id"),
        "dxScore": ("dxScore", "dx_score"),
    }
    names = aliases.get(key, (key,))
    for name in names:
        value = record.get(name) if isinstance(record, Mapping) else getattr(record, name, None)
        if value is not None:
            return value
    return None


def _matches_range(actual: Any, expected: str) -> bool:
    if actual is None:
        return True
    try:
        number = float(actual)
    except (TypeError, ValueError):
        return False
    match = _RANGE_RE.fullmatch(expected)
    if not match:
        return number == float(expected)
    if match.group("left") and number < float(match.group("left")):
        return False
    if match.group("right") and number > float(match.group("right")):
        return False
    return True


def record_matches(record: Any, filters: Mapping[str, list[str] | bool]) -> bool:
    """Post-filter fields present in a response; missing metadata is trusted
    only after the server's ``filters`` echo has validated the request."""
    for key, expected in filters.items():
        actual = _record_value(record, key)
        if actual is None:
            continue
        if isinstance(expected, bool):
            if isinstance(actual, str):
                actual_bool = actual.strip().casefold() in {"true", "1", "yes", "是"}
            else:
                actual_bool = bool(actual)
            if actual_bool != expected:
                return False
        elif key in NUMERIC_FIELDS:
            if not any(_matches_range(actual, item) for item in expected):
                return False
        else:
            actual_text = str(actual).casefold()
            if not any(actual_text == item.casefold() for item in expected):
                return False
    return True


def extract_response_records(payload: Any) -> tuple[list[dict], Mapping[str, Any] | None]:
    echoed = getattr(payload, "filters", None)
    if isinstance(payload, list):
        rows = []
        for item in payload:
            if isinstance(item, dict):
                rows.append(item)
            elif hasattr(item, "model_dump"):
                dumped = item.model_dump()
                if isinstance(dumped, dict):
                    rows.append(dumped)
        return rows, echoed if isinstance(echoed, Mapping) else None
    if not isinstance(payload, Mapping):
        raise FilterParseError("水鱼返回的成绩格式无法识别。")
    records = payload.get("records", payload.get("data"))
    if isinstance(records, Mapping):
        records = list(records.values())
    if not isinstance(records, list):
        raise FilterParseError("水鱼返回的成绩格式无法识别。")
    return [item for item in records if isinstance(item, dict)], payload.get("filters")


def echoed_keys(echo: Mapping[str, Any] | None) -> set[str]:
    if not isinstance(echo, Mapping):
        return set()
    return {canonical_key(str(key)) for key in echo}
