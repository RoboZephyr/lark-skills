from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    REPO_ROOT / "skills" / "progress-report" / "scripts" / "validate_lark_markdown.py"
)
SPEC = importlib.util.spec_from_file_location("validate_lark_markdown", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ValidateLarkMarkdownTest(unittest.TestCase):
    def test_reports_every_ascii_tilde(self) -> None:
        self.assertEqual(MODULE.tilde_locations("a~b\nc~~d\n"), [(1, 2), (2, 2), (2, 3)])

    def test_fix_replaces_tildes_with_safe_range_separator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            markdown_file = Path(directory) / "report.md"
            markdown_file.write_text("[#48](url)~[#55](url)\n", encoding="utf-8")

            with mock.patch(
                "sys.argv", [str(SCRIPT_PATH), "--fix", str(markdown_file)]
            ):
                self.assertEqual(MODULE.main(), 0)

            self.assertEqual(
                markdown_file.read_text(encoding="utf-8"),
                "[#48](url)–[#55](url)\n",
            )


if __name__ == "__main__":
    unittest.main()
