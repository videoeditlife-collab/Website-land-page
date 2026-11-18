#!/usr/bin/env python3
"""
Find the creators that missed a High rating by one test, narrowly.

High needs all four of: 10+ uploads in 90 days, a video in the last 30 days,
niche consistency of 0.6+, and median views of 3,000+ - on top of selling a
product. A creator who posts 9 times a quarter with 40,000 median views is
rated Mid, the same as one posting twice to 400 people, and the first is
often a better prospect than a weak High.

This picks out the Mid rows that sell a product and fail exactly one test,
by a small margin, so a list that comes up short can be topped up honestly.
Each row says which test it missed, so the shortfall is visible when it is
reported.

    python near_misses.py "results/*_leads.csv" \
        --exclude results/sent.txt --niche outdoors --output near.csv

The margins are flags: --uploads-min 8 accepts 8 or 9 uploads, --median-min
2500 accepts 2,500-2,999 median views, and so on.
"""

import argparse
import csv
import glob
import sys

from pick_sellers import TIERS, TIER_ORDER, channel_keys, is_agency, load, normalise, to_int


def miss_reasons(row, args):
    """The High tests this row failed, each marked narrow or not."""
    uploads = to_int(row.get('uploads_90d'))
    median = to_int(row.get('median_views'))
    days = row.get('days_since_last_upload')
    days = to_int(days) if str(days or '').strip() else 999
    try:
        niche = float(row.get('niche_consistency') or 0)
    except ValueError:
        niche = 0.0

    misses = []
    if uploads < 10:
        misses.append((f"{uploads} uploads in 90 days (needs 10)",
                       uploads >= args.uploads_min))
    if days > 30:
        misses.append((f"last upload {days} days ago (needs 30 or fewer)",
                       days <= args.days_max))
    if niche < 0.6:
        misses.append((f"niche consistency {niche:.2f} (needs 0.6)",
                       niche >= args.niche_min))
    if median < 3000:
        misses.append((f"median {median:,} views (needs 3,000)",
                       median >= args.median_min))
    return misses


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('sources', nargs='+', help='Scored lead CSVs (globs ok)')
    parser.add_argument('--exclude', action='append', default=[],
                        help='CSV or txt of channels to leave out, repeatable')
    parser.add_argument('--niche', default='',
                        help='Comma-separated niche labels to keep, e.g. '
                             'finance,business (default: any)')
    parser.add_argument('--tier', choices=TIER_ORDER, action='append',
                        help='Product tiers to keep, repeatable (default: all)')
    parser.add_argument('--uploads-min', type=int, default=8)
    parser.add_argument('--days-max', type=int, default=40)
    parser.add_argument('--niche-min', type=float, default=0.5)
    parser.add_argument('--median-min', type=int, default=2500)
    parser.add_argument('--output', help='Write the near-misses to a CSV')
    args = parser.parse_args()

    excluded = set()
    for pattern in args.exclude:
        for path in sorted(glob.glob(pattern)):
            excluded |= channel_keys(path)
    niches = {n.strip() for n in args.niche.split(',') if n.strip()}

    picked = []
    for row in load(args.sources):
        if row.get('Value Rating') != 'Mid':
            continue
        if normalise(row.get('Channel Link')) in excluded:
            continue
        tier = TIERS.get((row.get('Product Type') or '').strip())
        if not tier or (args.tier and tier not in args.tier):
            continue
        if niches and (row.get('Niche') or '') not in niches:
            continue
        misses = miss_reasons(row, args)
        if len(misses) != 1 or not misses[0][1]:
            continue
        row['product_tier'] = tier
        row['near_miss'] = misses[0][0]
        row['email_is_agency'] = 'Yes' if is_agency(row.get('Email')) else ''
        picked.append(row)

    picked.sort(key=lambda r: -to_int(r.get('Subscriber Count')))
    for row in picked:
        flag = ' [AGENCY EMAIL]' if row['email_is_agency'] else ''
        print(f"{row.get('Creator Name', '')} | {row.get('Channel Link', '')}")
        print(f"    {to_int(row.get('Subscriber Count')):,} subs | "
              f"{to_int(row.get('median_views')):,} median | "
              f"{row.get('Niche', '')} | {row.get('Product Type', '')}")
        print(f"    missed: {row['near_miss']}")
        print(f"    {(row.get('Email') or '').strip() or 'no published email'}{flag}")
    print(f"\n{len(picked)} near-misses")

    if args.output and picked:
        fields = list(picked[0].keys())
        with open(args.output, 'w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(picked)
        print(f"-> {args.output}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
