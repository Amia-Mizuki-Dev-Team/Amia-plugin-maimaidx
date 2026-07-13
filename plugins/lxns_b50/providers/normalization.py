from __future__ import annotations


def normalize_chart_type(raw: object) -> str | None:
    """Translate supported upstream chart labels to the Core contract."""
    value = str(raw).strip().lower()
    if value in {"sd", "standard"}:
        return "standard"
    if value in {"dx", "deluxe"}:
        return "dx"
    if value == "utage":
        return None
    raise ValueError(f"unsupported chart type: {raw!r}")


def normalize_song_id(
    raw_song_id: object,
    *,
    source: str,
    chart_type: str,
) -> int | None:
    """Return the canonical LXNS song id, without guessing special charts.

    WaterFish represents ordinary DX charts as the corresponding native song
    id plus 10000.  Core uses the native id for both chart types and keeps the
    distinction in ``chart_type``.  Utage and other special charts are not in
    the Core contract and therefore deliberately return ``None``.
    """
    if chart_type not in {"standard", "dx"}:
        return None
    try:
        value = int(raw_song_id)
    except (TypeError, ValueError):
        return None
    if value <= 0 or value >= 100000:
        return None

    if source == "lxns":
        return value
    if source == "fish":
        if chart_type == "dx" and 10000 < value < 20000:
            return value - 10000
        return value
    return None


def catalog_song_id(raw_song_id: object, chart_type: str) -> int | None:
    """Canonicalize a local catalog item whose source was not persisted."""
    try:
        value = int(raw_song_id)
    except (TypeError, ValueError):
        return None
    source = "fish" if chart_type == "dx" and 10000 < value < 20000 else "lxns"
    return normalize_song_id(value, source=source, chart_type=chart_type)
