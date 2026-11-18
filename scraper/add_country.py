#!/usr/bin/env python3
"""
Add each creator's country to a shortlist, and keep only the countries wanted.

The scoring pass (run_lead_generator.py) does not record a country. The
discovery scraper (youtube_scraper.py) does: its CSV has a Country column,
read from the channel's About page. This joins the two.

    python add_country.py picked.csv \
        --countries-from "results/*_channels.csv" \
        --keep "United States,United Kingdom,Canada,Australia,New Zealand,Ireland,South Africa" \
        --output picked_english.csv \
        --missing need_country.txt

Channels with no country on record are written to --missing. Run the scraper
over that file to read their About pages, then run this again with the new
CSV added to --countries-from:

    python youtube_scraper.py --input need_country.txt --min-subscribers 0 \
        --skip-uploads --output probe.csv

A channel can still come back with no country: YouTube only shows one if the
creator set it. Those are kept or dropped by --unknown (default: drop, and
listed so they can be checked by hand).
"""

import argparse
import csv
import glob
import sys

from pick_sellers import normalise

URL_COLUMNS = ('Channel Link', 'YT Channel', 'channel_url', 'Channel URL')


def row_key(row):
    for column in URL_COLUMNS:
        key = normalise(row.get(column))
        if key:
            return key
    return ''


def load_countries(patterns):
    """channel -> country, from any CSV with a Country column."""
    countries = {}
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            with open(path, newline='', encoding='utf-8') as handle:
                for row in csv.DictReader(handle):
                    country = (row.get('Country') or row.get('country') or '').strip()
                    key = row_key(row)
                    # A later file fills a gap but never overwrites a country.
                    if key and country and key not in countries:
                        countries[key] = country
    return countries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', help='Shortlist CSV, e.g. from pick_sellers.py --output')
    parser.add_argument('--countries-from', action='append', default=[],
                        help='CSV(s) with a Country column, globs ok, repeatable')
    parser.add_argument('--keep', default='',
                        help='Comma-separated countries to keep (default: keep all)')
    parser.add_argument('--unknown', choices=['drop', 'keep'], default='drop',
                        help='What to do with channels that have no country')
    parser.add_argument('--output', required=True)
    parser.add_argument('--missing', help='Write channels with no country here')
    args = parser.parse_args()

    countries = load_countries(args.countries_from)
    keep = {c.strip().lower() for c in args.keep.split(',') if c.strip()}

    with open(args.source, newline='', encoding='utf-8') as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        print("no rows in source", file=sys.stderr)
        return 1

    kept, wrong, missing = [], [], []
    for row in rows:
        country = countries.get(row_key(row), '')
        row['country'] = country
        if not country:
            missing.append(row)
            if args.unknown == 'keep':
                kept.append(row)
        elif not keep or country.lower() in keep:
            kept.append(row)
        else:
            wrong.append(row)

    fields = list(rows[0].keys())
    with open(args.output, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(kept)

    if args.missing:
        with open(args.missing, 'w', encoding='utf-8') as handle:
            for row in missing:
                handle.write(row_key(row) + '\n')

    print(f"{len(rows)} rows: {len(kept)} kept, {len(wrong)} outside the "
          f"countries wanted, {len(missing)} with no country"
          + (f" (kept)" if args.unknown == 'keep' else " (dropped)"))
    for row in wrong:
        print(f"  dropped  {row.get('Creator Name', '')} - {row['country']}")
    for row in missing:
        print(f"  unknown  {row.get('Creator Name', '')} - {row_key(row)}")
    print(f"-> {args.output}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
