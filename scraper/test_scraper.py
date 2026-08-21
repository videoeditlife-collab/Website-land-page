#!/usr/bin/env python3
"""
Tests for youtube_scraper.

Covers the parsing layer directly, then runs the scraper end to end against a
locally served fake YouTube About page so the browser path is exercised too.

    python test_scraper.py
"""

import asyncio
import csv
import http.server
import json
import os
import socket
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import youtube_scraper  # noqa: E402
from youtube_scraper import (  # noqa: E402
    matches_niche,
    classify_creator,
    classify_cadence,
    meets_cadence,
    parse_relative_age,
    video_ages_from_data,
    build_search_filter,
    channel_urls_from_hrefs,
    read_terms,
    search_url,
    channel_about_url,
    extract_json_blob,
    has_business_email,
    links_from_page,
    normalize_instagram_url,
    normalize_skool_url,
    parse_args,
    parse_count,
    parse_followers,
    parse_members,
    parse_subscribers,
    resolve_redirect,
    channel_name_from_html,
    subscribers_from_data,
    run,
)

FAILURES = []


def check(label, got, want):
    if got == want:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}\n          got:  {got!r}\n          want: {want!r}")
        FAILURES.append(label)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def youtube_about_html(name, subs, links, email=True):
    data = {
        "contents": {
            "aboutChannelViewModel": {
                "description": "Test channel description",
                "subscriberCountText": subs,
                "viewCountText": "123,456,789 views",
                "videoCountText": "150 videos",
                "links": [
                    {
                        "channelExternalLinkViewModel": {
                            "title": {"content": title},
                            "link": {
                                "content": bare,
                                "commandRuns": [{
                                    "onTap": {"innertubeCommand": {"urlEndpoint": {
                                        "url": redirect
                                    }}}
                                }],
                            },
                        }
                    }
                    for title, bare, redirect in links
                ],
            }
        }
    }
    if email:
        data["contents"]["aboutChannelViewModel"]["signInForBusinessEmail"] = (
            "Sign in to see email address"
        )

    return f"""<!DOCTYPE html><html><head>
<meta property="og:title" content="{name}">
<title>{name} - YouTube</title>
</head><body>
<script>var ytInitialData = {json.dumps(data)};</script>
<div id="content">150 videos</div>
</body></html>"""


INSTAGRAM_HTML = (
    '<html><head><meta property="og:description" '
    'content="48.2K Followers, 812 Following, 431 Posts - See Instagram photos">'
    '</head><body></body></html>'
)

SKOOL_HTML = (
    '<html><head><meta property="og:title" content="Test Community | Skool">'
    '</head><body><div>2,481 Members</div></body></html>'
)


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

def test_counts():
    print("\nCount parsing")
    check("1.2M subscribers", parse_subscribers("1.2M subscribers"), 1_200_000)
    check("50K subscribers", parse_subscribers("50K subscribers"), 50_000)
    check("1,234 subscribers", parse_subscribers("1,234 subscribers"), 1_234)
    check("2.4B subscribers", parse_subscribers("2.4B subscribers"), 2_400_000_000)
    check("No subscribers", parse_subscribers("No subscribers"), None)

    # The old bug: any number was accepted as a subscriber count.
    check("'150 videos' rejected", parse_subscribers("150 videos"), None)
    check("'1.2M views' rejected", parse_subscribers("1.2M views"), None)
    check("'89 posts' rejected", parse_followers("89 posts"), None)

    # The old bug: no-suffix calls skipped lowercasing and returned 1.
    check("bare '1.2K'", parse_count("1.2K"), 1_200)
    check("bare '12,345'", parse_count("12,345"), 12_345)
    check("bare '1.234'", parse_count("1.234"), 1_234)

    check("48.2K followers", parse_followers("48.2K followers"), 48_200)
    check("2,481 Members", parse_members("2,481 Members"), 2_481)
    check("empty", parse_count(""), None)
    check("None", parse_count(None), None)


def test_urls():
    print("\nURL handling")
    check(
        "redirect unwrap",
        resolve_redirect(
            "https://www.youtube.com/redirect?q=https%3A%2F%2Fwww.instagram.com%2Ffoo%2F"
        ),
        "https://www.instagram.com/foo/",
    )
    check(
        "redirect without scheme",
        resolve_redirect("https://www.youtube.com/redirect?q=instagram.com%2Ffoo"),
        "https://instagram.com/foo",
    )
    check("non-redirect passthrough",
          resolve_redirect("https://skool.com/x"), "https://skool.com/x")

    check("ig bare", normalize_instagram_url("instagram.com/foo"),
          "https://www.instagram.com/foo")
    check("ig handle", normalize_instagram_url("foo"), "https://www.instagram.com/foo")

    check("skool about", normalize_skool_url("https://www.skool.com/mygroup"),
          "https://www.skool.com/mygroup/about")
    check("skool utm stripped",
          normalize_skool_url("https://www.skool.com/mygroup?utm_source=yt"),
          "https://www.skool.com/mygroup/about")
    check("skool already about",
          normalize_skool_url("skool.com/mygroup/about"),
          "https://www.skool.com/mygroup/about")
    check("skool junk", normalize_skool_url("https://example.com/x"), None)

    check("about from handle", channel_about_url("https://www.youtube.com/@foo"),
          "https://www.youtube.com/@foo/about")
    check("about from /videos", channel_about_url("https://www.youtube.com/@foo/videos"),
          "https://www.youtube.com/@foo/about")
    check("about from channel id",
          channel_about_url("https://www.youtube.com/channel/UC123/featured"),
          "https://www.youtube.com/channel/UC123/about")


def test_extraction():
    print("\nPage extraction")
    html = youtube_about_html(
        "Test Creator",
        "1.2M subscribers",
        [
            ("Instagram", "instagram.com/testcreator",
             "https://www.youtube.com/redirect?q=https%3A%2F%2Fwww.instagram.com%2Ftestcreator%2F"),
            ("Skool", "skool.com/testcommunity",
             "https://www.youtube.com/redirect?q=https%3A%2F%2Fwww.skool.com%2Ftestcommunity"),
        ],
    )
    data = extract_json_blob(html, 'ytInitialData')

    check("json blob parsed", isinstance(data, dict), True)
    check("channel name", channel_name_from_html(html, data), "Test Creator")
    check("subscribers", subscribers_from_data(data), ("1.2M subscribers", 1_200_000))
    check("email detected", has_business_email(html, data), True)

    igs = links_from_page(html, data, 'instagram.com')
    check("instagram link", igs[0] if igs else None,
          "https://www.instagram.com/testcreator/")

    skools = links_from_page(html, data, 'skool.com')
    check("skool link", skools[0] if skools else None,
          "https://www.skool.com/testcommunity")

    # "150 videos" appears in the JSON and the DOM; it must not become a sub count.
    no_subs = youtube_about_html("No Subs", "", [], email=False)
    no_subs_data = extract_json_blob(no_subs, 'ytInitialData')
    check("no false subscriber count", subscribers_from_data(no_subs_data), (None, None))
    check("no false email", has_business_email(no_subs, no_subs_data), False)

    check("blob missing", extract_json_blob("<html></html>", 'ytInitialData'), None)


def test_profile_regexes():
    print("\nInstagram / Skool page parsing")
    import re
    from youtube_scraper import _unescape_html

    m = re.search(r'content="([\d.,]+[KMB]?)\s+Followers', INSTAGRAM_HTML, re.IGNORECASE)
    check("ig followers found", m.group(1) if m else None, "48.2K")
    check("ig followers parsed",
          parse_followers(f"{m.group(1)} followers") if m else None, 48_200)

    m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', SKOOL_HTML, re.I)
    name = re.split(r'\s*\|\s*', _unescape_html(m.group(1)))[0].strip() if m else None
    check("skool name", name, "Test Community")

    m = re.search(r'([\d.,]+\s*[KMB]?)\s*(?:Members?|member)', SKOOL_HTML, re.I)
    check("skool members parsed", parse_members(m.group(0)) if m else None, 2_481)


def videos_tab_html(ages):
    """
    Fake Videos tab in the shape YouTube actually serves today: each entry is a
    lockupViewModel keyed by contentId, with the upload date in a bare
    {'content': '3 weeks ago'} node and repeated in an accessibility label.

    This mirrors the structure reported by diagnose_videos.py against a live
    channel. The previous fixture used videoRenderer/publishedTimeText, which
    the live page no longer emits at all - so the tests passed while the
    scraper returned nothing.
    """
    items = [
        {"richItemRenderer": {"content": {"lockupViewModel": {
            "contentId": f"vid{index:05d}",
            "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
            "metadata": {"lockupMetadataViewModel": {
                "title": {"content": f"Video {index}"},
                "metadata": {"contentMetadataViewModel": {"metadataRows": [
                    {"metadataParts": [
                        {"text": {"content": "12K views"}},
                        {"text": {"content": age}},
                    ]},
                ]}},
                "image": {"decoratedAvatarViewModel": {
                    "accessibilityLabel": f"Video {index} 12K views {age}",
                }},
            }},
        }}}}
        for index, age in enumerate(ages)
    ]
    data = {"contents": {"tabs": [{"tabRenderer": {"content": {
        "richGridRenderer": {"contents": items}
    }}}]}}
    return (f'<!DOCTYPE html><html><head><title>Videos</title></head><body>'
            f'<script>var ytInitialData = {json.dumps(data)};</script>'
            f'</body></html>')


def legacy_videos_tab_html(ages):
    """The older videoRenderer/publishedTimeText shape, kept as a fallback."""
    items = [
        {"richItemRenderer": {"content": {"videoRenderer": {
            "videoId": f"old{index:05d}",
            "publishedTimeText": {"simpleText": age},
        }}}}
        for index, age in enumerate(ages)
    ]
    data = {"contents": {"richGridRenderer": {"contents": items}}}
    return (f'<!DOCTYPE html><html><body>'
            f'<script>var ytInitialData = {json.dumps(data)};</script>'
            f'</body></html>')


def test_upload_cadence():
    print("\nUpload cadence")
    check("3 weeks ago", parse_relative_age("3 weeks ago"), 21.0)
    check("1 day ago", parse_relative_age("1 day ago"), 1.0)
    check("Streamed 2 months ago",
          round(parse_relative_age("Streamed 2 months ago"), 2), 60.88)
    check("13 hours ago", round(parse_relative_age("13 hours ago"), 3), 0.542)
    check("no date", parse_relative_age("Members only"), None)
    check("empty", parse_relative_age(""), None)

    # Live shape: lockupViewModel, date repeated in an accessibility label.
    data = extract_json_blob(
        videos_tab_html(["2 days ago", "9 days ago", "16 days ago"]),
        'ytInitialData',
    )
    check("lockup ages parsed", video_ages_from_data(data), [2.0, 9.0, 16.0])

    # The repeated label must not be counted as a second upload.
    check("repeated date not double counted",
          len(video_ages_from_data(data)), 3)

    # Legacy shape still works via the fallback.
    legacy = extract_json_blob(
        legacy_videos_tab_html(["1 day ago", "8 days ago"]), 'ytInitialData')
    check("legacy ages parsed", video_ages_from_data(legacy), [1.0, 8.0])

    check("no data", video_ages_from_data(None), [])

    weekly = [float(d) for d in range(2, 92, 7)]      # 13 uploads in 90 days
    check("weekly", classify_cadence(weekly)[0], "weekly")
    check("weekly last upload", classify_cadence(weekly)[1], 2)
    check("weekly count", classify_cadence(weekly)[2], 13)

    check("biweekly", classify_cadence([3.0, 17.0, 31.0, 45.0, 59.0, 73.0])[0],
          "biweekly")
    check("monthly", classify_cadence([5.0, 35.0, 65.0])[0], "monthly")
    check("sporadic", classify_cadence([10.0, 200.0])[0], "sporadic")
    check("inactive", classify_cadence([120.0, 300.0])[0], "inactive")
    check("dormant", classify_cadence([400.0])[0], "dormant")
    check("unknown", classify_cadence([]), ('unknown', None, 0))

    check("weekly meets monthly", meets_cadence('weekly', 'monthly'), True)
    check("monthly fails weekly", meets_cadence('monthly', 'weekly'), False)
    check("monthly meets monthly", meets_cadence('monthly', 'monthly'), True)
    check("dormant fails monthly", meets_cadence('dormant', 'monthly'), False)
    check("no requirement", meets_cadence('dormant', None), True)


def test_creator_type():
    print("\nSolo creator vs business")
    # Every case below is a real description and link set from the seed scrape.
    check("tour site -> business",
          classify_creator("Benidorm by Ana",
                           "Welcome to Benidorm, Costa Blanca and other Holiday Destinations",
                           ["https://www.benidormbyanatours.com",
                            "https://www.instagram.com/benidormbyana/"]),
          "business")
    check("'we offer' -> business",
          classify_creator("MMT Holiday Expert",
                           "As the Holiday Pro, we offer practical tips and reviews", []),
          "business")
    check("B2B in name -> business",
          classify_creator("TRAVEL BOX B2B HOLIDAY EXPERT", "", []), "business")

    check("first person -> solo",
          classify_creator("Holiday Expert",
                           "My name's Chelsea and I'm a holiday expert!",
                           ["https://holidayexpert.com/"]),
          "solo")
    check("lived-there -> solo",
          classify_creator("Benidorm Channel",
                           "Hi! I'm Michael, a Dutch guy who's been living in Benidorm",
                           []),
          "solo")
    check("couple -> solo",
          classify_creator("Paul and Carole",
                           "We are a fun loving married couple who love to travel", []),
          "solo")
    check("support link -> solo",
          classify_creator("Some Channel", "",
                           ["https://www.buymeacoffee.com/x"]), "solo")

    # An affiliate link is monetisation, not a tour business.
    check("affiliate link stays solo",
          classify_creator("Reviewer", "My name's Sam",
                           ["https://amzn.to/abc"]), "solo")

    check("no signal -> unclear",
          classify_creator("Benidorm Enthusiast",
                           "Benidorm is located on the Costa Blanca, Spain.", []),
          "unclear")


def test_niche():
    print("\nNiche relevance")
    # Real names and descriptions from the 283-channel search run.
    check("cruise channel", matches_niche("Eat Sleep Cruise", "cruise tips"), True)
    check("travel in name",
          matches_niche("Happy to Wander (Travel Tips & Inspo)", ""), True)
    check("general vlogger rejected",
          matches_niche("Ryan Trahan", "just a guy"), False)
    check("fitness rejected",
          matches_niche("Mike Thurston", "For business enquiries"), False)
    check("kids channel rejected",
          matches_niche("Ozzie - Educational Videos For Kids",
                        "Australian kid's entertainer"), False)
    check("resort wording", matches_niche("Some Channel", "all inclusive resort reviews"), True)
    check("empty", matches_niche("", ""), False)


def test_search_filters():
    print("\nSearch filter encoding")
    # These are the values YouTube itself puts in the sp= parameter, so they
    # pin the protobuf encoding to something externally verifiable.
    check("duration=long", build_search_filter(duration='long'), "EgIYAg==")
    check("upload_date=year", build_search_filter(upload_date='year'), "EgIIBQ==")
    check("result_type=channel", build_search_filter(result_type='channel'), "EgIQAg==")
    check("duration=medium", build_search_filter(duration='medium'), "EgIYAw==")
    check("year + long", build_search_filter(duration='long', upload_date='year'),
          "EgQIBRgC")
    check("sort_by=views", build_search_filter(sort_by='views'), "CAM=")
    check("sort default omitted", build_search_filter(sort_by='relevance'), None)
    check("no filters", build_search_filter(), None)

    check("search url",
          search_url("travel vlog", "EgIYAg=="),
          "https://www.youtube.com/results?search_query=travel+vlog&sp=EgIYAg%3D%3D")
    check("search url unfiltered",
          search_url("van life australia"),
          "https://www.youtube.com/results?search_query=van+life+australia")


def test_channel_hrefs():
    print("\nChannel link extraction")
    hrefs = [
        "/@traveller",
        "/@traveller/videos",              # same channel, different tab
        "/channel/UCabcdefghijklmnopqrstuv",
        "/watch?v=abc123",                 # not a channel
        "/results?search_query=x",         # not a channel
        "/@Another_One-1",
        None,
        "https://external.example/@nope",  # not a relative YouTube link
    ]
    check("extracted", channel_urls_from_hrefs(hrefs), [
        "https://www.youtube.com/@traveller",
        "https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv",
        "https://www.youtube.com/@Another_One-1",
    ])
    check("empty input", channel_urls_from_hrefs([]), [])


def test_output_roundtrip():
    print("\nOutput CSV reads back as input")
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, 'results.csv')

    from youtube_scraper import CSV_HEADER, read_input
    with open(path, 'w', newline='') as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_HEADER)
        row = [''] * len(CSV_HEADER)
        row[CSV_HEADER.index('YT Channel')] = 'https://www.youtube.com/@one'
        writer.writerow(row)
        row2 = [''] * len(CSV_HEADER)
        row2[CSV_HEADER.index('YT Channel')] = 'https://www.youtube.com/@two'
        writer.writerow(row2)

    check("results file reads back",
          read_input(path),
          ['https://www.youtube.com/@one', 'https://www.youtube.com/@two'])


def test_terms():
    print("\nSearch term input")
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, 'terms.txt')
    with open(path, 'w') as fh:
        fh.write("# comment\ntravel vlog\n\nvan life\ntravel vlog\n")

    args = parse_args(['--search', 'solo travel', '--search-file', path])
    check("merged and deduped", read_terms(args),
          ["solo travel", "travel vlog", "van life"])
    check("no terms", read_terms(parse_args([])), [])


def test_cli():
    print("\nCLI")
    args = parse_args([])
    check("default input", args.input, "youtube_filtered.csv")
    check("default concurrency", args.concurrency, 3)
    check("default headless", args.headed, False)
    args = parse_args(['--input', 'x.csv', '--concurrency', '8', '--headed', '--resume'])
    check("parsed input", args.input, "x.csv")
    check("parsed concurrency", args.concurrency, 8)
    check("parsed resume", args.resume, True)


# ---------------------------------------------------------------------------
# End-to-end test against a local fake YouTube
# ---------------------------------------------------------------------------

PAGES = {
    "/@testcreator/about": youtube_about_html(
        "Test Creator", "1.2M subscribers",
        [("Instagram", "instagram.com/testcreator",
          "https://www.youtube.com/redirect?q=https%3A%2F%2Fwww.instagram.com%2Ftestcreator%2F")],
    ),
    "/@plaincreator/about": youtube_about_html(
        "Plain Creator", "8,432 subscribers", [], email=False
    ),
    "/@nosubs/about": youtube_about_html("No Subs Creator", "", [], email=False),
    # skool.com is unreachable from the test environment, which is the point:
    # the link must survive even when the community page cannot be read.
    "/@skoolcreator/about": youtube_about_html(
        "Skool Creator", "12.5K subscribers",
        [("Skool", "skool.com/testcommunity",
          "https://www.youtube.com/redirect?q=https%3A%2F%2Fwww.skool.com%2Ftestcommunity")],
    ),
    # In the subscriber band but has not posted in over a year.
    "/@lazycreator/about": youtube_about_html(
        "Lazy Creator", "45K subscribers", [], email=False
    ),

    # Videos tabs. 13 uploads over 90 days reads as weekly.
    "/@testcreator/videos": videos_tab_html(
        [f"{d} days ago" for d in range(2, 92, 7)]
    ),
    "/@plaincreator/videos": videos_tab_html(
        ["1 month ago", "2 months ago", "3 months ago"]
    ),
    "/@nosubs/videos": videos_tab_html(["5 days ago", "1 month ago", "2 months ago"]),
    "/@skoolcreator/videos": videos_tab_html(
        [f"{d} days ago" for d in range(1, 90, 6)]
    ),
    "/@lazycreator/videos": videos_tab_html(["2 years ago", "3 years ago"]),
}


SEARCH_HTML = """<!DOCTYPE html><html><body>
<a href="/@testcreator">Test Creator</a>
<a href="/@testcreator/videos">Test Creator videos</a>
<a href="/watch?v=abc123">A video</a>
<a href="/@plaincreator">Plain Creator</a>
<a href="/results?search_query=other">Related search</a>
<a href="/@skoolcreator">Skool Creator</a>
<a href="/@lazycreator">Lazy Creator</a>
</body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?')[0]
        body = SEARCH_HTML if path == '/results' else PAGES.get(path)
        self.send_response(200 if body else 404)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write((body or "<html><body>404</body></html>").encode())

    def log_message(self, *args):
        pass


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def test_end_to_end():
    print("\nEnd-to-end (real browser, local fake YouTube)")

    chrome = '/opt/pw-browsers/chromium-1194/chrome-linux/chrome'
    if not os.path.exists(chrome):
        chrome = None

    port = free_port()
    server = http.server.HTTPServer(('127.0.0.1', port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    tmpdir = tempfile.mkdtemp()
    in_path = os.path.join(tmpdir, 'channels.txt')
    out_path = os.path.join(tmpdir, 'out.csv')

    with open(in_path, 'w') as fh:
        fh.write(f"http://127.0.0.1:{port}/@testcreator\n")
        fh.write(f"http://127.0.0.1:{port}/@plaincreator\n")
        fh.write(f"http://127.0.0.1:{port}/@nosubs\n")
        fh.write(f"http://127.0.0.1:{port}/@skoolcreator\n")
        fh.write(f"http://127.0.0.1:{port}/@testcreator\n")  # duplicate

    argv = ['--input', in_path, '--output', out_path,
            '--concurrency', '2', '--delay', '0',
            '--instagram-state', '/nonexistent.json']
    if chrome:
        argv += ['--executable-path', chrome]

    code = asyncio.run(run(parse_args(argv)))
    server.shutdown()
    server.server_close()

    check("exit code", code, 0)

    with open(out_path, newline='') as fh:
        rows = list(csv.DictReader(fh))

    check("row count (duplicate dropped)", len(rows), 4)

    by_name = {r['Display Name']: r for r in rows}
    check("names", sorted(by_name),
          ["No Subs Creator", "Plain Creator", "Skool Creator", "Test Creator"])

    tc = by_name.get('Test Creator', {})
    check("subscribers", tc.get('YT Subscribers'), "1200000")
    check("email", tc.get('Email'), "Email in YouTube Bio")
    check("instagram", tc.get('IG Account'), "https://www.instagram.com/testcreator/")
    check("status", tc.get('Status'), "ok")

    pc = by_name.get('Plain Creator', {})
    check("plain subscribers", pc.get('YT Subscribers'), "8432")
    check("plain no email", pc.get('Email'), "")

    ns = by_name.get('No Subs Creator', {})
    check("missing subs flagged", ns.get('Status'), "no_subscriber_count")

    # The old code dropped the Skool URL whenever the member count failed to parse.
    sc = by_name.get('Skool Creator', {})
    check("skool link kept despite unreachable page",
          sc.get('Skool Link'), "https://www.skool.com/testcommunity/about")
    check("skool creator subscribers", sc.get('YT Subscribers'), "12500")

    # Resume must skip everything already written.
    argv2 = list(argv) + ['--resume']
    server2 = http.server.HTTPServer(('127.0.0.1', port), Handler)
    threading.Thread(target=server2.serve_forever, daemon=True).start()
    asyncio.run(run(parse_args(argv2)))
    server2.shutdown()
    server2.server_close()

    with open(out_path, newline='') as fh:
        rows_after = list(csv.DictReader(fh))
    check("resume added no rows", len(rows_after), 4)


def test_discovery_end_to_end():
    print("\nDiscovery end-to-end (search -> scrape, local fixture server)")

    chrome = '/opt/pw-browsers/chromium-1194/chrome-linux/chrome'
    if not os.path.exists(chrome):
        chrome = None

    port = free_port()
    server = http.server.HTTPServer(('127.0.0.1', port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    tmpdir = tempfile.mkdtemp()
    out_path = os.path.join(tmpdir, 'discovered.csv')
    list_path = os.path.join(tmpdir, 'channels_found.txt')

    original_base = youtube_scraper.YOUTUBE_BASE
    youtube_scraper.YOUTUBE_BASE = f"http://127.0.0.1:{port}"

    argv = ['--search', 'travel vlog', '--duration', 'long',
            '--output', out_path, '--save-discovered', list_path,
            '--scrolls', '1', '--concurrency', '2', '--delay', '0',
            '--min-subscribers', '10000', '--max-subscribers', '200000',
            '--require-cadence', 'monthly',
            '--instagram-state', '/nonexistent.json']
    if chrome:
        argv += ['--executable-path', chrome]

    try:
        code = asyncio.run(run(parse_args(argv)))
    finally:
        youtube_scraper.YOUTUBE_BASE = original_base
        server.shutdown()
        server.server_close()

    check("exit code", code, 0)

    with open(list_path) as fh:
        discovered = [line.strip() for line in fh if line.strip()]
    check("discovered 4 channels (video/search links ignored)", len(discovered), 4)

    with open(out_path, newline='') as fh:
        rows = list(csv.DictReader(fh))
    check("scraped every discovered channel", len(rows), 4)

    by_name = {r['Display Name']: r for r in rows}
    check("discovered names", sorted(by_name),
          ["Lazy Creator", "Plain Creator", "Skool Creator", "Test Creator"])

    # The 10k-200k band: 12.5K is in, 8,432 is under, 1.2M is over.
    check("12.5K in range and active", by_name['Skool Creator']['Status'], "ok")
    check("8,432 under range",
          by_name['Plain Creator']['Status'], "below_min_subscribers")
    check("1.2M over range",
          by_name['Test Creator']['Status'], "above_max_subscribers")

    # In the band, but two years since the last upload.
    check("dormant channel rejected",
          by_name['Lazy Creator']['Status'], "cadence_dormant")
    check("dormant cadence recorded", by_name['Lazy Creator']['Cadence'], "dormant")

    check("weekly cadence recorded", by_name['Skool Creator']['Cadence'], "weekly")
    check("uploads in 90d", by_name['Skool Creator']['Uploads (90d)'], "15")


def main():
    test_counts()
    test_urls()
    test_extraction()
    test_profile_regexes()
    test_upload_cadence()
    test_creator_type()
    test_niche()
    test_search_filters()
    test_channel_hrefs()
    test_output_roundtrip()
    test_terms()
    test_cli()
    test_end_to_end()
    test_discovery_end_to_end()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("All tests passed")
    return 0


if __name__ == '__main__':
    sys.exit(main())
