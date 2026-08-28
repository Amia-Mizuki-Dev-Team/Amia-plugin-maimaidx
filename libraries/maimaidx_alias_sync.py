"""Public alias-source helpers shared by startup and manual refresh paths."""

from __future__ import annotations

from typing import Any

import httpx


def yuzu_alias_urls(*, proxy: bool = False) -> tuple[str, str]:
    """Return current and legacy public Yuzu alias endpoints."""
    host = "www.yuzuchan.cn" if proxy else "www.yuzuchan.moe"
    return (
        f"https://{host}/api/v2/aliases/maimaidx/aliases",
        f"https://{host}/api/maimaidx/maimaidxalias",
    )


def alias_values(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        alias = str(item).strip()
        key = alias.casefold()
        if alias and key not in seen:
            seen.add(key)
            result.append(alias)
    return result


def normalize_yuzu_alias_payload(payload: Any) -> dict[str, list[str]]:
    """Normalize Yuzu v2/legacy responses to ``song_id -> aliases``.

    Current v2 returns a list of ``song_id``/``alias`` records.  The legacy
    route wraps equivalent records in ``{"content": [...]}``; accepting a
    mapping as well keeps old local mirrors usable without changing the
    command-layer data model.
    """
    rows: Any = payload
    if isinstance(rows, dict):
        for key in ("content", "data", "aliases"):
            if isinstance(rows.get(key), list):
                rows = rows[key]
                break
        else:
            mapping_rows = [
                {"song_id": sid, "alias": aliases}
                for sid, aliases in rows.items()
                if str(sid).strip().isdigit()
            ]
            rows = mapping_rows or [rows]

    if not isinstance(rows, list):
        return {}

    result: dict[str, list[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        song_id = row.get("song_id", row.get("SongID", row.get("id")))
        if song_id is None or not str(song_id).strip().isdigit():
            continue
        aliases = alias_values(
            row.get("alias", row.get("aliases", row.get("Alias", [])))
        )
        if aliases:
            sid = str(song_id).strip()
            result[sid] = alias_values(result.get(sid, []) + aliases)
    return result


async def fetch_yuzu_aliases(
    client: httpx.AsyncClient, *, proxy: bool = False
) -> dict[str, list[str]]:
    """Fetch Yuzu aliases, falling back to the pre-v2 public route."""
    for url in yuzu_alias_urls(proxy=proxy):
        try:
            response = await client.get(url)
            if response.status_code != 200:
                continue
            aliases = normalize_yuzu_alias_payload(response.json())
            if aliases:
                return aliases
        except (httpx.HTTPError, ValueError):
            continue
    return {}
