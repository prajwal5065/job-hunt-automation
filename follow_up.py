#!/usr/bin/env python3
"""Follow-up tracker.

Works on drafts.csv (from message_drafter.py). The roadmap's rule: no reply in 5-7 days,
send ONE polite follow-up, then stop. This script tracks that and drafts the follow-up.

  python follow_up.py sent "Acme"        # you sent the message today -> follow-up due in 6 days
  python follow_up.py                    # list what's due, write follow_ups.csv with drafts
  python follow_up.py followed "Acme"    # you sent the follow-up (never shown as due again)
  python follow_up.py replied "Acme"     # they answered (never shown as due again)

Use --email to target one contact when a company has several rows.
"""
import argparse
import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

EXTRA_COLUMNS = ["sent", "follow_up_date", "replied", "followed_up"]


def parse_date(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        fields = list(rd.fieldnames or [])
        rows = list(rd)
    for c in EXTRA_COLUMNS:  # older drafts.csv files may lack these
        if c not in fields:
            fields.append(c)
            for r in rows:
                r[c] = ""
    return rows, fields


def save(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def select(rows, company, email=None):
    hits = [r for r in rows if r.get("company", "").strip().lower() == company.strip().lower()
            and (not email or r.get("email", "").lower() == email.lower())]
    return hits


def due_date(row, days):
    """follow_up_date if set, else sent + days; None if not sent yet."""
    explicit = parse_date(row.get("follow_up_date"))
    if explicit:
        return explicit
    sent = parse_date(row.get("sent"))
    return sent + timedelta(days=days) if sent else None


def classify(rows, today, days):
    """Return (due, upcoming) lists of (row, due_date). Closed rows (replied/followed up) are skipped."""
    due, upcoming = [], []
    for r in rows:
        if not parse_date(r.get("sent")):
            continue
        if (r.get("replied") or "").strip() or (r.get("followed_up") or "").strip():
            continue
        d = due_date(r, days)
        if d is None:
            continue
        (due if today >= d else upcoming).append((r, d))
    due.sort(key=lambda x: x[1])
    upcoming.sort(key=lambda x: x[1])
    return due, upcoming


def first_name(full):
    parts = (full or "").strip().split()
    return parts[0].capitalize() if parts else "there"


def followup_text(row, sender):
    return "\n".join([
        f"Hi {first_name(row.get('contact'))},",
        "",
        f"Just following up on my note about the {row.get('role', 'open')} role at {row.get('company', 'your company')}. "
        "I know things get busy, so no pressure. I'm still very interested and happy to share anything that would help.",
        "",
        "Thanks,",
        sender,
    ])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--drafts", default="drafts.csv")
    ap.add_argument("--profile", default="profile.json")
    ap.add_argument("--out", default="follow_ups.csv")
    ap.add_argument("--days", type=int, default=6, help="days to wait before following up (roadmap: 5-7)")
    ap.add_argument("--today", help="override today's date, YYYY-MM-DD (for testing)")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("check")
    for name in ("sent", "replied", "followed"):
        p = sub.add_parser(name)
        p.add_argument("company")
        p.add_argument("--email")
    args = ap.parse_args(argv)

    today = parse_date(args.today) if args.today else date.today()
    if today is None:
        sys.exit("--today must look like 2026-11-06")
    rows, fields = load(args.drafts)

    if args.cmd in ("sent", "replied", "followed"):
        hits = select(rows, args.company, args.email)
        if not hits:
            sys.exit(f"No row for company '{args.company}'" + (f" with email {args.email}" if args.email else "") + ".")
        for r in hits:
            if args.cmd == "sent":
                r["sent"] = today.isoformat()
                r["follow_up_date"] = (today + timedelta(days=args.days)).isoformat()
            elif args.cmd == "replied":
                r["replied"] = "y"
            else:
                r["followed_up"] = today.isoformat()
        save(args.drafts, rows, fields)
        msg = {"sent": f"follow-up due {(today + timedelta(days=args.days)).isoformat()}",
               "replied": "closed, no follow-up needed", "followed": "closed, follow-up recorded"}[args.cmd]
        print(f"{args.cmd}: {len(hits)} row(s) for {args.company} - {msg}")
        return 0

    # default: check
    due, upcoming = classify(rows, today, args.days)
    try:
        sender = json.loads(Path(args.profile).read_text())["name"]
    except (OSError, ValueError, KeyError):
        sender = "[Your name]"
    out = [{"company": r["company"], "contact": r.get("contact", ""), "email": r.get("email", ""),
            "linkedin": r.get("linkedin", ""), "role": r.get("role", ""), "sent": r.get("sent", ""),
            "due": d.isoformat(), "subject": "Re: " + r.get("subject", ""), "body": followup_text(r, sender)}
           for r, d in due]
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["company", "contact", "email", "linkedin", "role", "sent", "due", "subject", "body"])
        w.writeheader()
        w.writerows(out)

    print(f"Today {today.isoformat()}: {len(due)} follow-up(s) due, {len(upcoming)} waiting.")
    for r, d in due:
        print(f"  DUE      {r['company']} - {r.get('contact') or r.get('email')} (sent {r['sent']}, due {d})")
    for r, d in upcoming:
        print(f"  waiting  {r['company']} - due {d}")
    if due:
        print(f"Drafts -> {args.out}. Send one follow-up, then run: follow_up.py followed \"<company>\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
