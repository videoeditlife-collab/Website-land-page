#!/usr/bin/env python3
"""
Tests for pick_sellers.py - the product tiering and the exclusion.

The exclusion is the part worth testing. A filter that silently matches
nothing looks exactly like a filter that correctly found nothing: reading
only 'Channel Link' matched zero rows in every file written before the ROTI
work, and the run still printed "excluding 1,613 channels" while excluding
none of them. Every case below is one that failed silently at some point.

    python test_pick_sellers.py
"""

import csv
import os
import sys
import tempfile

from pick_sellers import (
    TIERS, RATING_RANK, channel_keys, normalise, is_agency, load, to_int,
)

FAILURES = []


def check(label, got, want):
    if got == want:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}\n          got:  {got!r}\n          want: {want!r}")
        FAILURES.append(label)


def write(directory, name, header, rows):
    path = os.path.join(directory, name)
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_normalise():
    print("\nURL normalisation")
    canonical = 'https://www.youtube.com/@creator'
    for variant in (
            'https://www.youtube.com/@creator',
            'https://www.youtube.com/@creator/',
            'https://youtube.com/@creator',
            'https://m.youtube.com/@creator',
            'HTTPS://WWW.YOUTUBE.COM/@Creator',
            'https://www.youtube.com/@creator/videos',
            'https://www.youtube.com/@creator/about',
            'https://www.youtube.com/@creator?sub_confirmation=1',
            '  https://www.youtube.com/@creator  ',
            '@creator',
    ):
        check(f"{variant.strip()[:44]} -> canonical", normalise(variant), canonical)

    check("channel id form kept", normalise('https://www.youtube.com/channel/UCabc'),
          'https://www.youtube.com/channel/UCabc')
    check("empty", normalise(''), '')
    check("not a url", normalise('Some Creator Name'), '')
    # A name with a space is not a handle, even if it starts with @.
    check("name with @ and space", normalise('@ some name'), '')


def test_channel_keys_column_names():
    print("\nExclusion reads every column name used across the passes")
    with tempfile.TemporaryDirectory() as directory:
        # The post-ROTI shape.
        a = write(directory, 'leads.csv',
                  ['Creator Name', 'Channel Link'],
                  [{'Creator Name': 'A', 'Channel Link': 'https://www.youtube.com/@a'}])
        # The pre-ROTI shape, which is most of what was already reported.
        b = write(directory, 'old.csv',
                  ['#', 'Display Name', 'YT Channel'],
                  [{'#': '1', 'Display Name': 'B',
                    'YT Channel': 'https://www.youtube.com/@b'}])
        # The editor scraper's shape.
        c = write(directory, 'editors.csv',
                  ['Editor', 'Credited By'],
                  [{'Editor': 'E', 'Credited By': 'https://www.youtube.com/@c'}])
        # Handles only, no URL anywhere.
        d = write(directory, 'drafts.csv',
                  ['Channel', 'Handle'],
                  [{'Channel': 'D Name', 'Handle': '@d'}])
        # A plain URL list.
        e = os.path.join(directory, 'discovered.txt')
        with open(e, 'w', encoding='utf-8') as handle:
            handle.write("# a comment\nhttps://www.youtube.com/@e\n\n")

        check("Channel Link", channel_keys(a), {'https://www.youtube.com/@a'})
        check("YT Channel", channel_keys(b), {'https://www.youtube.com/@b'})
        check("Credited By", channel_keys(c), {'https://www.youtube.com/@c'})
        check("Handle expanded", channel_keys(d), {'https://www.youtube.com/@d'})
        check("plain txt list", channel_keys(e), {'https://www.youtube.com/@e'})
        check("comment line ignored", '# a comment' in channel_keys(e), False)

    check("missing file is not fatal", channel_keys('/nonexistent/x.csv'), set())


def test_exclusion_catches_respelled_channel():
    print("\nA channel spelled differently is still excluded")
    reported = {normalise('https://www.youtube.com/@creator')}
    # The same channel as a scored row would carry it.
    for spelling in ('https://youtube.com/@creator',
                     'https://www.youtube.com/@creator/videos',
                     'https://www.youtube.com/@Creator'):
        check(f"excluded: {spelling[:46]}", normalise(spelling) in reported, True)
    check("a different channel is not excluded",
          normalise('https://www.youtube.com/@other') in reported, False)


def test_best_rating_wins_dedupe():
    print("\nDedupe keeps the strongest rating")
    with tempfile.TemporaryDirectory() as directory:
        header = ['Creator Name', 'Channel Link', 'Value Rating', 'Product Type',
                  'Subscriber Count', 'median_views']
        row = {'Creator Name': 'All The Gear',
               'Channel Link': 'https://www.youtube.com/@g',
               'Product Type': 'coaching_or_program',
               'Subscriber Count': '462000', 'median_views': '433000'}
        mid = write(directory, '1_challenge.csv', header,
                    [dict(row, **{'Value Rating': 'Mid'})])
        high = write(directory, '2_outdoor.csv', header,
                     [dict(row, **{'Value Rating': 'High'})])

        # Mid read first - the order that lost the High.
        rows = load([mid, high])
        check("one row for the channel", len(rows), 1)
        check("High kept when Mid came first", rows[0]['Value Rating'], 'High')

        # And the other way round.
        rows = load([high, mid])
        check("High kept when High came first", rows[0]['Value Rating'], 'High')

    check("rank order", RATING_RANK['High'] > RATING_RANK['Mid'] > RATING_RANK['Low'],
          True)


def test_product_tiers():
    print("\nProduct tiers")
    check("course is owned", TIERS['course'], 'owned')
    check("digital product is owned", TIERS['digital_product'], 'owned')
    check("coaching is owned", TIERS['coaching_or_program'], 'owned')
    check("membership is recurring", TIERS['community_or_membership'], 'recurring')
    check("merch is merch", TIERS['merch'], 'merch')
    # These are not products, and a High cannot rest on them.
    for absent in ('affiliate_only', 'sponsors_only', 'lead_magnet_only', 'none'):
        check(f"{absent} is not a tier", absent in TIERS, False)


def test_agency_detection():
    print("\nAgency address detection")
    for address in ('themacmaster@ruthlesstalent.com',
                    'vanessa@undercurrent.net',
                    'rose@wylertravelgroup.com',
                    'partnerships@tbnr.work',
                    'strictlydumpling@delkatalents.com'):
        check(f"agency: {address}", is_agency(address), True)

    # A free mailbox is the creator's own however it is named.
    for address in ('jordan.bauth@gmail.com',
                    'adventurefreaksss@gmail.com',
                    'beachlifeandbeyond@outlook.com',
                    'collabnikolaspilates@gmail.com'):
        check(f"direct: {address}", is_agency(address), False)

    # Their own domain is direct too.
    check("own domain", is_agency('contact@allthegear.shop'), False)
    check("empty", is_agency(''), False)


def test_to_int():
    print("\nNumber parsing")
    check("plain", to_int('462000'), 462000)
    check("float text", to_int('462000.0'), 462000)
    check("empty", to_int(''), 0)
    check("None", to_int(None), 0)
    check("junk", to_int('n/a'), 0)


def main():
    test_normalise()
    test_channel_keys_column_names()
    test_exclusion_catches_respelled_channel()
    test_best_rating_wins_dedupe()
    test_product_tiers()
    test_agency_detection()
    test_to_int()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("All tests passed")
    return 0


if __name__ == '__main__':
    sys.exit(main())
