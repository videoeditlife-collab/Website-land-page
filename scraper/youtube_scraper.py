#!/usr/bin/env python3
"""
YouTube channel scraper.

Reads channel URLs from a CSV (or plain text file), visits each channel's About
page, and extracts:

  - channel display name
  - subscriber count
  - whether a business email is listed
  - Instagram link (+ follower count, if Instagram cookies are supplied)
  - Skool community link (+ name and member count)

Channels come either from a file of URLs (--input) or from YouTube search
itself (--search), which discovers channels for a niche without needing a
list up front.

Results stream to the output CSV row by row, so an interrupted run keeps
everything scraped so far and can be resumed with --resume.

Usage:
    python youtube_scraper.py --input youtube_filtered.csv
    python youtube_scraper.py --search "travel vlog" --duration long
    python youtube_scraper.py --search-file terms.txt --min-subscribers 10000
    python youtube_scraper.py --input in.csv --output out.csv --resume
"""

import argparse
import asyncio
import base64
import csv
import json
import os
import re
import sys
from urllib.parse import urlparse, parse_qs, unquote, quote_plus

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("Playwright is required. Install with:")
    print("    pip install playwright && playwright install chromium")
    sys.exit(1)


# ============================================================================
# URL HELPERS
# ============================================================================

def normalize_instagram_url(url):
    """Normalize an Instagram URL to a canonical https://www.instagram.com/... form."""
    if not url:
        return None
    url = url.strip()
    if url.startswith('http'):
        return url
    if url.startswith('www.'):
        return 'https://' + url
    if url.startswith('instagram.com'):
        return 'https://www.' + url
    return 'https://www.instagram.com/' + url.lstrip('/')


def normalize_skool_url(url):
    """Normalize a Skool URL and point it at the community's /about page."""
    if not url:
        return None

    url = url.split('?')[0].strip()

    if not url.startswith('http'):
        if url.startswith('www.'):
            url = 'https://' + url
        elif url.startswith('skool.com'):
            url = 'https://www.' + url
        else:
            url = 'https://www.skool.com/' + url.lstrip('/')

    if 'skool.com/' not in url:
        return None

    community = url.split('skool.com/')[1].split('/')[0]
    if not community:
        return None

    return f"https://www.skool.com/{community}/about"


def resolve_redirect(url):
    """Unwrap a youtube.com/redirect?q=... link into the URL it points at."""
    if not url:
        return None

    if 'youtube.com/redirect' not in url:
        return url

    try:
        params = parse_qs(urlparse(url).query)
    except ValueError:
        return url

    if 'q' not in params:
        return url

    target = unquote(params['q'][0])
    if not target.startswith('http'):
        target = 'https://' + target.lstrip('/')
    return target


def channel_about_url(channel_url):
    """Turn any channel URL into its /about page URL."""
    url = channel_url.strip().rstrip('/')

    for marker in ('/@', '/channel/', '/c/', '/user/'):
        if marker in url:
            head, tail = url.split(marker, 1)
            handle = tail.split('/')[0].split('?')[0]
            return f"{head}{marker}{handle}/about"

    return url + '/about'


# ============================================================================
# COUNT PARSING
# ============================================================================

_MULTIPLIERS = {'k': 1_000, 'm': 1_000_000, 'b': 1_000_000_000}

# A number, optionally followed by a K/M/B magnitude suffix. The trailing \b keeps
# the 'M' of "2,481 Members" from being read as a millions suffix - the suffix only
# counts when the letter ends a word.
_COUNT_RE = re.compile(r'(\d[\d,.]*)\s*([KMB])?\b', re.IGNORECASE)


def parse_count(text, require_word=None):
    """
    Parse a human-formatted count such as '1.2M subscribers' or '12,345'.

    require_word guards against reading the wrong metric: passing
    'subscriber' means '150 videos' returns None instead of 150.
    """
    if not text:
        return None

    text = text.strip()

    if require_word and require_word not in text.lower():
        return None

    match = _COUNT_RE.search(text)
    if not match:
        return None

    digits, suffix = match.group(1), match.group(2)

    try:
        if suffix:
            return int(float(digits.replace(',', '')) * _MULTIPLIERS[suffix.lower()])
        # Without a magnitude suffix any '.' or ',' is a thousands separator.
        return int(digits.replace(',', '').replace('.', ''))
    except (ValueError, KeyError):
        return None


def parse_subscribers(text):
    return parse_count(text, require_word='subscriber')


def parse_followers(text):
    return parse_count(text, require_word='follower')


def parse_members(text):
    return parse_count(text, require_word='member')


# ============================================================================
# ytInitialData EXTRACTION
#
# YouTube renders the About panel from a JSON blob embedded in the page. Reading
# that blob is far more reliable than querying the DOM: it does not depend on
# CSS being loaded, on the "...more" / "and N more links" panels being expanded,
# or on YouTube's rotating element names.
# ============================================================================

def extract_json_blob(html, marker):
    """Pull a JSON object out of `html` by brace-matching from after `marker`."""
    start = html.find(marker)
    if start == -1:
        return None

    start = html.find('{', start)
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False

    for i in range(start, len(html)):
        char = html[i]

        if in_string:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start:i + 1])
                except json.JSONDecodeError:
                    return None

    return None


def walk_strings(node):
    """Yield every (key, string) pair anywhere inside a nested JSON structure."""
    stack = [(None, node)]

    while stack:
        key, value = stack.pop()

        if isinstance(value, dict):
            for k, v in value.items():
                stack.append((k, v))
        elif isinstance(value, list):
            for item in value:
                stack.append((key, item))
        elif isinstance(value, str):
            yield key, value


_SUBSCRIBER_TEXT_RE = re.compile(r'^[\d.,]+\s*[KMB]?\s*subscribers?$', re.IGNORECASE)


def subscribers_from_data(data):
    """Find the subscriber count string in ytInitialData."""
    if not data:
        return None, None

    fallback = None

    for key, value in walk_strings(data):
        text = value.strip()

        if not _SUBSCRIBER_TEXT_RE.match(text):
            continue

        count = parse_subscribers(text)
        if count is None:
            continue

        # subscriberCountText is the authoritative field; anything else is a guess.
        if key == 'subscriberCountText':
            return text, count
        if fallback is None:
            fallback = (text, count)

    return fallback if fallback else (None, None)


def channel_name_from_html(html, data):
    """Read the channel's display name from og:title, falling back to the JSON."""
    match = re.search(
        r'<meta\s+property="og:title"\s+content="([^"]+)"', html, re.IGNORECASE
    )
    if match:
        name = match.group(1).strip()
        if name:
            return _unescape_html(name)

    if data:
        for key, value in walk_strings(data):
            if key == 'title' and value.strip():
                return value.strip()

    return None


def _unescape_html(text):
    return (
        text.replace('&amp;', '&')
        .replace('&quot;', '"')
        .replace('&#39;', "'")
        .replace('&lt;', '<')
        .replace('&gt;', '>')
    )


def links_from_page(html, data, keyword):
    """
    Collect every link matching `keyword` from the page, unwrapping YouTube's
    redirect wrapper. Reads the JSON blob first, then the raw HTML as a backstop.
    """
    found = []

    def add(candidate):
        resolved = resolve_redirect(candidate)
        if resolved and keyword in resolved.lower() and resolved not in found:
            found.append(resolved)

    if data:
        for _, value in walk_strings(data):
            lowered = value.lower()
            if keyword in lowered or 'youtube.com/redirect' in lowered:
                add(value)

    if not found:
        for candidate in re.findall(r'https?://[^\s"\'<>\\]+', html):
            if keyword in candidate.lower() or 'youtube.com/redirect' in candidate.lower():
                add(candidate)

    # A page lists the same profile twice: once as display text ("instagram.com/foo")
    # and once as a full redirect target. Prefer the fully-qualified URL.
    found.sort(key=lambda u: not u.startswith('http'))
    return found


_EMAIL_HINTS = (
    'sign in to see email address',
    'sign in to view email address',
    'sign in to see the email address',
    'view email address',
)


def has_business_email(html, data):
    """Detect whether the channel lists a business email."""
    lowered = html.lower()
    if any(hint in lowered for hint in _EMAIL_HINTS):
        return True

    if data:
        for key, value in walk_strings(data):
            if key in ('signInForBusinessEmail', 'businessEmail') and value.strip():
                return True
            if 'email address' in value.lower() and 'sign in' in value.lower():
                return True

    return False


# ============================================================================
# BROWSER SETUP
# ============================================================================

BLOCKED_RESOURCES = {'image', 'font', 'media'}

USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)


async def block_heavy_resources(context):
    """Skip images, fonts and media. Stylesheets are left alone so that any
    DOM-visibility check still sees a normally laid out page."""

    async def handler(route):
        if route.request.resource_type in BLOCKED_RESOURCES:
            await route.abort()
        else:
            await route.continue_()

    await context.route('**/*', handler)


async def new_context(browser, storage_state=None):
    kwargs = {
        'viewport': {'width': 1280, 'height': 900},
        'user_agent': USER_AGENT,
    }
    if storage_state:
        kwargs['storage_state'] = storage_state

    context = await browser.new_context(**kwargs)
    await block_heavy_resources(context)
    return context


def load_instagram_state(path):
    """Return a usable Playwright storage-state path, or None."""
    if not path:
        return None

    if os.path.exists(path):
        return path

    print(f"   Instagram state file not found: {path} - Instagram scraping disabled")
    return None


# ============================================================================
# SCRAPERS
# ============================================================================

async def scrape_instagram(page, instagram_url):
    """Return the follower-count text from an Instagram profile, if readable."""
    url = normalize_instagram_url(instagram_url)
    if not url:
        return None

    try:
        await page.goto(url, wait_until='domcontentloaded', timeout=20000)
    except Exception as exc:
        print(f"         Instagram navigation failed: {exc}")
        return None

    # The profile header exposes the follower count in a meta description such as
    # "1,234 Followers, 567 Following, 89 Posts - ...". That is stable and does
    # not require the profile grid to finish rendering.
    try:
        html = await page.content()
    except Exception:
        return None

    match = re.search(
        r'content="([\d.,]+[KMB]?)\s+Followers', html, re.IGNORECASE
    )
    if match:
        return f"{match.group(1)} followers"

    try:
        element = await page.query_selector("a[href*='/followers/'] span[title]")
        if element:
            title = await element.get_attribute('title')
            if title:
                return f"{title} followers"

        element = await page.query_selector("a[href*='/followers/'] span")
        if element:
            text = (await element.text_content() or '').strip()
            if text:
                return f"{text} followers"
    except Exception:
        pass

    return None


async def scrape_skool(page, skool_url):
    """Return (community name, member count, member text) for a Skool community."""
    url = normalize_skool_url(skool_url)
    if not url:
        return None, None, None

    try:
        await page.goto(url, wait_until='domcontentloaded', timeout=20000)
    except Exception as exc:
        print(f"         Skool navigation failed: {exc}")
        return None, None, None

    try:
        html = await page.content()
    except Exception:
        return None, None, None

    name = None
    match = re.search(
        r'<meta\s+property="og:title"\s+content="([^"]+)"', html, re.IGNORECASE
    )
    if match:
        name = _unescape_html(match.group(1).strip())
        # Skool titles are often "Community Name | Skool".
        name = re.split(r'\s*\|\s*', name)[0].strip() or None

    member_text = None
    member_count = None
    match = re.search(r'([\d.,]+\s*[KMB]?)\s*(?:Members?|member)', html, re.IGNORECASE)
    if match:
        member_text = match.group(0).strip()
        member_count = parse_members(member_text)

    return name, member_count, member_text


async def scrape_channel(yt_page, ig_page, skool_page, channel_url):
    """Scrape one YouTube channel's About page and its linked profiles."""
    result = {
        'channel_name': None,
        'subscriber_text': None,
        'subscriber_count': None,
        'has_email': False,
        'instagram': None,
        'instagram_followers': None,
        'instagram_follower_count': None,
        'skool': None,
        'skool_name': None,
        'skool_member_count': None,
        'skool_member_text': None,
        'status': 'ok',
    }

    about_url = channel_about_url(channel_url)

    try:
        await yt_page.goto(about_url, wait_until='domcontentloaded', timeout=25000)
        html = await yt_page.content()
    except Exception as exc:
        result['status'] = f"error: {type(exc).__name__}"
        print(f"         Failed to load {about_url}: {exc}")
        return result

    data = extract_json_blob(html, 'ytInitialData')

    result['channel_name'] = channel_name_from_html(html, data)
    if result['channel_name']:
        print(f"         Name: {result['channel_name']}")

    subscriber_text, subscriber_count = subscribers_from_data(data)
    result['subscriber_text'] = subscriber_text
    result['subscriber_count'] = subscriber_count

    if subscriber_count is None:
        result['status'] = 'no_subscriber_count'
        print("         Subscribers: not found")
    else:
        print(f"         Subscribers: {subscriber_text} ({subscriber_count})")

    result['has_email'] = has_business_email(html, data)
    print(f"         Email listed: {'yes' if result['has_email'] else 'no'}")

    instagram_links = links_from_page(html, data, 'instagram.com')
    if instagram_links:
        result['instagram'] = normalize_instagram_url(instagram_links[0])
        print(f"         Instagram: {result['instagram']}")

        if ig_page:
            followers = await scrape_instagram(ig_page, result['instagram'])
            if followers:
                result['instagram_followers'] = followers
                result['instagram_follower_count'] = parse_followers(followers)
                print(f"         Instagram followers: {followers}")

    skool_links = links_from_page(html, data, 'skool.com')
    if skool_links:
        # Keep the link even if the community page cannot be read - a URL we
        # already found is worth more than nothing.
        result['skool'] = normalize_skool_url(skool_links[0])
        print(f"         Skool: {result['skool']}")

        if skool_page and result['skool']:
            name, members, member_text = await scrape_skool(skool_page, result['skool'])
            result['skool_name'] = name
            result['skool_member_count'] = members
            result['skool_member_text'] = member_text
            if name or member_text:
                print(f"         Skool community: {name or 'unknown'} - {member_text or 'n/a'}")

    return result


# ============================================================================
# SEARCH DISCOVERY
#
# YouTube encodes search filters into the `sp` query parameter as a base64url
# protobuf. Building it here means filters can be combined freely instead of
# copying opaque constants around, and it avoids clicking through the filter
# menu (which was the fragile part of the original implementation).
#
#   top level : field 1 = sort order, field 2 = filter submessage
#   filters   : field 1 = upload date, field 2 = result type, field 3 = duration
# ============================================================================

UPLOAD_DATE = {'hour': 1, 'today': 2, 'week': 3, 'month': 4, 'year': 5}
RESULT_TYPE = {'video': 1, 'channel': 2, 'playlist': 3, 'movie': 4}
DURATION = {'short': 1, 'long': 2, 'medium': 3}
SORT_BY = {'relevance': 0, 'rating': 1, 'date': 2, 'views': 3}


def _varint(value):
    """Encode an integer as a protobuf varint."""
    out = bytearray()
    while True:
        chunk = value & 0x7F
        value >>= 7
        out.append(chunk | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _tag(field_number, wire_type):
    return _varint((field_number << 3) | wire_type)


def build_search_filter(duration=None, upload_date=None, result_type=None, sort_by=None):
    """
    Build the `sp` search-filter parameter.

    Verifiable against YouTube's own values: duration=long alone gives
    'EgIYAg%3D%3D', upload_date=year gives 'EgIIBQ%3D%3D'.
    """
    filters = bytearray()

    if upload_date:
        filters += _tag(1, 0) + _varint(UPLOAD_DATE[upload_date])
    if result_type:
        filters += _tag(2, 0) + _varint(RESULT_TYPE[result_type])
    if duration:
        filters += _tag(3, 0) + _varint(DURATION[duration])

    message = bytearray()

    # Sort order is only emitted when it is not the default, matching YouTube.
    if sort_by and SORT_BY[sort_by]:
        message += _tag(1, 0) + _varint(SORT_BY[sort_by])
    if filters:
        message += _tag(2, 2) + _varint(len(filters)) + filters

    if not message:
        return None

    return base64.urlsafe_b64encode(bytes(message)).decode()


# Overridden by the test suite to point discovery at a local fixture server.
YOUTUBE_BASE = 'https://www.youtube.com'


def search_url(term, search_filter=None):
    url = f"{YOUTUBE_BASE}/results?search_query={quote_plus(term)}"
    if search_filter:
        url += f"&sp={quote_plus(search_filter)}"
    return url


_CHANNEL_HREF_RE = re.compile(r'^/(@[^/?#]+|channel/UC[\w-]{22})')


def channel_urls_from_hrefs(hrefs):
    """Reduce a page's links down to unique canonical channel URLs."""
    found = []
    seen = set()

    for href in hrefs:
        if not href:
            continue

        match = _CHANNEL_HREF_RE.match(href)
        if not match:
            continue

        url = f"{YOUTUBE_BASE}/{match.group(1)}"
        key = url.lower()
        if key not in seen:
            seen.add(key)
            found.append(url)

    return found


async def dismiss_consent(page):
    """Click through the cookie/consent wall that EU and UK sessions hit."""
    for selector in (
        "button[aria-label*='Accept all']",
        "button[aria-label*='Accept the use of cookies']",
        "form[action*='consent'] button",
    ):
        try:
            button = await page.query_selector(selector)
            if button:
                await button.click()
                await page.wait_for_timeout(1500)
                return True
        except Exception:
            continue
    return False


async def discover_channels(page, term, search_filter, scrolls, per_term):
    """Run one YouTube search and collect the channel URLs it surfaces."""
    url = search_url(term, search_filter)
    print(f"\n   Searching: {term}")
    print(f"      {url}")

    try:
        await page.goto(url, wait_until='domcontentloaded', timeout=30000)
    except Exception as exc:
        print(f"      Search failed: {exc}")
        return []

    await dismiss_consent(page)
    await page.wait_for_timeout(2000)

    found = []

    for index in range(max(1, scrolls)):
        try:
            hrefs = await page.eval_on_selector_all(
                'a[href]', 'nodes => nodes.map(n => n.getAttribute("href"))'
            )
        except Exception as exc:
            print(f"      Could not read results: {exc}")
            break

        for candidate in channel_urls_from_hrefs(hrefs):
            if candidate not in found:
                found.append(candidate)

        if per_term and len(found) >= per_term:
            break

        if index < scrolls - 1:
            try:
                await page.evaluate(
                    "window.scrollTo(0, document.documentElement.scrollHeight);"
                )
                await page.wait_for_timeout(2000)
            except Exception:
                break

    if per_term:
        found = found[:per_term]

    print(f"      Found {len(found)} channels")
    return found


async def run_discovery(browser, terms, args):
    """Search every term and return the combined, deduplicated channel list."""
    context = await new_context(browser)
    page = await context.new_page()

    search_filter = build_search_filter(
        duration=args.duration,
        upload_date=args.upload_date,
        result_type=args.result_type,
        sort_by=args.sort_by,
    )
    if search_filter:
        print(f"Search filter: sp={search_filter}")

    all_channels = []

    try:
        for term in terms:
            for url in await discover_channels(
                page, term, search_filter, args.scrolls, args.per_term
            ):
                if url not in all_channels:
                    all_channels.append(url)
    finally:
        try:
            await context.close()
        except Exception:
            pass

    print(f"\nDiscovered {len(all_channels)} unique channels across {len(terms)} terms")
    return all_channels


# ============================================================================
# INPUT / OUTPUT
# ============================================================================

URL_COLUMNS = ('Channel URL', 'channel_url', 'url', 'URL', 'Url', 'channel', 'Channel')


def read_input(path):
    """Read channel URLs from a CSV (any common URL column) or a .txt list."""
    if not os.path.exists(path):
        print(f"Input file not found: {path}")
        return []

    urls = []

    if path.lower().endswith(('.txt', '.list')):
        with open(path, encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if line and not line.startswith('#'):
                    urls.append(line)
    else:
        with open(path, newline='', encoding='utf-8') as handle:
            reader = csv.DictReader(handle)
            column = next(
                (c for c in URL_COLUMNS if reader.fieldnames and c in reader.fieldnames),
                None,
            )
            if not column:
                print(f"No URL column in {path}. Looked for: {', '.join(URL_COLUMNS)}")
                print(f"Columns present: {', '.join(reader.fieldnames or [])}")
                return []

            for row in reader:
                value = (row.get(column) or '').strip()
                if value:
                    urls.append(value)

    # Preserve input order while dropping duplicates.
    seen = set()
    unique = []
    for url in urls:
        key = url.rstrip('/').lower()
        if key not in seen:
            seen.add(key)
            unique.append(url)

    dropped = len(urls) - len(unique)
    print(f"Loaded {len(unique)} channels from {path}" + (f" ({dropped} duplicates dropped)" if dropped else ""))
    return unique


CSV_HEADER = [
    '#', 'Display Name', 'Email', 'YT Channel', 'YT Subscribers',
    'IG Account', 'IG Followers', 'Skool Community', 'Skool Link',
    '# of Members', 'Status',
]


def already_scraped(path):
    """URLs present in an existing output file, for --resume."""
    if not os.path.exists(path):
        return set()

    done = set()
    try:
        with open(path, newline='', encoding='utf-8') as handle:
            for row in csv.DictReader(handle):
                url = (row.get('YT Channel') or '').strip()
                if url:
                    done.add(url.rstrip('/').lower())
    except OSError as exc:
        print(f"Could not read existing output ({exc}); starting fresh")

    return done


class ResultWriter:
    """Appends each result to the CSV as it is scraped, so a crash loses nothing."""

    def __init__(self, path, resume=False):
        self.path = path
        self.lock = asyncio.Lock()
        self.count = 0

        exists = os.path.exists(path) and os.path.getsize(path) > 0
        mode = 'a' if (resume and exists) else 'w'

        self.handle = open(path, mode, newline='', encoding='utf-8')
        self.writer = csv.writer(self.handle)

        if mode == 'w':
            self.writer.writerow(CSV_HEADER)
            self.handle.flush()
        else:
            self.count = max(0, sum(1 for _ in open(path, encoding='utf-8')) - 1)

    async def write(self, channel_url, result):
        async with self.lock:
            self.count += 1
            self.writer.writerow([
                self.count,
                result.get('channel_name') or '',
                'Email in YouTube Bio' if result.get('has_email') else '',
                channel_url,
                result.get('subscriber_count') or '',
                result.get('instagram') or '',
                result.get('instagram_follower_count') or '',
                result.get('skool_name') or '',
                result.get('skool') or '',
                result.get('skool_member_count') or result.get('skool_member_text') or '',
                result.get('status') or '',
            ])
            self.handle.flush()

    def close(self):
        self.handle.close()


# ============================================================================
# MAIN
# ============================================================================

async def worker(name, queue, writer, browser, instagram_state, delay,
                 min_subscribers=0, max_subscribers=0):
    """Own a set of pages and drain the shared queue."""
    yt_context = await new_context(browser)
    yt_page = await yt_context.new_page()

    skool_context = await new_context(browser)
    skool_page = await skool_context.new_page()

    ig_context = None
    ig_page = None
    if instagram_state:
        ig_context = await new_context(browser, storage_state=instagram_state)
        ig_page = await ig_context.new_page()

    try:
        while True:
            try:
                index, total, channel_url = queue.get_nowait()
            except asyncio.QueueEmpty:
                return

            print(f"   [{name}] ({index}/{total}) {channel_url}")

            try:
                result = await scrape_channel(yt_page, ig_page, skool_page, channel_url)
            except Exception as exc:
                print(f"         Unhandled error: {exc}")
                result = {'status': f"error: {type(exc).__name__}"}

            # Rows outside the range are kept but flagged, so moving the bounds
            # later does not mean scraping everything again.
            count = result.get('subscriber_count')
            if count is not None:
                if min_subscribers and count < min_subscribers:
                    result['status'] = 'below_min_subscribers'
                    print(f"         Below range ({count:,} < {min_subscribers:,})")
                elif max_subscribers and count > max_subscribers:
                    result['status'] = 'above_max_subscribers'
                    print(f"         Above range ({count:,} > {max_subscribers:,})")

            await writer.write(channel_url, result)

            if delay:
                await asyncio.sleep(delay)
    finally:
        for context in (yt_context, skool_context, ig_context):
            if context:
                try:
                    await context.close()
                except Exception:
                    pass


def read_terms(args):
    """Search terms from --search (repeatable) and/or --search-file."""
    terms = list(args.search or [])

    if args.search_file:
        if not os.path.exists(args.search_file):
            print(f"Search-term file not found: {args.search_file}")
            return []
        with open(args.search_file, encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if line and not line.startswith('#') and line not in terms:
                    terms.append(line)

    return terms


def apply_limits(urls, args):
    """Apply --limit and --resume to a channel list."""
    if args.limit:
        urls = urls[:args.limit]
        print(f"Limited to first {len(urls)} channels")

    if args.resume:
        done = already_scraped(args.output)
        if done:
            before = len(urls)
            urls = [u for u in urls if u.rstrip('/').lower() not in done]
            print(f"Resuming: skipping {before - len(urls)} already-scraped channels")

    return urls


async def launch_browser(playwright, args):
    launcher = getattr(playwright, args.browser)
    launch_kwargs = {'headless': not args.headed}
    if args.executable_path:
        launch_kwargs['executable_path'] = args.executable_path
    browser = await launcher.launch(**launch_kwargs)
    print(f"Started {args.browser} ({'headed' if args.headed else 'headless'})")
    return browser


async def run(args):
    terms = read_terms(args)

    # Without search terms the channel list has to come from a file, and it is
    # worth failing before launching a browser.
    urls = []
    if not terms:
        urls = apply_limits(read_input(args.input), args)
        if not urls:
            print("Nothing to scrape.")
            return 1

    instagram_state = load_instagram_state(args.instagram_state)
    writer = ResultWriter(args.output, resume=args.resume)

    playwright = None
    browser = None

    try:
        playwright = await async_playwright().start()
        browser = await launch_browser(playwright, args)

        if terms:
            urls = apply_limits(await run_discovery(browser, terms, args), args)
            if args.save_discovered:
                with open(args.save_discovered, 'w', encoding='utf-8') as handle:
                    handle.write('\n'.join(urls) + '\n')
                print(f"Saved discovered channel list to {args.save_discovered}")

        if not urls:
            print("Nothing left to scrape.")
            return 0

        queue = asyncio.Queue()
        for index, url in enumerate(urls, 1):
            queue.put_nowait((index, len(urls), url))

        concurrency = max(1, min(args.concurrency, len(urls)))
        print(f"\nScraping {len(urls)} channels with {concurrency} workers\n")

        await asyncio.gather(*[
            worker(f"w{i + 1}", queue, writer, browser, instagram_state,
                   args.delay, args.min_subscribers, args.max_subscribers)
            for i in range(concurrency)
        ])

        print(f"\nDone. Wrote {writer.count} rows to {args.output}")
        return 0

    except Exception as exc:
        print(f"\nRun failed: {exc}")
        print(f"Partial results are in {args.output} ({writer.count} rows). "
              f"Re-run with --resume to continue.")
        return 1

    finally:
        writer.close()
        if browser:
            await browser.close()
        if playwright:
            await playwright.stop()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='Scrape YouTube channel details, from a URL list or from search.'
    )
    parser.add_argument('--input', default='youtube_filtered.csv',
                        help='CSV or .txt file of channel URLs (default: youtube_filtered.csv). '
                             'Ignored when --search or --search-file is given.')

    discovery = parser.add_argument_group('discovery (search instead of a URL list)')
    discovery.add_argument('--search', action='append', metavar='TERM',
                           help='Search term to discover channels from. Repeatable.')
    discovery.add_argument('--search-file', metavar='PATH',
                           help='File of search terms, one per line')
    discovery.add_argument('--duration', choices=sorted(DURATION),
                           help="Video length filter: 'long' is 20+ minutes, "
                                "'medium' 4-20, 'short' under 4")
    discovery.add_argument('--upload-date', choices=sorted(UPLOAD_DATE),
                           help='Only results uploaded within this window')
    discovery.add_argument('--result-type', choices=sorted(RESULT_TYPE),
                           help="Restrict results to one type, e.g. 'channel'")
    discovery.add_argument('--sort-by', choices=sorted(SORT_BY),
                           help='Search result ordering (default: relevance)')
    discovery.add_argument('--scrolls', type=int, default=4,
                           help='Result pages to load per term (default: 4)')
    discovery.add_argument('--per-term', type=int, default=25,
                           help='Max channels to keep per search term (default: 25)')
    discovery.add_argument('--save-discovered', metavar='PATH',
                           help='Also write the discovered channel URLs to this file')
    discovery.add_argument('--min-subscribers', type=int, default=0,
                           help='Flag channels below this count as below_min_subscribers')
    discovery.add_argument('--max-subscribers', type=int, default=0,
                           help='Flag channels above this count as above_max_subscribers')

    parser.add_argument('--output', default='youtube_scraped_details.csv',
                        help='Where to write results (default: youtube_scraped_details.csv)')
    parser.add_argument('--concurrency', type=int, default=3,
                        help='Channels scraped in parallel (default: 3)')
    parser.add_argument('--limit', type=int, default=0,
                        help='Only scrape the first N channels')
    parser.add_argument('--delay', type=float, default=0.5,
                        help='Seconds to pause between channels per worker (default: 0.5)')
    parser.add_argument('--browser', default='chromium',
                        choices=['chromium', 'webkit', 'firefox'],
                        help='Playwright browser to use (default: chromium)')
    parser.add_argument('--headed', action='store_true',
                        help='Show the browser window (default: headless)')
    parser.add_argument('--executable-path', default=None,
                        help='Explicit browser binary, if Playwright cannot find one')
    parser.add_argument('--instagram-state', default='instagram_storage_state.json',
                        help='Playwright storage state with Instagram cookies '
                             '(default: instagram_storage_state.json)')
    parser.add_argument('--resume', action='store_true',
                        help='Skip channels already present in the output file')
    return parser.parse_args(argv)


def main():
    args = parse_args()
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nInterrupted. Partial results were already written; "
              "re-run with --resume to continue.")
        return 130


if __name__ == '__main__':
    sys.exit(main())
