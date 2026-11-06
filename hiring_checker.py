#!/usr/bin/env python3
"""Hiring checker.

Reads companies.csv, finds each company's public job board (Greenhouse, Lever
or Ashby), pulls the open roles, and writes the ones matching keywords.json to
matches.csv. Companies with no detectable board go to no_board.csv so you can
check them by hand.

Uses only the public job-board endpoints those ATS vendors publish. No logins,
no scraping of LinkedIn/Wellfound/Crunchbase.
"""
import argparse
import csv
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

UA = {"User-Agent": "job-hunt-automation/0.1 (personal job search)"}
TIMEOUT = 15
SKIP_SLUGS = {"embed", "jobs", "api", "v1", "v0", "static"}

ATS_PATTERNS = {
    "greenhouse": re.compile(
        r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)", re.I),
    "lever": re.compile(r"jobs(?:\.eu)?\.lever\.co/([a-z0-9_.-]+)", re.I),
    "ashby": re.compile(r"jobs\.ashbyhq\.com/([a-z0-9_.%-]+)", re.I),
}


@dataclass
class Job:
    title: str
    location: str
    url: str
    remote: bool
    ats: str


def http_get(url, **kw):
    """GET wrapper. Returns a Response or None. Tests patch this."""
    try:
        return requests.get(url, headers=UA, timeout=TIMEOUT, **kw)
    except requests.RequestException:
        return None


def _json(url):
    r = http_get(url)
    if r is None or r.status_code != 200:
        return None
    try:
        return r.json()
    except ValueError:
        return None


# ---- job board fetchers: return list[Job], or None if no board at that slug ----

def fetch_greenhouse(slug):
    data = _json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    if not isinstance(data, dict):
        return None
    jobs = []
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "") or ""
        jobs.append(Job(j.get("title", ""), loc, j.get("absolute_url", ""),
                        "remote" in loc.lower(), "greenhouse"))
    return jobs


def fetch_lever(slug):
    data = _json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if not isinstance(data, list):
        return None
    jobs = []
    for j in data:
        loc = (j.get("categories") or {}).get("location", "") or ""
        remote = (j.get("workplaceType") == "remote") or "remote" in loc.lower()
        jobs.append(Job(j.get("text", ""), loc, j.get("hostedUrl", ""), remote, "lever"))
    return jobs


def fetch_ashby(slug):
    data = _json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    if not isinstance(data, dict):
        return None
    jobs = []
    for j in data.get("jobs", []):
        loc = j.get("location", "") or ""
        remote = bool(j.get("isRemote")) or "remote" in loc.lower()
        jobs.append(Job(j.get("title", ""), loc, j.get("jobUrl") or j.get("applyUrl", ""), remote, "ashby"))
    return jobs


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby}


# ---- finding the board ----

def find_ats_in_text(text):
    """Return unique [(ats, slug)] for any job-board links found in text."""
    found, seen = [], set()
    for ats, pat in ATS_PATTERNS.items():
        for m in pat.finditer(text or ""):
            slug = m.group(1).rstrip(".").lower()
            if slug in SKIP_SLUGS or (ats, slug) in seen:
                continue
            seen.add((ats, slug))
            found.append((ats, slug))
    return found


def slug_guesses(company, website):
    names = set()
    base = re.sub(r"[^a-z0-9]+", "", company.lower())
    dashed = re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-")
    host = urlparse(website if "//" in website else f"//{website}").netloc or website
    host = re.sub(r"^www\.", "", host.lower())
    stem = host.split(".")[0] if host else ""
    for n in (base, dashed, stem):
        if n:
            names.add(n)
    return sorted(names)


def candidates(row):
    """Yield (ats, slug, how) in the order we should try them."""
    seen = set()

    def emit(ats, slug, how):
        if (ats, slug) not in seen:
            seen.add((ats, slug))
            return [(ats, slug, how)]
        return []

    company = row.get("company", "")
    website = (row.get("website") or "").strip()
    careers = (row.get("careers_url") or "").strip()

    for ats, slug in find_ats_in_text(careers):
        yield from emit(ats, slug, "detected")

    pages = []
    if careers:
        pages.append(careers)
    if website:
        base = website if website.startswith("http") else f"https://{website}"
        pages += [base, base.rstrip("/") + "/careers", base.rstrip("/") + "/jobs"]
    for p in pages:
        r = http_get(p)
        if r is not None and r.status_code == 200:
            for ats, slug in find_ats_in_text(r.text):
                yield from emit(ats, slug, "detected")

    for slug in slug_guesses(company, website):
        for ats in FETCHERS:
            yield from emit(ats, slug, "guessed")


# ---- matching ----

def _word_regex(words):
    words = sorted({w.lower() for w in words}, key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.I) if words else None


def match_job(job, kw, any_location=False):
    """Return a result dict if the job matches, else None."""
    title = job.title
    if not _word_regex(kw["role_keywords"]).search(title):
        return None
    ex = _word_regex(kw.get("exclude_title_words", []))
    if ex and ex.search(title):
        return None

    loc = job.location.lower()
    loc_hit = next((l for l in kw["locations"] if l in loc), None)
    if job.remote:
        loc_hit = loc_hit or "remote"
    if not loc_hit and not any_location:
        return None

    entry = _word_regex(kw.get("entry_level_words", []))
    is_entry = bool(entry and entry.search(title))

    score = 0
    score += 3 if is_entry else 0
    score += 2 if loc_hit == "pune" else 1 if loc_hit else 0
    score += 1 if re.search(r"\b(genai|gen ai|generative ai|llm|llms|rag)\b", title, re.I) else 0

    return {
        "title": job.title,
        "location": job.location or ("Remote" if job.remote else ""),
        "location_match": loc_hit or "other",
        "level": "entry" if is_entry else "unspecified",
        "url": job.url,
        "score": score,
    }


# ---- run ----

def check_company(row, kw, any_location=False):
    for ats, slug, how in candidates(row):
        jobs = FETCHERS[ats](slug)
        if jobs is not None:
            matches = [m for m in (match_job(j, kw, any_location) for j in jobs) if m]
            return {"ats": ats, "slug": slug, "how": how, "total": len(jobs), "matches": matches}
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--companies", default="companies.csv")
    ap.add_argument("--keywords", default="keywords.json")
    ap.add_argument("--out", default="matches.csv")
    ap.add_argument("--no-board-out", default="no_board.csv")
    ap.add_argument("--any-location", action="store_true", help="keep roles outside your locations too")
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between companies")
    args = ap.parse_args(argv)

    kw = json.loads(Path(args.keywords).read_text())
    with open(args.companies, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("company") or "").strip()]

    all_matches, no_board = [], []
    for i, row in enumerate(rows, 1):
        name = row["company"].strip()
        res = check_company(row, kw, args.any_location)
        if res is None:
            print(f"[{i}/{len(rows)}] {name}: no public board found")
            no_board.append({"company": name, "website": row.get("website", "")})
        else:
            print(f"[{i}/{len(rows)}] {name}: {res['ats']}/{res['slug']} ({res['how']}) "
                  f"- {res['total']} open, {len(res['matches'])} match")
            for m in res["matches"]:
                all_matches.append({
                    "company": name, **m, "ats": res["ats"],
                    "board_source": res["how"],
                    "website": row.get("website", ""),
                    "funding_round": row.get("funding_round", ""),
                    "funding_date": row.get("funding_date", ""),
                    "status": "", "notes": "",
                })
        time.sleep(args.delay)

    all_matches.sort(key=lambda m: -m["score"])
    fields = ["company", "title", "location", "location_match", "level", "score", "url",
              "ats", "board_source", "website", "funding_round", "funding_date", "status", "notes"]
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(all_matches)
    with open(args.no_board_out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["company", "website"])
        w.writeheader()
        w.writerows(no_board)

    print(f"\n{len(all_matches)} matching roles -> {args.out}; "
          f"{len(no_board)} companies without a board -> {args.no_board_out}")
    if any(m["board_source"] == "guessed" for m in all_matches):
        print("Note: board_source=guessed means the board was found by name; open the link and confirm it's the right company.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
