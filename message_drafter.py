#!/usr/bin/env python3
"""Message drafter.

Reads contacts.csv (from contact_finder.py) and profile.json (about you) and writes
short outreach drafts to drafts.csv. You review, edit and send them yourself.

Default mode fills the roadmap template (no API key needed). With --llm gemini and
GEMINI_API_KEY set, an LLM rewrites it to reference the specific role. The LLM is told
to use only the facts in your profile; always read the draft before sending.
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path

import requests

MAX_WORDS = 120


def first_name(full):
    parts = (full or "").strip().split()
    return parts[0].capitalize() if parts else "there"


def template_message(contact, profile, applied=False):
    hl = (profile.get("highlights") or [""])[0]
    bg = f"I'm a {profile['education']} with {profile['experience']}"
    if hl:
        bg += f", and I {hl}" if not hl.startswith(("I ", "have ", "'ve ")) else f", and {hl}"
    apply_line = ("I've applied for the role and wanted to reach out directly as well."
                  if applied else "I'm applying for the role and wanted to reach out directly as well.")
    lines = [
        f"Hi {first_name(contact.get('name'))},",
        "",
        f"I came across {contact['company']} while researching growing startups, and noticed the "
        f"{contact['role_to_apply']} opening.",
        "",
        f"{bg}. It seems closely aligned with what you're looking for.",
        "",
        f"{apply_line} {profile.get('resume_line', '').strip()}".strip(),
        "",
        "Thanks,",
        profile["name"],
    ]
    return "\n".join(lines)


def build_prompt(contact, profile, applied):
    return (
        "Write a short LinkedIn/email outreach message (under 100 words, plain text, no subject line) "
        "from a student to the person below about a job opening.\n"
        "Rules: use ONLY the facts given here; do not invent skills, projects, numbers or company details; "
        "no flattery, no 'I hope this finds you well'; one specific sentence on why the role fits; "
        f"{'say they have already applied' if applied else 'say they are applying'}; end with the sender's name.\n\n"
        f"Recipient: {contact.get('name') or 'unknown'}, {contact.get('position') or 'unknown title'} at {contact['company']}\n"
        f"Role: {contact['role_to_apply']}\n"
        f"Sender: {profile['name']}, {profile['education']}, {profile['experience']}\n"
        f"Sender highlights: {'; '.join(profile.get('highlights') or [])}\n"
        f"Closing line to include: {profile.get('resume_line', '')}\n"
    )


def gemini_generate(prompt, key, model):
    """Return text or None on any failure. Tests patch this."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    try:
        r = requests.post(url, headers={"x-goog-api-key": key}, timeout=40, json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.6, "maxOutputTokens": 800}})
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (requests.RequestException, KeyError, IndexError, ValueError):
        return None


def draft(contact, profile, applied, llm=None, key="", model=""):
    """Return (subject, body, mode)."""
    subject = f"{contact['role_to_apply']} - {profile['name']}"
    if llm == "gemini" and key:
        text = gemini_generate(build_prompt(contact, profile, applied), key, model)
        if text and 0 < len(text.split()) <= MAX_WORDS:
            return subject, text, "llm"
    return subject, template_message(contact, profile, applied), "template"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--contacts", default="contacts.csv")
    ap.add_argument("--profile", default="profile.json")
    ap.add_argument("--out", default="drafts.csv")
    ap.add_argument("--per-company", type=int, default=1, help="drafts per company (contacts are already ranked)")
    ap.add_argument("--applied", action="store_true", help="say you've already applied (use only if true)")
    ap.add_argument("--llm", choices=["gemini"], help="personalise with an LLM (needs GEMINI_API_KEY)")
    ap.add_argument("--model", default="gemini-2.5-flash")
    args = ap.parse_args(argv)

    try:
        profile = json.loads(Path(args.profile).read_text())
    except OSError:
        sys.exit(f"{args.profile} not found. Copy profile.example.json to profile.json and edit it.")
    for k in ("name", "education", "experience"):
        if not profile.get(k):
            sys.exit(f"profile.json is missing '{k}'.")

    key = os.environ.get("GEMINI_API_KEY", "")
    if args.llm and not key:
        print("GEMINI_API_KEY not set; using the plain template.")

    with open(args.contacts, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("email")]

    seen, out = {}, []
    for r in rows:
        if seen.get(r["company"], 0) >= args.per_company:
            continue
        seen[r["company"]] = seen.get(r["company"], 0) + 1
        subject, body, mode = draft(r, profile, args.applied, args.llm, key, args.model)
        out.append({"company": r["company"], "contact": r.get("name", ""), "position": r.get("position", ""),
                    "email": r["email"], "linkedin": r.get("linkedin", ""), "role": r["role_to_apply"],
                    "apply_url": r.get("apply_url", ""), "subject": subject, "body": body, "mode": mode,
                    "sent": "", "follow_up_date": "", "notes": ""})

    fields = ["company", "contact", "position", "email", "linkedin", "role", "apply_url", "subject", "body",
              "mode", "sent", "follow_up_date", "notes"]
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out)
    print(f"{len(out)} drafts -> {args.out} ({sum(o['mode'] == 'llm' for o in out)} LLM, "
          f"{sum(o['mode'] == 'template' for o in out)} template). Read each one before sending.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
