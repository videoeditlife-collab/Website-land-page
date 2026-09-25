#!/usr/bin/env python3
"""
Report how a watch page actually carries its description.

find_editors.py read 424 watch pages and found zero credits, which points at
the description extraction rather than at the channels. Give it a channel URL;
it finds that channel's newest video and dumps what the live page contains.

    python diagnose_watch.py https://www.youtube.com/@SomeChannel
"""
import asyncio
import re
import sys

from playwright.async_api import async_playwright

from youtube_scraper import (
    USER_AGENT, channel_about_url, extract_json_blob, walk_objects)
from find_editors import video_ids_from_data

MARKERS = ('ytInitialPlayerResponse', 'ytInitialData', 'shortDescription',
           'attributedDescription', 'videoDetails', 'consent',
           'before you continue', 'Sign in to confirm')


async def main():
    if len(sys.argv) < 2:
        print("usage: diagnose_watch.py <channel-url>", file=sys.stderr)
        return 1
    channel = sys.argv[1]

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await (await browser.new_context(user_agent=USER_AGENT)).new_page()

        videos_url = channel_about_url(channel).rsplit('/about', 1)[0] + '/videos'
        await page.goto(videos_url, wait_until='domcontentloaded', timeout=30000)
        ids = video_ids_from_data(
            extract_json_blob(await page.content(), 'ytInitialData'), 1)
        if not ids:
            print("no video ids from the Videos tab")
            await browser.close()
            return 1

        url = f"https://www.youtube.com/watch?v={ids[0]}"
        await page.goto(url, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(2500)
        html = await page.content()
        title = await page.title()
        await browser.close()

    print(f"channel: {channel}")
    print(f"video:   {url}")
    print(f"title:   {title}")
    print(f"bytes:   {len(html)}")
    for marker in MARKERS:
        print(f"  {marker:24} {html.count(marker)}")

    player = extract_json_blob(html, 'ytInitialPlayerResponse')
    print(f"\nytInitialPlayerResponse parsed: {player is not None}")
    if player:
        for obj in walk_objects(player):
            details = obj.get('videoDetails')
            if isinstance(details, dict):
                print(f"  videoDetails keys: {sorted(details.keys())[:14]}")
                text = details.get('shortDescription')
                print(f"  shortDescription: {repr(text)[:300] if text else 'MISSING'}")
                break
        else:
            print("  no videoDetails anywhere in the payload")

    data = extract_json_blob(html, 'ytInitialData')
    print(f"\nytInitialData parsed: {data is not None}")
    if data:
        for obj in walk_objects(data):
            attributed = obj.get('attributedDescription')
            if isinstance(attributed, dict) and isinstance(attributed.get('content'), str):
                print(f"  attributedDescription.content: "
                      f"{repr(attributed['content'])[:300]}")
                break
        else:
            print("  no attributedDescription found")

    match = re.search(r'<meta name="description" content="([^"]{0,300})"', html)
    print(f"\nmeta description: {match.group(1) if match else 'MISSING'}")
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
