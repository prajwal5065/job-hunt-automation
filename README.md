# job-hunt-automation

Personal tool that automates the research half of the "startup remote job hunt" roadmap:
you pick the companies, the script finds which of them have a matching open role.
Applying and messaging stay manual.

## Pipeline

1. **You:** build `companies.csv` by hand (funding news, VC portfolio pages, Crunchbase profile views). See `companies.example.csv`.
2. **`hiring_checker.py`:** finds each company's public Greenhouse / Lever / Ashby job board and keeps roles that match `keywords.json`.
3. **You:** open the links in `matches.csv`, apply, and track progress in the `status` / `notes` columns.
4. **`contact_finder.py`:** for the best-scoring matches, looks up a few hiring-relevant contacts via Hunter.io (free plan) into `contacts.csv`.
5. **You:** pick one person per role, write a short specific message, send it yourself, log it in `contacted` / `notes`.
6. **`message_drafter.py`:** writes a short draft per contact into `drafts.csv`. You edit and send it yourself.
7. **`follow_up.py`:** tracks what you sent and drafts the one follow-up when there's no reply after about 6 days.

## Usage

```bash
pip install -r requirements.txt
cp companies.example.csv companies.csv   # then replace with your own list
python hiring_checker.py
```

Outputs:
- `matches.csv`: matching roles, best first (entry-level and Pune/remote roles score higher)
- `no_board.csv`: companies with no detectable public board; check their careers page by hand

Options: `--any-location` (keep roles outside your locations), `--keywords`, `--delay`.

`companies.csv` columns: `company` and `website` are required. `careers_url` helps if you already know it. The rest is carried into the output.

`board_source = guessed` means the board was found by company name, not from a link on their site. Open the link and confirm it's the right company.

## Contact lookup (Hunter free plan)

```bash
export HUNTER_API_KEY=...           # https://hunter.io/api_keys
python contact_finder.py --dry-run  # see who would be looked up, spends nothing
python contact_finder.py            # default: at most 10 lookups (1 credit each)
```

- Companies are looked up best-scoring first. Results are cached in `contacts_cache.json`, so re-runs never spend credits twice on the same domain.
- The free plan is about 50 credits a month, so run the hiring check first and only look up companies that have a real matching role.
- `contacts.csv` ranks recruiters/HR first, then heads of AI/engineering, then founders. Check `verification` before sending.
- Use the contact for one personal, relevant message. Don't bulk-send.

## Message drafts

```bash
cp profile.example.json profile.json     # edit: your name, education, experience, highlights
python message_drafter.py                # plain roadmap template, no API key
python message_drafter.py --llm gemini   # optional: personalise with Gemini (GEMINI_API_KEY, free tier)
```

- One draft per company by default (the top-ranked contact). Use `--per-company 2` for more.
- Add `--applied` only once you've actually applied; otherwise the draft says you're applying.
- The LLM is told to use only facts from `profile.json`, but read every draft before sending. If the LLM call fails or runs long, it falls back to the template.
- Keep `highlights` to things that are true and specific; one good line beats a list.

## Follow-ups

```bash
python follow_up.py sent "Acme"        # you sent the message today -> follow-up due in 6 days
python follow_up.py                    # lists what's due; writes follow_ups.csv with a draft for each
python follow_up.py followed "Acme"    # you sent the follow-up -> never shown as due again
python follow_up.py replied "Acme"     # they answered -> closed
```

- Matches the roadmap: one polite follow-up after 5-7 days, then stop. Change the wait with `--days`.
- `--email` targets one contact if a company has several rows. Company names are matched ignoring case.
- State lives in `drafts.csv` (`sent`, `follow_up_date`, `replied`, `followed_up`), so you can also edit it in a spreadsheet. Dates are YYYY-MM-DD or DD-MM-YYYY.
- Older `drafts.csv` files without the new columns are upgraded automatically.

## Tuning

Edit `keywords.json`: role keywords, title words to exclude, entry-level words, accepted locations.
Titles are matched as whole words, so `ml` won't match "HTML".

## Limits

- Only companies on Greenhouse, Lever or Ashby are covered. Others land in `no_board.csv`.
- Matching uses titles only, so a role needing 3+ years can still appear if the title looks entry-level.
- Roles titled just "Software Engineer" won't match unless you add that to `role_keywords`.

## Tests

```bash
python -m unittest discover -s tests -v
```
