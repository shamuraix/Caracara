import contextlib
import datetime as dt
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_trivyignore as ct  # noqa: E402

TODAY = dt.date(2026, 9, 18)


class ValidateTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(ct.validate(None, TODAY, 90), [])
        self.assertEqual(ct.validate({"vulnerabilities": []}, TODAY, 90), [])

    def test_valid_entry(self):
        doc = {"vulnerabilities": [{"id": "CVE-2026-0001", "statement": "not reachable", "expired_at": dt.date(2026, 10, 1)}]}
        self.assertEqual(ct.validate(doc, TODAY, 90), [])

    def test_missing_fields(self):
        doc = {"vulnerabilities": [{"id": "CVE-1"}, {"statement": "x"}]}
        problems = ct.validate(doc, TODAY, 90)
        self.assertEqual(len(problems), 3)
        self.assertTrue(any("statement" in p for p in problems))
        self.assertTrue(any("expired_at" in p for p in problems))
        self.assertTrue(any("needs an id" in p for p in problems))

    def test_expired_and_too_long(self):
        doc = {"vulnerabilities": [
            {"id": "OLD", "statement": "s", "expired_at": "2026-09-18"},
            {"id": "LONG", "statement": "s", "expired_at": "2027-09-18"},
        ]}
        problems = ct.validate(doc, TODAY, 90)
        self.assertEqual(len(problems), 2)
        self.assertIn("OLD: expired", problems[0])
        self.assertIn("LONG: expires", problems[1])

    def test_unknown_section(self):
        self.assertTrue(ct.validate({"bogus": []}, TODAY, 90)[0].startswith("unknown top-level keys"))

    def test_repo_file_is_valid(self):
        with contextlib.redirect_stdout(io.StringIO()):
            rc = ct.main([str(ROOT / ".trivyignore.yaml"), "--today", "2026-09-18"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
