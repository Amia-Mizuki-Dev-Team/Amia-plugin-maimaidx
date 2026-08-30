"""query_chart（id 指令）正则契约测试。

2026-08-30 生产事故：@Bot 前缀（卡片按钮回发 / 手动 @）使完整消息串带
CQ 段前缀，行首锚定 ^id 永远匹配不上，指令静默无响应。改为 \\b 词边界后
必须兼容带前缀消息，且不误命中 qid/valid 等以 id 结尾的单词。
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

COMMAND_FILE = Path(__file__).resolve().parents[1] / "command" / "mai_search.py"


def _load_query_chart_pattern() -> re.Pattern:
    tree = ast.parse(COMMAND_FILE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "query_chart"
            and isinstance(node.value, ast.Call)
        ):
            pattern = ast.literal_eval(node.value.args[0])
            flags = 0
            for kw in node.value.keywords:
                if kw.arg == "flags":
                    flags = ast.literal_eval(kw.value)
            return re.compile(pattern, flags)
    raise AssertionError("mai_search.py 中未找到 query_chart 的 on_regex 定义")


class QueryChartRegexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pattern = _load_query_chart_pattern()

    def _group(self, text: str) -> str | None:
        m = self.pattern.search(text)
        return m.group(1) if m else None

    def test_plain_command(self):
        self.assertEqual(self._group("id 11630"), "11630")
        self.assertEqual(self._group("id11630"), "11630")

    def test_at_prefix_command(self):
        self.assertEqual(
            self._group("[CQ:at,qq=3889004352] id 11630"), "11630"
        )
        self.assertEqual(self._group("  id 11630"), "11630")
        self.assertEqual(self._group("id 11630 "), "11630")

    def test_no_false_positive_on_words_ending_with_id(self):
        for text in ("qid 11630", "valid 123", "bid 5", "idabc 11630"):
            with self.subTest(text=text):
                self.assertIsNone(self._group(text))


if __name__ == "__main__":
    unittest.main()
