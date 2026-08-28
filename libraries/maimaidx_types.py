"""Small shared types used by the two supported score providers."""

from collections.abc import Mapping
from typing import Literal

SourceName = Literal["lxns", "diving-fish"]


def normalize_source(value: str | None) -> SourceName:
    """Normalize user/config aliases without silently selecting another API."""
    value = str(value or "lxns").strip().lower().replace("_", "-")
    if value in {"fish", "divingfish", "diving-fish", "waterfish", "water-fish", "水鱼"}:
        return "diving-fish"
    return "lxns"


def source_label(source: SourceName) -> str:
    return "Diving-Fish" if source == "diving-fish" else "LXNS"


def lxns_song_target(music_id: str | int, music: object | None) -> tuple[int, str]:
    """Map a merged local song id to the LXNS id and ``song_type`` pair.

    Diving-Fish keeps ordinary DX charts in the ``10000 + native_id``
    namespace, while LXNS uses the native id together with ``song_type=dx``.
    Utage is different: its ids are already LXNS ids (for example 100018),
    and must not be reduced by 10000.  Some historical Fish payloads label
    these entries as ``DX``, so the id range is authoritative for Utage.
    """
    remote_id = int(music_id)
    if isinstance(music, Mapping):
        raw_type_value = music.get("type", "")
    else:
        raw_type_value = getattr(music, "type", "")
    raw_type = str(raw_type_value or "").strip().lower()
    if remote_id >= 100000:
        return remote_id, "utage"
    if raw_type in {"dx", "deluxe"}:
        return (remote_id - 10000 if remote_id >= 10000 else remote_id), "dx"
    if raw_type in {"utage", "宴会场", "宴会場"}:
        return remote_id, "utage"
    return remote_id, "standard"
