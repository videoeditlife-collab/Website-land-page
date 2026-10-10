#!/usr/bin/env python3
"""
Pull the High-rated creators that sell a real product out of scored lead files.

Every High already has sells_product=True - the spec will not rate a channel
High without it. But sells_product is True for a t-shirt as readily as for a
$500 course, and those are not the same prospect: a creator charging for
knowledge has a margin that pays an editor, where merch mostly does not.

So this sorts the product types into tiers and reports them separately:

    owned     course, digital product, coaching or program - the creator sells
              their own knowledge, at a price they set. Best prospects.
    recurring community or membership - Patreon, Skool, channel memberships.
              Real recurring revenue, usually smaller per head.
    merch     print-on-demand and stores. Weakest signal of budget.

    python pick_sellers.py results/martial_leads.csv
    python pick_sellers.py results/*.csv --tier owned --min-subs 20000
"""

import argparse
import csv
import glob
import sys

TIERS = {
    'course': 'owned',
    'digital_product': 'owned',
    'coaching_or_program': 'owned',
    'community_or_membership': 'recurring',
    'merch': 'merch',
}

TIER_ORDER = ['owned', 'recurring', 'merch']

# Addresses at a talent agency, management company or media firm are not the
# creator. They also say the creator already has a team, which usually means
# an editor - so these are the weakest leads in an otherwise strong row.
AGENCY_HINTS = (
    'talent', 'management', 'mgmt', 'media', 'agency', 'partnerships',
    'inquiries@', 'collab', 'brand', 'wyler', 'undercurrent', 'dovora',
    'delka', 'ruthless', 'tbnr',
)


def is_agency(email):
    low = (email or '').lower()
    if not low or '@' in low[:1]:
        return False
    domain = low.split('@')[-1]
    # A free mailbox is the creator's own however it is named.
    if domain in ('gmail.com', 'outlook.com', 'hotmail.com', 'yahoo.com',
                  'icloud.com', 'protonmail.com', 'me.com'):
        return False
    return any(h in low for h in AGENCY_HINTS)


def channel_keys(path):
    """
    Every channel this file names, normalised for comparison.

    Handles both shapes in results/: scored CSVs with a Channel Link column,
    and the plain URL lists the discovery passes save.
    """
    keys = set()
    try:
        handle = open(path, newline='', encoding='utf-8')
    except OSError as exc:
        print(f"exclude: skipped {path}: {exc}", file=sys.stderr)
        return keys

    with handle:
        if path.lower().endswith('.csv'):
            for row in csv.DictReader(handle):
                # The column has been called four different things across the
                # passes. Reading only 'Channel Link' silently matched nothing
                # in every file written before the ROTI work, which is most of
                # what has already been reported - so an exclusion built from
                # them would have excluded nobody.
                for column in ('Channel Link', 'YT Channel', 'channel_url',
                               'Credited By', 'Handle', 'Channel'):
                    key = normalise(row.get(column))
                    if key:
                        keys.add(key)
                        break
        else:
            for line in handle:
                key = normalise(line)
                if key:
                    keys.add(key)
    return keys


def normalise(url):
    """
    A channel URL reduced to something two files can be compared on.

    The same channel is written several ways across these files - with and
    without www, as /@handle or /channel/UC..., sometimes with a /videos or
    /about tab still attached - so comparing raw strings would let a channel
    through the exclusion simply because it was spelled differently.
    """
    url = (url or '').strip().lower().rstrip('/')
    if not url:
        return ''
    # Some files store only the @handle. Expanding it to the canonical URL
    # lets those files take part in the exclusion rather than matching nothing.
    if url.startswith('@') and ' ' not in url:
        url = 'https://www.youtube.com/' + url
    if not url.startswith('http'):
        return ''
    for tab in ('/about', '/videos', '/featured', '/streams', '/shorts',
                '/playlists', '/community'):
        if url.endswith(tab):
            url = url[:-len(tab)]
    url = url.replace('://m.youtube.com', '://www.youtube.com')
    url = url.replace('://youtube.com', '://www.youtube.com')
    return url.split('?')[0].rstrip('/')


def to_int(value):
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


RATING_RANK = {'High': 3, 'Mid': 2, 'Low': 1, '': 0}


def load(paths):
    """
    Every scored row, one per channel, keeping the strongest rating.

    The passes overlap - a search for camping trips and a search for challenge
    formats both reach the same gear channel - and the same channel does not
    always score the same twice: each pass reads a different sample of recent
    videos, and the niche keyword lists were widened between passes. All The
    Gear came back Mid in the challenge pass and High in the outdoor pass.

    First-wins dedupe therefore threw away the better-informed score, silently.
    Ranking by rating keeps the High, and a later pass breaks a tie because it
    ran against the wider keyword lists.
    """
    rows = {}
    for pattern in paths:
        for path in sorted(glob.glob(pattern)):
            try:
                handle = open(path, newline='', encoding='utf-8')
            except OSError as exc:
                print(f"skipped {path}: {exc}", file=sys.stderr)
                continue
            with handle:
                for row in csv.DictReader(handle):
                    key = (row.get('Channel Link') or '').strip().lower()
                    if not key:
                        continue
                    row['source_file'] = path.rsplit('/', 1)[-1]
                    held = rows.get(key)
                    if held is None or (RATING_RANK.get(row.get('Value Rating'), 0)
                                        >= RATING_RANK.get(held.get('Value Rating'), 0)):
                        rows[key] = row
    return list(rows.values())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('sources', nargs='+', help='Scored lead CSVs (globs ok)')
    parser.add_argument('--tier', choices=TIER_ORDER,
                        help='Only this product tier (default: all three)')
    parser.add_argument('--min-subs', type=int, default=0)
    parser.add_argument('--max-subs', type=int, default=0)
    parser.add_argument('--limit', type=int, default=0,
                        help='Report only the first N, best first')
    parser.add_argument('--email-only', action='store_true',
                        help='Only rows with a published address')
    parser.add_argument('--direct-only', action='store_true',
                        help='Drop talent-agency and management addresses')
    parser.add_argument('--exclude', action='append', default=[],
                        help='CSV or txt of channels to leave out, repeatable '
                             '(globs ok). Use for creators already reported.')
    parser.add_argument('--output', help='Write the selection to a CSV')
    args = parser.parse_args()

    rows = load(args.sources)
    if not rows:
        print("no rows read", file=sys.stderr)
        return 1

    excluded = set()
    for pattern in args.exclude:
        for path in sorted(glob.glob(pattern)):
            excluded |= channel_keys(path)
    if args.exclude:
        print(f"excluding {len(excluded)} channels already reported",
              file=sys.stderr)

    picked = []
    skipped_seen = 0
    for row in rows:
        if excluded and normalise(row.get('Channel Link')) in excluded:
            skipped_seen += 1
            continue
        if row.get('Value Rating') != 'High':
            continue
        tier = TIERS.get((row.get('Product Type') or '').strip())
        if not tier:
            continue
        if args.tier and tier != args.tier:
            continue
        subs = to_int(row.get('Subscriber Count'))
        if args.min_subs and subs < args.min_subs:
            continue
        if args.max_subs and subs > args.max_subs:
            continue
        email = (row.get('Email') or '').strip()
        if args.email_only and not email:
            continue
        agency = is_agency(email)
        if args.direct_only and agency:
            continue
        row['product_tier'] = tier
        row['email_is_agency'] = 'Yes' if agency else ''
        picked.append(row)

    # Best first: owned product over membership over merch, then by the median
    # views that decide whether the audience is actually watching.
    picked.sort(key=lambda r: (TIER_ORDER.index(r['product_tier']),
                               -to_int(r.get('median_views'))))
    if args.limit:
        picked = picked[:args.limit]

    for tier in TIER_ORDER:
        group = [r for r in picked if r['product_tier'] == tier]
        if not group:
            continue
        print(f"\n=== {tier.upper()} ({len(group)}) ===")
        for row in group:
            flag = ' [AGENCY EMAIL]' if row['email_is_agency'] else ''
            print(f"{row.get('Creator Name','')} | {row.get('Channel Link','')}")
            print(f"    {to_int(row.get('Subscriber Count')):,} subs | "
                  f"{to_int(row.get('median_views')):,} median views | "
                  f"{row.get('Niche','')} | {row.get('Product Type','')}"
                  f" | {row.get('product_price_seen') or 'no price seen'}")
            print(f"    uploads/90d {row.get('uploads_90d','')} | "
                  f"last upload {row.get('days_since_last_upload','')}d ago | "
                  f"niche {row.get('niche_consistency','')}")
            print(f"    {email_or_dash(row)}{flag}")

    print(f"\n{len(picked)} selected from {len(rows)} scored rows"
          + (f", {skipped_seen} already reported" if skipped_seen else ""))

    if args.output:
        columns = list(picked[0].keys()) if picked else []
        with open(args.output, 'w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=columns,
                                    extrasaction='ignore')
            writer.writeheader()
            writer.writerows(picked)
        print(f"-> {args.output}")

    return 0


def email_or_dash(row):
    return (row.get('Email') or '').strip() or 'no published email'


if __name__ == '__main__':
    sys.exit(main())
