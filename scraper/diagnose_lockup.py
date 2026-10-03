#!/usr/bin/env python3
"""
Dump every string inside the first lockups on a channel's Videos tab.

View counts reached the parser for 6 channels out of 106 while upload ages
reached it for 104, so the view string is either absent or shaped differently
from what the regex expects. This shows what is actually there.
"""
import asyncio
import sys

from playwright.async_api import async_playwright
from youtube_scraper import (
    USER_AGENT, channel_about_url, extract_json_blob, walk_objects)


async def main():
    channel = sys.argv[1] if len(sys.argv) > 1 else \
        'https://www.youtube.com/@TheLoversPassport'
    url = channel_about_url(channel).rsplit('/about', 1)[0] + '/videos'

    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        page = await (await b.new_context(user_agent=USER_AGENT)).new_page()
        await page.goto(url, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(3000)
        html = await page.content()
        await b.close()

    data = extract_json_blob(html, 'ytInitialData')
    print(f"{url}\n  payload parsed: {data is not None}")
    if not data:
        return 1

    shown = 0
    for obj in walk_objects(data):
        lockup = obj.get('lockupViewModel')
        if not isinstance(lockup, dict):
            continue
        shown += 1
        print(f"\n--- lockup {shown}  contentId={lockup.get('contentId')}")
        strings = []
        for inner in walk_objects(lockup):
            for key, value in inner.items():
                if isinstance(value, str) and value.strip():
                    strings.append((key, value.strip()))
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str) and item.strip():
                            strings.append((key + '[]', item.strip()))
        seen = set()
        for key, value in strings:
            if (key, value) in seen:
                continue
            seen.add((key, value))
            print(f"    {key:28} {value[:90]!r}")
        if shown >= 2:
            break
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
