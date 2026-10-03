#!/usr/bin/env python3
"""
Why did the lead generator read nothing from ytInitialData?

Creator names came through (those use og:title) while every field sourced from
ytInitialData was empty, on both the About page and the Videos tab. This
reports what the runner is actually being served.
"""
import asyncio
import sys

from playwright.async_api import async_playwright
from youtube_scraper import (
    USER_AGENT, channel_about_url, extract_json_blob, subscribers_from_data,
    walk_objects)


async def look(page, label, url):
    await page.goto(url, wait_until='domcontentloaded', timeout=30000)
    await page.wait_for_timeout(2000)
    html = await page.content()

    print(f"\n=== {label}: {url}")
    print(f"  bytes: {len(html)}")
    print(f"  title: {await page.title()}")
    for marker in ('ytInitialData', 'lockupViewModel', 'subscribers',
                   'subscriberCountText', 'consent', 'Before you continue',
                   'Sign in to confirm', 'not a bot'):
        print(f"    {marker:22} {html.count(marker)}")

    data = extract_json_blob(html, 'ytInitialData')
    print(f"  extract_json_blob -> {type(data).__name__ if data else 'None'}")

    if data is None:
        idx = html.find('ytInitialData')
        shown = 0
        while idx != -1 and shown < 4:
            print(f"    context @{idx}: {html[max(0, idx-50):idx+130]!r}")
            idx = html.find('ytInitialData', idx + 1)
            shown += 1
    else:
        dicts = sum(1 for _ in walk_objects(data))
        lockups = sum(1 for o in walk_objects(data)
                      if isinstance(o.get('lockupViewModel'), dict))
        print(f"  dicts in payload: {dicts}   lockups: {lockups}")
        print(f"  subscribers_from_data: {subscribers_from_data(data)}")


async def main():
    channel = sys.argv[1] if len(sys.argv) > 1 else \
        'https://www.youtube.com/@TheLoversPassport'
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        page = await (await b.new_context(user_agent=USER_AGENT)).new_page()
        await look(page, 'ABOUT', channel_about_url(channel))
        await look(page, 'VIDEOS',
                   channel_about_url(channel).rsplit('/about', 1)[0] + '/videos')
        await b.close()
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
