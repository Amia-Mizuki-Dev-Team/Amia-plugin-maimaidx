from __future__ import annotations

import ast
import unittest
from pathlib import Path


COMMAND_FILE = Path(__file__).resolve().parents[1] / "command" / "mai_score.py"


class ScoreCommandRegistrationTests(unittest.TestCase):
    """Keep score commands ahead of a stale, separately installed plugin."""

    def test_score_matchers_are_exclusive_and_high_priority(self) -> None:
        tree = ast.parse(COMMAND_FILE.read_text(encoding="utf-8"))
        registrations: dict[str, ast.Call] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            call = node.value
            if (
                not isinstance(target, ast.Name)
                or not isinstance(call, ast.Call)
                or not isinstance(call.func, ast.Name)
                or call.func.id != "on_command"
                or not call.args
                or not isinstance(call.args[0], ast.Constant)
            ):
                continue
            registrations[target.id] = call

        for name in ("best50", "ap50", "minfo", "ginfo", "score"):
            with self.subTest(name=name):
                call = registrations[name]
                keywords = {keyword.arg: keyword.value for keyword in call.keywords}
                self.assertEqual(ast.literal_eval(keywords["priority"]), 0)
                self.assertTrue(ast.literal_eval(keywords["block"]))


if __name__ == "__main__":
    unittest.main()
