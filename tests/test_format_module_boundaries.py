"""Architectural regression checks for currently isolated format services.

The test intentionally examines imports without importing conversion libraries,
so it can run without FFmpeg or Telegram and without executing user files.
"""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FORMAT_MODULES = {
    "audio": ROOT / "services" / "audio_tools.py",
    "audio_adapter": ROOT / "services" / "audio_module.py",
    "pdf_adapter": ROOT / "services" / "pdf_module.py",
    "pdf_implementation": ROOT / "services" / "pdf_tools.py",
    "image_adapter": ROOT / "services" / "image_module.py",
    "image_implementation": ROOT / "services" / "image_tools.py",
    "image_bundle": ROOT / "services" / "image_bundle.py",
    "archive": ROOT / "services" / "archive_tools.py",
}
FORBIDDEN_PREFIXES = (
    "main", "api", "aiogram", "fastapi", "miniapp",
    "services.bot_access", "services.bot_operations",
    "services.campaign_bridge",
)


class FormatModuleBoundaryTests(unittest.TestCase):
    def test_existing_format_modules_do_not_depend_on_ingress_or_billing(self):
        for name, path in FORMAT_MODULES.items():
            with self.subTest(format=name):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                imported = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imported.extend(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        if node.level:
                            # A relative import must be reviewed as the format
                            # boundary grows; none are needed in these modules.
                            self.fail(f"{path}: relative import requires architecture review")
                        imported.append(node.module or "")
                for module in imported:
                    self.assertFalse(
                        any(module == prefix or module.startswith(prefix + ".")
                            for prefix in FORBIDDEN_PREFIXES),
                        f"{path}: forbidden infrastructure/ingress dependency {module}",
                    )


if __name__ == "__main__":
    unittest.main()
