"""resolve_qq_id 身份解析契约测试（无 nonebot 环境可运行）。

maimaidx 包名含连字符无法常规导入，这里用别名命名空间包加载
providers.normalization，并把延迟导入的 ..dependencies 换成桩模块，
以便控制 qbind 查询结果。
"""

from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

_PKG = "maimaidx_under_test"


def _load_normalization():
    pkg = ModuleType(_PKG)
    pkg.__path__ = [str(PLUGIN_ROOT)]
    sys.modules[_PKG] = pkg
    providers = ModuleType(f"{_PKG}.providers")
    providers.__path__ = [str(PLUGIN_ROOT / "providers")]
    sys.modules[f"{_PKG}.providers"] = providers
    deps = ModuleType(f"{_PKG}.dependencies")
    sys.modules[f"{_PKG}.dependencies"] = deps
    mod = importlib.import_module(f"{_PKG}.providers.normalization")
    return mod, deps


class ResolveQqIdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.deps = _load_normalization()

    @classmethod
    def tearDownClass(cls):
        for name in (
            f"{_PKG}.providers.normalization",
            f"{_PKG}.dependencies",
            f"{_PKG}.providers",
            _PKG,
        ):
            sys.modules.pop(name, None)

    def _identity(self, user_id="3429630094", self_id="3889004352", canonical=None):
        return SimpleNamespace(
            canonical_user_id=canonical,
            external_key=SimpleNamespace(self_id=str(self_id), user_id=str(user_id)),
        )

    def test_canonical_decimal_wins(self):
        self.assertEqual(self.mod.resolve_qq_id(self._identity(canonical="9999")), 9999)

    def test_canonical_non_decimal_falls_through_to_qbind(self):
        self.deps.get_real_qq = lambda sid: "3429630094"
        try:
            identity = self._identity(user_id="virt_001", canonical="unbound:x:virt_001")
            self.assertEqual(self.mod.resolve_qq_id(identity), 3429630094)
        finally:
            del self.deps.get_real_qq

    def test_qbind_mapping_beats_raw_user_id(self):
        self.deps.get_real_qq = lambda sid: "88888888" if sid == "virt_001" else None
        try:
            identity = self._identity(user_id="virt_001")
            self.assertEqual(self.mod.resolve_qq_id(identity), 88888888)
        finally:
            del self.deps.get_real_qq

    def test_onebot_real_qq_used_when_unbound(self):
        # 未注册 identity resolver 的 OneBot 用户：user_id 即真实 QQ
        self.deps.get_real_qq = lambda sid: None
        try:
            self.assertEqual(self.mod.resolve_qq_id(self._identity()), 3429630094)
        finally:
            del self.deps.get_real_qq

    def test_qbind_non_decimal_result_falls_to_raw(self):
        self.deps.get_real_qq = lambda sid: "not-a-qq"
        try:
            self.assertEqual(self.mod.resolve_qq_id(self._identity()), 3429630094)
        finally:
            del self.deps.get_real_qq

    def test_unresolvable_identity_returns_none(self):
        self.deps.get_real_qq = lambda sid: None
        try:
            identity = self._identity(user_id="opend_虚拟id_9f3a")
            self.assertIsNone(self.mod.resolve_qq_id(identity))
        finally:
            del self.deps.get_real_qq

    def test_dependencies_import_failure_still_uses_raw(self):
        # 隔离环境（无 maimai_sync/qbind）时延迟导入的查找失败不致命，raw 仍可用
        def _boom(sid):
            raise ImportError("stub: dependencies 不可用")

        self.deps.get_real_qq = _boom
        try:
            self.assertEqual(self.mod.resolve_qq_id(self._identity()), 3429630094)
        finally:
            del self.deps.get_real_qq

    def test_official_bot_self_id_never_blocks_resolution(self):
        # 回归：official_bot_ids 默认含 Gensokyo self_id，不得据此拒绝
        self.deps.get_real_qq = lambda sid: None
        try:
            identity = self._identity(user_id="3429630094", self_id="3889004352")
            self.assertEqual(self.mod.resolve_qq_id(identity), 3429630094)
        finally:
            del self.deps.get_real_qq


if __name__ == "__main__":
    unittest.main()
