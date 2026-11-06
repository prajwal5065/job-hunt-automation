import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import hiring_checker as hc

KW = json.loads((Path(__file__).resolve().parent.parent / "keywords.json").read_text())


class Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code, self._p, self.text = status, payload, text

    def json(self):
        if self._p is None:
            raise ValueError
        return self._p


class TestDetect(unittest.TestCase):
    def test_find_links(self):
        t = ('<a href="https://boards.greenhouse.io/acme">x</a> '
             '<a href="https://jobs.lever.co/beta">y</a> '
             '<a href="https://jobs.ashbyhq.com/gamma">z</a> '
             '<script src="https://boards.greenhouse.io/embed/job_board?for=delta">')
        got = hc.find_ats_in_text(t)
        self.assertIn(("greenhouse", "acme"), got)
        self.assertIn(("lever", "beta"), got)
        self.assertIn(("ashby", "gamma"), got)
        self.assertIn(("greenhouse", "delta"), got)
        self.assertNotIn(("greenhouse", "embed"), got)

    def test_slug_guesses(self):
        self.assertEqual(hc.slug_guesses("Example AI", "www.exampleai.com"), ["example-ai", "exampleai"])


class TestMatch(unittest.TestCase):
    def j(self, title, loc="Pune, India", remote=False):
        return hc.Job(title, loc, "http://x", remote, "lever")

    def test_matches_genai_intern_pune(self):
        m = hc.match_job(self.j("GenAI Engineer Intern"), KW)
        self.assertIsNotNone(m)
        self.assertEqual(m["level"], "entry")
        self.assertEqual(m["location_match"], "pune")

    def test_rejects_senior_and_non_ai(self):
        self.assertIsNone(hc.match_job(self.j("Senior ML Engineer"), KW))
        self.assertIsNone(hc.match_job(self.j("Account Executive, AI"), KW))
        self.assertIsNone(hc.match_job(self.j("Office Manager"), KW))

    def test_word_boundaries(self):
        self.assertIsNone(hc.match_job(self.j("Maintain Systems Engineer"), KW))

    def test_location_filter(self):
        self.assertIsNone(hc.match_job(self.j("LLM Engineer", "Berlin, Germany"), KW))
        self.assertIsNotNone(hc.match_job(self.j("LLM Engineer", "Berlin, Germany"), KW, any_location=True))
        self.assertIsNotNone(hc.match_job(self.j("LLM Engineer", "Berlin", remote=True), KW))


class TestFetchAndRun(unittest.TestCase):
    def test_parsers(self):
        with patch.object(hc, "http_get", return_value=Resp(payload={"jobs": [
                {"title": "RAG Engineer", "location": {"name": "Remote"}, "absolute_url": "u"}]})):
            self.assertEqual(hc.fetch_greenhouse("a")[0].title, "RAG Engineer")
        with patch.object(hc, "http_get", return_value=Resp(payload=[
                {"text": "ML Intern", "hostedUrl": "u", "categories": {"location": "Pune"}}])):
            self.assertEqual(hc.fetch_lever("a")[0].location, "Pune")
        with patch.object(hc, "http_get", return_value=Resp(payload={"jobs": [
                {"title": "AI Engineer", "location": "India", "isRemote": False, "jobUrl": "u"}]})):
            self.assertEqual(hc.fetch_ashby("a")[0].title, "AI Engineer")

    def test_404_means_no_board(self):
        with patch.object(hc, "http_get", return_value=Resp(status=404)):
            self.assertIsNone(hc.fetch_lever("nope"))

    def test_check_company_end_to_end(self):
        def fake(url, **kw):
            if "api.lever.co/v0/postings/acme" in url:
                return Resp(payload=[
                    {"text": "LLM Engineer Intern", "hostedUrl": "u1", "categories": {"location": "Pune"}},
                    {"text": "Head of Sales", "hostedUrl": "u2", "categories": {"location": "Pune"}}])
            if url.startswith("https://acme.com"):
                return Resp(text='<a href="https://jobs.lever.co/acme">Careers</a>')
            return Resp(status=404)
        with patch.object(hc, "http_get", side_effect=fake):
            res = hc.check_company({"company": "Acme", "website": "acme.com"}, KW)
        self.assertEqual((res["ats"], res["how"], res["total"], len(res["matches"])), ("lever", "detected", 2, 1))

    def test_no_board(self):
        with patch.object(hc, "http_get", return_value=Resp(status=404)):
            self.assertIsNone(hc.check_company({"company": "Ghost", "website": "ghost.io"}, KW))


if __name__ == "__main__":
    unittest.main()
