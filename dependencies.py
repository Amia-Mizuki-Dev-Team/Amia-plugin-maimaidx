"""Stable require-based imports for cross-plugin dependencies.

The sync plugin intentionally exposes a small public API.  Rendering helpers
which are not part of that API stay local to maimaidx.
"""

import importlib
import json
from pathlib import Path
import sys

from nonebot import require
from nonebot.adapters.onebot.v11 import MessageSegment


class _QbindFileFallback:
    """Read the existing qbind store when its optional plugin is unavailable.

    This is deliberately read-only and does not create a second binding store;
    it only lets isolated maimaidx imports keep resolving identities from the
    same ``qbind/binds.json`` file.
    """

    _path = Path(__file__).resolve().parents[1] / "qbind" / "binds.json"

    @classmethod
    def get_real_qq(cls, session_id: str):
        try:
            binds = json.loads(cls._path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        if not isinstance(binds, dict):
            return None
        key = str(session_id)
        value = binds.get(key)
        if value is not None:
            return str(value)
        values = {str(item) for item in binds.values()}
        return key if key in values else None

try:
    # ``amia_core`` is a library layer, not a NoneBot plugin with its own
    # ``PluginMetadata``.  A normal full-bot load may already expose it via
    # ``require``, while an isolated plugin load has to import the project
    # package directly.  Keep both paths so maimaidx does not fail before its
    # own commands can be registered.
    core = require("amia_core")
except (RuntimeError, ModuleNotFoundError):
    try:
        from src.plugins import amia_core as core
    except ModuleNotFoundError:
        import amia_core as core
def _load_dependency(name: str):
    """Load a companion plugin through NoneBot, with source-tree fallback.

    ``nonebot.load_plugins(<single plugin path>)`` intentionally does not scan
    the sibling qbind/sync directories.  The fallback keeps this plugin
    independently loadable for tests and tooling; a normal bot startup still
    uses the registered companion plugin instance first.
    """
    try:
        return require(name)
    except (RuntimeError, ModuleNotFoundError):
        if name == "maimai_sync":
            sync_root = Path(__file__).resolve().parents[1] / "Mizuki-plugin-Maimai-sync" / "plugins"
            if sync_root.is_dir() and str(sync_root) not in sys.path:
                sys.path.insert(0, str(sync_root))
            return importlib.import_module(name)
        if name == "qbind":
            loaded = sys.modules.get("src.plugins.qbind") or sys.modules.get("qbind")
            if loaded is not None:
                return loaded
            return _QbindFileFallback()
        raise


maimai_sync = _load_dependency("maimai_sync")
qbind = _load_dependency("qbind")

_REQUIRED_SYNC_API = (
    "get_user_bind_async", "save_user_bind", "send_message", "build_message_with_mention",
)
_missing = [name for name in _REQUIRED_SYNC_API if not hasattr(maimai_sync, name)]
if _missing:
    raise RuntimeError("maimai_sync 缺少公共 API: " + ", ".join(_missing))

for _name in _REQUIRED_SYNC_API:
    globals()[_name] = getattr(maimai_sync, _name)

# 对外公共函数映射层：统一经 maimai_manage 门面取用（Manage → sync 桥接），
# 禁止跳过 Manage 直挂其他插件的公共实现。分层结果被 config import 期依赖，
# Manage 不可用时必须显式抛错而非静默降级。
try:
    _manage = require("maimai_manage")
except Exception as exc:
    raise RuntimeError(f"无法加载 maimai_manage（dotenv 分层映射源）: {exc}") from exc
load_env_layers = getattr(_manage, "load_env_layers", None)
if load_env_layers is None:
    raise RuntimeError("maimai_manage 缺少公共 API: load_env_layers")

# Manage facade 的绑定查询函数（运行时使用）。
# Manage 版本过旧没有 get_bind 时为 None，运行时回退 get_user_bind_async。
get_bind = getattr(_manage, "get_bind", None)

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
            normalized = []
            for button in row:
                item = _normalize_button(button)
                render_data = item.setdefault("render_data", {})
                label = render_data.setdefault("label", button.get("label", "按钮"))
                render_data.setdefault("visited_label", label)
                render_data.setdefault("style", 1)

                action = item.setdefault("action", {})
                if "data" in button:
                    action.setdefault("data", button["data"])
                action.setdefault("type", 2)
                permission = action.setdefault("permission", {})
                permission.setdefault("type", 2)
                action.setdefault("data", "")
                action.setdefault("unsupport_tips", "请更新客户端以查看按钮")
                if action["type"] == 2:
                    action.setdefault("reply", False)
                    action.setdefault("enter", False)
                    action.setdefault("anchor", 0)
                elif action["type"] == 0:
                    action["enter"] = True
                    action.pop("reply", None)
                item.setdefault("id", f"btn_{hash(label) & 0xffff}")
                normalized.append(item)
            rows.append({"buttons": normalized})
        data["keyboard"] = {"content": {"rows": rows}}
    return MessageSegment(type="markdown", data={"data": data})


def get_at_user_id(segment: MessageSegment, bot_id: int | str | None = None) -> int | None:
    """Read a native @ segment from legacy OneBot and Gensokyo v008."""

    if segment.type != "at":
        return None
    data = segment.data or {}
    raw = data.get("qq") or data.get("user_id") or data.get("id")
    if raw is None or str(raw).lower() == "all" or (bot_id is not None and str(raw) == str(bot_id)):
        return None
    return int(raw) if str(raw).isdigit() else None


get_real_qq = qbind.get_real_qq
