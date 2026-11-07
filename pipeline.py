#!/usr/bin/env python3
"""One-command runner for the whole pipeline, plus a status summary.

  python pipeline.py run          # companies.csv -> matches.csv -> contacts.csv -> drafts.csv
  python pipeline.py run --dry-run   # same, but only previews who would be looked up in Hunter
  python pipeline.py status       # counts at every stage + follow-ups due

Run it from the project folder. Sending messages and applying stay manual.
"""
import argparse
import csv
import os
import sys
from datetime import date
from pathlib import Path

import contact_finder
import follow_up
import hiring_checker
import message_drafter

FILES = {
    "companies": "companies.csv",
    "matches": "matches.csv",
    "contacts": "contacts.csv",
    "drafts": "drafts.csv",
}


def read_rows(path):
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except OSError:
        return None


def status(today=None, days=6, files=None):
    """Return counts for every stage (None where the file doesn't exist yet)."""
    files = files or FILES
    today = today or date.today()
    companies, matches = read_rows(files["companies"]), read_rows(files["matches"])
    contacts, drafts = read_rows(files["contacts"]), read_rows(files["drafts"])
    out = {
        "companies": None if companies is None else len([r for r in companies if (r.get("company") or "").strip()]),
        "companies_with_matches": None if matches is None else len({r["company"] for r in matches}),
        "matching_roles": None if matches is None else len(matches),
        "contacts": None if contacts is None else len(contacts),
        "drafts": None if drafts is None else len(drafts),
    }
    if drafts is not None:
        for r in drafts:
            for c in follow_up.EXTRA_COLUMNS:
                r.setdefault(c, "")
        due, waiting = follow_up.classify(drafts, today, days)
        out.update({
            "sent": sum(1 for r in drafts if follow_up.parse_date(r.get("sent"))),
            "replied": sum(1 for r in drafts if (r.get("replied") or "").strip()),
            "followed_up": sum(1 for r in drafts if (r.get("followed_up") or "").strip()),
            "follow_ups_due": len(due),
            "waiting": len(waiting),
        })
    return out


def print_status(s):
    def n(k):
        return "-" if s.get(k) is None else s[k]
    print(f"Companies listed:            {n('companies')}")
    print(f"Companies with a matching role: {n('companies_with_matches')}  ({n('matching_roles')} roles)")
    print(f"Contacts found:              {n('contacts')}")
    print(f"Drafts written:              {n('drafts')}")
    print(f"Sent / replied / followed up: {n('sent')} / {n('replied')} / {n('followed_up')}")
    print(f"Follow-ups due now:          {n('follow_ups_due')}   (waiting: {n('waiting')})")


def run(args):
    if not Path(FILES["companies"]).exists():
        sys.exit("companies.csv not found. Build it by hand first (see companies.example.csv).")

    print("== 1/3 hiring check ==")
    hc_args = ["--companies", FILES["companies"], "--out", FILES["matches"]]
    if args.any_location:
        hc_args.append("--any-location")
    hiring_checker.main(hc_args)

    matches = read_rows(FILES["matches"]) or []
    if not matches:
        print("\nNo matching roles this time. Add more companies or loosen keywords.json, then run again.")
        return 0

    print("\n== 2/3 contacts ==")
    if not args.dry_run and not os.environ.get("HUNTER_API_KEY"):
        print("HUNTER_API_KEY is not set, so stopping here. Set it (hunter.io/api_keys) and run again;")
        print("the hiring check is cheap to repeat and contact lookups are cached.")
        return 0
    cf_args = ["--matches", FILES["matches"], "--out", FILES["contacts"],
               "--max-lookups", str(args.max_lookups), "--min-score", str(args.min_score)]
    if args.dry_run:
        cf_args.append("--dry-run")
    contact_finder.main(cf_args)
    if args.dry_run:
        print("\nDry run: nothing spent. Run without --dry-run to look these up.")
        return 0

    print("\n== 3/3 drafts ==")
    if not Path("profile.json").exists():
        print("profile.json not found. Copy profile.example.json to profile.json, edit it, and run again.")
        return 0
    md_args = ["--contacts", FILES["contacts"], "--out", FILES["drafts"]]
    if args.llm:
        md_args += ["--llm", args.llm]
    if args.applied:
        md_args.append("--applied")
    message_drafter.main(md_args)

    print("\nDone. Review drafts.csv, send what you like, then mark it:")
    print('  python follow_up.py sent "<company>"')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run all three automated steps")
    r.add_argument("--dry-run", action="store_true", help="preview Hunter lookups, spend nothing")
    r.add_argument("--max-lookups", type=int, default=10)
    r.add_argument("--min-score", type=int, default=0)
    r.add_argument("--any-location", action="store_true")
    r.add_argument("--llm", choices=["gemini"])
    r.add_argument("--applied", action="store_true", help="drafts say you've already applied (only if true)")
    sub.add_parser("status", help="counts at each stage and follow-ups due")
    args = ap.parse_args(argv)

    if args.cmd == "status":
        print_status(status())
        return 0
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
