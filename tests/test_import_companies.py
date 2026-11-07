import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import import_companies as ic


class TestParsing(unittest.TestCase):
    def test_clean_domain(self):
        self.assertEqual(ic.clean_domain("https://www.Acme.ai/about?x=1"), "acme.ai")
        self.assertEqual(ic.clean_domain("acme.ai"), "acme.ai")
        self.assertEqual(ic.clean_domain("http://user@sub.acme.co.in:8080/x"), "sub.acme.co.in")
        self.assertEqual(ic.clean_domain("Acme"), "")
        self.assertEqual(ic.clean_domain(""), "")

    def test_crunchbase_style_headers(self):
        text = ("Organization Name,Homepage URL,Last Funding Type,Last Funding Date,Industries\n"
                "Acme AI,https://www.acme.ai/,Series A,2026-09-01,Artificial Intelligence\n"
                "Beta,,Seed,2026-08-15,SaaS\n")
        rows = ic.parse_table(text)
        self.assertEqual(rows[0]["company"], "Acme AI")
        self.assertEqual(rows[0]["website"], "acme.ai")
        self.assertEqual(rows[0]["funding_round"], "Series A")
        self.assertEqual(rows[0]["industry"], "Artificial Intelligence")
        self.assertEqual(rows[1]["website"], "")

    def test_tsv_and_bom(self):
        text = "\ufeffName\tWebsite\nAcme AI\tacme.ai\n"
        rows = ic.parse_table(text)
        self.assertEqual((rows[0]["company"], rows[0]["website"]), ("Acme AI", "acme.ai"))

    def test_missing_company_column(self):
        with self.assertRaises(ValueError):
            ic.parse_table("foo,bar\n1,2\n")

    def test_blank_rows_skipped(self):
        self.assertEqual(len(ic.parse_table("company,website\n,\nAcme,acme.ai\n")), 1)


class TestMerge(unittest.TestCase):
    def row(self, name, site=""):
        return {"company": name, "website": site, "careers_url": "", "industry": "", "funding_round": "", "funding_date": ""}

    def test_dedupe_by_domain_and_name(self):
        existing = [{"company": "Acme AI", "website": "https://acme.ai"}]
        merged, added, dupes = ic.merge(existing, [self.row("Acme", "www.acme.ai"), self.row("ACME  AI"), self.row("Beta", "beta.io")], "x")
        self.assertEqual([r["company"] for r in added], ["Beta"])
        self.assertEqual(dupes, 2)
        self.assertEqual(len(merged), 2)

    def test_dedupe_within_batch(self):
        _, added, dupes = ic.merge([], [self.row("Beta", "beta.io"), self.row("Beta Inc", "beta.io")], "x")
        self.assertEqual((len(added), dupes), (1, 1))

    def test_source_default(self):
        _, added, _ = ic.merge([], [self.row("Beta", "beta.io")], "crunchbase")
        self.assertEqual(added[0]["source"], "crunchbase")


class TestCli(unittest.TestCase):
    def test_import_then_add_then_reimport(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            src, out = d / "export.csv", d / "companies.csv"
            src.write_text("Organization Name,Homepage URL\nAcme AI,https://acme.ai\nBeta,beta.io\n")
            ic.main([str(src), "--out", str(out), "--source", "crunchbase"])
            ic.main(["--add", "Gamma Labs", "gamma.dev", "--out", str(out)])
            ic.main([str(src), "--out", str(out)])                       # same batch again: all duplicates
            rows = list(csv.DictReader(open(out)))
            self.assertEqual([r["company"] for r in rows], ["Acme AI", "Beta", "Gamma Labs"])
            self.assertEqual(rows[0]["source"], "crunchbase")
            self.assertEqual(rows[2]["website"], "gamma.dev")

    def test_keeps_extra_columns_of_existing_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "companies.csv"
            out.write_text("company,website,my_notes\nAcme,acme.ai,call mom\n")
            ic.main(["--add", "Beta", "beta.io", "--out", str(out)])
            rows = list(csv.DictReader(open(out)))
            self.assertEqual(rows[0]["my_notes"], "call mom")
            self.assertIn("careers_url", rows[0])


if __name__ == "__main__":
    unittest.main()
