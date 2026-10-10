#!/usr/bin/env python3
"""
Tests for the Lead Generator spec.

The nine fixtures are the lesson's own examples. Values the lesson does not
state are filled with numbers consistent with the label it gives, per the spec.

    python test_lead_generator.py
"""

import sys

from lead_generator import (
    Config, Creator, classify_niche, detect_monetization, rate_roti,
    view_stats, to_row, ALL_COLUMNS, SHEET_COLUMNS,
)

FAILURES = []


def check(label, got, want):
    if got == want:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}\n          got:  {got!r}\n          want: {want!r}")
        FAILURES.append(label)


# ---------------------------------------------------------------------------
# The lesson's nine examples
# ---------------------------------------------------------------------------

FIXTURES = [
    # name, sells, monetized, uploads_90d, median_views, niche_consistency,
    # days_since_last, expected
    ("lawn care, $47 guide, weekly",        True,  True, 13, 18000, 0.9,  5, "High"),
    ("finance, budgeting course, 2x week",  True,  True, 26, 18000, 0.9,  3, "High"),
    ("educational, $5k accelerator, weekly", True, True, 13, 12000, 0.9,  5, "High"),
    ("travel vlogger, twice a month",       False, True,  6,  8000, 0.8, 10, "Mid"),
    ("tech reviewer, affiliate only",       False, True,  5, 10000, 0.9, 12, "Mid"),
    ("cooking, free e-book, intermittent",  False, True,  3,  6000, 0.9, 20, "Mid"),
    ("no niche, every two months",          False, False, 1,   300, 0.3, 40, "Low"),
    ("variety, no monetization",            False, False, 6,   500, 0.35, 10, "Low"),
    ("20K subs, 400 views, gone quiet",     False, False, 2,   400, 0.8, 35, "Low"),
]


def test_fixtures():
    print("\nLesson fixtures")
    for (name, sells, monetized, uploads, views, niche, days, expected) in FIXTURES:
        c = Creator(
            creator_name=name,
            sells_product=sells,
            has_monetization=monetized,
            uploads_90d=uploads,
            median_views=views,
            avg_views=views,          # equal unless testing the outlier flag
            niche_consistency=niche,
            days_since_last_upload=days,
        )
        roti, reasons, review = rate_roti(c)
        check(name, roti, expected)


def test_fixture_nine_review():
    print("\nFixture 9 review flags")
    c = Creator(sells_product=False, has_monetization=False, uploads_90d=2,
                median_views=400, avg_views=400, niche_consistency=0.8,
                days_since_last_upload=35, subscriber_count=20000)
    roti, reasons, review = rate_roti(c)
    check("rating", roti, "Low")
    # 400 / 20000 = 0.02, under the 0.03 cold-audience ratio
    check("cold audience flagged", review, True)
    check("reason recorded",
          any('low for the subscriber count' in r for r in reasons), True)
    check("views_to_subs", c.views_to_subs, 0.02)


def test_every_high_is_flagged():
    print("\nEvery High is flagged for review")
    # Three of the seven High criteria cannot be scraped, so a scraped High is
    # only ever a candidate.
    for name, sells, monetized, uploads, views, niche, days, expected in FIXTURES:
        if expected != "High":
            continue
        c = Creator(sells_product=sells, has_monetization=monetized,
                    uploads_90d=uploads, median_views=views, avg_views=views,
                    niche_consistency=niche, days_since_last_upload=days)
        _, _, review = rate_roti(c)
        check(f"{name[:28]} flagged", review, True)


def test_outlier_and_median_rule():
    print("\nMedian rule and outlier flag")
    # One viral video: mean clears 3,000, median does not. use_median keeps it
    # out of High, which is the point of the default.
    c = Creator(sells_product=True, has_monetization=True, uploads_90d=13,
                avg_views=9000, median_views=900, niche_consistency=0.9,
                days_since_last_upload=5)
    roti, reasons, review = rate_roti(c, Config(use_median=True))
    check("median rule keeps it out of High", roti != "High", True)
    check("outlier flagged", any('carrying the average' in r for r in reasons), True)

    # The lesson's exact rule uses the mean.
    roti_mean, _, _ = rate_roti(c, Config(use_median=False))
    check("use_median=False promotes it", roti_mean, "High")


def test_low_override():
    print("\nThree low traits override monetization")
    # Sells something but has gone quiet with few views - the spec's addition.
    c = Creator(sells_product=True, has_monetization=True, uploads_90d=1,
                median_views=400, avg_views=400, niche_consistency=0.4,
                days_since_last_upload=60)
    roti, reasons, _ = rate_roti(c)
    check("rating", roti, "Low")
    check("no 'no monetization' reason",
          any('no monetization' in r for r in reasons), False)


def test_monetization_detection():
    print("\nMonetization and product type")
    r = detect_monetization("Grab the guide for $47", ["https://stan.store/me"])
    check("checkout -> sells", r['sells_product'], True)
    check("price captured", r['product_price_seen'], "$47")

    r = detect_monetization("Join my community", ["https://www.skool.com/x"])
    check("skool -> community", r['product_type'], 'community_or_membership')

    r = detect_monetization("Gear I use", ["https://amzn.to/abc"])
    check("affiliate not a product", r['sells_product'], False)
    check("affiliate is monetization", r['has_monetization'], True)
    check("affiliate_only type", r['product_type'], 'affiliate_only')

    r = detect_monetization("This video is sponsored by Squarespace, use code JB", [])
    check("sponsor detected", r['has_sponsors'], True)
    check("sponsor is monetization", r['has_monetization'], True)

    r = detect_monetization("Download my free checklist below", [])
    check("lead magnet monetizes", r['has_monetization'], True)
    check("lead magnet is not a product", r['sells_product'], False)
    check("lead_magnet_only", r['product_type'], 'lead_magnet_only')

    r = detect_monetization("Book a call with me", ["https://calendly.com/me"])
    check("booking -> coaching", r['product_type'], 'coaching_or_program')

    r = detect_monetization("All my links", ["https://linktr.ee/me"])
    check("link hub flagged", r['has_link_hub'], True)

    r = detect_monetization("Just a travel vlog about Lisbon", [])
    check("nothing found", r['has_monetization'], False)
    check("type none", r['product_type'], 'none')


def test_niche_classification():
    print("\nNiche classification")
    niche, consistency = classify_niche([
        "Best Places to Visit in Italy", "Travel Guide to Lisbon",
        "How to Pack for a Trip", "Cheap Flights Explained",
    ])
    check("travel", niche, 'travel')
    check("consistency", consistency, 1.0)

    niche, consistency = classify_niche([
        "Full Body Workout", "My Gym Routine", "Vlog: moving house",
        "Best Places to Visit in Italy",
    ])
    check("fitness wins the vote", niche, 'fitness')
    check("mixed consistency", consistency, 0.5)

    niche, consistency = classify_niche([
        "I tried this for 30 days", "Reacting to comments", "Q and A",
    ])
    check("no clear niche", consistency < 0.6, True)

    niche, _ = classify_niche(["BJJ rolling session", "Muay Thai sparring"])
    check("martial arts", niche, 'martial_arts')

    # The widened martial arts list, on titles phrased the way the channels
    # actually phrase them - the art is usually not named.
    niche, consistency = classify_niche([
        "How To Escape Side Control Every Time",
        "5 Mistakes Every Blue Belt Makes",
        "Heel Hook Entries From Half Guard",
        "Open Mat Highlights",
    ])
    check("technique titles without the art named", niche, 'martial_arts')
    check("martial consistency", consistency, 1.0)

    # Substring matching means a too-generic keyword steals travel titles,
    # which are the largest group in the pool. These must NOT read as martial.
    for title in ("Rolling Coasters At Universal Studios",
                  "Striking Views From The Amalfi Coast",
                  "48 Hours In Kathmandu",
                  "Controlling Your Budget On A Long Trip"):
        niche, _ = classify_niche([title])
        check(f"not martial: {title[:34]}", niche != 'martial_arts', True)

    # An unlabelled title is uninformative, not off-niche. Counting it against
    # the channel pushed every seller to 0.5 and blocked all 25 from High.
    niche, consistency = classify_niche([
        "WATCH THIS BEFORE YOU VISIT TURKS AND CAICOS",
        "All 9 California National Parks Ranked",
        "Best Beaches in Portugal",
    ])
    check("travel despite a keyword-free title", niche, 'travel')
    check("unlabelled title does not drag consistency", consistency, 1.0)

    # A channel genuinely split between topics still scores low.
    _, consistency = classify_niche(["Full Body Workout", "Best Beaches in Portugal"])
    check("genuinely mixed stays low", consistency, 0.5)


def test_view_stats():
    print("\nView statistics")
    avg, med, trend = view_stats([1000] * 15)
    check("flat avg", avg, 1000)
    check("flat median", med, 1000)
    check("flat trend", trend, 1.0)

    avg, med, _ = view_stats([100000] + [1000] * 9)
    check("outlier pulls mean up", avg > med * 2, True)

    avg, med, trend = view_stats([])
    check("empty", (avg, med, trend), (0, 0, None))

    # Last 5 at 2000 against the 10 before at 1000.
    _, _, trend = view_stats([2000] * 5 + [1000] * 10)
    check("rising trend", trend, 2.0)


def test_row_shape():
    print("\nOutput row")
    c = Creator(creator_name="Test", channel_url="https://youtube.com/@t",
                sells_product=True, median_views=5000, avg_views=5000,
                uploads_90d=13, niche_consistency=0.9, days_since_last_upload=3)
    roti, reasons, review = rate_roti(c)
    row = to_row(c, roti, reasons, review)

    check("all columns present", sorted(row.keys()), sorted(ALL_COLUMNS))
    check("sheet columns come first",
          list(row.keys())[:17], SHEET_COLUMNS)
    check("sells rendered as Yes", row['Do They Sell a Product'], 'Yes')
    check("manual columns left blank",
          all(row[k] == '' for k in SHEET_COLUMNS[9:]), True)


def test_live_payload_formats():
    """Formats taken from a real Videos tab dump, not from what I expected."""
    print("\nLive payload formats")
    from run_lead_generator import parse_views, clean_title, duration_seconds

    # YouTube spells the magnitude out in the accessibility label.
    check("111 thousand views", parse_views("111 thousand views"), 111000)
    check("1.2 million views", parse_views("1.2 million views"), 1200000)
    check("2.4 billion views", parse_views("2.4 billion views"), 2400000000)
    # Short counts print in full, which is all the old regex ever matched.
    check("562 views", parse_views("562 views"), 562)
    check("abbreviated still works", parse_views("48K views"), 48000)
    check("no views", parse_views("No views"), None)

    # The title label carries the duration on the end.
    check("title strips duration",
          clean_title("WATCH THIS BEFORE YOU VISIT TURKS AND CAICOS 26 minutes"),
          "WATCH THIS BEFORE YOU VISIT TURKS AND CAICOS")
    check("title strips compound duration",
          clean_title("Some Title 1 hour, 2 minutes"), "Some Title")
    check("title without duration untouched",
          clean_title("Title With No Duration"), "Title With No Duration")

    check("duration text", duration_seconds("26:28"), 1588)


def main():
    test_fixtures()
    test_fixture_nine_review()
    test_every_high_is_flagged()
    test_outlier_and_median_rule()
    test_low_override()
    test_monetization_detection()
    test_niche_classification()
    test_view_stats()
    test_row_shape()
    test_live_payload_formats()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("All tests passed")
    return 0


if __name__ == '__main__':
    sys.exit(main())
