#!/usr/bin/env python3
"""
Collect Lead Generator rows by scraping.

    python run_lead_generator.py results/creators_around_100k.csv leads.csv
    python run_lead_generator.py channels.txt leads.csv --limit 20

Reads each channel's About page and Videos tab, builds the sample the spec
defines, scores it, and writes the sheet columns followed by the helpers.
"""

import argparse
import asyncio
import csv
import re
import sys

from playwright.async_api import async_playwright

from youtube_scraper import (
    USER_AGENT, all_external_links, channel_about_url, description_from_html,
    extract_json_blob, parse_count, parse_relative_age, read_input,
    subscribers_from_data, channel_name_from_html, walk_objects, field_value,
)
from find_editors import description_from_watch
from lead_generator import (
    ALL_COLUMNS, Config, Creator, classify_niche, detect_monetization,
    rate_roti, to_row, view_stats,
)

# YouTube writes the count out in words in the accessibility label:
# "111 thousand views", not "111K views". A regex expecting the number next to
# "views" only ever matched counts small enough to print in full, which is why
# exactly the three-digit channels came through.
VIEWS_RE = re.compile(
    r'([\d.,]+)\s*(thousand|million|billion|[KMB])?\s+views?', re.IGNORECASE)

_WORD_MAGNITUDE = {'thousand': 'K', 'million': 'M', 'billion': 'B'}

# The title label carries the duration on the end: "Some Title 26 minutes".
_TRAILING_DURATION = re.compile(
    r'\s+\d+\s+(hours?|minutes?|seconds?)(,\s*\d+\s+(minutes?|seconds?))*$',
    re.IGNORECASE)


def parse_views(text):
    """Views from any of the forms YouTube publishes."""
    match = VIEWS_RE.search(text or '')
    if not match:
        return None
    number = match.group(1)
    suffix = (match.group(2) or '')
    suffix = _WORD_MAGNITUDE.get(suffix.lower(), suffix)
    return parse_count(f"{number}{suffix} views", require_word='view')


def clean_title(text):
    return _TRAILING_DURATION.sub('', (text or '').strip()).strip()
DURATION_RE = re.compile(r'^(\d{1,2}):(\d{2})(?::(\d{2}))?$')


def duration_seconds(text):
    match = DURATION_RE.match((text or '').strip())
    if not match:
        return None
    a, b, c = match.groups()
    if c is None:
        return int(a) * 60 + int(b)
    return int(a) * 3600 + int(b) * 60 + int(c)


# Keys that actually carry display text. Without this the longest string in a
# lockup is clickTrackingParams - an ~88 character base64 blob - so every title
# came out as tracking gibberish, no title matched a niche keyword, and every
# channel fell back to the 0.5 description score that sits just under the 0.6
# clear-niche threshold.
TEXT_KEYS = {'label', 'content', 'title', 'simpleText', 'text',
             'accessibilityLabel', 'headline'}


def strings_in(node, keys=None):
    for obj in walk_objects(node):
        for key, value in obj.items():
            if keys is not None and key not in keys:
                continue
            if isinstance(value, str):
                yield value


def videos_from_grid(data):
    """
    One record per video on the Videos tab.

    Fields are picked out of each lockup's own subtree by shape - a duration
    looks like 12:34, a view count ends in "views", an age ends in "ago" -
    rather than by a fixed path, because the paths move. The Videos tab moved
    from videoRenderer to lockupViewModel once already during this project.
    """
    out = []
    for obj in walk_objects(data or {}):
        lockup = obj.get('lockupViewModel')
        if not isinstance(lockup, dict):
            continue
        vid = lockup.get('contentId')
        if not isinstance(vid, str):
            continue

        title, views, age_days, seconds = '', None, None, None
        for text in strings_in(lockup, TEXT_KEYS):
            stripped = text.strip()
            if not stripped:
                continue
            if seconds is None:
                seconds = duration_seconds(stripped)
            if views is None:
                views = parse_views(stripped)
            if age_days is None and stripped.lower().endswith('ago'):
                age_days = parse_relative_age(stripped)
            # The longest plain string with no metadata markers is the title.
            if (len(stripped) > len(title) and ' views' not in stripped.lower()
                    and not stripped.lower().endswith('ago')
                    and not DURATION_RE.match(stripped)):
                title = clean_title(stripped)

        out.append({'id': vid, 'title': title, 'views': views,
                    'age_days': age_days, 'seconds': seconds})

        if len(out) >= 40:
            break
    return out


def build_sample(videos, cfg):
    """The spec's sample: long form, not live, aged, newest first, capped."""
    kept = []
    for v in videos:
        # A video with no duration shown cannot be classified, so keep it
        # rather than silently dropping a long form upload.
        if v['seconds'] is not None and v['seconds'] <= cfg.shorts_max_seconds:
            continue
        if v['age_days'] is not None and v['age_days'] < cfg.min_video_age_days:
            continue
        kept.append(v)
    return kept[:cfg.sample_size]


async def read(page, url, require=None, attempts=2):
    """
    Fetch a page, and when a marker is required, make sure it actually arrived.

    domcontentloaded fires before a 2.8MB channel page has finished streaming.
    og:title is in the head and lands immediately; ytInitialData sits far down
    the document. Reading too early returns a page with the name present and
    the entire payload missing, which is how 106 creators were scored on zeros
    without a single load error.
    """
    for attempt in range(attempts):
        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            await page.wait_for_timeout(1500 + attempt * 2500)
            html = await page.content()
        except Exception as exc:
            print(f"      load failed: {exc}", file=sys.stderr)
            continue

        if require and extract_json_blob(html, require) is None:
            print(f"      {require} missing, retrying with a longer wait",
                  file=sys.stderr)
            continue
        return html

    return ''


async def collect(page, channel_url, cfg, read_descriptions):
    c = Creator(channel_url=channel_url)

    about = await read(page, channel_about_url(channel_url),
                       require='ytInitialData')
    if not about:
        return None
    data = extract_json_blob(about, 'ytInitialData')
    if data is None:
        print("      no ytInitialData after retries - skipping rather than "
              "scoring on zeros", file=sys.stderr)
        return None

    c.creator_name = channel_name_from_html(about, data) or ''
    text, count = subscribers_from_data(data)
    c.subscriber_count = count or 0
    c.channel_id = field_value(data, 'externalId', 'channelId') or ''
    channel_description = description_from_html(about)
    links = all_external_links(data)

    videos_html = await read(
        page, channel_about_url(channel_url).rsplit('/about', 1)[0] + '/videos',
        require='ytInitialData')
    videos = videos_from_grid(extract_json_blob(videos_html, 'ytInitialData'))
    sample = build_sample(videos, cfg)
    c.sample_size_used = len(sample)

    if sample:
        c.latest_video_url = f"https://www.youtube.com/watch?v={sample[0]['id']}"
        with_views = [v for v in sample if v['views']]
        if with_views:
            top = max(with_views, key=lambda v: v['views'])
            c.top_video_url = f"https://www.youtube.com/watch?v={top['id']}"

    c.avg_views, c.median_views, c.views_trend = view_stats(
        [v['views'] for v in sample if v['views']])

    ages = [v['age_days'] for v in videos if v['age_days'] is not None]
    if ages:
        c.days_since_last_upload = round(min(ages))
    c.uploads_90d = sum(1 for v in videos
                        if v['age_days'] is not None and v['age_days'] <= 90
                        and (v['seconds'] is None
                             or v['seconds'] > cfg.shorts_max_seconds))

    c.niche, c.niche_consistency = classify_niche(
        [v['title'] for v in sample], channel_description)

    # Monetization: channel description and links first, then a few video
    # descriptions, which is where sponsor reads and offer links usually sit.
    blob = channel_description
    if read_descriptions:
        for v in sample[:read_descriptions]:
            watch = await read(page,
                               f"https://www.youtube.com/watch?v={v['id']}")
            if watch:
                blob += "\n" + description_from_watch(watch)
            await asyncio.sleep(0.3)

    found = detect_monetization(blob, links)
    c.sells_product = found['sells_product']
    c.product_type = found['product_type']
    c.has_monetization = found['has_monetization']
    c.has_sponsors = found['has_sponsors']
    c.monetization_signals = found['monetization_signals']
    c.product_price_seen = found['product_price_seen']

    email, source = find_email(blob, channel_description)
    c.email, c.email_source = email, source

    return c


BUSINESS_NEAR = re.compile(
    r'(business|inquir|enquir|collab|contact|booking|work with|partnership)',
    re.IGNORECASE)
EMAIL_RE = re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')
OBFUSCATED_RE = re.compile(
    r'([A-Za-z0-9._%+\-]+)\s*[\[(]?\s*at\s*[\])]?\s*([A-Za-z0-9.\-]+)'
    r'\s*[\[(]?\s*dot\s*[\])]?\s*([A-Za-z]{2,})', re.IGNORECASE)


def find_email(blob, channel_description):
    """
    Only addresses published in plain text, per the spec.

    An address from a video description is accepted only when it sits near
    business wording - sponsor support addresses are common there and are not
    the creator's.
    """
    for match in EMAIL_RE.finditer(channel_description or ''):
        return match.group(0), 'channel_description'

    match = OBFUSCATED_RE.search(channel_description or '')
    if match:
        return f"{match.group(1)}@{match.group(2)}.{match.group(3)}", 'channel_description'

    for line in (blob or '').splitlines():
        if not BUSINESS_NEAR.search(line):
            continue
        match = EMAIL_RE.search(line)
        if match:
            return match.group(0), 'video_description'

    return '', 'manual'


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('destination')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--descriptions', type=int, default=3,
                        help='Video descriptions to read per channel for '
                             'monetization signals (0 to skip)')
    parser.add_argument('--use-mean', action='store_true',
                        help="Rate on the mean, the lesson's exact rule")
    args = parser.parse_args()

    cfg = Config(use_median=not args.use_mean)

    urls = read_input(args.source)
    if not urls:
        return 1
    if args.limit:
        urls = urls[:args.limit]

    rows = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await (await browser.new_context(user_agent=USER_AGENT)).new_page()

        for index, url in enumerate(urls, 1):
            print(f"[{index}/{len(urls)}] {url}", file=sys.stderr)
            try:
                c = await collect(page, url, cfg, args.descriptions)
            except Exception as exc:
                print(f"      error: {exc}", file=sys.stderr)
                continue
            if not c:
                continue

            roti, reasons, review = rate_roti(c, cfg)
            print(f"      {c.creator_name} | {roti} | "
                  f"{c.subscriber_count:,} subs | med {c.median_views:,} views | "
                  f"{c.uploads_90d} uploads/90d | {c.niche or 'no niche'} "
                  f"({c.niche_consistency}) | sells={c.sells_product}",
                  file=sys.stderr)
            rows.append(to_row(c, roti, reasons, review, cfg))

        await browser.close()

    order = {'High': 0, 'Mid': 1, 'Low': 2}
    rows.sort(key=lambda r: (order.get(r['Value Rating'], 3),
                             -int(r['median_views'] or 0)))

    with open(args.destination, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=ALL_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    counts = {}
    for r in rows:
        counts[r['Value Rating']] = counts.get(r['Value Rating'], 0) + 1
    print(f"\n{len(rows)} leads -> {args.destination}  {counts}", file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
