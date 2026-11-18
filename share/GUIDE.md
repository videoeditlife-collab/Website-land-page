# YouTube Prospect Finder: Complete Guide

This is a set of Python tools for finding YouTube creators who are good
prospects for a paid service, such as video editing, and narrowing them down to
a short list worth contacting. It was built for a solo long-form video editor
looking for creators who:

- post long-form video regularly,
- have an audience that actually watches,
- **sell something of their own** (a course, coaching, a community, digital
  products or merch), which means they have money to pay someone, and
- are individuals, not companies with an in-house team.

The same tools work for any service aimed at YouTube creators. You change
**what you search for** and **which filters you apply**. Nothing is
hard-wired to video editing.

---

## Contents

1. [How it works in one picture](#1-how-it-works-in-one-picture)
2. [What is in the folder](#2-what-is-in-the-folder)
3. [Setup](#3-setup)
4. [Step 1: Write search terms](#4-step-1-write-search-terms)
5. [Step 2: Discover channels](#5-step-2-discover-channels)
6. [Step 3: Drop channels you have already seen, and split into batches](#6-step-3-drop-channels-you-have-already-seen-and-split-into-batches)
7. [Step 4: Score every channel (the ROTI rating)](#7-step-4-score-every-channel-the-roti-rating)
8. [Step 5: Pick the creators who sell something](#8-step-5-pick-the-creators-who-sell-something)
9. [Step 6: Filter by country](#9-step-6-filter-by-country)
10. [Step 7: Check every prospect by hand](#10-step-7-check-every-prospect-by-hand)
11. [Step 8: Top up a short list with near-misses](#11-step-8-top-up-a-short-list-with-near-misses)
12. [Step 9: Keep records so nobody is contacted twice](#12-step-9-keep-records-so-nobody-is-contacted-twice)
13. [Finding contact details](#13-finding-contact-details)
14. [Running everything on GitHub Actions](#14-running-everything-on-github-actions)
15. [Worked example, start to finish](#15-worked-example-start-to-finish)
16. [Tuning the rules](#16-tuning-the-rules)
17. [Troubleshooting](#17-troubleshooting)
18. [What to expect, and lessons learned](#18-what-to-expect-and-lessons-learned)
19. [Responsible use](#19-responsible-use)

---

## 1. How it works in one picture

```
 search terms ──► DISCOVER ──► drop already-seen ──► SCORE ──► PICK SELLERS ──► COUNTRY ──► HAND CHECK ──► final list
 (your .txt)    youtube_      split_new.py          run_lead_   pick_sellers.py  add_country.py  (you)        + records
                scraper.py                          generator.py                                             updated
                                                                       │
                                                                       └──► near_misses.py (to top up a short list)
```

| Stage | Tool | Input | Output | Typical time |
|---|---|---|---|---|
| Discover | `youtube_scraper.py` | a file of search terms | a list of channel URLs, plus a CSV with subscribers, country, cadence and links | 5–10 min to search ~75 terms; 15–60 min to read every channel's About page |
| De-duplicate and split | `split_new.py` | the discovered list, plus your "already seen" files | batches of ~150 new channels | seconds |
| Score | `run_lead_generator.py` | one batch | a scored CSV with a High/Mid/Low rating and 38 columns | ~35–40 min per 150 channels |
| Pick sellers | `pick_sellers.py` | scored CSVs | High-rated creators who sell a product, grouped by product type | seconds |
| Country | `add_country.py` | the picked list, plus discovery CSVs | the list limited to the countries you want | seconds (plus a short scrape for any missing countries) |
| Near-misses | `near_misses.py` | scored CSVs | Mid-rated sellers that failed one test narrowly | seconds |

Every step writes a file, so you can stop after any step, look at the result in
a spreadsheet, and carry on later.

---

## 2. What is in the folder

```
scraper/
  GUIDE.md                 this guide
  README.md                reference for youtube_scraper.py's flags and output columns

  # The pipeline
  youtube_scraper.py       discovery: searches YouTube, reads each channel's About page and Videos tab
  run_lead_generator.py    scoring: reads ~15 recent videos per channel and rates it High / Mid / Low
  lead_generator.py        the scoring rules: thresholds, niche keywords, product detection
  split_new.py             removes channels you have already seen; splits big lists into batches
  pick_sellers.py          pulls out High-rated sellers, grouped by what they sell
  add_country.py           attaches each creator's country and filters by it
  near_misses.py           finds Mid-rated sellers that missed High by one test
  make_shortlist.py        filters a discovery CSV down to Status == ok
  inspect_channels.py      dumps full About-page detail (description, links, join date) for a list
  find_contact.py          finds PUBLISHED business emails on a creator's own websites
  find_editors.py          finds the editors creators credit in their video descriptions

  # Inputs you edit
  *_terms.txt              search-term files, one search per line (examples for many niches)
  example_terms.txt        a three-term file for a quick first test
  niche_broad.txt          niche keywords used by --require-niche at discovery
  holiday_seed_channels.csv  an example input list of known channels

  # Debugging
  diagnose_*.py            print what YouTube's page actually contains when parsing breaks
  test_*.py                automated tests (run these after any change)

  requirements.txt         Python dependencies (Playwright)

.github/workflows/
  scrape-channels.yml      runs discovery on GitHub's servers
  lead-generator.yml       runs scoring on GitHub's servers
  find-contact.yml         runs find_contact.py on GitHub's servers
  find-editors.yml         runs find_editors.py on GitHub's servers
```

All results are written to `scraper/results/` (created on first run) or to the
file names you pass.

---

## 3. Setup

You need **Python 3.10 or newer**. The tools drive a real (headless) Chrome
browser through Playwright, because YouTube has no free API that gives
everything needed here.

### Option A: on your own computer (simplest)

```bash
cd scraper
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
```

Check that it works with a five-channel test:

```bash
python youtube_scraper.py --search "bushcraft shelter build" --per-term 5 \
    --output test.csv
```

Open `test.csv`. You should see five channels with names, subscriber counts and
`Status` = `ok` or a reason. If you get errors, see
[Troubleshooting](#17-troubleshooting).

Run the tests too. They use local fixture pages, so they need no internet:

```bash
python test_scraper.py
python test_lead_generator.py
python test_pick_sellers.py
```

**Where you run it matters.** YouTube ranks search results by the language
and region of the connection. Running from a US, UK, Canadian or Australian
connection with an English browser biases results toward English-speaking
creators. A VPN set to one of those countries works if you are elsewhere.

### Option B: on GitHub Actions (runs unattended, in parallel, for free)

Use this if your own network can't reach YouTube reliably, if you want to run
several searches at once, or if you don't want to leave a laptop running for
an hour. Section [14](#14-running-everything-on-github-actions) covers it in
full. In short:

1. Create a **private** GitHub repository and upload the whole folder,
   including `.github/workflows/`.
2. In the repository, go to **Settings → Actions → General → Workflow
   permissions** and select **Read and write permissions**, so the workflows
   can commit results back.
3. Go to the **Actions** tab, pick a workflow, click **Run workflow**, fill in
   the inputs, and run it.

The workflows install everything themselves on each run. A free GitHub account
includes a generous monthly allowance of Actions minutes for private
repositories, and public repositories are unlimited.

---

## 4. Step 1: Write search terms

This is the single biggest lever on the quality of what you find. Discovery is
only as good as the searches you give it.

A term file is plain text, one YouTube search per line. Lines starting with `#`
are comments:

```text
# my_terms.txt
hot tent winter camping
solo truck camping overnight
bushcraft shelter build
```

The folder ships with tested term files for several niches. Copy one as a
starting point:

| File | Niche |
|---|---|
| `rich_terms.txt`, `rich2_terms.txt`, `rich3_terms.txt`, `rich4_terms.txt` | money: business, investing, real estate, sales, e-commerce, trade-business owners, realtors |
| `survival_terms.txt`, `camping2_terms.txt`, `outdoor_terms.txt`, `solocamp_terms.txt` | camping, survival, bushcraft, prepping, overlanding, backpacking |
| `martial_terms.txt` | martial arts and combat sports |
| `strength_terms.txt` | strongman, powerlifting |
| `photo_terms.txt` | photography and filmmaking |
| `holiday_terms.txt`, `travel_terms.txt` | travel and holidays |
| `vlog_fitness_terms.txt`, `challenge_terms.txt` | vlogs, fitness, challenge formats |
| `agency_terms.txt` | travel businesses (agencies, tour operators) |

### How to write terms that find the right people

1. **Be specific.** Broad terms ("camping", "investing") return the same
   famous channels every time, however far down you scroll. Long, specific
   phrases reach the mid-size creators you want: "hot tent winter camping",
   "dividend portfolio update", "Toronto real estate market update".
2. **Describe the video, not the niche.** Think of the titles your ideal
   prospect actually uses: "I spent 24 hours alone in the woods", "how I built
   a 7 figure business", "my rental property portfolio".
3. **Aim for formats that sell.** Creators who teach usually sell a course or
   coaching. "how to", "for beginners", "step by step", "my strategy" and
   "case study" terms surface sellers far more often than entertainment terms.
4. **Use professions.** Realtors, mortgage brokers, financial advisors, coaches
   and trade-business owners (pressure washing, HVAC, landscaping) use YouTube
   to win clients. They post weekly, earn well per client, and almost all have
   a booking link. In our runs, city-specific real estate ("Austin real
   estate market update") was one of the richest sources of prospects.
5. **Use country-specific words** to reach a country: "ISA" and "UK property"
   for the UK, "TFSA" and "RRSP" for Canada, "superannuation" for Australia,
   "KiwiSaver" for New Zealand, city names for local creators.
6. **Avoid terms a previous pass already used.** The same term returns
   largely the same channels. Each new pass should cover new ground.
7. **70–100 terms per file** is a good size. It yields roughly 600–750
   discovered channels.

### The niche filter (`niche_broad.txt`)

At discovery, `--require-niche` drops any channel whose **name and About
description** contain none of the keywords in the niche file. This is a
substring match, so `camp` matches "camping" and "campfire". When you open a
new niche, add 10–30 words that a creator in it would use to describe their
own channel. `niche_broad.txt` already holds sections for every niche above,
and you can append your own. Keep the words specific enough that unrelated
channels don't match.

---

## 5. Step 2: Discover channels

### The command

```bash
python youtube_scraper.py \
    --search-file my_terms.txt \
    --require-niche --niche-file niche_broad.txt \
    --sort-by date --scrolls 4 --per-term 12 --limit 1200 \
    --min-subscribers 20000 \
    --save-discovered results/discovered_mine.txt \
    --output results/mine_channels.csv
```

What each part does:

| Flag | Meaning | Advice |
|---|---|---|
| `--search-file` | your term file | or use `--search "term"` repeatedly |
| `--sort-by date` | newest videos first | recommended: it reaches past the big channels that dominate relevance ranking, and only finds **active** creators |
| `--scrolls 4` | result pages loaded per term | 3–8; more scrolls means more channels and a slower run |
| `--per-term 12` | max channels kept per term | 8–15 keeps any one term from dominating |
| `--limit 1200` | stop after this many channels in total | a safety cap |
| `--duration long` | only videos of 20+ minutes | optional; use it if you only want long-form creators |
| `--min-subscribers 20000` | flag smaller channels | rows below are **kept but flagged** `below_min_subscribers`, not deleted |
| `--max-subscribers N` | flag bigger channels | leave it off to have no ceiling |
| `--require-niche` + `--niche-file` | flag channels off your niche | see above |
| `--countries "United States,Canada,..."` | flag channels in other countries | channels that publish no country are **kept** |
| `--solo-only` | flag channels that look like businesses or agencies | uses the About page wording |
| `--sells-only` | flag channels with no store, course, coaching or membership link | a rougher version of what scoring does properly |
| `--require-cadence weekly\|biweekly\|monthly` | flag channels that post less often | weekly = 10+ uploads in 90 days |
| `--save-discovered PATH` | also write the plain list of discovered URLs | **always use this**: it is the input to the next step |
| `--discover-only` | stop after saving the discovered list | useful if you only want the list |
| `--resume` | skip channels already in the output CSV | restart an interrupted run where it stopped |
| `--concurrency 3` | channels read in parallel | keep it at 3–4; higher gets rate-limited |
| `--limit 5` | only read the first 5 | a quick test |

`README.md` documents every flag and output column in more detail.

### What you get

1. **`results/discovered_mine.txt`**: one channel URL per line, everything the
   searches found. This feeds Step 3.
2. **`results/mine_channels.csv`**: one row per channel, with display name,
   email (if the page shows one, it usually reads "Email in YouTube Bio",
   which means YouTube hides it behind a sign-in and CAPTCHA), subscribers,
   **Country**, cadence, last upload, uploads in 90 days, Instagram and Skool
   links, a `Type` guess (`solo`, `business`, `unclear`), and **Status**.

`Status` is `ok`, or it names the **first** filter the channel failed:
`below_min_subscribers`, `above_max_subscribers`, `wrong_country`,
`off_niche`, `not_selling`, `looks_like_business`, `cadence_<label>`,
`no_subscriber_count` or `error: <type>`. Nothing is deleted, so you can
loosen a filter later without scraping again. To get only the passes:

```bash
python make_shortlist.py results/mine_channels.csv results/mine_shortlist.csv
```

**Tip:** the discovered list (`discovered_mine.txt`) is written first, within a
few minutes. Reading every About page takes much longer. If you are only
going to score the channels anyway, you can run with `--discover-only` and go
straight to Step 3, then get countries later with `add_country.py` (Step 6).

---

## 6. Step 3: Drop channels you have already seen, and split into batches

A new search always finds some channels an earlier search found. Scoring them
again wastes time, and worse, an old prospect comes back looking new.
`split_new.py` removes every channel named in your exclusion files, then splits
what's left into batches of about 150. One batch scores in about 35–40
minutes, short enough to finish comfortably and easy to run in parallel.

```bash
python split_new.py results/discovered_mine.txt \
    --exclude results/already_scored.txt \
    --exclude "results/*_leads.csv" \
    --prefix results/mine_new --size 150
```

```
689 channels read, 6017 excluded, 565 new
  results/mine_new_1.txt: 142
  results/mine_new_2.txt: 142
  results/mine_new_3.txt: 142
  results/mine_new_4.txt: 139
```

- `--exclude` takes `.txt` lists or CSVs (any of these columns: `Channel Link`,
  `YT Channel`, `channel_url`, `Credited By`, `Handle`, `Channel`), and globs in
  quotes. Repeat it as often as you like.
- Channel URLs are compared after normalising: `www`, `m.`, trailing tabs like
  `/videos` and query strings are ignored. Handles are case-insensitive and
  channel IDs are case-sensitive, which is how YouTube treats them.

---

## 7. Step 4: Score every channel (the ROTI rating)

This is the heart of it. For each channel, `run_lead_generator.py`:

1. reads the About page (description, links, subscriber count, email notice),
2. reads the Videos tab and takes a sample of **15 recent long-form videos**
   (Shorts under 3 minutes and videos less than 14 days old are excluded, so
   views have had time to settle),
3. reads one or more video descriptions (`--descriptions`), where many creators
   put their course or coaching link,
4. works out **what they sell**, **what niche** they are in and how
   consistently they stay in it, **how often** they upload, and **median
   views**,
5. rates them **High**, **Mid** or **Low** for "return on time invested", that
   is, how worthwhile they are to pitch.

```bash
python run_lead_generator.py results/mine_new_1.txt results/mine_1_leads.csv \
    --descriptions 1 --resume
```

| Option | Meaning |
|---|---|
| `source` | `.txt` list or a CSV with a URL column (`Channel URL`, `YT Channel`, `channel_url`, `url`, `Channel`) |
| `destination` | the scored CSV to write |
| `--descriptions N` | video descriptions to read per channel. 1 is the best trade-off; 3 is slower and rarely finds more |
| `--limit N` | only score the first N (for testing) |
| `--resume` | skip channels already in the destination and append. **Always use it**: an interrupted run then continues where it stopped |
| `--use-mean` | rate on average views instead of median (not recommended: one viral video skews the mean) |

Run several batches **at the same time** in separate terminals (or as
separate workflow runs). Each takes 35–40 minutes for ~150 channels.

### The rating rules

A channel is **High** only if **all five** are true:

| Test | Threshold | Why |
|---|---|---|
| Sells a product they own | course, coaching or program, digital product, paid community or membership, merch, or their own store | they have revenue and a reason to invest in better videos |
| Uploads consistently | **10+ uploads in the last 90 days** (about weekly) | they produce enough for steady work |
| Still active | a video in the **last 30 days** | not paused or abandoned |
| Clear niche | **60%+** of recent titles that match any niche match the same one | a focused channel with a defined audience |
| Audience watches | **median views of 3,000+** across the sample | real demand, not a dead subscriber count |

**Low** means no monetization plus at least one weak trait, or three or more
weak traits (2 or fewer uploads in 90 days, stale, no clear niche, median
under 1,000).

**Mid** is everything in between: monetized but missing at least one High
test, or active but with no monetization found.

### How "sells a product" is decided

It looks at the About page, the channel links and the video descriptions:

| Signal | Example | Product type recorded |
|---|---|---|
| Checkout platforms | stan.store, gumroad, kajabi, teachable, thinkific, podia, payhip, whop, samcart, circle.so, shopify | `digital_product`, or `course` / `coaching_or_program` if the wording says so |
| Communities | skool.com, patreon.com, ko-fi memberships | `community_or_membership` |
| Booking links | calendly, cal.com, acuity, tidycal | `coaching_or_program` |
| Own store | links to the creator's own site at `/shop`, `/store`, `/products`, `/collections`, `/merch`, `/pricing`, `/checkout` (not Amazon or other affiliate hosts) | `digital_product` |
| An offer with a price **on the same line** | "My 6-week coaching program, $497" | `course` / `coaching_or_program` / `digital_product` |
| Merch | fourthwall, spring, teespring, represent, "merch" | `merch` |

What does **not** count as selling: affiliate links (Amazon, `geni.us`, LTK),
sponsor reads, free lead magnets, and a price that appears somewhere else in
the text. These still count as **monetized**, which can make a channel Mid but
never High.

Keyword matching is anchored to the **start of a word**, so `camp` matches
"camping" but not "decamp", and `eat` doesn't match "creating". Common false
phrases are stripped first: "of course", "golf course", "loyalty program",
"affiliate program", "business class", "accounting for".

### The output columns

The first 17 columns are a ready-made outreach sheet:

`Creator Name`, `Channel Link`, `Email`, `Do They Sell a Product`, `Product
Type`, `Niche`, `Average Views Per Video`, `Subscriber Count`, **`Value
Rating`**, `Editing Weak Spots`, `Editing Strengths`, `Personality Type /
On-Camera Presence` (you fill in the last three after watching a video), then
pipeline columns for you to fill in: `Outreach Sent`, `Reply Received`,
`Meeting Booked`, `Deal Closed`, `Rate / Retainer Value`.

The helper columns after them are what you filter on:

| Column | Meaning |
|---|---|
| `uploads_90d` | uploads in the last 90 days (bucketed, because YouTube shows "3 weeks ago" rather than a date) |
| `days_since_last_upload` | days since the newest video |
| `median_views` | median views across the sample (rounded the way YouTube rounds, e.g. 12K) |
| `views_trend` | median views of the 5 newest sampled videos ÷ median of the 10 before them. Above 1 means growing, below 1 means slipping |
| `views_to_subs` | average views ÷ subscribers |
| `has_monetization` | any revenue signal, including affiliate links and sponsors |
| `has_sponsors` | sponsor reads found |
| `monetization_signals` | **exactly what was found**, e.g. `skool.com; course; calendly.com`. Read this when checking a prospect |
| `product_price_seen` | a price found near an offer, if any. Treat it as a hint only |
| `niche_consistency` | share of matching titles that agree on the niche (0–1) |
| `niche_evidence` | the first 10 titles, each with the niche its words matched, so you can see **why** it was put in that niche |
| `latest_video_url`, `top_video_url` | links for a quick look |
| `roti_reasons` | in plain words, why it got its rating |
| `needs_review` | true for every High (things like video quality can't be scraped) and for anything suspicious |
| `views_are_rounded`, `dates_are_bucketed` | reminders that these are approximations |
| `scraped_at` | when it was scored (UTC) |

The `Niche` labels are: `travel`, `fitness`, `running_endurance`, `nutrition`,
`finance`, `tech`, `business`, `lifestyle_vlog`, `food`, `photography`,
`filmmaking`, `martial_arts`, `outdoors`. `finance` and `business` count as one
family for consistency, because money channels mix the two.

---

## 8. Step 5: Pick the creators who sell something

```bash
python pick_sellers.py "results/mine_*_leads.csv" \
    --exclude results/sent.txt \
    --output results/mine_picked.csv
```

It keeps **High-rated** rows that sell a product and groups them into tiers,
best first:

| Tier | Product types | What it tells you |
|---|---|---|
| **owned** (Tier 1) | `course`, `coaching_or_program`, `digital_product` | they sell their own knowledge at a price they set: best margins, best prospects |
| **recurring** (Tier 2) | `community_or_membership` (Skool, Patreon, memberships) | steady recurring revenue, usually smaller per person |
| **merch** (Tier 3) | `merch` | the weakest budget signal |

Options:

| Option | Use |
|---|---|
| `--exclude FILE` | leave out channels already reported or contacted (repeatable; globs ok) |
| `--tier owned` | only one tier |
| `--niche outdoors` or `--niche finance,business` | only these niche labels |
| `--min-subs 20000` / `--max-subs 500000` | a subscriber band |
| `--email-only` | only rows with an email listed |
| `--direct-only` | drop addresses at talent agencies and management firms |
| `--limit 50` | the first 50, best first |
| `--output FILE` | write the selection to a CSV (adds `product_tier` and `email_is_agency` columns) |

When the same channel appears in several scored files, **the most recent
score wins**, because the detector only gets more accurate over time.

**Agency emails** are flagged by domain hints (talent, management, mgmt,
media, agency, partnerships and a list of known firms). An agency address
means you'd be pitching a manager, not the creator. It also suggests they
already have a team, and quite possibly an editor. Free mailboxes (gmail,
outlook and so on) are never flagged.

---

## 9. Step 6: Filter by country

The scoring step does not record a country. The discovery CSVs from Step 2 do,
from each channel's About page. `add_country.py` joins them:

```bash
python add_country.py results/mine_picked.csv \
    --countries-from "results/*_channels.csv" \
    --keep "United States,United Kingdom,Canada,Australia,New Zealand,Ireland,South Africa" \
    --output results/mine_english.csv \
    --missing results/need_country.txt
```

It prints what it dropped and which channels have no country on record. For
those, read their About pages (a quick run of around 5 minutes):

```bash
python youtube_scraper.py --input results/need_country.txt \
    --min-subscribers 0 --skip-uploads --output results/probe_channels.csv
```

Then run `add_country.py` again, adding `--countries-from
results/probe_channels.csv`.

Some channels still come back with **no country**, because YouTube only shows
one if the creator set it. By default they are dropped (`--unknown drop`) and
listed. Check them by hand: content that is obviously local (US mortgages,
Chase and Amex cards, Florida camping, UK ISAs) is a reliable clue. Mark any
country you infer that way, for example with `*`.

---

## 10. Step 7: Check every prospect by hand

The scraper is good at counting and bad at judgment. **Every High still needs
a two-minute look**, and these are the checks that mattered most in practice:

1. **Is it a person or a company?** Drop media companies, brands, schools and
   channels with a big team (TED-Ed, Good Mythical Morning, a subscription-box
   company, an "investment education" firm). Names like "X Media", "X
   Academy", "X Education", "X Official" and addresses like `partners@`,
   `team@` or a production company are clues. A couple or a family counts
   as solo.
2. **Is it really in your niche?** Read `niche_evidence`. Search terms leak:
   a "survival" search also returns firearms channels, food channels and
   military history, and a "money" search returns Disney vlogs and watch
   collectors. Drop what doesn't fit, even if it's rated High.
3. **Shorts or long-form?** If **median views are at or above 90% of
   subscribers**, the views probably come from Shorts or paid ads. Open the
   channel and check there are long-form videos to work on. Flag these with
   ⚠️.
4. **Is the product real?** Read `monetization_signals`. A Patreon with three
   members or merch on a print-on-demand site is a weaker signal than a $500
   course. The tier (Step 5) is a start, not the answer.
5. **Do they already have an editor?** Look for "edited by" in video
   descriptions (or run `find_editors.py`, section 13), a team page on their
   site, or a talent-agency email. If they do, that isn't a hard no, but the
   pitch has to be different.
6. **Are they your competitor?** People who teach editing or filmmaking, or
   sell YouTube growth services, edit their own work or sell to the same
   clients as you.
7. **Can you actually help?** Watch two minutes of a recent video: pacing,
   cuts, captions, sound, thumbnails. Note weak spots and strengths in the
   sheet columns, ready for a personal first line in your email.

Archetypes that came up again and again:

| Archetype | Verdict |
|---|---|
| Realtors, loan officers, financial advisors, coaches | excellent: weekly videos, booking links, money to spend |
| Trade-business owners (pressure washing, HVAC, landscaping) documenting their business | very good |
| Course and community sellers (Skool, Kajabi, Stan Store) | very good |
| Sponsor-funded entertainers | rarely High: sponsors aren't a product, so a big channel can still fail |
| Solo campers and adventurers | often fail only on cadence, since every video needs a real trip (see near-misses) |
| Filmmakers, photographers, editing teachers | poor: they edit their own work, or are competitors |

---

## 11. Step 8: Top up a short list with near-misses

High is strict. A creator who posts 9 times a quarter with 40,000 median views
is rated Mid, the same as one posting twice to 400 people, and the first is
often a better prospect than a weak High. If a list comes up short,
`near_misses.py` finds **Mid sellers that failed exactly one High test, by a
small margin**:

```bash
python near_misses.py "results/mine_*_leads.csv" \
    --exclude results/sent.txt \
    --niche outdoors \
    --output results/mine_near.csv
```

| Option | Default | Accepts |
|---|---|---|
| `--uploads-min` | 8 | 8 or 9 uploads in 90 days, against the 10 required |
| `--days-max` | 40 | last upload 31–40 days ago |
| `--niche-min` | 0.5 | niche consistency 0.50–0.59 |
| `--median-min` | 2500 | median views 2,500–2,999 |
| `--niche` | any | comma-separated niche labels |
| `--tier` | all | `owned`, `recurring`, `merch` (repeatable) |

Each row gets a `near_miss` column saying exactly what it missed, e.g. `8
uploads in 90 days (needs 10)`. **Always label near-misses** when you report
them, so nobody mistakes them for full passes. Prefer the ones that missed on
upload frequency or slightly low views. Ones that missed on niche consistency
often post mixed content.

Then run them through Step 6 (country) and Step 7 (hand check) like any other
prospect.

---

## 12. Step 9: Keep records so nobody is contacted twice

Keep two plain-text files of channel URLs, one per line (`#` comments
allowed):

| File | Contains | Used for |
|---|---|---|
| `results/sent.txt` | every creator you have **reported or contacted** | `--exclude` in `pick_sellers.py` and `near_misses.py`, so a new list never repeats anyone |
| `results/already_scored.txt` | every channel that has **been scored** | `--exclude` in `split_new.py`, so nobody is scored twice |

**Update both in the same sitting as every report.** If they fall behind,
creators you already sent start coming back as "new". It's an easy mistake
that's hard to spot.

Adding a final list to `sent.txt`:

```bash
python - <<'EOF'
import csv
rows = csv.DictReader(open('results/final_list.csv'))
with open('results/sent.txt', 'a') as f:
    f.write('# final_list, 2026-11-18\n')
    for r in rows:
        f.write(r['Channel Link'] + '\n')
EOF
```

Adding everything scored to `already_scored.txt`:

```bash
python - <<'EOF'
import csv, glob
with open('results/already_scored.txt', 'a') as f:
    for path in glob.glob('results/mine_*_leads.csv'):
        for r in csv.DictReader(open(path)):
            f.write(r['Channel Link'] + '\n')
EOF
```

Duplicates in these files don't matter, because every tool de-duplicates on
read.

---

## 13. Finding contact details

Most channels show **"Email in YouTube Bio"**. YouTube hides the address
behind a sign-in and a CAPTCHA. You can reveal it by hand on the channel's
About page while signed in (YouTube limits how many per day).

`find_contact.py` looks for a **published business address** on the creator's
own sites instead: their website, store and link hub, including the usual
`/contact` pages:

```bash
python find_contact.py https://www.youtube.com/@Someone https://theirsite.com
```

It reports only what any visitor can see on those pages.

`find_editors.py` reads recent video descriptions and lists editor credits
("edited by @x"). Use it to see who already has an editor, or to find editors
to network with or learn from:

```bash
python find_editors.py results/mine_english.csv results/mine_editors.csv --videos 4
```

---

## 14. Running everything on GitHub Actions

Each workflow installs Python, Playwright and Chrome, runs the tests, does
the work, and **commits the results back** into `scraper/results/`. It also
saves them as a downloadable artifact on the run's page.

### First-time setup

1. Create a **private** repository and push the folder, with
   `.github/workflows/` at the repository root.
2. **Settings → Actions → General → Workflow permissions → Read and write
   permissions → Save.**
3. The workflows also run when certain trigger files are pushed to the branch
   named under `push: branches:` in each file (set to `main`). Change it if
   your branch has a different name. You can ignore this and use the **Run
   workflow** button only.

### Discovery: "Scrape YouTube channels" (`scrape-channels.yml`)

Actions tab → **Scrape YouTube channels** → **Run workflow**:

| Input | Meaning |
|---|---|
| `source` | `custom` to run your own term file; or a preset mode: `rich`, `rich2`, `rich3`, `rich4`, `survival`, `camping2`, `solocamp`, `outdoor`, `photo`, `strength`, `martial`, `challenge`, `broad`, `agency`, `search`; or `probe` to read a list for countries |
| `terms` | (custom only) your term file inside `scraper/`, e.g. `my_terms.txt` |
| `niche_file` | (custom only) niche keyword file, default `niche_broad.txt` |
| `min_subscribers` | default 20000 (use 0 for `probe`) |
| `max_subscribers` | empty means no ceiling |
| `require_cadence` | currently not passed to the scraper by any mode, so leave it. Upload frequency is judged properly at scoring |

So the usual route is: commit `scraper/my_terms.txt`, then run with `source =
custom` and `terms = my_terms.txt`. The run:

1. searches and **saves the discovered list straight away** as
   `results/discovered_my_terms.txt` (within about 5–10 minutes, so a later
   failure can't lose it),
2. reads every channel's About page and commits
   `results/my_terms_channels.csv` (with countries) plus shortlist files.

Two `custom` runs with different term files can run in parallel. Their files
are named after the term file, so they don't overwrite each other.

**Country check (`probe`):** put the URLs in `scraper/results/country_probe.txt`
(one per line), commit, run with `source = probe` and `min_subscribers = 0`.
Countries land in `results/probe_channels.csv`, which each probe overwrites,
so copy it if you want to keep it.

To add a permanent preset of your own, copy one of the blocks in the `case
"$SOURCE" in` section of the workflow (for example `survival)`), give it a new
name, and point `--search-file` at your terms.

### Scoring: "Lead generator" (`lead-generator.yml`)

Run `split_new.py` locally (it is quick and needs no browser), commit the
`*_new_N.txt` parts, then start one run per part:

| Input | Example | Meaning |
|---|---|---|
| `source` | `results/mine_new_1.txt` | the list to score (path inside `scraper/`) |
| `name` | `mine_1_leads` | output name, giving `results/mine_1_leads.csv` |
| `limit` | `0` | 0 = all |
| `descriptions` | `1` | video descriptions read per channel |

Give every part its own `name`, or the runs overwrite each other. Four parts
running in parallel score ~600 channels in about 40 minutes. When they finish,
pull the repository and continue from Step 5 on your own computer.

### Contact lookup and editor credits

- **find-contact.yml** runs when `scraper/.contact-targets` changes: put one URL
  per line (channel, website or store) and push. The findings are committed
  as `results/contact.log`.
- **find-editors.yml** runs `find_editors.py` over a list. Open the file to see
  its inputs.

### Things to know

- Several workflow runs commit to the same branch, so each one **pulls and
  retries** before pushing. Pull before you push your own changes too.
- A run can be cut off if GitHub reclaims the machine (`exit code 143`).
  Scoring uses `--resume`, so just run it again and it continues. Discovery
  saves its list first for the same reason.
- Job logs appear only after a step finishes.

---

## 15. Worked example, start to finish

Goal: **50 camping and survival creators**, English-speaking, selling
something, never contacted before.

```bash
# 1. Terms: two files, so the searches can run in parallel and cover different ground
#    survival_terms.txt  - survival skills, bushcraft, prepping, survival gear, foraging, off-grid
#    camping2_terms.txt  - camping formats, overlanding, backpacking, canoe trips, camp gear

# 2. Discover (or run the workflow with source=custom twice)
python youtube_scraper.py --search-file survival_terms.txt --require-niche \
    --niche-file niche_broad.txt --sort-by date --scrolls 4 --per-term 14 \
    --limit 1400 --save-discovered results/discovered_survival.txt \
    --output results/survival_channels.csv
#    -> 689 discovered

# 3. Drop the already-scored, split
python split_new.py results/discovered_survival.txt \
    --exclude results/already_scored.txt --prefix results/survival_new
#    -> 565 new, 4 parts

# 4. Score the four parts (in parallel)
python run_lead_generator.py results/survival_new_1.txt results/survival_1_leads.csv --descriptions 1 --resume
#    ... _2, _3, _4
#    -> 40 High, 346 Mid, 179 Low

# 5. Pick sellers in the niche
python pick_sellers.py "results/survival_*_leads.csv" --exclude results/sent.txt \
    --output results/survival_picked.csv

# 6. Country
python add_country.py results/survival_picked.csv \
    --countries-from "results/*_channels.csv" \
    --keep "United States,United Kingdom,Canada,Australia,New Zealand,Ireland,South Africa" \
    --output results/survival_english.csv --missing results/need_country.txt
#    (probe any missing, re-run)

# 7. Hand check: 40 High became 16 usable. Dropped 5 companies, 3 firearms
#    channels, 5 food or lifestyle channels, 2 plain fishing channels,
#    a knife collector, a military-history channel, a faceless listicle
#    channel, and 4 outside the target countries.

# 8. Short of 50 after both searches (36 usable Highs), so top up
python near_misses.py "results/*_leads.csv" --exclude results/sent.txt \
    --niche outdoors --output results/outdoor_near.csv
#    -> pick the 14 strongest (mostly 8-9 uploads in 90 days), country-check, hand-check

# 9. Save the final 50, then add all 50 to sent.txt and every scored channel to already_scored.txt
```

---

## 16. Tuning the rules

All thresholds live in the `Config` class at the top of `lead_generator.py`:

| Setting | Default | Meaning |
|---|---|---|
| `sample_size` | 15 | recent long-form videos sampled per channel |
| `shorts_max_seconds` | 180 | videos at or under this length are treated as Shorts and skipped |
| `min_video_age_days` | 14 | newer videos are skipped (their views haven't settled) |
| `high_min_views` | 3000 | median views needed for High |
| `consistent_min_uploads_90d` | 10 | uploads in 90 days needed for High |
| `stale_after_days` | 30 | no upload for longer than this fails High |
| `clear_niche_min` | 0.6 | niche consistency needed for High |
| `low_max_uploads_90d` | 2 | at or under this counts as "rare uploads" for Low |
| `low_max_views` | 1000 | under this counts as "low views" for Low |
| `low_traits_override` | 3 | this many weak traits makes a channel Low even if monetized |

Examples:
- **Smaller creators who post less** (such as podcasters or documentary
  makers): lower `consistent_min_uploads_90d` to 6 and `stale_after_days` to
  45.
- **Bigger budgets only**: raise `high_min_views` to 10000, or use
  `pick_sellers.py --min-subs 100000`.

**Niche keywords** are in `NICHE_KEYWORDS` in `lead_generator.py`. When you
open a new niche, add the words its titles actually use. Matching is anchored
to the start of a word, so `prep` would match "preparation" and "prepping".
Prefer specific words or phrases, and put phrases that mean something else
("of course", "business class") into `NICHE_DECOYS` or `OFFER_DECOYS`.

**Product detection** is in the domain and word lists near the top of the
monetization section: `CHECKOUT_DOMAINS`, `COMMUNITY_DOMAINS`, `MERCH_WORDS`,
`BOOKING_DOMAINS`, `OFFER_WORDS`, `STORE_PATHS`, `AFFILIATE_HOSTS`. Add a
platform there if you see creators using one that isn't detected.

**Agency hints** are in `AGENCY_HINTS` in `pick_sellers.py`. Add a firm's
domain when you spot one slipping through.

**After any change, run the tests** (`python test_lead_generator.py` and
`python test_pick_sellers.py`), then re-score a handful of channels you know,
to check the change does what you expect on live data. Several "fixes" during
development looked right in theory and were wrong on real channels.

---

## 17. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `playwright` not found, or the browser won't start | Chrome not installed for Playwright | `python -m playwright install chromium` (on Linux add `--with-deps`) |
| Every channel shows `error:` or no subscriber count | YouTube changed its page, or blocked the connection | run `python diagnose_about.py https://www.youtube.com/@SomeChannel` and `python diagnose_videos.py https://www.youtube.com/@SomeChannel` to see what the page contains; try again later or from another network |
| Few or no channels discovered | terms too narrow, or the niche filter too strict | test terms with `--search "..." --per-term 5`; widen `niche_broad.txt` |
| The same big channels every time | terms too broad | use long, specific terms and `--sort-by date` |
| Mostly non-English channels | running from a non-English region or browser | run from a US, UK, CA or AU connection or VPN; use country-specific terms; filter with `add_country.py` |
| A run stopped half way | timeout, sleep or interruption | re-run the same command with `--resume` |
| A workflow failed at "Bank" or "Commit" with a merge conflict | two runs wrote the same file | give each run its own `name` / term file; re-run |
| Everyone is rated Mid | they don't sell, or post less than weekly | read `roti_reasons`; see near-misses; consider loosening `Config` for that niche |
| An obvious seller marked "no product" | their link isn't on a known platform, or the price is elsewhere in the text | check `monetization_signals`; add the platform to `CHECKOUT_DOMAINS` |
| Wrong niche label | a title word matched another niche | read `niche_evidence`; add keywords or a decoy phrase |

---

## 18. What to expect, and lessons learned

Typical yields from real runs:

| Niche | Scored | High | Usable after hand check |
|---|---|---|---|
| Money (business, investing, real estate) | 592 | 40 | 30 |
| Money, second pass | 603 | 34 | 21 |
| Money, third pass (trades, reselling) | 507 | 14 | 10 |
| Money, fourth pass (realtors, crypto, owners) | 558 | 15 | 10 |
| Camping formats, overlanding, backpacking | 569 | 23 | 17 |
| Survival, bushcraft, prepping | 565 | 40 | 16 |

So budget roughly **1,000 fresh scored channels for every 50 usable
prospects**, and expect each new pass in the same niche to yield less than
the last, as the best channels get found first.

Lessons that cost time to learn:

- **Products matter more than size.** A 20,000-subscriber realtor with a
  booking link is a better prospect than a 2-million-subscriber entertainer
  paid by sponsors.
- **Search terms leak.** Plan for a third to a half of Highs being off-niche,
  companies or in the wrong country. The hand check isn't optional.
- **"Email in YouTube Bio" is the norm.** Plan to reveal addresses by hand, or
  find them on the creator's own site.
- **Keep the records current.** The one time they fell behind, creators who
  had already been sent came back as new.
- **Don't trust a fix until it has run on live channels.**

---

## 19. Responsible use

- Collect **only published business contact details**: an address a creator
  lists for business enquiries, on YouTube or on their own website. Do not
  dig for personal emails, home addresses, phone numbers or private social
  accounts, and do not contact private individuals such as a creator's
  family or staff.
- Keep the scraping polite: the defaults (3 channels at a time, half a second
  between pages) are deliberate. Don't raise them much.
- YouTube's terms restrict automated access. Use this for modest research
  volumes, at your own risk, and stop if asked to.
- Cold email is regulated (CAN-SPAM in the US, PECR and GDPR in the UK and EU,
  CASL in Canada). Use your real name and business, keep messages relevant,
  honour any request to stop at once, and keep volumes low and personal.
