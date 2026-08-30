"""NoneBot2 多环境 dotenv 分层注入（供 maimaidx / maimai_sync 的配置副本共用）。

分层规则与 NoneBot2 官方一致（docs/appendices/config）：

    真实环境变量 > .env.{ENVIRONMENT}（如 .env.prod / .env.dev）> .env

NoneBot 自身的 .env 只进 driver.config 不进 os.environ；插件里 os.getenv
兜底读取路径需要这里手动对齐同一套规则。

跨插件协作：被注入过的键名登记在保留环境变量 ``_DOTENV_INJECTED_KEYS``
中，后执行的副本可以用更高层级的值升级这些键，同时绝不覆盖进程真实
环境变量。本文件与 Mizuki-plugin-Maimai-sync 的内联副本保持逻辑同步，
修改时两处同改。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from dotenv import find_dotenv, dotenv_values
from loguru import logger as log

_REGISTRY_KEY = "_DOTENV_INJECTED_KEYS"


def _dict_get_ci(mapping: dict, key: str):
    """大小写不敏感读取字典项。"""
    for k, v in mapping.items():
        if k.lower() == key.lower():
            return v
    return None


def _load_registry() -> set:
    raw = os.environ.get(_REGISTRY_KEY, "")
    if not raw:
        return set()
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return set()
    return {str(item) for item in data} if isinstance(data, list) else set()


def _save_registry(registry: set) -> None:
    os.environ[_REGISTRY_KEY] = json.dumps(sorted(registry))


def _find_env_file(directory: Path, env_name: str) -> Optional[Path]:
    """查找 .env.{env_name}；文件名大小写不敏感，拒绝路径穿越。"""
    if not env_name or any(ch in env_name for ch in ("/", "\\", "..")):
        return None
    exact = directory / f".env.{env_name}"
    if exact.is_file():
        return exact
    target = f".env.{env_name}".lower()
    try:
        for entry in directory.iterdir():
            if entry.is_file() and entry.name.lower() == target:
                return entry
    except OSError:
        return None
    return None


def load_env_layers(log_prefix: str = "[dotenv]") -> str:
    """按 NoneBot2 分层规则把 dotenv 注入 os.environ，返回解析出的环境名。

    优先级（高 → 低）：进程真实环境变量 > .env.{ENVIRONMENT} > .env；
    ENVIRONMENT 取自真实环境变量或 .env（大小写不敏感），缺省 prod。
    可重复执行：本协议注入过的键允许被更高层级升级，真实环境变量永远
    不被覆盖。
    """
    found = find_dotenv(usecwd=True)
    base_path = Path(found).resolve() if found else None
    base_vals: dict = {}
    search_dirs = []
    if base_path and base_path.is_file():
        base_vals = {k: v for k, v in dotenv_values(base_path).items() if v is not None}
        search_dirs.append(base_path.parent)
    search_dirs.append(Path.cwd())

    env_name = os.getenv("ENVIRONMENT") or _dict_get_ci(base_vals, "ENVIRONMENT") or "prod"
    env_name = str(env_name).strip() or "prod"

    spec_vals: dict = {}
    spec_file: Optional[Path] = None
    for d in search_dirs:
        spec_path = _find_env_file(d, env_name)
        if spec_path is not None:
            spec_vals = {k: v for k, v in dotenv_values(spec_path).items() if v is not None}
            spec_file = spec_path
            break

    merged = {**base_vals, **spec_vals}
    merged["ENVIRONMENT"] = env_name  # 保持 os.getenv("ENVIRONMENT") 与实际分层一致

    registry = _load_registry()
    added: list = []
    upgraded: list = []
    kept: list = []
    for key, value in merged.items():
        if key not in os.environ:
            os.environ[key] = value
            registry.add(key)
            added.append(key)
        elif key in registry:
            if os.environ[key] != value:
                os.environ[key] = value
                upgraded.append(key)
        else:
            kept.append(key)
    _save_registry(registry)

    base_name = base_path.name if base_path else "无"
    spec_name = spec_file.name if spec_file else "无"
    log.info(
        f"{log_prefix} 运行环境 ENVIRONMENT={env_name} | dotenv 分层: "
        f"{base_name}({len(base_vals)}键) + {spec_name}({len(spec_vals)}键) | "
        f"注入 {len(added)} 升级 {len(upgraded)} 保留 {len(kept)}"
    )
    if kept:
        log.info(
            f"{log_prefix} 以下键保留既有环境变量值（真实变量优先，不覆盖）: "
            f"{', '.join(sorted(kept))}"
        )
    return env_name
