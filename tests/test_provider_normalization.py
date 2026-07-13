from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROVIDER_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "lxns_b50" / "providers"
sys.path.insert(0, str(PROVIDER_ROOT))

from normalization import catalog_song_id, normalize_chart_type, normalize_song_id


class ProviderNormalizationTests(unittest.TestCase):
    def test_chart_type_normalization(self):
        self.assertEqual(normalize_chart_type("SD"), "standard")
        self.assertEqual(normalize_chart_type("standard"), "standard")
        self.assertEqual(normalize_chart_type("DX"), "dx")
        self.assertEqual(normalize_chart_type("deluxe"), "dx")
        self.assertIsNone(normalize_chart_type("utage"))
        with self.assertRaises(ValueError):
            normalize_chart_type("unknown")

    def test_lxns_and_fish_identify_the_same_dx_chart(self):
        self.assertEqual(normalize_song_id(8, source="lxns", chart_type="dx"), 8)
        self.assertEqual(normalize_song_id(10008, source="fish", chart_type="dx"), 8)

    def test_fish_standard_and_special_ids_are_not_guessed(self):
        self.assertEqual(normalize_song_id(8, source="fish", chart_type="standard"), 8)
        self.assertIsNone(normalize_song_id(110114, source="fish", chart_type="dx"))
        self.assertIsNone(normalize_song_id(8, source="unknown", chart_type="dx"))

    def test_catalog_offsets_and_unknown_chart_type(self):
        self.assertEqual(catalog_song_id(10008, "dx"), 8)
        self.assertEqual(catalog_song_id(8, "standard"), 8)
        self.assertIsNone(catalog_song_id(8, "utage"))


if __name__ == "__main__":
    unittest.main()
