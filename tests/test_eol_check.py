import contextlib
import datetime as dt
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import eol_check as ec  # noqa: E402

TODAY = dt.date(2026, 9, 18)
DOC = {
    "base_os": {"name": "UBI 9", "full_support_ends": "2027-05-31", "maintenance_ends": "2032-05-31"},
    "products": {
        "jira": {
            "lts": {"line": "11.3", "support_ends": "2027-12-01"},
            "latest": {"line": "11.6", "support_ends": None},
        },
        "confluence": {"lts": {"line": "9.2", "support_ends": "2026-10-10"}},
        "bitbucket": {"line": "9.4", "lts": True, "support_ends": "2026-09-01"},  # legacy single-line shape
    },
}


class EvaluateTests(unittest.TestCase):
    def test_statuses(self):
        rows = {(r["name"], r["phase"]): r for r in ec.evaluate(DOC, TODAY, 90, 30)}
        self.assertEqual(rows[("UBI 9", "full support")]["status"], "ok")
        self.assertEqual(rows[("UBI 9", "maintenance")]["days"], (dt.date(2032, 5, 31) - TODAY).days)
        self.assertEqual(rows[("jira/lts 11.3", "LTS")]["status"], "ok")
        self.assertEqual(rows[("jira/latest 11.6", "feature release")]["status"], "unknown")
        self.assertEqual(rows[("confluence/lts 9.2", "LTS")]["status"], "fail")
        self.assertEqual(rows[("bitbucket/lts 9.4", "LTS")]["status"], "expired")

    def test_warn_band(self):
        doc = {"products": {"p": {"line": "1", "support_ends": (TODAY + dt.timedelta(days=60)).isoformat()}}}
        self.assertEqual(ec.evaluate(doc, TODAY, 90, 30)[0]["status"], "warn")

    def test_repo_file_covers_every_line(self):
        import yaml
        doc = yaml.safe_load((ROOT / "support-windows.yaml").read_text())
        for product in ("jira", "confluence", "bitbucket"):
            for line in ("lts", "latest"):
                self.assertIn(line, doc["products"][product], f"{product}/{line}")
                _, mdoc = __import__("manifest").load(ROOT / product / line)
                self.assertTrue(mdoc["args"]["VERSION"].startswith(doc["products"][product][line]["line"] + "."), f"{product}/{line}")

    def test_repo_file(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = ec.main([str(ROOT / "support-windows.yaml"), "--today", "2026-09-18"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
