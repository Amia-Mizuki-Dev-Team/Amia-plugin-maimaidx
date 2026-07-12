"""Stable require-based imports for cross-plugin dependencies."""

from nonebot import require

core = require("amia_core")
maimai_sync = require("maimai_sync")
qbind = require("qbind")

_REQUIRED_SYNC_API = (
    "initialize_databases", "get_user_bind_async", "save_user_bind",
    "send_message", "build_message_with_mention", "build_markdown_segment",
)
_missing = [name for name in _REQUIRED_SYNC_API if not hasattr(maimai_sync, name)]
if _missing:
    raise RuntimeError("maimai_sync 缺少公共 API: " + ", ".join(_missing))

initialize_databases = maimai_sync.initialize_databases
get_user_bind_async = maimai_sync.get_user_bind_async
save_user_bind = maimai_sync.save_user_bind
send_message = maimai_sync.send_message
build_message_with_mention = maimai_sync.build_message_with_mention
build_markdown_segment = maimai_sync.build_markdown_segment
get_real_qq = qbind.get_real_qq
