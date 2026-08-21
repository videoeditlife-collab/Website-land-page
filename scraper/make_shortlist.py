#!/usr/bin/env python3
"""
Filter a results CSV down to the channels worth approaching.

Keeps rows whose Status is 'ok' (inside the subscriber band, consistent
uploads, not a tour operator), sorted by subscriber count.

    python make_shortlist.py results.csv shortlist.csv
    python make_shortlist.py results.csv shortlist.csv --max-subscribers 200000
"""

import argparse
import csv
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('destination')
    parser.add_argument('--status', default='ok',
                        help="Status to keep (default: ok)")
    parser.add_argument('--max-subscribers', type=int, default=0,
                        help='Optional extra ceiling applied when shortlisting')
    parser.add_argument('--include-unclear', action='store_true',
                        help="Also keep rows whose Type is 'unclear'")
    args = parser.parse_args()

    try:
        with open(args.source, newline='', encoding='utf-8') as handle:
            rows = list(csv.DictReader(handle))
    except FileNotFoundError:
        print(f"No such file: {args.source}", file=sys.stderr)
        return 1

    if not rows:
        print("No rows to shortlist", file=sys.stderr)
        return 1

    kept = [r for r in rows if (r.get('Status') or '') == args.status]

    if args.max_subscribers:
        kept = [
            r for r in kept
            if (r.get('YT Subscribers') or '').isdigit()
            and int(r['YT Subscribers']) <= args.max_subscribers
        ]

    if not args.include_unclear:
        kept = [r for r in kept if (r.get('Type') or '') != 'unclear']

    kept.sort(key=lambda r: -int(r.get('YT Subscribers') or 0))

    with open(args.destination, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        for index, row in enumerate(kept, 1):
            row['#'] = index
            writer.writerow(row)

    print(f"{len(kept)} of {len(rows)} channels shortlisted -> {args.destination}",
          file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
