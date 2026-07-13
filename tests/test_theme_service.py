from pathlib import Path
import sys

import unittest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

import importlib.util

_THEME_PATH = PLUGIN_ROOT / "plugins" / "lxns_b50" / "libraries" / "theme.py"
_SPEC = importlib.util.spec_from_file_location("maimaidx_theme", _THEME_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules["maimaidx_theme"] = _MODULE
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_MODULE)
ThemeService = _MODULE.ThemeService


class ThemeServiceTests(unittest.TestCase):
    def test_theme_service_persists_canonical_identity(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "themes.json"
            service = ThemeService(path)
            self.assertEqual(service.get(123).theme_id, "default")
            self.assertEqual(service.set(123, "mizuki").theme_id, "mizuki")
            self.assertEqual(ThemeService(path).get(123).theme_id, "mizuki")


    def test_theme_service_rejects_missing_identity(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                ThemeService(Path(directory) / "themes.json").set(None, "mizuki")
