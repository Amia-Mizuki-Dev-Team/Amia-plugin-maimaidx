from __future__ import annotations

import sys
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "lxns_b50"
LIBRARIES_ROOT = PLUGIN_ROOT / "libraries"
for path in (PLUGIN_ROOT, LIBRARIES_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from maimaidx_error import (  # noqa: E402
    TokenNotFoundError,
    UserNotBindLXNSError,
    UserNotFoundError,
)
from release010_import import format_user_error  # noqa: E402


class Release010MaimaiErrorTests(unittest.TestCase):
    def test_errors_have_stable_codes_and_no_raw_exception_text(self):
        self.assertIn("HX-MAI-001", format_user_error(UserNotBindLXNSError(), "MAI"))
        self.assertIn("HX-MAI-002", format_user_error(TokenNotFoundError(), "MAI"))
        self.assertIn("HX-MAI-005", format_user_error(UserNotFoundError(), "MAI"))
        self.assertNotIn("<class", format_user_error(UserNotFoundError(), "MAI"))


if __name__ == "__main__":
    unittest.main()
