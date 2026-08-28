from __future__ import annotations

import hashlib
import json
import sys
import unittest
from types import SimpleNamespace
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from libraries.maimaidx_error import MusicNotPlayError, UserNotBindLXNSError  # noqa: E402
from libraries.maimaidx_types import (  # noqa: E402
    lxns_song_target,
    normalize_source,
    source_label,
)
from libraries.score_line import calculate_score_line  # noqa: E402
from libraries.attribution import attribution_text, draw_attribution  # noqa: E402
from libraries.maimaidx_oauth_binding import (  # noqa: E402
    build_oauth_binding,
    is_authorized_oauth_binding,
    normalize_oauth_binding,
)
from release010_import import _sanitize, format_user_error  # noqa: E402


class MaimaiCoreContractTests(unittest.TestCase):
    def test_release010_helper_is_part_of_the_plugin_root(self):
        self.assertTrue(
            (PLUGIN_ROOT / "release010_import.py").is_file(),
            "部署 maimaidx 时不能漏掉顶层 release010_import.py",
        )

    def test_attribution_stays_inside_footer_safe_width(self):
        class RecordingDrawer:
            def __init__(self):
                self.drawn = None

            def get_box(self, _text, size):
                # A deterministic stand-in for a font whose measured width is
                # 40px per point.  It lets the test exercise the shrink loop
                # without depending on a particular font rasterizer.
                return (0, 0, size * 40, size)

            def draw(self, *args):
                self.drawn = args

        drawer = RecordingDrawer()
        draw_attribution(drawer, 1200, 827, "lxns")
        self.assertIsNotNone(drawer.drawn)
        self.assertEqual(drawer.drawn[3], attribution_text("lxns"))
        self.assertLessEqual(drawer.drawn[2] * 40, 840)
        self.assertEqual(drawer.drawn[0], 600)

        narrow = RecordingDrawer()
        draw_attribution(narrow, 1400, 100, "merged", max_width=700)
        self.assertLessEqual(narrow.drawn[2] * 40, 700)

    def test_source_aliases_are_stable(self):
        self.assertEqual(normalize_source("落雪"), "lxns")
        self.assertEqual(normalize_source("水鱼"), "diving-fish")
        self.assertEqual(source_label("diving-fish"), "Diving-Fish")

    def test_expected_errors_have_a_short_chat_variant(self):
        msg = format_user_error(UserNotBindLXNSError(), include_code=False)
        self.assertNotIn("HX-MAI-", msg)
        self.assertIn("绑定", msg)
        self.assertNotIn("HX-MAI-", format_user_error(MusicNotPlayError(), include_code=False))

    def test_oauth_secrets_are_removed_from_json_diagnostics(self):
        text = _sanitize(
            '{"client_secret":"secret-value", "access_token":"bearer-value", '
            '"device_code":"device-value", "Authorization":"Bearer header-value"}'
        )
        for value in ("secret-value", "bearer-value", "device-value", "header-value"):
            self.assertNotIn(value, text)

    def test_oauth_binding_persists_consent_without_tokens(self):
        class FakeOAuth:
            client_id = "public-client"
            scope = "prober.records.read"

            @staticmethod
            def subject_ref(external_id):
                digest = hashlib.sha256(
                    f"public-client:{external_id}".encode("utf-8")
                ).hexdigest()
                return f"ref:{digest}"

        binding = build_oauth_binding(FakeOAuth(), "999999999", now=1_700_000_000)
        self.assertTrue(is_authorized_oauth_binding(binding))
        stored = json.dumps(
            {**binding, "access_token": "must-not-be-stored", "device_code": "nope"}
        )
        normalized = normalize_oauth_binding(stored)
        self.assertIsNotNone(normalized)
        self.assertNotIn("access_token", normalized)
        self.assertNotIn("device_code", normalized)
        self.assertEqual(normalized["subject_ref"], binding["subject_ref"])

        revoked = dict(binding, status="revoked")
        self.assertFalse(is_authorized_oauth_binding(revoked))

    def test_score_line_uses_target_rate_and_break_50(self):
        music = SimpleNamespace(
            title="测试",
            charts=[SimpleNamespace(notes=SimpleNamespace(tap=100, hold=10, slide=20, touch=5, brk=4))],
        )
        result = calculate_score_line(music, 0, 100, ["Basic"])
        self.assertIn("10.25", result)
        self.assertIn("BREAK 50", result)
        self.assertIn("100.5%", calculate_score_line(music, 0, 100.5, ["Basic"]))
        with self.assertRaises(ValueError):
            calculate_score_line(music, 0, 101, ["Basic"])

    def test_lxns_song_id_mapping_keeps_utage_ids(self):
        self.assertEqual(
            lxns_song_target("833", SimpleNamespace(type="SD")),
            (833, "standard"),
        )
        self.assertEqual(
            lxns_song_target("11235", SimpleNamespace(type="DX")),
            (1235, "dx"),
        )
        # Fish's historical music_data labels this entry as DX, but LXNS
        # documents 100018 as an Utage id and it must not be reduced.
        self.assertEqual(
            lxns_song_target("100018", SimpleNamespace(type="DX")),
            (100018, "utage"),
        )


if __name__ == "__main__":
    unittest.main()
