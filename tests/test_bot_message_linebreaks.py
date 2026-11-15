"""Regression guard for Telegram bot text formatting."""
import ast
from pathlib import Path
import unittest


MAIN = Path(__file__).resolve().parents[1] / "main.py"


class BotMessageLineBreakTests(unittest.TestCase):
    def test_user_facing_strings_do_not_contain_literal_backslash_n(self):
        tree = ast.parse(MAIN.read_text(encoding="utf-8"))
        offenders = [
            (node.lineno, node.value[:80])
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "\\n" in node.value
        ]
        self.assertEqual([], offenders, "Use actual newlines in bot messages")

    def test_home_message_contains_real_line_breaks(self):
        tree = ast.parse(MAIN.read_text(encoding="utf-8"))
        home = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "home_text")
        returned = next(node.value for node in home.body if isinstance(node, ast.Return))
        value = ast.literal_eval(returned)
        self.assertIn("FileShape\n", value)
        self.assertIn("\n\n", value)
        self.assertNotIn("\\n", value)


if __name__ == "__main__":
    unittest.main()
