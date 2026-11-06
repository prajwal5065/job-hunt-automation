# job-hunt-automation

Personal tool that automates the research half of the "startup remote job hunt" roadmap:
you pick the companies, the script finds which of them have a matching open role.
Applying and messaging stay manual.

## Pipeline

1. **You:** build `companies.csv` by hand (funding news, VC portfolio pages, Crunchbase profile views). See `companies.example.csv`.
2. **`hiring_checker.py`:** finds each company's public Greenhouse / Lever / Ashby job board and keeps roles that match `keywords.json`.
3. **You:** open the links in `matches.csv`, apply, and track progress in the `status` / `notes` columns.
4. *(next)* contact lookup for companies that have a match, then message drafts.

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
