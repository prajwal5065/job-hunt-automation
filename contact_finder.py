#!/usr/bin/env python3
"""Contact finder.

Reads matches.csv (output of hiring_checker.py), and for the companies with the
best-scoring open roles looks up a few hiring-relevant contacts with the Hunter.io
Domain Search API (free plan: ~50 credits/month). Writes contacts.csv.

You still read the role, pick ONE person and write the message yourself.

Setup: export HUNTER_API_KEY=...   (https://hunter.io/api_keys)
"""
import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

HUNTER = "https://api.hunter.io/v2"
TIMEOUT = 20

# (regex on job title, points). Highest total wins; small startups: founders count.
TITLE_POINTS = [
    (r"\b(talent|recruit\w*|hiring|people|human resources|hr)\b", 5),
    (r"\b(head|director|vp|manager|lead)\b.*\b(ai|ml|machine learning|data|engineering)\b", 4),
    (r"\b(ai|ml|machine learning|data|engineering)\b.*\b(head|director|vp|manager|lead)\b", 4),
    (r"\b(cto|chief technology)\b", 3),
    (r"\b(co-?founder|founder|ceo|chief executive)\b", 3),
    (r"\b(engineer|scientist|developer)\b", 1),
]


class RateLimited(Exception):
    pass


def api_get(path, **params):
    """Return (status_code, json_or_None). Tests patch this."""
    try:
        r = requests.get(f"{HUNTER}{path}", params=params, timeout=TIMEOUT)
    except requests.RequestException:
        return 0, None
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, None


def domain_of(website):
    w = (website or "").strip()
    if not w:
        return ""
    host = urlparse(w if "//" in w else f"//{w}").netloc or w
    return re.sub(r"^www\.", "", host.lower()).split("/")[0]


def credits_left(key):
    """Remaining Hunter credits, or None if the account call doesn't say."""
    status, data = api_get("/account", api_key=key)
    if status != 200 or not isinstance(data, dict):
        return None
    req = (data.get("data") or {}).get("requests") or {}
    for bucket in ("credits", "searches"):
        b = req.get(bucket)
        if isinstance(b, dict) and "available" in b:
            return max(int(b["available"]) - int(b.get("used", 0)), 0) if b["available"] is not None else None
    return None


def domain_search(domain, key, limit=10):
    status, data = api_get("/domain-search", domain=domain, api_key=key, limit=limit)
    if status in (401, 403):
        sys.exit("Hunter rejected the API key (401/403). Check HUNTER_API_KEY.")
    if status == 429:
        raise RateLimited()
    if status != 200 or not isinstance(data, dict):
        return []
    out = []
    for e in (data.get("data") or {}).get("emails", []) or []:
        out.append({
            "name": " ".join(x for x in (e.get("first_name"), e.get("last_name")) if x),
            "position": e.get("position") or "",
            "email": e.get("value") or "",
            "confidence": e.get("confidence") or "",
            "verification": ((e.get("verification") or {}).get("status")) or "",
            "linkedin": e.get("linkedin") or "",
            "department": e.get("department") or "",
        })
    return out


def contact_score(c):
    pos = (c.get("position") or "").lower()
    score = max((pts for pat, pts in TITLE_POINTS if re.search(pat, pos)), default=0)
    if (c.get("department") or "").lower() == "hr":
        score = max(score, 5)
    try:
        score += float(c.get("confidence") or 0) / 100  # tie-breaker
    except ValueError:
        pass
    return score


def rank(contacts, n=3):
    ranked = sorted((c for c in contacts if c.get("email")), key=contact_score, reverse=True)
    return ranked[:n]


def load_cache(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--matches", default="matches.csv")
    ap.add_argument("--out", default="contacts.csv")
    ap.add_argument("--cache", default="contacts_cache.json")
    ap.add_argument("--max-lookups", type=int, default=10, help="max Hunter lookups this run (1 credit each)")
    ap.add_argument("--per-company", type=int, default=3)
    ap.add_argument("--min-score", type=int, default=0, help="only companies whose best role scores at least this")
    ap.add_argument("--dry-run", action="store_true", help="show which companies would be looked up, spend nothing")
    args = ap.parse_args(argv)

    with open(args.matches, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # best role per company, best company first
    best = {}
    for r in rows:
        try:
            sc = int(r.get("score") or 0)
        except ValueError:
            sc = 0
        if sc < args.min_score:
            continue
        cur = best.get(r["company"])
        if cur is None or sc > cur["_score"]:
            best[r["company"]] = {**r, "_score": sc}
    companies = sorted(best.values(), key=lambda r: -r["_score"])

    cache = load_cache(args.cache)
    todo = []
    for r in companies:
        d = domain_of(r.get("website"))
        if not d:
            print(f"skip {r['company']}: no website in matches.csv")
            continue
        r["_domain"] = d
        if d not in cache:
            todo.append(r)

    budget = args.max_lookups
    key = os.environ.get("HUNTER_API_KEY", "")
    if args.dry_run:
        print(f"{len(companies)} companies with matches, {len(companies) - len(todo)} already cached.")
        for r in todo[:budget]:
            print(f"would look up: {r['company']} ({r['_domain']}) - best role: {r['title']}")
        return 0
    if not key:
        sys.exit("Set HUNTER_API_KEY first (free key: https://hunter.io/api_keys).")

    left = credits_left(key)
    if left is not None:
        print(f"Hunter credits left: {left}")
        budget = min(budget, left)
        if left == 0:
            print("No credits left; writing contacts from cache only.")

    for r in todo[:budget]:
        try:
            cache[r["_domain"]] = domain_search(r["_domain"], key)
        except RateLimited:
            print("Hunter rate/credit limit hit; stopping early.")
            break
        print(f"looked up {r['company']} ({r['_domain']}): {len(cache[r['_domain']])} contacts")
        time.sleep(1)
    Path(args.cache).write_text(json.dumps(cache, indent=1))

    fields = ["company", "role_to_apply", "apply_url", "name", "position", "email", "confidence",
              "verification", "linkedin", "contacted", "notes"]
    n_rows, no_contacts = 0, []
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in companies:
            d = r.get("_domain")
            top = rank(cache.get(d, []), args.per_company) if d else []
            if not top:
                no_contacts.append(r["company"])
            for c in top:
                w.writerow({"company": r["company"], "role_to_apply": r["title"], "apply_url": r["url"],
                            **{k: c[k] for k in ("name", "position", "email", "confidence", "verification", "linkedin")},
                            "contacted": "", "notes": ""})
                n_rows += 1
    print(f"\n{n_rows} contacts -> {args.out}")
    if no_contacts:
        print("No contacts yet (not looked up, or none found): " + ", ".join(no_contacts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
