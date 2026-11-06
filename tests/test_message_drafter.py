import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import message_drafter as md

PROFILE = json.loads((Path(__file__).resolve().parent.parent / "profile.example.json").read_text())
C = {"company": "Acme", "role_to_apply": "LLM Intern", "name": "ann lee", "position": "Recruiter", "email": "a@acme.com"}


class TestTemplate(unittest.TestCase):
    def test_first_name(self):
        self.assertEqual(md.first_name("ann lee"), "Ann")
        self.assertEqual(md.first_name(""), "there")

    def test_template_content(self):
        t = md.template_message(C, PROFILE)
        self.assertIn("Hi Ann,", t)
        self.assertIn("Acme", t)
        self.assertIn("LLM Intern", t)
        self.assertIn("I'm applying for the role", t)
        self.assertTrue(t.rstrip().endswith(PROFILE["name"]))
        self.assertLess(len(t.split()), 110)

    def test_applied_flag(self):
        self.assertIn("I've applied for the role", md.template_message(C, PROFILE, applied=True))


class TestDraft(unittest.TestCase):
    def test_llm_success(self):
        with patch.object(md, "gemini_generate", return_value="Hi Ann, short note. Prajwal"):
            self.assertEqual(md.draft(C, PROFILE, False, "gemini", "k", "m")[2], "llm")

    def test_llm_failure_falls_back(self):
        with patch.object(md, "gemini_generate", return_value=None):
            self.assertEqual(md.draft(C, PROFILE, False, "gemini", "k", "m")[2], "template")

    def test_llm_too_long_falls_back(self):
        with patch.object(md, "gemini_generate", return_value="word " * 200):
            self.assertEqual(md.draft(C, PROFILE, False, "gemini", "k", "m")[2], "template")

    def test_no_key_uses_template(self):
        with patch.object(md, "gemini_generate") as g:
            self.assertEqual(md.draft(C, PROFILE, False, "gemini", "", "m")[2], "template")
            g.assert_not_called()


class TestMain(unittest.TestCase):
    def test_end_to_end_per_company(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "profile.json").write_text(json.dumps(PROFILE))
            with open(d / "contacts.csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["company", "role_to_apply", "apply_url", "name", "position", "email", "linkedin"])
                w.writeheader()
                w.writerows([
                    {"company": "Acme", "role_to_apply": "LLM Intern", "apply_url": "u", "name": "Ann", "position": "Recruiter", "email": "a@a.com", "linkedin": ""},
                    {"company": "Acme", "role_to_apply": "LLM Intern", "apply_url": "u", "name": "Bob", "position": "CTO", "email": "b@a.com", "linkedin": ""},
                    {"company": "Beta", "role_to_apply": "ML Engineer", "apply_url": "u2", "name": "Cy", "position": "CEO", "email": "", "linkedin": ""},
                ])
            md.main(["--contacts", str(d / "contacts.csv"), "--profile", str(d / "profile.json"), "--out", str(d / "drafts.csv")])
            rows = list(csv.DictReader(open(d / "drafts.csv")))
            self.assertEqual([r["company"] for r in rows], ["Acme"])
            self.assertEqual(rows[0]["contact"], "Ann")


if __name__ == "__main__":
    unittest.main()
