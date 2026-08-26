from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "skills" / "weekly-report" / "scripts" / "init_index.py"
SPEC = importlib.util.spec_from_file_location("weekly_report_init_index", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class WeeklyReportInitIndexTest(unittest.TestCase):
    def test_main_refuses_stay_put_false_before_creating(self) -> None:
        config = """\
lark:
  index_doc: {}
  permissions:
    doc_owner_open_ids: [owner-id]
    bot_open_id: bot-id
    stay_put: false
  doc:
    folder_token: folder-token
"""
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.yaml"
            config_path.write_text(config, encoding="utf-8")
            with (
                mock.patch("sys.argv", [str(SCRIPT_PATH), "--config", str(config_path)]),
                mock.patch.object(MODULE, "create_doc") as create_doc,
            ):
                with self.assertRaisesRegex(SystemExit, "stay_put must be true"):
                    MODULE.main()
            create_doc.assert_not_called()

    def test_create_doc_refuses_drive_root(self) -> None:
        with self.assertRaisesRegex(SystemExit, "refusing to create in Drive root"):
            MODULE.create_doc("<title>test</title>")

    def test_create_doc_passes_parent_token(self) -> None:
        response = {
            "ok": True,
            "data": {
                "document": {
                    "document_id": "doc-token",
                    "url": "https://example.test/docx/doc-token",
                }
            },
        }
        with mock.patch.object(MODULE, "_run_lark", return_value=("", response)) as run:
            token, url = MODULE.create_doc(
                "<title>test</title>", parent_token="folder-token"
            )

        self.assertEqual(token, "doc-token")
        self.assertEqual(url, "https://example.test/docx/doc-token")
        command = run.call_args.args[0]
        self.assertEqual(
            command[command.index("--parent-token") + 1], "folder-token"
        )

    def test_verify_doc_archive_checks_owner_and_folder(self) -> None:
        responses = [
            (
                "",
                {
                    "ok": True,
                    "data": {
                        "metas": [
                            {"doc_token": "doc-token", "owner_id": "owner-id"}
                        ]
                    },
                },
            ),
            (
                "",
                {
                    "ok": True,
                    "data": {"files": [{"token": "doc-token", "type": "docx"}]},
                },
            ),
        ]
        with mock.patch.object(MODULE, "_run_lark", side_effect=responses) as run:
            MODULE.verify_doc_archive("doc-token", "folder-token", "owner-id")

        list_command = run.call_args_list[1].args[0]
        self.assertIn("--page-all", list_command)
        self.assertEqual(
            list_command[list_command.index("--folder-token") + 1], "folder-token"
        )

    def test_verify_doc_archive_rejects_wrong_owner(self) -> None:
        response = {
            "ok": True,
            "data": {
                "metas": [{"doc_token": "doc-token", "owner_id": "wrong-owner"}]
            },
        }
        with mock.patch.object(MODULE, "_run_lark", return_value=("", response)):
            with self.assertRaisesRegex(SystemExit, "owner verification failed"):
                MODULE.verify_doc_archive("doc-token", "folder-token", "owner-id")

    def test_verify_doc_archive_rejects_missing_folder_entry(self) -> None:
        responses = [
            (
                "",
                {
                    "ok": True,
                    "data": {
                        "metas": [
                            {"doc_token": "doc-token", "owner_id": "owner-id"}
                        ]
                    },
                },
            ),
            ("", {"ok": True, "data": {"files": []}}),
        ]
        with mock.patch.object(MODULE, "_run_lark", side_effect=responses):
            with self.assertRaisesRegex(SystemExit, "folder verification failed"):
                MODULE.verify_doc_archive("doc-token", "folder-token", "owner-id")


if __name__ == "__main__":
    unittest.main()
