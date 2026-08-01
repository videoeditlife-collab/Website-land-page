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

Two ways to get channels: discover them from YouTube search, or scrape a list
you already have.

### Discover from search

No input list needed — the scraper searches YouTube and scrapes what it finds:

```bash
python youtube_scraper.py \
  --search-file travel_terms.txt \
  --duration long \
  --min-subscribers 10000 \
  --save-discovered channels_found.txt \
  --output travel_channels.csv
```

`travel_terms.txt` ships with 35 travel/holiday terms weighted toward the US,
UK, Canada and Australia. Start with a couple of terms and `--per-term 10` to
see the shape of the results before running the whole file.

Single term:

```bash
python youtube_scraper.py --search "travel documentary" --duration long
```

Discovery flags:

| Flag | Default | Notes |
|---|---|---|
| `--search TERM` | — | Search term; repeat for several |
| `--search-file` | — | File of terms, one per line |
| `--duration` | — | `long` (20 min+), `medium` (4–20), `short` |
| `--upload-date` | — | `hour`, `today`, `week`, `month`, `year` |
| `--result-type` | — | `channel` restricts to channel results |
| `--sort-by` | relevance | `rating`, `date`, `views` |
| `--scrolls` | `4` | Result pages loaded per term |
| `--per-term` | `25` | Max channels kept per term |
| `--min-subscribers` | `0` | Flags smaller channels rather than dropping them |
| `--save-discovered` | — | Write the discovered URL list to a file |

`--duration long` is the one that matters for long-form: it maps to YouTube's
own 20-minutes-and-over filter.

Region note: YouTube ranks results by the language and region of the browser
session. Running from a US/UK/CA/AU IP with an English locale is what biases
results toward English-speaking creators — the scraper cannot force a country.
For a specific market, either run from that region or lean on the country terms
in `travel_terms.txt`.

### Scrape a list you already have

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

`Status` is `ok`, `below_min_subscribers`, `no_subscriber_count` (page loaded
but no count found — usually a channel that hides it), or `error: <Type>`.

Rows under `--min-subscribers` are written and flagged rather than dropped, so
changing the threshold later does not mean scraping everything again. Filter on
`Status == ok` to get the shortlist.

## Tests

```bash
python test_scraper.py
```

79 assertions covering the parsing layer, the search-filter encoding, and two
end-to-end runs through a real browser against locally served fixture pages —
one scraping a URL list, one going search → discovery → scrape. No network
access required.

## Notes

- Channel data is read from the `ytInitialData` JSON blob in the page rather
  than from DOM selectors. That survives YouTube's element renames and does not
  need the "...more" / "and N more links" panels to be expanded.
- Images, fonts and media are blocked for speed; stylesheets are not, so page
  layout stays intact.
- Keep `--concurrency` modest. Several parallel sessions hitting Instagram from
  one account is the fastest way to get rate limited.
