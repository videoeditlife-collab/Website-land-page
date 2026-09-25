#!/usr/bin/env python3
"""
Report how a watch page actually carries its description.

find_editors.py read 424 watch pages and found zero credits, which points at
the description extraction rather than at the channels. This dumps what the
live page really contains.

    python diagnose_watch.py https://www.youtube.com/watch?v=VIDEO_ID
"""
import asyncio, re, sys
from playwright.async_api import async_playwright
from youtube_scraper import USER_AGENT, extract_json_blob, walk_objects


async def main():
    url = sys.argv[1]
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        page = await (await b.new_context(user_agent=USER_AGENT)).new_page()
        await page.goto(url, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(2500)
        html = await page.content()
        title = await page.title()
        await b.close()

    print(f"url: {url}")
    print(f"title: {title}")
    print(f"bytes: {len(html)}")
    for marker in ('ytInitialPlayerResponse', 'ytInitialData', 'shortDescription',
                   'attributedDescription', 'videoDetails', 'consent.youtube',
                   'Sign in', 'before you continue'):
        print(f"  {marker:26} {html.count(marker)}")

    player = extract_json_blob(html, 'ytInitialPlayerResponse')
    print(f"\nytInitialPlayerResponse parsed: {player is not None}")
    if player:
        for obj in walk_objects(player):
            d = obj.get('videoDetails')
            if isinstance(d, dict):
                print(f"  videoDetails keys: {sorted(d.keys())[:12]}")
                sd = d.get('shortDescription')
                print(f"  shortDescription: {type(sd).__name__} "
                      f"{repr(sd)[:200] if sd else 'MISSING'}")
                break
        else:
            print("  no videoDetails anywhere in the payload")

    data = extract_json_blob(html, 'ytInitialData')
    print(f"\nytInitialData parsed: {data is not None}")
    if data:
        for obj in walk_objects(data):
            ad = obj.get('attributedDescription')
            if isinstance(ad, dict) and isinstance(ad.get('content'), str):
                print(f"  attributedDescription.content: "
                      f"{repr(ad['content'])[:240]}")
                break
        else:
            print("  no attributedDescription found")

    m = re.search(r'<meta name="description" content="([^"]{0,240})"', html)
    print(f"\nmeta description: {m.group(1) if m else 'MISSING'}")
    return 0

if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
