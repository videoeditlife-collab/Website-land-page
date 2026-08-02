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
  --search-file holiday_terms.txt \
  --duration long \
  --min-subscribers 10000 --max-subscribers 200000 \
  --sort-by date \
  --scrolls 8 \
  --save-discovered channels_found.txt \
  --output holiday_channels.csv
```

Two term files ship with the scraper:

- `holiday_terms.txt` — package holidays, resort and cruise reviews, deal
  hunting, sit-down holiday guides. The "holiday expert" style.
- `travel_terms.txt` — travel documentary, backpacking, van life, road trips.

Start with a couple of terms and `--per-term 10` to see the shape of the
results before running a whole file.

### Targeting mid-size channels

YouTube ranks by relevance, which means broad terms return the same handful of
million-subscriber channels no matter how far you scroll. `--min-subscribers`
and `--max-subscribers` filter *after* scraping, so they narrow the output but
do not make search surface smaller creators. Three levers actually do:

- **Long-tail terms.** "jet2 holiday review" reaches mid-size channels that
  "travel vlog" never will. Both term files are written this way.
- **`--sort-by date`.** Recency ordering pushes past the established channels
  that dominate relevance ranking.
- **More scrolls.** `--scrolls 8` digs further down each result page.

Expect a low hit rate on a first pass — that is the nature of the band. Scrape
wide, then filter on `Status == ok`.

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
| `--max-subscribers` | `0` | Flags larger channels rather than dropping them |
| `--require-cadence` | — | `weekly`, `biweekly` or `monthly` upload consistency |
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

## Upload cadence

Every channel's Videos tab is checked so you can tell an active creator from an
abandoned one. Three columns come out of it: `Cadence`, `Last Upload (days)`
and `Uploads (90d)`.

| Label | Meaning |
|---|---|
| `weekly` | 10+ uploads in the last 90 days |
| `biweekly` | 5–9 in the last 90 days |
| `monthly` | 2–4 in the last 90 days |
| `sporadic` | 1 or fewer in the last 90 days |
| `inactive` | Nothing for 90–180 days |
| `dormant` | Nothing for over 180 days |
| `unknown` | No dated videos found |

`--require-cadence weekly|biweekly|monthly` flags anything less consistent as
`cadence_<label>`. It's applied after the subscriber band, so `Status` names the
first reason a channel was set aside.

```bash
python youtube_scraper.py --input holiday_seed_channels.csv \
  --min-subscribers 10000 --max-subscribers 200000 \
  --require-cadence monthly
```

Two caveats. YouTube dates uploads relatively ("3 weeks ago"), so cadence is
measured to the nearest bucket, not the day — reliable for separating weekly
from dormant, not for exact intervals. And this loads a second page per channel;
`--skip-uploads` turns it off if you want a faster first pass.

## Output columns

`#`, `Display Name`, `Email`, `YT Channel`, `YT Subscribers`, `Cadence`,
`Last Upload (days)`, `Uploads (90d)`, `IG Account`, `IG Followers`,
`Skool Community`, `Skool Link`, `# of Members`, `Status`

`Status` is `ok`, `below_min_subscribers`, `above_max_subscribers`,
`cadence_<label>`, `no_subscriber_count` (page loaded but no count found — usually a channel that
hides it), or `error: <Type>`.

Rows outside the subscriber range are written and flagged rather than dropped,
so moving the bounds later does not mean scraping everything again. Filter on
`Status == ok` to get the shortlist.

## Tests

```bash
python test_scraper.py
```

106 assertions covering the parsing layer, cadence classification, the
search-filter encoding, and two end-to-end runs through a real browser against
locally served fixture pages — one scraping a URL list, one going search →
discovery → scrape. No network access required.

## Notes

- Channel data is read from the `ytInitialData` JSON blob in the page rather
  than from DOM selectors. That survives YouTube's element renames and does not
  need the "...more" / "and N more links" panels to be expanded.
- Images, fonts and media are blocked for speed; stylesheets are not, so page
  layout stays intact.
- Keep `--concurrency` modest. Several parallel sessions hitting Instagram from
  one account is the fastest way to get rate limited.
