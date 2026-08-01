# YouTube channel scraper

Reads a list of YouTube channel URLs, visits each channel's About page, and
writes a CSV with display name, subscriber count, whether a business email is
listed, and any Instagram / Skool links (with follower and member counts).

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
```

## Run

```bash
python youtube_scraper.py --input youtube_filtered.csv
```

Input can be a CSV with a `Channel URL` column (also accepts `url`, `URL`,
`channel_url`, `Channel`) or a plain `.txt` file with one URL per line.

Useful flags:

| Flag | Default | Notes |
|---|---|---|
| `--input` | `youtube_filtered.csv` | CSV or `.txt` of channel URLs |
| `--output` | `youtube_scraped_details.csv` | Results, written row by row |
| `--concurrency` | `3` | Channels scraped in parallel |
| `--limit` | `0` | Only scrape the first N (handy for a test run) |
| `--delay` | `0.5` | Seconds between channels per worker |
| `--resume` | off | Skip channels already in the output file |
| `--headed` | off | Show the browser window |
| `--browser` | `chromium` | `chromium`, `webkit`, or `firefox` |
| `--executable-path` | auto | Explicit browser binary if Playwright can't find one |

Start with `--limit 5` to confirm YouTube's markup still parses before
committing to a long run.

## Instagram follower counts

Follower counts need a logged-in session. Export your Instagram cookies to a
Playwright storage state file:

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto("https://www.instagram.com/")
    input("Log in, then press Enter...")
    page.context.storage_state(path="instagram_storage_state.json")
    browser.close()
```

Without that file the scraper still runs; it records the Instagram URL and
leaves the follower count blank.

## Resuming

Rows are flushed to the CSV as each channel finishes, so an interrupted run
keeps everything scraped so far:

```bash
python youtube_scraper.py --input youtube_filtered.csv --resume
```

## Output columns

`#`, `Display Name`, `Email`, `YT Channel`, `YT Subscribers`, `IG Account`,
`IG Followers`, `Skool Community`, `Skool Link`, `# of Members`, `Status`

`Status` is `ok`, `no_subscriber_count` (page loaded but no count found —
usually a channel that hides it), or `error: <Type>`.

## Tests

```bash
python test_scraper.py
```

Covers the parsing layer and runs the scraper end to end through a real browser
against a locally served fake About page. No network access required.

## Notes

- Channel data is read from the `ytInitialData` JSON blob in the page rather
  than from DOM selectors. That survives YouTube's element renames and does not
  need the "...more" / "and N more links" panels to be expanded.
- Images, fonts and media are blocked for speed; stylesheets are not, so page
  layout stays intact.
- Keep `--concurrency` modest. Several parallel sessions hitting Instagram from
  one account is the fastest way to get rate limited.
