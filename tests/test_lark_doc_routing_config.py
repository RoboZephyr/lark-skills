from pathlib import Path
import unittest

from ruamel.yaml import YAML


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_yaml(relative_path: str) -> dict:
    yaml = YAML(typ="safe")
    with (REPO_ROOT / relative_path).open(encoding="utf-8") as stream:
        return yaml.load(stream)


class LarkDocRoutingConfigTest(unittest.TestCase):
    def test_deliver_template_matches_current_information_architecture(self) -> None:
        config = load_yaml("skills/lark-doc-deliver/config.example.yaml")
        storage = config["storage"]
        folders = storage["folders"]
        aliases = storage["folder_aliases"]

        self.assertNotEqual(
            storage["root_folder_token"], storage["default_folder_token"]
        )
        self.assertEqual(folders["inbox"], storage["default_folder_token"])
        self.assertTrue(
            {
                "weekly_demand_management",
                "reports",
                "archive",
                "team",
                "zero_stage_delivery",
            }
            <= folders.keys()
        )
        self.assertFalse(
            {"collaboration", "recruiting_operations", "recruiting_exercises", "tools"}
            & folders.keys()
        )
        self.assertTrue(aliases.keys() <= folders.keys())

    def test_progress_report_overrides_historical_weekly_report_folder(self) -> None:
        progress = load_yaml("skills/progress-report/config.example.yaml")
        weekly = load_yaml("skills/weekly-report/config.example.yaml")

        self.assertNotEqual(
            progress["lark"]["doc"]["folder_token"],
            weekly["lark"]["doc"]["folder_token"],
        )


if __name__ == "__main__":
    unittest.main()
