#!/usr/bin/env python3
"""
Dump each channel's About-page detail so shared ownership, shared networks or
affiliate monetisation can be spotted.

Reports description, country, join date, total views, and every external link
the channel lists.

    python inspect_channels.py results/shortlist.csv > inspect.json
"""

import asyncio
import csv
import json
import re
import sys

from playwright.async_api import async_playwright

from youtube_scraper import (
    USER_AGENT,
    channel_about_url,
    channel_name_from_html,
    extract_json_blob,
    read_input,
    resolve_redirect,
    walk_objects,
    _text_of,
)

# Domains that indicate booking/affiliate monetisation rather than a personal link.
AFFILIATE_HINTS = (
    'amzn.to', 'amazon.', 'booking.com', 'awin1.com', 'shareasale',
    'skimresources', 'linktr.ee', 'stan.store', 'beacons.ai', 'bit.ly',
    'tidd.ly', 'expedia', 'agoda', 'tui.co', 'jet2', 'loveholidays',
    'ricksteves', 'geni.us', 'howl.link', 'shopmy', 'ltk.',
)


def external_links(data):
    """Every external link the channel lists, as (title, url)."""
    links = []
    seen = set()

    for obj in walk_objects(data):
        model = obj.get('channelExternalLinkViewModel')
        if not isinstance(model, dict):
            continue

        title = _text_of(model.get('title')) or ''
        link = model.get('link')
        url = _text_of(link) if link is not None else None

        target = None
        for candidate in walk_objects(link if isinstance(link, dict) else {}):
            raw = candidate.get('url')
            if isinstance(raw, str):
                target = resolve_redirect(raw)
                break

        final = target or url
        if final and final not in seen:
            seen.add(final)
            links.append({'title': title.strip(), 'url': final})

    return links


def field(data, *names):
    for obj in walk_objects(data):
        for name in names:
            value = obj.get(name)
            text = _text_of(value) if value is not None else None
            if text and text.strip():
                return text.strip()
    return None


async def inspect(page, url):
    about = channel_about_url(url)
    record = {'channel': url}

    try:
        await page.goto(about, wait_until='domcontentloaded', timeout=25000)
        html = await page.content()
    except Exception as exc:
        record['error'] = str(exc)
        return record

    data = extract_json_blob(html, 'ytInitialData')

    record['name'] = channel_name_from_html(html, data)
    record['country'] = field(data, 'country')
    record['joined'] = field(data, 'joinedDateText')
    record['views'] = field(data, 'viewCountText')
    record['canonical'] = field(data, 'canonicalChannelUrl')

    description = None
    match = re.search(
        r'<meta\s+property="og:description"\s+content="([^"]*)"', html, re.IGNORECASE
    )
    if match:
        description = match.group(1)
    record['description'] = (description or '')[:600]

    links = external_links(data)
    record['links'] = links
    record['affiliate_links'] = [
        link for link in links
        if any(hint in link['url'].lower() for hint in AFFILIATE_HINTS)
    ]

    return record


async def main():
    if len(sys.argv) < 2:
        print("usage: inspect_channels.py <csv-or-txt>", file=sys.stderr)
        return 1

    urls = read_input(sys.argv[1])
    if not urls:
        return 1

    records = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        page = await context.new_page()

        for url in urls:
            print(f"inspecting {url}", file=sys.stderr)
            records.append(await inspect(page, url))
            await asyncio.sleep(1)

        await browser.close()

    print(json.dumps(records, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
