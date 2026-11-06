import csv
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import follow_up as fu

FIELDS = ["company", "contact", "email", "linkedin", "role", "subject", "sent", "follow_up_date", "notes"]


def write(path, rows, fields=FIELDS):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def row(company, **kw):
    return {"company": company, "contact": "ann lee", "email": f"a@{company.lower()}.com", "role": "LLM Intern",
            "subject": "LLM Intern - Prajwal", **kw}


class TestLogic(unittest.TestCase):
    def test_parse_date(self):
        self.assertEqual(fu.parse_date("2026-11-06"), date(2026, 11, 6))
        self.assertEqual(fu.parse_date("06-11-2026"), date(2026, 11, 6))
        self.assertIsNone(fu.parse_date("20 Sep"))
        self.assertIsNone(fu.parse_date(""))

    def test_classify(self):
        rows = [
            row("Acme", sent="2026-11-01"),                                  # due via sent+6 = 11-07? no, not yet
            row("Beta", sent="2026-10-25"),                                  # due
            row("Gamma", sent="2026-10-25", replied="y"),                    # closed
            row("Delta", sent="2026-10-25", followed_up="2026-11-01"),       # closed (one follow-up only)
            row("Eps"),                                                      # not sent
            row("Zeta", sent="2026-10-25", follow_up_date="2026-11-10"),     # explicit date wins
        ]
        for r in rows:
            r.setdefault("replied", ""); r.setdefault("followed_up", "")
        due, up = fu.classify(rows, date(2026, 11, 6), 6)
        self.assertEqual([r["company"] for r, _ in due], ["Beta"])
        self.assertEqual({r["company"] for r, _ in up}, {"Acme", "Zeta"})

    def test_followup_text(self):
        t = fu.followup_text({"contact": "ann lee", "role": "LLM Intern", "company": "Acme"}, "Prajwal Kamte")
        self.assertIn("Hi Ann,", t)
        self.assertIn("LLM Intern role at Acme", t)
        self.assertTrue(t.endswith("Prajwal Kamte"))


class TestCli(unittest.TestCase):
    def test_flow(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            dr, out, pr = d / "drafts.csv", d / "fu.csv", d / "profile.json"
            write(dr, [row("Acme"), row("Beta")])          # old file: no replied/followed_up columns
            pr.write_text(json.dumps({"name": "Prajwal Kamte"}))
            base = ["--drafts", str(dr), "--out", str(out), "--profile", str(pr)]

            fu.main(base + ["--today", "2026-10-25", "sent", "Acme"])
            rows = list(csv.DictReader(open(dr)))
            self.assertEqual(rows[0]["sent"], "2026-10-25")
            self.assertEqual(rows[0]["follow_up_date"], "2026-10-31")
            self.assertIn("replied", rows[0])               # columns were added
            self.assertEqual(rows[1]["sent"], "")

            fu.main(base + ["--today", "2026-10-30"])
            self.assertEqual(list(csv.DictReader(open(out))), [])          # not due yet

            fu.main(base + ["--today", "2026-11-01"])
            fl = list(csv.DictReader(open(out)))
            self.assertEqual([r["company"] for r in fl], ["Acme"])
            self.assertTrue(fl[0]["subject"].startswith("Re: "))
            self.assertIn("Prajwal Kamte", fl[0]["body"])

            fu.main(base + ["--today", "2026-11-01", "followed", "acme"])  # case-insensitive
            fu.main(base + ["--today", "2026-11-20"])
            self.assertEqual(list(csv.DictReader(open(out))), [])          # one follow-up only

    def test_unknown_company_exits(self):
        with tempfile.TemporaryDirectory() as d:
            dr = Path(d) / "drafts.csv"
            write(dr, [row("Acme")])
            with self.assertRaises(SystemExit):
                fu.main(["--drafts", str(dr), "sent", "Nope"])

    def test_replied_closes(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            dr, out = d / "drafts.csv", d / "fu.csv"
            write(dr, [row("Acme", sent="2026-10-01")])
            fu.main(["--drafts", str(dr), "--out", str(out), "--today", "2026-11-01", "replied", "Acme"])
            fu.main(["--drafts", str(dr), "--out", str(out), "--today", "2026-11-01"])
            self.assertEqual(list(csv.DictReader(open(out))), [])


if __name__ == "__main__":
    unittest.main()
