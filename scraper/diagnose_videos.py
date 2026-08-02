#!/usr/bin/env python3
"""
Diagnostic: report how a channel's Videos tab actually encodes upload dates.

The cadence parser found nothing on live pages, so this dumps the real shape of
the payload rather than guessing at it.

    python diagnose_videos.py https://www.youtube.com/@SomeChannel
"""

import asyncio
import re
import sys
from collections import Counter

from playwright.async_api import async_playwright

from youtube_scraper import (
    USER_AGENT,
    channel_about_url,
    extract_json_blob,
    walk_objects,
    _RELATIVE_AGE_RE,
)


async def main():
    if len(sys.argv) < 2:
        print("usage: diagnose_videos.py <channel-url>")
        return 1

    videos_url = channel_about_url(sys.argv[1]).rsplit('/about', 1)[0] + '/videos'
    print(f"Loading {videos_url}\n")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        page = await context.new_page()
        await page.goto(videos_url, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(3000)
        html = await page.content()
        await browser.close()

    print(f"page bytes: {len(html)}")

    for marker in ('ytInitialData', 'lockupViewModel', 'videoRenderer',
                   'richItemRenderer', 'publishedTimeText', 'contentId',
                   'lockupMetadataViewModel', 'metadataParts'):
        print(f"  {marker:26} occurrences in html: {html.count(marker)}")

    data = extract_json_blob(html, 'ytInitialData')
    print(f"\nytInitialData parsed: {data is not None}")
    if not data:
        matches = _RELATIVE_AGE_RE.findall(html)
        print(f"raw 'N unit ago' matches in html: {len(matches)}")
        print(f"sample: {matches[:10]}")
        return 0

    # Which keys hold a relative date, and what sits alongside them?
    date_keys = Counter()
    parent_shapes = Counter()
    id_like = Counter()
    samples = []

    for obj in walk_objects(data):
        for key, value in obj.items():
            if isinstance(value, str) and _RELATIVE_AGE_RE.search(value):
                date_keys[key] += 1
                parent_shapes[tuple(sorted(obj.keys()))[:12]] += 1
                if len(samples) < 8:
                    samples.append((key, value, sorted(obj.keys())[:14]))

        for key in ('videoId', 'contentId', 'entityId'):
            if isinstance(obj.get(key), str):
                id_like[key] += 1

    print(f"\nkeys whose value contains a relative date:")
    for key, count in date_keys.most_common(15):
        print(f"  {key:30} {count}")

    print(f"\nid-ish keys present:")
    for key, count in id_like.most_common():
        print(f"  {key:30} {count}")

    print(f"\nsample objects holding a date:")
    for key, value, keys in samples:
        print(f"  key={key!r} value={value!r}")
        print(f"    sibling keys: {keys}")

    print(f"\nmost common shapes of objects holding a date:")
    for shape, count in parent_shapes.most_common(5):
        print(f"  {count:4}  {list(shape)}")

    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
