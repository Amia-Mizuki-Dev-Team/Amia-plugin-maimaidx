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

    if source == "lxns":
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

