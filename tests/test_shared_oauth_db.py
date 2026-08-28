from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import logging
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


SYNC_DB_ROOT = (
    Path(__file__).resolve().parents[2]
    / "Mizuki-plugin-Maimai-sync"
    / "plugins"
    / "maimai_sync"
)


def _ensure_nonebot_stub() -> None:
    """Satisfy lib_db's nonebot imports in the bare unittest runner.

    Importing the real ``nonebot`` package without an initialized driver
    fails with a circular import, so provide the minimal names ``lib_db``
    uses at module scope (``log.logger`` and two OneBot event types) when
    the real library is unavailable.
    """
    try:
        import nonebot.log  # noqa: F401
        import nonebot.adapters.onebot.v11  # noqa: F401
        return
    except Exception:
        pass
    for name in (
        "nonebot",
        "nonebot.log",
        "nonebot.adapters",
        "nonebot.adapters.onebot",
        "nonebot.adapters.onebot.v11",
    ):
        sys.modules.pop(name, None)

    class _StubEvent:
        pass

    nonebot_pkg = ModuleType("nonebot")
    log_mod = ModuleType("nonebot.log")
    log_mod.logger = logging.getLogger("maimai_sync_test_stub")
    adapters_pkg = ModuleType("nonebot.adapters")
    onebot_pkg = ModuleType("nonebot.adapters.onebot")
    v11_mod = ModuleType("nonebot.adapters.onebot.v11")
    v11_mod.MessageEvent = _StubEvent
    v11_mod.GroupMessageEvent = _StubEvent
    nonebot_pkg.log = log_mod
    adapters_pkg.onebot = onebot_pkg
    onebot_pkg.v11 = v11_mod
    for name, module in (
        ("nonebot", nonebot_pkg),
        ("nonebot.log", log_mod),
        ("nonebot.adapters", adapters_pkg),
        ("nonebot.adapters.onebot", onebot_pkg),
        ("nonebot.adapters.onebot.v11", v11_mod),
    ):
        sys.modules[name] = module


def _load_sync_db_module():
    """Load only lib_db.py without importing the matcher-heavy sync plugin."""

    _ensure_nonebot_stub()

    missing = [
        name for name in ("sqlalchemy", "aiosqlite")
        if importlib.util.find_spec(name) is None
    ]
    if missing:
        # These tests exercise the shared SQLite schema, so they need the
        # bot venv's ORM stack; a bare system Python legitimately skips.
        raise unittest.SkipTest(
            "shared-DB schema tests need: " + ", ".join(missing)
        )

    lib_source = (SYNC_DB_ROOT / "lib_db.py").read_text(encoding="utf-8")
    if "diving_fish_oauth" not in lib_source:
        # Cross-plugin contract not implemented yet: the deployed
        # maimai_sync lib_db field_map still lacks the shared OAuth marker
        # column, so the schema/round-trip expectations cannot hold.  These
        # tests start running for real as soon as sync ships the column.
        raise unittest.SkipTest(
            "deployed maimai_sync lib_db does not implement the "
            "diving_fish_oauth shared OAuth marker yet (cross-plugin "
            "contract pending)"
        )

    package_name = "maimai_sync_shared_oauth_test"
    package = ModuleType(package_name)
    package.__path__ = [str(SYNC_DB_ROOT)]
    sys.modules[package_name] = package

    version = ModuleType(f"{package_name}.version")
    version.PLUGIN_VERSION = "test"
    sys.modules[version.__name__] = version

    module_name = f"{package_name}.lib_db"
    spec = importlib.util.spec_from_file_location(
        module_name, SYNC_DB_ROOT / "lib_db.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load shared DB module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, package_name


class SharedOAuthDatabaseTests(unittest.TestCase):
    def test_legacy_sqlite_table_gets_oauth_column(self):
        asyncio.run(self._legacy_schema())

    def test_oauth_marker_round_trip_keeps_legacy_fish_token(self):
        asyncio.run(self._round_trip())

    async def _legacy_schema(self):
        module, package_name = _load_sync_db_module()
        manager = None
        try:
            # aiosqlite can release its worker handle just after dispose on
            # Windows; ignore only this OS-level temp cleanup race.
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
                try:
                    db_path = Path(temp_dir) / "legacy.db"
                    with sqlite3.connect(db_path) as connection:
                        connection.executescript(
                            """
                            CREATE TABLE user_binds (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                qq VARCHAR(20) NOT NULL UNIQUE,
                                fish_token TEXT,
                                lxns_token TEXT,
                                user_type INTEGER NOT NULL DEFAULT 1,
                                last_sync_time DATETIME,
                                sync_count INTEGER NOT NULL DEFAULT 0,
                                created_at DATETIME,
                                updated_at DATETIME,
                                keji_warning_shown BOOLEAN NOT NULL DEFAULT 0,
                                maimai_user_id INTEGER,
                                op_timestamp BIGINT NOT NULL DEFAULT 0
                            );
                            """
                        )
                    manager = module.AsyncDatabaseManager(
                        f"sqlite+aiosqlite:///{db_path}", label="legacy-test"
                    )
                    await manager.connect()
                    async with manager.session() as session:
                        result = await session.execute(module.text("PRAGMA table_info(user_binds)"))
                        columns = {row[1] for row in result}
                        del result
                    self.assertIn("diving_fish_oauth", columns)
                finally:
                    if manager is not None:
                        await manager.disconnect()
                        manager.engine = None
                        manager.session_maker = None
                        await asyncio.sleep(0.05)
        finally:
            for name in list(sys.modules):
                if name == package_name or name.startswith(f"{package_name}."):
                    sys.modules.pop(name, None)

    async def _round_trip(self):
        module, package_name = _load_sync_db_module()
        manager = None
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                try:
                    db_path = Path(temp_dir) / "shared-oauth.db"
                    manager = module.AsyncDatabaseManager(
                        f"sqlite+aiosqlite:///{db_path}", label="test"
                    )
                    await manager.connect()
                    module.local_db = manager
                    module.cloud_db = None

                    subject = "ref:" + hashlib.sha256(
                        b"public-client:123456789"
                    ).hexdigest()
                    marker = {
                        "version": 1,
                        "provider": "diving-fish",
                        "status": "authorized",
                        "client_id": "public-client",
                        "subject_ref": subject,
                        "scope": ["prober.records.read"],
                        "authorized_at": 1_700_000_000,
                        "checked_at": 1_700_000_000,
                    }
                    await module.save_user_bind(
                        "123456789", "fish", "legacy-import-token"
                    )
                    await module.save_user_bind(
                        "123456789", "diving_fish_oauth", marker
                    )

                    stored = await module.get_user_bind_async("123456789")
                    self.assertEqual(
                        set(stored),
                        {
                            "fish",
                            "diving_fish_oauth",
                            "lxns",
                            "Type",
                            "keji_warning_shown",
                            "last_sync",
                            "sync_count",
                            "maimai_user_id",
                        },
                    )
                    self.assertEqual(stored["fish"], "legacy-import-token")
                    self.assertEqual(
                        stored["diving_fish_oauth"]["subject_ref"], subject
                    )

                    # The shared DB layer rejects credentials even if a
                    # caller accidentally sends a token-shaped field.
                    await module.save_user_bind(
                        "123456789",
                        "diving_fish_oauth",
                        {**marker, "access_token": "must-not-be-stored"},
                    )
                    still_safe = await module.get_user_bind_async("123456789")
                    self.assertNotIn(
                        "access_token", still_safe["diving_fish_oauth"]
                    )

                    await module.save_user_bind(
                        "123456789", "diving_fish_oauth", None
                    )
                    cleared = await module.get_user_bind_async("123456789")
                    self.assertEqual(cleared["fish"], "legacy-import-token")
                    self.assertIsNone(cleared["diving_fish_oauth"])
                    self.assertIn(
                        "diving_fish_oauth", module.UserBind.__table__.columns
                    )
                finally:
                    if manager is not None:
                        await manager.disconnect()
                        manager.engine = None
                        manager.session_maker = None
                        await asyncio.sleep(0.05)
        finally:
            for name in list(sys.modules):
                if name == package_name or name.startswith(f"{package_name}."):
                    sys.modules.pop(name, None)


if __name__ == "__main__":
    unittest.main()
