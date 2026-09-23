#!/usr/bin/env python3
"""
Find published business contact details for a creator.

Takes channel and site URLs, loads each page plus the usual contact paths, and
reports the email addresses and social links actually published on them.

    python find_contact.py https://www.youtube.com/@Someone https://theirstore.com

Only reads what a visitor sees. YouTube's own business email stays behind a
sign-in and a CAPTCHA, so this reports whether the channel lists one and then
looks for a published address on the sites the channel links to instead.
"""

import asyncio
import re
import sys
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright

from youtube_scraper import (
    USER_AGENT, channel_about_url, extract_json_blob, all_external_links,
    has_business_email, channel_name_from_html, subscribers_from_data,
    description_from_html,
)

# Paths a small business almost always puts contact details on.
CONTACT_PATHS = [
    '', '/pages/contact', '/pages/contact-us', '/contact', '/contact-us',
    '/pages/about', '/about', '/pages/faq', '/policies/contact-information',
]

EMAIL_RE = re.compile(
    r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}', re.IGNORECASE)

# Addresses that belong to the platform, not the business.
IGNORE = re.compile(
    r'@(sentry|wixpress|example|shopify\.com|godaddy|squarespace|'
    r'cloudflare|googlemail\.com\.|domain)', re.IGNORECASE)

IMAGE_EXT = re.compile(r'\.(png|jpe?g|gif|svg|webp|css|js)$', re.IGNORECASE)


def clean(found):
    out = []
    for address in found:
        address = address.strip().strip('.').lower()
        if IGNORE.search(address) or IMAGE_EXT.search(address):
            continue
        if address not in out:
            out.append(address)
    return out


async def read_page(page, url):
    try:
        await page.goto(url, wait_until='domcontentloaded', timeout=20000)
        await page.wait_for_timeout(1200)
        return await page.content()
    except Exception as exc:
        return f"<!--error {exc}-->"


async def scan_site(page, base):
    """Check a site's home page and its usual contact paths."""
    parsed = urlparse(base if base.startswith('http') else 'https://' + base)
    root = f"{parsed.scheme}://{parsed.netloc}"

    results = {}
    for path in CONTACT_PATHS:
        url = urljoin(root, path) if path else root
        html = await read_page(page, url)
        if html.startswith('<!--error'):
            continue

        found = clean(EMAIL_RE.findall(html))
        # mailto: links are the deliberate ones, so list them first.
        mailto = clean(re.findall(r'mailto:([^"\'?&>\s]+)', html, re.IGNORECASE))
        addresses = clean(mailto + found)

        if addresses:
            results[url] = addresses

    return results


async def main():
    if len(sys.argv) < 2:
        print("usage: find_contact.py <url> [url ...]", file=sys.stderr)
        return 1

    youtube_urls = [u for u in sys.argv[1:] if 'youtube.com' in u]
    site_urls = [u for u in sys.argv[1:] if 'youtube.com' not in u]

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        page = await context.new_page()

        for url in youtube_urls:
            print(f"\n=== YOUTUBE {url}")
            html = await read_page(page, channel_about_url(url))
            data = extract_json_blob(html, 'ytInitialData')

            print(f"  name:        {channel_name_from_html(html, data)}")
            text, count = subscribers_from_data(data)
            print(f"  subscribers: {text} ({count})")
            print(f"  business email listed: {has_business_email(html, data)}"
                  f"   (address itself needs sign-in + CAPTCHA)")
            description = description_from_html(html)
            print(f"  description: {description[:220]}")

            in_desc = clean(EMAIL_RE.findall(description))
            if in_desc:
                print(f"  EMAIL IN DESCRIPTION: {', '.join(in_desc)}")

            links = all_external_links(data)
            for link in links:
                print(f"  link: {link}")
            site_urls.extend(
                l for l in links
                if not re.search(r'(instagram|tiktok|twitter|x\.com|facebook|'
                                 r'youtube|threads|snapchat|discord)\.', l))

        seen = set()
        for url in site_urls:
            key = urlparse(url if url.startswith('http') else 'https://' + url).netloc
            if not key or key in seen:
                continue
            seen.add(key)

            print(f"\n=== SITE {key}")
            results = await scan_site(page, url)
            if not results:
                print("  no published address found on the usual contact paths")
            for where, addresses in results.items():
                print(f"  {where}")
                for address in addresses:
                    print(f"      {address}")

        await browser.close()

    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
