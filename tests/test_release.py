"""Version im Manifest und Changelog passen zusammen, damit der Release-Workflow das Release anlegen kann."""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ReleaseTest(unittest.TestCase):
    def test_manifest_version_has_changelog_section(self):
        manifest = json.loads(
            (ROOT / "custom_components/air_water_heatpump_audit/manifest.json").read_text(encoding="utf-8")
        )
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        versions = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", changelog, flags=re.MULTILINE)
        self.assertTrue(versions, "CHANGELOG.md ohne Versionsabschnitt")
        # Ein Pre-Release (0.16.0b1) gehört zum Abschnitt seiner Zielversion (0.16.0)
        target = re.match(r"\d+\.\d+\.\d+", manifest["version"]).group(0)
        self.assertEqual(versions[0], target, "neueste Changelog-Version ≠ manifest.json")


if __name__ == "__main__":
    unittest.main()
