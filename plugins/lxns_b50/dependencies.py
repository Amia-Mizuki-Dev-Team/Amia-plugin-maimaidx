"""Stable require-based imports for cross-plugin dependencies.

The sync plugin intentionally exposes a small public API.  Rendering helpers
which are not part of that API stay local to maimaidx.
"""

from nonebot import require
from nonebot.adapters.onebot.v11 import MessageSegment

core = require("amia_core")
maimai_sync = require("maimai_sync")
qbind = require("qbind")

_REQUIRED_SYNC_API = (
    "get_user_bind_async", "save_user_bind", "send_message", "build_message_with_mention",
)
_missing = [name for name in _REQUIRED_SYNC_API if not hasattr(maimai_sync, name)]
if _missing:
    raise RuntimeError("maimai_sync 缺少公共 API: " + ", ".join(_missing))

for _name in _REQUIRED_SYNC_API:
    globals()[_name] = getattr(maimai_sync, _name)

# Keep the developer-provided API available to consumers when the installed
# sync version exports it, without making older compatible versions fail to
# import maimaidx for unused helpers.
for _name in (
    "config", "keychip_manager", "db_manager", "upload_queue", "music_db_cache",
    "PLUGIN_VERSION", "get_error_tracker", "get_user_type_async", "set_user_type",
    "check_disclaimer_agreed", "GameSync", "resolve_crypt_version",
    "get_auth_data_from_qr", "fetch_user_music_data", "perform_triple_logout",
    "is_maintenance_time", "CalcRandom", "BADGE_MAP", "BADGE_REQUIREMENTS",
):
    if hasattr(maimai_sync, _name):
        globals()[_name] = getattr(maimai_sync, _name)


def _normalize_button(button: dict) -> dict:
    result = {}
    for key, value in button.items():
        cursor = result
        parts = key.split(".")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
    return result


def build_markdown_segment(content: str, buttons_config=None) -> MessageSegment:
    """Build Gensokyo Markdown locally; it is not a maimai_sync API."""
    data = {"markdown": {"content": content}}
    if buttons_config:
        rows = []
        for row in buttons_config:
            rows.append({"buttons": [_normalize_button(button) for button in row]})
        data["keyboard"] = {"content": {"rows": rows}}
    return MessageSegment(type="markdown", data={"data": data})


get_real_qq = qbind.get_real_qq
