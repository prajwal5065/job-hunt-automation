import csv
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pipeline as pl


def write(path, fields, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


class InTempDir(unittest.TestCase):
    def setUp(self):
        self._old = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)

    def tearDown(self):
        os.chdir(self._old)
        self._tmp.cleanup()


class TestStatus(InTempDir):
    def test_missing_files_are_none(self):
        s = pl.status(today=date(2026, 11, 6))
        self.assertIsNone(s["companies"])
        self.assertNotIn("sent", s)

    def test_counts(self):
        write("companies.csv", ["company", "website"], [{"company": "A", "website": "a.com"}, {"company": "B", "website": "b.com"}, {"company": " ", "website": ""}])
        write("matches.csv", ["company", "title"], [{"company": "A", "title": "x"}, {"company": "A", "title": "y"}])
        write("contacts.csv", ["company", "email"], [{"company": "A", "email": "a@a.com"}])
        write("drafts.csv", ["company", "sent", "follow_up_date", "replied", "followed_up"], [
            {"company": "A", "sent": "2026-10-20", "follow_up_date": "2026-10-26", "replied": "", "followed_up": ""},
            {"company": "B", "sent": "2026-11-05", "follow_up_date": "2026-11-11", "replied": "", "followed_up": ""},
            {"company": "C", "sent": "2026-10-01", "follow_up_date": "", "replied": "y", "followed_up": ""},
            {"company": "D", "sent": "", "follow_up_date": "", "replied": "", "followed_up": ""},
        ])
        s = pl.status(today=date(2026, 11, 6))
        self.assertEqual((s["companies"], s["companies_with_matches"], s["matching_roles"]), (2, 1, 2))
        self.assertEqual((s["contacts"], s["drafts"], s["sent"], s["replied"]), (1, 4, 3, 1))
        self.assertEqual((s["follow_ups_due"], s["waiting"]), (1, 1))


class TestRun(InTempDir):
    def args(self, *a):
        import argparse
        p = argparse.Namespace(dry_run=False, max_lookups=10, min_score=0, any_location=False, llm=None, applied=False)
        for k, v in zip(a[::2], a[1::2]):
            setattr(p, k, v)
        return p

    def test_requires_companies_csv(self):
        with self.assertRaises(SystemExit):
            pl.run(self.args())

    def test_stops_without_hunter_key(self):
        Path("companies.csv").write_text("company,website\nA,a.com\n")
        calls = []
        with patch.object(pl.hiring_checker, "main", side_effect=lambda a: (write("matches.csv", ["company", "title"], [{"company": "A", "title": "x"}]), calls.append("hc"))), \
                patch.object(pl.contact_finder, "main", side_effect=lambda a: calls.append("cf")), \
                patch.object(pl.message_drafter, "main", side_effect=lambda a: calls.append("md")), \
                patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HUNTER_API_KEY", None)
            pl.run(self.args())
        self.assertEqual(calls, ["hc"])

    def test_full_run_passes_options(self):
        Path("companies.csv").write_text("company,website\nA,a.com\n")
        Path("profile.json").write_text("{}")
        seen = {}
        with patch.object(pl.hiring_checker, "main", side_effect=lambda a: (write("matches.csv", ["company", "title"], [{"company": "A", "title": "x"}]), seen.update(hc=a))), \
                patch.object(pl.contact_finder, "main", side_effect=lambda a: seen.update(cf=a)), \
                patch.object(pl.message_drafter, "main", side_effect=lambda a: seen.update(md=a)), \
                patch.dict(os.environ, {"HUNTER_API_KEY": "k"}):
            pl.run(self.args("llm", "gemini", "applied", True, "max_lookups", 4, "any_location", True))
        self.assertIn("--any-location", seen["hc"])
        self.assertEqual(seen["cf"][seen["cf"].index("--max-lookups") + 1], "4")
        self.assertIn("--applied", seen["md"])
        self.assertEqual(seen["md"][seen["md"].index("--llm") + 1], "gemini")

    def test_dry_run_never_drafts(self):
        Path("companies.csv").write_text("company,website\nA,a.com\n")
        seen = []
        with patch.object(pl.hiring_checker, "main", side_effect=lambda a: write("matches.csv", ["company", "title"], [{"company": "A", "title": "x"}])), \
                patch.object(pl.contact_finder, "main", side_effect=lambda a: seen.append(a)), \
                patch.object(pl.message_drafter, "main", side_effect=lambda a: seen.append("md")):
            pl.run(self.args("dry_run", True))
        self.assertEqual(len(seen), 1)
        self.assertIn("--dry-run", seen[0])

    def test_no_matches_stops_early(self):
        Path("companies.csv").write_text("company,website\nA,a.com\n")
        with patch.object(pl.hiring_checker, "main", side_effect=lambda a: write("matches.csv", ["company", "title"], [])), \
                patch.object(pl.contact_finder, "main") as cf:
            pl.run(self.args())
        cf.assert_not_called()


if __name__ == "__main__":
    unittest.main()
