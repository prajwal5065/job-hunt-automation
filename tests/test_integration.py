"""End-to-end check that each step's output file is accepted by the next step.

All network calls are faked; this tests the CSV contract between steps, not the live APIs.
"""
import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import contact_finder
import follow_up
import hiring_checker
import import_companies
import message_drafter
import pipeline


class Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code, self._p, self.text = status, payload, text

    def json(self):
        if self._p is None:
            raise ValueError
        return self._p


def fake_http(url, **kw):
    # Acme: Greenhouse board linked from its careers page; one matching entry-level role, one senior role
    if url == "https://acme.ai/careers":
        return Resp(text='<a href="https://boards.greenhouse.io/acmeai">Jobs</a>')
    if "boards-api.greenhouse.io/v1/boards/acmeai/jobs" in url:
        return Resp(payload={"jobs": [
            {"title": "GenAI Engineer Intern", "location": {"name": "Pune, India"}, "absolute_url": "https://x/1"},
            {"title": "Senior ML Engineer", "location": {"name": "Pune, India"}, "absolute_url": "https://x/2"},
        ]})
    # Beta: nothing detectable anywhere
    return Resp(status=404)


def fake_hunter(path, **p):
    if path == "/account":
        return 200, {"data": {"requests": {"credits": {"used": 0, "available": 50}}}}
    if p.get("domain") == "acme.ai":
        return 200, {"data": {"emails": [
            {"first_name": "Dev", "last_name": "Roy", "position": "Software Engineer", "value": "dev@acme.ai", "confidence": 95},
            {"first_name": "Priya", "last_name": "Shah", "position": "Talent Partner", "value": "priya@acme.ai",
             "confidence": 80, "department": "hr", "verification": {"status": "valid"}, "linkedin": "https://linkedin.com/in/p"},
        ]}}
    return 200, {"data": {"emails": []}}


class TestWholePipeline(unittest.TestCase):
    def setUp(self):
        self._old = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        for name in ("keywords.json", "profile.example.json"):
            Path(name).write_text((ROOT / name).read_text())
        Path("profile.json").write_text((ROOT / "profile.example.json").read_text())

    def tearDown(self):
        os.chdir(self._old)
        self._tmp.cleanup()

    def test_import_to_followup(self):
        # 1) import
        import_companies.main(["--add", "Acme AI", "https://www.acme.ai/"])
        import_companies.main(["--add", "Beta Labs", "beta.io"])

        with patch.object(hiring_checker, "http_get", side_effect=fake_http), patch.object(hiring_checker.time, "sleep"), \
                patch.object(contact_finder, "api_get", side_effect=fake_hunter), patch.object(contact_finder.time, "sleep"), \
                patch.dict(os.environ, {"HUNTER_API_KEY": "k"}):
            # 2-4) full run through the runner
            self.assertEqual(pipeline.main(["run"]), 0)

        matches = list(csv.DictReader(open("matches.csv")))
        self.assertEqual([m["title"] for m in matches], ["GenAI Engineer Intern"])      # senior role filtered out
        self.assertEqual(matches[0]["website"], "acme.ai")
        self.assertEqual(matches[0]["board_source"], "detected")
        self.assertEqual([r["company"] for r in csv.DictReader(open("no_board.csv"))], ["Beta Labs"])

        contacts = list(csv.DictReader(open("contacts.csv")))
        self.assertEqual(contacts[0]["email"], "priya@acme.ai")                           # recruiter ranked first
        self.assertEqual(contacts[0]["role_to_apply"], "GenAI Engineer Intern")

        drafts = list(csv.DictReader(open("drafts.csv")))
        self.assertEqual(len(drafts), 1)                                                  # one draft per company
        self.assertIn("Hi Priya,", drafts[0]["body"])
        self.assertIn("GenAI Engineer Intern", drafts[0]["body"])
        self.assertEqual(drafts[0]["replied"], "")                                        # tracking columns present

        # 5) mark sent, status, follow-up
        follow_up.main(["sent", "Acme AI"])
        s = pipeline.status()
        self.assertEqual((s["companies"], s["companies_with_matches"], s["drafts"], s["sent"]), (2, 1, 1, 1))
        self.assertEqual(s["follow_ups_due"], 0)

        later = (date.today() + timedelta(days=7)).isoformat()
        follow_up.main(["--today", later])
        due = list(csv.DictReader(open("follow_ups.csv")))
        self.assertEqual([d["email"] for d in due], ["priya@acme.ai"])
        self.assertIn("Re: ", due[0]["subject"])

        follow_up.main(["--today", later, "followed", "Acme AI"])
        follow_up.main(["--today", later])
        self.assertEqual(list(csv.DictReader(open("follow_ups.csv"))), [])

    def test_rerun_uses_hunter_cache(self):
        import_companies.main(["--add", "Acme AI", "acme.ai"])
        calls = []

        def counting(path, **p):
            calls.append(path)
            return fake_hunter(path, **p)

        with patch.object(hiring_checker, "http_get", side_effect=fake_http), patch.object(hiring_checker.time, "sleep"), \
                patch.object(contact_finder, "api_get", side_effect=counting), patch.object(contact_finder.time, "sleep"), \
                patch.dict(os.environ, {"HUNTER_API_KEY": "k"}):
            pipeline.main(["run"])
            pipeline.main(["run"])
        self.assertEqual(calls.count("/domain-search"), 1)


if __name__ == "__main__":
    unittest.main()
