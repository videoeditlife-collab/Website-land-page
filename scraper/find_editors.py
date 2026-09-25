#!/usr/bin/env python3
"""
Find the editors credited by a list of creators.

For each channel it opens the most recent videos, reads the descriptions, and
pulls out editor credits - names, @handles and social links that appear next to
editing words. That is the ten-minutes-per-channel step from the referral
strategy, done in a pass.

    python find_editors.py results/creators_around_100k.csv editors.csv
    python find_editors.py channels.txt editors.csv --videos 5 --limit 40

Output has one row per credit found: the editor, the creator who credited them,
and the video it came from, so every row can be checked against its source.
"""

import argparse
import asyncio
import csv
import re
import sys

from playwright.async_api import async_playwright

from youtube_scraper import (
    USER_AGENT, channel_about_url, extract_json_blob, read_input, walk_objects,
)

# "Edited by X", "Editor: @x", "edit - x". The separator is optional because
# plenty of descriptions just run the words together on one line.
# [^\S\n] is "whitespace but not a newline": a credit and its name sit on one
# line, and letting \s cross the break swallowed the next line's label too
# ("Marcus Lee\nInstagram").
CREDIT_RE = re.compile(
    r'(?:video[^\S\n]+)?(?:edited[^\S\n]+by|editor|editing[^\S\n]+by'
    r'|edit[^\S\n]+by|edited)'
    r'[^\S\n]*[:\-–—>|]?[^\S\n]*'
    r'(@[\w.\-]{2,40}|[A-Z][\w.\'\-]+(?:[^\S\n]+[A-Z][\w.\'\-]+){0,2})',
    re.IGNORECASE,
)

# A social link sitting on the same line as an editing word is usually the
# editor's own, so the line is captured whole and reported for checking.
SOCIAL_RE = re.compile(
    r'(https?://(?:www\.)?(?:instagram|twitter|x|tiktok|youtube|linkedin)\.com/'
    r'[^\s)"\']+)', re.IGNORECASE)

EDIT_WORD = re.compile(r'\bedit(?:ed|or|ing)?\b', re.IGNORECASE)

# Words that follow an editing verb without naming a person.
NOT_A_NAME = re.compile(
    r'^(by|the|this|my|our|me|myself|is|was|and|for|in|on|it|a|an|'
    r'software|software:|video|videos|vlog|channel|content|footage|'
    r'premiere|resolve|final|capcut|after|adobe|davinci|vegas|filmora|'
    r'with|using|entirely|mostly|all|everything|himself|herself|them)$',
    re.IGNORECASE)


def video_ids_from_data(data, limit):
    """Video ids off a channel's Videos tab, newest first."""
    ids = []
    for obj in walk_objects(data or {}):
        lockup = obj.get('lockupViewModel')
        if isinstance(lockup, dict):
            vid = lockup.get('contentId')
            if isinstance(vid, str) and vid not in ids:
                ids.append(vid)
        elif isinstance(obj.get('videoId'), str):
            vid = obj['videoId']
            if vid not in ids:
                ids.append(vid)
        if len(ids) >= limit:
            break
    return ids[:limit]


def description_from_player(html):
    """The full description, from the player payload rather than the DOM."""
    data = extract_json_blob(html, 'ytInitialPlayerResponse')
    if not data:
        return ''
    for obj in walk_objects(data):
        details = obj.get('videoDetails')
        if isinstance(details, dict):
            text = details.get('shortDescription')
            if isinstance(text, str):
                return text
    return ''


def credits_from_description(text):
    """Every editor credit in one description."""
    found = []

    for match in CREDIT_RE.finditer(text or ''):
        name = match.group(1).strip().strip('.,:;-')
        if not name:
            continue
        # Test the first word, not the whole capture: "Edited in Premiere Pro"
        # otherwise reads as a person called "in Premiere Pro".
        if NOT_A_NAME.match(name.split()[0]):
            continue
        # The line it sits on, for checking the match is a real credit.
        start = text.rfind('\n', 0, match.start()) + 1
        end = text.find('\n', match.end())
        line = text[start:end if end != -1 else len(text)].strip()
        found.append((name, line[:160]))

    # Social links on a line that also mentions editing.
    for line in (text or '').splitlines():
        if not EDIT_WORD.search(line):
            continue
        for link in SOCIAL_RE.findall(line):
            found.append((link, line.strip()[:160]))

    unique = []
    seen = set()
    for name, line in found:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            unique.append((name, line))
    return unique


async def read(page, url):
    try:
        await page.goto(url, wait_until='domcontentloaded', timeout=25000)
        return await page.content()
    except Exception as exc:
        print(f"      load failed: {exc}", file=sys.stderr)
        return ''


async def scan_channel(page, channel_url, video_count):
    videos_url = channel_about_url(channel_url).rsplit('/about', 1)[0] + '/videos'
    html = await read(page, videos_url)
    if not html:
        return []

    ids = video_ids_from_data(extract_json_blob(html, 'ytInitialData'), video_count)
    print(f"      {len(ids)} recent videos", file=sys.stderr)

    rows = []
    for vid in ids:
        watch = await read(page, f"https://www.youtube.com/watch?v={vid}")
        if not watch:
            continue
        for name, line in credits_from_description(description_from_player(watch)):
            rows.append({
                'Editor': name,
                'Credited By': channel_url,
                'Video': f"https://www.youtube.com/watch?v={vid}",
                'Context': line,
            })
        await asyncio.sleep(0.4)

    return rows


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', help='CSV or txt of creator channel URLs')
    parser.add_argument('destination')
    parser.add_argument('--videos', type=int, default=4,
                        help='Recent videos to read per channel (default: 4)')
    parser.add_argument('--limit', type=int, default=0,
                        help='Only scan the first N channels')
    args = parser.parse_args()

    urls = read_input(args.source)
    if not urls:
        return 1
    if args.limit:
        urls = urls[:args.limit]

    rows = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        page = await context.new_page()

        for index, url in enumerate(urls, 1):
            print(f"[{index}/{len(urls)}] {url}", file=sys.stderr)
            found = await scan_channel(page, url, args.videos)
            for row in found:
                print(f"      CREDIT: {row['Editor']}", file=sys.stderr)
            rows.extend(found)

        await browser.close()

    with open(args.destination, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=['#', 'Editor', 'Credited By', 'Video', 'Context',
                        'Contact', 'Sent', 'Reply'])
        writer.writeheader()
        for index, row in enumerate(rows, 1):
            row['#'] = index
            row.setdefault('Contact', '')
            row.setdefault('Sent', '')
            row.setdefault('Reply', '')
            writer.writerow(row)

    print(f"\n{len(rows)} credits across {len(urls)} channels -> {args.destination}",
          file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
