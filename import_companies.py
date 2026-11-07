#!/usr/bin/env python3
"""Company importer: turn whatever you collected by hand into a clean companies.csv.

  python import_companies.py export.csv                     # CSV/TSV from Crunchbase, Sheets, Notion...
  python import_companies.py --add "Acme AI" acme.ai        # add one company
  pbpaste | python import_companies.py -                    # paste a table from the clipboard

Column names are matched loosely (Organization Name, Homepage URL, Last Funding Type ...).
Websites are cleaned to a bare domain, and duplicates (same domain or name) are skipped,
so you can keep importing new batches into the same companies.csv.
"""
import argparse
import csv
import io
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

FIELDS = ["company", "website", "careers_url", "industry", "funding_round", "funding_date", "source"]

ALIASES = {
    "company": ["company", "name", "organization name", "organization", "company name", "startup"],
    "website": ["website", "url", "homepage url", "homepage", "domain", "site", "web"],
    "careers_url": ["careers_url", "careers", "careers page", "careers url", "jobs url", "jobs"],
    "industry": ["industry", "industries", "category", "sector"],
    "funding_round": ["funding_round", "last funding type", "funding type", "round", "stage", "funding stage"],
    "funding_date": ["funding_date", "last funding date", "funding date", "date announced", "date"],
}


def clean_domain(value):
    """'https://www.Acme.ai/about?x=1' -> 'acme.ai'. Returns '' if it doesn't look like a domain."""
    v = (value or "").strip().lower()
    if not v:
        return ""
    host = urlparse(v if "//" in v else f"//{v}").netloc.split("@")[-1].split(":")[0]
    host = re.sub(r"^www\.", "", host)
    return host if re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", host) else ""


def map_headers(headers):
    """Return {canonical_field: original_header} for the headers we recognise."""
    norm = {h.strip().lower(): h for h in headers if h}
    out = {}
    for field, names in ALIASES.items():
        for n in names:
            if n in norm:
                out[field] = norm[n]
                break
    return out


def parse_table(text):
    """Parse CSV/TSV text into a list of dicts with canonical fields (missing ones empty)."""
    text = text.lstrip("\ufeff")
    if not text.strip():
        return []
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",\t;|")
    except csv.Error:
        dialect = csv.excel
    rd = csv.DictReader(io.StringIO(text), dialect=dialect)
    cols = map_headers(rd.fieldnames or [])
    if "company" not in cols:
        raise ValueError("Couldn't find a company-name column. Expected one of: " + ", ".join(ALIASES["company"]))
    rows = []
    for r in rd:
        row = {f: (r.get(cols[f]) or "").strip() if f in cols else "" for f in ALIASES}
        if row["company"]:
            row["website"] = clean_domain(row["website"])
            rows.append(row)
    return rows


def key_of(row):
    return clean_domain(row.get("website")) or re.sub(r"[^a-z0-9]+", "", row["company"].lower())


def load_existing(path):
    p = Path(path)
    if not p.exists():
        return [], list(FIELDS)
    with open(p, newline="", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        fields = list(rd.fieldnames or FIELDS)
        rows = [r for r in rd if (r.get("company") or "").strip()]
    for c in FIELDS:
        if c not in fields:
            fields.append(c)
    return rows, fields


def merge(existing, new_rows, source):
    """Return (merged_rows, added, skipped_duplicates). Existing rows are kept untouched."""
    seen, names = set(), set()
    for r in existing:
        seen.add(key_of(r))
        names.add(re.sub(r"[^a-z0-9]+", "", r["company"].lower()))
    merged, added, dupes = list(existing), [], 0
    for r in new_rows:
        k, n = key_of(r), re.sub(r"[^a-z0-9]+", "", r["company"].lower())
        if k in seen or n in names:
            dupes += 1
            continue
        seen.add(k)
        names.add(n)
        row = {**r, "source": r.get("source") or source}
        merged.append(row)
        added.append(row)
    return merged, added, dupes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("file", nargs="?", help="CSV/TSV file to import, or - for stdin")
    ap.add_argument("--add", nargs="+", metavar=("NAME", "WEBSITE"), help='add one company: --add "Acme AI" acme.ai')
    ap.add_argument("--out", default="companies.csv")
    ap.add_argument("--source", default="import", help="value for the source column (e.g. crunchbase)")
    args = ap.parse_args(argv)

    if args.add:
        new = [{**{f: "" for f in ALIASES}, "company": args.add[0].strip(),
                "website": clean_domain(args.add[1]) if len(args.add) > 1 else ""}]
    elif args.file:
        text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
        try:
            new = parse_table(text)
        except ValueError as e:
            sys.exit(str(e))
    else:
        ap.error("give a file, - for stdin, or --add")

    existing, fields = load_existing(args.out)
    merged, added, dupes = merge(existing, new, args.source)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in merged:
            w.writerow({k: r.get(k, "") for k in fields})

    print(f"Added {len(added)}, skipped {dupes} duplicate(s). {args.out} now has {len(merged)} companies.")
    no_site = [r["company"] for r in added if not r["website"]]
    if no_site:
        print(f"No usable website for {len(no_site)}: {', '.join(no_site[:8])}"
              + (" ..." if len(no_site) > 8 else ""))
        print("The hiring check can still guess a job board from the name, but contact lookup needs a website.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
