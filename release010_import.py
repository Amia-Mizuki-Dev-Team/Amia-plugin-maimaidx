"""Release010 error helpers with an optional Amia Core integration.

The maimaidx plugin is independently installable.  Amia Core's
``release010`` module is used when present, but it must never be a plugin-load
requirement: deployed environments may contain the Core plugin without that
optional helper module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module
import os
from pathlib import Path
import re
import traceback
import logging
from typing import Any
from uuid import uuid4


def _load_shared_helpers():
    for module_name in ("amia_core.release010", "src.plugins.amia_core.release010"):
        try:
            return import_module(module_name)
        except ModuleNotFoundError as error:
            if error.name not in {
                "amia_core",
                "amia_core.release010",
                "src",
                "src.plugins",
                "src.plugins.amia_core",
                "src.plugins.amia_core.release010",
            }:
                raise
    return None


_shared_helpers = _load_shared_helpers()
_log = logging.getLogger(__name__)
DEVELOPER_GROUP_ID = "1053964431"
MAX_DIAGNOSTIC_BYTES = 64 * 1024
_SECRET_RE = re.compile(
    r"(?i)(?P<key>\"?(?:authorization|access[_-]?token|device[_-]?code|"
    r"client[_-]?secret|token|cookie|secret|password|api[_-]?key)\"?"
    r"\s*[:=]\s*\"?)(?:bearer\s+)?(?P<value>[^\"'\s,;\}\]]+)",
)


class _FallbackHXCodeError(Exception):
    def __init__(self, code: str, reason: str, suggestion: str, cause: str):
        super().__init__(reason)
        self.hx_code = code
        self.hx_reason = reason
        self.hx_suggestion = suggestion
        self.hx_cause = cause


@dataclass(frozen=True)
class _Failure:
    code: str
    reason: str
    suggestion: str
    cause: str


HXCodeError = getattr(_shared_helpers, "HXCodeError", _FallbackHXCodeError)


def _normalise_code(code: str, source: str) -> str:
    value = str(code or "").strip().upper()
    if not value:
        return f"HX-{source.upper()}-009"
    return value if value.startswith("HX-") else f"HX-{source.upper()}-{value}"


def _is_transport_error(exc: BaseException) -> bool:
    """Recognize adapter/WebSocket send failures without importing an adapter.

    The maimaidx package also runs with Gensokyo and test adapters, so importing
    a concrete OneBot exception here would make the error layer less portable.
    """
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    return (
        "networkerror" in name
        or "websocket" in text
        or "send_msg" in text
        or "call api" in text
    )


def _classify_fallback(exc: BaseException, source: str) -> _Failure:
    code = getattr(exc, "hx_code", "")
    if code:
        return _Failure(
            _normalise_code(code, source),
            str(getattr(exc, "hx_reason", "插件处理失败")),
            str(getattr(exc, "hx_suggestion", "请稍后重试；持续失败时请提交诊断文件")),
            str(getattr(exc, "hx_cause", type(exc).__name__)),
        )
    if _is_transport_error(exc):
        return _Failure(
            _normalise_code("008", source),
            "Bot 消息通道暂时没有回应",
            "请检查 OneBot/Gensokyo 的 WebSocket 连接后再试",
            "适配器 WebSocket 调用 send_msg 未在限定时间内完成或连接已断开",
        )
    if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower():
        return _Failure(
            _normalise_code("003", source),
            "外部数据源响应超时",
            "请稍后重试；持续失败时请提交诊断文件",
            "上游请求未在限定时间内完成",
        )
    if isinstance(exc, FileNotFoundError):
        return _Failure(
            _normalise_code("006", source),
            "本地资源文件不存在",
            "请检查资源包路径和文件权限后重试",
            "读取资源时收到 FileNotFoundError",
        )
    if isinstance(exc, (ValueError, TypeError)):
        return _Failure(
            _normalise_code("007", source),
            "返回数据格式不符合当前版本",
            "请确认数据源与 Release010 兼容；持续失败时提交诊断文件",
            f"解析输入或响应时收到 {type(exc).__name__}",
        )
    return _Failure(
        _normalise_code("009", source),
        "插件内部处理失败",
        "请稍后重试；持续失败时请提交诊断文件",
        f"捕获到未分类异常 {type(exc).__name__}",
    )


def _format_fallback(exc: BaseException, source: str = "MAI") -> str:
    failure = _classify_fallback(exc, source)
    return (
        "处理失败\n\n"
        f"错误码：{failure.code}\n"
        f"原因：{failure.reason}\n"
        f"建议：{failure.suggestion}\n"
        f"错误码分析：{failure.code} 表示 {failure.cause}\n\n"
        "诊断日志已附上，请移交给开发者处理。\n"
        f"如需进一步协助，请加入开发群：{DEVELOPER_GROUP_ID}"
    )


def format_user_error(exc: BaseException, source: str = "MAI", *, include_code: bool = True) -> str:
    """Return the short chat-facing message owned by maimaidx.

    The shared Amia Core helper remains useful for other plugins, but its
    diagnostic-oriented paragraph is too verbose for an expected user input
    error.  Keep the HX code only for failures that need administrator action.
    """
    failure = _classify_fallback(exc, source)
    if getattr(exc, "user_expected", False) and not include_code:
        return f"{failure.reason}\n{failure.suggestion}"
    return f"{failure.reason}（{failure.code}）\n{failure.suggestion}"


def _sanitize(value: str) -> str:
    text = _SECRET_RE.sub(lambda match: f"{match.group('key')}<redacted>", str(value))
    encoded = text.encode("utf-8", "replace")
    if len(encoded) > MAX_DIAGNOSTIC_BYTES:
        text = encoded[:MAX_DIAGNOSTIC_BYTES].decode("utf-8", "ignore")
    return text


def _write_fallback_diagnostic(
    exc: BaseException,
    source: str,
    *,
    context: str = "",
    log_text: str = "",
    directory: str | Path | None = None,
) -> Path:
    failure = _classify_fallback(exc, source)
    root = Path(directory or os.getenv("AMIA_DIAGNOSTIC_DIR", "data/diagnostics"))
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = root / f"{failure.code.lower()}-{stamp}-{uuid4().hex[:8]}.log"
    raw = "\n".join(
        (
            "Amia Release010 diagnostic",
            f"time_utc={stamp}",
            f"error_code={failure.code}",
            f"source={source}",
            f"context={context}",
            f"exception={type(exc).__name__}: {exc}",
            "traceback:",
            "".join(traceback.format_exception(exc)),
            "correlated_log:",
            log_text,
        )
    )
    path.write_text(_sanitize(raw), encoding="utf-8", newline="\n")
    return path


def _write_diagnostic(
    exc: BaseException,
    source: str,
    *,
    context: str = "",
    log_text: str = "",
    directory: str | Path | None = None,
) -> Path:
    """Prefer Amia Core's stronger identity/query-secret scrubber."""
    if _shared_helpers is not None and hasattr(_shared_helpers, "write_diagnostic"):
        path = _shared_helpers.write_diagnostic(
            exc,
            source,
            context=context,
            log_text=log_text,
            directory=directory,
        )
        # Core intentionally keeps a generic classifier for all plugins.  A
        # maimaidx adapter/WebSocket failure has a more useful local code;
        # keep Core's sanitisation, then align the diagnostic header and name.
        failure = _classify_fallback(exc, source)
        try:
            # Amia Core predates the OAuth migration and does not know about
            # ``device_code``.  Run the local scrubber after the shared helper
            # so every OAuth secret/token field is removed regardless of which
            # diagnostic writer was selected.
            content = path.read_text(encoding="utf-8")
            sanitized = _sanitize(content)
            if sanitized != content:
                path.write_text(sanitized, encoding="utf-8", newline="\n")
                content = sanitized
            if _is_transport_error(exc) and failure.code != "HX-MAI-009":
                content = re.sub(
                    r"(?m)^error_code=[^\r\n]*$",
                    f"error_code={failure.code}",
                    content,
                    count=1,
                )
                parts = path.name.split("-", 3)
                suffix = parts[3] if len(parts) == 4 else path.name
                target = path.with_name(f"{failure.code.lower()}-{suffix}")
                if target != path:
                    target.write_text(content, encoding="utf-8", newline="\n")
                    path.unlink()
                    return target
                path.write_text(content, encoding="utf-8", newline="\n")
        except (OSError, UnicodeError):
            _log.warning("could not sanitize or align diagnostic file %s", path)
        return path
    return _write_fallback_diagnostic(
        exc, source, context=context, log_text=log_text, directory=directory
    )


async def _send_fallback(
    matcher: Any,
    exc: BaseException,
    source: str,
    *,
    context: str = "",
    log_text: str = "",
    directory: str | Path | None = None,
) -> Path:
    path = _write_fallback_diagnostic(
        exc,
        source,
        context=context,
        log_text=log_text,
        directory=directory,
    )
    if not await _safe_send(matcher, format_user_error(exc, source)):
        return path
    try:
        from nonebot.adapters.onebot.v11 import MessageSegment

        if not await _safe_send(
            matcher,
            MessageSegment("file", {"file": path.resolve().as_uri(), "file_name": path.name}),
        ):
            return path
    except Exception:  # noqa: BLE001 - upload failure must not hide the error code
        _log.exception("maimaidx fallback diagnostic file could not be prepared")
    try:
        await matcher.finish()
    except Exception as error:  # noqa: BLE001 - do not report through a dead channel
        if not _is_transport_error(error):
            raise
        _log.warning("maimaidx fallback matcher finish could not be sent: %s", type(error).__name__)
    return path


async def _safe_send(matcher: Any, message: Any, **kwargs: Any) -> bool:
    """Send an error message once; never create a second send-timeout failure."""
    try:
        await matcher.send(message, **kwargs)
        return True
    except Exception as error:  # noqa: BLE001 - adapter failures are best effort
        if _is_transport_error(error):
            _log.warning("maimaidx error response could not be sent: %s", type(error).__name__)
            return False
        raise


async def send_error_with_diagnostic(
    matcher: Any,
    exc: BaseException,
    source: str,
    *,
    context: str = "",
    log_text: str = "",
    directory: str | Path | None = None,
) -> Path:
    # Expected input/permission states never create a diagnostic file and do
    # not expose an internal HX code in chat.
    if getattr(exc, "user_expected", False):
        try:
            await matcher.finish(format_user_error(exc, source, include_code=False), reply_message=True)
        except Exception as error:  # noqa: BLE001 - the channel may already be down
            if not _is_transport_error(error):
                raise
            _log.warning("expected maimaidx error response could not be sent: %s", type(error).__name__)
        return Path()

    path = _write_diagnostic(
        exc, source, context=context, log_text=log_text, directory=directory
    )
    failure = _classify_fallback(exc, source)
    if not await _safe_send(matcher, format_user_error(exc, source)):
        return path
    # Timeouts and upstream outages keep the log on disk for operators, but a
    # chat user should only see the short error number.  Resource/data/internal
    # failures include the sanitized file to make recovery actionable.
    if failure.code not in {"HX-MAI-003", "HX-MAI-004", "HX-MAI-008"}:
        try:
            if _shared_helpers is not None and hasattr(_shared_helpers, "build_file_segment"):
                segment = _shared_helpers.build_file_segment(path)
            else:
                from nonebot.adapters.onebot.v11 import MessageSegment
                segment = MessageSegment("file", {"file": path.resolve().as_uri(), "file_name": path.name})
            if not await _safe_send(matcher, segment):
                return path
        except Exception:  # noqa: BLE001 - upload failure must not hide the code
            _log.exception("maimaidx diagnostic file could not be sent")
    try:
        await matcher.finish()
    except Exception as error:  # noqa: BLE001 - do not report an error through a dead channel
        if not _is_transport_error(error):
            raise
        _log.warning("maimaidx matcher finish could not be sent: %s", type(error).__name__)
    return path
