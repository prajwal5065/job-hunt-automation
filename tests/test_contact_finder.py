import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import contact_finder as cf


def email(first, last, pos, conf=90, dept="", ver="valid"):
    return {"first_name": first, "last_name": last, "position": pos, "value": f"{first}@x.com".lower(),
            "confidence": conf, "department": dept, "verification": {"status": ver},
            "linkedin": f"https://linkedin.com/in/{first}"}


class TestHelpers(unittest.TestCase):
    def test_domain_of(self):
        self.assertEqual(cf.domain_of("https://www.Acme.com/careers"), "acme.com")
        self.assertEqual(cf.domain_of("acme.io"), "acme.io")
        self.assertEqual(cf.domain_of(""), "")

    def test_rank_prefers_hiring_people(self):
        cs = [
            {"email": "a@x.com", "position": "Software Engineer", "confidence": "99"},
            {"email": "b@x.com", "position": "Co-Founder & CEO", "confidence": "80"},
            {"email": "c@x.com", "position": "Technical Recruiter", "confidence": "70"},
            {"email": "d@x.com", "position": "Head of AI", "confidence": "60"},
            {"email": "", "position": "Talent Lead", "confidence": "99"},
        ]
        order = [c["email"] for c in cf.rank(cs, 4)]
        self.assertEqual(order, ["c@x.com", "d@x.com", "b@x.com", "a@x.com"])

    def test_credits_left(self):
        with patch.object(cf, "api_get", return_value=(200, {"data": {"requests": {"credits": {"used": 12, "available": 50}}}})):
            self.assertEqual(cf.credits_left("k"), 38)
        with patch.object(cf, "api_get", return_value=(500, None)):
            self.assertIsNone(cf.credits_left("k"))

    def test_domain_search_parses_and_handles_errors(self):
        payload = {"data": {"emails": [email("Ann", "Lee", "Talent Partner", dept="hr")]}}
        with patch.object(cf, "api_get", return_value=(200, payload)):
            out = cf.domain_search("x.com", "k")
        self.assertEqual(out[0]["name"], "Ann Lee")
        with patch.object(cf, "api_get", return_value=(429, None)):
            with self.assertRaises(cf.RateLimited):
                cf.domain_search("x.com", "k")
        with patch.object(cf, "api_get", return_value=(404, None)):
            self.assertEqual(cf.domain_search("x.com", "k"), [])


class TestMain(unittest.TestCase):
    def test_end_to_end_uses_cache_and_budget(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            with open(d / "matches.csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["company", "title", "url", "score", "website"])
                w.writeheader()
                w.writerows([
                    {"company": "Acme", "title": "LLM Intern", "url": "u1", "score": 6, "website": "acme.com"},
                    {"company": "Beta", "title": "ML Engineer", "url": "u2", "score": 3, "website": "beta.io"},
                    {"company": "Gamma", "title": "AI Engineer", "url": "u3", "score": 2, "website": "gamma.ai"},
                ])
            (d / "cache.json").write_text(json.dumps({"gamma.ai": [
                {"name": "Cy", "position": "CTO", "email": "cy@gamma.ai", "confidence": 90,
                 "verification": "valid", "linkedin": "", "department": ""}]}))
            calls = []

            def fake(path, **p):
                calls.append(path)
                if path == "/account":
                    return 200, {"data": {"requests": {"credits": {"used": 0, "available": 1}}}}
                return 200, {"data": {"emails": [email("Ann", "Lee", "Recruiter")]}}

            with patch.object(cf, "api_get", side_effect=fake), patch.object(cf.time, "sleep"), \
                    patch.dict("os.environ", {"HUNTER_API_KEY": "k"}):
                cf.main(["--matches", str(d / "matches.csv"), "--out", str(d / "contacts.csv"),
                         "--cache", str(d / "cache.json"), "--max-lookups", "5"])
            # only 1 credit available -> exactly one domain-search call, for the best-scoring uncached company
            self.assertEqual(calls.count("/domain-search"), 1)
            rows = list(csv.DictReader(open(d / "contacts.csv")))
            self.assertEqual({r["company"] for r in rows}, {"Acme", "Gamma"})


if __name__ == "__main__":
    unittest.main()
