"""多环境 dotenv 分层注入测试（无 nonebot 环境可运行）。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from libraries.env_layering import _REGISTRY_KEY, load_env_layers  # noqa: E402


class EnvLayeringTests(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._env_backup = dict(os.environ)
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        os.environ.pop("ENVIRONMENT", None)
        os.environ.pop(_REGISTRY_KEY, None)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()
        os.environ.clear()
        os.environ.update(self._env_backup)

    def _write(self, name: str, content: str) -> None:
        (Path(self._tmp.name) / name).write_text(content, encoding="utf-8")

    def test_spec_overrides_base(self):
        self._write(".env", "A=base\nB=base\nENVIRONMENT=dev\n")
        self._write(".env.dev", "A=spec\nC=specdev\n")
        env = load_env_layers()
        self.assertEqual(env, "dev")
        self.assertEqual(os.environ["A"], "spec")
        self.assertEqual(os.environ["B"], "base")
        self.assertEqual(os.environ["C"], "specdev")
        self.assertEqual(os.environ["ENVIRONMENT"], "dev")

    def test_real_env_var_wins(self):
        os.environ["A"] = "real"
        self._write(".env", "A=file\n")
        self._write(".env.prod", "A=spec\n")
        load_env_layers()
        self.assertEqual(os.environ["A"], "real")
        # 真实变量不得被登记为协议注入键
        self.assertNotIn("A", json.loads(os.environ[_REGISTRY_KEY]))

    def test_real_environment_selects_prod_spec(self):
        os.environ["ENVIRONMENT"] = "prod"
        self._write(".env", "X=base\nENVIRONMENT=dev\n")
        self._write(".env.dev", "X=devspec\n")
        self._write(".env.prod", "X=prodspec\n")
        env = load_env_layers()
        self.assertEqual(env, "prod")
        self.assertEqual(os.environ["X"], "prodspec")
        # 真实 ENVIRONMENT 优先，.env 里的 dev 不得覆盖它
        self.assertEqual(os.environ["ENVIRONMENT"], "prod")

    def test_case_insensitive_spec_file_lookup(self):
        self._write(".env", "ENVIRONMENT=Prod\nA=base\n")
        self._write(".env.PROD", "A=spec\n")
        env = load_env_layers()
        self.assertEqual(env, "Prod")
        self.assertEqual(os.environ["A"], "spec")

    def test_traversal_guard_blocks_spec(self):
        os.environ["ENVIRONMENT"] = "../evil"
        self._write(".env", "A=base\n")
        env = load_env_layers()
        # 环境名含路径穿越片段时不得参与 spec 文件查找
        self.assertEqual(os.environ["A"], "base")
        self.assertEqual(env, "../evil")

    def test_rerun_upgrades_registered_key(self):
        self._write(".env", "A=base\nENVIRONMENT=dev\n")
        load_env_layers()
        self.assertEqual(os.environ["A"], "base")
        self._write(".env.dev", "A=spec\n")
        load_env_layers()
        self.assertEqual(os.environ["A"], "spec")

    def test_registry_corruption_falls_back_to_injection(self):
        os.environ[_REGISTRY_KEY] = "not-json{{"
        self._write(".env", "A=file\n")
        load_env_layers()
        self.assertEqual(os.environ["A"], "file")

    def test_default_env_is_prod_when_nothing_set(self):
        with mock.patch("libraries.env_layering.find_dotenv", return_value=""):
            env = load_env_layers()
        self.assertEqual(env, "prod")
        self.assertEqual(os.environ["ENVIRONMENT"], "prod")


if __name__ == "__main__":
    unittest.main()
